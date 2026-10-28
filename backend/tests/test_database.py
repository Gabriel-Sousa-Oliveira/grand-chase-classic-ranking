import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from gc_radar.database import CandidateRepository, canonical_player_nick
from gc_radar.parser import parse_title
from gc_radar import cli


class DatabaseTests(unittest.TestCase):
    def test_bork_alias_is_canonicalized_as_borkaz(self):
        self.assertEqual(canonical_player_nick("Bork"), "Borkaz")
        self.assertEqual(canonical_player_nick(" bOrK "), "Borkaz")

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

    def test_metadata_refresh_preserves_ocr_time_and_evidence_for_same_run(self):
        parsed = parse_title("Ronan Void Invasion 3F")
        candidate, _ = self.repo.add("refresh", "https://youtu.be/refresh", parsed,
                                     metadata={"description": "old"})
        self.repo.set_ocr_time(candidate["id"], 80_000, .72,
                               {"roi": "results_panel", "matching_frames": 6})
        updated, created = self.repo.add(
            "refresh", "https://youtu.be/refresh", parsed,
            metadata={"description": "new"}, enrich_existing=True,
        )
        self.assertFalse(created)
        self.assertEqual(updated["time_ms"], 80_000)
        self.assertEqual(updated["status"], "ready_for_review")
        self.assertEqual(updated["confidence"], .72)
        metadata = json.loads(updated["raw_metadata"])
        self.assertEqual(metadata["description"], "new")
        self.assertEqual(metadata["ocr_time_ms"], 80_000)
        self.assertEqual(metadata["ocr"]["matching_frames"], 6)
        self.assertEqual(metadata["ocr_attempts"], 1)
        self.assertNotIn("refresh", {c["video_id"] for c in self.repo.ocr_candidates(0)})

    def test_metadata_refresh_preserves_manually_entered_time(self):
        parsed = parse_title("Ronan Void Invasion 3F")
        candidate, _ = self.repo.add("manual", "https://youtu.be/manual", parsed)
        self.repo.set_time(candidate["id"], 80_000)
        updated, _ = self.repo.add("manual", "https://youtu.be/manual", parsed,
                                    enrich_existing=True)
        self.assertEqual(updated["time_ms"], 80_000)
        self.assertEqual(updated["status"], "ready_for_review")

    def test_classification_refinement_preserves_resolved_time(self):
        for old_title in ("Ronan Void Invasion", "Void Invasion 3F",
                          "Ronan Grand Chase Classic"):
            for source in ("manual", "ocr"):
                with self.subTest(title=old_title, source=source):
                    video_id = f"refine-{source}-{old_title}"
                    candidate, _ = self.repo.add(video_id, "https://youtu.be/refine",
                                                 parse_title(old_title))
                    if source == "manual":
                        self.repo.set_time(candidate["id"], 80_000)
                    else:
                        self.repo.set_ocr_time(candidate["id"], 80_000, .72,
                                               {"roi": "results_panel"})
                    updated, _ = self.repo.add(video_id, "https://youtu.be/refine",
                        parse_title("Ronan Void Invasion 3F"), enrich_existing=True)
                    self.assertEqual(updated["time_ms"], 80_000)
                    self.assertEqual(updated["status"], "ready_for_review")
                    if source == "ocr":
                        self.assertEqual(json.loads(updated["raw_metadata"])["ocr_time_ms"], 80_000)

    def test_partial_refinement_keeps_classification_required(self):
        candidate, _ = self.repo.add("partial", "https://youtu.be/partial",
                                     parse_title("Ronan Grand Chase Classic"))
        self.repo.set_time(candidate["id"], 80_000)
        updated, _ = self.repo.add("partial", "https://youtu.be/partial",
            parse_title("Ronan Void Invasion"), enrich_existing=True)
        self.assertEqual(updated["time_ms"], 80_000)
        self.assertEqual(updated["status"], "classification_required")
        self.assertIsNone(updated["floor"])

    def test_classification_refinement_without_time_still_requires_time(self):
        self.repo.add("untimed", "https://youtu.be/untimed",
                       parse_title("Ronan Void Invasion"))
        updated, _ = self.repo.add("untimed", "https://youtu.be/untimed",
            parse_title("Ronan Void Invasion 3F"), enrich_existing=True)
        self.assertIsNone(updated["time_ms"])
        self.assertEqual(updated["status"], "time_required")

    def test_metadata_refresh_invalidates_time_when_run_identity_changes(self):
        original = parse_title("Ronan Void Invasion 3F")
        for field, replacement in (("character", "Arme"), ("floor", 2),
                                   ("category", "void_nightmare"), ("era_key", "new-era"),
                                   ("character", None), ("category", None), ("floor", None)):
            with self.subTest(field=field):
                video_id = f"changed-{field}-{replacement}"
                candidate, _ = self.repo.add(video_id, f"https://youtu.be/{video_id}", original)
                self.repo.set_ocr_time(candidate["id"], 80_000, .72, {"roi": "results_panel"})
                refreshed = original if field == "era_key" else replace(original, **{field: replacement})
                options = {"era_key": replacement} if field == "era_key" else {}
                updated, _ = self.repo.add(video_id, f"https://youtu.be/{video_id}",
                                            refreshed, metadata={"description": "new"},
                                            enrich_existing=True, **options)
                self.assertIsNone(updated["time_ms"])
                metadata = json.loads(updated["raw_metadata"])
                self.assertEqual(metadata["description"], "new")
                for key in ("ocr", "ocr_time_ms", "ocr_confidence", "evidence_frame",
                            "evidence_image", "ocr_outcome", "ocr_attempts"):
                    self.assertNotIn(key, metadata)

    def test_metadata_refresh_can_take_an_explicit_new_title_time(self):
        candidate, _ = self.repo.add("title-time", "https://youtu.be/title-time",
                                     parse_title("Ronan Void Invasion 3F"))
        self.repo.set_ocr_time(candidate["id"], 80_000, .72, {"roi": "results_panel"})
        updated, _ = self.repo.add("title-time", "https://youtu.be/title-time",
                                    parse_title("Ronan Void Invasion 3F 01:30"),
                                    enrich_existing=True)
        self.assertEqual(updated["time_ms"], 90_000)
        self.assertNotIn("ocr_time_ms", json.loads(updated["raw_metadata"]))

    def test_metadata_refresh_preserves_unresolved_ocr_attempt_history(self):
        parsed = parse_title("Ronan Void Invasion 3F")
        candidate, _ = self.repo.add("unresolved", "https://youtu.be/unresolved", parsed)
        self.repo.record_ocr_attempt(candidate["id"], "no_consensus")
        updated, _ = self.repo.add("unresolved", "https://youtu.be/unresolved", parsed,
                                    metadata={"description": "updated"}, enrich_existing=True)
        metadata = json.loads(updated["raw_metadata"])
        self.assertIsNone(updated["time_ms"])
        self.assertEqual(metadata["ocr_outcome"], "no_consensus")
        self.assertEqual(metadata["ocr_attempts"], 1)
        self.assertEqual(metadata["description"], "updated")

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
        attempted = self.repo.record_ocr_attempt(
            first["id"], "no_consensus", {
                "evidence_image": "ocr-evidence/first-no-consensus.png",
                "processing_reason": "timer_not_frozen_or_not_readable",
            }
        )
        self.assertIn("first-no-consensus.png", attempted["raw_metadata"])
        self.assertIn("timer_not_frozen_or_not_readable", attempted["raw_metadata"])
        self.assertEqual(self.repo.time_required(1)[0]["id"], second["id"])
        updated = self.repo.set_ocr_time(first["id"], 92_000, 0.82,
                                         {"engine": "tesseract", "matching_frames": 3})
        self.assertEqual(updated["status"], "ready_for_review")
        self.assertEqual(updated["time_ms"], 92_000)
        self.assertIn('"ocr"', updated["raw_metadata"])

    def test_ocr_candidates_include_unresolved_rows_and_skip_no_consensus(self):
        ordinary, _ = self.repo.add("ordinary", "https://youtu.be/ordinary",
                                    parse_title("Ronan Void Invasion 3F"))
        incomplete, _ = self.repo.add("incomplete", "https://youtu.be/incomplete",
                                      parse_title("Ronan Grand Chase Classic"))
        retriable, _ = self.repo.add("retriable", "https://youtu.be/retriable",
                                     parse_title("Arme Void Invasion 3F"))
        finished, _ = self.repo.add("finished", "https://youtu.be/finished",
                                    parse_title("Lire Void Invasion 3F"))
        self.repo.record_ocr_attempt(retriable["id"], "error")
        self.repo.record_ocr_attempt(finished["id"], "no_consensus")

        normal_ids = {row["video_id"] for row in self.repo.ocr_candidates(0)}
        all_ids = {row["video_id"] for row in self.repo.ocr_candidates(0, True)}
        self.assertEqual(normal_ids, {ordinary["video_id"], retriable["video_id"]})
        self.assertEqual(all_ids, {ordinary["video_id"], incomplete["video_id"],
                                  retriable["video_id"]})
        self.assertEqual(self.repo.ocr_remaining(True), 3)

    def test_automatic_relevance_rejection_only_changes_pending_rows(self):
        guide, _ = self.repo.add(
            "guide-video", "https://youtu.be/guide-video",
            parse_title("Ereb Void Invasion 3F Skill Tree Guide")
        )
        approved, _ = self.repo.add(
            "approved-video", "https://youtu.be/approved-video",
            parse_title("Ronan Void Invasion 3F 01:00")
        )
        self.repo.decide(approved["id"], True)

        rejected = self.repo.reject_candidates(
            [guide["id"], approved["id"]], "automatic_relevance_filter"
        )

        self.assertEqual([row["id"] for row in rejected], [guide["id"]])
        self.assertEqual(self.repo.get(guide["id"])["status"], "rejected")
        self.assertEqual(self.repo.get(approved["id"])["status"], "approved")

    def test_targeted_ocr_can_retry_no_consensus_for_selected_characters(self):
        ai, _ = self.repo.add("ai-run", "https://youtu.be/ai-run",
                              parse_title("Ai Void Invasion 3F Solo"))
        amy, _ = self.repo.add("amy-run", "https://youtu.be/amy-run",
                               parse_title("Amy Void Invasion 3F Solo"))
        self.repo.record_ocr_attempt(ai["id"], "no_consensus")
        self.repo.record_ocr_attempt(amy["id"], "no_consensus")

        default_ids = {row["video_id"] for row in self.repo.ocr_candidates(0)}
        targeted_ids = {row["video_id"] for row in self.repo.ocr_candidates(
            0, retry_no_consensus=True, characters=["Ai"]
        )}

        self.assertNotIn("ai-run", default_ids)
        self.assertEqual(targeted_ids, {"ai-run"})
        self.assertEqual(self.repo.ocr_remaining(
            retry_no_consensus=True, characters=["Ai"]
        ), 1)

    def test_targeted_ocr_can_select_exact_reference_videos(self):
        first, _ = self.repo.add("reference-a", "https://youtu.be/reference-a",
                                 parse_title("Ai Void Invasion 3F Solo"))
        self.repo.add("reference-b", "https://youtu.be/reference-b",
                      parse_title("Ai Void Invasion 3F Solo"))
        self.repo.record_ocr_attempt(first["id"], "no_consensus")

        selected = self.repo.ocr_candidates(
            0, retry_no_consensus=True, video_ids=["reference-a"]
        )

        self.assertEqual([row["video_id"] for row in selected], ["reference-a"])
        self.assertEqual(self.repo.ocr_remaining(
            retry_no_consensus=True, video_ids=["reference-a"]
        ), 1)

    def test_ocr_cli_forwards_targeted_video_ids(self):
        repository = None
        with patch("gc_radar.cli.CandidateRepository") as repository_factory:
            repository = repository_factory.return_value
            repository.ocr_candidates.return_value = []
            repository.ocr_remaining.return_value = 0
            with patch.object(sys, "argv", [
                "gc-radar", "--db", "test.sqlite3", "ocr-queue",
                "--limit", "0", "--video-id", "video-a",
            ]), contextlib.redirect_stdout(io.StringIO()):
                cli.main()

        repository.ocr_candidates.assert_called_once_with(
            0, False, False, None, ["video-a"]
        )
        repository.ocr_remaining.assert_called_once_with(
            False, False, None, ["video-a"]
        )
        repository.close.assert_called_once()

    def test_ocr_cli_reports_technical_failure_details(self):
        candidate = {
            "id": 7, "video_id": "video-a", "video_url": "https://youtu.be/video-a",
            "title": "Ai Void Invasion 3F", "channel": "player",
            "player_nick": "player", "published_at": None, "character": "Ai",
            "category": "void_invasion", "floor": 3, "time_ms": None,
            "confidence": None, "status": "time_required", "era_key": "current",
            "raw_metadata": "{}",
        }
        output = io.StringIO()
        with patch("gc_radar.cli.CandidateRepository") as repository_factory, \
                patch("gc_radar.cli.read_video_time",
                      side_effect=RuntimeError("video download timed out")):
            repository = repository_factory.return_value
            repository.ocr_candidates.return_value = [candidate]
            repository.ocr_remaining.return_value = 1
            repository.queue.return_value = []
            with patch.object(sys, "argv", [
                "gc-radar", "--db", "test.sqlite3", "ocr-queue", "--limit", "1",
            ]), contextlib.redirect_stdout(output):
                cli.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["results"], [{
            "video_id": "video-a",
            "result": "error",
            "error_type": "RuntimeError",
            "error": "video download timed out",
        }])


if __name__ == "__main__":
    unittest.main()
