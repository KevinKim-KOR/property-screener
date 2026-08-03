# 서울 아파트 퀀트 투자 분석 및 실시간 모니터링 시스템 (Development Summary)

> **문서 버전**: v4.3.0  
> **최종 업데이트**: 2026-08-02 (SCORING v4.3 퀀트 스크리너 고도화 반영)  
> **시스템 개요**: 네이버 부동산 API 실거래/호가 매물 실시간 크롤링, 5-Factor 부동산 전문 퀀트 투자 스코어링, 로컬 웹 GUI 대시보드(`http://127.0.0.1:8585`), 텔레그램 알림 발송을 통합한 엔드투엔드 부동산 분석 솔루션입니다.

---

## 1. 전체 시스템 아키텍처 (System Architecture)

본 시스템은 **네이버 API 차단(429 Error) 방지** 및 **효율적인 로컬 분석**을 위해 모듈이 명확히 분리되어 있습니다.

```mermaid
graph TD
    subgraph "Data Collection Layer (OCI / Backend Crawler)"
        NC["NaverCrawler (oci/crawler/naver_crawler.py)"] -->|20/30/40평형대 수집| DB[("SQLite DB (screener.db)")]
        NC -->|네이버 부동산 API (429 방어)| NAVER["네이버 부동산"]
    end

    subgraph "Core Analytics Layer (PC / ML Engine)"
        DB -->|매물 및 추세 데이터| SQ["MLEngine (pc/ml_engine/scorer.py)"]
        LC["LocationCrawler (pc/basic_crawler/location_crawler.py)"] -->|카카오맵 지하철 도보 거리| SQ
        SQ -->|5-Factor 퀀트 점수 산출| JSON["ml_results.json & DB 적재"]
    end

    subgraph "User Interface & Presentation Layer (PC Web GUI)"
        JSON --> WEB["FastAPI Web Dashboard (pc/web_app.py - Port 8585)"]
        DB --> WEB
        WEB -->|11개 컬럼 & 평형/금액 필터| BROWSER["웹 브라우저 (http://127.0.0.1:8585)"]
    end

    subgraph "Notification Layer (OCI Notifier)"
        DB --> TB["TelegramBot (oci/notifier/telegram_bot.py)"]
        JSON --> TB
        TB -->|고득점 신규 매물 알림| TELEGRAM["Telegram Messenger"]
    end
```

---

## 2. 프로젝트 디렉토리 및 핵심 모듈 구성

```text
property-screener/
│
├── common/                              # [공통 라이브러리 및 데이터 계층]
│   ├── config_loader.py                 # config.yaml 및 .env 설정 파일 로더
│   ├── database.py                      # SQLite3 (screener.db) 연결 및 자동 테이블 마이그레이션
│   └── models.py                        # properties, sent_alerts, target_regions 스키마 정의
│
├── oci/                                 # [수집 및 알리미 전용 계층]
│   ├── crawler/
│   │   └── naver_crawler.py             # 20평형·30평형·40평형대 매물 동시 수집 및 1M/3M/6M 변동률 계산
│   ├── notifier/
│   │   └── telegram_bot.py              # 중복 발송 이력(sent_alerts) 필터링 및 고득점 매물 텔레그램 푸시
│   └── main.py                          # OCI 수집 & 알림 실행 진입점
│
├── pc/                                  # [분석 및 스마트 웹 대시보드 계층]
│   ├── basic_crawler/
│   │   └── location_crawler.py          # 카카오맵 로컬 API 기반 지하철역 반경 1.5km 도보 시간 산출
│   ├── ml_engine/
│   │   └── scorer.py                    # 100점 만점 5-Factor 부동산 퀀트 투자 모델 (Val/Mom/Loc/Scale/Floor)
│   ├── viewer/
│   │   └── generate_report.py           # 정적 HTML 분석 요약 보고서 생성
│   ├── web_app.py                       # FastAPI/Uvicorn (포트 8585) 기반 스마트 웹 GUI 대시보드 서버
│   └── main.py                          # PC 분석 및 정적 보고서 실행 진입점
│
├── docs/                                # [프로젝트 문서]
│   ├── PROJECT_STATUS.md                # 마일스톤 및 개발 상태 추적 문서
│   └── DEVELOPMENT_SUMMARY.md           # 본 종합 개발 명세서
│
├── config.yaml                          # 관심 법정동 지역 및 필터 기준 설정
├── .env                                 # 카카오 API KEY 및 텔레그램 BOT 토큰 (시크릿)
├── start.bat                            # [Windows] 포트 정리 후 웹 GUI 대시보드 자동 실행 스크립트
└── stop.bat                             # [Windows] 로컬 서버(포트 8000/8585) 안전 종료 스크립트
```

