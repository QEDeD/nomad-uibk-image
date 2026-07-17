# Testing the plugin skip-selector release candidate

The `QEDeD/nomad-uibk-image` branch `upgrade_to_1.4.3` contains the complete
repository-level fix for `PLUGIN_TESTS_PLUGINS_TO_SKIP`. It is designed to be
tested without merging it into an existing checkout.

The distribution pins the accepted PVComb fix at commit
`e1b28bd7ea6e94705031d2884b2a3e056ebc2232` in the public
`QEDeD/nomad-pvcomb` testing mirror.

## Run the complete stack on GitHub

1. Open the [Actions page](https://github.com/QEDeD/nomad-uibk-image/actions).
2. If GitHub displays its fork safety prompt, select **I understand my
   workflows, go ahead and enable them**. This is a one-time fork setting.
3. Select **Build and publish docker images**, then **Run workflow**.
4. Choose branch `upgrade_to_1.4.3`.
5. Leave `plugins_to_skip` empty and run the workflow. The complete workflow must
   execute the installed `nomad-pvcomb` unit tests and pass; a green run that
   skips PVComb does not validate the parser fix.

To exercise selector mapping separately, run with `nomad-pvcomb`. The installed
distribution name must resolve exactly to module `nomad_pvcomb` and be reported
as actually skipped. This is a selector diagnostic, not the primary full-stack
test.

To exercise strict configuration validation separately, run with
`simulationworkflowschema,nomad-pvcomb`. In the upgraded environment,
`simulationworkflowschema` is not installed. The plugin-test jobs must exit 2,
report `nomad-pvcomb -> nomad_pvcomb` as the successful match, and identify only
`simulationworkflowschema` as unknown. They must not claim the combined raw
string was skipped.

The workflow uses its repository-scoped `GITHUB_TOKEN`; it does not require a
user-defined secret. It builds the candidate app, Jupyter, and action images,
starts the service stack from `tests/docker-compose.yml`, and runs plugin unit,
example-upload, and application-entry-point tests from the `tests` directory.
Running from that directory is significant because NOMAD loads the test API URL
and the `test/password` credentials from `tests/nomad.yaml`.

## Test beside an existing upstream checkout

First confirm that the existing checkout has no work that would be confused with
the trial:

```sh
git status --short
```

Add the QEDeD fork as a read-only source and create a separate worktree:

```sh
git remote add qeded https://github.com/QEDeD/nomad-uibk-image.git
git fetch qeded upgrade_to_1.4.3
git worktree add ../nomad-uibk-image-qeded-test qeded/upgrade_to_1.4.3
cd ../nomad-uibk-image-qeded-test
git rev-parse HEAD
```

If a `qeded` remote already exists, omit the `git remote add` command. The
original checkout and its current branch remain untouched.

### Focused checks without Docker

```sh
uv sync --frozen --extra plugins --group test
uv run --frozen --extra plugins --group test pytest -q tests/test_plugin_skip.py
uv run --frozen --extra plugins --group test \
  nomad-plugin-tests --plugins-to-skip ''
uv run --frozen --extra plugins --group test \
  nomad-plugin-tests --plugins-to-skip \
  'simulationworkflowschema nomad-pvcomb'
```

The empty-selector command must run PVComb rather than reporting it as skipped.
The final command must either resolve both installed identities exactly or exit
with status 2 and name only the unavailable selector. It must not report the raw
two-selector input as successfully skipped.

### Full local Docker-stack checks

These commands require Docker with Compose support and enough resources for the
NOMAD test services:

```sh
docker build --build-arg UV_VERSION=0.9 --target final --tag qeded-nomad-app .
docker build --build-arg UV_VERSION=0.9 --target jupyter --tag qeded-nomad-jupyter .
uv sync --frozen --extra plugins --group test
cd tests
APP_IMAGE=qeded-nomad-app JUPYTER_IMAGE=qeded-nomad-jupyter \
  docker compose up -d --wait
PLUGIN_TESTS_PLUGINS_TO_SKIP='' \
  ../.venv/bin/python -m pytest -p no:warnings -sv
docker compose down --volumes
```

Run `docker compose down --volumes` after a failed test as well. The full test
command must be started from `tests/`; running it from the repository root does
not load `tests/nomad.yaml` and can therefore produce misleading authentication
failures.

The `nomad-plugin-tests` CLI is the inverse: run it from the distribution root,
where it can read `pyproject.toml`. Only the service-backed pytest command runs
from `tests/`.

## Test the fixed PVComb revision in an existing distribution

Use a temporary branch or worktree so the trial does not alter the existing
installation. Replace its PVComb requirement with this immutable source:

```toml
"nomad-pvcomb @ git+https://github.com/QEDeD/nomad-pvcomb.git@e1b28bd7ea6e94705031d2884b2a3e056ebc2232",
```

If another installed plugin declares PVComb from the upstream GitLab URL, add
the same requirement as a root-level uv override as well:

```toml
[tool.uv]
override-dependencies = [
  "nomad-pvcomb @ git+https://github.com/QEDeD/nomad-pvcomb.git@e1b28bd7ea6e94705031d2884b2a3e056ebc2232",
]
```

Merge `override-dependencies` into an existing `[tool.uv]` table instead of
declaring that table twice. The override is required in this distribution
because `nomad-uibk-plugin` still declares PVComb from the upstream URL.

Then regenerate and verify the environment from the distribution root:

```sh
uv lock
uv sync --frozen --extra plugins --group test
uv run --frozen --extra plugins --group test \
  nomad-plugin-tests --plugins-to-skip ''
```

The output must include `nomad_pvcomb` among the packages whose tests ran and
must not list it under requested, matched, or actually skipped identities. For a
full distribution check, run that repository's Docker-backed workflow with the
skip input empty.

To revert, discard only the temporary worktree or restore its `pyproject.toml`
and lockfile to their original revision. Do not reuse the trial lockfile after
restoring the upstream dependency.

## Test only the reusable `nomad-plugin-tests` candidate

An existing NOMAD distribution can exercise the public fork prerelease without
adopting the template changes. Run this from the distribution root:

```sh
uv run \
  --with 'nomad-plugin-tests @ https://github.com/QEDeD/nomad-plugin-tests/releases/download/v0.3.0-qeded.2/nomad_plugin_tests-0.3.0-py3-none-any.whl' \
  nomad-plugin-tests \
  --plugins-to-skip 'simulationworkflowschema nomad-pvcomb'
```

For a source-based immutable pin, use commit
`6619c2ce509988e302d4d1fab0fcebe20e4e1487` instead:

```sh
uv run \
  --with 'nomad-plugin-tests @ git+https://github.com/QEDeD/nomad-plugin-tests.git@6619c2ce509988e302d4d1fab0fcebe20e4e1487' \
  nomad-plugin-tests \
  --plugins-to-skip 'simulationworkflowschema nomad-pvcomb'
```

This isolates the CLI parser, normalization, strict unknown-selector policy, and
reporting. Testing example-upload filtering additionally requires the template
or `nomad-uibk-image` repository changes because that consumer lives outside the
CLI package.

## Remove the side-by-side trial

Return to the original checkout and remove only the temporary worktree:

```sh
git worktree remove ../nomad-uibk-image-qeded-test
```
