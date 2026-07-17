# Testing the plugin skip-selector release candidate

The `QEDeD/nomad-uibk-image` branch `upgrade_to_1.4.3` contains the complete
repository-level fix for `PLUGIN_TESTS_PLUGINS_TO_SKIP`. It is designed to be
tested without merging it into an existing checkout.

The expected candidate commit is
`bf9c8e079453dc504fda585fde9ac954141fb346` or a documented descendant of it.

## Run the complete stack on GitHub

1. Open the [Actions page](https://github.com/QEDeD/nomad-uibk-image/actions).
2. If GitHub displays its fork safety prompt, select **I understand my
   workflows, go ahead and enable them**. This is a one-time fork setting.
3. Select **Build and publish docker images**, then **Run workflow**.
4. Choose branch `upgrade_to_1.4.3`.
5. Enter `nomad-pvcomb` and run the workflow. This installed distribution name
   must resolve exactly to module `nomad_pvcomb`, and the complete workflow is
   expected to pass.

To exercise strict configuration validation separately, run it again with
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
  nomad-plugin-tests --plugins-to-skip \
  'simulationworkflowschema nomad-pvcomb'
```

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
PLUGIN_TESTS_PLUGINS_TO_SKIP='nomad-pvcomb' \
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

## Test only the reusable `nomad-plugin-tests` candidate

An existing NOMAD distribution can exercise the public fork prerelease without
adopting the template changes. Run this from the distribution root:

```sh
uv run \
  --with 'nomad-plugin-tests @ https://github.com/QEDeD/nomad-plugin-tests/releases/download/v0.3.0-qeded.1/nomad_plugin_tests-0.3.0-py3-none-any.whl' \
  nomad-plugin-tests \
  --plugins-to-skip 'simulationworkflowschema nomad-pvcomb'
```

For a source-based immutable pin, use commit
`1439e997ccc1c1200171f43a75f8566ed15329dc` instead:

```sh
uv run \
  --with 'nomad-plugin-tests @ git+https://github.com/QEDeD/nomad-plugin-tests.git@1439e997ccc1c1200171f43a75f8566ed15329dc' \
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
