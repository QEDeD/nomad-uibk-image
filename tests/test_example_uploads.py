import os
import sys
import time

from typing import TYPE_CHECKING

import pytest
from nomad.config import config
from conftest import (
    get_nomad_api,
    get_request,
    make_request_with_retry,
    post_request,
)
from nomad_plugin_tests.plugin_selection import (
    discover_plugin_identities,
    format_actually_skipped,
    format_requested_and_matched,
    format_unknown_selector_error,
    parse_plugin_skip_list,
    plugin_module_is_skipped,
    resolve_skip_selectors,
    select_identities_by_module,
)

if TYPE_CHECKING:
    from nomad.config.models.plugins import ExampleUploadEntryPoint


SKIP_LIST_ENV_VAR = "PLUGIN_TESTS_PLUGINS_TO_SKIP"


def get_example_upload_entrypoints() -> list["ExampleUploadEntryPoint"]:
    """
    Retrieves information about example upload entrypoints
    """
    get_nomad_api()
    config.load_plugins()
    if not config.plugins:
        return []

    example_uploads = [
        entry_point
        for entry_point in config.plugins.entry_points.filtered_values()
        if entry_point.entry_point_type == "example_upload"
    ]

    return example_uploads


def get_example_upload_ids() -> list[str]:
    installed_plugins = discover_plugin_identities()
    resolution = resolve_skip_selectors(
        parse_plugin_skip_list(os.getenv(SKIP_LIST_ENV_VAR)), installed_plugins
    )
    if resolution.unknown:
        raise ValueError(
            format_unknown_selector_error(
                resolution,
                installed_plugins,
                context="example upload tests",
            )
        )

    if resolution.requested:
        for line in format_requested_and_matched(
            resolution, context="example upload tests"
        ):
            print(line, file=sys.stderr, flush=True)

    eligible_entry_points = [
        entry_point
        for entry_point in get_example_upload_entrypoints()
        if entry_point.id and not entry_point.from_examples_directory
    ]
    skipped_module_names = {
        entry_point.plugin_package
        for entry_point in eligible_entry_points
        if entry_point.plugin_package
        and plugin_module_is_skipped(entry_point.plugin_package, resolution)
    }
    actually_skipped = select_identities_by_module(
        resolution.matched, skipped_module_names
    )
    if resolution.requested:
        print(
            format_actually_skipped(actually_skipped, context="example upload tests"),
            file=sys.stderr,
            flush=True,
        )

    return [
        entry_point.id
        for entry_point in eligible_entry_points
        if not plugin_module_is_skipped(entry_point.plugin_package or "", resolution)
    ]


@pytest.mark.parametrize(
    "entry_point_id",
    get_example_upload_ids(),
    ids=lambda entry_point_id: entry_point_id,
)
def test_example_uploads(entry_point_id, auth):
    url = f"uploads?example_upload_id={entry_point_id}"
    response = make_request_with_retry(post_request, url=url, auth=auth)
    upload_id = response.json().get("upload_id")
    url = f"uploads/{upload_id}"

    timeout = 600
    interval = 10
    start = time.time()
    processing = True

    while processing:
        if time.time() - start > timeout:
            raise TimeoutError("Example upload processing timed out")
        time.sleep(interval)
        url = f"uploads/{upload_id}"
        response = make_request_with_retry(get_request, url=url, auth=auth)
        upload_data = response.json()["data"]
        assert not upload_data["errors"]
        assert not upload_data["warnings"]
        if not upload_data["process_running"]:
            # Check that upload processed fine with no overall errors/warnings
            assert (
                upload_data["process_status"] == "READY"
                or upload_data["process_status"] == "SUCCESS"
            )
            processing = False

    # Check entries for errors
    response = make_request_with_retry(
        post_request, url="entries/query", auth=auth, json={"upload_id": upload_id}
    )

    entry_ids = [entry.entry_id for entry in response.json()["data"]]
    for entry_id in entry_ids:
        url = (f"entries/{entry_id}/archive",)
        response = make_request_with_retry(get_request, url=url, auth=auth)
        logs = response.json()["data"]["archive"]["processing_logs"]
        for log in logs:
            assert log["level"] != "ERROR"
