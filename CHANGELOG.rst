
Release History
---------------

2.4.4

- Bump `packaging` requirement to >= 20.5. Older versions of `pip-check-reqs`     may be broken with the previously-specified version requirements.

2.4.3

- Improves performance on Python 3.11.

2.4.2

- Added support for Python 3.11.
- Added `python_requires` to metadata; from now on, releases of
  `pip-check-reqs` are marked as compatible with Python 3.8.0 and up.
- Made `--version` flag show interpretter version and path to the package which
  pip-check-reqs is running from, similar to information shown by `pip
  --version`.
- `-V` is now an alias of `--version`.

2.3.2

- Fixed support for pip < 21.3

2.3.1

- Fixed `--skip-incompatible` skipping other requirements too.
- Support pip >= 21.3

2.3.0

- Support pip >= 21.2.1

2.2.2

- AST parsing failures will now report tracebacks with a proper filename for
  the parsed frame, instead of `<unknown>`.

2.2.1

- Python source is now always read using utf-8, even if default encoding for
  reading files is set otherwise.

2.2.0

- Added `--skip-incompatible` flag to `pip-extra-reqs`, which makes it ignore
  requirements with environment markers that are incompatible with the current
  environment.
- Added `--requirements-file` flag to `pip-extra-reqs` and `pip-missing-reqs`
  commands. This flag makes it possible to specify a path to the requirements
  file. Previously, `"requirements.txt"` was always used.
- Fixed some of the logs not being visible with `-d` and `-v` flags.

2.1.1

- Bug fix: Though Python 2 support was removed from the source code, the published wheel was still universal.
  The published wheel now explicitly does not support Python 2.
  Please use version 2.0.4 for Python 2.

2.1.0

- Remove support for Python 2.
  Please use an older version of this tool if you require that support.
- Remove requirement for setuptools.
- Support newer versions of pip, including the current version, for more features (20.1.1).
  Thanks to @Czaki for important parts of this change.

2.0.1

- handled removal of normalize_name from pip.utils
- handle packages with no files

2.0 **renamed package to pip_check_reqs**

- added tool pip-extra-reqs to find packages installed but not used
  (contributed by Josh Hesketh)

1.2.1

- relax requirement to 6.0+

1.2.0

- bumped pip requirement to 6.0.8+
- updated use of pip internals to match that version

1.1.9

- test fixes and cleanup
- remove hard-coded simplejson debugging behaviour

1.1.8

- use os.path.realpath to avoid symlink craziness on debian/ubuntu

1.1.7

- tweak to debug output

1.1.6

- add debug (very verbose) run output

1.1.5

- add header to output to make it clearer when in a larger test run
- fix tests and self-test

1.1.4

- add --version
- remove debug print from released code lol

1.1.3

- fix program to generate exit code useful for testing

1.1.2

- corrected version of vendored search_packages_info() from pip
- handle relative imports

1.1.1

- fixed handling of import from __future__
- self-tested and added own requirements.txt
- cleaned up usage to require a file or directory to scan (rather than
  defaulting to ".")
- vendored code from pip 1.6dev which fixes bug in search_packages_info
  until pip 1.6 is released

1.1.0

- implemented --ignore-module
