# PC-OCI 하이브리드 부동산 퀀트 스크리너 개발 현황 및 인수인계서

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

### ✅ Phase 2: PC 분석 모듈 개발 (완료)
- **`pc/ml_engine/scorer.py`**: 가상 데이터(또는 실데이터)를 기반으로 평당가, 하락률을 계산하여 기본 점수를 산출.
- **`pc/basic_crawler/location_crawler.py`**: 카카오맵 로컬 API를 연동하여 단지의 좌표를 따고 반경 1.5km 내 지하철역 도보 거리를 계산해 추가 가점 부여 로직 반영 (REST API 키 연동 검증 완료).
- **PC 실행 환경**: `start.bat`, `stop.bat`, `requirements.txt` 세팅 완료. 

### ✅ Phase 3: OCI 스캐너 및 알리미 뼈대 개발 (완료)
- **`oci/notifier/telegram_bot.py`**: PC에서 분석한 `ml_results.json`과 DB의 `sent_alerts` 테이블을 조인하여, 중복 발송 없이 신규 매물만 텔레그램으로 쏘는 로직 완성 (실제 텔레그램 봇 토큰 연동 및 알림 발송 검증 완료).
- **`oci/main.py`**: OCI 파이프라인 진입점 테스트 완료.

### ✅ Phase 4: 네이버 부동산 API 봇 차단(429 Error) 우회 해결 (완료)
- **`oci/crawler/naver_crawler.py`**: `curl_cffi` (Chrome 120 TLS 지문 에뮬레이션) 및 메인 세션 쿠키 초기화 로직 적용.
- 기존의 429 Too Many Requests 방화벽 차단을 우회하여 100개 이상의 아파트 단지 목록 API 수집(HTTP 200)에 성공함.

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
4. **실행 테스트**:
   - PC 분석 엔진 테스트: `.\.venv\Scripts\python pc/main.py`
   - OCI 텔레그램 알림 및 크롤러 테스트: `.\.venv\Scripts\python oci/main.py`
