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
import hashlib
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
MODEL = os.environ.get("MCBOT_MODEL", "sonnet")   # escalate to opus per-task, see mcthink
EFFORT = os.environ.get("MCBOT_EFFORT", "low")   # low|medium|high — medium if it gets sloppy
LIMITS_FILE = Path("/etc/mcbot/limits")            # root-owned; the bot cannot edit it

# Rollover happens only during silence, never mid-conversation: a turn-count cap would
# eventually cut someone off mid-project. Cost per turn grows with transcript length,
# so a fresh session resets it — durable knowledge lives in memory.db, not the transcript.
IDLE_ROLLOVER_MIN = 20        # quiet this long, start a fresh session
BUSY_TURNS = 25               # after this many turns in one session...
BUSY_IDLE_ROLLOVER_MIN = 5    # ...roll at the first shorter pause

CRASH_DIR = Path("/opt/mc/data/crash-reports")
REPORT_DIR = Path("/var/lib/mcbot/crash-reports")
CRASH_COOLDOWN_MIN = 15       # never look at two crashes closer together than this
CRASH_REPORTS_PER_DAY = 3     # after this, keep counting crashes but stop thinking
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
# Approval for a Fable request. Matched against the admin's raw chat by the daemon,
# so the model cannot grant itself permission by claiming it was given.
APPROVE_FABLE = re.compile(r"\b(approve|approved|yes|go ahead|allow)\b.*\bfable\b"
                           r"|\bfable\b.*\b(approved?|ok|okay|yes|go ahead|allowed)\b", re.I)
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
    """Follow the server log, surviving rotation without dropping the lines it hides."""
    first_open = True
    while True:
        try:
            with SERVER_LOG.open("r", errors="replace") as f:
                # Only skip history on the very first open. After a rotation the new
                # latest.log starts empty, so reading it from the beginning recovers
                # anything written between the rotation and this reopen — otherwise
                # chat sent in that window is lost with no sign that it happened.
                if first_open:
                    f.seek(0, 2)
                    first_open = False
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
        self.cost = 0.0

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
            if isinstance(cost, (int, float)):
                self.cost = float(cost)
            if msg.is_error:
                log(f"turn ended with error: {msg.subtype}", "error")
            elif isinstance(cost, (int, float)):
                spent = max(0.0, cost - SESSION_COST["seen"])
                log(f"turn complete · ${spent:.4f}", "wake")


# total_cost_usd on a ResultMessage is the SESSION's running total, not this turn's
# cost. Recording it directly counts every turn once more for each turn that follows,
# so what we log and bill against is the delta since the previous result in the same
# session. Reset to 0.0 whenever a new session starts.
SESSION_COST = {"seen": 0.0}


async def run_turn(client: ClaudeSDKClient, prompt: str, why: str,
                   db=None, source: str = "chat") -> None:
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

    cumulative = getattr(turn, "cost", 0.0) or 0.0
    this_turn = max(0.0, cumulative - SESSION_COST["seen"])
    if cumulative:
        SESSION_COST["seen"] = cumulative
    if db is not None:
        memory.record_spend(db, source, MODEL, this_turn)

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


