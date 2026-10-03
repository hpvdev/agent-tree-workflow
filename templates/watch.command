#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
exec python3 .agent-tree/watch.py
