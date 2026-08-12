#!/usr/bin/env bash

set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

if ! command -v code >/dev/null 2>&1; then
    echo "The VS Code 'code' command is not available in this shell." >&2
    echo "Install it from VS Code's Command Palette with: Shell Command: Install 'code' command in PATH" >&2
    exit 1
fi

cd "$repo_dir"
uv sync --locked
exec code "$repo_dir"
