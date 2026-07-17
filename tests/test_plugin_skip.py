from subprocess import CompletedProcess
from pathlib import Path

import pytest

from plugin_skip import (
    PluginIdentity,
    build_plugin_test_command,
    format_skip_resolution,
    format_unknown_selector_error,
    normalize_distribution_name,
    parse_plugin_skip_list,
    plugin_module_is_skipped,
    resolve_skip_selectors,
    run_plugin_tests,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ()),
        ("", ()),
        ("plugin", ("plugin",)),
        ("plugin,plugin-extra", ("plugin", "plugin-extra")),
        ("plugin, plugin-extra", ("plugin", "plugin-extra")),
        ("plugin plugin-extra", ("plugin", "plugin-extra")),
        ("plugin\nplugin-extra", ("plugin", "plugin-extra")),
        ("plugin, plugin-extra\nthird", ("plugin", "plugin-extra", "third")),
        ("plugin,plugin,plugin-extra", ("plugin", "plugin-extra")),
        (" \tplugin,plugin-extra\n", ("plugin", "plugin-extra")),
        (
            "simulationworkflowschema nomad-pvcomb",
            ("simulationworkflowschema", "nomad-pvcomb"),
        ),
    ],
)
def test_parse_plugin_skip_list(value, expected):
    assert parse_plugin_skip_list(value) == expected


def test_distribution_name_normalization():
    assert normalize_distribution_name("Nomad_PVComb") == "nomad-pvcomb"
    assert normalize_distribution_name("nomad.pvcomb") == "nomad-pvcomb"


def test_example_matching_uses_resolved_exact_module_names():
    resolution = resolve_skip_selectors(
        ("nomad-schema-plugin-run",),
        (PluginIdentity("runschema", "nomad-schema-plugin-run"),),
    )

    assert plugin_module_is_skipped("runschema", resolution)
    assert not plugin_module_is_skipped("RUNSCHEMA", resolution)
    assert not plugin_module_is_skipped("nomad_schema_plugin_run", resolution)
    assert not plugin_module_is_skipped("runschema-extra", resolution)


def test_distribution_resolution_does_not_conflate_module_names():
    plugins = (
        PluginIdentity("foo_bar", "foo-bar"),
        PluginIdentity("foo.bar", "other-distribution"),
    )
    resolution = resolve_skip_selectors(("foo-bar",), plugins)

    assert resolution.matched_module_names == ("foo_bar",)
    assert plugin_module_is_skipped("foo_bar", resolution)
    assert not plugin_module_is_skipped("foo.bar", resolution)


def test_resolve_module_and_distribution_names_and_report_unknown():
    plugins = (
        PluginIdentity("simulationworkflowschema", "simulation-workflow-schema"),
        PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),
    )

    resolution = resolve_skip_selectors(
        ("simulationworkflowschema", "nomad-pvcomb", "nomad-pvcom"), plugins
    )

    assert resolution.matched == plugins
    assert resolution.matched_module_names == (
        "simulationworkflowschema",
        "nomad_pvcomb",
    )
    assert resolution.unknown == ("nomad-pvcom",)


def test_missing_distribution_name_does_not_create_a_normalized_alias():
    plugins = (PluginIdentity("foo_bar", None),)

    normalized_alias = resolve_skip_selectors(("FOO-BAR",), plugins)
    exact_module = resolve_skip_selectors(("foo_bar",), plugins)

    assert normalized_alias.matched == ()
    assert normalized_alias.unknown == ("FOO-BAR",)
    assert exact_module.matched == plugins
    assert exact_module.unknown == ()


@pytest.mark.parametrize(
    "value, expected_argument",
    [
        ("", ""),
        ("nomad-pvcomb", "nomad_pvcomb"),
        (
            "simulationworkflowschema nomad-pvcomb",
            "simulationworkflowschema,nomad_pvcomb",
        ),
    ],
)
def test_effective_plugin_test_command(value, expected_argument):
    plugins = (
        PluginIdentity("simulationworkflowschema", "simulation-workflow-schema"),
        PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),
    )
    resolution = resolve_skip_selectors(parse_plugin_skip_list(value), plugins)

    assert build_plugin_test_command(resolution) == [
        "nomad-plugin-tests",
        "--plugins-to-skip",
        expected_argument,
    ]


