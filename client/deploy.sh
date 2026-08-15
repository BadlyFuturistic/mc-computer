#!/usr/bin/env bash
# deploy.sh — push this repo to the Minecraft host.
#
#   ./deploy.sh              tools + bot code + prompt, then restart the service
#   ./deploy.sh --prompt     prompt only (no service restart needed for tools)
#   ./deploy.sh --no-restart copy everything, leave the service running old code
#   ./deploy.sh --setup      also run the privileged installer (asks for sudo)
#   ./deploy.sh --personas   replace deployed personas that differ from the repo
#
# Secrets are never transferred. The API key and RCON password live only in
# /etc/mcbot on the server, installed once by setup/mcbot-setup.sh.
set -euo pipefail

HOST="${MC_HOST:-mc-public}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE=/tmp/mcbot-stage

PROMPT_ONLY=false
RESTART=true
RUN_SETUP=false
FORCE_PERSONAS=false
for arg in "$@"; do
    case "$arg" in
        --prompt)     PROMPT_ONLY=true ;;
        --no-restart) RESTART=false ;;
        --setup)      RUN_SETUP=true ;;
        --personas)   FORCE_PERSONAS=true ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done

echo "==> staging on $HOST"
ssh "$HOST" "mkdir -p $STAGE"

if [[ "$PROMPT_ONLY" == false ]]; then
    echo "==> server tools -> /opt/mc"
    # One list drives both the copy and the modes, so a new tool cannot be copied and
    # then left unrunnable. Regular files only: a stray __pycache__ from running the
    # tools locally is a directory, and scp aborts the whole transfer on it.
    NAMES=$(cd "$REPO/server/bin" && ls -p | grep -v '/$' | tr '\n' ' ')
    (cd "$REPO/server/bin" && scp -q $NAMES "$HOST:/opt/mc/")
    # Libraries stay 644; everything else is a command and needs to be executable.
    ssh "$HOST" "cd /opt/mc && for f in $NAMES; do
        case \$f in *.py) chmod 644 \"\$f\" ;; *) chmod 755 \"\$f\" ;; esac
    done"
fi

echo "==> stamping build"
# Version plus commit, so "what is running" has an unambiguous answer later.
BUILD_JSON=$(printf '{"version":"%s","commit":"%s","deployed":"%s"}' \
    "$(cat "$REPO/VERSION" 2>/dev/null | tr -d '\n')" \
    "$(cd "$REPO" && git rev-parse --short HEAD 2>/dev/null)$(cd "$REPO" && git diff --quiet 2>/dev/null || echo '-dirty')" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
echo "$BUILD_JSON" | ssh "$HOST" "cat > $STAGE/BUILD"
echo "    $BUILD_JSON"

echo "==> bot code + prompt -> staging"
scp -q "$REPO/server/mcbot/comp-daemon.py"        "$HOST:$STAGE/comp-daemon.py"
scp -q "$REPO/server/mcbot/memory.py"             "$HOST:$STAGE/memory.py"
scp -q "$REPO/server/mcbot/config.py"             "$HOST:$STAGE/config.py"
scp -q "$REPO/server/mcbot/runas.py"              "$HOST:$STAGE/runas.py"
ssh "$HOST" "mkdir -p $STAGE/personas"
scp -q "$REPO"/server/personas/*.md               "$HOST:$STAGE/personas/"
scp -q "$REPO/server/mcbot/minecraft-computer.md" "$HOST:$STAGE/minecraft-computer.md"
scp -q "$REPO/server/systemd/mcbot.service"       "$HOST:$STAGE/mcbot.service"
scp -q "$REPO"/server/systemd/mcbot-acl.*         "$HOST:$STAGE/"
scp -q "$REPO/server/setup/mcbot-setup.sh"        "$HOST:$STAGE/mcbot-setup.sh"

if [[ "$RUN_SETUP" == true ]]; then
    echo "==> running privileged installer (sudo)"
    ssh -t "$HOST" "sudo bash $STAGE/mcbot-setup.sh"
    exit 0
fi

# /opt/mcbot is root-owned so the service cannot rewrite its own code; installing
# there and restarting both need sudo.
echo "==> installing bot files (sudo)"
ssh -t "$HOST" "
    sudo install -o root -g root -m 644 $STAGE/BUILD                 /opt/mcbot/BUILD &&
    sudo install -o root -g root -m 755 $STAGE/comp-daemon.py        /opt/mcbot/comp-daemon.py &&
    sudo install -o root -g root -m 644 $STAGE/memory.py             /opt/mcbot/memory.py &&
    sudo install -o root -g root -m 644 $STAGE/config.py             /opt/mcbot/config.py &&
    sudo install -o root -g root -m 644 $STAGE/runas.py              /opt/mcbot/runas.py &&
    sudo install -d -o root -g root -m 755 /opt/mcbot/personas &&
    for f in $STAGE/personas/*.md; do
        b=\$(basename \$f); d=/opt/mcbot/personas/\$b
        if [ ! -e \$d ]; then
            sudo install -o root -g root -m 644 \$f \$d && echo \"    + \$b new\"
        elif ! cmp -s \$f \$d; then
            if [ "$FORCE_PERSONAS" = true ]; then
                sudo install -o root -g root -m 644 \$f \$d && echo \"    ~ \$b replaced\"
            else
                echo \"    ! \$b differs from the deployed copy; use --personas to replace it\"
            fi
        fi
    done &&
    sudo /opt/mcbot/venv/bin/python /opt/mcbot/config.py &&
    sudo install -o root -g root -m 644 $STAGE/minecraft-computer.md /opt/mcbot/minecraft-computer.md &&
    sudo install -o root -g root -m 644 $STAGE/mcbot.service         /etc/systemd/system/mcbot.service &&
    sudo systemctl daemon-reload &&
    $( [[ "$RESTART" == true ]] && echo 'sudo systemctl restart mcbot && sleep 4 && systemctl is-active mcbot' || echo 'echo \"service left running old code\"' )
"

echo "==> done"
