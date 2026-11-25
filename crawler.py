import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from menu_date import korean_today

MENU_DAY = korean_today()
TODAY = MENU_DAY.isoformat()
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"][MENU_DAY.weekday()]

MENU_PATH = "menu.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.skku.edu/skku/campus/support/welfare_11.do",
}

DORM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://dorm.skku.edu/dorm_suwon/lifeguide/dorm_restaurant_table.jsp",
}

RESTAURANTS = [
    {"name": "행단골", "conspaceCd": "20201104", "srResId": "3"},
    {"name": "해오름",  "conspaceCd": "20201251", "srResId": "12"},
    {"name": "구시재",  "conspaceCd": "20201040", "srResId": "11"},
    {"name": "THE S LOUNGE", "conspaceCd": "20201289", "srResId": "17"},
]

HAENGDAN_STALLS = ["가츠엔", "싱푸차이나", "봄이온소반", "나폴리폴리"]

MEAL_LABELS = {"breakfast": "조식", "lunch": "중식", "dinner": "석식"}

# 한 건의 요청이 늦거나 한 곳의 페이지가 죽어도 전체 업데이트가 멈추지 않게 한다.
# 값은 환경변수로 조정할 수 있고, 기본값은 기존 10초보다 넉넉한 25초 × 3회 재시도다.
def _env_number(name, default, cast=float, minimum=None):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        print(f"환경변수 {name}={raw!r} 값을 무시하고 기본값 {default}을 사용합니다.")
        return default
    if minimum is not None and value < minimum:
        return default
    return value


REQUEST_TIMEOUT = _env_number("CRAWL_TIMEOUT", 25.0, float, minimum=1)
REQUEST_ATTEMPTS = int(_env_number("CRAWL_ATTEMPTS", 3, int, minimum=1))
RETRY_BACKOFF = _env_number("CRAWL_BACKOFF", 2.0, float, minimum=0)

# build_menu가 채우는 실행 결과. 실패한 단위는 빈 값(또는 같은 날짜의 기존 값)으로 대체된다.
OK_UNITS = []
FAILED_UNITS = []


class CrawlError(RuntimeError):
    """재시도 후에도 페이지를 가져오지 못했을 때."""


def fetch_html(url, params, headers, what, require=None):
    """GET 한 번을 재시도/백오프와 함께 수행하고 응답 본문을 돌려준다."""
    last_error = None
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            text = resp.text
            if require is not None and not require(text):
                raise CrawlError(f"{what}: 응답에 예상한 내용이 없습니다(빈 페이지/차단 페이지)")
            return text
        except Exception as exc:  # 네트워크 오류·타임아웃·잘못된 응답 모두 재시도 대상
            last_error = exc
            if attempt < REQUEST_ATTEMPTS:
                wait = RETRY_BACKOFF * attempt
                print(
                    f"    ↻ {what} 실패({attempt}/{REQUEST_ATTEMPTS}): "
                    f"{type(exc).__name__}: {exc} → {wait:.1f}초 후 재시도"
                )
                time.sleep(wait)
    raise CrawlError(f"{what} 실패: {type(last_error).__name__}: {last_error}") from last_error


def load_unit(label, fetch_fn, fallback):
    """한 식단 단위를 가져오고, 끝내 실패하면 fallback으로 대체해 나머지를 계속 진행한다."""
    try:
        value = fetch_fn()
    except Exception as exc:
        FAILED_UNITS.append(label)
        if fallback:
            print(f"  ✗ {label}: {type(exc).__name__}: {exc} → 같은 날짜의 기존 값 유지")
        else:
            print(f"  ✗ {label}: {type(exc).__name__}: {exc} → 빈 값으로 대체")
        return fallback
    OK_UNITS.append(label)
    print(f"  ✓ {label}")
    return value


