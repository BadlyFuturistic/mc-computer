"""The scenario files parse, and say what a scenario has to say.

A scenario with no `forbid`, or a `world` whose canned command never matches, looks
exactly like a passing test and checks nothing. These run in the ordinary suite so a
broken scenario is found when it is written rather than when the harness is next run.
"""
import re
import unittest
from pathlib import Path

import support                                              # noqa: F401  (sets up path)
import miniyaml

SCENARIOS = Path(__file__).parent / "prompt-scenarios"
FILES = sorted(SCENARIOS.glob("*.yaml"))


class TheSubsetParser(support.TestCase):

    def test_a_mapping(self):
        self.assertEqual(miniyaml.load("a: 1\nb: two\n"), {"a": 1, "b": "two"})

    def test_a_block_scalar_keeps_its_lines_and_loses_its_indent(self):
        got = miniyaml.load("why: |\n  one\n  two\nname: x\n")
        self.assertEqual(got["why"], "one\ntwo\n")
        self.assertEqual(got["name"], "x")

    def test_a_list_of_strings(self):
        self.assertEqual(miniyaml.load("expect:\n  - one\n  - two\n"),
                         {"expect": ["one", "two"]})

    def test_a_list_of_mappings_with_a_block_scalar_inside(self):
        got = miniyaml.load(
            'world:\n'
            '  commands:\n'
            '    - match: "mcfill"\n'
            '      stdout: |\n'
            '        changed 0 block(s)\n'
            '      exit: 1\n'
            '    - match: "compsay"\n'
            '      stdout: ""\n')
        commands = got["world"]["commands"]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["match"], "mcfill")
        self.assertEqual(commands[0]["stdout"], "changed 0 block(s)\n")
        self.assertEqual(commands[0]["exit"], 1)
        self.assertEqual(commands[1], {"match": "compsay", "stdout": ""})

    def test_a_hash_inside_a_value_is_not_a_comment(self):
        got = miniyaml.load('a: "#minecraft:logs"\n# a real comment\nb: 2\n')
        self.assertEqual(got, {"a": "#minecraft:logs", "b": 2})

    def test_bad_indentation_raises_rather_than_guessing(self):
        with self.assertRaises(miniyaml.YamlError):
            miniyaml.load("a: 1\n    b: 2\n")


class EveryScenario(support.TestCase):

    def test_there_are_some(self):
        self.assertGreaterEqual(len(FILES), 8)
        self.assertLessEqual(len(FILES), 10, "this is a suite to read, not a coverage "
                                             "exercise")

    def test_each_one_parses_and_carries_what_a_scenario_needs(self):
        for path in FILES:
            with self.subTest(path.name):
                s = miniyaml.load(path.read_text())
                for key in ("name", "behaviour", "why", "utterance", "expect", "forbid"):
                    self.assertIn(key, s, f"{path.name} has no {key}")
                self.assertTrue(s["expect"], "a scenario with nothing expected passes "
                                             "whatever happens")
                self.assertTrue(s["forbid"], "a scenario with nothing forbidden cannot "
                                             "catch a regression")

    def test_the_name_matches_the_filename(self):
        for path in FILES:
            with self.subTest(path.name):
                s = miniyaml.load(path.read_text())
                self.assertEqual(s["name"], re.sub(r"^\d+-", "", path.stem))

    def test_the_utterance_looks_like_minecraft_chat(self):
        """The harness feeds these in as chat lines, so a bare sentence would be testing
        a message shape the daemon never sends."""
        for path in FILES:
            with self.subTest(path.name):
                s = miniyaml.load(path.read_text())
                for line in s["utterance"].strip().splitlines():
                    self.assertRegex(line, r"^<[A-Za-z0-9_]+> .+")

    def test_every_canned_command_is_a_usable_pattern(self):
        for path in FILES:
            with self.subTest(path.name):
                s = miniyaml.load(path.read_text())
                for command in (s.get("world") or {}).get("commands") or []:
                    self.assertIn("match", command)
                    re.compile(command["match"])
                    self.assertIn("stdout", command)

    def test_the_scenarios_cover_the_failures_this_world_actually_had(self):
        names = {miniyaml.load(p.read_text())["name"] for p in FILES}
        for required in ("teleport-relative", "pave-over-player-blocks",
                         "structure-identity", "progress-updates",
                         "persona-imitation", "item-id-guess"):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
