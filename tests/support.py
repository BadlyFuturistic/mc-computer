"""Shared scaffolding for the unit tests.

These tests are the one part of this repository that runs on a workstation. That is not
an accident: the modules under test — the geometry in `builder`, the road tests in
`roads`, the predicates in `region`, the comparisons in `verify` — are the ones that
need no world, and they are also the ones whose bugs reach the most tools. Everything
that talks to RCON or to a region file is tested by deploying it and running it.

No region-file fixtures. `region.py` decodes chunks and cannot write them, so a fixture
world would need an NBT and chunk writer first, which is more code than the bugs it
would catch. A reader is a thing with `.block(x, y, z)` and `.survey(box)`, so the tests
supply one backed by a dict.
"""
import os
import sys
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "server", "bin")
if BIN not in sys.path:
    sys.path.insert(0, BIN)

import region  # noqa: E402


class FakeReader:
    """A world made of a dict: {(x, y, z): block id}.

    Anything not in the dict reads as `default`. `None` is the honest default — that is
    what the real reader returns for a chunk that was never generated — but a test that
    wants open sky over solid ground says so explicitly with `fill`.
    """

    def __init__(self, blocks=None, default=None, dimension="minecraft:overworld"):
        self.blocks = dict(blocks or {})
        self.default = default
        self.dimension = dimension
        self.flushes = 0
        self.on_flush = None

    def flush(self):
        """Counted, so a test can prove a check read the world after the write.

        The real flush is what makes a read current. Skipping it reads the state from
        before the write, which makes a check either useless or a liar.
        """
        self.flushes += 1
        if self.on_flush:
            self.on_flush(self)
        return 0.0

    def block(self, x, y, z):
        if not -64 <= y < 320:
            return None
        return self.blocks.get((x, y, z), self.default)

    def survey(self, box):
        x1, y1, z1, x2, y2, z2 = region._ordered(box)
        counts = {}
        for (x, y, z), name in self.blocks.items():
            if x1 <= x <= x2 and y1 <= y <= y2 and z1 <= z <= z2 and name:
                counts[name] = counts.get(name, 0) + 1
        return counts

    # -- builders, so a test reads as the world it means

    def fill(self, box, name):
        x1, y1, z1, x2, y2, z2 = region._ordered(box)
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                for z in range(z1, z2 + 1):
                    self.blocks[(x, y, z)] = name
        return self

    def clear(self, box):
        x1, y1, z1, x2, y2, z2 = region._ordered(box)
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                for z in range(z1, z2 + 1):
                    self.blocks.pop((x, y, z), None)
        return self


def road(y=64, along_x=True, length=200, across=(-2, 2), surface="minecraft:gray_concrete",
         base="minecraft:stone", ground=None):
    """A carriageway: `across` blocks wide, `length` long, on ground that runs on forever.

    The ground matters as much as the road. A road that floats in a void passes tests
    that a road on a hillside fails, and the hillside is the case that caused damage.
    """
    reader = FakeReader()
    lo, hi = across
    span = range(-length // 2, length // 2 + 1)
    wide = range(lo - 40, hi + 41)
    for t in span:
        for a in wide:
            x, z = roads_at(t, a, along_x)
            # Ground below, spreading sideways without end, as real ground does.
            reader.blocks[(x, y - 1, z)] = ground or base
            if lo <= a <= hi:
                reader.blocks[(x, y, z)] = surface
    return reader


def roads_at(t, across, along_x):
    return (t, across) if along_x else (across, t)


class TestCase(unittest.TestCase):
    """Base class, so every test file gets the path set up by importing this one."""