def fetch_restaurant(conspaceCd, srResId, category, label=None):
    url = "https://www.skku.edu/skku/campus/support/welfare_11_1.do"
    params = {
        "mode": "info",
        "conspaceCd": conspaceCd,
        "srResId": srResId,
        "srShowTime": "W",
        "srCategory": category,
    }
    what = label or f"학생식당 {conspaceCd}/{category}"
    html = fetch_html(url, params, HEADERS, what, require=lambda body: "<pre" in body)
    return BeautifulSoup(html, "html.parser")


def parse_pre_list(soup):
    pres = []
    for pre in soup.find_all("pre"):
        text = pre.get_text(strip=True)
        if text:
            pres.append(text)
    return pres


def extract_today_menu(pre_text):
    lines = pre_text.strip().splitlines()
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        weekday_match = re.match(r"^\[(.)\](.*)$", line)
        if weekday_match:
            day, menu = weekday_match.group(1), weekday_match.group(2).strip()
            if day == WEEKDAY and menu:
                result.append(menu)
        elif not re.match(r"^\[.\]", line):
            result.append(line)
    return result


def parse_haengdan(soup):
    pres = parse_pre_list(soup)
    stalls = []
    info_pre = pres[0] if pres else ""

    stall_pres = [p for p in pres if p != info_pre]

    # 가츠엔, 싱푸차이나가 요일별로 반복 → 첫 등장만 사용
    seen = set()
    unique_pres = []
    for p in stall_pres:
        key = p[:20]
        if key not in seen:
            seen.add(key)
            unique_pres.append(p)

    for i, name in enumerate(HAENGDAN_STALLS):
        if i < len(unique_pres):
            menu_lines = extract_today_menu(unique_pres[i])
            stalls.append({"name": name, "menu": menu_lines})
        else:
            stalls.append({"name": name, "menu": []})

    return stalls


def empty_haengdan_stalls():
    return [{"name": name, "menu": []} for name in HAENGDAN_STALLS]


def parse_simple(soup):
    pres = parse_pre_list(soup)
    for pre in pres:
        if "미운영" in pre or len(pre) < 5:
            continue
        if any(x in pre[:30] for x in ["○", "※", "♥", "운영", "Tel", "주말"]):
            continue
        lines = [l.strip() for l in pre.splitlines() if l.strip()]
        return lines
    return []


def fetch_dorm(category_id):
    url = f"https://dorm.skku.edu/_custom/skku/_common/board/schedule_menu/food_menu_page.jsp"
    params = {"date": TODAY, "board_no": "61", "lng": "ko"}
    what = f"기숙사 식단 {category_id}"
    html = fetch_html(url, params, DORM_HEADERS, what, require=lambda body: "foodlist0" in body)
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", id=f"foodlist0{category_id}")
    if not div:
        raise CrawlError(f"{what}: foodlist0{category_id} 영역을 찾지 못했습니다")

    result = {}
    current_name = None
    current_menu = []

    for li in div.find_all("li"):
        span = li.find("span", class_=lambda c: c and "board-menu-title" in c)
        p = li.find("p")
        if span:
            if current_name:
                result[current_name] = current_menu
            current_name = span.get_text(strip=True)
            current_menu = []
        if p and current_name:
            text = p.get_text(strip=True)
            # 시간 제거 (앞부분 HH:MM~HH:MM, 또는 *가격* 제거)
            text = re.sub(r"^\d{2}:\d{2}~\d{2}:\d{2},?\s*", "", text)
            text = re.sub(r"\*[\d,]+\*\s*", "", text)
            items = [x.strip() for x in text.split(",") if x.strip()]
            current_menu.extend(items)

    if current_name:
        result[current_name] = current_menu

    return result


