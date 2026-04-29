# Golf Course Booking DB — 프로젝트 핸드오프

> 마지막 업데이트: 2026-04-21
> 다음 단계: 로컬 크롤링 안정화 → 새 웹사이트 개발 (Vercel + Supabase)

---

## 1. 프로젝트 개요

위니펙 근처 골프장의 티타임을 매주 크롤링해서 Notion + Obsidian + CSV에 저장하는 파이프라인.
궁극적 목표는 이 데이터를 기반으로 **새로운 웹사이트**를 만들어 예약 정보를 공유/추적하는 것.

### 핵심 설계 결정
- **타겟 날짜**: 매주 **토요일** (주말 골프용)
- **자동화**: 매주 **월요일 오전 8시 위니펙 시간**에 GitHub Actions 실행
- **데이터 저장**: Notion DB (공유/뷰) + Obsidian (개인 백업) + CSV (이중 백업)
- **기존 사이트 연동 안 함**: `good-morning-golf.vercel.app`은 사용하지 않음. 새 Vercel 프로젝트 + 새 도메인으로 신규 제작 예정
- **Supabase**: 새 웹사이트 개발 시 처음부터 재설계

---

## 2. 데이터 흐름

```
[매주 월요일 오전 8시]
     ↓
GitHub Actions 트리거
     ↓
Python 크롤러 (Playwright)
     ↓
┌─────────────┬─────────────┬─────────────┐
↓             ↓             ↓             ↓
Notion DB   Obsidian    CSV 백업    Telegram (선택)
(공유용)    (개인)      (이중백업)
```

---

## 3. 파일 구조

```
~/golf-agent/
├── run.py                  # 메인 오케스트레이터 (thin)
├── config.py               # 코스 목록 + ALL_DAY_CUTOFF (23:59)
├── season.py               # 시즌 계산 + get_target_date (다음 토요일)
├── message.py              # Telegram 메시지 빌더
├── logger.py               # 로그 유틸
├── telegram.py             # Telegram 전송
├── webapp.py               # (미사용 — 새 웹사이트 개발 시 재설계)
├── scrapers/
│   ├── __init__.py         # SCRAPERS 레지스트리
│   ├── base.py             # parse_time, within_cutoff, make_slot, body_text_fallback
│   ├── tee_on.py           # Tee-On + ALTCHA 브라우저 우회
│   ├── clubhouse_online.py
│   ├── prophetservices.py  # 플레이어 수별 중복 제거 로직 포함
│   ├── cps_golf.py
│   ├── chronogolf.py
│   ├── teeitup.py
│   └── golfnow.py          # API 우선 + Playwright fallback
├── exporters/
│   ├── notion_exporter.py  # Notion DB upsert + 컬럼 자동 추가
│   ├── obsidian_exporter.py # 로컬 vault 마크다운 저장
│   └── csv_backup.py       # ~/golf-agent/backup/YYYY-MM-DD.csv
├── .github/workflows/weekly_crawl.yml
├── .env                    # 로컬 전용 (git 제외)
├── .gitignore
└── requirements.txt
```

---

## 4. 타겟 날짜 로직 (season.py)

```python
def get_target_date(today: date) -> date:
    """이번 주 토요일을 반환 (오늘이 토요일이면 다음 주 토요일)."""
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    return today + timedelta(days=days_until_saturday)
```

- **평일(월~금) 실행** → 이번 주 토요일
- **토요일 실행** → 다음 주 토요일
- **일요일 실행** → 이번 주 토요일 (6일 후)

---

## 5. 환경 변수

### `.env` (로컬)
```
NOTION_TOKEN=ntn_z79312512855f8GvFVwGKDCQ8ZEKgVWlghKJ82zMUgg6UC
TELEGRAM_BOT_TOKEN=       # 미설정 → --dry-run 자동
TELEGRAM_CHAT_ID=         # 미설정
API_SECRET_KEY=gmg-api-secret-2026
WEBAPP_URL=https://good-morning-golf.vercel.app  # 미사용
```

