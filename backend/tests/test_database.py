import tempfile
import unittest
from pathlib import Path

from gc_radar.database import CandidateRepository
from gc_radar.parser import parse_title


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = CandidateRepository(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_duplicate_video_is_not_inserted_twice(self):
        parsed = parse_title("Ereb | Vazio (Invasão) 3f (1'32)")
        first, created_first = self.repo.add("WZeUJAw4pmU", "https://youtu.be/WZeUJAw4pmU", parsed)
        second, created_second = self.repo.add("WZeUJAw4pmU", "https://youtu.be/WZeUJAw4pmU", parsed)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.repo.queue()), 1)

    def test_direct_refresh_reclassifies_an_existing_pending_video(self):
        old = parse_title("Ereb | Grand Chase Classic")
        first, created = self.repo.add(
            "Q2TUPeiTmPI", "https://youtu.be/Q2TUPeiTmPI", old,
            channel="Borkaz"
        )
        self.assertTrue(created)
        self.assertEqual(first["status"], "classification_required")

        refreshed = parse_title(
            "Ereb | Infinity Cloister Stage 4 Duell | Grand Chase Classic"
        )
        updated, created_again = self.repo.add(
            "Q2TUPeiTmPI", "https://youtu.be/Q2TUPeiTmPI", refreshed,
            channel="Borkaz", enrich_existing=True
        )
        self.assertFalse(created_again)
        self.assertEqual(updated["character"], "Ereb")
        self.assertEqual(updated["category"], "duel_4")
        self.assertEqual(updated["floor"], 0)
        self.assertEqual(updated["status"], "time_required")

    def test_missing_time_blocks_approval_until_filled(self):
        parsed = parse_title("Lupus | Vazio (Apocalipse) 3F Solo Sem poções")
        candidate, _ = self.repo.add("aTglQvuekIE", "https://youtu.be/aTglQvuekIE", parsed)
        with self.assertRaises(ValueError):
            self.repo.decide(candidate["id"], True)
        updated = self.repo.set_time(candidate["id"], 180_000)
        self.assertEqual(updated["status"], "ready_for_review")
        approved = self.repo.decide(candidate["id"], True)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(self.repo.ranking("void_apocalypse", 3)), 1)

    def test_character_ranking_keeps_best_run_per_nick_and_top_four(self):
        for index, (nick, seconds) in enumerate([
            ("RunnerA", 60), ("RunnerB", 61), ("RunnerA", 59),
            ("RunnerC", 62), ("RunnerD", 63), ("RunnerE", 64)
        ]):
            stamp = f"{seconds // 60:02d}:{seconds % 60:02d}"
            parsed = parse_title(f"Ronan Void Invasion 3F {stamp}")
            candidate, _ = self.repo.add(
                f"ronan-{index}", f"https://youtu.be/ronan-{index}", parsed,
                channel=f"Channel{index}", player_nick=nick, era_key="era-balance-1"
            )
            self.repo.decide(candidate["id"], True)
        ranking = self.repo.character_ranking(
            "void_invasion", 3, "Ronan", "era-balance-1"
        )
        self.assertEqual([row["player_nick"] for row in ranking],
                         ["RunnerA", "RunnerB", "RunnerC", "RunnerD"])
        self.assertEqual(ranking[0]["time_ms"], 59_000)

    def test_eras_do_not_mix_records(self):
        for era, seconds in [("old-patch", 58), ("current", 60)]:
            stamp = f"{seconds // 60:02d}:{seconds % 60:02d}"
            parsed = parse_title(f"Ronan Void Invasion 3F {stamp}")
            candidate, _ = self.repo.add(
                era, f"https://youtu.be/{era}", parsed,
                player_nick="SameNick", era_key=era
            )
            self.repo.decide(candidate["id"], True)
        current = self.repo.character_ranking("void_invasion", 3, "Ronan")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["time_ms"], 60_000)

    def test_ocr_attempt_rotates_queue_and_records_evidence(self):
        first, _ = self.repo.add("first", "https://youtu.be/first",
                                 parse_title("Ronan Void Invasion 3F"))
        second, _ = self.repo.add("second", "https://youtu.be/second",
                                  parse_title("Arme Void Invasion 3F"))
        self.repo.record_ocr_attempt(first["id"], "no_consensus")
        self.assertEqual(self.repo.time_required(1)[0]["id"], second["id"])
        updated = self.repo.set_ocr_time(first["id"], 92_000, 0.82,
                                         {"engine": "tesseract", "matching_frames": 3})
        self.assertEqual(updated["status"], "ready_for_review")
        self.assertEqual(updated["time_ms"], 92_000)
        self.assertIn('"ocr"', updated["raw_metadata"])


if __name__ == "__main__":
    unittest.main()
