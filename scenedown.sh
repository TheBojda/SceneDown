#!/usr/bin/env bash

set -e

# ==========================================
# LOAD ENV
# ==========================================

if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# ==========================================
# CONFIG
# ==========================================

PYTHON_SCRIPT="scenedown_narration.py"

# ==========================================
# COMMANDS
# ==========================================

COMMAND="$1"

shift || true

case "$COMMAND" in

    narration)
        python3 "$PYTHON_SCRIPT" "$@"
        ;;

    *)
        echo "Usage:"
        echo "  ./scenedown.sh narration <project-directory>"
        exit 1
        ;;

esac