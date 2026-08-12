#!/bin/bash
# mcbot-setup.sh — create the locked-down service account and install the unit.
# Run once, on mc-public, with sudo. Everything here needs root; nothing else does.
set -euo pipefail

STAGE=/tmp/mcbot-stage          # files uploaded ahead of this script
BOT=/opt/mcbot
STATE=/var/lib/mcbot
ETC=/etc/mcbot

echo "==> service account (no shell, no docker group, no sudo group)"
if ! id mcbot &>/dev/null; then
  useradd --system --home-dir "$BOT" --shell /usr/sbin/nologin mcbot
fi

echo "==> directories"
install -d -o mcbot -g mcbot -m 750 "$BOT" "$STATE"
# Logs are group-readable by the admin so they can be tailed without sudo,
# while staying unwritable by anyone but the service.
install -d -o mcbot -g "$(stat -c %U /opt/mc)" -m 750 "$STATE/logs"
install -d -o root  -g mcbot -m 750 "$ETC"

echo "==> program files (root-owned; the bot can read and run, never modify)"
install -o root -g root -m 755 "$STAGE/comp-daemon.py"            "$BOT/comp-daemon.py"
install -o root -g root -m 644 "$STAGE/memory.py"                 "$BOT/memory.py"
install -o root -g root -m 644 "$STAGE/minecraft-computer.md"     "$BOT/minecraft-computer.md"

echo "==> secrets, readable only by mcbot"
RCON_PASS="$(grep -oP 'RCON_PASSWORD:\s*"\K[^"]+' /opt/mc/compose.yaml)"
ADMIN="$(grep -oP 'OPS:\s*"?\K[^",]+' /opt/mc/compose.yaml)"
# Re-running must never blank the key: take it from the stage if present, else keep
# whatever is already installed.
if [[ -s "$STAGE/api.key" ]]; then
  API_KEY="$(cat "$STAGE/api.key")"
elif [[ -f "$ETC/env" ]]; then
  API_KEY="$(grep -oP '^ANTHROPIC_API_KEY=\K.*' "$ETC/env" || true)"
else
  API_KEY=""
fi
if [[ -z "$API_KEY" ]]; then
  echo "ERROR: no API key. Put it at $STAGE/api.key and re-run." >&2
  exit 1
fi
umask 077
cat > "$ETC/env" <<EOF
ANTHROPIC_API_KEY=${API_KEY}
RCON_PASSWORD=${RCON_PASS}
RCON_HOST=127.0.0.1
RCON_PORT=25575
MCBOT_ADMIN=${ADMIN}
EOF
chown root:mcbot "$ETC/env"
chmod 640 "$ETC/env"
printf '%s' "${RCON_PASS}" > "$ETC/rcon.pass"
# The admin runs mcask from a terminal and needs the same key; they own the box
# anyway, so this grants read without widening what the service group can see.
# The admin runs mcask from a terminal and needs the same key. Grant traverse on the
# directory as well as read on the file — the file ACL alone is unreachable without it.
ADMIN_USER="$(stat -c %U /opt/mc)"
setfacl -m "u:${ADMIN_USER}:rx" "$ETC" 2>/dev/null || true
setfacl -m "u:${ADMIN_USER}:r"  "$ETC/env" 2>/dev/null || true
chown root:mcbot "$ETC/rcon.pass"
chmod 640 "$ETC/rcon.pass"
rm -f "$STAGE/api.key"

echo "==> backups: readable and writable only by the owner, invisible to the bot"
OWNER="$(stat -c %U /opt/mc)"
chown -R "$OWNER:$OWNER" /opt/mc/backups
chmod 750 /opt/mc/backups
chmod 640 /opt/mc/backups/*.tar.gz 2>/dev/null || true

echo "==> the one directory the bot may write inside the world"
install -d -o mcbot -g "$OWNER" -m 775 /opt/mc/data/world/datapacks/mcbuilds

echo "==> spend limit (root-owned: readable by the bot, editable only by you)"
if [[ ! -f "$ETC/limits" ]]; then
  cat > "$ETC/limits" <<'EOF'
# Maximum model spend per day, in USD. The bot reads this fresh on every check, so a
# change takes effect immediately with no restart. It cannot write to this file.
DAILY_USD_LIMIT=50
EOF
fi
chown root:mcbot "$ETC/limits"
chmod 640 "$ETC/limits"
# Root-owned so the bot cannot raise its own ceiling. The admin may read it — they can
# already edit it with sudo, so withholding it only breaks their tooling.
setfacl -m "u:${ADMIN_USER}:r" "$ETC/limits" 2>/dev/null || true

echo "==> crash report directory"
install -d -o mcbot -g "$OWNER" -m 750 /var/lib/mcbot/crash-reports

echo "==> read access to everything under /opt/mc/data and the backups"
# Default ACLs so files the server rewrites (it recreates them mode 600) stay
# readable without having to revisit this for every new mod.
if command -v setfacl >/dev/null; then
  setfacl -R -m u:mcbot:rX -m d:u:mcbot:rX /opt/mc/data
  setfacl -R -m u:mcbot:rX -m d:u:mcbot:rX /opt/mc/backups
else
  echo "WARNING: setfacl not found (apt install acl) — bot will not be able to read world data" >&2
fi

echo "==> sudoers: exactly three fixed commands, no wildcards, no arguments it controls"
cat > /etc/sudoers.d/mcbot <<'EOF'
Cmnd_Alias MCBOT_CMDS = /usr/bin/docker restart mc, \
                        /usr/bin/docker compose -f /opt/mc/compose.yaml down, \
                        /usr/bin/docker compose -f /opt/mc/compose.yaml up -d, \
                        /opt/mc/mcbackup
mcbot ALL=(root) NOPASSWD: MCBOT_CMDS
EOF
# The admin asks questions from a terminal with mcask, which must run as the service
# account to reach its session store. SETENV allows the HOME override it needs.
cat >> /etc/sudoers.d/mcbot <<EOF
${ADMIN_USER} ALL=(mcbot) NOPASSWD: SETENV: /opt/mc/mcask
EOF
chmod 440 /etc/sudoers.d/mcbot
visudo -c -f /etc/sudoers.d/mcbot

echo "==> python environment"
install -d -o mcbot -g mcbot -m 750 "$BOT/venv"
sudo -H -u mcbot python3 -m venv "$BOT/venv"
sudo -H -u mcbot "$BOT/venv/bin/pip" install -q --upgrade pip claude-agent-sdk

echo "==> let the admin read the program dir (needed to run mcask from a terminal)"
chgrp -R "$OWNER" "$BOT"
chmod -R g+rX "$BOT"

echo "==> ACL refresh timer"
install -o root -g root -m 644 "$STAGE/mcbot-acl.service" /etc/systemd/system/mcbot-acl.service
install -o root -g root -m 644 "$STAGE/mcbot-acl.timer"   /etc/systemd/system/mcbot-acl.timer

echo "==> service"
install -o root -g root -m 644 "$STAGE/mcbot.service" /etc/systemd/system/mcbot.service
systemctl daemon-reload
systemctl enable --now mcbot-acl.timer
systemctl enable --now mcbot

echo
echo "done. status:"
systemctl --no-pager --lines=15 status mcbot || true
