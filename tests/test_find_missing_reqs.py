"""Tests for `find_missing_reqs.py`."""

from __future__ import absolute_import

import importlib
import logging
import optparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pretend
import pytest
from pytest import MonkeyPatch

from pip_check_reqs import common, find_missing_reqs


@pytest.fixture(name="fake_opts")
def fixture_fake_opts() -> Any:
    class _FakeOptParse:
        class Options:
            """Options from the command line."""

            requirements_filename = ""
            paths = ["dummy"]
            verbose = False
            debug = False
            version = False
            ignore_files: List[str] = []
            ignore_mods: List[str] = []
            ignore_reqs: List[str] = []

        given_options = Options()
        args = ["ham.py"]

        def __init__(self, usage: str) -> None:
            pass

        def add_option(self, *args: Any, **kw: Any) -> None:
            pass

        def parse_args(self) -> Tuple[Options, List[str]]:
            return (self.given_options, self.args)

    return _FakeOptParse


def test_find_missing_reqs(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    imported_modules = dict(
        spam=common.FoundModule("spam", "site-spam/spam.py", [("ham.py", 1)]),
        shrub=common.FoundModule(
            "shrub", "site-spam/shrub.py", [("ham.py", 3)]
        ),
        ignore=common.FoundModule("ignore", "ignore.py", [("ham.py", 2)]),
    )

    def fake_find_imported_modules(
        paths: Iterable[str],  # pylint: disable=unused-argument
        ignore_files_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
        ignore_modules_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
    ) -> Dict[str, common.FoundModule]:
        return imported_modules

    monkeypatch.setattr(
        common,
        "find_imported_modules",
        pretend.call_recorder(fake_find_imported_modules),
    )

    @dataclass
    class _FakePathDistribution:
        metadata: Dict[str, str]
        name: Optional[str] = None

    installed_distributions = map(
        _FakePathDistribution,
        [{"Name": "spam"}, {"Name": "pass"}],
    )
    monkeypatch.setattr(
        importlib.metadata,
        "distributions",
        pretend.call_recorder(lambda **kwargs: installed_distributions),
    )
    packages_info = [
        dict(
            name="spam",
            location="site-spam",
            files=["spam/__init__.py", "spam/shrub.py"],
        ),
        dict(name="shrub", location="site-spam", files=["shrub.py"]),
        dict(name="pass", location="site-spam", files=["pass.py"]),
    ]

    monkeypatch.setattr(
        find_missing_reqs,
        "search_packages_info",
        pretend.call_recorder(lambda x: packages_info),
    )

    fake_requirements_file = tmp_path / "requirements.txt"
    fake_requirements_file.write_text("spam==1")

    result = find_missing_reqs.find_missing_reqs(
        requirements_filename=str(fake_requirements_file),
        paths=[],
        ignore_files_function=common.ignorer(ignore_cfg=[]),
        ignore_modules_function=common.ignorer(ignore_cfg=[]),
    )
    assert result == [("shrub", [imported_modules["shrub"]])]


def test_main_failure(
    monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_opts: Any
) -> None:
    monkeypatch.setattr(optparse, "OptionParser", fake_opts)

    caplog.set_level(logging.WARN)

    def fake_find_missing_reqs(
        requirements_filename: str,  # pylint: disable=unused-argument
        paths: Iterable[str],  # pylint: disable=unused-argument
        ignore_files_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
        ignore_modules_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
    ) -> List[Tuple[str, List[common.FoundModule]]]:
        return [
            (
                "missing",
                [
                    common.FoundModule(
                        "missing",
                        "missing.py",
                        [("location.py", 1)],
                    )
                ],
            )
        ]

    monkeypatch.setattr(
        find_missing_reqs,
        "find_missing_reqs",
        fake_find_missing_reqs,
    )

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()

    assert excinfo.value.code == 1

    assert caplog.records[0].message == "Missing requirements:"
    assert (
        caplog.records[1].message
        == "location.py:1 dist=missing module=missing"
    )


def test_main_no_spec(monkeypatch: MonkeyPatch, fake_opts: Any) -> None:
    fake_opts.args = []
    monkeypatch.setattr(optparse, "OptionParser", fake_opts)
    monkeypatch.setattr(
        fake_opts,
        "error",
        pretend.call_recorder(lambda s, e: None),
        raising=False,
    )

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()

    assert excinfo.value.code == 2

    assert fake_opts.error.calls


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
) -> None:
    class Options:
        """Options from the command line."""

        requirements_filename = ""
        paths = ["dummy"]
        verbose = verbose_cfg
        debug = debug_cfg
        version = False
        ignore_files: List[str] = []
        ignore_mods: List[str] = []

    given_options = Options()

    class _FakeOptParse:
        def __init__(self, usage: str) -> None:
            pass

        def add_option(self, *args: Any, **kw: Any) -> None:
            pass

        @staticmethod
        def parse_args() -> Tuple[Options, List[str]]:
            return (given_options, ["ham.py"])

    monkeypatch.setattr(optparse, "OptionParser", _FakeOptParse)

    def fake_find_missing_reqs(
        requirements_filename: str,  # pylint: disable=unused-argument
        paths: Iterable[str],  # pylint: disable=unused-argument
        ignore_files_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
        ignore_modules_function: Callable[  # pylint: disable=unused-argument
            [str], bool
        ],
    ) -> List[Tuple[str, List[common.FoundModule]]]:
        return []

    monkeypatch.setattr(
        find_missing_reqs,
        "find_missing_reqs",
        fake_find_missing_reqs,
    )
    find_missing_reqs.main()

    for event in [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARN, "warn"),
    ]:
        find_missing_reqs.log.log(*event)

    messages = [r.message for r in caplog.records]
    # first message is always the usage message
    if verbose_cfg or debug_cfg:
        assert messages[1:] == result
    else:
        assert messages == result


def test_main_version(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[Any],
    fake_opts: Any,
) -> None:
    fake_opts.Options.version = True
    monkeypatch.setattr(optparse, "OptionParser", fake_opts)

    with pytest.raises(SystemExit):
        find_missing_reqs.main()

    assert capsys.readouterr().out == common.version_info() + "\n"
