import ast
import collections
import fnmatch
import imp
import logging
import optparse
import os
import re
import sys

import pkg_resources
from pip.req import parse_requirements
from pip.download import PipSession
from pip.util import get_installed_distributions, normalize_name

log = logging.getLogger(__name__)


# TODO: remove me when pip 1.6 is released (vendored from pypa/pip git)
def search_packages_info(query):  # pragma: no cover
    """
    Gather details from installed distributions. Print distribution name,
    version, location, and installed files. Installed files requires a
    pip generated 'installed-files.txt' in the distributions '.egg-info'
    directory.
    """
    installed = dict(
        [(p.project_name.lower(), p) for p in pkg_resources.working_set])
    query_names = [name.lower() for name in query]
    for dist in [installed[pkg] for pkg in query_names if pkg in installed]:
        package = {
            'name': dist.project_name,
            'version': dist.version,
            'location': dist.location,
            'requires': [dep.project_name for dep in dist.requires()],
        }
        file_list = None
        if isinstance(dist, pkg_resources.DistInfoDistribution):
            # RECORDs should be part of .dist-info metadatas
            if dist.has_metadata('RECORD'):
                lines = dist.get_metadata_lines('RECORD')
                paths = [l.split(',')[0] for l in lines]
                paths = [os.path.join(dist.location, p) for p in paths]
                file_list = [os.path.relpath(p, dist.location) for p in paths]
        else:
            # Otherwise use pip's log for .egg-info's
            if dist.has_metadata('installed-files.txt'):
                paths = dist.get_metadata_lines('installed-files.txt')
                paths = [os.path.join(dist.egg_info, p) for p in paths]
                file_list = [os.path.relpath(p, dist.location) for p in paths]
        # use and short-circuit to check for None
        package['files'] = file_list and sorted(file_list)
        yield package


class FoundModule:
    def __init__(self, modname, filename, locations=None):
        self.modname = modname
        self.filename = os.path.realpath(filename)
        self.locations = locations or []         # filename, lineno

    def __repr__(self):
        return 'FoundModule("%s")' % self.modname


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, options):
        super(ImportVisitor, self).__init__()
        self.__options = options
        self.__modules = {}
        self.__location = None

    def set_location(self, location):
        self.__location = location

    def visit_Import(self, node):
        for alias in node.names:
            self.__addModule(alias.name, node.lineno)

    def visit_ImportFrom(self, node):
        if node.module == '__future__':
            # not an actual module
            return
        for alias in node.names:
            if node.module is None:
                # relative import
                continue
            self.__addModule(node.module + '.' + alias.name, node.lineno)

    def __addModule(self, modname, lineno):
        if self.__options.ignore_mods(modname):
            return
        path = None
        progress = []
        modpath = last_modpath = None
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

            # we might have previously seen a useful path though...
            if modpath is None:   # pragma: no cover
                # the sys module will hit this code path on py3k - possibly
                # others will, but I've not discovered them
                modpath = last_modpath
                break

            # ... though it might not be a file, so not interesting to us
            if not os.path.isdir(modpath):
                break

            path = [modpath]
            last_modpath = modpath

        if modpath is None:
            # the module doesn't actually appear to exist on disk
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
    vis = ImportVisitor(options)
    for path in options.paths:
        for filename in pyfiles(path):
            if options.ignore_files(filename):
                log.info('ignoring: %s', os.path.relpath(filename))
                continue
            log.debug('scanning: %s', os.path.relpath(filename))
            with open(filename) as f:
                content = f.read()
            vis.set_location(filename)
            vis.visit(ast.parse(content))
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
        log.debug('installed package: %s (at %s)', package['name'],
            package['location'])
        for file in package['files'] or []:
            path = os.path.realpath(os.path.join(package['location'], file))
            installed_files[path] = package['name']
            package_path = is_package_file(path)
            if package_path:
                # we've seen a package file so add the bare package directory
                # to the installed list as well as we might want to look up
                # a package by its directory path later
                installed_files[package_path] = package['name']

    # 3. match imported modules against those packages
    used = collections.defaultdict(list)
    for modname, info in used_modules.items():
        # probably standard library if it's not in the files list
        if info.filename in installed_files:
            used_name = normalize_name(installed_files[info.filename])
            log.debug('used module: %s (from package %s)', modname,
                installed_files[info.filename])
            used[used_name].append(info)
        else:
            log.debug(
                'used module: %s (from file %s, assuming stdlib or local)',
                modname, info.filename)

    # 4. compare with requirements.txt
    explicit = set()
    for requirement in parse_requirements('requirements.txt',
            session=PipSession()):
        log.debug('found requirement: %s', requirement.name)
        explicit.add(normalize_name(requirement.name))

    return [(name, used[name]) for name in used
        if name not in explicit]


def ignorer(ignore_cfg):
    if not ignore_cfg:
        return lambda candidate: False

    def f(candidate, ignore_cfg=ignore_cfg):
        for ignore in ignore_cfg:
            if fnmatch.fnmatch(candidate, ignore):
                return True
            elif fnmatch.fnmatch(os.path.relpath(candidate), ignore):
                return True
        return False
    return f


def main():
    from pip_missing_reqs import __version__

    usage = 'usage: %prog [options] files or directories'
    parser = optparse.OptionParser(usage)
    parser.add_option("-f", "--ignore-file", dest="ignore_files",
        action="append", default=[],
        help="file paths globs to ignore")
    parser.add_option("-m", "--ignore-module", dest="ignore_mods",
        action="append", default=[],
        help="used module names (globs are ok) to ignore")
    parser.add_option("-v", "--verbose", dest="verbose",
        action="store_true", default=False, help="be more verbose")
    parser.add_option("-d", "--debug", dest="debug",
        action="store_true", default=False, help="be *really* verbose")
    parser.add_option("--version", dest="version",
        action="store_true", default=False, help="display version information")

    (options, args) = parser.parse_args()

    if options.version:
        sys.exit(__version__)

    if not args:
        parser.error("no source files or directories specified")
        sys.exit(2)

    options.ignore_files = ignorer(options.ignore_files)
    options.ignore_mods = ignorer(options.ignore_mods)

    options.paths = args

    logging.basicConfig(format='%(message)s')
    if options.debug:
        log.setLevel(logging.DEBUG)
    elif options.verbose:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARN)

    log.info('using pip_missing_reqs-%s from %s', __version__, __file__)

    missing = find_missing_reqs(options)

    if missing:
        log.warning('Missing requirements:')
    for name, uses in missing:
        for use in uses:
            for filename, lineno in use.locations:
                log.warning('%s:%s dist=%s module=%s',
                    os.path.relpath(filename), lineno, name, use.modname)

    if missing:
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    main()
