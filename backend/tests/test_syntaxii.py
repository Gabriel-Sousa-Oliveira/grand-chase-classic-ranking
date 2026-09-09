import io
import unittest

from gc_radar.syntaxii import ARCHIVE_DUNGEONS, DUNGEONS, parse_sheet


class SyntaxiiImportTests(unittest.TestCase):
    def test_all_public_dungeons_are_registered(self):
        self.assertEqual(len(DUNGEONS), 7)
        self.assertEqual(len(ARCHIVE_DUNGEONS), 4)
        self.assertEqual(
            {d.category for d in DUNGEONS},
            {"void_invasion", "void_taint", "void_nightmare", "void_apocalypse",
             "tower_of_disappearance", "duel_4", "loj_unlimited"},
        )

    def test_parses_numbered_character_and_known_time(self):
        source = (
            "Void 1 3f,Average Time:,01:01\n"
            "Position,Character,Player,Time,Time (array),Speedrun video:,Post date (dd/mm/yyyy)\n"
            "1,06) Ronan,Syntaxii,01:01,61.00,https://www.youtube.com/watch?v=MKfOdv2dBjk,03/07/2026\n"
        )
        rows = parse_sheet(source, DUNGEONS[0])
        self.assertEqual(rows[0]["character"], "Ronan")
        self.assertEqual(rows[0]["player_nick"], "Syntaxii")
        self.assertEqual(rows[0]["time_ms"], 61_000)
        self.assertEqual(rows[0]["published_at"], "2026-07-03")

    def test_ignores_empty_rows(self):
        source = (
            "Position,Character,Player,Time,Time (array),Speedrun video:,Post date (dd/mm/yyyy)\n"
            ",01) Elesis,,,,,\n"
        )
        self.assertEqual(parse_sheet(source, DUNGEONS[0]), [])


if __name__ == "__main__":
    unittest.main()
