"""Minimal RCON client — the only way this bot talks to Minecraft.

Deliberately does not shell out to `docker exec`. Docker group membership is
root-equivalent, so speaking the protocol directly over localhost is what lets the
service run as an unprivileged user with no container access at all.

Password comes from RCON_PASSWORD in the environment, or /etc/mcbot/rcon.pass.
"""
import os
import select
import socket
import struct
from pathlib import Path

HOST = os.environ.get("RCON_HOST", "127.0.0.1")
PORT = int(os.environ.get("RCON_PORT", "25575"))
PASS_FILE = Path("/etc/mcbot/rcon.pass")

SERVERDATA_AUTH = 3
SERVERDATA_EXECCOMMAND = 2
SPLIT_THRESHOLD = 4000   # replies shorter than this cannot be continued


class RconError(RuntimeError):
    pass


COMPOSE = Path("/opt/mc/compose.yaml")


def _password() -> str:
    """Environment first (how the service gets it), then the secret file, then the
    compose file — so an admin running these tools by hand also works, without
    needing read access to the service's private secret."""
    if p := os.environ.get("RCON_PASSWORD"):
        return p
    try:
        if PASS_FILE.exists():
            return PASS_FILE.read_text().strip()
    except PermissionError:
        pass
    try:
        if COMPOSE.exists():
            import re as _re
            if m := _re.search(r'RCON_PASSWORD:\s*"?([^"\n]+)', COMPOSE.read_text()):
                return m.group(1).strip()
    except PermissionError:
        pass
    raise RconError(
        "no RCON password available: set RCON_PASSWORD, or run as a user that can "
        "read /etc/mcbot/rcon.pass or /opt/mc/compose.yaml"
    )


def _pack(req_id: int, kind: int, body: str) -> bytes:
    payload = struct.pack("<ii", req_id, kind) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RconError("connection closed by server")
        buf += chunk
    return buf


class Rcon:
    """One connection, reusable for many commands."""

    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = 30.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.timeout = timeout
        self._id = 0
        self._auth()

    def _send(self, kind: int, body: str) -> int:
        self._id += 1
        self.sock.sendall(_pack(self._id, kind, body))
        return self._id

    def _recv(self) -> tuple[int, int, str]:
        (length,) = struct.unpack("<i", _read_exact(self.sock, 4))
        payload = _read_exact(self.sock, length)
        req_id, kind = struct.unpack("<ii", payload[:8])
        return req_id, kind, payload[8:-2].decode("utf-8", "replace")

    def _auth(self) -> None:
        sent = self._send(SERVERDATA_AUTH, _password())
        req_id, _, _ = self._recv()
        if req_id == -1:
            raise RconError("RCON authentication failed — wrong password")
        if req_id != sent:
            # Some servers send an empty SERVERDATA_RESPONSE_VALUE first.
            req_id, _, _ = self._recv()
            if req_id == -1:
                raise RconError("RCON authentication failed — wrong password")

    def command(self, cmd: str) -> str:
        """Run one command and return its output, minus terminal colour codes."""
        sent = self._send(SERVERDATA_EXECCOMMAND, cmd)
        chunks = []
        while True:
            req_id, _, body = self._recv()
            if req_id == sent:
                chunks.append(body)
            # A short, non-empty reply is complete: only a reply at the packet ceiling
            # can be continued. An empty one may still be followed by the real body, so
            # it has to wait — but briefly, since the server is on this machine. Waiting
            # 150ms after every reply dominates any tool issuing hundreds of probes.
            if body and len(body) < SPLIT_THRESHOLD:
                break
            wait = 0.15 if len(body) >= SPLIT_THRESHOLD else 0.03
            if not select.select([self.sock], [], [], wait)[0]:
                break
        return "".join(chunks).replace("\x1b[0m", "").strip()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def run(*cmds: str) -> list[str]:
    """Convenience: run commands over a single connection, return outputs in order."""
    with Rcon() as r:
        return [r.command(c) for c in cmds]
