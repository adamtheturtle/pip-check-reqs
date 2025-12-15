"""Tests for `find_missing_reqs.py`."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pip  # This happens to be installed in the test environment.
import pytest

from pip_check_reqs import common, find_missing_reqs


def test_find_missing_reqs(tmp_path: Path) -> None:
    installed_imported_not_required_package = pytest
    installed_imported_required_package = pip

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        textwrap.dedent(
            f"""\
            not_installed_package_12345==1
            {installed_imported_required_package.__name__}
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

            import {installed_imported_not_required_package.__name__}
            import {installed_imported_required_package.__name__}
            """,
        ),
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )
    expected_result = [
        (
            installed_imported_not_required_package.__name__,
            [
                common.FoundModule(
                    modname=installed_imported_not_required_package.__name__,
                    filename=Path(
                        installed_imported_not_required_package.__file__,
                    ).parent,
                    locations=[(str(source_file), 3)],
                ),
            ],
        ),
    ]
    assert result == expected_result


def test_main_failure(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    # We need to import something which is installed.
    # We choose `pytest` because we know it is installed.
    source_file.write_text("import pytest")

    caplog.set_level(logging.WARNING)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    assert excinfo.value.code == 1

    assert caplog.records[0].message == "Missing requirements:"
    assert (
        caplog.records[1].message
        == f"{source_file}:1 dist=pytest module=pytest"
    )


def test_main_no_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main(arguments=[])

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith("error: no source files or directories specified\n")


@pytest.mark.parametrize(
    ("verbose_cfg", "debug_cfg", "expected_log_levels"),
    [
        (False, False, {logging.WARNING}),
        (True, False, {logging.INFO, logging.WARNING}),
        (False, True, {logging.DEBUG, logging.INFO, logging.WARNING}),
        (True, True, {logging.DEBUG, logging.INFO, logging.WARNING}),
    ],
)
def test_logging_config(
    *,
    caplog: pytest.LogCaptureFixture,
    verbose_cfg: bool,
    debug_cfg: bool,
    expected_log_levels: set[int],
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    arguments = [str(source_dir)]
    if verbose_cfg:
        arguments.append("--verbose")
    if debug_cfg:
        arguments.append("--debug")

    find_missing_reqs.main(arguments=arguments)

    for event in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warn"),
    ]:
        find_missing_reqs.log.log(*event)

    log_levels = {r.levelno for r in caplog.records}
    assert log_levels == expected_log_levels


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        find_missing_reqs.main(arguments=["--version"])

    assert capsys.readouterr().out == common.version_info() + "\n"


def test_backports_namespace_false_positive(tmp_path: Path) -> None:
    """Test that namespace packages don't cause false positives.

    Regression test for issue #397.
    """
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text("# No backports requirements\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    source_file.write_text(
        textwrap.dedent(
            """\
            try:
                from backports.ssl_match_hostname import match_hostname
            except ImportError:
                HAS_MATCH_HOSTNAME = False
            """,
        ),
    )

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=requirements_file,
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )

    assert result == []
