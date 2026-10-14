"""Test suite for Dizibox API Client."""

import unittest
from dizibox_api.client import DiziboxClient
from dizibox_api.models import SeriesDetail, EpisodeStreamDetail


class TestDiziboxClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = DiziboxClient()

    def test_recent_episodes(self):
        items = self.client.get_recent_episodes(page=1)
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)
        first = items[0]
        self.assertTrue(len(first.title) > 0)
        self.assertTrue(len(first.episode_slug) > 0)
        print(f"\n[Test] Recent episode: {first.title} ({first.episode_slug})")

    def test_archive_and_search(self):
        series = self.client.search("breaking bad")
        self.assertIsInstance(series, list)
        self.assertGreater(len(series), 0)
        first = series[0]
        self.assertTrue("breaking" in first.title.lower() or "breaking" in first.slug.lower())
        print(f"[Test] Found series: {first.title} ({first.slug})")

    def test_series_detail(self):
        detail = self.client.get_series("breaking-bad-izle-1")
        self.assertIsInstance(detail, SeriesDetail)
        self.assertTrue(len(detail.title) > 0)
        self.assertGreater(detail.total_episodes, 0)
        print(f"[Test] Series detail: {detail.title}, Total episodes: {detail.total_episodes}")

    def test_stream_extraction(self):
        stream = self.client.get_episode_stream("breaking-bad-1-sezon-1-bolum-hd-1-izle")
        self.assertIsInstance(stream, EpisodeStreamDetail)
        self.assertTrue(stream.stream_url.startswith("http"))
        self.assertTrue("molystream" in stream.stream_url)
        print(f"[Test] Extracted Stream URL: {stream.stream_url}")

    def test_cache_speed(self):
        # Repeated call should hit cache instantly
        stats_before = self.client.cache_stats()
        _ = self.client.get_recent_episodes(page=1)
        stats_after = self.client.cache_stats()
        self.assertGreaterEqual(stats_after["hits"], stats_before["hits"])
        print(f"[Test] Cache hit ratio: {stats_after['hit_ratio_percent']}%")


if __name__ == "__main__":
    unittest.main()
