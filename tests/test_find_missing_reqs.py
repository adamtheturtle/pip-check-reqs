from __future__ import absolute_import

import collections
import logging
import optparse

import pytest
import pretend

from pip_check_reqs import find_missing_reqs, common


@pytest.fixture
def fake_opts():

    class FakeOptParse:
        class options:
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


def test_find_missing_reqs(monkeypatch):
    imported_modules = dict(
        spam=common.FoundModule('spam', 'site-spam/spam.py',
            [('ham.py', 1)]),
        shrub=common.FoundModule('shrub', 'site-spam/shrub.py',
            [('ham.py', 3)]),
        ignore=common.FoundModule('ignore', 'ignore.py',
            [('ham.py', 2)])
    )
    monkeypatch.setattr(common, 'find_imported_modules',
        pretend.call_recorder(lambda a: imported_modules))

    FakeDist = collections.namedtuple('FakeDist', ['project_name'])
    installed_distributions = map(FakeDist, ['spam', 'pass'])
    monkeypatch.setattr(find_missing_reqs, 'get_installed_distributions',
        pretend.call_recorder(lambda: installed_distributions))
    packages_info = [
        dict(name='spam', location='site-spam', files=['spam/__init__.py',
            'spam/shrub.py']),
        dict(name='shrub', location='site-spam', files=['shrub.py']),
        dict(name='pass', location='site-spam', files=['pass.py']),
    ]

    monkeypatch.setattr(find_missing_reqs, 'search_packages_info',
        pretend.call_recorder(lambda x: packages_info))

    FakeReq = collections.namedtuple('FakeReq', ['name'])
    requirements = [FakeReq('spam')]
    monkeypatch.setattr(find_missing_reqs, 'parse_requirements',
        pretend.call_recorder(lambda a, session=None: requirements))

    result = list(find_missing_reqs.find_missing_reqs(None))
    assert result == [('shrub', [imported_modules['shrub']])]


def test_main_failure(monkeypatch, caplog, fake_opts):
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    caplog.set_level(logging.WARN)

    monkeypatch.setattr(find_missing_reqs, 'find_missing_reqs', lambda x: [
        ('missing', [common.FoundModule('missing', 'missing.py',
            [('location.py', 1)])])
    ])

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()
        assert excinfo.value == 1

    assert caplog.records[0].message == \
        'Missing requirements:'
    assert caplog.records[1].message == \
        'location.py:1 dist=missing module=missing'


def test_main_no_spec(monkeypatch, caplog, fake_opts):
    fake_opts.args = []
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)
    monkeypatch.setattr(fake_opts, 'error',
        pretend.call_recorder(lambda s, e: None), raising=False)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()
        assert excinfo.value == 2

    assert fake_opts.error.calls


@pytest.mark.parametrize(["verbose_cfg", "debug_cfg", "result"], [
    (False, False, ['warn']),
    (True, False, ['info', 'warn']),
    (False, True, ['debug', 'info', 'warn']),
    (True, True, ['debug', 'info', 'warn']),
])
def test_logging_config(monkeypatch, caplog, verbose_cfg, debug_cfg, result):
    class options:
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

    monkeypatch.setattr(find_missing_reqs, 'find_missing_reqs', lambda x: [])
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


def test_main_version(monkeypatch, caplog, fake_opts):
    fake_opts.options.version = True
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()
        assert excinfo.value == 'version'
