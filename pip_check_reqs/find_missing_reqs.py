import collections
import logging
import optparse
import os
import sys

from packaging.utils import canonicalize_name
from pip.commands.show import search_packages_info
from pip.download import PipSession
from pip.req import parse_requirements
from pip.utils import get_installed_distributions

from pip_check_reqs import common

log = logging.getLogger(__name__)


def find_missing_reqs(options):
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = common.find_imported_modules(options)

    # 2. find which packages provide which files
    installed_files = {}
    all_pkgs = (pkg.project_name for pkg in get_installed_distributions())
    for package in search_packages_info(all_pkgs):
        log.debug('installed package: %s (at %s)', package['name'],
                  package['location'])
        for file in package.get('files', []) or []:
            # Convert the path to lower case to handle file systems that are case insensitive
            path = os.path.realpath(os.path.join(package['location'], file)).lower()
            installed_files[path] = package['name']
            package_path = common.is_package_file(path)
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
            used_name = canonicalize_name(installed_files[info.filename])
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
        explicit.add(canonicalize_name(requirement.name))

    return [(name, used[name]) for name in used
            if name not in explicit]


def main():
    from pip_check_reqs import __version__

    usage = 'usage: %prog [options] files or directories'
    parser = optparse.OptionParser(usage)
    parser.add_option("-f", "--ignore-file", dest="ignore_files",
                      action="append", default=[],
                      help="file paths globs to ignore")
    parser.add_option("-m", "--ignore-module", dest="ignore_mods",
                      action="append", default=[],
                      help="used module names (globs are ok) to ignore")
    parser.add_option("-l", "--follow-links", dest="follow_links",
                      action="store_true", default=False, help="follow symlinks (can cause infinite recursion)")
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

    options.ignore_files = common.ignorer(options.ignore_files)
    options.ignore_mods = common.ignorer(options.ignore_mods)

    options.paths = args

    logging.basicConfig(format='%(message)s')
    if options.debug:
        log.setLevel(logging.DEBUG)
        common.log.setLevel(logging.DEBUG)
    elif options.verbose:
        log.setLevel(logging.INFO)
        common.log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARN)
        common.log.setLevel(logging.WARN)

    log.info('using pip_check_reqs-%s from %s', __version__, __file__)

    missing = find_missing_reqs(options)

    if missing:
        log.warning('Missing requirements:')
    for name, uses in sorted(missing):
        for use in uses:
            for filename, lineno in use.locations:
                log.warning('%s:%s dist=%s module=%s',
                            os.path.relpath(filename), lineno, name, use.modname)

    if missing:
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    main()
