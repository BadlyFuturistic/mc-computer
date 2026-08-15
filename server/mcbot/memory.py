"""Persistent memory for the bot: deferred messages, an activity log, backup health.

Design note — why this is a plain SQLite file and not a memory framework:

The binding constraint here is tokens per turn, not retrieval quality. Every query
this bot needs is exact and keyed ("messages pending for player X", "backups since
date Y"), so semantic search buys nothing while adding a dependency, a network hop
and a per-query cost. The daemon owns the store and injects one small fixed block
per turn, which means context cost stays flat no matter how much history piles up.

Bloat control is the nightly rollup: raw request rows collapse into one summary line
per day, and anything older than RAW_RETENTION_DAYS is deleted. A month of history
is a few dozen lines, not a transcript.
"""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("/var/lib/mcbot/memory.db")
RAW_RETENTION_DAYS = 4        # keep individual events this long, then only summaries
SUMMARY_RETENTION_DAYS = 60   # keep daily rollups this long
MAX_CONTEXT_EVENTS = 12       # never inject more than this many recent lines

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    for_player  TEXT NOT NULL COLLATE NOCASE,
    from_player TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_msg_pending ON messages(for_player, delivered_at);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,          -- join | leave | request | note | backup
    player  TEXT,
    detail  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS daily (
    day     TEXT PRIMARY KEY,       -- YYYY-MM-DD
    summary TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spend (
    id     INTEGER PRIMARY KEY,
    ts     REAL NOT NULL,
    day    TEXT NOT NULL,          -- YYYY-MM-DD, local
    source TEXT NOT NULL,          -- chat | login | terminal | escalation | crash
    model  TEXT,
    usd    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spend_day ON spend(day);

CREATE TABLE IF NOT EXISTS crashes (
    id         INTEGER PRIMARY KEY,
    ts         REAL NOT NULL,
    signature  TEXT NOT NULL,      -- exception + top frame, to recognise a repeat
    report     TEXT,               -- path to the written report, if one was written
    seen_count INTEGER NOT NULL DEFAULT 1,
    last_ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crash_sig ON crashes(signature);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fable_requests (
    id          INTEGER PRIMARY KEY,
    ts          REAL NOT NULL,
    player      TEXT NOT NULL,      -- who asked for it
    what        TEXT NOT NULL,
    approved_at REAL,               -- set by the daemon on seeing the admin approve
    used_at     REAL                -- first run, or a denial; the grant itself is in settings
);

CREATE TABLE IF NOT EXISTS backups (
    id          INTEGER PRIMARY KEY,
    ts          REAL NOT NULL,
    filename    TEXT,
    size_bytes  INTEGER,
    ok          INTEGER NOT NULL,
    detail      TEXT NOT NULL,
    reported_at REAL
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


# ----------------------------------------------------------------- writing
def add_message(db, for_player: str, from_player: str, body: str) -> int:
    cur = db.execute(
        "INSERT INTO messages (for_player, from_player, body, created_at) VALUES (?,?,?,?)",
        (for_player, from_player, body, time.time()),
    )
    db.commit()
    return cur.lastrowid


def mark_delivered(db, ids: list[int]) -> None:
    if not ids:
        return
    db.executemany(
        "UPDATE messages SET delivered_at = ? WHERE id = ?",
        [(time.time(), i) for i in ids],
    )
    db.commit()


def log_event(db, kind: str, detail: str, player: str | None = None) -> None:
    db.execute(
        "INSERT INTO events (ts, kind, player, detail) VALUES (?,?,?,?)",
        (time.time(), kind, player, detail[:400]),
    )
    db.commit()


def record_backup(db, filename: str | None, size: int | None, ok: bool, detail: str) -> None:
    db.execute(
        "INSERT INTO backups (ts, filename, size_bytes, ok, detail) VALUES (?,?,?,?,?)",
        (time.time(), filename, size, 1 if ok else 0, detail),
    )
    db.commit()


def record_spend(db, source: str, model: str | None, usd: float) -> None:
    db.execute(
        "INSERT INTO spend (ts, day, source, model, usd) VALUES (?,?,?,?,?)",
        (time.time(), time.strftime("%Y-%m-%d"), source, model, float(usd or 0)),
    )
    db.commit()


def spent_today(db) -> float:
    row = db.execute(
        "SELECT COALESCE(SUM(usd), 0) AS t FROM spend WHERE day = ?",
        (time.strftime("%Y-%m-%d"),),
    ).fetchone()
    return float(row["t"])


def crash_seen(db, signature: str) -> tuple[bool, int]:
    """Register a crash. Returns (is_new_signature, how_many_times_seen)."""
    row = db.execute("SELECT * FROM crashes WHERE signature = ?", (signature,)).fetchone()
    now = time.time()
    if row:
        db.execute("UPDATE crashes SET seen_count = seen_count + 1, last_ts = ? WHERE id = ?",
                   (now, row["id"]))
        db.commit()
        return False, row["seen_count"] + 1
    db.execute("INSERT INTO crashes (ts, signature, seen_count, last_ts) VALUES (?,?,1,?)",
               (now, signature, now))
    db.commit()
    return True, 1


def crashes_reported_today(db) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM crashes WHERE report IS NOT NULL "
        "AND date(ts,'unixepoch','localtime') = date('now','localtime')"
    ).fetchone()
    return int(row["n"])


def set_crash_report(db, signature: str, path: str) -> None:
    db.execute("UPDATE crashes SET report = ? WHERE signature = ?", (path, signature))
    db.commit()


def last_crash_time(db) -> float:
    row = db.execute("SELECT COALESCE(MAX(last_ts), 0) AS t FROM crashes").fetchone()
    return float(row["t"])


def get_setting(db, key: str) -> str:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def set_setting(db, key: str, value: str) -> None:
    """Runtime state the bot may change, as opposed to /etc/mcbot/config which it
    can only read."""
    db.execute("INSERT INTO settings (key, value) VALUES (?,?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    db.commit()


def request_fable(db, player: str, what: str) -> int:
    cur = db.execute("INSERT INTO fable_requests (ts, player, what) VALUES (?,?,?)",
                     (time.time(), player, what[:300]))
    db.commit()
    return cur.lastrowid


def pending_fable(db):
    """The newest request still waiting on approval, if any."""
    return db.execute(
        "SELECT * FROM fable_requests WHERE approved_at IS NULL AND used_at IS NULL "
        "AND ts > ? ORDER BY ts DESC LIMIT 1", (time.time() - 1800,)).fetchone()


def approve_fable(db, req_id: int) -> None:
    """Only the daemon calls this, on seeing the admin approve in raw chat. The model
    has no route to it, which is what makes the approval meaningful.

    Approving opens a grant rather than a single use. A request is rarely finished in
    one run — "actually make it blue" is the same piece of work — and asking the admin
    to approve every follow-up made the feature unusable in practice. The grant ends
    at the boundaries the admin's decision was scoped to: see revoke_fable().
    """
    row = db.execute("SELECT * FROM fable_requests WHERE id = ?", (req_id,)).fetchone()
    db.execute("UPDATE fable_requests SET approved_at = ? WHERE id = ?",
               (time.time(), req_id))
    set_setting(db, "fable_grant", json.dumps({
        "request_id": req_id,
        "player": row["player"] if row else "",
        "what": row["what"] if row else "",
        "since": time.time(),
        "runs": 0,
    }))
    db.commit()


def deny_fable(db, req_id: int) -> None:
    """Mark a request as spent without approving it, so a refusal is final rather
    than leaving it pending for something later to claim."""
    db.execute("UPDATE fable_requests SET used_at = ? WHERE id = ?", (time.time(), req_id))
    db.commit()


def fable_grant(db):
    """The open grant, or None. Reading it does not spend it."""
    raw = get_setting(db, "fable_grant")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def note_fable_run(db) -> None:
    """Record that the grant was used once. Kept for the audit trail and for telling
    the admin how much has been done on one approval; it does not close the grant."""
    grant = fable_grant(db)
    if not grant:
        return
    grant["runs"] = grant.get("runs", 0) + 1
    grant["last_run"] = time.time()
    set_setting(db, "fable_grant", json.dumps(grant))
    if grant.get("request_id"):
        db.execute("UPDATE fable_requests SET used_at = ? WHERE id = ?",
                   (time.time(), grant["request_id"]))
    db.commit()


def revoke_fable(db, why: str) -> bool:
    """End the grant. Returns whether there was one to end.

    The daemon calls this at the two boundaries the admin's approval was scoped to:
    when the conversation is wiped (a new session, so the work being approved of is
    forgotten anyway) and when the admin logs out (nobody left to object). It also
    runs at startup, because a grant that outlived the daemon belongs to a
    conversation that no longer exists.
    """
    grant = fable_grant(db)
    if not grant:
        return False
    set_setting(db, "fable_grant", "")
    log_event(db, "note",
              f"fable access ended ({why}) after {grant.get('runs', 0)} run(s)",
              player=grant.get("player") or None)
    return True


# ----------------------------------------------------------------- reading
def pending_messages(db, player: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM messages WHERE for_player = ? AND delivered_at IS NULL "
        "ORDER BY created_at",
        (player,),
    ).fetchall()


def unreported_backups(db) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM backups WHERE reported_at IS NULL ORDER BY ts"
    ).fetchall()


def mark_backups_reported(db) -> None:
    db.execute("UPDATE backups SET reported_at = ? WHERE reported_at IS NULL", (time.time(),))
    db.commit()


def backup_verdict(db) -> str | None:
    """One line covering all unreported backups, not a per-night rundown."""
    rows = unreported_backups(db)
    if not rows:
        return None
    ok = sum(r["ok"] for r in rows)
    n = len(rows)
    if n == 1:
        r = rows[0]
        return (f"Last backup succeeded ({r['size_bytes'] // 1024**2} MB)."
                if r["ok"] else f"Last backup FAILED: {r['detail']}")
    if ok == n:
        return f"Backups healthy — {n} successful since you were last on."
    if ok == 0:
        return f"Backups are FAILING — all {n} attempts failed. Most recent: {rows[-1]['detail']}"
    return (f"Backups intermittent — {ok} of {n} succeeded. "
            f"Most recent: {'ok' if rows[-1]['ok'] else rows[-1]['detail']}")


def recent_activity(db, since_hours: float = 72, limit: int = MAX_CONTEXT_EVENTS) -> list[str]:
    """Compact recent history: rolled-up days first, then individual recent events."""
    out = [f"{r['day']}: {r['summary']}" for r in db.execute(
        "SELECT day, summary FROM daily ORDER BY day DESC LIMIT 5").fetchall()]
    cutoff = time.time() - since_hours * 3600
    rows = db.execute(
        "SELECT ts, kind, player, detail FROM events WHERE ts > ? AND kind = 'request' "
        "ORDER BY ts DESC LIMIT ?", (cutoff, limit)).fetchall()
    out += [f"{time.strftime('%m-%d %H:%M', time.localtime(r['ts']))} "
            f"{r['player'] or '?'}: {r['detail']}" for r in rows]
    return out


# ----------------------------------------------------------------- upkeep
def rollup(db) -> None:
    """Collapse finished days into one summary line each, then drop the raw rows.

    Cheap and deterministic — no model call. The summary is a count per player plus
    the first few things they asked for, which is enough to answer "what did X get
    up to while I was away" without keeping the transcript.
    """
    cutoff_day = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    days = db.execute(
        "SELECT DISTINCT date(ts,'unixepoch','localtime') AS d FROM events "
        "WHERE date(ts,'unixepoch','localtime') <= ? AND kind='request'",
        (cutoff_day,),
    ).fetchall()
    for row in days:
        day = row["d"]
        if db.execute("SELECT 1 FROM daily WHERE day = ?", (day,)).fetchone():
            continue
        events = db.execute(
            "SELECT player, detail FROM events WHERE kind='request' "
            "AND date(ts,'unixepoch','localtime') = ?", (day,)).fetchall()
        by_player: dict[str, list[str]] = {}
        for e in events:
            by_player.setdefault(e["player"] or "?", []).append(e["detail"])
        parts = []
        for player, items in by_player.items():
            sample = "; ".join(items[:3])[:180]
            extra = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
            parts.append(f"{player} — {len(items)} request(s): {sample}{extra}")
        db.execute("INSERT INTO daily (day, summary) VALUES (?,?)", (day, " | ".join(parts)[:600]))
    db.commit()

    db.execute("DELETE FROM events WHERE ts < ?", (time.time() - RAW_RETENTION_DAYS * 86400,))
    db.execute("DELETE FROM daily WHERE day < date('now', ?)",
               (f"-{SUMMARY_RETENTION_DAYS} days",))
    db.execute("DELETE FROM messages WHERE delivered_at IS NOT NULL AND delivered_at < ?",
               (time.time() - 14 * 86400,))
    db.execute("DELETE FROM backups WHERE reported_at IS NOT NULL AND reported_at < ?",
               (time.time() - 30 * 86400,))
    db.execute("DELETE FROM spend WHERE ts < ?", (time.time() - 90 * 86400,))
    db.commit()
