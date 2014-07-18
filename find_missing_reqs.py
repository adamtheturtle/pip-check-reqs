import ast
import collections
import fnmatch
import imp
import optparse
import os
import re
import logging

from pip.req import parse_requirements
from pip.download import PipSession
from pip.commands.show import search_packages_info
from pip.util import get_installed_distributions, normalize_name


log = logging.getLogger(__name__)


class FoundModule:
    def __init__(self, modname, filename, locations=None):
        self.modname = modname
        self.filename = filename
        self.locations = locations or []         # filename, lineno

    def __repr__(self):
        return 'FoundModule("%s")' % self.modname


class ImportVisitor(ast.NodeVisitor):
    def __init__(self):
        super(ImportVisitor, self).__init__()
        self.__modules = {}
        self.__location = None

    def set_location(self, location):
        self.__location = location

    def visit_Import(self, node):
        for alias in node.names:
            self.__addModule(alias.name, node.lineno)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.__addModule(node.module + '.' + alias.name, node.lineno)

    def __addModule(self, modname, lineno):
        path = None
        progress = []
        modpath = None
        for p in modname.split('.'):
            try:
                file, modpath, description = imp.find_module(p, path)
            except ImportError:
                # the component specified at this point is not importable
                # (is just an attr of the module)
                # *or* it's not actually installed, so we don't care either
                break

            # success! we found *something*
            progress.append(p)

            # ... though it might not be a file, so not interesting to us
            if not os.path.isdir(modpath):
                break

            path = [modpath]

        if modpath is None:
            # the module doesn't actually appear to exist
            return

        modname = '.'.join(progress)
        if modname not in self.__modules:
            self.__modules[modname] = FoundModule(modname, modpath)
        self.__modules[modname].locations.append((self.__location, lineno))

    def finalise(self):
        return self.__modules


def pyfiles(root):
    d = os.path.abspath(root)
    if not os.path.isdir(d):
        n, ext = os.path.splitext(d)
        if ext == '.py':
            yield d
        else:
            raise ValueError('%s is not a python file or directory' % root)
    for root, dirs, files in os.walk(d):
        for f in files:
            n, ext = os.path.splitext(f)
            if ext == '.py':
                yield os.path.join(root, f)


def find_imported_modules(options):
    vis = ImportVisitor()
    for path in options.paths:
        for filename in pyfiles(path):
            if options.ignore_files(filename):
                log.info('ignoring: %s', filename)
                continue
            with open(filename) as f:
                vis.set_location(filename)
                vis.visit(ast.parse(f.read()))
    return vis.finalise()


def is_package_file(path):
    '''Determines whether the path points to a Python package sentinel
    file - the __init__.py or its compiled variants.
    '''
    m = re.search('(.+)/__init__\.py[co]?$', path)
    if m is not None:
        return m.group(1)
    return ''


def find_missing_reqs(options):
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = find_imported_modules(options)

    # 2. find which packages provide which files
    installed_files = {}
    all_pkgs = (pkg.project_name for pkg in get_installed_distributions())
    for package in search_packages_info(all_pkgs):
        for file in package['files'] or []:
            path = os.path.normpath(os.path.join(package['location'], file))
            installed_files[path] = package['name']
            package_path = is_package_file(path)
            if package_path:
                # we've seen a package file so add the bare package directory
                # to the installed list as well as we might want to look up
                # a package by its directory path later
                installed_files[package_path] = package['name']

    used = collections.defaultdict(list)
    for modname, info in used_modules.items():
        # probably standard library if it's not in the files list
        if info.filename in installed_files:
            used_name = normalize_name(installed_files[info.filename])
            used[used_name].append(info)

    # 3. compare with requirements.txt
    explicit = set()
    for requirement in parse_requirements('requirements.txt',
            session=PipSession()):
        explicit.add(normalize_name(requirement.name))

    for name in used:
        if name not in explicit:
            yield name, used[name]


def main():
    parser = optparse.OptionParser()
    parser.add_option("-f", "--ignore-file", dest="ignore_files",
        action="append", default=[],
        help="file paths (globs or fragments) to ignore")
    parser.add_option("-m", "--ignore-module", dest="ignore_mods",
        action="append", default=[],
        help="used modules (by name) to ignore")
    parser.add_option("-v", "--verbose", dest="verbose",
        action="store_true", default=False, help="be more verbose")

    (options, args) = parser.parse_args()
    if options.ignore_files:
        def ignore_files(filename, ignore_files=options.ignore_files):
            for ignore in ignore_files:
                if '*' in ignore:
                    if fnmatch.fnmatch(filename, ignore):
                        return True
                elif ignore in filename:
                    return True
            return False
        options.ignore_files = ignore_files
    else:
        options.ignore_files = lambda x: False

    options.paths = args or ['.']

    logging.basicConfig(level=logging.INFO if options.verbose
        else logging.WARN)

    for name, uses in find_missing_reqs(options):
        for use in uses:
            for filename, lineno in use.locations:
                log.warning('%s:%s dist=%s module=%s', filename, lineno,
                    name, use.modname)

if __name__ == '__main__':  # pragma: no cover
    main()
