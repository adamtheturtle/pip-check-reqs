import ast
import collections
import logging
import optparse
import os
import os.path
import sys

import pytest
import pretend

import find_missing_reqs


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
    vis = find_missing_reqs.ImportVisitor()
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


@pytest.mark.parametrize(["ignore_ham", "result_keys", "locs"], [
    (False, ['ast', 'os'], [('spam.py', 1), ('ham.py', 2)]),
    (True, ['ast'], [('spam.py', 1)]),
])
def test_find_imported_modules(monkeypatch, caplog, ignore_ham, result_keys,
        locs):
    monkeypatch.setattr(find_missing_reqs, 'pyfiles',
        pretend.call_recorder(lambda x: ['spam.py', 'ham.py']))

    if sys.version_info[0] == 2:
        # py2 will find sys module but py3k won't
        result_keys.append('sys')

    class FakeFile():
        contents = [
            'from os import path\nimport ast',
            'import ast, sys',
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

    result = find_missing_reqs.find_imported_modules(options)
    assert set(result) == set(result_keys)
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


def test_main(monkeypatch, caplog):
    class options:
        paths = ['dummy']
        verbose = True
        ignore_files = []
        ignore_mods = []
    options = options()

    class FakeOptParse:
        def add_option(*args, **kw):
            pass

        def parse_args(self):
            return [options, 'ham.py']

    monkeypatch.setattr(optparse, 'OptionParser', FakeOptParse)

    caplog.setLevel(logging.WARN)

    monkeypatch.setattr(find_missing_reqs, 'find_missing_reqs', lambda x: [
        ('missing', [find_missing_reqs.FoundModule('missing', 'missing.py',
            [('location.py', 1)])])
    ])

    find_missing_reqs.main()

    assert caplog.records()[0].message == \
        'location.py:1 dist=missing module=missing'


@pytest.mark.parametrize(["ignore_cfg", "file_candidates"], [
    ([], [('spam', False), ('ham', False)]),
    (['spam'], [('spam', True), ('ham', False), ('eggs', False)]),
    (['*am'], [('spam', True), ('ham', True), ('eggs', False)]),
])
def test_ignore_files(monkeypatch, ignore_cfg, file_candidates):
    class options:
        paths = ['dummy']
        verbose = True
        ignore_files = ignore_cfg
        ignore_mods = []
    options = options()

    class FakeOptParse:
        def add_option(*args, **kw):
            pass

        def parse_args(self):
            return [options, 'ham.py']

    monkeypatch.setattr(optparse, 'OptionParser', FakeOptParse)

    monkeypatch.setattr(find_missing_reqs, 'find_missing_reqs', lambda x: [])
    find_missing_reqs.main()

    for fn, matched in file_candidates:
        assert options.ignore_files(fn) == matched
