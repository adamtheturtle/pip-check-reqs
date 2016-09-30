from __future__ import absolute_import

import collections
import logging
import optparse

import pytest
import pretend

from pip_check_reqs import find_extra_reqs, common


@pytest.fixture
def fake_opts():
    class FakeOptParse:
        class Options:
            paths = ['dummy']
            verbose = False
            debug = False
            version = False
            ignore_files = []
            ignore_mods = []
            ignore_reqs = []

        options = Options()
        args = ['ham.py']

        def __init__(self, _):
            pass

        def add_option(*args, **kw):
            pass

        def parse_args(self):
            return self.options, self.args

    return FakeOptParse


def test_find_extra_reqs(monkeypatch):
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

    fake_dist = collections.namedtuple('fake_dist', ['project_name'])
    installed_distributions = map(fake_dist, ['spam', 'pass'])
    monkeypatch.setattr(find_extra_reqs, 'get_installed_distributions',
                        pretend.call_recorder(lambda: installed_distributions))
    packages_info = [
        dict(name='spam', location='site-spam', files=['spam/__init__.py',
                                                       'spam/shrub.py']),
        dict(name='shrub', location='site-spam', files=['shrub.py']),
        dict(name='pass', location='site-spam', files=['pass.py']),
    ]

    monkeypatch.setattr(find_extra_reqs, 'search_packages_info',
                        pretend.call_recorder(lambda x: packages_info))

    fake_req = collections.namedtuple('fake_req', ['name'])
    requirements = [fake_req('foobar')]
    monkeypatch.setattr(common, 'parse_requirements',
                        pretend.call_recorder(lambda a, session=None: requirements))

    class Options:
        @staticmethod
        def ignore_reqs(_):
            return False

    options = Options()

    result = find_extra_reqs.find_extra_reqs(options)
    assert result == ['foobar']


# noinspection PyShadowingNames
def test_main_failure(monkeypatch, caplog, fake_opts):
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    caplog.setLevel(logging.WARN)

    monkeypatch.setattr(find_extra_reqs, 'find_extra_reqs', lambda x: [
        'extra'
    ])

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main()
        assert excinfo.value == 1

    assert caplog.records()[0].message == 'Extra requirements:'
    assert caplog.records()[1].message == 'extra in requirements.txt'


# noinspection PyUnusedLocal,PyShadowingNames
def test_main_no_spec(monkeypatch, caplog, fake_opts):
    fake_opts.args = []
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)
    monkeypatch.setattr(fake_opts, 'error',
                        pretend.call_recorder(lambda s, e: None), raising=False)

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main()
        assert excinfo.value == 2

    assert fake_opts.error.calls


@pytest.mark.parametrize(["verbose_cfg", "debug_cfg", "result"], [
    (False, False, ['warn']),
    (True, False, ['info', 'warn']),
    (False, True, ['debug', 'info', 'warn']),
    (True, True, ['debug', 'info', 'warn']),
])
def test_logging_config(monkeypatch, caplog, verbose_cfg, debug_cfg, result):
    class Options:
        paths = ['dummy']
        verbose = verbose_cfg
        debug = debug_cfg
        version = False
        ignore_files = []
        ignore_mods = []
        ignore_reqs = []

    options = Options()

    class FakeOptParse:
        def __init__(self, _):
            pass

        def add_option(*args, **kw):
            pass

        @staticmethod
        def parse_args():
            return options, ['ham.py']

    monkeypatch.setattr(optparse, 'OptionParser', FakeOptParse)

    monkeypatch.setattr(find_extra_reqs, 'find_extra_reqs', lambda x: [])
    find_extra_reqs.main()

    for event in [(logging.DEBUG, 'debug'), (logging.INFO, 'info'),
                  (logging.WARN, 'warn')]:
        find_extra_reqs.log.log(*event)

    messages = [r.message for r in caplog.records()]
    # first message is always the usage message
    if verbose_cfg or debug_cfg:
        assert messages[1:] == result
    else:
        assert messages == result


# noinspection PyUnusedLocal,PyShadowingNames
def test_main_version(monkeypatch, caplog, fake_opts):
    fake_opts.options.version = True
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    with pytest.raises(SystemExit) as excinfo:
        find_extra_reqs.main()
        assert excinfo.value == 'version'
