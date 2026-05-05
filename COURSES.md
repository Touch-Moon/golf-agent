# Golf Course Booking URLs & Scraping Strategy

마니토바 위니펙 인근 골프 코스 — 예약 페이지 URL과 스크래핑 방식.
URL이 바뀌면 이 파일과 [config.py](config.py)를 같이 업데이트.

부킹 시스템별로 그룹핑 — 같은 시스템은 같은 스크래퍼([scrapers/](scrapers/))로 처리.

---

## 1. Tee-On (`tee_on`)

`tee-on.com/PubGolf/...` 도메인. JSP 기반. ComboLanding → "Public Enter Here" 클릭으로 진입.
랜딩 후 두 가지 인터페이스로 분기:
- **WebBookingSearchSteps** — 폼 입력(date/time/holes/players) → 결과 페이지 반복 검색
- **WebBookingAllTimesLanding** — 날짜 탭 + 홀 필터 그리드 (Lorette 등)

스크래퍼: [scrapers/tee_on.py](scrapers/tee_on.py)

| 코스 | 예약 URL | 인터페이스 |
|---|---|---|
| River Oaks Golf Course | https://www.tee-on.com/PubGolf/servlet/com.teeon.teesheet.servlets.golfersection.ComboLanding?CourseCode=RIOA&FromCourseWebsite=true | SearchSteps |
| Lorette Golf Course | https://www.tee-on.com/PubGolf/servlet/com.teeon.teesheet.servlets.golfersection.ComboLanding?CourseCode=LORE&FromCourseWebsite=true | AllTimesLanding |
| Larters at St. Andrews | https://www.tee-on.com/PubGolf/servlet/com.teeon.teesheet.servlets.golfersection.ComboLanding?CourseCode=LART&FromCourseWebsite=true | SearchSteps |
| Southside Golf Course | https://www.tee-on.com/PubGolf/servlet/com.teeon.teesheet.servlets.golfersection.ComboLanding?CourseCode=STHS&FromCourseWebsite=true | SearchSteps |
| Windsor Park Golf Course | https://www.tee-on.com/PubGolf/servlet/com.teeon.teesheet.servlets.golfersection.WebBookingSearchSteps?FromTrailSearch=true&CourseCode=WIPA&CourseGroupID=11354 | SearchSteps (직접) |

**스크래핑 규칙:**
- ComboLanding URL이면 페이지 내 `a:has-text('Public Enter Here')` 클릭
- 클릭 후 URL이 `WebBookingAllTimesLanding`이면 → `_scrape_all_times_landing()` 분기:
  - 날짜 탭 클릭 (`a[href*="changeDate('YYYY-MM-DD')"]`)
  - 홀 필터 'All' 클릭 (텍스트 정확 일치)
  - body 텍스트에서 시간 파싱
- 그 외(SearchSteps)는 폼 입력 + 반복 검색:
  - `select#Date` = target_date
  - `select#SearchTime` = 가장 이른 시간부터
  - `#toggle-18` + `#toggle-4` 체크
  - `#form` submit
  - 결과에서 `\d{1,2}:\d{2}\s*[AaPp][Mm]` + `$XX.XX` 추출
  - 마지막 슬롯 +8분으로 다시 검색 (Tee-On은 한 번에 2개만 반환)

---

## 2. Tee It Up (`teeitup`)

`<course-slug>.book.teeitup.com` 도메인. React SPA. JSON API로 슬롯 로드.

⚠️ **Bare URL은 빈 페이지** — `?holes=18&golfers=4&max=999999` 쿼리 없으면 SPA가 필터링되지 않은 상태로 머물고 슬롯 데이터를 fetch하지 않음.

스크래퍼: [scrapers/teeitup.py](scrapers/teeitup.py)

| 코스 | 예약 URL (사용자 검증) |
|---|---|
| Kingswood Golf & Country Club | https://kingswood-golf-country-club.book.teeitup.com/?course=15876&date=2026-05-09&golfers=4&holes=18&max=999999 |
| Maplewood Golf Club | https://maplewood-golf-club.book.teeitup.com/?course=15888&date=2026-05-09&golfers=4&holes=18&max=999999 |
| John Blumberg Golf Course | https://john-blumberg-golf-course.book.teeitup.com/?course=17374&date=2026-05-09&golfers=4&holes=18&max=999999 |
| Assiniboine Golf Club | https://assiniboine-golf-club.book.teeitup.com/?course=15887&date=2026-05-09&golfers=4&holes=18&max=999999 |
| Whispering Winds of Warren | https://whispering-winds-of-warren-golf-and-country-club.book.teeitup.com/?course=&date=2026-05-09&golfers=4&holes=18&max=999999 |

**스크래핑 규칙:**
- URL: `{booking_url}?date={target_date}&golfers=4&holes=18&max=999999`
- `page.goto()` + `networkidle` 대기
- `response` 이벤트로 JSON 응답 캡처 (URL에 `tee/slot/time/booking/avail` 포함)
- JSON 우선: `teeTimes[]` / `slots[]` / `times[]` 안의 `time` + `price`
- DOM 폴백: `[class*='tee-time']`, `[class*='time-slot']`, `[class*='slot']`
- body 텍스트 폴백 (마지막 수단)