def daily_limit() -> float:
    """Spend ceiling, read fresh each time so raising it needs no restart. Lives in a
    root-owned file: the bot can read it and cannot change it."""
    try:
        for line in LIMITS_FILE.read_text().splitlines():
            if line.strip().startswith("DAILY_USD_LIMIT"):
                return float(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return 50.0


def crash_signature(text: str) -> str:
    """Identify a crash by its exception and top frame, so a loop is recognisable."""
    exc = re.search(r"^(?:Description|Exception).*?:\s*(.+)$", text, re.M)
    frame = re.search(r"^\s*at ([\w.$]+)", text, re.M)
    raw = f"{(exc.group(1) if exc else 'unknown')[:120]}|{frame.group(1) if frame else '?'}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def new_crash_reports() -> list[Path]:
    try:
        return sorted(CRASH_DIR.glob("crash-*.txt"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []


async def handle_crash(client, db, path: Path) -> bool:
    """Write a report for a server crash, unless we have already seen this one.

    Three layers of protection, because an unattended crash loop is where money
    disappears: identical crashes only ever update a counter, reports are capped per
    day, and a cooldown stops a fast loop firing even that many times.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        log(f"crash file unreadable: {e}", "warn")
        return False

    sig = crash_signature(text)
    is_new, seen = memory.crash_seen(db, sig)

    if not is_new:
        log(f"crash {sig} seen again (x{seen}) — counter updated, not investigating", "warn")
        existing = db.execute("SELECT report FROM crashes WHERE signature = ?", (sig,)).fetchone()
        if existing and existing["report"]:
            try:
                with open(existing["report"], "a") as f:
                    f.write(f"\n- Recurred {time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
                            f"(occurrence {seen}) — {path.name}\n")
            except OSError:
                pass
        return False

    if memory.crashes_reported_today(db) >= CRASH_REPORTS_PER_DAY:
        log(f"crash {sig} is new, but the daily report budget is spent — not investigating",
            "warn")
        return False

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H%M%S%z")
    report = REPORT_DIR / f"{stamp}.md"

    await run_turn(
        client,
        "The Minecraft server crashed. A crash report was written to "
        f"{path}. Read it, work out what happened, and write your findings to "
        f"{report} as markdown: what crashed, the most likely cause, which mod or "
        "component is implicated, and whether it is likely to recur. Be concise and "
        "concrete. Do not announce anything in chat — nobody may be online. If the "
        "cause is obvious and harmless, say so in two lines rather than speculating.",
        why=f"server crash ({path.name})",
        db=db, source="crash",
    )
    memory.set_crash_report(db, sig, str(report))
    memory.log_event(db, "crash", f"crash investigated, report at {report.name}")
    return True


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

    opts = dict(
        system_prompt=system_prompt,
        model=MODEL,
        # Routine chat needs lookups and a sentence, not deliberation. Thinking bills as
        # output, several times the input rate, on every one of the ~4 requests a turn
        # makes — which is most of what a simple question costs. Hard problems go to
        # mcthink, which runs at full effort deliberately.
        effort=EFFORT,
        allowed_tools=["Bash"],
        permission_mode="bypassPermissions",
        setting_sources=[],          # ignore local CLAUDE.md / settings, like --bare
        cwd=str(LOG_DIR.parent),   # writable; SDK writes .claude/ into cwd
    )

    q: "asyncio.Queue[tuple[str, str]]" = asyncio.Queue()
    asyncio.create_task(tail_chat(q))
    db = memory.connect()
    memory.rollup(db)
    seen_crashes = {p.name for p in new_crash_reports()}   # ignore ones already on disk

    def make_client() -> ClaudeSDKClient:
        return ClaudeSDKClient(options=ClaudeAgentOptions(**opts))

    client = make_client()
    await client.connect()
    # Record the build this process loaded. Files on disk tell you what was deployed;
    # only the process can say what it is actually running.
    build = {}
    try:
        build = json.loads(Path("/opt/mcbot/BUILD").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    try:
        (LOG_DIR.parent / "runtime.json").write_text(json.dumps({
            **build, "pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "model": MODEL, "effort": EFFORT,
        }))
    except OSError as e:
        log(f"could not record runtime build: {e}", "warn")

    log(f"mcbot up · {build.get('version', '?')} ({build.get('commit', '?')}) · "
        f"model {MODEL} · effort {EFFORT} · admin {ADMIN}")

    pending: list[str] = []
    turn_task: asyncio.Task | None = None
    interrupted = False
    greet_at: dict[str, float] = {}
    turns_this_session = 0
    last_activity = time.time()
    fresh_session = True

    try:
        while True:
            idle_needed = (BUSY_IDLE_ROLLOVER_MIN if turns_this_session >= BUSY_TURNS
                           else IDLE_ROLLOVER_MIN) * 60
            waits = [t - time.time() for t in greet_at.values()]
            if pending:
                waits.append(DEBOUNCE_SEC)
            if turns_this_session:
                waits.append(last_activity + idle_needed - time.time())
            timeout = max(0.1, min(waits)) if waits else None

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
                    log(f"{payload} left before being greeted — messages stay pending")
                    del greet_at[payload]
                continue

            if kind == "ready":
                log("server finished starting — checking backup and crash reports")
                check_backup(db)
                verdict = memory.backup_verdict(db) or "no change"
                log(f"    | backup check: {verdict}", "wake")
                log("turn complete · $0.0000", "wake")   # no model call; keeps the cost log complete
                memory.rollup(db)
                for report in new_crash_reports():
                    if report.name in seen_crashes:
                        continue
                    seen_crashes.add(report.name)
                    if time.time() - memory.last_crash_time(db) < CRASH_COOLDOWN_MIN * 60:
                        log("within crash cooldown — not investigating", "warn")
                        continue
                    if memory.spent_today(db) >= daily_limit():
                        log("daily spend limit reached — not investigating crash", "warn")
                        continue
                    if turn_task and not turn_task.done():
                        await turn_task
                    turn_task = asyncio.create_task(handle_crash(client, db, report))
                    turns_this_session += 1
                continue

            if kind == "chat":
                speaker, _, text = payload.partition(":")
                if speaker.strip().lower() == ADMIN.lower():
                    req = memory.pending_fable(db)
                    if req and APPROVE_FABLE.search(text):
                        memory.approve_fable(db, req["id"])
                        log(f"admin approved fable request #{req['id']} "
                            f"for {req['player']}", "wake")
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

            if turn_task and not turn_task.done():
                continue

            # --- a quiet moment: greet, roll over, or send queued chat ---
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
                    last_activity = time.time()
                    turns_this_session += 1
                    turn_task = asyncio.create_task(run_turn(
                        client, f"{player} has just logged in and finished loading." + block,
                        why=f"{player} login", db=db, source="login"))
                    break
                continue

            if not pending:
                # Nothing to do. If it has been quiet long enough, start a clean session
                # so cost per turn stops climbing with transcript length.
                if turns_this_session and time.time() - last_activity >= idle_needed:
                    log(f"idle {idle_needed // 60:.0f}m after {turns_this_session} turns — "
                        f"rolling to a fresh session")
                    await client.disconnect()
                    client = make_client()
                    await client.connect()
                    turns_this_session = 0
                    fresh_session = True
                    SESSION_COST["seen"] = 0.0
                continue

            if memory.spent_today(db) >= daily_limit():
                log(f"daily spend limit ${daily_limit():.2f} reached — ignoring chat", "warn")
                pending.clear()
                continue

            lines, pending = pending, []
            who = ", ".join(sorted({l.split(":", 1)[0] for l in lines}))
            for line in lines:
                player, _, text = line.partition(":")
                memory.log_event(db, "request", text.strip()[:200], player=player.strip())

            prompt = build_prompt(lines, interrupted) + context_block(db, online_players(), ADMIN)
            if fresh_session:
                # A new session has no transcript, so hand it the gist of recent history.
                if recent := memory.recent_activity(db, since_hours=24, limit=6):
                    prompt += "\n\nRecent history, for context:\n" + "\n".join(recent)
                fresh_session = False

            last_activity = time.time()
            turns_this_session += 1
            turn_task = asyncio.create_task(
                run_turn(client, prompt, why=f"chat from {who} ({len(lines)} line(s))",
                         db=db, source="chat"))
            interrupted = False
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("stopped by user")
