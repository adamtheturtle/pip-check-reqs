from __future__ import absolute_import

import ast
import collections
import logging
import os.path
import sys

import pytest
import pretend

from pip_check_reqs import common


@pytest.mark.parametrize(["path", "result"], [
    ('/', ''),
    ('__init__.py', ''),  # a top-level file like this has no package name
    ('/__init__.py', ''),  # no package name
    ('spam/__init__.py', 'spam'),
    ('spam/__init__.pyc', 'spam'),
    ('spam/__init__.pyo', 'spam'),
    ('ham/spam/__init__.py', 'ham/spam'),
    ('/ham/spam/__init__.py', '/ham/spam'),
])
def test_is_package_file(path, result):
    assert common.is_package_file(path) == result


# noinspection PyPep8Naming
def test_FoundModule():
    fm = common.FoundModule('spam', 'ham')
    assert fm.modname == 'spam'
    assert fm.filename == os.path.realpath('ham')
    assert fm.locations == []
    assert str(fm) == 'FoundModule("spam")'


# noinspection PyPep8Naming,PyUnusedLocal
@pytest.mark.parametrize(["stmt", "result"], [
    ('import ast', ['ast']),
    ('import ast, sys', ['ast', 'sys']),
    ('from sys import version', ['sys']),
    ('from os import path', ['os']),
    ('import distutils.command.check', ['distutils']),
    ('import spam', []),  # don't break because bad programmer
])
def test_ImportVisitor(stmt, result):
    class Options:
        @staticmethod
        def ignore_mods(_):
            return False

    vis = common.ImportVisitor(Options())
    vis.set_location('spam.py')
    vis.visit(ast.parse(stmt))
    result = vis.finalise()
    assert set(result.keys()) == set(result)


def test_pyfiles_file(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham.py'))

    assert list(common.pyfiles('spam')) == ['/spam/ham.py']


def test_pyfiles_file_no_dice(monkeypatch):
    monkeypatch.setattr(os.path, 'abspath',
                        pretend.call_recorder(lambda x: '/spam/ham'))

    with pytest.raises(ValueError):
        list(common.pyfiles('spam'))


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
                        pretend.call_recorder(lambda x, **_: walk_results))

    assert list(common.pyfiles('spam')) == ['spam/__init__.py', 'spam/ham.py', 'spam/dub/bass.py']


@pytest.mark.parametrize(["ignore_ham", "ignore_hashlib", "expect", "locs"], [
    (False, False, ['ast', 'os', 'hashlib'], [('spam.py', 2), ('ham.py', 2)]),
    (False, True, ['ast', 'os'], [('spam.py', 2), ('ham.py', 2)]),
    (True, False, ['ast'], [('spam.py', 2)]),
    (True, True, ['ast'], [('spam.py', 2)]),
])
def test_find_imported_modules(monkeypatch, caplog, ignore_ham, ignore_hashlib,
                               expect, locs):
    monkeypatch.setattr(common, 'pyfiles',
                        pretend.call_recorder(lambda x, _: ['spam.py', 'ham.py']))

    if sys.version_info[0] == 2:
        # py2 will find sys module but py3k won't
        expect.append('sys')

    class FakeFile:
        contents = [
            'from os import path\nimport ast, hashlib',
            'from __future__ import braces\nimport ast, sys\n'
            'from . import friend',
        ]

        def __init__(self, _):
            pass

        def read(self):
            return self.contents.pop()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(common, 'open', FakeFile, raising=False)

    caplog.setLevel(logging.INFO)

    class Options:
        paths = ['dummy']
        follow_links = False
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

    result = common.find_imported_modules(Options)
    assert set(result) == set(expect)
    assert result['ast'].locations == locs

    if ignore_ham:
        assert caplog.records()[0].message == 'ignoring: ham.py'


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
    ignorer = common.ignorer(ignore_cfg)
    assert ignorer(candidate) == result


def test_find_required_modules(monkeypatch):
    class Options:
        @staticmethod
        def ignore_reqs(req):
            if req.name == 'barfoo':
                return True
            return False

    fake_req = collections.namedtuple('fake_req', ['name'])
    requirements = [fake_req('foobar'), fake_req('barfoo')]
    monkeypatch.setattr(common, 'parse_requirements',
                        pretend.call_recorder(lambda a, session=None: requirements))

    reqs = common.find_required_modules(Options)
    assert reqs == set(['foobar'])
