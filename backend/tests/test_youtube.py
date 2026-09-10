import io
import json
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from gc_radar.youtube import DEFAULT_SEARCH_QUERIES, discover_videos, fill_ranking_queries, search_videos


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class YouTubeSearchTests(unittest.TestCase):
    def test_search_builds_bounded_public_video_query(self):
        requested = {}

        def opener(url, timeout):
            requested.update(parse_qs(urlparse(url).query))
            payload = {"items": [{
                "id": {"videoId": "WZeUJAw4pmU"},
                "snippet": {"title": "Ereb Vazio Invasão 3F 1:32",
                            "channelTitle": "Borkaz", "publishedAt": "2026-09-08T10:00:00Z"},
            }]}
            return FakeResponse(json.dumps(payload).encode())

        result = search_videos(
            "Grand Chase Classic", api_key="test-key", days=3, max_results=25,
            opener=opener, now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        self.assertEqual(requested["type"], ["video"])
        self.assertEqual(requested["order"], ["date"])
        self.assertEqual(requested["maxResults"], ["25"])
        self.assertEqual(requested["publishedAfter"], ["2026-09-05T00:00:00Z"])
        self.assertEqual(result["videos"][0]["video_id"], "WZeUJAw4pmU")

    def test_discovery_deduplicates_results_from_multiple_queries(self):
        def opener(url, timeout):
            query = parse_qs(urlparse(url).query)["q"][0]
            payload = {"items": [{
                "id": {"videoId": "aTglQvuekIE"},
                "snippet": {"title": "Lupus Void Apocalypse 3F",
                            "channelTitle": query, "publishedAt": "2026-09-08T10:00:00Z"},
            }]}
            return FakeResponse(json.dumps(payload).encode())

        videos = discover_videos(["query one", "query two"], api_key="test-key", opener=opener)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["video_id"], "aTglQvuekIE")

    def test_fill_ranking_covers_all_characters_in_both_locales(self):
        queries = fill_ranking_queries()
        self.assertEqual(len(queries), 50)
        self.assertEqual(len(set(queries)), 50)
        self.assertIn("Grand Chase Classic Lupus Vazio Invasão 3F", queries)
        self.assertIn("Grand Chase Classic Rufus Void Invasion 3F", queries)
        self.assertIn("Grand Chase Classic Uno Void Invasion 3F", queries)

    def test_recent_search_includes_korean_and_thai_queries(self):
        self.assertIn("그랜드체이스 클래식 공허 침공", DEFAULT_SEARCH_QUERIES)
        self.assertIn("แกรนด์เชส คลาสสิก วอยด์ อินเวชัน", DEFAULT_SEARCH_QUERIES)

    def test_recent_search_includes_non_void_dungeons(self):
        self.assertIn("Grand Chase Classic Duel 4", DEFAULT_SEARCH_QUERIES)
        self.assertIn("Grand Chase Classic Tower of Disappearance", DEFAULT_SEARCH_QUERIES)
        self.assertIn("Grand Chase Classic LoJ Unlimited", DEFAULT_SEARCH_QUERIES)


if __name__ == "__main__":
    unittest.main()
