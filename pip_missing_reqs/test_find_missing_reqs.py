from __future__ import absolute_import

import ast
import collections
import logging
import optparse
import os
import os.path
import sys

import pytest
import pretend

from . import find_missing_reqs


@pytest.fixture
def fake_opts():

    class FakeOptParse:
        class options:
            paths = ['dummy']
            verbose = True
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


@pytest.mark.parametrize(["path", "result"], [
    ('/', ''),
    ('__init__.py', ''),    # a top-level file like this has no package name
    ('/__init__.py', ''),   # no package name
    ('spam/__init__.py', 'spam'),
    ('spam/__init__.pyc', 'spam'),
    ('spam/__init__.pyo', 'spam'),
    ('ham/spam/__init__.py', 'ham/spam'),
    ('/ham/spam/__init__.py', '/ham/spam'),
])
def test_is_package_file(path, result):
    assert find_missing_reqs.is_package_file(path) == result


def test_FoundModule():
    fm = find_missing_reqs.FoundModule('spam', 'ham')
    assert fm.modname == 'spam'
    assert fm.filename == 'ham'
    assert fm.locations == []
    assert str(fm) == 'FoundModule("spam")'


@pytest.mark.parametrize(["stmt", "result"], [
    ('import ast', ['ast']),
    ('import ast, sys', ['ast', 'sys']),
    ('from sys import version', ['sys']),
    ('from os import path', ['os']),
    ('import distutils.command.check', ['distutils']),
    ('import spam', []),    # don't break because bad programmer
])
def test_ImportVisitor(stmt, result):
    class options:
        def ignore_mods(self, modname):
            return False
    vis = find_missing_reqs.ImportVisitor(options())
    vis.set_location('spam.py')
    vis.visit(ast.parse(stmt))
    result = vis.finalise()
    assert set(result.keys()) == set(result)


def test_pyfiles_file(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
        pretend.call_recorder(lambda x: '/spam/ham.py'))

    assert list(find_missing_reqs.pyfiles('spam')) == ['/spam/ham.py']


def test_pyfiles_file_no_dice(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
        pretend.call_recorder(lambda x: '/spam/ham'))

    with pytest.raises(ValueError):
        list(find_missing_reqs.pyfiles('spam'))


def test_pyfiles_package(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
        pretend.call_recorder(lambda x: '/spam'))
    monkeypatch.setattr(os.path, 'isdir',
        pretend.call_recorder(lambda x: True))
    walk_results = [
        ('spam', [], ['__init__.py', 'spam', 'ham.py']),
        ('spam/dub', [], ['bass.py', 'dropped']),
    ]
    monkeypatch.setattr(os, 'walk',
        pretend.call_recorder(lambda x: walk_results))

    assert list(find_missing_reqs.pyfiles('spam')) == \
        ['spam/__init__.py', 'spam/ham.py', 'spam/dub/bass.py']


@pytest.mark.parametrize(["ignore_ham", "ignore_hashlib", "expect", "locs"], [
    (False, False, ['ast', 'os', 'hashlib'], [('spam.py', 2), ('ham.py', 2)]),
    (False, True, ['ast', 'os'], [('spam.py', 2), ('ham.py', 2)]),
    (True, False, ['ast'], [('spam.py', 2)]),
    (True, True, ['ast'], [('spam.py', 2)]),
])
def test_find_imported_modules(monkeypatch, caplog, ignore_ham, ignore_hashlib,
        expect, locs):
    monkeypatch.setattr(find_missing_reqs, 'pyfiles',
        pretend.call_recorder(lambda x: ['spam.py', 'ham.py']))

    if sys.version_info[0] == 2:
        # py2 will find sys module but py3k won't
        expect.append('sys')

    class FakeFile():
        contents = [
            'from os import path\nimport ast, hashlib',
            'from __future__ import braces\nimport ast, sys\n'
            'from . import friend',
        ]

        def __init__(self, filename):
            pass

        def read(self):
            return self.contents.pop()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass
    monkeypatch.setattr(find_missing_reqs, 'open', FakeFile, raising=False)

    caplog.setLevel(logging.INFO)

    class options:
        paths = ['dummy']
        verbose = True

        @staticmethod
        def ignore_files(path):
            if path == 'ham.py' and ignore_ham:
                return True
            return False

        @staticmethod
        def ignore_mods(module):
            if module == 'hashlib' and ignore_hashlib:
                return True
            return False

    result = find_missing_reqs.find_imported_modules(options)
    assert set(result) == set(expect)
    assert result['ast'].locations == locs

    if ignore_ham:
        assert caplog.records()[0].message == 'ignoring: ham.py'


def test_find_missing_reqs(monkeypatch):
    imported_modules = dict(
        spam=find_missing_reqs.FoundModule('spam', 'site-spam/spam.py',
            [('ham.py', 1)]),
        shrub=find_missing_reqs.FoundModule('shrub', 'site-spam/shrub.py',
            [('ham.py', 3)]),
        ignore=find_missing_reqs.FoundModule('ignore', 'ignore.py',
            [('ham.py', 2)])
    )
    monkeypatch.setattr(find_missing_reqs, 'find_imported_modules',
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

    caplog.setLevel(logging.WARN)

    monkeypatch.setattr(find_missing_reqs, 'find_missing_reqs', lambda x: [
        ('missing', [find_missing_reqs.FoundModule('missing', 'missing.py',
            [('location.py', 1)])])
    ])

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()
        assert excinfo.value == 1

    assert caplog.records()[0].message == \
        'Missing requirements:'
    assert caplog.records()[1].message == \
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


@pytest.mark.parametrize(["ignore_cfg", "candidate", "result"], [
    ([], 'spam', False),
    ([], 'ham', False),
    (['spam'], 'spam', True),
    (['spam'], 'spam.ham', False),
    (['spam'], 'eggs', False),
    (['spam*'], 'spam', True),
    (['spam*'], 'spam.ham', True),
    (['spam*'], 'eggs', False),
    (['spam'], '/spam', True),
])
def test_ignorer(monkeypatch, ignore_cfg, candidate, result):
    monkeypatch.setattr(os.path, 'relpath', lambda s: s.lstrip('/'))
    ignorer = find_missing_reqs.ignorer(ignore_cfg)
    assert ignorer(candidate) == result


@pytest.mark.parametrize(["verbose_cfg", "events", "result"], [
    (False, [(logging.INFO, 'info'), (logging.WARN, 'warn')], ['warn']),
    (True, [(logging.INFO, 'info'), (logging.WARN, 'warn')], ['info', 'warn']),
])
def test_logging_config(monkeypatch, caplog, verbose_cfg, events, result):
    class options:
        paths = ['dummy']
        verbose = verbose_cfg
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

    for event in events:
        find_missing_reqs.log.log(*event)

    messages = [r.message for r in caplog.records()]
    assert messages == result


def test_main_version(monkeypatch, caplog, fake_opts):
    fake_opts.options.version = True
    monkeypatch.setattr(optparse, 'OptionParser', fake_opts)

    with pytest.raises(SystemExit) as excinfo:
        find_missing_reqs.main()
        assert excinfo.value == 'version'
