# PC-OCI 하이브리드 부동산 퀀트 스크리너 개발 현황 및 인수인계서

이 문서는 사용자가 데스크탑에서 노트북으로 개발 환경을 전환할 때, 현재까지의 개발 진행 상황과 앞으로의 남은 과제를 파악하기 위해 작성되었습니다.

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
- **`pc/basic_crawler/location_crawler.py`**: 카카오맵 로컬 API를 연동하여 단지의 좌표를 따고 반경 1.5km 내 지하철역 도보 거리를 계산해 추가 가점 부여 로직 반영. (캐싱 적용으로 중복 API 호출 방지)
- **PC 실행 환경**: `start.bat`, `stop.bat`, `requirements.txt` 세팅 완료. 

### ✅ Phase 3: OCI 스캐너 및 알리미 뼈대 개발 (완료)
- **`oci/notifier/telegram_bot.py`**: PC에서 분석한 `ml_results.json`과 DB의 `sent_alerts` 테이블을 조인하여, 중복 발송 없이 신규 매물만 텔레그램으로 쏘는 로직 완성. (테스트 완료)
- **`oci/crawler/naver_crawler.py`**: 네이버 부동산 비공식 JSON API 클러스터링 호출 구조 작성 완료 (단, 봇 차단 이슈 잔존).
- **OCI 실행 환경**: `oci/main.py` 진입점 완성.

---

## 3. 남은 과제 및 미완성 영역 (노트북에서 이어서 할 작업)

### 🚨 Issue 1. 네이버 부동산 API 봇 차단(429 Error) 우회
- **원인**: 현재 `oci/crawler/naver_crawler.py`가 Python `requests`로 네이버 부동산 API를 찌르고 있으나, 네이버 측에서 봇 접근을 감지하고 `429 Too Many Requests`로 차단함.
- **해결 방안 계획**:
  1. **Selenium / Playwright 도입**: 브라우저 자동화 도구를 사용해 실제 사람이 접속하는 것처럼 쿠키와 세션을 생성하여 우회.
  2. **모바일 웹 파싱**: `m.land.naver.com`의 덜 엄격한 구형 API나 HTML 구조를 파싱하는 방법.

### ⏳ Issue 2. OCI / PC 환경 배포 준비 (Phase 4)
- **목표**: 노트북 및 클라우드(OCI)에서 클릭 한 번에 구동되도록 인프라 구축.
- **작업 내용**:
  1. `Dockerfile` 작성
  2. `docker-compose.yml` 작성 (선택)
  3. 로컬과 OCI 간의 실제 DB(sqlite) 동기화(SFTP 또는 SCP) 스크립트 고도화 (현재는 `sync_manager.py`에 Mock으로만 존재함).

---

## 4. 노트북 세팅 및 구동 가이드

노트북에서 이 Git 저장소를 Clone(또는 다운로드) 받은 후 다음을 수행하세요:

1. **가상 환경 세팅**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r pc/requirements.txt
   ```
2. **환경 변수 파일 생성**:
   프로젝트 루트에 `.env` 파일을 만들고 아래 값을 채워넣습니다. (`.env.example` 참고)
   ```env
   # 카카오맵 로컬 API
   KAKAO_REST_API_KEY=발급받은키
   
   # 텔레그램 봇
   TELEGRAM_BOT_TOKEN=봇토큰
   TELEGRAM_CHAT_ID=채팅방ID
   ```
3. **실행 테스트**:
   - PC 분석 엔진 테스트: `start.bat` (또는 `python pc/main.py`)
   - OCI 텔레그램 알림 테스트: `python oci/main.py`
