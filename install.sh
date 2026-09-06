#!/usr/bin/env bash
set -euo pipefail

SKILL_NAME="evm-bytecode-decompiler"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/.agents/skills/$SKILL_NAME"

if [ -z "${HOME:-}" ]; then
    echo "error: HOME must be set" >&2
    exit 1
fi

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
TARGET="all"

usage() {
    cat <<'EOF'
Usage: ./install.sh [--target all|codex|claude]

Install the evm-bytecode-decompiler Agent Skill without overwriting an existing target.

Environment:
  CODEX_HOME   Codex home directory (default: $HOME/.codex)
  CLAUDE_HOME  Claude Code home directory (default: $HOME/.claude)
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --target)
            if [ "$#" -lt 2 ]; then
                echo "error: --target requires all, codex, or claude" >&2
                exit 2
            fi
            TARGET="$2"
            shift 2
            ;;
        --target=*)
            TARGET="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$TARGET" in
    all|codex|claude) ;;
    *)
        echo "error: invalid target: $TARGET (expected all, codex, or claude)" >&2
        exit 2
        ;;
esac

if [ ! -d "$SOURCE_DIR" ] || [ ! -f "$SOURCE_DIR/SKILL.md" ]; then
    echo "error: Skill source is missing: $SOURCE_DIR" >&2
    exit 1
fi

DESTINATIONS=()
LABELS=()
add_destination() {
    DESTINATIONS+=("$1")
    LABELS+=("$2")
}

case "$TARGET" in
    all)
        add_destination "$CODEX_HOME/skills/$SKILL_NAME" "Codex"
        add_destination "$CLAUDE_HOME/skills/$SKILL_NAME" "Claude Code"
        ;;
    codex)
        add_destination "$CODEX_HOME/skills/$SKILL_NAME" "Codex"
        ;;
    claude)
        add_destination "$CLAUDE_HOME/skills/$SKILL_NAME" "Claude Code"
        ;;
esac

# Check every selected destination before creating any parent directory or payload.
for destination in "${DESTINATIONS[@]}"; do
    if [ -e "$destination" ] || [ -L "$destination" ]; then
        echo "error: destination already exists: $destination" >&2
        echo "       remove it deliberately before reinstalling" >&2
        exit 1
    fi
done

# Create all parents first so a bad target path cannot leave a partial install.
for destination in "${DESTINATIONS[@]}"; do
    mkdir -p "$(dirname -- "$destination")"
done

STAGING_DIRS=()
cleanup() {
    for staging_dir in "${STAGING_DIRS[@]}"; do
        rm -rf "$staging_dir"
    done
}
trap cleanup EXIT HUP INT TERM

for index in "${!DESTINATIONS[@]}"; do
    destination="${DESTINATIONS[$index]}"
    parent="$(dirname -- "$destination")"
    staging_dir="$(mktemp -d "$parent/.$SKILL_NAME.install.XXXXXX")"
    STAGING_DIRS+=("$staging_dir")

    cp -pR "$SOURCE_DIR/." "$staging_dir/"
    if [ ! -f "$staging_dir/SKILL.md" ]; then
        echo "error: staged Skill is incomplete: $staging_dir" >&2
        exit 1
    fi

    mv "$staging_dir" "$destination"
    echo "Installed $SKILL_NAME for ${LABELS[$index]}: $destination"
done
