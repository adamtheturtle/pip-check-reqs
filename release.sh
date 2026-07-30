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

uv run python -m build
uv run twine upload --username=__token__ -r pypi dist/*
