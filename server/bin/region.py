"""region.py — read the world straight off disk, instead of asking the server.

RCON is a console for humans. It has no command that answers "what block is here?" —
only `execute if block <id>`, which tests a guess and answers yes or no. Every read
therefore costs a force-load, a settle delay, and a round trip, and cannot tell a
wrong guess from an absent block. That is what made a mistyped block id grind through
a hundred fills and change nothing.

The region files hold the same information and answer in microseconds:

    reader = Reader()
    reader.flush()                         # make the files current first
    reader.block(950, 66, 293)             # -> 'waystones:andesite_waystone'

Two things this cannot do, both by design:

  * Writes. Editing region files under a running server corrupts them. Every change
    still goes through RCON.
  * Live truth. The files hold the last save, so a block placed seconds ago is not
    there yet. flush() runs `save-all flush` — one call, about 0.3s, covers any
    number of reads after it.

The chunk format changes between Minecraft versions, and a stale parser returns wrong
blocks rather than an error. verify() checks one known block against RCON so a batch
is never trusted blindly.
"""
import gzip
import io
import os
import struct
import zlib
from pathlib import Path

WORLD = Path(os.environ.get("MCBOT_WORLD", "/opt/mc/data/world"))
SECTION_VOLUME = 16 * 16 * 16


class RegionError(RuntimeError):
    pass


# ---------------------------------------------------------------- NBT

def _read_nbt(f: io.BufferedIOBase):
    """Named Binary Tag, the format every chunk is stored in."""
    def u1() -> int:
        return f.read(1)[0]

    def i4() -> int:
        return struct.unpack(">i", f.read(4))[0]

    def name() -> str:
        (n,) = struct.unpack(">H", f.read(2))
        return f.read(n).decode("utf-8", "replace")

    def array(count_format: str, width: int):
        (count,) = struct.unpack(">i", f.read(4))
        return list(struct.unpack(f">{count}{count_format}", f.read(width * count)))

    def payload(tag: int):
        if tag == 1:
            return struct.unpack(">b", f.read(1))[0]
        if tag == 2:
            return struct.unpack(">h", f.read(2))[0]
        if tag == 3:
            return i4()
        if tag == 4:
            return struct.unpack(">q", f.read(8))[0]
        if tag == 5:
            return struct.unpack(">f", f.read(4))[0]
        if tag == 6:
            return struct.unpack(">d", f.read(8))[0]
        if tag == 7:
            return f.read(i4())
        if tag == 8:
            return name()
        if tag == 9:
            elem, count = u1(), i4()
            if elem == 0:
                return []
            return [payload(elem) for _ in range(count)]
        if tag == 10:
            out = {}
            while (inner := u1()) != 0:
                # The key must be read before the value: reading them in one
                # statement lets Python evaluate the value first and desync the stream.
                key = name()
                out[key] = payload(inner)
            return out
        if tag == 11:
            return array("i", 4)
        if tag == 12:
            return array("q", 8)
        raise RegionError(f"unknown NBT tag {tag}")

    tag = u1()
    if tag == 0:
        return None
    name()
    return payload(tag)


# ---------------------------------------------------------------- dimensions

def region_dir(dimension: str = "minecraft:overworld") -> Path:
    """Where one dimension's region files live.

    Modern saves put every dimension under dimensions/<namespace>/<path>/. Older ones
    keep the overworld at the world root and use DIM-1 / DIM1. Both are checked, so
    this does not have to be told which layout a server uses.
    """
    dim = dimension if ":" in dimension else f"minecraft:{dimension}"
    namespace, path = dim.split(":", 1)

    candidates = [WORLD / "dimensions" / namespace / path / "region"]
    if namespace == "minecraft":
        candidates += {
            "overworld": [WORLD / "region"],
            "the_nether": [WORLD / "DIM-1" / "region"],
            "the_end": [WORLD / "DIM1" / "region"],
        }.get(path, [])

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise RegionError(
        f"no region files for {dim}. Looked in: "
        + ", ".join(str(c) for c in candidates))