---

## 3. 핵심 개발 기능 명세

### 3.1 스마트 로컬 웹 대시보드 (`pc/web_app.py`)
사용자가 별도의 설정 파일이나 명령어를 알 필요 없이 **웹 브라우저(`http://127.0.0.1:8585`)에서 클릭만으로 서울 지역을 선택하고 실시간 퀀트 분석 결과를 조회할 수 있는 대시보드**입니다.

#### ① [매물 퀀트 분석 대시보드] 탭
- **17개 확장 컬럼 및 고정 컬럼·4대 프리셋 시스템 (v4.3 개편)**:
  - **고정 컬럼 (`지역 | 단지명 | 평형`)**: 좌우 스크롤 시에도 최좌측에 고정(`100px / 220px / 130px`). 평형 표기를 `34평 / 84㎡` 형식으로 직관 개선.
  - **4대 뷰 프리셋 버튼**:
    - `[가격] (기본)`: 최근 거래가, 전고점, 전고점 시점, 하락률, 초과하락, **전세가율**(최근 6개월 월세 0원 순수 전세 보증금 중위 ÷ 거래가)
    - `[흐름]`: M3, M6, M12, 거래 건수, 거래량비
    - `[단지]`: 연식, 브랜드, **역세권**(`강남역 320m` 형식), **학원가**(`학원 87곳` 형식), **학교거리**(`초 180m / 중 420m` 형식)
    - `[전체]`: 선택 가능한 모든 컬럼 동시 노출
  - 개별 컬럼 체크박스를 제공하며 브라우저 `localStorage('screener_visible_cols')`에 유지.
- **실시간 인터랙티브 평형 & 매매가 필터**:
  - **평형 조건 버튼**: `[전체 평형]`, `[20평형대]`, `[30평형대]`, `[40평형대 이상]` 선택 즉시 클라이언트 필터링.
  - **금액 조건 슬라이더**: 좌우로 조절 가능한 가로막대 슬라이더(`15.0억` ~ `60.0억 이하`)를 통해 예산 조건 매물만 필터링.
- **API 차단 방지 `[⚡ 퀀트 점수 즉시 재계산 (API 미호출)]` 버튼**:
  - 네이버 부동산 API를 재호출하지 않고, 현재 DB에 적재된 로컬 매물 데이터만을 기반으로 **1초 만에 5-Factor 퀀트 점수를 다시 산출하여 갱신**합니다.

#### ② [수집 지역 선택 & 실시간 크롤링] 탭
- 서울 주요 12개 핵심 법정동(반포동, 개포동, 대치동, 잠실동, 압구정동, 서초동, 이촌동, 여의도동, 성수동 등) 체크박스 제공.
- 원하는 지역 체크 후 `[선택 지역 저장 후 실시간 크롤링 시작]` 버튼 클릭 시:
  1. `config.yaml`에 선택 지역 자동 업데이트
  2. 백그라운드에서 네이버 부동산 실거래/호가 매물(**20평형대, 30평형대, 40평형대**) 동시 수집
  3. 최근 1개월, 3개월, 6개월 시세 변동률(`change_1m, 3m, 6m`) 계산 및 DB 적재
  4. 최신 5-Factor 퀀트 스코어링 자동 실행 완료

---

### 3.2 5-Factor 부동산 전문 퀀트 스코어링 모델 (`pc/ml_engine/scorer.py`)
단순 고점 대비 하락률에 의존하던 점수 체계를 발전시켜, **실제 부동산 투자자가 매물을 평가하는 5대 핵심 팩터를 100점 만점으로 계량화**하였습니다.

```math
\text{Total Score} = \text{Valuation (30)} + \text{Momentum (25)} + \text{Location (20)} + \text{Scale (15)} + \text{Floor Premium (10)}
```

