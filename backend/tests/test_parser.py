import unittest
from gc_radar.parser import parse_title


class ParserTests(unittest.TestCase):
    def test_ereb_invasion_with_time(self):
        run = parse_title("Ereb | Vazio (Invasão) 3f (1'32) | Grand Chase Classic")
        self.assertEqual((run.character, run.category, run.floor, run.time_ms),
                         ("Ereb", "void_invasion", 3, 92_000))
        self.assertEqual(run.status, "ready_for_review")
        self.assertEqual(run.missing_fields, ())

    def test_ereb_nightmare_needs_time(self):
        run = parse_title("Ereb | Void(Nightmare) 4f | Grand Chase Classic")
        self.assertEqual((run.character, run.category, run.floor),
                         ("Ereb", "void_nightmare", 4))
        self.assertIsNone(run.time_ms)
        self.assertEqual(run.status, "time_required")

    def test_lupus_apocalypse_flags(self):
        run = parse_title("Lupus | Vazio (Apocalipse) 3F Solo Sem poções | Grand Chase Classic")
        self.assertEqual(run.character, "Rufus/Lupus")
        self.assertEqual(run.category, "void_apocalypse")
        self.assertEqual(run.floor, 3)
        self.assertTrue(run.solo)
        self.assertTrue(run.no_potions)
        self.assertEqual(run.status, "time_required")

    def test_other_time_formats(self):
        self.assertEqual(parse_title("Ronan Void Invasion 3F 01:02.345").time_ms, 62_345)
        self.assertEqual(parse_title("Ronan Void Invasion 3F 1m 02s").time_ms, 62_000)

    def test_regional_character_aliases(self):
        self.assertEqual(parse_title("Azin Vazio Invasão 3F 1:00").character, "Asin")
        self.assertEqual(parse_title("Decane Void Invasion 3F 1:00").character, "Decanee")
        self.assertEqual(parse_title("Uno Void Invasion 3F 1:00").character, "Uno")


if __name__ == "__main__":
    unittest.main()
