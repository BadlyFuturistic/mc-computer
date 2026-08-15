"""marks.py — read a shape out of blocks the player placed in the world.

Reading coordinates out loud is the worst part of asking for a build. Standing where
you want the corners and dropping a block is not. Because blocks are read from the
region files, sweeping a 128-block box for markers costs hundredths of a second, so
this can simply look rather than needing a selection wand or a click.

The convention, chosen so the markers are obvious on sight and unlikely to be load-
bearing in a build:

    gold block       a corner, or a point on the edge of a round shape
    emerald block    the centre
    redstone block   the second measurement — a cone's height, a torus tube

Every one of them is consumed after the build, so they never end up inside it.
Override any of the three with MCBOT_MARK_CORNER / _CENTRE / _SECOND if these blocks
are already used for something on your server.
"""
import math
import os
import re
import subprocess

CORNER = os.environ.get("MCBOT_MARK_CORNER", "minecraft:gold_block")
CENTRE = os.environ.get("MCBOT_MARK_CENTRE", "minecraft:emerald_block")
SECOND = os.environ.get("MCBOT_MARK_SECOND", "minecraft:redstone_block")

KINDS = {"corner": CORNER, "centre": CENTRE, "second": SECOND}
SEARCH_RADIUS = 64
SEARCH_HEIGHT = 48

# How many numbers each shape takes. It lives here rather than in mcshape because both
# tools need it, and a tool with no file extension cannot simply be imported.
ARITY = {
    "box": 6, "sphere": 4, "ellipsoid": 6, "cylinder": 5, "dome": 4, "bowl": 4,
    "cone": 5, "pyramid": 4, "torus": 5, "disc": 4, "line": 6, "wall": 6, "ramp": 6,
}


class MarkError(RuntimeError):
    pass


def player_position(name: str) -> tuple[int, int, int]:
    out = subprocess.run(["/opt/mc/mccmd"], input=f"data get entity {name} Pos\n",
                         capture_output=True, text=True).stdout
    m = re.search(r"\[(-?[\d.]+)d, (-?[\d.]+)d, (-?[\d.]+)d\]", out)
    if not m:
        raise MarkError(f"could not read {name}'s position — are they online?")
    return tuple(round(float(v)) for v in m.groups())


def find_in_box(reader, box) -> dict[str, list[tuple[int, int, int]]]:
    """Every marker inside a box, grouped by what it means."""
    import region

    x1, y1, z1, x2, y2, z2 = region._ordered(box)
    wanted = {block: kind for kind, block in KINDS.items()}
    found: dict[str, list] = {k: [] for k in KINDS}
    for cx in range(x1 >> 4, (x2 >> 4) + 1):
        for cz in range(z1 >> 4, (z2 >> 4) + 1):
            chunk = reader.chunk(cx, cz)
            if not chunk:
                continue
            ox, oz = cx * 16, cz * 16
            for section_y in range(y1 >> 4, (y2 >> 4) + 1):
                section = chunk.sections.get(section_y)
                # Skip the section outright unless a marker is in its palette.
                if not section or not any(n in wanted for n in section[0] if n):
                    continue
                for lx, wy, lz, name in chunk.section_blocks(section_y):
                    if name not in wanted:
                        continue
                    wx, wz = ox + lx, oz + lz
                    if x1 <= wx <= x2 and z1 <= wz <= z2 and y1 <= wy <= y2:
                        found[wanted[name]].append((wx, wy, wz))
    return found


def near_player(reader, player: str, radius: int = SEARCH_RADIUS):
    px, py, pz = player_position(player)
    found = find_in_box(reader, (px - radius, py - SEARCH_HEIGHT, pz - radius,
                                 px + radius, py + SEARCH_HEIGHT, pz + radius))
    if not any(found.values()):
        raise MarkError(
            f"no markers within {radius} blocks of {player}. Place "
            f"{CORNER.split(':')[-1]} at the corners, "
            f"{CENTRE.split(':')[-1]} at the centre of a round shape.")
    return found


def describe(found) -> str:
    parts = []
    for kind in ("corner", "centre", "second"):
        spots = found.get(kind) or []
        if spots:
            shown = "; ".join(f"{x} {y} {z}" for x, y, z in spots[:4])
            more = f" (+{len(spots) - 4})" if len(spots) > 4 else ""
            parts.append(f"{len(spots)} {kind} at {shown}{more}")
    return ", ".join(parts) if parts else "none"


def _centre(found):
    if found["centre"]:
        return found["centre"][0]
    corners = found["corner"]
    if not corners:
        raise MarkError(f"no centre marker. Place {CENTRE.split(':')[-1]} at the centre.")
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]; zs = [c[2] for c in corners]
    return ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2, (min(zs) + max(zs)) // 2)


def _span(found):
    """The box the corner markers describe."""
    corners = found["corner"]
    if len(corners) < 2:
        raise MarkError(
            f"that shape needs two opposite corners. Place two "
            f"{CORNER.split(':')[-1]}s and try again "
            f"(found {len(corners)}).")
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]; zs = [c[2] for c in corners]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _reach(centre, spots, what: str) -> int:
    if not spots:
        raise MarkError(f"nothing marking the {what}. Place "
                        f"{CORNER.split(':')[-1]} out at the edge.")
    return max(1, round(max(math.dist(centre, s) for s in spots)))


def parameters(found, kind: str, arity: int) -> list[int]:
    """Turn markers into the numbers a shape wants, in the order it wants them."""
    if kind in ("box", "line", "wall", "ramp"):
        x1, y1, z1, x2, y2, z2 = _span(found)
        return [x1, y1, z1, x2, y2, z2]

    centre = list(_centre(found))
    corners = found["corner"]
    seconds = found["second"]

    if kind in ("sphere", "dome", "bowl", "disc", "pyramid"):
        reach = _reach(centre, corners, "radius")
        return centre + [reach]

    if kind in ("cylinder", "cone"):
        reach = _reach(centre, corners, "radius")
        if seconds:
            height = max(1, abs(seconds[0][1] - centre[1]) + 1)
        else:
            height = max(1, max(abs(c[1] - centre[1]) for c in corners) + 1)
        return centre + [reach, height]

    if kind == "torus":
        ring = _reach(centre, corners, "ring radius")
        tube = _reach(centre, seconds, "tube radius") if seconds else max(1, ring // 4)
        return centre + [ring, tube]

    if kind == "ellipsoid":
        x1, y1, z1, x2, y2, z2 = _span(found)
        return [(x1 + x2) // 2, (y1 + y2) // 2, (z1 + z2) // 2,
                max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2), max(1, (z2 - z1) // 2)]

    raise MarkError(f"markers are not supported for {kind} yet")


def clear(rcon, dimension: str, found) -> int:
    """Remove the markers, so they are not left embedded in the finished build."""
    ctx = f"execute in {dimension} run "
    gone = 0
    for spots in found.values():
        for x, y, z in spots:
            if "Changed the block" in rcon.command(
                    f"{ctx}setblock {x} {y} {z} minecraft:air"):
                gone += 1
    return gone
