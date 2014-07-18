from setuptools import setup
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

with open(path.join(here, 'CHANGELOG.rst'), encoding='utf-8') as f:
    long_description += f.read()

from pip_missing_reqs import __version__

setup(
    name='pip_missing_reqs',
    version=__version__,
    description='Find packages that should be in requirements for a project',
    long_description=long_description,
    url='https://github.com/r1chardj0n3s/pip-missing-reqs',
    author='Richard Jonees',
    author_email='r1chardj0n3s@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
    ],
    packages=['pip_missing_reqs'],
    entry_points={
        'console_scripts': [
            'pip-missing-reqs=pip_missing_reqs.find_missing_reqs:main',
        ],
    },
)
