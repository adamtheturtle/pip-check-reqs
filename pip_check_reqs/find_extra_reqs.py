import collections
import logging
import optparse
import os
import sys

from packaging.utils import canonicalize_name
from pip.commands.show import search_packages_info
from pip.utils import get_installed_distributions

from pip_check_reqs import common

log = logging.getLogger(__name__)


def find_extra_reqs(options):
    # 1. find files used by imports in the code (as best we can without
    #    executing)
    used_modules = common.find_imported_modules(options)

    # 2. find which packages provide which files
    installed_files = {}
    all_pkgs = (pkg.project_name for pkg in get_installed_distributions())
    for package in search_packages_info(all_pkgs):
        log.debug('installed package: %s (at %s)', package['name'],
            package['location'])
        for f in package['files'] or []:
            path = os.path.realpath(os.path.join(package['location'], f))
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
    explicit = common.find_required_modules(options)

    return [name for name in explicit if name not in used]


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
    parser.add_option("-r", "--ignore-requirement", dest="ignore_reqs",
        action="append", default=[],
        help="reqs in requirements.txt to ignore")
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
    options.ignore_reqs = common.ignorer(options.ignore_reqs)

    options.paths = args

    logging.basicConfig(format='%(message)s')
    if options.debug:
        log.setLevel(logging.DEBUG)
    elif options.verbose:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARN)

    log.info('using pip_check_reqs-%s from %s', __version__, __file__)

    extras = find_extra_reqs(options)

    if extras:
        log.warning('Extra requirements:')
    for name in extras:
        log.warning('%s in requirements.txt' % name)

    if extras:
        sys.exit(1)


if __name__ == '__main__':  # pragma: no cover
    main()
