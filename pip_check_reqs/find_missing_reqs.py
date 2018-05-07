import collections
import logging
import optparse
import os
import pkg_resources
import sys

from packaging.utils import canonicalize_name
#from pip._internal.commands.show import search_packages_info
from pip._internal.download import PipSession
from pip._internal.req.req_file import parse_requirements
from pip._internal.utils.misc import get_installed_distributions

from pip_check_reqs import common

log = logging.getLogger(__name__)


def search_packages_info(query):
    """
    Gather details from installed distributions. Print distribution name,
    version, location, and installed files. Installed files requires a
    pip generated 'installed-files.txt' in the distributions '.egg-info'
    directory.
    """
    installed = {}
    for p in pkg_resources.working_set:
        installed[canonicalize_name(p.project_name)] = p

    query_names = [canonicalize_name(name) for name in query]

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

        if file_list:
            package['files'] = sorted(file_list)
        yield package


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
            path = os.path.realpath(os.path.join(package['location'], file))
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
    elif options.verbose:
        log.setLevel(logging.INFO)
    else:
        log.setLevel(logging.WARN)

    log.info('using pip_check_reqs-%s from %s', __version__, __file__)

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
