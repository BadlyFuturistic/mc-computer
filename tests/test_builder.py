"""builder — the merge that turns cells into fills, and the splits that keep them legal.

Every tool that writes a shape goes through here, so an error in this file reaches
`mcshape`, `mcfill`, `mcbore`, `mcpave` and `mcbranch` at once. Two claims are worth
pinning down above all: the merge loses nothing, and no piece it produces is bigger than
the server will accept.
"""
import unittest

import support
import builder


def expand(boxes):
    """Every cell covered by a list of boxes, as a list so overlaps are visible."""
    cells = []
    for x1, y1, z1, x2, y2, z2 in boxes:
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                for z in range(z1, z2 + 1):
                    cells.append((x, y, z))
    return cells


def cuboid(x1, y1, z1, x2, y2, z2):
    return {(x, y, z)
            for x in range(x1, x2 + 1)
            for y in range(y1, y2 + 1)
            for z in range(z1, z2 + 1)}


class MergeIsLossless(support.TestCase):

    def test_cuboid_becomes_one_fill(self):
        cells = cuboid(0, 0, 0, 9, 4, 7)
        self.assertEqual(builder.to_boxes(cells), [(0, 0, 0, 9, 4, 7)])

    def test_empty_input_makes_no_fills(self):
        self.assertEqual(builder.to_boxes(set()), [])

    def test_single_cell(self):
        self.assertEqual(builder.to_boxes({(3, 4, 5)}), [(3, 4, 5, 3, 4, 5)])

    def test_a_gap_is_not_paved_over(self):
        cells = cuboid(0, 0, 0, 4, 0, 0) - {(2, 0, 0)}
        self.assertEqual(sorted(builder.to_boxes(cells)),
                         [(0, 0, 0, 1, 0, 0), (3, 0, 0, 4, 0, 0)])

    def test_boxes_cover_the_cells_exactly_and_once(self):
        """The claim the whole merge rests on: same cells out as in, none twice.

        A duplicated cell would be filled twice, which is slow but harmless. A missing
        one is a hole in the shape, which is not.
        """
        for name, cells in (
                ("sphere", {(x, y, z)
                            for x in range(-9, 10) for y in range(-9, 10)
                            for z in range(-9, 10) if x * x + y * y + z * z <= 81}),
                ("ragged", {(x, y, z)
                            for x in range(12) for y in range(6) for z in range(9)
                            if (x * 7 + y * 13 + z * 3) % 5}),
                ("hollow", cuboid(0, 0, 0, 8, 8, 8) - cuboid(2, 2, 2, 6, 6, 6)),
                ("two lumps", cuboid(0, 0, 0, 3, 3, 3) | cuboid(20, 7, 30, 24, 9, 33))):
            with self.subTest(name):
                covered = expand(builder.to_boxes(cells))
                self.assertEqual(sorted(covered), sorted(cells),
                                 f"{name}: merge changed which cells are filled")
                self.assertEqual(len(covered), len(set(covered)),
                                 f"{name}: a cell is covered by two boxes")

    def test_merge_is_worth_doing(self):
        """A slab must not come back as one fill per block; that was the point."""
        cells = cuboid(0, 0, 0, 39, 0, 39)
        self.assertEqual(len(builder.to_boxes(cells)), 1)


class SplitStaysInsideTheServerLimit(support.TestCase):

    def test_every_piece_is_within_the_cap(self):
        for box in ((0, 0, 0, 63, 63, 63), (0, 0, 0, 199, 3, 199), (0, 0, 0, 0, 0, 0)):
            with self.subTest(box=box):
                for x1, y1, z1, x2, y2, z2 in builder.split(box):
                    volume = (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1)
                    self.assertLessEqual(volume, builder.MAX_BLOCKS_PER_FILL)

    def test_pieces_cover_the_box_exactly_and_once(self):
        box = (0, 0, 0, 99, 9, 99)
        covered = expand(list(builder.split(box)))
        self.assertEqual(len(covered), 100 * 10 * 100)
        self.assertEqual(len(set(covered)), len(covered), "a block is filled twice")

    def test_a_single_layer_over_the_cap_splits_across_z(self):
        """One y-layer of this box is 40,000 blocks, past the 32,768 limit."""
        pieces = list(builder.split((0, 0, 0, 199, 0, 199)))
        self.assertGreater(len(pieces), 1)
        for x1, y1, z1, x2, y2, z2 in pieces:
            self.assertLessEqual((x2 - x1 + 1) * (z2 - z1 + 1),
                                 builder.MAX_BLOCKS_PER_FILL)

    def test_a_small_box_is_left_alone(self):
        self.assertEqual(list(builder.split((5, 6, 7, 9, 8, 11))),
                         [(5, 6, 7, 9, 8, 11)])


