#!/usr/bin/env bash
# deploy.sh — push this repo to the Minecraft host.
#
#   ./deploy.sh              tools + bot code + prompt, then restart the service
#   ./deploy.sh --prompt     prompt only (no service restart needed for tools)
#   ./deploy.sh --no-restart copy everything, leave the service running old code
#   ./deploy.sh --setup      also run the privileged installer (asks for sudo)
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
for arg in "$@"; do
    case "$arg" in
        --prompt)     PROMPT_ONLY=true ;;
        --no-restart) RESTART=false ;;
        --setup)      RUN_SETUP=true ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done

echo "==> staging on $HOST"
ssh "$HOST" "mkdir -p $STAGE"

if [[ "$PROMPT_ONLY" == false ]]; then
    echo "==> server tools -> /opt/mc"
    scp -q "$REPO"/server/bin/* "$HOST:/opt/mc/"
    ssh "$HOST" "chmod 755 /opt/mc/{compsay,mccmd,mcbuild,mcbag,mcwhere,mctp,mcrestart,mcbackup,mcmotd,mcnote,mcask,mcthink} && chmod 644 /opt/mc/mcrcon.py"
fi

echo "==> bot code + prompt -> staging"
scp -q "$REPO/server/mcbot/comp-daemon.py"        "$HOST:$STAGE/comp-daemon.py"
scp -q "$REPO/server/mcbot/memory.py"             "$HOST:$STAGE/memory.py"
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
    sudo install -o root -g root -m 755 $STAGE/comp-daemon.py        /opt/mcbot/comp-daemon.py &&
    sudo install -o root -g root -m 644 $STAGE/memory.py             /opt/mcbot/memory.py &&
    sudo install -o root -g root -m 644 $STAGE/minecraft-computer.md /opt/mcbot/minecraft-computer.md &&
    sudo install -o root -g root -m 644 $STAGE/mcbot.service         /etc/systemd/system/mcbot.service &&
    sudo systemctl daemon-reload &&
    $( [[ "$RESTART" == true ]] && echo 'sudo systemctl restart mcbot && sleep 4 && systemctl is-active mcbot' || echo 'echo \"service left running old code\"' )
"

echo "==> done"