### GitHub Actions Secrets (필요 시)
- `NOTION_TOKEN`
- `TELEGRAM_BOT_TOKEN` (선택)
- `TELEGRAM_CHAT_ID` (선택)
- `API_SECRET_KEY` (선택)

---

## 6. 실행 방법

```bash
# 로컬 테스트 (Telegram 없이 Notion/Obsidian 동작)
python3 run.py --dry-run

# 2팀 모드 (연속 슬롯 찾기)
python3 run.py --dry-run 두팀이야

# 정상 실행 (Telegram 토큰 설정 필요)
python3 run.py
```

---

## 7. Notion 연동

### 계정 정보
- **Integration 이름**: Golf Booking
- **Token**: `ntn_z79312512855f8GvFVwGKDCQ8ZEKgVWlghKJ82zMUgg6UC`
- **Parent Page**: ⛳ Golf Booking (`3491d8bd-4a55-813e-bbba-d2e69a51b179`)
- **Database**: Golf Course 크롤링 결과 (`d059a4b4-ac30-4ee6-806c-9f2190cdb435`)
- **Collection ID**: `328cbce9-928f-44c6-955e-3d4596e0e8be`
- **Default View**: `3a54d67b-a785-469a-bcb8-98275475d951`

### DB 컬럼 (뷰 순서)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| Course | Title | 코스 이름 |
| Status | Select | 🟢 green / 🔴 red / 🟡 yellow / ⚫ error |
| Earliest 2-Team | Text | 2팀 연속 가장 이른 시간 (예: "07:00 + 07:10") |
| Earliest Slot | Text | 가장 이른 단일 슬롯 |
| Slots | Text | 전체 가능 시간 목록 |
| Booking URL | URL | 예약 링크 |
| Date | Date | 크롤링 대상 날짜 (= 토요일) |
| Cart Mandatory | Checkbox | 카트 필수 여부 |
| Lowest Price | Number ($) | 최저 가격 |
| Discount % | Number | 할인율 |
| Distance km | Number | 위니펙 시내 기준 거리 |
| Source | Select | individual / golfnow |

### 동작 방식
- **Upsert**: 같은 `(Date, Course)` 페이지 있으면 업데이트 (최신 유지), 없으면 생성
- **히스토리 누적**: 매주 새 토요일 날짜 → 자동으로 16개 새 레코드
- **자동 컬럼 추가**: `_ensure_db_columns()` 가 `Earliest Slot` / `Earliest 2-Team` 없으면 자동 추가

### 뷰(탭) 자동 생성
- 공개 API: 미지원
- 해결책: `NOTION_TOKEN_V2` (사용자 세션 쿠키) → 내부 API `saveTransactionsFanout` 호출
- **매 크롤링마다 자동으로 날짜 이름 뷰 생성** (이미 존재하면 스킵)
- 쿠키 발급: notion.so → DevTools → Application → Cookies → `token_v2` 복사
- 쿠키 만료: ≈1년, 만료 시 .env / GitHub Secret 갱신 필요
- 핵심 ID:
  - `space_id`: `0af1d8bd-4a55-81ac-a670-0003f1ce2b88`
  - `Date` property ID: `vHj\``
  - View parent: `block` (database), 아니라 collection 아님

---

## 8. Obsidian 연동

- **Vault 경로**: `/Users/jin-chulmoon/Documents/Obsidian Vault/`
- **파일명**: `YYYY-MM-DD.md` (토요일 날짜)
- **포맷**: YAML frontmatter + 전체 코스 마크다운 테이블 + 상세 + 상태 안내
- Notion과 **동일한 컬럼 순서**

### 공유 한계
- Obsidian은 로컬 개인용 → 다른 사람과 공유 어려움
- Notion이 공유용, Obsidian은 개인 백업용
- **웹사이트 구축 후**: Obsidian exporter → Local REST API 플러그인 방식으로 교체 가능 (방법 2)

