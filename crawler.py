import requests
from bs4 import BeautifulSoup
from datetime import date
import json
import re

TODAY = date.today().strftime("%Y-%m-%d")
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"][date.today().weekday()]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.skku.edu/skku/campus/support/welfare_11.do",
}

RESTAURANTS = [
    {"name": "행단골", "conspaceCd": "20201104", "srResId": "3"},
    {"name": "해오름",  "conspaceCd": "20201251", "srResId": "12"},
    {"name": "구시재",  "conspaceCd": "20201040", "srResId": "11"},
    {"name": "THE S LOUNGE", "conspaceCd": "20201289", "srResId": "17"},
]

HAENGDAN_STALLS = ["가츠엔", "싱푸차이나", "봄이온소반", "나폴리폴리"]


def fetch_restaurant(conspaceCd, srResId, category):
    url = "https://www.skku.edu/skku/campus/support/welfare_11_1.do"
    params = {
        "mode": "info",
        "conspaceCd": conspaceCd,
        "srResId": srResId,
        "srShowTime": "W",
        "srCategory": category,
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
    return BeautifulSoup(resp.text, "html.parser")


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

    stall_names = ["가츠엔", "싱푸차이나", "봄이온소반", "나폴리폴리"]
    for i, name in enumerate(stall_names):
        if i < len(unique_pres):
            menu_lines = extract_today_menu(unique_pres[i])
            stalls.append({"name": name, "menu": menu_lines})
        else:
            stalls.append({"name": name, "menu": []})

    return stalls


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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://dorm.skku.edu/dorm_suwon/lifeguide/dorm_restaurant_table.jsp",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    div = soup.find("div", id=f"foodlist0{category_id}")
    if not div:
        return {}

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


def build_menu():
    menu = {"date": TODAY, "weekday": WEEKDAY, "restaurants": {}, "dorm": {}}

    print(f"크롤링 시작: {TODAY} ({WEEKDAY}요일)")

    for r in RESTAURANTS:
        name = r["name"]
        print(f"  {name} 크롤링 중...")

        if name == "행단골":
            soup_l = fetch_restaurant(r["conspaceCd"], r["srResId"], "L")
            soup_b = fetch_restaurant(r["conspaceCd"], r["srResId"], "B")
            menu["restaurants"][name] = {
                "type": "haengdan",
                "breakfast": parse_simple(soup_b),
                "lunch": parse_haengdan(soup_l),
            }
        else:
            soup_b = fetch_restaurant(r["conspaceCd"], r["srResId"], "B")
            soup_l = fetch_restaurant(r["conspaceCd"], r["srResId"], "L")
            soup_d = fetch_restaurant(r["conspaceCd"], r["srResId"], "D")
            menu["restaurants"][name] = {
                "type": "simple",
                "breakfast": parse_simple(soup_b),
                "lunch": parse_simple(soup_l),
                "dinner": parse_simple(soup_d),
            }

    print("  기숙사 크롤링 중...")
    menu["dorm"] = {
        "breakfast": fetch_dorm(1),
        "lunch": fetch_dorm(2),
        "dinner": fetch_dorm(3),
    }

    return menu


if __name__ == "__main__":
    menu = build_menu()
    with open("menu.json", "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)
    print(f"\n✅ menu.json 저장 완료!")
    print(json.dumps(menu, ensure_ascii=False, indent=2)[:1000])
