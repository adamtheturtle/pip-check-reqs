from __future__ import absolute_import
from dataclasses import dataclass
import importlib
from typing import Any, Dict, List, Tuple, Optional

import logging
import optparse
from pathlib import Path

import pytest
import pretend
from pytest import MonkeyPatch

from pip_check_reqs import find_extra_reqs, common


@pytest.fixture
def fake_opts() -> Any:
    class FakeOptParse:
        class options:
            requirements_filename = 'requirements.txt'
            paths = ['dummy']
            verbose = False
            debug = False
            version = False
            ignore_files: List[str] = []
            ignore_mods: List[str] = []
            ignore_reqs: List[str] = []

        given_options = options()
        args = ['ham.py']

        def __init__(self, usage: str) -> None:
            pass

        def add_option(*args: Any, **kw: Any) -> None:
            pass

        def parse_args(self) -> Tuple[options, List[str]]:
            return (self.given_options, self.args)

    return FakeOptParse


def test_find_extra_reqs(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    imported_modules = dict(spam=common.FoundModule('spam',
                                                    'site-spam/spam.py',
                                                    [('ham.py', 1)]),
                            shrub=common.FoundModule('shrub',
                                                     'site-spam/shrub.py',
                                                     [('ham.py', 3)]),
                            ignore=common.FoundModule('ignore', 'ignore.py',
                                                      [('ham.py', 2)]))
    monkeypatch.setattr(common, 'find_imported_modules',
                        pretend.call_recorder(lambda a: imported_modules))

    @dataclass
    class FakePathDistribution:
        metadata: Dict[str, str]
        name: Optional[str] = None

    installed_distributions = map(
        FakePathDistribution,
        [{'Name': 'spam'}, {'Name': 'pass'}],
    )
    monkeypatch.setattr(
        importlib.metadata,
        'distributions',
        pretend.call_recorder(lambda **kwargs: installed_distributions),
    )
    packages_info = [
        dict(name='spam',
             location='site-spam',
             files=['spam/__init__.py', 'spam/shrub.py']),
        dict(name='shrub', location='site-spam', files=['shrub.py']),
        dict(name='pass', location='site-spam', files=['pass.py']),
    ]

    monkeypatch.setattr(find_extra_reqs, 'search_packages_info',
                        pretend.call_recorder(lambda x: packages_info))

    fake_requirements_file = tmp_path / 'requirements.txt'
    fake_requirements_file.write_text('foobar==1')

    class options:
        def ignore_reqs(x: Any, y: Any) -> bool:
            return False
        skip_incompatible = False

    given_options = options()

    result = find_extra_reqs.find_extra_reqs(
        options=given_options,
        requirements_filename=str(fake_requirements_file),
    )
    assert result == ['foobar']


def test_main_failure(monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_opts: Any) -> None:
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    caplog.set_level(logging.WARN)

    monkeypatch.setattr(find_extra_reqs, 'find_extra_reqs',
                        lambda options, requirements_filename: ['extra'])

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main()

    assert excinfo.value.code == 1

    assert caplog.records[0].message == \
        'Extra requirements:'
    assert caplog.records[1].message == \
        'extra in requirements.txt'


def test_main_no_spec(monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_opts: Any) -> None:
    fake_opts.args = []
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)
    monkeypatch.setattr(fake_opts,
                        'error',
                        pretend.call_recorder(lambda s, e: None),
                        raising=False)

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main()

    assert excinfo.value.code == 2

    assert fake_opts.error.calls


@pytest.mark.parametrize(["verbose_cfg", "debug_cfg", "result"], [
    (False, False, ['warn']),
    (True, False, ['info', 'warn']),
    (False, True, ['debug', 'info', 'warn']),
    (True, True, ['debug', 'info', 'warn']),
])
def test_logging_config(monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture, verbose_cfg: bool, debug_cfg: bool, result: List[str]) -> None:
    class options:
        requirements_filename = ''
        paths = ['dummy']
        verbose = verbose_cfg
        debug = debug_cfg
        version = False
        ignore_files: List[str] = []
        ignore_mods: List[str] = []
        ignore_reqs: List[str] = []

    given_options = options()

    class FakeOptParse:
        def __init__(self, usage: str) -> None:
            pass

        def add_option(*args: Any, **kw: Any) -> None:
            pass

        def parse_args(self) -> Tuple[options, List[str]]:
            return (given_options, ['ham.py'])

    monkeypatch.setattr(optparse, 'OptionParser', FakeOptParse)

    monkeypatch.setattr(
        find_extra_reqs,
        'find_extra_reqs',
        lambda options, requirements_filename: [],
    )
    find_extra_reqs.main()

    for event in [(logging.DEBUG, 'debug'), (logging.INFO, 'info'),
                  (logging.WARN, 'warn')]:
        find_extra_reqs.log.log(*event)

    messages = [r.message for r in caplog.records]
    # first message is always the usage message
    if verbose_cfg or debug_cfg:
        assert messages[1:] == result
    else:
        assert messages == result


def test_main_version(monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[Any], fake_opts: Any) -> None:
    fake_opts.options.version = True
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    with pytest.raises(SystemExit):
        find_extra_reqs.main()

    assert capsys.readouterr().out == common.version_info() + "\n"