---

## 9. 코스 목록 & 스크래퍼 현황

### INDIVIDUAL_COURSES (10개)
| 코스 | 시스템 | 상태 | 비고 |
|---|---|---|---|
| River Oaks | tee_on | ✅ | |
| Lorette | tee_on | ✅ | |
| Southside | tee_on | ⚠️ 불안정 | ALTCHA 후 결과 없음 간헐 |
| Windsor Park | tee_on | ❌ | TrailSearch URL — ComboLanding 플로우 다름 |
| Quarry Oaks | prophetservices | ✅ | 플레이어 수별 행 중복 제거됨 |
| Rossmere | clubhouse_online | ⚠️ | 간헐적 타임아웃 |
| St. Boniface | clubhouse_online | ✅ | |
| Bridges | cps_golf | ✅ | 카트 필수 |
| Larters | chronogolf | ❌ | API 404 |
| John Blumberg | teeitup | ❌ | 타임아웃 35초 |

### GOLFNOW_COURSES (7개)
Assiniboine, Bel Acres, Kingswood, Oakwood, Maplewood, Whispering Winds, Larters
(Larters는 individual과 중복 → 런타임에 자동 스킵)

---

## 10. 상태 아이콘

| 아이콘 | 의미 |
|---|---|
| 🟢 green | 예약 가능 — 슬롯 확인됨 |
| 🔴 red | 슬롯 없음 — 당일이거나 마감 |
| 🟡 yellow | 접속 불가 — 사이트 타임아웃 |
| ⚫ error | 수집 오류 — 스크래퍼 파싱 실패 |

---

## 11. GitHub Actions 자동화

**파일**: `.github/workflows/weekly_crawl.yml`

```yaml
schedule:
  - cron: '0 13 * * 1'   # 매주 월요일 13:00 UTC = 오전 8시 위니펙 CDT
```

- **Telegram 미설정 시**: 자동 `--dry-run` 모드 (Notion/Obsidian은 항상 실행)
- **CSV 백업**: Actions artifact로 90일 보관
- **수동 실행**: GitHub Actions 탭 → Run workflow

### 미완료: GitHub repo 초기화
```bash
cd ~/golf-agent
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/golf-agent.git
git push -u origin main
```
이후 Settings → Secrets → `NOTION_TOKEN` 등록 필요.

---

## 12. Tee-On ALTCHA 우회 (핵심 로직)

Tee-On은 ALTCHA proof-of-work CAPTCHA를 사용해서 `requests.post()`로 직접 접근 불가.
반드시 Playwright로 브라우저 탐색해야 함.

```
ComboLanding 페이지
  → "Public Enter Here" 링크 클릭
  → Date select_option (YYYY-MM-DD)
  → SearchTime select_option ("06:00")
  → JS로 hidden radio 설정:
     document.getElementById('toggle-18').checked = true
     document.getElementById('toggle-4').checked = true
     document.getElementById('form').submit();
  → ALTCHA 자동 풀릴 때까지 대기 (최대 30초)
  → body에서 시간 패턴 파싱: r'\b(\d{1,2}:\d{2}\s*[AaPp][Mm])\b'
```

**Windsor Park 문제**: `TrailSearch` URL은 ComboLanding 구조가 다름 → 별도 분기 필요

---

## 13. 미완료 작업 목록

### 🔧 버그 수정
- [ ] **Windsor Park** — TrailSearch URL 처리 로직 추가
- [ ] **John Blumberg** — teeitup 스크래퍼 타임아웃 해결 (wait_until 완화)
- [ ] **Larters** — Chronogolf API 404 원인 파악
- [ ] **Southside** — ALTCHA 간헐 실패 재시도 강화
- [ ] **Rossmere** — 간헐적 타임아웃 재시도

### 🚀 자동화 완성
- [ ] GitHub repo 초기화 (`git init` + push)
- [ ] GitHub Secrets에 `NOTION_TOKEN` 등록
- [ ] 첫 자동 실행 성공 확인
- [ ] Telegram 봇 토큰 발급 (선택)

