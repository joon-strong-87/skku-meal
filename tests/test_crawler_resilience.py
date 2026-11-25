import json
import os
import tempfile
import unittest
from unittest import mock

import requests
from bs4 import BeautifulSoup

import crawler


SIMPLE_HTML = "<html><body><pre>[수]밥\n국\n반찬</pre></body></html>"
HAENGDAN_HTML = (
    "<html><body>"
    "<pre>운영시간 안내 Tel. 000-0000</pre>"
    "<pre>[수]가츠엔메뉴\n돈가스</pre>"
    "<pre>[수]싱푸메뉴\n자장면</pre>"
    "<pre>[수]봄이온메뉴\n라면</pre>"
    "<pre>[수]나폴리메뉴\n곰탕</pre>"
    "</body></html>"
)


def fake_response(text):
    resp = mock.Mock()
    resp.text = text
    resp.raise_for_status = lambda: None
    return resp


class RetryTests(unittest.TestCase):
    """10초 타임아웃 한 번으로 전체가 죽지 않도록 재시도/백오프가 도는지 확인."""

    def setUp(self):
        self._timeout = crawler.REQUEST_TIMEOUT
        self._attempts = crawler.REQUEST_ATTEMPTS
        self._backoff = crawler.RETRY_BACKOFF
        self.sleeps = []
        self._sleep = crawler.time.sleep
        crawler.REQUEST_TIMEOUT = 25.0
        crawler.REQUEST_ATTEMPTS = 3
        crawler.RETRY_BACKOFF = 2.0
        crawler.time.sleep = self.sleeps.append

    def tearDown(self):
        crawler.time.sleep = self._sleep
        crawler.REQUEST_TIMEOUT = self._timeout
        crawler.REQUEST_ATTEMPTS = self._attempts
        crawler.RETRY_BACKOFF = self._backoff

    def test_timed_out_request_is_retried_then_succeeds(self):
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(timeout)
            if len(calls) < 3:
                raise requests.exceptions.ReadTimeout("read timed out")
            return fake_response('<html><div id="foodlist01"></div></html>')

        with mock.patch.object(crawler.requests, "get", side_effect=fake_get):
            self.assertEqual(crawler.fetch_dorm(1), {})

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], 25.0)  # 기존 10초보다 넉넉한 타임아웃
        self.assertEqual(self.sleeps, [2.0, 4.0])  # 백오프

    def test_persistent_failure_raises_crawl_error(self):
        def fake_get(url, params=None, headers=None, timeout=None):
            raise requests.exceptions.ReadTimeout("read timed out")

        with mock.patch.object(crawler.requests, "get", side_effect=fake_get) as get:
            with self.assertRaises(crawler.CrawlError):
                crawler.fetch_dorm(2)
        self.assertEqual(get.call_count, 3)

    def test_empty_or_blocked_page_is_retried(self):
        # 200이지만 내용이 없는 응답은 데이터를 지우지 않도록 실패로 본다.
        with mock.patch.object(crawler.requests, "get", return_value=fake_response("<html></html>")) as get:
            with self.assertRaises(crawler.CrawlError):
                crawler.fetch_restaurant("20201251", "12", "L", "해오름 중식")
        self.assertEqual(get.call_count, 3)


