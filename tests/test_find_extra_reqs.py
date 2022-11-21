"""Tests for `find_extra_reqs.py`."""

from __future__ import absolute_import

import logging
import textwrap
from pathlib import Path
from typing import Any, Callable, Iterable, List, Union

import pretend
import pytest
from pip._internal.req.req_file import ParsedRequirement
from pytest import MonkeyPatch

from pip_check_reqs import common, find_extra_reqs


def test_find_extra_reqs(tmp_path: Path) -> None:
    installed_not_imported_required_package = pytest
    installed_imported_required_package = pretend

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text(
        textwrap.dedent(
            f"""\
            not_installed_package_12345==1
            {installed_imported_required_package.__name__}
            {installed_not_imported_required_package.__name__}
            """
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
            """
        ),
    )

    result = find_extra_reqs.find_extra_reqs(
        requirements_filename=str(fake_requirements_file),
        paths=[str(source_dir)],
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

    caplog.set_level(logging.WARN)

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


def test_main_no_spec(capsys: pytest.CaptureFixture[Any]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main(arguments=[])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.endswith("error: no source files or directories specified\n")


@pytest.mark.parametrize(
    ["verbose_cfg", "debug_cfg", "result"],
    [
        (False, False, ["warn"]),
        (True, False, ["info", "warn"]),
        (False, True, ["debug", "info", "warn"]),
        (True, True, ["debug", "info", "warn"]),
    ],
)
def test_logging_config(
    monkeypatch: MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    verbose_cfg: bool,
    debug_cfg: bool,
    result: List[str],
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    def fake_find_extra_reqs(
        requirements_filename: str,  # pylint: disable=unused-argument
        paths: Iterable[str],  # pylint: disable=unused-argument
        ignore_files_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
        ignore_modules_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
        ignore_requirements_function: Callable[  # noqa: E501 pylint: disable=unused-argument
            [Union[str, ParsedRequirement]], bool
        ],
        skip_incompatible: bool,  # pylint: disable=unused-argument
    ) -> List[str]:
        return []

    monkeypatch.setattr(
        find_extra_reqs,
        "find_extra_reqs",
        fake_find_extra_reqs,
    )
    arguments = [str(source_dir)]
    if verbose_cfg:
        arguments.append("--verbose")
    if debug_cfg:
        arguments.append("--debug")

    find_extra_reqs.main(arguments=arguments)

    for event in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARN, "warn"),
    ]:
        find_extra_reqs.log.log(*event)

    messages = [r.message for r in caplog.records]
    # first message is always the usage message
    if verbose_cfg or debug_cfg:
        assert messages[1:] == result
    else:
        assert messages == result


def test_main_version(capsys: pytest.CaptureFixture[Any]) -> None:
    with pytest.raises(SystemExit):
        find_extra_reqs.main(arguments=["--version"])

    assert capsys.readouterr().out == common.version_info() + "\n"
