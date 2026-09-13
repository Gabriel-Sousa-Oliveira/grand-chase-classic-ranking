import unittest

from gc_radar.parser import parse_title
from gc_radar.relevance import (description_from_metadata,
                                evaluate_video_relevance)


class RelevanceTests(unittest.TestCase):
    def decide(self, title, description=""):
        return evaluate_video_relevance(title, description, parse_title(title))

    def test_accepts_structured_individual_borkaz_run_without_time(self):
        decision = self.decide(
            "Ereb | Void(Nightmare) 4f | Grand Chase Classic"
        )
        self.assertTrue(decision.accepted)
        self.assertIn("individual_title_structure", decision.reasons)

    def test_rejects_explicit_many_character_video(self):
        decision = self.decide(
            "Ereb Void Invasion with 23 Characters | Grand Chase Classic"
        )
        self.assertFalse(decision.accepted)
        self.assertTrue(decision.hard_reject)
        self.assertEqual(decision.reasons, ("multi_character_title",))

    def test_rejects_guide_even_when_many_aliases_are_present(self):
        decision = self.decide(
            "Skill Tree Guide 2026 (Rufus, Rin, Asin, Edel update)"
        )
        self.assertFalse(decision.accepted)
        self.assertTrue(decision.hard_reject)
        self.assertEqual(decision.reasons, ("editorial_title",))

    def test_rejects_multi_character_chapter_description(self):
        description = "\n".join([
            "00:00 Elesis", "01:15 Lire", "02:30 Arme", "03:45 Lass",
        ])
        decision = self.decide(
            "Ereb | Void Invasion 3F | Grand Chase Classic", description
        )
        self.assertFalse(decision.accepted)
        self.assertTrue(decision.hard_reject)
        self.assertEqual(decision.reasons, ("multi_character_chapters",))

    def test_generic_gameplay_does_not_count_as_run_intent(self):
        decision = self.decide("Ronan Void Invasion 3F gameplay")
        self.assertFalse(decision.accepted)
        self.assertFalse(decision.hard_reject)
        self.assertIn("missing_run_context", decision.reasons)

    def test_accepts_korean_and_thai_run_language(self):
        titles = (
            "그랜드체이스 클래식 아신 공허 침공 3층 스피드런",
            "แกรนด์เชส คลาสสิก อาซิน วอยด์ อินเวชัน 3ชั้น สปีดรัน",
        )
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(self.decide(title).accepted)

    def test_extracts_description_from_youtube_metadata_shapes(self):
        metadata = {"snippet": {"description": "00:00 Ereb"}}
        self.assertEqual(description_from_metadata(metadata), "00:00 Ereb")
        self.assertEqual(description_from_metadata(
            '{"snippet":{"description":"speedrun"}}'
        ), "speedrun")


if __name__ == "__main__":
    unittest.main()