def dimensions() -> list[str]:
    """Every dimension that has region files on disk."""
    found = []
    root = WORLD / "dimensions"
    if root.is_dir():
        for namespace in sorted(root.iterdir()):
            for path in sorted(namespace.glob("*/region")):
                found.append(f"{namespace.name}:{path.parent.name}")
    for legacy, dim in ((WORLD / "region", "minecraft:overworld"),
                        (WORLD / "DIM-1" / "region", "minecraft:the_nether"),
                        (WORLD / "DIM1" / "region", "minecraft:the_end")):
        if legacy.is_dir() and dim not in found:
            found.append(dim)
    return found


# ---------------------------------------------------------------- chunks

class Chunk:
    """One 16x16 column, decoded far enough to answer block questions."""

    __slots__ = ("sections", "status")

    def __init__(self, nbt: dict):
        self.status = nbt.get("Status", "")
        self.sections = {}
        for section in nbt.get("sections", []):
            states = section.get("block_states") or {}
            palette = [entry.get("Name") for entry in states.get("palette", [])]
            if palette:
                self.sections[section.get("Y")] = (palette, states.get("data"))

    def block(self, x: int, y: int, z: int) -> str | None:
        """Block id at world coordinates. None means the section is not stored."""
        found = self.sections.get(y >> 4)
        if not found:
            return None
        palette, data = found
        if len(palette) == 1 or not data:
            return palette[0]
        bits = max(4, (len(palette) - 1).bit_length())
        per_long = 64 // bits
        index = (y & 15) * 256 + (z & 15) * 16 + (x & 15)
        # Since 1.16 an entry never straddles two longs; the spare high bits are padding.
        which, offset = divmod(index, per_long)
        value = (data[which] >> (offset * bits)) & ((1 << bits) - 1)
        return palette[value] if value < len(palette) else None

    def section_blocks(self, section_y: int):
        """Yield (x, y, z, block) for a whole section, in storage order.

        Decoding a section once is far cheaper than 4096 separate lookups, which is
        what makes surveying a large box practical.
        """
        found = self.sections.get(section_y)
        if not found:
            return
        palette, data = found
        base_y = section_y * 16
        if len(palette) == 1 or not data:
            only = palette[0]
            for index in range(SECTION_VOLUME):
                yield (index & 15, base_y + (index >> 8), (index >> 4) & 15, only)
            return
        bits = max(4, (len(palette) - 1).bit_length())
        per_long = 64 // bits
        mask = (1 << bits) - 1
        index = 0
        for word in data:
            for slot in range(per_long):
                if index >= SECTION_VOLUME:
                    return
                value = (word >> (slot * bits)) & mask
                yield (index & 15, base_y + (index >> 8), (index >> 4) & 15,
                       palette[value] if value < len(palette) else None)
                index += 1


