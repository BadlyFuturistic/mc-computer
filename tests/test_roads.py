"""roads — the two questions that decide whether a repave helps or does damage.

Which way does the road run, and is this actually road? Both were answered from the
arguments once, and both answers came back as damage a player had to report. These tests
rebuild the worlds that produced those answers.

`mcpave`, `mcrepave`, `mcbranch` and `mcbore --repave` all ask through this module.
"""
import unittest

import support
import roads

Y = 64
ACROSS = [-2, -1, 0, 1, 2]
SURFACE = "minecraft:gray_concrete"


class WhichWayDoesItRun(support.TestCase):
    """A bore of a single block hands a repave a strip 1 along and 5 across. Taking the
    direction from that shape decided the road ran across itself, which sampled the
    tunnel walls for road and cloned them into the floor."""

    def test_a_road_along_x_reads_as_along_x(self):
        reader = support.road(y=Y, along_x=True)
        self.assertTrue(roads.direction(reader, Y, 0, 0))

    def test_a_road_along_z_reads_as_across_x(self):
        reader = support.road(y=Y, along_x=False)
        self.assertFalse(roads.direction(reader, Y, 0, 0))

    def test_the_answer_does_not_depend_on_where_along_the_road_it_is_asked(self):
        reader = support.road(y=Y, along_x=True, length=200)
        for t in (-80, -1, 0, 1, 37, 80):
            with self.subTest(t=t):
                self.assertTrue(roads.direction(reader, Y, t, 0))

    def test_the_answer_does_not_depend_on_which_lane_it_is_asked_from(self):
        """The one-block-bore case: every column of the strip must agree."""
        reader = support.road(y=Y, along_x=True)
        for across in ACROSS:
            with self.subTest(across=across):
                self.assertTrue(roads.direction(reader, Y, 0, across))

    def test_open_sky_falls_back_rather_than_guessing_from_nothing(self):
        self.assertTrue(roads.direction(support.FakeReader(), Y, 0, 0))

    def test_reach_stops_at_the_first_block_that_is_not_the_same_kind(self):
        reader = support.FakeReader()
        reader.fill((0, Y, 0, 9, Y, 0), SURFACE)
        self.assertEqual(roads.reach(reader, Y, 0, 0, 1, 0, {SURFACE}), 9)
        self.assertEqual(roads.reach(reader, Y, 0, 0, -1, 0, {SURFACE}), 0)

    def test_reach_never_looks_further_than_it_is_asked_to(self):
        reader = support.FakeReader()
        reader.fill((0, Y, 0, 500, Y, 0), SURFACE)
        self.assertEqual(roads.reach(reader, Y, 0, 0, 1, 0, {SURFACE}, limit=10), 10)


class IsThisActuallyRoad(support.TestCase):

    def test_the_carriageway_reads_as_road(self):
        reader = support.road(y=Y)
        self.assertEqual(roads.road_slice(reader, Y, 0, 1, ACROSS, True),
                         [SURFACE] * 5)

    def test_the_level_below_the_road_does_not(self):
        """Asked to repave one level too low, this found stone, called stone the road
        surface, and laid stone across the carriageway. What separates them is that the
        row under a road spreads sideways without end and the road stops at its width."""
        reader = support.road(y=Y)
        self.assertIsNone(roads.bounded_slice(reader, Y - 1, 0, ACROSS, True))
        self.assertIsNone(roads.road_slice(reader, Y - 1, 0, 1, ACROSS, True))

    def test_a_hillside_is_not_road_however_solid_it_is(self):
        reader = support.FakeReader()
        reader.fill((-60, Y, -60, 60, Y, 60), "minecraft:stone")
        self.assertIsNone(roads.road_slice(reader, Y, 0, 1, ACROSS, True))

    def test_a_band_that_runs_a_little_past_the_strip_is_not_road(self):
        """A band of stone happened to run five blocks past a strip and no further,
        which a generous width tolerance waved through."""
        reader = support.FakeReader()
        reader.fill((-60, Y, -7, 60, Y, 7), "minecraft:stone")
        self.assertIsNone(roads.road_slice(reader, Y, 0, 1, ACROSS, True))

    def test_a_gap_across_the_width_disqualifies_the_slice(self):
        """One passable spot means an edge, a hole, or ground that merely sits beside
        the road. Cloning any of those carries the flaw the whole way."""
        reader = support.road(y=Y)
        reader.clear((0, Y, 0, 0, Y, 0))
        self.assertIsNone(roads.slice_names(reader, Y, 0, ACROSS, True))
        self.assertIsNone(roads.road_slice(reader, Y, 0, 1, ACROSS, True))

    def test_a_surface_that_does_not_repeat_along_its_length_is_not_road(self):
        """Bounded is half the test. A road is built, so the same slice repeats far
        beyond anything natural ground holds for."""
        reader = support.FakeReader()
        reader.fill((0, Y, -2, 3, Y, 2), SURFACE)
        self.assertIsNotNone(roads.bounded_slice(reader, Y, 1, ACROSS, True))
        self.assertIsNone(roads.road_slice(reader, Y, 1, 1, ACROSS, True))

    def test_spreads_across_sees_ground_and_not_a_carriageway(self):
        reader = support.road(y=Y)
        self.assertFalse(roads.spreads_across(reader, Y, 0, ACROSS, True, {SURFACE}))
        base = reader.block(0, Y - 1, 0)
        self.assertTrue(roads.spreads_across(reader, Y - 1, 0, ACROSS, True, {base}))


class FindingRoadBesideDamage(support.TestCase):
    """A repave is called on damage, so the blocks beside the strip are often damaged
    too. Looking only at the two flanking blocks refused on a road that was merely
    pitted."""

    def test_road_is_found_past_a_damaged_strip(self):
        reader = support.road(y=Y)
        reader.clear((-4, Y, -2, 4, Y, 2))
        self.assertTrue(roads.carriageway_near(reader, Y, -4, 4, ACROSS, True))

    def test_road_is_found_past_a_pitted_stretch(self):
        reader = support.road(y=Y)
        reader.clear((-4, Y, -2, 4, Y, 2))
        for t in (-6, -8, 7, 11):
            reader.clear((t, Y, 0, t, Y, 0))
        self.assertTrue(roads.carriageway_near(reader, Y, -4, 4, ACROSS, True))

    def test_open_ground_has_no_road_near_it(self):
        reader = support.FakeReader()
        reader.fill((-60, Y, -60, 60, Y, 60), "minecraft:grass_block")
        self.assertFalse(roads.carriageway_near(reader, Y, -4, 4, ACROSS, True))

    def test_the_wrong_level_has_no_road_near_it(self):
        reader = support.road(y=Y)
        self.assertFalse(roads.carriageway_near(reader, Y - 1, -4, 4, ACROSS, True))


class Coordinates(support.TestCase):

    def test_along_x_puts_the_road_position_in_x(self):
        self.assertEqual(roads.at(7, -2, True), (7, -2))

    def test_along_z_puts_the_road_position_in_z(self):
        self.assertEqual(roads.at(7, -2, False), (-2, 7))


if __name__ == "__main__":
    unittest.main()