class ForceloadStaysUnderTheChunkCap(support.TestCase):
    """The 645-chunk incident: one `forceload add` past the cap loads nothing at all,
    and the clones that follow go into chunks that are not there."""

    def test_no_piece_asks_for_more_chunks_than_the_server_allows(self):
        for region_box in ((0, 0, 2000, 2000), (-4200, -1900, -1000, 900),
                           (0, 0, 15, 15)):
            with self.subTest(region_box):
                for x1, z1, x2, z2 in builder.load_boxes(*region_box):
                    chunks = (((x2 >> 4) - (x1 >> 4) + 1)
                              * ((z2 >> 4) - (z1 >> 4) + 1))
                    self.assertLessEqual(chunks, builder.FORCELOAD_CAP)

    def test_the_pieces_cover_the_whole_region(self):
        pieces = builder.load_boxes(0, 0, 500, 300)
        self.assertEqual(min(p[0] for p in pieces), 0)
        self.assertEqual(min(p[1] for p in pieces), 0)
        self.assertEqual(max(p[2] for p in pieces), 500)
        self.assertEqual(max(p[3] for p in pieces), 300)

    def test_pieces_do_not_reach_outside_the_region(self):
        for x1, z1, x2, z2 in builder.load_boxes(10, 20, 100, 200):
            self.assertGreaterEqual(x1, 10)
            self.assertGreaterEqual(z1, 20)
            self.assertLessEqual(x2, 100)
            self.assertLessEqual(z2, 200)


class Shell(support.TestCase):

    def test_one_layer_of_a_cube_is_its_surface(self):
        cells = cuboid(0, 0, 0, 6, 6, 6)
        self.assertEqual(len(builder.shell(cells, 1)), 7 ** 3 - 5 ** 3)

    def test_two_layers_go_deeper(self):
        cells = cuboid(0, 0, 0, 8, 8, 8)
        self.assertEqual(len(builder.shell(cells, 2)), 9 ** 3 - 5 ** 3)

    def test_a_shell_is_a_subset_of_the_shape(self):
        cells = {(x, y, z) for x in range(-6, 7) for y in range(-6, 7)
                 for z in range(-6, 7) if x * x + y * y + z * z <= 36}
        self.assertTrue(builder.shell(cells, 1) <= cells)

    def test_a_thin_shape_is_all_surface(self):
        cells = cuboid(0, 0, 0, 5, 0, 5)
        self.assertEqual(builder.shell(cells, 1), cells)

    def test_thickness_beyond_the_shape_stops_rather_than_looping(self):
        cells = cuboid(0, 0, 0, 2, 2, 2)
        self.assertEqual(builder.shell(cells, 99), cells)

    def test_no_cells_no_shell(self):
        self.assertEqual(builder.shell(set(), 1), set())


class Bounds(support.TestCase):

    def test_bounds_of_scattered_cells(self):
        self.assertEqual(builder.bounds({(1, 2, 3), (-4, 9, 0), (7, -1, 5)}),
                         (-4, -1, 0, 7, 9, 5))

    def test_bounds_of_one_cell_is_that_cell_twice(self):
        self.assertEqual(builder.bounds({(3, 4, 5)}), (3, 4, 5, 3, 4, 5))


class FallingBlocks(support.TestCase):
    """Sand over a hole empties the column from the ground to the sky."""

    def test_sand_resting_on_a_cell_about_to_go_is_reported(self):
        reader = support.FakeReader({(5, 11, 5): "minecraft:sand"})
        self.assertEqual(builder.falling_above(reader, {(5, 10, 5)}), {(5, 11, 5)})

    def test_stone_above_is_not_reported(self):
        reader = support.FakeReader({(5, 11, 5): "minecraft:stone"})
        self.assertEqual(builder.falling_above(reader, {(5, 10, 5)}), set())

    def test_sand_inside_the_shape_is_not_double_counted(self):
        reader = support.FakeReader({(5, 11, 5): "minecraft:sand"})
        cells = {(5, 10, 5), (5, 11, 5)}
        self.assertEqual(builder.falling_above(reader, cells), set())

    def test_a_box_reports_gravel_sitting_on_its_lid(self):
        reader = support.FakeReader()
        reader.fill((0, 6, 0, 2, 6, 2), "minecraft:gravel")
        found = builder.falling_over_box(reader, (0, 0, 0, 2, 5, 2))
        self.assertEqual(len(found), 9)


if __name__ == "__main__":
    unittest.main()