class Reader:
    """Cached access to one world's blocks.

    A flood fill visits the same chunk thousands of times, so decoded chunks are kept.
    Cached chunks are not re-read after a flush(); call reset() if the world changed
    underneath a long-running read.
    """

    def __init__(self, dimension: str = "minecraft:overworld"):
        self.dimension = dimension if ":" in dimension else f"minecraft:{dimension}"
        self.dir = region_dir(self.dimension)
        self._chunks: dict[tuple[int, int], Chunk | None] = {}

    # -- loading

    def _load(self, cx: int, cz: int) -> Chunk | None:
        path = self.dir / f"r.{cx >> 5}.{cz >> 5}.mca"
        if not path.is_file():
            return None
        slot = 4 * ((cx & 31) + (cz & 31) * 32)
        with path.open("rb") as fh:
            fh.seek(slot)
            header = fh.read(4)
            if len(header) < 4:
                return None
            (offset,) = struct.unpack(">I", b"\0" + header[:3])
            if offset == 0:
                return None                      # chunk never generated
            fh.seek(offset * 4096)
            (length,) = struct.unpack(">i", fh.read(4))
            scheme = fh.read(1)[0]
            raw = fh.read(length - 1)

        if scheme & 0x80:
            # An oversized chunk lives in its own file; the region entry is a stub.
            external = self.dir / f"c.{cx}.{cz}.mcc"
            if not external.is_file():
                return None
            raw = external.read_bytes()
            scheme &= 0x7F

        if scheme == 1:
            raw = gzip.decompress(raw)
        elif scheme == 2:
            raw = zlib.decompress(raw)
        elif scheme == 3:
            pass
        else:
            raise RegionError(
                f"chunk {cx},{cz} uses compression scheme {scheme}, which this reader "
                f"does not decode. The world format has changed — use RCON for now.")
        return Chunk(_read_nbt(io.BytesIO(raw)))

    def chunk(self, cx: int, cz: int) -> Chunk | None:
        if (cx, cz) not in self._chunks:
            self._chunks[(cx, cz)] = self._load(cx, cz)
        return self._chunks[(cx, cz)]

    def reset(self) -> None:
        self._chunks.clear()

    # -- reading

    def block(self, x: int, y: int, z: int) -> str | None:
        """Block id at these coordinates, or None if that chunk is not generated."""
        if not -64 <= y < 320:
            return None
        chunk = self.chunk(x >> 4, z >> 4)
        return chunk.block(x, y, z) if chunk else None

    def survey(self, box, limit: int = 40_000_000) -> dict[str, int]:
        """Count every block id inside a box. Decodes whole sections, not points."""
        x1, y1, z1, x2, y2, z2 = _ordered(box)
        volume = (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1)
        if volume > limit:
            raise RegionError(
                f"{volume:,} blocks is more than this will survey at once "
                f"(limit {limit:,}). Narrow the box.")
        counts: dict[str, int] = {}
        for cx in range(x1 >> 4, (x2 >> 4) + 1):
            for cz in range(z1 >> 4, (z2 >> 4) + 1):
                chunk = self.chunk(cx, cz)
                if not chunk:
                    continue
                ox, oz = cx * 16, cz * 16
                for section_y in range(y1 >> 4, (y2 >> 4) + 1):
                    for lx, wy, lz, name in chunk.section_blocks(section_y):
                        wx, wz = ox + lx, oz + lz
                        if (x1 <= wx <= x2 and z1 <= wz <= z2 and y1 <= wy <= y2
                                and name):
                            counts[name] = counts.get(name, 0) + 1
        return counts

    def present(self, box) -> set[str]:
        """Which block ids the palettes in a box mention.

        Much cheaper than survey() because no packed data is decoded, but a palette can
        keep an entry after the last block of that kind is gone. Treat this as "may be
        present", and use survey() when the count matters.
        """
        x1, y1, z1, x2, y2, z2 = _ordered(box)
        names: set[str] = set()
        for cx in range(x1 >> 4, (x2 >> 4) + 1):
            for cz in range(z1 >> 4, (z2 >> 4) + 1):
                chunk = self.chunk(cx, cz)
                if not chunk:
                    continue
                for section_y in range(y1 >> 4, (y2 >> 4) + 1):
                    found = chunk.sections.get(section_y)
                    if found:
                        names.update(n for n in found[0] if n)
        return names

    # -- keeping honest

    def flush(self) -> float:
        """Write the live world to disk, so reads that follow are current.

        One call covers every read after it. Without it a block placed moments ago is
        simply absent from the files, which reads exactly like empty ground.
        """
        import time
        from mcrcon import Rcon

        started = time.time()
        with Rcon() as rcon:
            rcon.command("save-all flush")
        self.reset()
        return time.time() - started

    def verify(self, x: int, y: int, z: int) -> tuple[bool, str | None, str | None]:
        """Check one block against RCON. Returns (agree, from_file, rcon_verdict).

        The chunk format changes between Minecraft versions, and a parser that has
        fallen behind returns plausible wrong answers instead of failing. Any tool
        about to trust a large batch of file reads should spend one RCON call here.

        The chunk has to be force-loaded first: `execute if block` reports no match for
        anything the server does not currently have loaded, which would make every
        check of a quiet corner of the world look like a disagreement.
        """
        import time
        from mcrcon import Rcon

        mine = self.block(x, y, z)
        if mine is None:
            return False, None, "chunk not generated or not saved"
        ctx = f"execute in {self.dimension} run "
        with Rcon() as rcon:
            rcon.command(f"{ctx}forceload add {x} {z} {x} {z}")
            try:
                time.sleep(0.6)          # a chunk is not readable the instant it loads
                out = rcon.command(
                    f"{ctx}execute if block {x} {y} {z} {mine} run list")
            finally:
                rcon.command(f"{ctx}forceload remove {x} {z} {x} {z}")
        return bool(out.strip()), mine, out.strip() or "no match"


