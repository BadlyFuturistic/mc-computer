"""region — the two predicates every world-editing tool trusts, and box ordering.

Nothing here touches a region file. `falls` and `passable` are lookups over block names,
and they decide whether a tool braces a ceiling or lets a desert pour into a tunnel.
"""
import unittest

import support
import region


class WhatFalls(support.TestCase):
    """Matched exactly, never by substring: "sandstone" contains "sand" and does not
    fall. Getting that wrong has tools bracing solid rock while real sand pours through."""

    def test_sand_and_gravel_fall(self):
        for name in ("sand", "red_sand", "gravel", "suspicious_sand",
                     "suspicious_gravel", "minecraft:sand", "minecraft:gravel"):
            with self.subTest(name):
                self.assertTrue(region.falls(name))

    def test_sandstone_does_not_fall(self):
        for name in ("sandstone", "minecraft:sandstone", "red_sandstone",
                     "smooth_sandstone", "chiseled_sandstone", "gravel_bricks"):
            with self.subTest(name):
                self.assertFalse(region.falls(name))

    def test_concrete_powder_falls_and_concrete_does_not(self):
        self.assertTrue(region.falls("minecraft:white_concrete_powder"))
        self.assertFalse(region.falls("minecraft:white_concrete"))

    def test_the_odd_ones_that_also_fall(self):
        for name in ("anvil", "chipped_anvil", "dragon_egg", "pointed_dripstone",
                     "scaffolding"):
            with self.subTest(name):
                self.assertTrue(region.falls(name))

    def test_nothing_does_not_fall(self):
        self.assertFalse(region.falls(None))
        self.assertFalse(region.falls(""))

    def test_a_modded_block_is_treated_as_staying_put(self):
        """Unknown means solid, which is the safe direction: a tool braces nothing it
        did not need to, rather than leaving a real hazard unbraced."""
        self.assertFalse(region.falls("create:andesite_casing"))


class WhatIsPassable(support.TestCase):

    def test_air_and_liquids_are_passable(self):
        for name in ("air", "cave_air", "void_air", "water", "lava",
                     "minecraft:flowing_water", "bubble_column"):
            with self.subTest(name):
                self.assertTrue(region.passable(name))

    def test_stone_is_not(self):
        for name in ("stone", "minecraft:gray_concrete", "obsidian",
                     "create:andesite_casing"):
            with self.subTest(name):
                self.assertFalse(region.passable(name))

    def test_plants_and_decoration_are_passable_by_suffix(self):
        for name in ("oak_sapling", "minecraft:oak_sign", "white_banner",
                     "stone_button", "oak_pressure_plate", "red_tulip",
                     "warped_fungus", "powered_rail", "blue_carpet"):
            with self.subTest(name):
                self.assertTrue(region.passable(name))

    def test_an_ungenerated_chunk_is_passable(self):
        """None counts as passable: an ungenerated chunk is not a wall, and treating it
        as one would make a tunnel run off into nothing."""
        self.assertTrue(region.passable(None))

    def test_a_modded_block_is_treated_as_solid(self):
        """A tunnel that runs a block too far is harmless. One that stops short leaves
        a wall across the road."""
        self.assertFalse(region.passable("mekanism:steel_casing"))


class BoxOrdering(support.TestCase):

    def test_a_reversed_box_is_turned_the_right_way_round(self):
        self.assertEqual(region._ordered((10, 70, 30, 0, 60, 20)),
                         (0, 60, 20, 10, 70, 30))

    def test_height_is_clamped_to_the_build_range(self):
        x1, y1, z1, x2, y2, z2 = region._ordered((0, -200, 0, 10, 500, 10))
        self.assertEqual((y1, y2), (-64, 319))

    def test_clamping_happens_after_sorting(self):
        """Clamping first would turn a reversed pair inside out."""
        _, y1, _, _, y2, _ = region._ordered((0, 400, 0, 10, -100, 10))
        self.assertEqual((y1, y2), (-64, 319))

    def test_a_single_block_box_survives(self):
        self.assertEqual(region._ordered((5, 6, 7, 5, 6, 7)), (5, 6, 7, 5, 6, 7))


if __name__ == "__main__":
    unittest.main()