| 팩터 구분 | 배점 만점 | 평가 지표 및 점수 산출 방식 |
| :--- | :---: | :--- |
| **1. Valuation<br>(가격 밸류에이션)** | **30점** | • 고점(최고실거래가) 대비 현재 호가의 할인율 매력도 (`drop_rate`)<br>• 평당가 합리성 (할인율 15% 이상 시 상위 점수 부여, 기본 10점 ~ 최대 30점) |
| **2. Momentum<br>(시세 변동 모멘텀)** | **25점** | • **최근 1개월·3개월·6개월 실거래 시세 변동률(`change_1m, 3m, 6m`)**의 평균 추세<br>• 하락을 멈추고 **상승 전환 또는 견조한 회복세를 보이는 매물에 탄력성 가점 부여** |
| **3. Location<br>(역세권 입지)** | **20점** | • 카카오맵 로컬 API 연동을 통한 반경 1.5km 이내 지하철역 도보 시간 계산<br>• **도보 5분 이내(20점) / 10분 이내(15점) / 15분 이내(10점)** |
| **4. Scale & Liquidity<br>(규모 및 브랜드 유동성)** | **15점** | • 아파트 브랜드 및 대단지 거래 활성도 유동성 가점<br>• 선호 브랜드(`자이`, `래미안`, `힐스테이트`, `아크로`, `푸르지오`, `아이파크`, `롯데캐슬`, `더샵`, `리센츠`, `엘스`, `트리지움`) 해당 시 15점, 그 외 12점 |
| **5. Floor Premium<br>(층수 및 호가 프리미엄)** | **10점** | • 매물 층수(`floor`) 정보 분석<br>• **고층 / 로열층 / 중층 매물 가점(10점)**, 저층(7점) |

---

### 3.3 데이터 모델 및 자동 스키마 마이그레이션 (`common/models.py`, `common/database.py`)
DB 연결(`init_db()`) 시 스키마가 자동으로 마이그레이션되어 신규 컬럼이 유실 없이 반영됩니다.

- **`properties` 테이블 주요 컬럼**:
  - `property_id`, `complex_code`, `complex_name`, `region_name`, `building_dong`, `floor`
  - `high_price` (전고점 최고실거래가), `asking_price` (현재 매매 호가), `area_pyeong` (평형: 20PY/30PY/40PY)
  - `drop_rate` (고점 대비 하락률)
  - **`change_1m`, `change_3m`, `change_6m`** (최근 1개월·3개월·6개월 시세 변동률)
- **`sent_alerts` 테이블**:
  - 텔레그램 발송 이력을 `property_id` 및 `sent_at`으로 기록하여 중복 알림을 완벽 차단합니다.

---

### 3.4 네이버 API 차단 방어 크롤러 (`oci/crawler/naver_crawler.py`)
- **429 Too Many Requests 방어**:
  - 대량 수집 시 네이버 부동산 서버 차단을 막기 위해 매 요청 사이에 랜덤 지연(`time.sleep`)과 헤더 스푸핑(User-Agent, Referer) 적용.
- **다중 평형 수집**:
  - 각 단지별로 **20평형대(24~26평)**, **30평형대(32~35평)**, **40평형대(42~46평)** 실매물을 동시 수집하여 다양한 평형 선택 조건을 지원합니다.

---

## 4. 시스템 설치 및 간편 실행 가이드 (Quick Start Guide)

### 4.1 Windows 환경 원클릭 실행 (`start.bat` / `stop.bat`)
터미널에서 명령어 입력 없이 프로젝트 디렉토리 루트의 배치 파일을 실행합니다.

1. **대시보드 시작**:
   - `start.bat` 더블 클릭 (또는 터미널에서 `.\start.bat` 실행)
   - 자동으로 기존 포트(8585) 충돌 프로세스를 정리하고 로컬 웹 GUI 서버(`http://127.0.0.1:8585`)를 구동합니다.
2. **대시보드 종료**:
   - `stop.bat` 더블 클릭 (또는 터미널에서 `.\stop.bat` 실행)

### 4.2 웹 대시보드 활용 3단계
1. 브라우저에서 `http://127.0.0.1:8585` 에 접속합니다.
2. **`[매물 퀀트 분석 대시보드]`** 탭에서 **`[20평형대 / 30평형대 / 40평형대 이상]`** 버튼과 **매매가 조절 슬라이더**를 좌우로 조작하여 원하는 조건의 매물 순위를 확인합니다.
3. 관심 매물 우측의 **`[네이버 부동산 →]`** 버튼을 클릭하여 네이버 실매물 상세 페이지로 바로 이동합니다.

---

## 5. 변경 이력 및 릴리즈 노트 (Release Notes)
- **v1.0.0 (2026-07-29)**
  - `web_app.py`: 웹 대시보드 11개 컬럼 순서 개편, 전고점 취소선 제거, 1M/3M/6M 한국식 시세 추세 컬러 표기(▲ 적색/▼ 청색) 적용.
  - `pc/ml_engine/scorer.py`: 100점 만점 5-Factor 전문 부동산 퀀트 투자 모델(Valuation 30 / Momentum 25 / Location 20 / Scale 15 / Floor 10) 정식 도입.
  - `oci/crawler/naver_crawler.py`: 20평형대, 30평형대에 이어 **40평형대 매물(40PY)** 수집 로직 및 1M/3M/6M 변동률 산출 로직 반영.
  - `common/database.py`: DB 자동 스키마 마이그레이션 로직 강화.