def load_previous_menu(path=MENU_PATH):
    """같은 날짜의 직전 크롤링 결과. 재실행 중 일부가 실패하면 이 값을 그대로 쓴다."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        print(f"  이전 menu.json을 읽지 못했습니다: {exc}")
        return {}
    if not isinstance(data, dict) or data.get("date") != TODAY:
        return {}
    print(f"  같은 날짜({TODAY})의 기존 menu.json을 대체 값으로 사용합니다.")
    return data


def previous_value(prev_entry, key, expected_type):
    """같은 날짜의 기존 값 중 스키마가 맞는 것만 대체 값으로 돌려준다."""
    if not isinstance(prev_entry, dict) or prev_entry.get("type") != expected_type:
        return None
    value = prev_entry.get(key)
    return value if isinstance(value, list) else None


def build_menu(previous_path=MENU_PATH):
    menu = {"date": TODAY, "weekday": WEEKDAY, "restaurants": {}, "dorm": {}}
    previous = load_previous_menu(previous_path)
    prev_restaurants = previous.get("restaurants") if isinstance(previous.get("restaurants"), dict) else {}
    prev_dorm = previous.get("dorm") if isinstance(previous.get("dorm"), dict) else {}

    print(f"크롤링 시작: {TODAY} ({WEEKDAY}요일)")

    for r in RESTAURANTS:
        name = r["name"]
        prev_entry = prev_restaurants.get(name)

        if name == "행단골":
            breakfast = load_unit(
                f"{name} 조식",
                lambda r=r: parse_simple(fetch_restaurant(r["conspaceCd"], r["srResId"], "B", f"{r['name']} 조식")),
                previous_value(prev_entry, "breakfast", "haengdan") or [],
            )
            lunch = load_unit(
                f"{name} 중식",
                lambda r=r: parse_haengdan(fetch_restaurant(r["conspaceCd"], r["srResId"], "L", f"{r['name']} 중식")),
                previous_value(prev_entry, "lunch", "haengdan") or empty_haengdan_stalls(),
            )
            menu["restaurants"][name] = {
                "type": "haengdan",
                "breakfast": breakfast,
                "lunch": lunch,
            }
        else:
            entry = {"type": "simple"}
            for meal, category in (("breakfast", "B"), ("lunch", "L"), ("dinner", "D")):
                entry[meal] = load_unit(
                    f"{name} {MEAL_LABELS[meal]}",
                    lambda r=r, category=category, meal=meal: parse_simple(
                        fetch_restaurant(r["conspaceCd"], r["srResId"], category, f"{r['name']} {MEAL_LABELS[meal]}")
                    ),
                    previous_value(prev_entry, meal, "simple") or [],
                )
            menu["restaurants"][name] = entry

    for meal, category_id in (("breakfast", 1), ("lunch", 2), ("dinner", 3)):
        prev_meal = prev_dorm.get(meal) if isinstance(prev_dorm.get(meal), dict) else {}
        menu["dorm"][meal] = load_unit(
            f"기숙사 {MEAL_LABELS[meal]}",
            lambda category_id=category_id: fetch_dorm(category_id),
            prev_meal,
        )

    return menu


def write_menu(menu, path=MENU_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)


def run(path=MENU_PATH):
    """크롤링 후 menu.json을 갱신한다. 전부 실패하면 기존 파일을 지키고 False를 돌려준다."""
    del OK_UNITS[:]
    del FAILED_UNITS[:]
    menu = build_menu(previous_path=path)

    if not OK_UNITS:
        print("\n❌ 모든 식단을 가져오지 못했습니다. 기존 menu.json을 덮어쓰지 않고 실패로 종료합니다.")
        print("   실패: " + ", ".join(FAILED_UNITS))
        return False

    write_menu(menu, path)
    print("\n✅ menu.json 저장 완료!")
    if FAILED_UNITS:
        print("⚠ 일부 식단은 가져오지 못해 빈 값 또는 기존 값으로 남겼습니다: " + ", ".join(FAILED_UNITS))
    print(json.dumps(menu, ensure_ascii=False, indent=2)[:1000])
    return True


if __name__ == "__main__":
    if not run():
        sys.exit(1)
