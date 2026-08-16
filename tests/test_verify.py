"""verify — reading a box back, and catching a write that reported a success it did not
achieve.

The case this exists for: `mcrepave` cloned a hillside into a bored tunnel, 1190 blocks,
and reported every one as a success because RCON had accepted every command. The count
was true and the road was wrong.
"""
import unittest

import support
import verify

Y = 64
ROAD = "minecraft:gray_concrete"


class BlockNames(support.TestCase):

    def test_the_namespace_and_the_state_come_off(self):
        self.assertEqual(verify.short("minecraft:oak_log[axis=x]"), "oak_log")
        self.assertEqual(verify.short("oak_log"), "oak_log")
        self.assertEqual(verify.short("create:andesite_casing"), "andesite_casing")

    def test_nothing_stays_nothing(self):
        self.assertIsNone(verify.short(None))


class Deltas(support.TestCase):

    def test_what_went_up(self):
        self.assertEqual(verify.gained({"stone": 10}, {"stone": 14, "sand": 3}),
                         {"stone": 4, "sand": 3})

    def test_what_went_down(self):
        self.assertEqual(verify.lost({"stone": 10, "sand": 3}, {"stone": 4}),
                         {"stone": 6, "sand": 3})

    def test_no_change_is_no_delta(self):
        self.assertEqual(verify.gained({"stone": 10}, {"stone": 10}), {})
        self.assertEqual(verify.lost({"stone": 10}, {"stone": 10}), {})


class ConfirmingAWrite(support.TestCase):

    def test_a_write_that_landed_is_accepted(self):
        self.assertIsNone(verify.confirm({}, {ROAD: 100}, ROAD, 100))

    def test_a_write_into_chunks_that_were_not_loaded_is_caught(self):
        """The world did not move at all, and RCON still answered cheerfully."""
        problem = verify.confirm({"minecraft:stone": 50}, {"minecraft:stone": 50},
                                 ROAD, 129)
        self.assertIsNotNone(problem)
        self.assertIn("129", problem)
        self.assertIn("nothing in the box changed", problem)

    def test_a_clone_that_copied_the_wrong_thing_is_caught(self):
        """1190 blocks moved, none of them road. The message has to name what did
        change, because that is what tells you where the source was wrong."""
        problem = verify.confirm({}, {"minecraft:stone": 900, "minecraft:dirt": 290},
                                 ROAD, 1190)
        self.assertIsNotNone(problem)
        self.assertIn("stone", problem)

    def test_a_large_shortfall_is_caught(self):
        problem = verify.confirm({}, {ROAD: 40}, ROAD, 1000)
        self.assertIsNotNone(problem)
        self.assertIn("40", problem)

    def test_filling_over_ground_that_already_held_the_block_is_not_a_failure(self):
        """A fill reports the blocks it changed, so a box that already held some of the
        target legitimately gains fewer than the box holds."""
        self.assertIsNone(verify.confirm({ROAD: 60}, {ROAD: 100}, ROAD, 40))

    def test_a_block_state_still_matches_its_plain_id(self):
        self.assertIsNone(
            verify.confirm({}, {"minecraft:oak_log": 20},
                           "minecraft:oak_log[axis=x]", 20))

    def test_a_write_that_claimed_nothing_is_not_second_guessed(self):
        self.assertIsNone(verify.confirm({}, {}, ROAD, 0))


class WatchingAWrite(support.TestCase):
    """What a writing tool actually calls. `region.Reader` is swapped for a dict-backed
    reader whose contents change between the two reads, which is a write."""

    def setUp(self):
        self.real_reader = verify.region.Reader
        self.reader = support.FakeReader()
        self.reader.fill((0, 60, 0, 9, 60, 9), "minecraft:grass_block")
        verify.region.Reader = lambda dimension: self.reader

    def tearDown(self):
        verify.region.Reader = self.real_reader

    def box(self):
        return (0, 60, 0, 9, 60, 9)

    def test_a_write_that_landed_is_confirmed(self):
        watch = verify.Watch("minecraft:overworld", self.box())
        self.reader.fill(self.box(), "minecraft:gray_concrete")
        self.assertIsNone(watch.check("minecraft:gray_concrete", 100))
        self.assertIsNone(watch.note)

    def test_a_write_that_did_not_land_is_refused(self):
        watch = verify.Watch("minecraft:overworld", self.box())
        problem = watch.check("minecraft:gray_concrete", 100)
        self.assertIsNotNone(problem)

    def test_the_world_is_read_again_after_the_write_and_not_before(self):
        """Comparing a box against itself would pass every write ever made."""
        watch = verify.Watch("minecraft:overworld", self.box())
        self.assertEqual(self.reader.flushes, 1)
        self.reader.fill(self.box(), "minecraft:gray_concrete")
        watch.check("minecraft:gray_concrete", 100)
        self.assertEqual(self.reader.flushes, 2)

    def test_two_checks_share_one_read(self):
        watch = verify.Watch("minecraft:overworld", self.box())
        self.reader.fill(self.box(), "minecraft:gray_concrete")
        watch.check("minecraft:gray_concrete", 100)
        watch.unexpected({"minecraft:gray_concrete"})
        self.assertEqual(self.reader.flushes, 2)

    def test_a_clone_from_the_wrong_source_is_caught_by_kind(self):
        """The 1190-block case: every command succeeded and the tunnel filled with
        hillside. The count is right and the contents are not."""
        watch = verify.Watch("minecraft:overworld", self.box())
        self.reader.fill(self.box(), "minecraft:stone")
        problem = watch.unexpected({"car:line_white", "minecraft:air"})
        self.assertIsNotNone(problem)
        self.assertIn("minecraft:stone", problem)

    def test_snow_on_a_finished_road_is_not_treated_as_damage(self):
        """Weather arrives between the write and the read. A check that fails on it
        gets switched off, and then it protects nothing."""
        watch = verify.Watch("minecraft:overworld", self.box())
        self.reader.fill(self.box(), "car:line_white")
        self.reader.fill((3, 60, 3, 4, 60, 4), "minecraft:snow")
        self.assertIsNone(watch.unexpected({"car:line_white", "minecraft:air"}))

    def test_a_world_that_cannot_be_read_says_so_and_does_not_block_the_write(self):
        verify.region.Reader = self._raising
        watch = verify.Watch("minecraft:overworld", self.box())
        self.assertIsNone(watch.check("minecraft:stone", 100))
        self.assertIn("could not read", watch.note)

    def test_a_read_that_fails_after_the_write_says_so_rather_than_passing_quietly(self):
        watch = verify.Watch("minecraft:overworld", self.box())

        def explode(_reader):
            raise OSError("region file vanished")

        self.reader.on_flush = explode
        self.assertIsNone(watch.check("minecraft:stone", 100))
        self.assertIn("could not read the box back", watch.note)

    @staticmethod
    def _raising(dimension):
        raise OSError("no region files")


