import unittest
from datetime import datetime
from menu_date import korean_today


class KoreanDateTests(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            ("2026-11-01T14:59:59+00:00", "2026-11-01", 6),
            ("2026-11-01T15:00:00+00:00", "2026-11-02", 0),
            ("2026-11-01T16:00:00+00:00", "2026-11-02", 0),
            ("2026-12-31T15:00:00+00:00", "2027-01-01", 4),
            ("2028-02-28T15:00:00+00:00", "2028-02-29", 1),
        ]
        for instant, expected, weekday in cases:
            with self.subTest(instant=instant):
                result = korean_today(datetime.fromisoformat(instant))
                self.assertEqual(result.isoformat(), expected)
                self.assertEqual(result.weekday(), weekday)

    def test_naive_instant_rejected(self):
        with self.assertRaises(ValueError):
            korean_today(datetime(2026, 11, 1))


class CrawlerIntegrationTests(unittest.TestCase):
    def test_crawler_uses_same_korean_day_for_weekday_and_dorm(self):
        from unittest.mock import patch, Mock
        from datetime import date
        import importlib
        import menu_date
        with patch.object(menu_date, "korean_today", return_value=date(2026, 11, 2)):
            import crawler
            importlib.reload(crawler)
        self.assertEqual(crawler.TODAY, "2026-11-02")
        self.assertEqual(crawler.WEEKDAY, "월")
        self.assertEqual(crawler.extract_today_menu("[일]old\n[월]correct"), ["correct"])
        with patch.object(crawler.requests, "get", return_value=Mock(text="<html></html>")) as get:
            crawler.fetch_dorm(1)
            self.assertEqual(get.call_args.kwargs["params"]["date"], "2026-11-02")


if __name__ == "__main__":
    unittest.main()
