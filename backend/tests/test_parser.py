import unittest
from gc_radar.parser import parse_title


class ParserTests(unittest.TestCase):
    def test_parses_duel_without_a_floor(self):
        run = parse_title("Grand Chase Classic Ereb Duel Lv.4 01:05")
        self.assertEqual(run.character, "Ereb")
        self.assertEqual(run.category, "duel_4")
        self.assertEqual(run.floor, 0)
        self.assertEqual(run.time_ms, 65_000)
        self.assertEqual(run.status, "ready_for_review")
        self.assertEqual(run.confidence, 0.95)

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

    def test_decodes_youtube_html_entities_before_parsing(self):
        run = parse_title("Rin | Vazio Invasão 3F 2&#39;08")
        self.assertEqual(run.time_ms, 128_000)
        self.assertEqual(run.status, "ready_for_review")

    def test_regional_character_aliases(self):
        self.assertEqual(parse_title("Azin Vazio Invasão 3F 1:00").character, "Asin")
        self.assertEqual(parse_title("Asin Void Invasion 3F 1:00").character, "Asin")
        self.assertEqual(parse_title("Decane Void Invasion 3F 1:00").character, "Decanee")
        self.assertEqual(parse_title("Uno Void Invasion 3F 1:00").character, "Uno")

    def test_korean_title_is_parsed_without_romanization(self):
        run = parse_title("그랜드체이스 클래식 아신 공허 침공 3층 01:07")
        self.assertEqual((run.character, run.category, run.floor, run.time_ms),
                         ("Asin", "void_invasion", 3, 67_000))
        self.assertEqual(run.status, "ready_for_review")

    def test_thai_title_is_parsed_without_romanization(self):
        run = parse_title("แกรนด์เชส คลาสสิก อาซิน วอยด์ อินเวชัน 3ชั้น 01:08")
        self.assertEqual((run.character, run.category, run.floor, run.time_ms),
                         ("Asin", "void_invasion", 3, 68_000))
        self.assertEqual(run.status, "ready_for_review")

    def test_numbered_void_title_from_youtube(self):
        run = parse_title("Grand Chase Classic - Void 1 Veigas Speedrun 1:27 (No Pots)")
        self.assertEqual((run.character, run.category, run.floor, run.time_ms),
                         ("Veigas", "void_invasion", 3, 87_000))
        self.assertTrue(run.no_potions)
        self.assertEqual(run.status, "ready_for_review")


if __name__ == "__main__":
    unittest.main()
