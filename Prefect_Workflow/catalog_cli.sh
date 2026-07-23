#!/usr/bin/env bash
# catalog_cli.sh — put credentials.py's folder on PYTHONPATH so catalog.py can import it.
# Source this file (source ./catalog_cli.sh) so the exported PYTHONPATH persists in the shell.
# Author: yRocket
__version__="0.0.0.2026.7.22"  # Semantic Versioning: Major.Minor.Patch.Date(YYYY.M.D)

# add_pypath: prepend a .py file's folder to PYTHONPATH (dedup, keep existing) so its module can be imported.
add_pypath() {
    local dir rest
    dir=$(cd "$(dirname "$1")" && pwd) || { echo "add_pypath: cannot resolve $1" >&2; return 1; }
    rest=$(printf '%s' "$PYTHONPATH" | tr ':' '\n' | grep -vxF "$dir" | grep -v '^$' | paste -sd ':' -)
    export PYTHONPATH="$dir${rest:+:$rest}"
}
add_pypath ../Docker/Prefect/credentials.py   # catalog.py imports credentials.py from this folder
echo "$PYTHONPATH"
