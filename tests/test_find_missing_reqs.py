from __future__ import absolute_import
from dataclasses import dataclass
import importlib
import site
from typing import Dict, Optional

import logging
import optparse
from pathlib import Path

import pytest
import pretend

from pip_check_reqs import find_missing_reqs, common

from .package_info_mock import _PackageInfo


@pytest.fixture
def fake_opts():
    class FakeOptParse:
        class options:
            requirements_filename = ''
            paths = ['dummy']
            verbose = False
            debug = False
            version = False
            ignore_files = []
            ignore_mods = []

        options = options()
        args = ['ham.py']

        def __init__(self, usage):
            pass

        def add_option(*args, **kw):
            pass

        def parse_args(self):
            return (self.options, self.args)

    return FakeOptParse


def test_find_missing_reqs(monkeypatch, tmp_path: Path):
    site_path = site.getsitepackages()[0]
    imported_modules = dict(spam=common.FoundModule('spam',
                                                    f'{site_path}/spam.py',
                                                    [('ham.py', 1)]),
                            shrub=common.FoundModule('shrub',
                                                     f'{site_path}/shrub.py',
                                                     [('ham.py', 3)]),
                            ignore=common.FoundModule('ignore', 'ignore.py',
                                                      [('ham.py', 2)]))
    monkeypatch.setattr(common, 'find_imported_modules',
                        pretend.call_recorder(lambda a: imported_modules))

    @dataclass
    class FakePathDistribution:
        metadata: Dict
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
        _PackageInfo(name='spam',
                     location=site_path,
                     files=['spam/__init__.py', 'spam/shrub.py']),
        _PackageInfo(name='shrub', location=site_path, files=['shrub.py']),
        _PackageInfo(name='pass', location=site_path, files=['pass.py']),
    ]

    monkeypatch.setattr(find_missing_reqs, 'search_packages_info',
                        pretend.call_recorder(lambda x: packages_info))

    fake_requirements_file = tmp_path / 'requirements.txt'
    fake_requirements_file.write_text('spam==1')

    result = list(
        find_missing_reqs.find_missing_reqs(
            options=None,
            requirements_filename=str(fake_requirements_file),
        )
    )
    assert result == [('shrub', [imported_modules['shrub']])]


def test_main_failure(monkeypatch, caplog, fake_opts):
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    caplog.set_level(logging.WARN)

    def fake_find_missing_reqs(options, requirements_filename):
        return [
            (
                'missing',
                [
                    common.FoundModule(
                        'missing',
                        'missing.py',
                        [('location.py', 1)],
                    )
                ]
            )
        ]

    monkeypatch.setattr(
        find_missing_reqs,
        'find_missing_reqs',
        fake_find_missing_reqs,
    )

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()

    assert excinfo.value.code == 1

    assert caplog.records[0].message == \
        'Missing requirements:'
    assert caplog.records[1].message == \
        'location.py:1 dist=missing module=missing'


def test_main_no_spec(monkeypatch, caplog, fake_opts):
    fake_opts.args = []
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)
    monkeypatch.setattr(fake_opts,
                        'error',
                        pretend.call_recorder(lambda s, e: None),
                        raising=False)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()

    assert excinfo.value.code == 2

    assert fake_opts.error.calls


@pytest.mark.parametrize(["verbose_cfg", "debug_cfg", "result"], [
    (False, False, ['warn']),
    (True, False, ['info', 'warn']),
    (False, True, ['debug', 'info', 'warn']),
    (True, True, ['debug', 'info', 'warn']),
])
def test_logging_config(monkeypatch, caplog, verbose_cfg, debug_cfg, result):
    class options:
        requirements_filename = '',
        paths = ['dummy']
        verbose = verbose_cfg
        debug = debug_cfg
        version = False
        ignore_files = []
        ignore_mods = []

    options = options()

    class FakeOptParse:
        def __init__(self, usage):
            pass

        def add_option(*args, **kw):
            pass

        def parse_args(self):
            return (options, ['ham.py'])

    monkeypatch.setattr(optparse, 'OptionParser', FakeOptParse)

    monkeypatch.setattr(
        find_missing_reqs,
        'find_missing_reqs',
        lambda options, requirements_filename: [],
    )
    find_missing_reqs.main()

    for event in [(logging.DEBUG, 'debug'), (logging.INFO, 'info'),
                  (logging.WARN, 'warn')]:
        find_missing_reqs.log.log(*event)

    messages = [r.message for r in caplog.records]
    # first message is always the usage message
    if verbose_cfg or debug_cfg:
        assert messages[1:] == result
    else:
        assert messages == result


def test_main_version(monkeypatch, capsys, fake_opts):
    fake_opts.options.version = True
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    with pytest.raises(SystemExit):
        find_missing_reqs.main()

    assert capsys.readouterr().out == common.version_info() + "\n"
