"""Tests for `find_extra_reqs.py`."""

from __future__ import annotations

import logging
import textwrap
from typing import TYPE_CHECKING

import pip  # This happens to be installed in the test environment.
import pytest

from pip_check_reqs import common, find_extra_reqs

if TYPE_CHECKING:
    from pathlib import Path


def test_find_extra_reqs(tmp_path: Path) -> None:
    installed_not_imported_required_package = pytest
    installed_imported_required_package = pip

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        textwrap.dedent(
            f"""\
            not_installed_package_12345==1
            {installed_imported_required_package.__name__}
            {installed_not_imported_required_package.__name__}
            """,
        ),
    )

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    source_file.write_text(
        textwrap.dedent(
            f"""\
            import pprint

            import {installed_imported_required_package.__name__}
            """,
        ),
    )

    result = find_extra_reqs.find_extra_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=False,
    )
    expected_result = [
        "not-installed-package-12345",
        installed_not_imported_required_package.__name__,
    ]
    assert sorted(result) == sorted(expected_result)


def test_main_failure(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("extra")

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1

    assert caplog.records[0].message == "Extra requirements:"
    assert caplog.records[1].message == f"extra in {requirements_file}"


def test_main_no_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(arguments=[])

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith("error: no source files or directories specified\n")


@pytest.mark.parametrize(
    ("expected_log_levels", "verbose_cfg", "debug_cfg"),
    [
        ({logging.WARNING}, False, False),
        ({logging.INFO, logging.WARNING}, True, False),
        ({logging.DEBUG, logging.INFO, logging.WARNING}, False, True),
        ({logging.DEBUG, logging.INFO, logging.WARNING}, True, True),
    ],
)
def test_logging_config(
    caplog: pytest.LogCaptureFixture,
    expected_log_levels: set[int],
    tmp_path: Path,
    *,
    verbose_cfg: bool,
    debug_cfg: bool,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    arguments = [str(source_dir), "--requirements", str(requirements_file)]
    if verbose_cfg:
        arguments.append("--verbose")
    if debug_cfg:
        arguments.append("--debug")

    find_extra_reqs.main(arguments=arguments)

    for event in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
    ]:
        find_extra_reqs.log.log(*event)

    log_levels = {r.levelno for r in caplog.records}
    assert log_levels == expected_log_levels


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        find_extra_reqs.main(arguments=["--version"])

    assert capsys.readouterr().out == common.version_info() + "\n"
