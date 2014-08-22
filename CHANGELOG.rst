
Release History
---------------

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