### 📅 주별 루틴
- [ ] 매주 월요일 크롤링 결과 확인
- [ ] Claude Code에게 `"이번 주 뷰 만들어줘"` 요청 (Notion 뷰 생성)

---

## 14. 🌐 웹사이트 개발 계획 (다음 단계)

### 목표
- 새 Vercel 프로젝트 + 새 도메인
- Supabase를 백엔드 DB로 사용
- 크롤링 결과를 웹에서 조회 + 예약 투표 기능

### 예상 기술 스택
- **프론트**: Next.js 15 (App Router) + Tailwind CSS
- **백엔드**: Supabase (Postgres + Auth + Realtime)
- **배포**: Vercel
- **도메인**: 신규 (미정)

### 데이터 소스 마이그레이션
- Notion DB → Supabase로 데이터 옮기거나, 이중 쓰기
- `notion_exporter.py` 옆에 `supabase_exporter.py` 추가 예정
- 기존 `webapp.py`는 참고용으로만 유지 (기존 good-morning-golf 연동 코드는 버림)

### 주요 기능
1. 이번 주 토요일 슬롯 목록 (대시보드)
2. 가격/거리/시간별 필터
3. 히스토리 조회 (주별 트렌드)
4. 팀원 투표 (Supabase Realtime)
5. 예약 담당자 지정

### 단계적 이행
1. **Phase 1 (현재)**: 로컬 크롤링 + Notion/Obsidian 저장 안정화
2. **Phase 2**: GitHub Actions 자동화 + 스크래퍼 버그 수정
3. **Phase 3**: Supabase 프로젝트 생성 + 스키마 설계
4. **Phase 4**: Next.js 대시보드 개발
5. **Phase 5**: 투표/알림 기능
6. **Phase 6**: Obsidian을 Local REST API 방식으로 전환 (선택)

---

## 15. 리소스 / 참조

- **Notion 페이지**: https://www.notion.so/3491d8bd4a55813ebbbad2e69a51b179
- **Notion DB**: https://www.notion.so/d059a4b4ac304ee6806c9f2190cdb435
- **Obsidian vault**: `/Users/jin-chulmoon/Documents/Obsidian Vault/`
- **로컬 프로젝트**: `/Users/jin-chulmoon/golf-agent/`
- **로그**: `~/golf-agent/logs/run_YYYY-MM-DD.json`
- **CSV 백업**: `~/golf-agent/backup/YYYY-MM-DD.csv`

---

## 16. 세션 이어가기 가이드 (웹사이트 개발 시작할 때)

다음 세션에서 Claude Code와 웹사이트 개발을 시작할 때:

1. **이 파일 읽기** — 프로젝트 전체 컨텍스트 파악
2. **현재 상태 확인**:
   - `python3 run.py --dry-run` 동작 확인
   - Notion DB에 이번 주 데이터 있는지 확인
   - GitHub Actions 성공 여부 확인
3. **스크래퍼 이슈 중 우선순위 정하기** — 3개 이상 실패 시 웹사이트보다 수정 먼저
4. **웹사이트 Phase 3 시작**:
   - 새 Vercel 프로젝트 이름 정하기
   - 새 Supabase 프로젝트 생성
   - 도메인 후보 정하기
   - Next.js 또는 Astro 선택

### 중요한 결정 사항 (이전 세션)
- ❌ `good-morning-golf.vercel.app`에 연동 안 함
- ✅ 화요일이 아닌 **토요일** 데이터만 크롤링
- ✅ 매주 월요일 오전 8시 자동 실행
- ✅ 같은 날짜 재실행 시 최신 데이터로 덮어쓰기 (upsert)
- ✅ Obsidian은 개인 백업용, 공유는 Notion
- ✅ Notion 뷰 자동 생성은 불가 → 매주 Claude Code에게 요청