def test_runner_reports_actual_matches(capsys):
    commands = []

    def runner(command, **kwargs):
        commands.append((command, kwargs))
        print("child output")
        return CompletedProcess(command, 0)

    return_code = run_plugin_tests(
        "nomad-pvcomb",
        plugins=(PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),),
        runner=runner,
    )

    assert return_code == 0
    assert commands == [
        (
            ["nomad-plugin-tests", "--plugins-to-skip", "nomad_pvcomb"],
            {"check": False},
        )
    ]
    output = capsys.readouterr()
    assert output.out.splitlines() == [
        "Requested plugin skip selectors: nomad-pvcomb",
        "Matched plugin packages: nomad_pvcomb (nomad-pvcomb)",
        "child output",
    ]


def test_unknown_selector_fails_before_test_tool_runs(capsys):
    def runner(command, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError((command, kwargs))

    return_code = run_plugin_tests(
        "nomad-pvcom",
        plugins=(PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),),
        runner=runner,
    )

    assert return_code == 2
    output = capsys.readouterr()
    assert "Requested plugin skip selectors: nomad-pvcom" in output.err
    assert "Unknown plugin skip selectors: nomad-pvcom" in output.err
    assert "nomad_pvcomb (nomad-pvcomb)" in output.err
    assert output.out == ""


def test_mixed_known_and_unknown_selectors_report_the_successful_match(capsys):
    def runner(command, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError((command, kwargs))

    return_code = run_plugin_tests(
        "simulationworkflowschema nomad-pvcomb",
        plugins=(PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),),
        runner=runner,
    )

    assert return_code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.splitlines() == [
        "Requested plugin skip selectors: simulationworkflowschema, nomad-pvcomb",
        "Matched plugin packages: nomad_pvcomb (nomad-pvcomb)",
        "Unknown plugin skip selectors: simulationworkflowschema",
        "Installed plugin names: nomad_pvcomb (nomad-pvcomb)",
    ]


def test_unknown_selector_error_lists_installed_identities():
    plugins = (PluginIdentity("runschema", "nomad-schema-plugin-run"),)
    resolution = resolve_skip_selectors(("misspelled",), plugins)

    assert format_unknown_selector_error(resolution, plugins) == (
        "Requested plugin skip selectors: misspelled\n"
        "Matched plugin packages: <none>\n"
        "Unknown plugin skip selectors: misspelled\n"
        "Installed plugin names: runschema (nomad-schema-plugin-run)"
    )


def test_unknown_selector_error_formats_missing_distribution_metadata():
    plugins = (PluginIdentity("foo_bar", None),)
    resolution = resolve_skip_selectors(("FOO-BAR",), plugins)

    assert format_unknown_selector_error(resolution, plugins) == (
        "Requested plugin skip selectors: FOO-BAR\n"
        "Matched plugin packages: <none>\n"
        "Unknown plugin skip selectors: FOO-BAR\n"
        "Installed plugin names: foo_bar (<unknown distribution>)"
    )


def test_example_resolution_report_uses_shared_formatter():
    resolution = resolve_skip_selectors(
        ("nomad-pvcomb",),
        (PluginIdentity("nomad_pvcomb", "nomad-pvcomb"),),
    )

    assert format_skip_resolution(resolution, context="example uploads") == (
        "Requested plugin skip selectors for example uploads: nomad-pvcomb",
        "Matched plugin packages for example uploads: nomad_pvcomb (nomad-pvcomb)",
    )


def test_workflow_delegates_skip_handling_to_shared_adapter():
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/docker-publish.yml"
    ).read_text()

    assert "PLUGINS_STRING" not in workflow
    assert "--with" not in workflow
    assert "--group test" in workflow
    assert "--frozen" in workflow
    assert "python tests/plugin_skip.py" in workflow
    assert "uv sync --frozen --extra plugins --group test" in workflow
    assert "uv sync --frozen --all-extras" not in workflow
    assert "pytest -p no:warnings -sv" in workflow
    assert "plugins_to_skip:" in workflow
    assert 'default: "nomad-pvcomb"' in workflow
    assert "${{ inputs.plugins_to_skip || 'nomad-pvcomb' }}" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "${GITHUB_REPOSITORY,,}" in workflow
    assert "${GITHUB_SHA}" in workflow
    assert "steps.manual_meta.outputs.tags || steps.meta.outputs.tags" in workflow
    assert workflow.count("docker compose up -d --quiet-pull --wait") == 1
    assert "docker compose logs --no-color app jupyter" in workflow


def test_jupyter_pyzmq_layer_uses_one_locked_wheel():
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    dockerfile = (root / "Dockerfile").read_text()

    assert '"pyzmq==27.1.0"' in pyproject
    assert 'site-packages/zmq"' in dockerfile
    assert 'uv pip install --system --reinstall --no-deps "pyzmq==27.1.0"' in dockerfile
    assert "assert zmq.__version__ == '27.1.0'" in dockerfile
