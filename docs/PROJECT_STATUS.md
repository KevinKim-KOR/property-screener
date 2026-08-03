# PC-OCI 하이브리드 부동산 퀀트 스크리너 개발 현황 및 인수인계서

> **💡 전체 개발 명세서 및 가이드**: 아키텍처, 5-Factor 퀀트 공식, 11개 대시보드 컬럼 설명 및 사용법은 [종합 개발 명세서(DEVELOPMENT_SUMMARY.md)](file:///e:/AI%20Study/property/docs/DEVELOPMENT_SUMMARY.md)를 참고하세요.

이 문서는 데스크탑 PC 및 노트북 환경 간 개발 작업을 상호 이어서 진행할 수 있도록 작성된 현황 문서입니다.

## 1. 프로젝트 개요
* **목적**: 네이버 부동산 매물을 스캔하여 하락률 기반으로 퀀트 점수를 매기고, 교통 입지 정보와 함께 AI 분석 프롬프트를 텔레그램으로 알림해주는 자동화 시스템.
* **아키텍처**: 
  - **OCI (Cloud)**: 정기적으로 매물을 스크래핑(`crawler`)하고 텔레그램 알림(`notifier`)을 발송.
  - **PC (Local)**: 수집된 매물을 바탕으로 카카오 API로 입지 가점을 매기고 ML 스코어링(`ml_engine`) 수행.

---

## 2. 개발 진행 현황 (완료된 작업)

### ✅ Phase 1: DB 및 공통 모듈 구성 (완료)
- `common/models.py`: SQLite 테이블 (`properties`, `sent_alerts`) 스키마 정의 완료.
- `common/database.py`: DB 세션 관리 및 연결 로직 완료.
- `common/config_loader.py`: `config.yaml` 및 `.env` 파일 로더 완벽 구현.

### ✅ Phase 2: PC 분석 모듈 및 스마트 웹 GUI 대시보드 개발 (완료)
- **`pc/ml_engine/scorer.py` (5-Factor 전문 부동산 퀀트 로직)**: 
  - 단순 하락률 기반 스코어링에서 벗어나 **100점 만점의 5대 핵심 팩터(Valuation 30점 + Momentum 25점 + Location 20점 + Scale 15점 + Floor 10점)** 전문 퀀트 모델을 새롭게 도입했습니다.
  - 고점 대비 할인율과 평당가 매력도뿐만 아니라, **최근 1개월/3개월/6개월 간의 시세 회복 및 상승 탄력성(모멘텀)**, 대단지 유동성 프리미엄, 로열층 가점을 종합 산출합니다.
- **`pc/web_app.py` (스마트 로컬 웹 대시보드)**: 
  - 사용자가 설정 파일(`config.yaml`)을 편집하지 않고도 **웹 브라우저(`http://127.0.0.1:8585`)에서 직접 원하는 서울 지역을 체크하고 실시간 크롤링 및 분석 결과를 조회할 수 있는 FastAPI 기반 웹 GUI**를 신설했습니다.
  - **기능 1 ([매물 퀀트 분석 대시보드] 탭)**: 
    - **11개 정제된 테이블 컬럼**: `순위 / 지역명 / 단지명(동·층) / 평형 / 현재가 / 전고점 / 최근 1개월 / 최근 3개월 / 최근 6개월 / 퀀트점수 / 매물확인`으로 개편했습니다. (전고점 취소선 제거 및 최근 1·3·6개월 시세 변동을 한국식 상승 ▲(적색) / 하락 ▼(청색) 컬러로 표기)
    - **평형 및 금액 인터랙티브 조회 조건**: 화면 상단에 **`[20평형대 / 30평형대 / 40평형대 이상]` 평형 선택 버튼**과, **좌우로 조절하는 가로막대 매매가 제한 슬라이더**를 추가하여 실시간 필터링이 가능합니다.
    - **v4.3 고도화 반영 (2026-08-03)**:
      - **입지·임차수요 지표 5종 도입**: ① 전세가율(`jeonse_ratio`: 국토부 월세 0원 순수 전세 버킷 중위, CSV 파서 예외 처리 강화), ② 단지 좌표 지오코딩(`lat`, `lng`: 카카오 API 시군구+본번-부번 / 도로명 폴백), ③ 역세권 거리(`subway_str`: 카카오 SW8 지하철역 직선거리, `강남역 320m` 형식), ④ 학원가 밀도(`academies_str`: 카카오 AC5 학원 반경 1km `total_count` 기반 `학원 1692곳` 형식), ⑤ 초·중학교 거리(`schools_str`: 카카오 SC4 반경 2km 이내 유치원·고교·대학 제외 필터링 적용 `초 180m / 중 420m` 형식)
      - **UI 고정 컬럼 및 4대 프리셋 개편**: 고정 컬럼 폭 최적화(`지역 100px | 단지명 220px | 평형 130px`, 평형 표기 `34평 / 84㎡`), 4대 프리셋(`가격`, `흐름`, `단지`, `전체`) 및 개별 체크박스 local storage 기억.
      - **가격·게이트 고도화**: 전고점 p95 상향, 가격 역전 게이트 G3 완화(`1.10x` 초과 시 제외, 미만 적격 및 하락률 `0.0% 🔥신고가` 표시), M3/M6/M12 최소 거래 건수 2건 완화.
      - **법정동 다중 선택 필터**: 구 선택 시 해당 구의 법정동만 표시하고 적격 매물 건수 표기(`반포동 (26)`), 브라우저 LocalStorage 기억.
      - **실거래 데이터 기준일 배너 & 경과일 경고**: 매매 CSV 또는 갱신 마커(`_api_refresh.txt`) 기반 실제 자료 기준일 및 경과 일수 동적 스타일링(7일 초과 노란색, 30일 초과 빨간색 경고 배지).
      - **국토교통부 실거래가 API 증분 갱신 (`oci/crawler/molit_client.py`)**: 웹 대시보드 상단 `[🔄 최신 자료 가져오기]` 버튼(`POST /api/refresh`)을 통한 최근 3개월 매매/전월세 실거래가 API 증분 적재 및 퀀트 재계산. 빈 값(`""`, `"-"` vs `" "`) 및 본번/부번 0패딩 정수 정규화(`normalize_value`), 토지임대부(`land_leasehold`) 지원.
  - **기능 2 ([수집 지역 선택 & 실시간 크롤링] 탭)**: 주요 법정동 체크 후 크롤링 시 **20평형대, 30평형대, 40평형대 매물 동시 수집** 및 최신 5-Factor 퀀트 점수 갱신 수행.

### ✅ Phase 3: OCI 스캐너 및 알리미 뼈대 개발 (완료)
- **`oci/notifier/telegram_bot.py`**: 분석된 매물과 DB의 `sent_alerts` 테이블을 조인하여 중복 발송 없이 신규 매물만 텔레그램으로 알림.
- **`oci/main.py`**: OCI 파이프라인 진입점 구성 완료.

### ✅ Phase 4: 네이버 부동산 API 봇 차단(429 Error) 우회 및 자동화 검증 체계 (완료)
- **`oci/crawler/naver_crawler.py`**: `curl_cffi` (Chrome 120 TLS 지문 에뮬레이션) 및 DB 자동 적재 로직 완성.
- **`tests/test_naver_crawler.py`**: 개발 및 검증 단계에서 사용자가 수많은 명령어를 수동으로 승인해야 하는 고역을 방지하기 위해, 크롤링부터 DB 적재까지 프로그램 내부에서 일괄 자동 검증하는 Automated Test Suite를 추가했습니다.

---

### ✅ Issue 1. 상세 매물(Article) 크롤링 및 DB 저장 고도화 (완료)
- `oci/crawler/naver_crawler.py`의 `save_complex_properties_to_db(complex_list)` 구현 완료.
- 네이버 부동산 API(`new.land.naver.com`)를 통해 반포·서초 일대의 아파트 단지 정보를 실시간 스크래핑한 후, SQLite DB(`screener.db`의 `properties` 테이블)에 87건 이상의 아파트 단지 실매물 및 시세 정보를 자동 Insert/Replace 하도록 로직 구축.

### ✅ Issue 2. OCI 무료티어 Native 배포 환경 (Docker 미사용) 구축 (완료)
- **배포 인프라 대응**: 다른 주요 프로젝트로 인해 **Docker 사용이 불가한 OCI 무료티어 VM** 환경에 맞춰, 도커 없이 가볍게 동작하는 Native 파이프라인(`deploy/`) 환경을 완비했습니다.
- **작업 내용**:
  1. `deploy/oci_run.sh`: Python 가상환경(`.venv`) 자동 생성 및 종속성 설치 후 `oci/main.py`를 실행하는 Native Bash 스크립트 구현.
  2. `deploy/oci-property-screener.service`: Linux Background Service 등록을 위한 Systemd 유닛 파일 작성.
  3. `deploy/README_OCI_NATIVE.md`: Crontab(정기 크롤링) 및 Systemd 등록 가이드 작성.

---

## 4. PC/노트북 환경 세팅 및 구동 가이드

PC에서 작업을 이어서 하실 때 아래 순서대로 실행하세요:

1. **Git 저장소 최신화**:
   ```bash
   git pull origin master
   ```
2. **가상 환경 세팅 및 패키지 설치**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r pc/requirements.txt
   ```
3. **환경 변수 파일 (`.env`) 설정**:
   프로젝트 루트에 `.env` 파일을 설정합니다.
   ```env
   # 카카오맵 로컬 API REST API 키
   KAKAO_REST_API_KEY=발급받은_REST_API_키
   
   # 텔레그램 봇
   TELEGRAM_BOT_TOKEN=봇토큰
   TELEGRAM_CHAT_ID=채팅방ID
   ```
4. **PC 원클릭 실행 및 수집 (`start.bat` / `stop.bat` / `crawl_now.bat`)**:
   - `E:\AI Study\krx_alertor_modular` 프로젝트처럼 **원클릭 배치 파일**로 구동됩니다.
   - **대시보드 분석 실행**: 프로젝트 루트의 **`start.bat`을 더블 클릭**하세요.
     1. 기존 프로세스 Clean up (`stop.bat` 자동 호출)
     2. 가상환경(`.venv`) 확인 및 종속성 자동 설치
     3. 로컬 시각적 보고서(`report.html`) 사전 생성
     4. 전용 콘솔 창(`"PC Property Quant Screener"`)에서 분석 파이프라인 구동
     5. **기본 웹 브라우저가 자동 실행**되어 `pc/viewer/report.html` 대시보드를 바로 띄워줍니다. (API 미호출, 차단 위험 0%)
   - **실시간 네이버 부동산 단지 수집 (`crawl_now.bat`)**:
     - 원할 때 **`crawl_now.bat`을 더블 클릭**하면 네이버 부동산 API에서 신규 매물을 스크래핑해 `screener.db`를 최신화합니다.
     - **단지가 87곳인 이유**: 현재 `config.yaml`의 `target_regions`에 기본 설정으로 **서초구 반포동(63곳)** 및 **강남구 개포동(24곳)**만 활성화되어 있습니다.
     - **단지 수백~수천 곳으로 확장하는 법**: `config.yaml`을 열어 대치동, 잠실동, 압구정동, 서초동, 이촌동 등 주석(`#`) 처리된 법정동 코드의 주석을 풀면 원하는 만큼 즉시 확장됩니다.
   - **종료**: 프로젝트 루트의 **`stop.bat`을 더블 클릭**하면 구동 중인 분석 창 및 파이프라인 프로세스가 정리됩니다.
