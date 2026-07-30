#!/usr/bin/env bash

set -euo pipefail

git checkout master
git pull
uv pip install --upgrade twine build
rm -rf build dist

if [[ -n "$(git status --porcelain)" ]]; then
    echo "The working tree must be clean before creating a release." >&2
    exit 1
fi

version="$(
    uv run python -c \
        "from pip_check_reqs import __version__; print(__version__)"
)"

if git rev-parse --verify --quiet "refs/tags/${version}" > /dev/null; then
    echo "The tag ${version} already exists." >&2
    exit 1
fi

uv run python -m build
uv run twine upload --username=__token__ -r pypi dist/*
git tag --annotate "${version}" --message "Release ${version}"
git push origin "${version}"
