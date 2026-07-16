"""Parse and resolve the plugin skip-list used by the CI test stages."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Callable, Iterable, Sequence


SKIP_LIST_ENV_VAR = "PLUGIN_TESTS_PLUGINS_TO_SKIP"
_SEPARATOR_RE = re.compile(r"[,\s]+")
_DISTRIBUTION_NORMALIZATION_RE = re.compile(r"[-_.]+")


@dataclass(frozen=True)
class PluginIdentity:
    """The import-module and distribution names of an installed plugin."""

    module_name: str
    distribution_name: str | None


@dataclass(frozen=True)
class SkipResolution:
    """Requested selectors split into installed matches and unknown values."""

    requested: tuple[str, ...]
    matched: tuple[PluginIdentity, ...]
    unknown: tuple[str, ...]

    @property
    def matched_module_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(plugin.module_name for plugin in self.matched))


def parse_plugin_skip_list(value: str | None) -> tuple[str, ...]:
    """Parse canonical comma-separated or legacy whitespace-separated selectors."""
    if not value or not value.strip():
        return ()

    # dict preserves configuration order while removing duplicate selectors.
    return tuple(dict.fromkeys(_SEPARATOR_RE.split(value.strip())))


def normalize_distribution_name(name: str) -> str:
    """Apply the Python packaging name-normalization rules used for lookup."""
    return _DISTRIBUTION_NORMALIZATION_RE.sub("-", name).lower()


def resolve_skip_selectors(
    selectors: Sequence[str], plugins: Iterable[PluginIdentity]
) -> SkipResolution:
    """Resolve selectors against installed module and distribution names."""
    installed = tuple(plugins)
    matched: list[PluginIdentity] = []
    unknown: list[str] = []

    for selector in selectors:
        selector_matches = [
            plugin
            for plugin in installed
            if selector == plugin.module_name
            or (
                plugin.distribution_name is not None
                and normalize_distribution_name(selector)
                == normalize_distribution_name(plugin.distribution_name)
            )
        ]
        if not selector_matches:
            unknown.append(selector)
            continue
        for plugin in selector_matches:
            if plugin not in matched:
                matched.append(plugin)

    return SkipResolution(tuple(selectors), tuple(matched), tuple(unknown))


def plugin_module_is_skipped(module_name: str, resolution: SkipResolution) -> bool:
    """Match an example-upload package to an already resolved module exactly."""
    return module_name in resolution.matched_module_names


def format_plugin_identities(plugins: Iterable[PluginIdentity]) -> str:
    """Format actual module and distribution names for user-facing reports."""
    return ", ".join(
        (
            f"{plugin.module_name} ({plugin.distribution_name})"
            if plugin.distribution_name
            else f"{plugin.module_name} (<unknown distribution>)"
        )
        for plugin in plugins
    )


def format_skip_resolution(
    resolution: SkipResolution, *, context: str | None = None
) -> tuple[str, str]:
    """Format requested selectors and installed matches consistently."""
    suffix = f" for {context}" if context else ""
    return (
        f"Requested plugin skip selectors{suffix}: "
        + (", ".join(resolution.requested) or "<none>"),
        f"Matched plugin packages{suffix}: "
        + (format_plugin_identities(resolution.matched) or "<none>"),
    )


def format_unknown_selector_error(
    resolution: SkipResolution, plugins: Iterable[PluginIdentity]
) -> str:
    """Describe the full resolution state when any selector is unknown."""
    requested, matched = format_skip_resolution(resolution)
    available = format_plugin_identities(plugins) or "<none>"
    return (
        requested
        + "\n"
        + matched
        + "\nUnknown plugin skip selectors: "
        + ", ".join(resolution.unknown)
        + "\nInstalled plugin names: "
        + available
    )


def discover_plugin_identities() -> tuple[PluginIdentity, ...]:
    """Discover the same ``nomad.plugin`` entry points used by the test tool."""
    discovered: list[PluginIdentity] = []
    for entry_point in entry_points(group="nomad.plugin"):
        module_name = entry_point.value.split(":", 1)[0].split(".", 1)[0]
        distribution_name = (
            entry_point.dist.metadata.get("Name") if entry_point.dist else None
        )
        identity = PluginIdentity(
            module_name=module_name,
            distribution_name=distribution_name,
        )
        if identity not in discovered:
            discovered.append(identity)
    return tuple(discovered)


def build_plugin_test_command(resolution: SkipResolution) -> list[str]:
    """Build the external command from resolved module names only."""
    return [
        "nomad-plugin-tests",
        "--plugins-to-skip",
        ",".join(resolution.matched_module_names),
    ]


def run_plugin_tests(
    value: str | None = None,
    *,
    plugins: Iterable[PluginIdentity] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Validate selectors, report actual matches, and run plugin unit tests."""
    selectors = parse_plugin_skip_list(
        os.getenv(SKIP_LIST_ENV_VAR) if value is None else value
    )
    installed = discover_plugin_identities() if plugins is None else tuple(plugins)
    resolution = resolve_skip_selectors(selectors, installed)

    if resolution.unknown:
        print(
            format_unknown_selector_error(resolution, installed),
            file=sys.stderr,
            flush=True,
        )
        return 2

    for line in format_skip_resolution(resolution):
        print(line, flush=True)

    completed = runner(build_plugin_test_command(resolution), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(run_plugin_tests())