---

## 3. CPS Golf (`cps_golf`)

`<course>.cps.golf` 도메인. Angular SPA. **URL의 Date= 파라미터 무시** — 캘린더 클릭 필수.

스크래퍼: [scrapers/cps_golf.py](scrapers/cps_golf.py)

| 코스 | 예약 URL |
|---|---|
| Bridges Golf Course | https://bridgesgccan.cps.golf/onlineresweb/search-teetime?TeeOffTimeMin=0&TeeOffTimeMax=23.999722222222225 |
| Bel Acres Golf and Country Club | https://belacres.cps.golf/ |

**스크래핑 규칙:**
- `page.goto(booking_url)` (Date 파라미터 추가 금지 — Angular가 무시함)
- `response` 이벤트로 `/onlineresapi/.../TeeTimes?searchDate=...` JSON 캡처
- 캘린더에서 target_date 클릭 (`span.day-background-upper.is-visible:not(.is-disabled)`)
  - 표시 달이 다르면 `button.mat-raised-button` 중 `>` 텍스트 가진 것 클릭으로 다음 달
  - 최대 3회 이동
- 클릭 후 새 API 응답 대기 (~20초)
- 마지막 캡처(`captured[-1]`)에서 `content[].startTime` + `shItemPrices[0].displayPrice` 추출

---

## 4. Clubhouse Online e3 (`clubhouse_online`)

`<club>.clubhouseonline-e3.net/PublicTeeTimes/TeeSheet[.aspx]` 도메인. ASP.NET WebForms.
멤버 전용 클럽이지만 "PUBLIC TEE TIMES" 페이지를 노출 — 비회원 접근 가능.

스크래퍼: [scrapers/clubhouse_online.py](scrapers/clubhouse_online.py)

| 코스 | 예약 URL |
|---|---|
| Rossmere Country Club | https://rossmeregc.clubhouseonline-e3.net/PublicTeeTimes/TeeSheet.aspx |
| St. Boniface Golf Club | https://stbonifacegolfclub.clubhouseonline-e3.net/PublicTeeTimes/TeeSheet |

**스크래핑 규칙:**
- URL에 `?date=YYYY-MM-DD` 추가 후 `page.goto()`
- DOM 셀렉터 시도 (순서대로):
  - `.teeTimeItem`, `.tee-time-item`
  - `tr.teetime`, `tr[id*='teetime']`
  - `.TeeTimeAvailable`, `[class*='TeeTime']`
  - `table#teeSheet tr`, `.teesheet-row`
- 각 row에서 시간 + `$XX.XX` 가격 + 예약 버튼 존재 확인
- 셀렉터 모두 매치 안되면 body 텍스트 폴백

⚠️ **현재 미해결**: 위 셀렉터가 실제 DOM과 일치 안 함 — 두 코스 모두 0 슬롯. 실제 DOM 검증 필요.

---

## 5. Tee-On Portal (`teeon_portal`)

Tee-On의 신형 portal 인터페이스 (`admin.teeon.com/portal/...`).

스크래퍼: [scrapers/teeon_portal.py](scrapers/teeon_portal.py)

| 코스 | 예약 URL |
|---|---|
| Oakwood Golf Course | https://admin.teeon.com/portal/oakwoodgc/teetimes/oakwoodgc |

---

## 6. Prophet Services (`prophetservices`)

`secure.east.prophetservices.com` 도메인.

스크래퍼: [scrapers/prophetservices.py](scrapers/prophetservices.py)

| 코스 | 예약 URL |
|---|---|
| Quarry Oaks Golf Course | https://secure.east.prophetservices.com/LinksatQuarryOaksV3 |

---

## 시스템 마이그레이션 이력

골프장이 부킹 시스템을 바꾸면 config.py에서 `system` 필드와 `booking_url` 모두 업데이트해야 함.

| 코스 | 이전 시스템 | 현재 시스템 | 변경일 |
|---|---|---|---|
| Assiniboine Golf Club | GolfNow | TeeItUp | 2026-05-05 (감지) |
| Bel Acres Golf and Country Club | GolfNow | CPS Golf | 2026-05-05 (감지) |
| Whispering Winds of Warren | GolfNow | TeeItUp | 2026-05-05 (감지) |

마이그레이션 감지 방법:
1. 골프장 홈페이지 → "Book Tee Time" 링크 따라가기
2. 리다이렉트되는 도메인으로 시스템 식별:
   - `*.book.teeitup.com` → teeitup
   - `*.cps.golf` → cps_golf
   - `*.clubhouseonline-e3.net` → clubhouse_online
   - `tee-on.com/PubGolf/...` → tee_on
   - `admin.teeon.com/portal/...` → teeon_portal
   - `secure.east.prophetservices.com` → prophetservices
