# 성균관대 자과캠 오늘의 학식

성균관대학교 자연과학캠퍼스 학식 메뉴를 매일 자동으로 크롤링해서 보여주는 사이트입니다.

## 식당 구성

**학생 식당**
- 행단골 (가츠엔 / 싱푸차이나 / 봄이온소반 / 나폴리폴리)
- 해오름
- 구시재
- THE S LOUNGE

**기숙사 식당 (봉룡학사)**
- 신관 / 지관

## 업데이트
매일 새벽 1시 (KST) GitHub Actions가 자동으로 크롤링 후 menu.json을 업데이트합니다.

## 로컬 실행

```bash
pip install requests beautifulsoup4
python crawler.py
```

## 실패 대비

한 사이트가 응답하지 않아도 전체 업데이트가 멈추지 않습니다. 요청은 기본 25초 타임아웃으로 3회까지 재시도(백오프 2초, 4초)하고, 그래도 실패한 식단은 같은 날짜의 기존 `menu.json` 값이 있으면 그대로 쓰고 없으면 빈 값으로 두어 나머지 식당 갱신과 배포는 정상 진행합니다. 모든 식단이 실패하면 기존 `menu.json`을 덮어쓰지 않고 실패로 종료합니다.

타임아웃·재시도 횟수·백오프는 `CRAWL_TIMEOUT`, `CRAWL_ATTEMPTS`, `CRAWL_BACKOFF` 환경변수로 조정합니다.

## 배포
GitHub Pages 사용. `index.html`이 `menu.json`을 fetch해서 렌더링합니다.


## 날짜 및 검증

메뉴 날짜와 요일은 실행 서버의 시간대와 무관하게 `Asia/Seoul` 기준입니다.
화면에는 실제 메뉴 데이터의 날짜를 표시하며, 한국시간 오늘과 다르면 경고합니다.
날짜가 없거나 잘못된 경우에도 오늘 메뉴라고 표시하지 않습니다.

회귀 테스트 (Python 의존성 설치 후, Node.js 필요):

```bash
python -m unittest discover -s tests -v
node tests/test_frontend.cjs
```