class ReportingABox(support.TestCase):

    def flat_world(self, surface="minecraft:grass_block"):
        reader = support.FakeReader()
        reader.fill((-40, Y - 4, -40, 40, Y, 40), "minecraft:stone")
        reader.fill((-40, Y, -40, 40, Y, 40), surface)
        return reader

    def test_counts_and_surfaces_of_plain_ground(self):
        found = verify.report(self.flat_world(), (0, Y - 2, 0, 9, Y, 9))
        self.assertEqual(found["volume"], 10 * 3 * 10)
        self.assertEqual(found["blocks"]["minecraft:grass_block"], 100)
        self.assertEqual(found["surface"]["columns"], 100)
        self.assertEqual(found["surface"]["min"], Y)
        self.assertEqual(found["surface"]["max"], Y)
        self.assertEqual(found["voids"]["empty_columns"], 0)

    def test_a_hole_in_the_ground_reads_as_empty_columns(self):
        reader = self.flat_world()
        reader.clear((2, Y - 2, 2, 4, Y, 4))
        found = verify.report(reader, (0, Y - 2, 0, 9, Y, 9))
        self.assertEqual(found["voids"]["empty_columns"], 9)
        self.assertEqual(len(found["voids"]["empty"]), 9)

    def test_a_cavity_under_the_surface_reads_as_undermined(self):
        """A road with the ground scooped out from under it looks perfect from above,
        and this is the only field that says otherwise."""
        reader = self.flat_world()
        reader.clear((2, Y - 2, 2, 4, Y - 1, 4))
        found = verify.report(reader, (0, Y - 4, 0, 9, Y, 9))
        self.assertEqual(found["voids"]["undermined_columns"], 9)
        x, z, surface, holes = found["voids"]["undermined"][0]
        self.assertEqual(surface, Y)
        self.assertEqual(holes, 2)

    def test_a_cave_well_below_solid_ground_is_not_undermining_it(self):
        """Counting every air block in the column called 1,547 of 1,681 columns
        undermined over ordinary cave country. A number that fires on everything
        says nothing."""
        reader = self.flat_world()
        reader.clear((0, Y - 20, 0, 9, Y - 10, 9))
        found = verify.report(reader, (0, Y - 30, 0, 9, Y, 9))
        self.assertEqual(found["voids"]["undermined_columns"], 0)

    def test_a_players_build_shows_up_as_foreign(self):
        reader = self.flat_world()
        reader.fill((3, Y, 3, 6, Y + 3, 6), "minecraft:cobblestone")
        found = verify.report(reader, (0, Y, 0, 9, Y + 4, 9))
        self.assertIn("minecraft:cobblestone", found["foreign"])
        self.assertNotIn("minecraft:grass_block", found["foreign"])

    def test_terrain_the_surroundings_also_use_is_not_foreign(self):
        found = verify.report(self.flat_world(), (0, Y - 2, 0, 9, Y, 9))
        self.assertEqual(found["foreign"], {})

    def test_with_no_terrain_around_it_foreign_is_refused_rather_than_guessed(self):
        """Everything-is-foreign is a wrong answer, not a loud one."""
        reader = support.FakeReader()
        reader.fill((0, Y, 0, 9, Y, 9), "minecraft:cobblestone")
        found = verify.report(reader, (0, Y, 0, 9, Y, 9))
        self.assertIsNone(found["foreign"])
        self.assertIn("nothing to compare", found["foreign_note"])

    def test_entities_are_declared_unread_rather_than_implied_clean(self):
        found = verify.report(self.flat_world(), (0, Y, 0, 4, Y, 4))
        self.assertIn("blocks only", found["entities"])

    def test_a_big_footprint_says_so_instead_of_truncating_in_silence(self):
        reader = self.flat_world()
        found = verify.report(reader, (-30, Y, -30, 30, Y, 30), max_columns=100)
        self.assertIsNone(found["columns"])
        self.assertIn("3,721", found["columns_note"])
        # The totals still cover every column, which is what stops this being a
        # truncated answer.
        self.assertEqual(found["surface"]["columns"], 61 * 61)

    def test_a_small_footprint_lists_every_column(self):
        found = verify.report(self.flat_world(), (0, Y, 0, 4, Y, 4))
        self.assertEqual(len(found["columns"]), 25)


if __name__ == "__main__":
    unittest.main()
