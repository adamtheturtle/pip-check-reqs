import ast
import fnmatch
import imp
import logging
import os
import re
from typing import Container, Optional, List, cast

from packaging.utils import canonicalize_name
from packaging.markers import Marker
# Between different versions of pip the location of PipSession has changed.
try:
    from pip._internal.network.session import PipSession
except ImportError:  # pragma: no cover
    from pip._internal.download import PipSession
from pip._internal.req.req_file import parse_requirements
try:
    from pip._internal.utils.misc import get_installed_distributions
except ImportError:  # pip>=21.3
    from pip._internal.utils.compat import stdlib_pkgs
    from pip._internal.metadata import get_default_environment, get_environment
    from pip._internal.metadata.pkg_resources import Distribution as _Dist
    from pip._vendor.pkg_resources import Distribution

    # get_installed_distributions was removed in pip 21.3.
    # This is a copy from pip.
    # See
    # https://github.com/pypa/pip/commit/d051a00fc57037104fca85ad8ebf2cdbd1e32d24#diff-058e40cb3a9ea705f655937e48f3a053f5dc7c500b7f1b2aae76e9bd673faf64.
    #
    # This is mocked in all tests (unfortunately) and so we do not cover this
    # function.
    def get_installed_distributions(
         local_only: bool = True,
         skip: Container[str] = stdlib_pkgs,
         include_editables: bool = True,
         editables_only: bool = False,
         user_only: bool = False,
         paths: Optional[List[str]] = None,
     ) -> List[Distribution]:  # pragma: no cover
        """Return a list of installed Distribution objects.

        Left for compatibility until direct pkg_resources uses are refactored
        out.
        """
        if paths is None:
            env = get_default_environment()
        else:
            env = get_environment(paths)

        dists = env.iter_installed_distributions(
            local_only=local_only,
            skip=skip,
            include_editables=include_editables,
            editables_only=editables_only,
            user_only=user_only,
        )
        return [cast(_Dist, dist)._dist for dist in dists]


log = logging.getLogger(__name__)


class FoundModule:
    def __init__(self, modname, filename, locations=None):
        self.modname = modname
        self.filename = os.path.realpath(filename)
        self.locations = locations or []  # filename, lineno

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
            if modpath is None:  # pragma: no cover
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
            with open(filename, encoding='utf-8') as f:
                content = f.read()
            vis.set_location(filename)
            vis.visit(ast.parse(content, filename))
    return vis.finalise()


def find_required_modules(options, requirements_filename: str):
    explicit = set()
    for requirement in parse_requirements(requirements_filename,
                                          session=PipSession()):
        try:
            requirement_name = requirement.name
        # The type of "requirement" changed between pip versions.
        # We exclude the "except" from coverage so that on any pip version we
        # can report 100% coverage.
        except AttributeError:  # pragma: no cover
            from pip._internal.req.constructors import install_req_from_line
            requirement_name = install_req_from_line(
                requirement.requirement,
            ).name

        if options.ignore_reqs(requirement):
            log.debug('ignoring requirement: %s', requirement_name)
            continue

        if options.skip_incompatible:
            requirement_string = requirement.requirement
            if not has_compatible_markers(requirement_string):
                log.debug('ignoring requirement (incompatible environment '
                          'marker): %s', requirement_string)
                continue

        log.debug('found requirement: %s', requirement_name)
        explicit.add(canonicalize_name(requirement_name))

    return explicit


def has_compatible_markers(full_requirement: str) -> bool:
    if ';' not in full_requirement:
        return True  # No environment marker.

    enviroment_marker = full_requirement.split(';')[1]
    if not enviroment_marker:
        return True  # Empty environment marker.

    return Marker(enviroment_marker).evaluate()


def is_package_file(path):
    '''Determines whether the path points to a Python package sentinel
    file - the __init__.py or its compiled variants.
    '''
    m = re.search(r'(.+)/__init__\.py[co]?$', path)
    if m is not None:
        return m.group(1)
    return ''


def ignorer(ignore_cfg):
    if not ignore_cfg:
        return lambda candidate: False

    def f(candidate, ignore_cfg=ignore_cfg):
        for ignore in ignore_cfg:
            try:
                from pip._internal.req.constructors import (
                    install_req_from_line,
                )
                candidate_path = install_req_from_line(  # pragma: no cover
                    candidate.requirement,
                ).name
            except (ImportError, AttributeError):
                try:
                    candidate_path = candidate.name
                except AttributeError:
                    candidate_path = candidate

            if fnmatch.fnmatch(candidate_path, ignore):
                return True
            elif fnmatch.fnmatch(os.path.relpath(candidate_path), ignore):
                return True
        return False

    return f
