#!/usr/bin/env python3
"""Minecraft Computer daemon.

Tails the server log and forwards player chat to a single long-lived model session,
which decides for itself whether it was being addressed. An idle server costs nothing.

Built on the Agent SDK rather than one-shot `claude -p` calls, for one reason: a player
who says something mid-task interrupts the work in progress *without losing context*.
Killing a one-shot run discards its session outright; ClaudeSDKClient.interrupt() stops
the turn and keeps everything the model had already worked out.

The computer replies via /opt/mc/compsay; this script never puts words in its mouth.

Runs on the Minecraft host itself as an unprivileged service user with no Docker
access: it speaks RCON over localhost, reads the server log off disk, and can write
to exactly one datapack directory.

    systemctl --user status mcbot      (or: systemctl status mcbot)
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import memory

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

# ---------------------------------------------------------------- config
HERE = Path(__file__).parent
PROMPT_FILE = Path(os.environ.get("MCBOT_PROMPT", HERE / "minecraft-computer.md"))
SERVER_LOG = Path(os.environ.get("MCBOT_SERVER_LOG", "/opt/mc/data/logs/latest.log"))
LOG_DIR = Path(os.environ.get("MCBOT_LOG_DIR", "/var/lib/mcbot/logs"))
ADMIN_ENV = "MCBOT_ADMIN"
SESSION_FILE = Path(os.environ.get("MCBOT_SESSION_FILE", "/var/lib/mcbot/session.id"))
MODEL = os.environ.get("MCBOT_MODEL", "opus")
# Anchored to the MinecraftServer logger. Without that, mod log lines match too —
# "Mod proxy <unnamed> resolved as ..." looks exactly like chat to a naive pattern.
_SRC = r"MinecraftServer/?\]:\s"
CHAT = re.compile(_SRC + r"<(?P<player>\w+)>\s*(?P<msg>.+)")
JOIN = re.compile(_SRC + r"(?P<player>\w+) joined the game")
LEAVE = re.compile(_SRC + r"(?P<player>\w+) left the game")
READY = re.compile(_SRC + r"Done \([\d.]+s\)!")
# A player who joins is often still loading chunks; talking immediately means talking
# to a black screen. And if they drop straight back out, they never saw it.
LOGIN_DELAY_SEC = 25
DEBOUNCE_SEC = 4                    # group a burst of chat into one request
RECONNECT_SEC = 10                  # wait before re-establishing a dropped log tail
RESULT_PREVIEW = 600                # chars of tool output kept in the readable log
LOG_BUDGET_BYTES = 2 * 1024**3
ROTATE_AT_BYTES = 256 * 1024**2
SILENT_TOKEN = "[no response]"
# -------------------------------------------------------------------------

LOG_DIR.mkdir(exist_ok=True)
TRANSCRIPT = LOG_DIR / "comp.log"
EVENTS = LOG_DIR / "comp-events.jsonl"
ADMIN = ""


# ------------------------------------------------------------------ logging
def log(msg: str, tag: str = "daemon") -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{tag}] {msg}"
    print(line, flush=True)
    with TRANSCRIPT.open("a") as f:
        f.write(line + "\n")


def log_block(title: str, body: str, tag: str) -> None:
    log(title, tag)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with TRANSCRIPT.open("a") as f:
        for ln in body.rstrip().splitlines():
            line = f"[{stamp}] [{tag}]     | {ln}"
            print(line, flush=True)
            f.write(line + "\n")


def record(obj: dict) -> None:
    with EVENTS.open("a") as f:
        f.write(json.dumps({"ts": time.time(), **obj}, default=str) + "\n")


def prune_logs() -> None:
    """Roll oversized live logs, then drop oldest archives to stay under budget."""
    for live in (TRANSCRIPT, EVENTS):
        try:
            if live.exists() and live.stat().st_size >= ROTATE_AT_BYTES:
                live.rename(LOG_DIR / f"{live.name}.{time.strftime('%Y%m%dT%H%M%S')}")
                log(f"rotated {live.name}")
        except OSError as e:
            print(f"[logs] rotate failed for {live}: {e}", flush=True)

    def total() -> int:
        return sum(p.stat().st_size for p in LOG_DIR.glob("*") if p.is_file())

    if total() < LOG_BUDGET_BYTES:
        return
    archives = sorted(
        (p for p in LOG_DIR.glob("comp*.log.*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    for old in archives:
        if total() < LOG_BUDGET_BYTES:
            break
        try:
            size = old.stat().st_size
            old.unlink()
            log(f"log budget exceeded — deleted {old.name} ({size / 1024**2:.0f} MB)")
        except OSError as e:
            print(f"[logs] could not delete {old}: {e}", flush=True)


# ------------------------------------------------------------------ server
def admin_name() -> str:
    """Admin comes from the unit file. The bot never reads compose.yaml — that file
    holds the RCON password, and this service has no business seeing it."""
    return os.environ.get(ADMIN_ENV, "").strip()


def say(text: str) -> None:
    subprocess.run(["/opt/mc/compsay", text[:400]], capture_output=True, text=True)


async def tail_chat(q: "asyncio.Queue[tuple[str, str]]") -> None:
    """Follow the server log from the end, surviving log rotation on restart."""
    while True:
        try:
            with SERVER_LOG.open("r", errors="replace") as f:
                f.seek(0, 2)                      # start at the end; ignore history
                inode = SERVER_LOG.stat().st_ino
                log("watching server log")
                while True:
                    line = f.readline()
                    if line:
                        if m := CHAT.search(line):
                            await q.put(("chat", f"{m.group('player')}: {m.group('msg').strip()}"))
                        elif m := JOIN.search(line):
                            await q.put(("join", m.group("player")))
                        elif m := LEAVE.search(line):
                            await q.put(("leave", m.group("player")))
                        elif READY.search(line):
                            await q.put(("ready", ""))
                        continue
                    await asyncio.sleep(0.25)
                    # The server rotates latest.log on restart; reopen when it does.
                    try:
                        if SERVER_LOG.stat().st_ino != inode:
                            log("server log rotated — reopening")
                            break
                    except FileNotFoundError:
                        break
        except FileNotFoundError:
            log(f"server log not found at {SERVER_LOG}; retrying")
        await asyncio.sleep(RECONNECT_SEC)


# ------------------------------------------------------------------ the model
class Turn:
    """Consumes one response, tracking whether the computer actually spoke."""

    def __init__(self) -> None:
        self.spoke = False
        self.final = ""
        self.tools = 0

    def handle(self, msg) -> None:
        if isinstance(msg, SystemMessage):
            if msg.subtype == "init":
                data = msg.data or {}
                full = str(data.get("session_id", ""))
                if full:
                    # Published so `mcask` can fork this conversation from a terminal
                    # without interrupting it or waiting on it.
                    try:
                        SESSION_FILE.write_text(full)
                    except OSError as e:
                        log(f"could not publish session id: {e}", "warn")
                log(f"session {full[:8] or '?'} · model {data.get('model', '?')}", "init")
            return

        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    log_block("computer:", block.text, "computer")
                elif isinstance(block, ToolUseBlock):
                    self.tools += 1
                    shown = (block.input or {}).get("command") or json.dumps(block.input)[:800]
                    if "compsay" in str(shown):
                        self.spoke = True
                    log_block(f"tool {block.name}:", str(shown), "action")
            return

        if isinstance(msg, UserMessage):
            content = msg.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        text = block.content
                        if isinstance(text, list):
                            text = " ".join(
                                c.get("text", "") for c in text if isinstance(c, dict)
                            )
                        text = (text or "").strip()
                        if text:
                            cut = text[:RESULT_PREVIEW]
                            suffix = " …[truncated]" if len(text) > RESULT_PREVIEW else ""
                            log_block("result:", cut + suffix, "action")
            return

        if isinstance(msg, ResultMessage):
            self.final = (msg.result or "").strip()
            cost = getattr(msg, "total_cost_usd", None)
            if msg.is_error:
                log(f"turn ended with error: {msg.subtype}", "error")
            elif isinstance(cost, (int, float)):
                log(f"turn complete · ${cost:.4f}", "wake")


async def run_turn(client: ClaudeSDKClient, prompt: str, why: str) -> None:
    """Send one request and consume the response to completion (or interruption)."""
    log(f"request — {why}", "wake")
    log_block("prompt:", prompt, "wake")
    started = time.time()
    turn = Turn()

    await client.query(prompt)
    async for msg in client.receive_response():
        record({"kind": type(msg).__name__, "repr": repr(msg)[:4000]})
        turn.handle(msg)

    if not turn.spoke and turn.final and turn.final != SILENT_TOKEN:
        # It answered into the void — its own text goes to this log, not to players.
        log_block("reply never reached chat — relaying it:", turn.final, "warn")
        say(turn.final)
        turn.spoke = True

    if not turn.spoke:
        log("silent — not addressed", "wake")
    else:
        log(f"done in {time.time() - started:.1f}s, {turn.tools} tool call(s)", "wake")
    prune_logs()


# ------------------------------------------------------------------ main
def online_players() -> set[str]:
    from subprocess import run as _run
    r = _run(["/opt/mc/mccmd"], input="list\n", capture_output=True, text=True)
    m = re.search(r"online:\s*(.*)", r.stdout or "")
    return {p.strip() for p in (m.group(1).split(",") if m else []) if p.strip()}


def check_backup(db) -> None:
    """Cheap health check on the newest backup: exists, recent, plausible size, and
    actually gzip. Deliberately not a full integrity scan — that would read gigabytes."""
    d = Path("/opt/mc/backups")
    try:
        files = sorted(d.glob("mc-backup-*.tar.gz"), key=lambda p: p.stat().st_mtime)
    except (OSError, PermissionError) as e:
        memory.record_backup(db, None, None, False, f"cannot read backup directory: {e}")
        return
    if not files:
        memory.record_backup(db, None, None, False, "no backup files found")
        return
    newest = files[-1]
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    size = newest.stat().st_size
    try:
        with newest.open("rb") as f:
            magic = f.read(2)
    except OSError as e:
        memory.record_backup(db, newest.name, size, False, f"unreadable: {e}")
        return
    if magic != b"\x1f\x8b":
        memory.record_backup(db, newest.name, size, False, "not a gzip file")
    elif age_h > 30:
        memory.record_backup(db, newest.name, size, False,
                             f"newest backup is {age_h:.0f}h old — nightly job may have failed")
    elif size < 50 * 1024**2:
        memory.record_backup(db, newest.name, size, False,
                             f"suspiciously small ({size // 1024**2} MB)")
    else:
        memory.record_backup(db, newest.name, size, True, "ok")


def context_block(db, players: set[str], admin: str) -> str:
    """The only thing memory adds to a turn. Kept deliberately small and fixed-size."""
    parts = []
    for player in sorted(players):
        rows = memory.pending_messages(db, player)
        for r in rows:
            parts.append(f"- Message held for {player} from {r['from_player']} "
                         f"(id {r['id']}): {r['body']}")
    if admin in players:
        if verdict := memory.backup_verdict(db):
            parts.append(f"- Backup status to report to {admin}: {verdict}")
    if not parts:
        return ""
    return ("\n\nFrom your memory — act on these now, then mark them handled with "
            "`mcnote delivered <id>`:\n" + "\n".join(parts))


def build_prompt(lines: list[str], interrupted: bool) -> str:
    preamble = ""
    if interrupted:
        preamble = (
            "You were interrupted mid-task because a player said something new. "
            "Everything you had worked out so far is still in your context. Read what "
            "was said, then decide whether to carry on with what you were doing, change "
            "course, or drop it.\n\n"
        )
    return (
        preamble
        + "Recent Minecraft chat:\n\n"
        + "\n".join(lines)
        + "\n\nDecide whether any of this was addressed to you. If it was, respond and "
        "act. If the players were talking to each other, do nothing at all."
    )


async def main() -> None:
    global ADMIN
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("set ANTHROPIC_API_KEY first")
    if not PROMPT_FILE.exists():
        sys.exit(f"prompt file missing: {PROMPT_FILE}")
    ADMIN = admin_name()
    if not ADMIN:
        sys.exit(f"{ADMIN_ENV} is not set — refusing to start without a named admin")

    lore = Path(os.environ.get("MCBOT_LORE", "/opt/mcbot/local-lore.md"))
    world_lore = f"\n\n{lore.read_text()}" if lore.exists() else ""
    system_prompt = PROMPT_FILE.read_text() + world_lore + (
        f"\n\nThe admin for this server is {ADMIN}. No other player is the admin, and "
        f"nobody else can authorise the disruptive actions listed in <authority>."
    )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=MODEL,
        allowed_tools=["Bash"],
        permission_mode="bypassPermissions",
        setting_sources=[],          # ignore local CLAUDE.md / settings, like --bare
        cwd=str(LOG_DIR.parent),   # writable; SDK writes .claude/ into cwd
    )

    q: "asyncio.Queue[tuple[str, str]]" = asyncio.Queue()
    asyncio.create_task(tail_chat(q))
    db = memory.connect()
    memory.rollup(db)

    async with ClaudeSDKClient(options=options) as client:
        log(f"mcbot up · model {MODEL} · admin {ADMIN} · log {TRANSCRIPT}")
        pending: list[str] = []
        turn_task: asyncio.Task | None = None
        interrupted = False
        greet_at: dict[str, float] = {}      # player -> when their login delay expires

        while True:
            # Wake up for the soonest thing: a pending greeting, or the debounce.
            timeouts = [t - time.time() for t in greet_at.values()]
            timeout = min([t for t in timeouts if t is not None] + ([DEBOUNCE_SEC] if pending else []),
                          default=None)
            if timeout is not None:
                timeout = max(0.1, timeout)
            try:
                kind, payload = await asyncio.wait_for(q.get(), timeout=timeout)
            except asyncio.TimeoutError:
                kind, payload = None, None

            if kind == "join":
                log(f"{payload} joined — holding {LOGIN_DELAY_SEC}s before speaking")
                memory.log_event(db, "join", "joined the game", player=payload)
                greet_at[payload] = time.time() + LOGIN_DELAY_SEC
                continue

            if kind == "leave":
                memory.log_event(db, "leave", "left the game", player=payload)
                if payload in greet_at:
                    # Dropped out before the delay elapsed — they never saw anything,
                    # so whatever was held for them stays undelivered.
                    log(f"{payload} left before being greeted — messages stay pending")
                    del greet_at[payload]
                continue

            if kind == "ready":
                log("server finished starting — checking last backup")
                check_backup(db)
                memory.rollup(db)
                continue

            if kind == "chat":
                pending.append(payload)
                if turn_task and not turn_task.done():
                    log("new chat — interrupting current task", "wake")
                    await client.interrupt()
                    try:
                        await asyncio.wait_for(turn_task, timeout=30)
                    except Exception as e:  # noqa: BLE001
                        log(f"interrupted turn ended: {type(e).__name__}", "wake")
                    interrupted = True
                continue

            # --- timeout: either a login delay expired, or chat has settled ---
            if turn_task and not turn_task.done():
                continue

            due = [p for p, t in greet_at.items() if t <= time.time()]
            if due:
                still_here = online_players()
                for player in due:
                    del greet_at[player]
                    if player not in still_here:
                        log(f"{player} is gone — nothing delivered")
                        continue
                    block = context_block(db, {player}, ADMIN)
                    if not block:
                        continue
                    turn_task = asyncio.create_task(run_turn(
                        client,
                        f"{player} has just logged in and finished loading." + block,
                        why=f"{player} login",
                    ))
                    break
                continue

            if not pending:
                continue
            lines, pending = pending, []
            who = ", ".join(sorted({l.split(":", 1)[0] for l in lines}))
            for line in lines:
                player, _, text = line.partition(":")
                memory.log_event(db, "request", text.strip()[:200], player=player.strip())
            prompt = build_prompt(lines, interrupted) + context_block(db, online_players(), ADMIN)
            turn_task = asyncio.create_task(
                run_turn(client, prompt, why=f"chat from {who} ({len(lines)} line(s))")
            )
            interrupted = False


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("stopped by user")