# Blocks that do not count as ground standing in the way. Anything not listed is
# treated as solid, which is the safe direction to be wrong in: a tunnel that runs a
# block too far is harmless, one that stops short leaves a wall across the road.
PASSABLE = {
    "air", "cave_air", "void_air",
    "water", "flowing_water", "bubble_column", "lava", "flowing_lava",
    "short_grass", "tall_grass", "fern", "large_fern", "dead_bush", "leaf_litter",
    "snow", "vine", "glow_lichen", "seagrass", "tall_seagrass", "kelp", "kelp_plant",
    "lily_pad", "sugar_cane", "bamboo", "cobweb", "light", "structure_void", "rail",
    "torch", "wall_torch", "soul_torch", "redstone_torch", "lantern",
    "poppy", "dandelion", "allium", "cornflower", "azure_bluet", "oxeye_daisy",
    "blue_orchid", "lily_of_the_valley", "wither_rose", "torchflower", "pitcher_plant",
}
PASSABLE_SUFFIX = (
    "_sapling", "_flower", "_sign", "_banner", "_button", "_pressure_plate",
    "_rail", "_carpet", "_bush", "_roots", "_sprouts", "_fungus", "_torch", "_tulip",
)


# Blocks that fall when whatever holds them up is taken away. Matched exactly, never by
# substring: "sandstone" contains "sand" and does not fall, and getting that wrong would
# have tools bracing solid rock while real sand poured through.
GRAVITY = {
    "sand", "red_sand", "suspicious_sand", "gravel", "suspicious_gravel",
    "anvil", "chipped_anvil", "damaged_anvil", "dragon_egg", "pointed_dripstone",
    "scaffolding",
}
GRAVITY_SUFFIX = ("_concrete_powder",)


def falls(name: str | None) -> bool:
    """True if this block drops once the block beneath it is gone."""
    if not name:
        return False
    short = name.split(":", 1)[-1]
    return short in GRAVITY or short.endswith(GRAVITY_SUFFIX)


def passable(name: str | None) -> bool:
    """True if this block would not stop someone walking through.

    None counts as passable: an ungenerated chunk is not a wall, and treating it as
    one would make a tunnel run off into nothing.
    """
    if not name:
        return True
    short = name.split(":", 1)[-1]
    return short in PASSABLE or short.endswith(PASSABLE_SUFFIX)


def _ordered(box) -> tuple[int, int, int, int, int, int]:
    x1, y1, z1, x2, y2, z2 = box
    lo_x, hi_x = sorted((x1, x2))
    lo_y, hi_y = sorted((y1, y2))
    lo_z, hi_z = sorted((z1, z2))
    # Nothing is stored outside the build range; clamping after sorting keeps a
    # reversed pair from being turned inside out.
    return lo_x, max(-64, lo_y), lo_z, hi_x, min(319, hi_y), hi_z
