# Golf Agent — 스크래핑 시스템 검수 & 사이트 수정 가이드

> **최종 검수**: 2026-05-05  
> **검수 기준 실행**: run_2026-05-09.json (GitHub Actions run #25408054881)  
> **결과**: failures = none, 16개 전부 스크래핑 완료

---

## 1. 스케줄 & 실행 조건

| 항목 | 내용 |
|------|------|
| **자동 실행** | 매일 Winnipeg 07:30–09:00 (CDT: UTC 12:50 cron, CST: UTC 13:50 cron 두 개 등록) |
| **Time guard** | cron은 하루 2번 트리거되지만, 실제 scraper 실행은 Winnipeg 로컬 시각이 07:30–09:00인 경우만 진행 |
| **수동 실행** | GitHub Actions → `workflow_dispatch` (time window 무시, 즉시 실행) |
| **타겟 날짜** | 다음 주 토요일 (`season.get_target_date()` 자동 계산) |
| **Job timeout** | 25분 (FlareSolverr 서비스 포함) |

```
CDT (여름, UTC-5): Winnipeg 07:50 = UTC 12:50  → cron '50 12 * * *'
CST (겨울, UTC-6): Winnipeg 07:50 = UTC 13:50  → cron '50 13 * * *'
```

### 데이터 흐름

```
GitHub Actions (ubuntu-latest)
  └─ FlareSolverr service (Docker, port 8191)   ← Bel Acres CF bypass용
  └─ Python + Playwright
       └─ 16개 코스 순차 스크래핑
       └─ logs/run_YYYY-MM-DD.json 저장
       └─ Telegram 전송
       └─ WebApp POST → /api/crawl-import (Supabase)
       └─ git push → good-morning-golf/data/latest.json
```

---

## 2. 코스별 스크래퍼 현황 (2026-05-05 검수)

### 상태 정의
| 상태 | 조건 | 표시 |
|------|------|------|
| `green` | AM(~12:00) 슬롯 있음 | 초록 |
| `afternoon` | AM 없고 PM(12:00~14:00) 또는 그 이후만 있음 | 노란색 |
| `red` | 슬롯 0개 | 빨간색 |

### 전체 코스 목록

| 코스 | 스크래퍼 | 2026-05-09 결과 | 비고 |
|------|---------|----------------|------|
| River Oaks Golf Course | `tee_on` (SearchSteps) | 30 slots / afternoon | AM 없음 |
| Lorette Golf Course | `tee_on` (AllTimesLanding) | 70 slots / green | |
| Quarry Oaks Golf Course | `prophetservices` | 27 slots / green | |
| Rossmere Country Club | `clubhouse_online` | 0 slots / red | "no public tee times" — 토요일 멤버 전용으로 추정 |
| St. Boniface Golf Club | `clubhouse_online` | 49 slots / afternoon | AM 없음 |
| Bridges Golf Course | `cps_golf` | 41 slots / green | |
| Larters at St. Andrews | `tee_on` (SearchSteps) | 19 slots / afternoon | AM 없음 |
| Kingswood Golf & Country Club | `teeitup` | 52 slots / green | |
| Maplewood Golf Club | `teeitup` | 71 slots / green | |
| John Blumberg Golf Course | `teeitup` | 81 slots / green | |
| Assiniboine Golf Club | `teeitup` | 12 slots / green | 9홀 코스 |
| Bel Acres Golf and Country Club | `cps_golf_belacres` | 31 slots / green | FlareSolverr 필요 |
| Whispering Winds of Warren | `teeitup` | 77 slots / green | |
| Southside Golf Course | `tee_on` (SearchSteps) | 72 slots / green | |
| Oakwood Golf Course | `teeon_portal` | 51 slots / green | |
| Windsor Park Golf Course | `tee_on` (SearchSteps) | 47 slots / green | |

---

## 3. 스크래퍼별 기술 규칙 요약

### `tee_on` — 5개 코스
- ComboLanding URL → "Public Enter Here" 클릭
- URL이 `WebBookingAllTimesLanding`이면 날짜 탭 + "All" 필터 클릭 (Lorette)
- URL이 `WebBookingSearchSteps`이면 폼 입력 + 반복 검색 (나머지 4개)
- Tee-On은 한 번에 2개 슬롯만 반환 → 마지막 슬롯 +8분으로 재검색 반복
- 시간 + `$XX.XX` 가격 regex로 파싱

### `teeitup` — 5개 코스
- URL: `{base}?date={YYYY-MM-DD}&golfers=4&holes=18&max=999999`
- React SPA → `networkidle` 안 떨어짐 → `domcontentloaded` + 6초 sleep
- Kenna API JSON 인터셉트: `phx-api-be-east-1b.kenna.io/v2/tee-times`
- `data[0].teetimes[i].teetime` = UTC ISO → America/Winnipeg 변환 필수
- 가격: `rates[0].promotion.greenFeeCart` 또는 `rates[0].greenFeeCart` (cents 단위)

### `cps_golf` — 1개 코스 (Bridges)
- Angular SPA → URL Date 파라미터 무시 → 캘린더 클릭으로만 날짜 변경
- `response` 이벤트로 `/onlineres/.../TeeTimes` JSON 인터셉트
- `content[].startTime` + `shItemPrices[0].displayPrice` 파싱

### `cps_golf_belacres` — 1개 코스 (Bel Acres)
- **Cloudflare Bot Fight Mode** 때문에 별도 스크래퍼
- FlareSolverr (GitHub Actions service container, port 8191) → cf_clearance 쿠키 획득
- cf_clearance를 Playwright browser context에 주입 → Angular SPA 정상 로드
- 이후 cps_golf와 동일하게 TeeTimes JSON 인터셉트

### `clubhouse_online` — 2개 코스 (Rossmere, St. Boniface)
- ASP.NET WebForms — URL `?date=` 파라미터 무시됨
- 페이지 로드 후 날짜 탭(`__doPostBack`) 클릭으로 날짜 전환
- body 텍스트에서 `HH:MM AM/PM` 패턴 파싱
- 가격 노출 안 됨 → `fallback_price` 사용

### `prophetservices` — 1개 코스 (Quarry Oaks)
- URL에 날짜/플레이어 파라미터 직접 포함
- body 텍스트 파싱

### `teeon_portal` — 1개 코스 (Oakwood)
- `admin.teeon.com/portal/...` 새 포털 인터페이스
- API 응답 인터셉트

---

## 4. latest.json 데이터 구조

**경로**: `good-morning-golf/data/latest.json` (매일 자동 push)

```json
{
  "target_date": "2026-05-09",
  "results": [
    {
      "name": "Kingswood Golf & Country Club",
      "status": "green",
      "slots": [
        {"time": "09:08", "price": 59.5, "is_hot_deal": false},
        {"time": "09:23", "price": 59.5, "is_hot_deal": false}
      ],
      "booking_url": "https://kingswood-golf-country-club.book.teeitup.com/",
      "homepage": "https://www.kingswoodgolf.ca/",
      "phone": "(204) 736-4079",
      "distance_km": 29,
      "holes": 18,
      "fallback_price": 40,
      "cart_mandatory": false
    }
  ],
  "stats": {
    "failures": "none",
    "individual_checked": 16,
    "with_slots": 12,
    "telegram": "success",
    "webapp_import": "success"
  }
}
```

### 슬롯 필드 상세

| 필드 | 타입 | 설명 |
|------|------|------|
| `time` | `"HH:MM"` | 24시간제, 항상 존재 |
| `price` | `number \| null` | 달러 단위. null이면 `fallback_price` 사용 |
| `is_hot_deal` | `boolean` | TeeItUp hot deal 여부 (대부분 false) |

### 가격이 null인 코스 (2026-05-09 기준)
`Lorette`, `Quarry Oaks`, `John Blumberg`, `St. Boniface`, `Southside`, `Oakwood` — fallback_price로 표시해야 함

---

## 5. 사이트 수정 시 주의사항

### priceRange() 로직
```typescript
// golf-agent-web/src/lib/data.ts
// AM(~12:00) → PM(~14:00) → 전체 순으로 가격 계산
// Bridges $49 오후 할인 슬롯 등 오후 가격이 왜곡하지 않도록
priceOf(slots.filter(s => s.time < "12:00"))
  ?? priceOf(slots.filter(s => s.time < "14:00"))
  ?? priceOf(slots)
```

### status 표시 기준
- `green`: `slots.some(s => s.time < "12:00")`
- `afternoon`: `slots.length > 0 && !green`
- `red`: `slots.length === 0`

### Rossmere 0슬롯
- 스크래퍼 오류 아님 — 사이트가 "no public tee times" 반환
- 토요일 공개 예약 없는 것으로 추정 (멤버 전용)
- 사이트에서 `red` 상태로 표시하는 것이 정확한 표현

### 코스 추가/변경 시
1. `config.py` → `INDIVIDUAL_COURSES`에 추가 (`system`, `booking_url` 필드 필수)
2. `system`이 새로운 플랫폼이면 `scrapers/<system>.py` 생성 + `scrapers/__init__.py` 등록
3. `COURSES.md` 업데이트

### 부킹 시스템 마이그레이션 감지
골프장이 예약 시스템을 바꾸면:
- 도메인으로 시스템 식별: `*.book.teeitup.com` / `*.cps.golf` / `*.clubhouseonline-e3.net` / `tee-on.com` / `admin.teeon.com/portal`
- `config.py`의 `system` + `booking_url` 모두 변경
- `COURSES.md` 마이그레이션 이력 섹션 추가

---

## 6. 알려진 잔여 이슈

| 이슈 | 원인 | 상태 |
|------|------|------|
| Rossmere 0 슬롯 | 토요일 공개 티타임 없음 (멤버 전용 추정) | 사이트에서 확인 필요 |
| obsidian_export 실패 | GitHub Actions에 로컬 `/Users` 경로 없음 | 무해 (로컬 전용 기능) |
| Bel Acres FlareSolverr 의존 | CF Bot Fight Mode 우회 필요 | 운영 중 — CF 정책 변경 시 재검토 필요 |
| TeeItUp price 소수점 | `rates[].greenFeeCart` cents → `/ 100.0` 변환 중 부동소수점 오차 (예: 55.2380...) | 표시 시 `Math.round()` 또는 `toFixed(0)` 처리 권장 |
