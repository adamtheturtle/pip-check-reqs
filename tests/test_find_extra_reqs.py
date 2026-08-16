"""Tests for `find_extra_reqs.py`."""

from __future__ import annotations

import logging
import re
import sys
import textwrap
from pathlib import Path

import pip  # This happens to be installed in the test environment.
import pytest

from pip_check_reqs import common, find_extra_reqs


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
    expected_result = [installed_not_imported_required_package.__name__]
    assert result == expected_result


def test_uninstalled_requirement_is_not_extra(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """An uninstalled requirement is reported as unchecked, not as extra.

    We tell which modules a requirement provides from the files of the
    installed distribution, so we cannot tell whether an uninstalled
    requirement is used, even when the code imports it.
    """
    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("not_installed_package_12345==1\n")

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "source.py"
    source_file.write_text("import not_installed_package_12345\n")

    caplog.set_level(logging.WARNING)

    result = find_extra_reqs.find_extra_reqs(
        requirements_filename=fake_requirements_file,
        paths=[source_dir],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
        ignore_requirements_function=common.ignorer(ignore_cfg=[]),
        skip_incompatible=False,
    )

    assert not result
    expected_message = (
        "not-installed-package-12345 is not installed, so we cannot tell "
        "whether it is used"
    )
    assert [record.message for record in caplog.records] == [expected_message]


def test_main_failure(
    *,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    installed_not_imported_required_package = pytest

    requirements_file = tmp_path / "requirements.txt"
    requirements_file.write_text(
        installed_not_imported_required_package.__name__,
    )

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
    expected_message = (
        f"{installed_not_imported_required_package.__name__} in "
        f"{requirements_file}"
    )
    assert caplog.records[1].message == expected_message


def test_main_no_spec(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(arguments=[])

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith("error: no source files or directories specified\n")


def test_main_missing_requirements_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    requirements_file = tmp_path / "missing-requirements.txt"

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(
        f"error: requirements file not found: {requirements_file}\n",
    )


def test_main_missing_source_path(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()
    source_dir = tmp_path / "missing-source"

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(f"error: source path not found: {source_dir}\n")


def test_main_source_file_parse_error(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "spam.py"
    source_file.write_text(data="def (\n")

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(
            arguments=[
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )

    expected_code = 2
    assert excinfo.value.code == expected_code
    err = capsys.readouterr().err
    assert err.endswith(
        f"error: could not parse {source_file}:1: invalid syntax\n",
    )


def test_main_debug_reraises_input_error(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    requirements_file = tmp_path / "missing-requirements.txt"

    with pytest.raises(
        FileNotFoundError,
        match=re.escape(f"requirements file not found: {requirements_file}"),
    ):
        find_extra_reqs.main(
            arguments=[
                "--debug",
                "--requirements",
                str(requirements_file),
                str(source_dir),
            ],
        )


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
    *,
    caplog: pytest.LogCaptureFixture,
    expected_log_levels: set[int],
    tmp_path: Path,
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


def test_main_warns_when_run_from_another_environment(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pprint")

    # We resolve the path as the warning shows resolved paths, and a
    # temporary directory is reached through a symbolic link on some hosts.
    active_prefix = (tmp_path / "active").resolve()
    monkeypatch.setenv("VIRTUAL_ENV", str(active_prefix))

    find_extra_reqs.main(
        arguments=[
            "--requirements-file",
            str(requirements_file),
            str(source_dir),
        ],
    )

    running_prefix = Path(sys.prefix).resolve()
    expected_stderr = (
        f"WARNING: Running from {running_prefix}, but the active "
        f"virtual environment is {active_prefix}. "
        "Results describe the environment pip-check-reqs is installed in. "
        "Install pip-check-reqs in the active virtual environment, and "
        'run "hash -r" ("rehash" in zsh), to check that environment.\n'
    )
    assert capsys.readouterr().err == expected_stderr


def test_main_does_not_warn_when_run_from_the_active_environment(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirements_file = tmp_path / "requirements.txt"
    requirements_file.touch()

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source.py").write_text("import pprint")

    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)

    find_extra_reqs.main(
        arguments=[
            "--requirements-file",
            str(requirements_file),
            str(source_dir),
        ],
    )

    assert capsys.readouterr().err == ""