class SectionFallbackTests(unittest.TestCase):
    """한 곳이 끝내 실패해도 나머지는 갱신되고 스키마는 그대로인지 확인."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "menu.json")
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

        self._sleep = crawler.time.sleep
        crawler.time.sleep = lambda seconds: None
        self.addCleanup(setattr, crawler.time, "sleep", self._sleep)

        patcher = mock.patch.object(crawler, "fetch_restaurant", side_effect=self._fetch_restaurant)
        self.fetch_restaurant = patcher.start()
        self.addCleanup(patcher.stop)
        self.dorm_failures = True
        dorm_patcher = mock.patch.object(crawler, "fetch_dorm", side_effect=self._fetch_dorm)
        self.fetch_dorm = dorm_patcher.start()
        self.addCleanup(dorm_patcher.stop)

    @staticmethod
    def _fetch_restaurant(conspaceCd, srResId, category, label=None):
        if conspaceCd == "20201104" and category == "L":
            return BeautifulSoup(HAENGDAN_HTML, "html.parser")
        return BeautifulSoup(SIMPLE_HTML, "html.parser")

    def _fetch_dorm(self, category_id):
        if self.dorm_failures:
            raise crawler.CrawlError("기숙사 식단 실패: ReadTimeout")
        return {"공통": ["테스트메뉴"]}

    def _write_previous(self, date, dorm_lunch):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date": date,
                    "weekday": "화",
                    "restaurants": {},
                    "dorm": {"breakfast": {}, "lunch": dorm_lunch, "dinner": {}},
                },
                f,
                ensure_ascii=False,
            )

    def _schema_shape(self, menu):
        self.assertEqual(set(menu), {"date", "weekday", "restaurants", "dorm"})
        self.assertEqual(set(menu["restaurants"]), {"행단골", "해오름", "구시재", "THE S LOUNGE"})
        self.assertEqual(set(menu["dorm"]), {"breakfast", "lunch", "dinner"})
        self.assertEqual(set(menu["restaurants"]["행단골"]), {"type", "breakfast", "lunch"})
        self.assertEqual(
            set(menu["restaurants"]["해오름"]), {"type", "breakfast", "lunch", "dinner"}
        )
        self.assertEqual(menu["restaurants"]["행단골"]["type"], "haengdan")
        self.assertEqual(menu["restaurants"]["해오름"]["type"], "simple")
        stalls = menu["restaurants"]["행단골"]["lunch"]
        self.assertEqual([s["name"] for s in stalls], crawler.HAENGDAN_STALLS)
        for stall in stalls:
            self.assertIsInstance(stall["menu"], list)
        self.assertIsInstance(menu["dorm"]["lunch"], dict)

    def test_dorm_failure_keeps_other_restaurants_and_returns_success(self):
        self.assertTrue(crawler.run(self.path))
        with open(self.path, encoding="utf-8") as f:
            menu = json.load(f)

        self._schema_shape(menu)
        self.assertEqual(menu["restaurants"]["해오름"]["lunch"], ["[수]밥", "국", "반찬"])
        self.assertEqual(menu["restaurants"]["행단골"]["lunch"][0]["menu"], ["가츠엔메뉴", "돈가스"])
        self.assertEqual(menu["dorm"]["breakfast"], {})
        self.assertEqual(menu["dorm"]["lunch"], {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "unexpected")))
        self.assertTrue(all(label.startswith("기숙사") for label in crawler.FAILED_UNITS))
        self.assertEqual(len(crawler.FAILED_UNITS), 3)
        self.assertEqual(len(crawler.OK_UNITS), 11)

    def test_dorm_failure_reuses_same_day_previous_data(self):
        self._write_previous(crawler.TODAY, {"신관": ["어제아닌오늘메뉴"], "공통": ["공통메뉴"]})
        self.assertTrue(crawler.run(self.path))
        with open(self.path, encoding="utf-8") as f:
            menu = json.load(f)
        self.assertEqual(menu["dorm"]["lunch"], {"신관": ["어제아닌오늘메뉴"], "공통": ["공통메뉴"]})
        self.assertIsInstance(menu["dorm"]["breakfast"], dict)

    def test_stale_previous_day_data_is_not_reused(self):
        self._write_previous("2000-01-01", {"신관": ["이전날짜메뉴"]})
        self.assertTrue(crawler.run(self.path))
        with open(self.path, encoding="utf-8") as f:
            menu = json.load(f)
        self.assertEqual(menu["dorm"]["lunch"], {})

    def test_everything_failing_keeps_existing_file_and_fails(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"date": "2000-01-01", "sentinel": true}')
        with mock.patch.object(crawler, "fetch_restaurant", side_effect=crawler.CrawlError("차단")), \
             mock.patch.object(crawler, "fetch_dorm", side_effect=crawler.CrawlError("차단")):
            self.assertFalse(crawler.run(self.path))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"date": "2000-01-01", "sentinel": True})


if __name__ == "__main__":
    unittest.main()
