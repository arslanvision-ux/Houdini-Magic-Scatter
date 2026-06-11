#!/usr/bin/env bash
# Magic Scatter World for Houdini - macOS / Linux installer launcher
# Double-click on macOS (Finder runs .command files in Terminal) or run from a shell.

set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    python3 install.py "$@"
elif command -v python >/dev/null 2>&1; then
    python install.py "$@"
else
    # Fall back to Houdini's bundled hython
    HFS_GUESSES=(
        "/Applications/Houdini/Houdini21.0"*"/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        "/Applications/Houdini/Houdini20.5"*"/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        "/Applications/Houdini/Houdini20.0"*"/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        "/Applications/Houdini/Houdini19.5"*"/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        "/Applications/Houdini/Houdini19.0"*"/Frameworks/Houdini.framework/Versions/Current/Resources/bin/hython"
        "/opt/hfs21.0"*"/bin/hython"
        "/opt/hfs20.5"*"/bin/hython"
        "/opt/hfs20.0"*"/bin/hython"
        "/opt/hfs19.5"*"/bin/hython"
        "/opt/hfs19.0"*"/bin/hython"
    )
    for pat in "${HFS_GUESSES[@]}"; do
        for hy in $pat; do
            if [ -x "$hy" ]; then
                "$hy" install.py "$@"
                exit $?
            fi
        done
    done

    echo
    echo "[Magic Scatter World] No Python interpreter found."
    echo "Install Python 3 from https://www.python.org/ and try again,"
    echo "or run 'hython install.py' from a Houdini Command Line Tools shell."
    exit 1
fi
