#!/usr/bin/env bash

set -e

# ==========================================
# ACTIVATE VENV
# ==========================================

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# ==========================================
# LOAD ENV
# ==========================================

if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# ==========================================
# CONFIG
# ==========================================

NARRATION_SCRIPT="scenedown_narration.py"
ALIGNMENT_SCRIPT="scenedown_alignment.py"
VIDEO_SCRIPT="scenedown_video.py"

# ==========================================
# COMMANDS
# ==========================================

COMMAND="$1"

shift || true

case "$COMMAND" in

    narration)
        python3 "$NARRATION_SCRIPT" "$@"
        ;;

    alignment)
        python3 "$ALIGNMENT_SCRIPT" "$@"
        ;;

    video)
        python3 "$VIDEO_SCRIPT" "$@"
        ;;

    all)
        python3 "$NARRATION_SCRIPT" "$@"
        python3 "$ALIGNMENT_SCRIPT" "$@"
        python3 "$VIDEO_SCRIPT" "$@"
        ;;

    *)
        echo "Usage:"
        echo "  ./scenedown.sh narration <project-directory>"
        echo "  ./scenedown.sh alignment <project-directory>"
        echo "  ./scenedown.sh video <project-directory>"
        echo "  ./scenedown.sh all <project-directory>"
        exit 1
        ;;

esac