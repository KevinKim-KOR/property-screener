# 부동산 퀀트 스코어링 v2 설계 명세서

> **문서 버전**: v2.1.0-draft
> **작성일**: 2026-07-29
> **대상 프로젝트**: `property-screener` (PC-OCI 하이브리드 부동산 퀀트 스크리너)
> **대상 독자**: 구현 담당 개발 AI
> **선행 문서**: `docs/DEVELOPMENT_SUMMARY.md` (v1.0.0), `docs/PROJECT_STATUS.md`

### 개정 이력
| 버전 | 일자 | 내용 |
| :-- | :-- | :-- |
| v2.0.0 | 2026-07-29 | 최초 작성 |
| v2.0.1 | 2026-07-29 | **유니버스를 서초구+강남구 2개 구로 확정**(§8.0 신설). 자치구 확장 대신 2개 구 내 전 법정동 활성화로 변경. 비교군을 2단계+팩터별 스코프 구조로 재설계(§8.1.1, §8.1.2). A1 기준선을 벨트 통합으로, A3/A4를 SGG로 분리. A3 가중치 0.20→0.10 하향. 국토부-네이버 역할 분담 명시(§4.1). UI 구 비교 패널(§14.6), 한계 L8·L9 추가. Q1 해결 처리. |
| v2.0.2 | 2026-07-29 | **국토부 수집 경로를 CSV 백필 + API 증분으로 이원화**(§4.1.1 신설). 공공데이터포털 점검(7/29~8/2)으로 API 키 발급이 일시 중단됨에 따라 `rt.molit.go.kr` CSV 경로를 백필 주 경로로 승격. CSV 원본 아카이빙을 통한 Point-In-Time 복원 설계 추가(§16.1 한계 완화). `trades_sale`에 스냅샷 추적 컬럼 3종 추가. 구현 우선순위 재배열(§19) — API 키를 임계 경로에서 제거. |
| v2.1.0 | 2026-07-29 | **CSV 실물 컬럼 20종 확인 완료**(§4.1.1). 해제사유발생일·거래유형 존재 확인 → API 폴백 불필요, P1-AC2b 해결. 지번(본번/부번)·도로명 제공 확인에 따라 **단지 매칭을 지번 기반 4단계로 전면 재설계**(§5, 최대 리스크 해소). 등기일자 기반 미등기 장기경과 게이트 `G2b` 신설(§9.1.1) 및 전고점 탐지 연계. 시군구 문자열 파싱 요구사항 추가(§4.1.2). `trades_sale` 컬럼 CSV 실물 기준 확장. A3 오작동을 실데이터로 확증하여 제거 후보로 격상. |

---

## 0. 문서의 목적과 범위

### 0.1 목적
현행 5-Factor 스코어링(`pc/ml_engine/scorer.py`)을 **비교군 상대평가 기반 4-Block 팩터 모델(v2)** 로 대체한다.

### 0.2 In Scope
- 스코어링 단위 재정의 (L1 시장 점수 / L2 매물 괴리)
- 국토부 실거래가 API 수집 계층 신설
- DB 스키마 확장 및 마이그레이션
- 팩터 산출 · 정규화 · 집계 파이프라인
- 데이터 품질 게이트 및 리스크 승수
- v1/v2 병행(Shadow) 운영 및 검증 체계

### 0.3 Out of Scope (이번 Phase 제외)
- 머신러닝 기반 가중치 최적화 (v2 안정화 후 별도 Phase)
- 크롤러 수집 로직 자체의 변경 (429 방어 로직 등은 현행 유지)
- 텔레그램 봇의 발송 인프라 변경 (메시지 포맷만 변경)

### 0.4 개발 AI 준수 사항 (Hard Constraints)

| # | 제약 | 사유 |
| :-- | :-- | :-- |
| C1 | 본 문서에 명시되지 않은 **신규 공개 API/함수 시그니처를 임의로 추가하지 않는다.** 필요 시 문서 갱신을 먼저 요청한다. | 계약 표류 방지 |
| C2 | 팩터 가중치·임계값을 **코드에 하드코딩하지 않는다.** 전부 `config/scoring_v2.yaml`에서 로드한다. | 튜닝 가능성 확보 |
| C3 | 모든 외부 API 호출에 **timeout을 명시**한다. 기본 10초. | 무한 대기 방지 |
| C4 | 점수 산출 결과는 **스냅샷 테이블에 저장**하고, UI/알림은 스냅샷만 조회한다. 조회 시점 재계산 금지. | 저장·조회 분리 원칙 |
| C5 | 데이터 부족은 **감점이 아니라 제외(fail-closed)** 로 처리한다. 결측을 0점이나 평균값으로 대체하지 않는다. | 허위 신호 방지 |
| C6 | v1 스코어러(`scorer.py`)를 **삭제하지 않는다.** v2와 병행 산출한다. | 회귀 비교 가능성 |
| C7 | 백테스트 로직은 **Point-In-Time 로더**를 반드시 경유한다. 기준일 이후 데이터 접근 시 예외를 발생시킨다. | 미래참조(look-ahead) 차단 |

---

## 1. As-Is 진단

### 1.1 현행 5-Factor 모델의 구조적 결함

| ID | 결함 | 근거 | 영향 |
| :-- | :-- | :-- | :-- |
| D1 | **상수 점수 잔존** | Valuation 최소 10 + Scale 최소 12 + Floor 최소 7 = 29점이 모든 매물에 공통 부여 | 실효 판별 구간이 100점이 아닌 약 71점 폭 |
| D2 | **Scale/Floor 팩터의 판별력 부재** | Scale: 15 or 12 (스프레드 3), Floor: 10 or 7 (스프레드 3) | 배점 25점을 차지하나 실제 순위 기여는 6점 |
| D3 | **스코어링 단위 혼재** | `properties` 1행 = 개별 호가이나 `change_1m/3m/6m`, `high_price`는 단지·평형 속성 | 동일 단지 매물이 동일 모멘텀 점수를 중복 수령 → 상위 랭킹 단지 편중 |
| D4 | **하락률의 베타/알파 미분리** | `drop_rate` = 단지 자체 하락률 | 시장 전체 하락분을 개별 매력도로 오인 |
| D5 | **전고점의 이상치 취약성** | `high_price` = 실거래 단일 최대값 | 직거래·특수거래 1건이 하락률을 인위적으로 부풀림 |
| D6 | **입지 팩터 절벽 효과** | 도보 5분(20점) / 10분(15점) / 15분(10점) 계단함수 | 도보 10분 0초 vs 10분 1초 = 5점 차 |
| D7 | **절대 점수의 비교 불가능성** | 지역·평형 무관 동일 척도 | 반포 84점과 개포 84점의 의미가 다름 |
| D8 | **밸류 트랩 미방어** | 하락률이 높을수록 무조건 고득점 | 펀더멘털 악화 단지가 상위 랭크 |
| D9 | **가격 데이터 성격 혼용** | `high_price`(실거래)와 `asking_price`(호가)를 직접 비율 계산 | 실거래-호가 갭이 하락률에 오염 |
| D10 | **유니버스 협소** | 반포동 63 + 개포동 24 = 87단지 | 비교군 통계 산출 불가 수준 |

### 1.2 D9 상세 — 반드시 인지할 것
현행 `drop_rate = 1 - asking_price / high_price` 는 **실거래가와 호가를 혼합한 비율**이다.
호가는 통상 직전 실거래 대비 상방 편향(seller's ask premium)이 있으므로, 이 비율은 순수 가격 하락분이 아니라 `실제 하락분 - 호가 프리미엄`이다. 시장 국면에 따라 호가 프리미엄이 변동하므로 시계열 비교가 성립하지 않는다.

**v2에서는 실거래 기준선(L1)과 호가 괴리(L2)를 분리한다.**

---

## 2. To-Be 설계 원칙

| P1 | **절대 점수 → 비교군 내 상대 점수** | 모든 팩터를 peer group 내 robust z-score로 변환 |
| :-- | :-- | :-- |
| P2 | **개별 가점 → 블록 가중합** | 팩터를 4개 블록으로 묶고 블록 단위 가중치 적용. 팩터별 IC 측정 가능 구조 |
| P3 | **스코어링 단위 2계층 분리** | L1(단지×평형, 실거래 기반) / L2(개별 호가, 괴리율) |
| P4 | **리스크·품질은 게이트** | 감점이 아닌 제외 또는 곱셈 승수 |
| P5 | **점수는 결과, evidence는 근거** | 모든 점수에 팩터별 기여 내역 JSON을 동반 저장 |
| P6 | **저장과 조회 분리** | 계산 결과 스냅샷 테이블 적재, 조회 계층은 읽기 전용 |

---

## 3. 스코어링 단위 재정의

### 3.1 2계층 구조

| 계층 | 단위 키 | 산출물 | 데이터 원천 | 통계 처리 |
| :-- | :-- | :-- | :-- | :-- |
| **L1 시장 점수** | `complex_code × area_type` | `market_score` (0~100) | 국토부 실거래 + 카카오 + 단지 마스터 | 비교군 z-score |
| **L2 매물 괴리** | `property_id` | `deal_gap_pct` (%) | 네이버 호가 | 통계 없음, 직접 계산 |

### 3.2 왜 분리하는가
- L1은 단지·평형당 실거래 수십 건을 근거로 하므로 통계적 처리가 가능하다.
- L2는 개별 호가 1건이므로 z-score를 계산할 표본이 없다. **점수화하지 말고 괴리율(%) 그대로 노출한다.**

### 3.3 최종 화면 표현
단일 랭킹이 아니라 **2차원**으로 제시한다.

```
Y축: L1 market_score (이 단지·평형이 매력적인가)
X축: L2 deal_gap_pct (이 매물이 그 단지 안에서 싼가)

→ 우상단(고득점 + 고괴리)이 우선 임장 대상
```

### 3.4 area_type 정의 (⚠️ 최우선 검증 항목)

**현행 `area_pyeong` 값(20PY/30PY/40PY)은 네이버 기준 공급면적 추정치이나, 국토부 API는 전용면적(㎡)만 제공한다. 이 매핑을 틀리면 전체 지표가 조용히 오염된다.**

`area_type`은 **전용면적(㎡) 기준**으로 재정의하고, 네이버 데이터는 이 기준으로 재매핑한다.

| area_type | 전용면적 범위(㎡) | 통칭 | 비고 |
| :-- | :-- | :-- | :-- |
| `A40` | 33.0 ≤ x < 50.0 | 소형 | 향후 확장용 |
| `A59` | 50.0 ≤ x < 70.0 | 20평형대 | 구 `20PY` |
| `A84` | 70.0 ≤ x < 100.0 | 30평형대 | 구 `30PY` |
| `A114` | 100.0 ≤ x < 135.0 | 40평형대 | 구 `40PY` |
| `A135P` | 135.0 ≤ x | 대형 | 향후 확장용 |

**구현 요구사항**
- `common/area_mapper.py::to_area_type(exclusive_area_m2: float) -> str | None`
- 범위 밖 값은 `None` 반환 → 해당 행은 스코어링 유니버스에서 제외 (C5)
- 네이버 매물의 전용면적을 확보할 수 없는 경우, 해당 매물은 **L2에서만 사용하고 L1 집계에는 투입하지 않는다.**
- 마이그레이션 시 기존 `area_pyeong` 컬럼은 보존하고 `area_type` 컬럼을 신설한다.

---

## 4. 데이터 소스 정의

### 4.1 신규: 국토부 실거래가 API (공공데이터포털)

| 항목 | 매매 | 전월세 |
| :-- | :-- | :-- |
| 요청 URL | `http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev` | `http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent` |
| 필수 파라미터 | `serviceKey`, `LAWD_CD`(법정동코드 앞 5자리), `DEAL_YMD`(YYYYMM) | 동일 |
| 페이징 | `pageNo`, `numOfRows` | 동일 |
| 개발계정 트래픽 | 10,000건/일 | 동일 |
| 본 프로젝트 `LAWD_CD` | `11650`(서초), `11680`(강남) 2개 | 동일 |

**수집 부하 추정**: 대상이 2개 시군구뿐이므로 60개월 소급 시 기본 호출은 2 × 60 = 120회, 페이징 포함 수백 회 수준이다. 일 쿼터 10,000건 대비 여유가 커서 **전체 백필을 1일 내에 완료할 수 있다.** 이후 증분 수집은 최근 2~3개월분만 재조회하면 되므로 월 수십 회다.

**국토부가 대체할 수 없는 것 (네이버 존치 사유)**
국토부 API는 **체결된 계약만** 제공하며 호가·매물 정보가 없다. 따라서 네이버는 제거되지 않고 역할이 축소된다.

| 데이터 | 국토부 | 네이버 | v2에서의 채택 |
| :-- | :--: | :--: | :-- |
| 매매 실거래 | 원천 | 재가공 | **국토부** (해제·직거래 플래그가 살아있음) |
| 전월세 실거래 | 원천 | 일부 | **국토부** |
| 현재 호가 | ✕ | ○ | **네이버** |
| 매물 건수 | ✕ | ○ | **네이버** |
| 단지 마스터(세대수·용적률) | ✕ | ○ | **네이버** |

> 네이버가 화면에 노출하는 실거래가는 국토부 데이터를 재가공한 것이다. 원천을 직접 받으면 네이버가 걸러낸 **해제여부·거래유형 플래그를 복원**할 수 있으며, 이것이 §1.1 D5(전고점 이상치 취약성)의 직접적 해법이다.
>
> 부수 효과로 네이버 호출량이 실거래 이력 조회분만큼 감소하여 **429 차단 노출면이 줄어든다.** Phase 4에서 `curl_cffi`로 대응한 문제의 부담이 경감된다.

**구현 주의사항**
1. `serviceKey`는 Encoding/Decoding 두 종류가 발급된다. `requests`의 `params=` 로 전달할 경우 **Decoding 키**를 쓰고, URL에 직접 붙일 경우 Encoding 키를 쓴다. 이중 인코딩 오류가 잦은 지점이다.
2. HTTPS 호출 시 SSL 오류가 보고된 사례가 있으므로 실패 시 HTTP 폴백을 허용한다.
3. **활용신청 승인에 최대 24시간이 소요**되므로 Phase 1 착수 시점에 즉시 신청한다.
4. 응답은 XML. 에러 시에도 HTTP 200에 에러 코드가 body에 담기는 경우가 있으므로 `resultCode` 검증을 필수화한다.
5. 최신 스펙은 구현 직전 공공데이터포털 Swagger UI에서 재확인한다.

**수집 대상 필드 (매매 상세)**

| 원본 필드(예상) | 저장 컬럼 | 용도 |
| :-- | :-- | :-- |
| 아파트명 | `apt_name_raw` | 단지 매칭 키 |
| 법정동 / 지역코드 / 지번 | `umd_nm`, `sgg_cd`, `jibun` | 단지 매칭 키 |
| 전용면적 | `exclusive_area` | `area_type` 산출 |
| 거래금액 | `deal_amount` | 가격 |
| 년/월/일 | `deal_date` | 시계열 |
| 층 | `floor` | 층 조정계수 추정 |
| 건축년도 | `build_year` | 연식, 매칭 보조키 |
| 해제여부 / 해제사유발생일 | `is_cancelled` | **제외 필터** |
| 거래유형(중개/직거래) | `deal_type` | **특수거래 비율 산출** |

> 필드명은 API 버전에 따라 상이할 수 있다. **응답 스키마를 코드에 하드코딩하지 말고 `oci/crawler/molit_schema.py`에 매핑 딕셔너리로 분리**한다.

**수집 대상 필드 (전월세)**: 보증금, 월세금액, 전용면적, 계약년월, 계약구분(신규/갱신), 계약기간

### 4.1.1 수집 경로 이원화 (CSV 백필 + API 증분)

**국토부 실거래 데이터는 두 개의 독립된 경로로 제공되며, 용도가 다르다. 양쪽을 모두 구현한다.**

| | 경로 A: 파일 다운로드 | 경로 B: 오픈 API |
| :-- | :-- | :-- |
| 제공처 | 실거래가공개시스템 `rt.molit.go.kr` (자료제공 메뉴) | 공공데이터포털 `apis.data.go.kr` |
| 인증 | 불필요 | `serviceKey` 필요 |
| 형식 | CSV / XLSX (한글 헤더) | XML |
| 소급 범위 | 2006년~ | 2006년~ |
| 조회 단위 | 시도·시군구·기간 범위 일괄 | 시군구 × 단일 계약년월 |
| **주 용도** | **60개월 백필 (1회성 대용량)** | **월 단위 증분 갱신 (정기)** |
| 자동화 | 어려움 (수동 다운로드) | 용이 |

> **두 시스템은 별개다.** 공공데이터포털 점검 중에도 `rt.molit.go.kr` 다운로드는 정상 동작한다. 반대로 API 키 발급은 포털에 종속된다.

#### 정규화 계층 요구사항 (필수)
CSV와 API는 **필드명·인코딩·값 포맷이 모두 다르다.** 두 경로가 동일한 내부 스키마를 산출하도록 어댑터를 분리한다.

```
molit_csv_loader.py  ─┐
                      ├─→ molit_schema.py::to_canonical() ─→ trades_sale / trades_rent
molit_client.py      ─┘
```

**`to_canonical()` 계약**
- 입력: 원본 dict (CSV 행 또는 API 노드)
- 출력: `CanonicalTrade` (frozen dataclass)
- 필수 정규화: 거래금액 콤마 제거 → int(만원), 년/월/일 → `YYYY-MM-DD`, 전용면적 → float
- **필드 매핑은 딕셔너리로 분리한다. 조건문으로 분기하지 않는다.** (C1)

**CSV 파싱 시 알려진 함정**
| 항목 | 대응 |
| :-- | :-- |
| 인코딩 | CP949(EUC-KR) 가능성이 높다. UTF-8 실패 시 폴백. 자동 감지 금지, 명시적 시도 순서 지정 |
| 헤더 앞 안내문 | 실제 헤더 행 전에 안내 문구 행이 존재한다. 고정 skiprows 대신 **헤더 키워드 탐색**으로 시작 행을 찾는다 |
| 거래금액 | `"450,000"` 형태 문자열. 콤마 제거 후 int 변환 |
| 결측 표기 | 빈 문자열/`-`/공백 혼재 가능. 명시적 결측 처리 |

#### ⚠️ 다운로드 직후 검증할 컬럼 (설계 영향)
아래 두 컬럼이 CSV에 존재하는지 **최초 샘플 다운로드 시 즉시 확인한다.**

| 컬럼 | 의존 로직 | 부재 시 영향 |
| :-- | :-- | :-- |
| 해제사유발생일 / 해제여부 | §7.3 Step 1 유효거래 필터 | 취소 거래가 전고점에 혼입 → D5 재발 |
| 거래유형 (중개/직거래) | 게이트 `G2` 특수거래 비중 | G2 판정 불가 |

**부재 시 대응 (폴백 설계)**: 백필은 CSV로 수행하되, **최근 12개월분만 API로 재수집하여 플래그를 덮어쓴다.** 게이트 G1·G2는 최근 12개월만 참조하므로 이것으로 충분하다. 전고점 탐지(60개월 소급)는 플래그 없이 p90 윈도우 방식만으로도 이상치 내성이 상당 부분 확보된다.

#### 원본 파일 아카이빙 (필수)
다운로드한 CSV 원본을 **날짜별 디렉토리에 무변경 보관**한다.

```
data/raw/molit/
  2026-07-29/
    apt_trade_11650_200601-202607.csv
    apt_trade_11680_200601-202607.csv
  2026-08-31/
    ...
```

**목적은 백업이 아니라 Point-In-Time 복원이다.** 실거래가공개시스템은 신고 변경·해제가 실시간 반영되므로, 동일 기간을 다른 날 받으면 내용이 달라진다. 따라서 각 원본 파일은 **"해당 다운로드 시점에 공개되어 있던 거래 집합"** 이라는 확정된 스냅샷이다. 이를 축적하면 과거 데이터에 없던 `ingested_at`을 사후 복원할 수 있으며, §16.1의 미래참조 근사 처리를 실측으로 대체할 수 있다.

- `trades_sale`에 `source_snapshot_date` 컬럼을 추가한다.
- 동일 `trade_id`가 이후 스냅샷에서 사라지면 해제된 거래이므로 `is_cancelled=1`로 갱신한다(원본 행은 삭제하지 않는다).

#### ✅ CSV 컬럼 명세 (2026-07-29 실물 확인 완료)

실제 헤더 20개 컬럼:
```
NO | 시군구 | 번지 | 본번 | 부번 | 단지명 | 전용면적(㎡) | 계약년월 | 계약일 |
거래금액(만원) | 동 | 층 | 매수자 | 매도자 | 건축년도 | 도로명 |
해제사유발생일 | 거래유형 | 중개사소재지 | 등기일자
```

| CSV 컬럼 | → `CanonicalTrade` | 변환 규칙 | 비고 |
| :-- | :-- | :-- | :-- |
| 시군구 | `sgg_cd`, `umd_nm` | **문자열 파싱 필요** (§4.1.2) | `"서울특별시 서초구 방배동"` |
| 번지 / 본번 / 부번 | `jibun`, `bonbun`, `bubun` | 정수 변환, 부번 0 허용 | **단지 매칭 주 키** (§5) |
| 단지명 | `apt_name_raw` | 원문 보존 | 매칭 보조 키 |
| 전용면적(㎡) | `exclusive_area` | float | `84.93` — API와 동일 기준 |
| 계약년월 + 계약일 | `deal_date` | `202607` + `16` → `2026-07-16` | 2개 컬럼 결합 |
| 거래금액(만원) | `deal_amount` | 콤마 제거 → int | `"184,000"` → `184000` |
| 동 | `building_dong` | `-` → NULL | **등기 완료 건만 공개** |
| 층 | `floor` | int | |
| 매수자 / 매도자 | `buyer_type`, `seller_type` | 원문 | 개인/법인 등. 저장만, 팩터화 보류 |
| 건축년도 | `build_year` | int | |
| 도로명 | `road_name` | 원문 | 매칭 보조 키 |
| 해제사유발생일 | `cancel_date`, `is_cancelled` | `-` → NULL, 값 존재 시 `is_cancelled=1` | **G2 / 유효거래 필터** |
| 거래유형 | `deal_type` | `중개거래` \| `직거래` | **G2 특수거래 비중** |
| 중개사소재지 | `agent_region` | `-` → NULL | 직거래는 항상 NULL |
| 등기일자 | `registry_date` | `YY.MM.DD` → `YYYY-MM-DD`, `-` → NULL | **G2b 미등기 경과 (§9.1)** |

> **P1-AC2b 해결**: `해제사유발생일`, `거래유형`이 모두 존재하므로 §4.1.1의 폴백(최근 12개월 API 재수집)은 **불필요하다.** CSV 단독으로 유효거래 필터와 G2 게이트가 완전히 작동한다.

#### 4.1.2 시군구 문자열 파싱

CSV는 지역을 코드가 아닌 **한글 문자열 단일 필드**로 제공한다. API(숫자 코드)와의 가장 큰 형식 차이다.

```
"서울특별시 서초구 방배동"  →  sido="서울특별시", sgg_nm="서초구", umd_nm="방배동"
                            →  sgg_cd="11650"  (매핑 테이블 조회)
```

**구현 요구사항**
- `config/lawd_codes.yaml`에 대상 2개 구의 법정동 코드표를 사전 등록한다. 행정표준코드관리시스템에서 1회 확보.
- 공백 분리 후 마지막 토큰을 `umd_nm`, 그 앞을 `sgg_nm`으로 취한다. **단, 세종시 등 2토큰 구조가 존재하므로 토큰 수 가정을 하드코딩하지 않는다.** 본 프로젝트는 서울 한정이므로 3토큰이나, 파서는 매핑 테이블 역조회를 우선한다.
- 매핑 테이블에 없는 지역명은 **예외를 발생시킨다.** 조용히 NULL 처리 금지 (C5).

#### ⚠️ 직거래 비중 재검토 필요
초기 샘플(서초구 2026-07, 5건)에서 직거래가 1건(20%) 관측되었다. 표본이 작아 일반화할 수 없으나, **게이트 임계값 `max_special_deal_ratio = 0.30`이 강남권 실제 분포에 적합한지 백필 완료 후 재산정한다.** 산정 근거: 단지·평형별 직거래 비중 분포의 상위 10~20% 지점.

### 4.2 기존 소스 역할 재정의

| 소스 | v1 역할 | v2 역할 |
| :-- | :-- | :-- |
| 네이버 부동산 | 실거래 + 호가 + 시세변동률 전부 | **호가(L2)와 매물 수 스냅샷 전용** |
| 카카오 로컬 API | 지하철 도보거리 | 유지 + 초등학교 거리 추가 |
| 국토부 API | — | **L1 가격·거래량·전세가율 기준선** |

### 4.3 외부 수동 데이터 (Phase 2)

| 데이터 | 출처 | 갱신 주기 | 저장 |
| :-- | :-- | :-- | :-- |
| 시군구별 입주물량 | 부동산지인/아실 수기 수집 | 분기 | `data/manual/supply_schedule.csv` |
| 미분양 세대수 | 국토교통 통계누리 | 월 | `data/manual/unsold_units.csv` |

> 자동화하지 말 것. 수기 CSV + 스키마 검증만으로 충분하며, 크롤링 시 유지보수 부담이 수집 가치를 초과한다.

---

## 5. 단지 키 매칭 (지번 기반 — 2026-07-29 개정)

### 5.1 문제 (완화됨)
- 네이버: `complex_code` (예: `104721`)
- 국토부: `시군구 문자열 + 본번 + 부번 + 도로명 + 단지명 + 건축년도`

당초 단지명 문자열만으로 매칭해야 할 것으로 가정했으나, **CSV 실물 확인 결과 지번(본번/부번)과 도로명이 모두 제공된다.** 단지명은 표기 흔들림이 크지만(`방배대성유니드아파트` / `대성유니드` / `방배 대성유니드`) 지번과 도로명은 고정값이므로 매칭 난이도가 크게 낮아졌다.

### 5.2 매칭 전략 (4단계, 정확도 순)

```
Tier 1. 지번 완전일치                    [주 경로]
  key = (sgg_cd, umd_nm, bonbun, bubun)
  → confidence 1.00, method 'JIBUN'

Tier 2. 도로명 정규화 일치               [보조]
  normalize_road(도로명) 완전일치 + build_year 일치
  → confidence 0.95, method 'ROAD'

Tier 3. 단지명 정규화 + 건축년도          [폴백]
  normalize(name) = 공백/괄호/특수문자 제거
                    + "아파트" 접미사 제거 + NFC 정규화
  key = (sgg_cd, umd_nm, normalize(name), build_year)
  → confidence 0.90, method 'NAME'

Tier 4. 유사도 매칭                      [잔여]
  동일 (sgg_cd, umd_nm, build_year) 내 Levenshtein ratio >= 0.85
  → confidence = ratio, method 'FUZZY'

Tier 5. 수동 확정
  → confidence 1.00, method 'MANUAL'
```

**교차 검증 필수**: Tier 1으로 매칭된 건이라도 `build_year`가 불일치하면 경고 로그를 남기고 `status='PENDING'`으로 보류한다. 지번 재개발로 신·구 단지가 같은 지번을 쓰는 경우가 있다.

### 5.3 다대일(N:1) 관계 처리

**하나의 단지가 여러 지번에 걸쳐 있는 경우가 흔하다** (대단지, 재건축 통합 단지). 따라서 `complex_key_map`은 **국토부 키 1행 → `complex_code` 1개**의 N:1 매핑이다.

```sql
-- UNIQUE 제약 변경 (기존 apt_name 기반 → 지번 기반)
CREATE TABLE IF NOT EXISTS complex_key_map (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    complex_code    TEXT,
    sgg_cd          TEXT NOT NULL,
    umd_nm          TEXT NOT NULL,
    bonbun          INTEGER,
    bubun           INTEGER,
    road_name       TEXT,
    apt_name_raw    TEXT NOT NULL,
    apt_name_norm   TEXT NOT NULL,
    build_year      INTEGER,
    confidence      REAL NOT NULL DEFAULT 0.0,
    match_method    TEXT NOT NULL,   -- JIBUN | ROAD | NAME | FUZZY | MANUAL | UNMATCHED
    status          TEXT NOT NULL,   -- CONFIRMED | PENDING | UNMATCHED
    reviewed_at     TEXT,
    UNIQUE(sgg_cd, umd_nm, bonbun, bubun, apt_name_norm)
);
```

> `apt_name_norm`을 UNIQUE에 포함하는 이유: 동일 지번에 `○○1단지` / `○○2단지`가 공존할 수 있다.

### 5.4 네이버 측 선행 조건 (⚠️ Q2와 함께 확인)
Tier 1/2가 작동하려면 **네이버 단지 정보에 지번 또는 도로명 주소가 포함되어야 한다.** 크롤러 응답 필드를 확인하여 `complexes` 테이블에 아래를 적재한다.

```sql
ALTER TABLE complexes ADD COLUMN bonbun    INTEGER;
ALTER TABLE complexes ADD COLUMN bubun     INTEGER;
ALTER TABLE complexes ADD COLUMN road_name TEXT;
```
둘 다 없으면 Tier 3부터 시작하며, 이 경우 당초 예상대로 수동 검수 부담이 발생한다.

### 5.5 게이트
`confidence < 0.85` 또는 `status != 'CONFIRMED'` 인 단지는 **L1 스코어링 유니버스에서 제외**한다. (C5, 게이트 G3)

### 5.6 산출물
- `pc/tools/match_review.py`: 미매칭 목록 출력 + 후보 제시 + 수동 확정 CLI
- **예상 수동 검수 분량**: 지번 매칭 가용 시 전체의 5% 미만. 불가 시 15~20%.

---

## 6. DB 스키마 설계

### 6.1 신규 테이블

```sql
-- ── 단지 마스터 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS complexes (
    complex_code      TEXT PRIMARY KEY,       -- 네이버 단지코드
    complex_name      TEXT NOT NULL,
    sgg_cd            TEXT NOT NULL,          -- 시군구코드 5자리
    umd_cd            TEXT,                   -- 법정동코드 10자리
    region_name       TEXT,
    build_year        INTEGER,
    total_households  INTEGER,
    total_dongs       INTEGER,
    floor_area_ratio  REAL,                   -- 용적률(%)
    building_coverage REAL,                   -- 건폐율(%)
    brand             TEXT,
    lat               REAL,
    lng               REAL,
    subway_dist_m     REAL,                   -- 최근접 지하철역 도보거리(m)
    subway_name       TEXT,
    subway_walk_min   REAL,
    elem_school_dist_m REAL,
    cbd_transit_min   REAL,                   -- 강남/여의도/시청 최소 대중교통 소요(분)
    updated_at        TEXT NOT NULL
);

-- ── 단지 키 매핑 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS complex_key_map (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    complex_code    TEXT,                     -- NULL 가능 (UNMATCHED)
    sgg_cd          TEXT NOT NULL,
    umd_nm          TEXT NOT NULL,
    apt_name_raw    TEXT NOT NULL,
    apt_name_norm   TEXT NOT NULL,
    jibun           TEXT,
    build_year      INTEGER,
    confidence      REAL NOT NULL DEFAULT 0.0,
    match_method    TEXT NOT NULL,            -- EXACT | FUZZY | MANUAL | UNMATCHED
    status          TEXT NOT NULL,            -- CONFIRMED | PENDING | UNMATCHED
    reviewed_at     TEXT,
    UNIQUE(sgg_cd, apt_name_norm, build_year)
);

-- ── 국토부 매매 실거래 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades_sale (
    trade_id        TEXT PRIMARY KEY,         -- 해시(sgg|본번|부번|apt|area|date|floor|amount)
    complex_code    TEXT,                     -- 매핑 결과, NULL 가능
    sgg_cd          TEXT NOT NULL,
    umd_nm          TEXT,
    bonbun          INTEGER,
    bubun           INTEGER,
    road_name       TEXT,
    apt_name_raw    TEXT NOT NULL,
    exclusive_area  REAL NOT NULL,
    area_type       TEXT,                     -- A59 | A84 | ...
    deal_date       TEXT NOT NULL,            -- YYYY-MM-DD
    deal_amount     INTEGER NOT NULL,         -- 만원 단위
    building_dong   TEXT,                     -- 등기 완료 건만 공개, 대부분 NULL
    floor           INTEGER,
    buyer_type      TEXT,                     -- 개인 | 법인 | 공공기관 등
    seller_type     TEXT,
    build_year      INTEGER,
    is_cancelled    INTEGER NOT NULL DEFAULT 0,
    cancel_date     TEXT,
    deal_type       TEXT,                     -- 중개거래 | 직거래
    agent_region    TEXT,
    registry_date   TEXT,                     -- 등기일자, NULL = 미등기
    source          TEXT NOT NULL,            -- CSV | API
    source_snapshot_date TEXT,                -- CSV 원본 다운로드일 (PIT 복원용)
    first_seen_date TEXT,                     -- 최초 관측 스냅샷일
    last_seen_date  TEXT,                     -- 최종 관측 스냅샷일 (해제 판정용)
    ingested_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_sale_key
    ON trades_sale(complex_code, area_type, deal_date);

-- ── 국토부 전월세 실거래 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS trades_rent (
    rent_id         TEXT PRIMARY KEY,
    complex_code    TEXT,
    sgg_cd          TEXT NOT NULL,
    apt_name_raw    TEXT NOT NULL,
    exclusive_area  REAL NOT NULL,
    area_type       TEXT,
    deal_date       TEXT NOT NULL,
    deposit         INTEGER NOT NULL,         -- 만원
    monthly_rent    INTEGER NOT NULL DEFAULT 0,
    floor           INTEGER,
    contract_type   TEXT,                     -- 신규 | 갱신
    ingested_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_rent_key
    ON trades_rent(complex_code, area_type, deal_date);

-- ── 매물 수 스냅샷 (Flow 팩터용, 시계열 누적) ──────────────
CREATE TABLE IF NOT EXISTS listing_snapshots (
    snapshot_date   TEXT NOT NULL,
    complex_code    TEXT NOT NULL,
    area_type       TEXT NOT NULL,
    listing_count   INTEGER NOT NULL,
    min_ask_price   INTEGER,
    median_ask_price INTEGER,
    PRIMARY KEY (snapshot_date, complex_code, area_type)
);

-- ── L1 집계 지표 (팩터 원천값) ─────────────────────────────
CREATE TABLE IF NOT EXISTS complex_area_stats (
    base_date            TEXT NOT NULL,
    complex_code         TEXT NOT NULL,
    area_type            TEXT NOT NULL,
    -- Value
    median_price_3m      REAL,
    peak_price_raw       REAL,
    peak_price_adj       REAL,
    peak_date            TEXT,
    drop_rate            REAL,
    excess_drop_rate     REAL,
    jeonse_ratio         REAL,
    price_per_pyeong     REAL,
    rent_yield           REAL,
    -- Flow
    trade_count_3m       INTEGER,
    trade_count_12m      INTEGER,
    volume_ratio         REAL,
    listing_delta_30d    REAL,
    momentum_3m          REAL,
    supply_pressure      REAL,
    -- Quality
    households_log       REAL,
    age_years            REAL,
    far_score            REAL,
    -- Data quality
    special_deal_ratio   REAL,
    sample_count_12m     INTEGER,
    computed_at          TEXT NOT NULL,
    PRIMARY KEY (base_date, complex_code, area_type)
);

-- ── 스코어 스냅샷 (조회 전용) ──────────────────────────────
CREATE TABLE IF NOT EXISTS market_scores (
    run_id           TEXT NOT NULL,
    base_date        TEXT NOT NULL,
    complex_code     TEXT NOT NULL,
    area_type        TEXT NOT NULL,
    peer_group_key   TEXT NOT NULL,
    peer_group_n     INTEGER NOT NULL,
    block_value      REAL,
    block_flow       REAL,
    block_location   REAL,
    block_quality    REAL,
    raw_score        REAL,
    base_score       REAL,                    -- Φ 매핑 후 0~100
    risk_multiplier  REAL NOT NULL DEFAULT 1.0,
    market_score     REAL,                    -- 최종
    gate_status      TEXT NOT NULL,           -- PASS | EXCLUDED
    gate_reason      TEXT,
    coverage_ratio   REAL,                    -- 산출 성공 팩터 비율
    evidence_json    TEXT NOT NULL,
    PRIMARY KEY (run_id, complex_code, area_type)
);

-- ── 실행 이력 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS score_runs (
    run_id          TEXT PRIMARY KEY,
    run_at          TEXT NOT NULL,
    base_date       TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    scorer_version  TEXT NOT NULL,            -- v1 | v2
    universe_total  INTEGER NOT NULL,
    universe_passed INTEGER NOT NULL,
    excluded_count  INTEGER NOT NULL,
    duration_sec    REAL
);

-- ── 지역 통계 (초과하락률 기준선) ──────────────────────────
CREATE TABLE IF NOT EXISTS region_stats (
    base_date       TEXT NOT NULL,
    sgg_cd          TEXT NOT NULL,
    area_type       TEXT NOT NULL,
    median_drop_rate REAL,
    median_ppp      REAL,
    median_jeonse_ratio REAL,
    sample_n        INTEGER NOT NULL,
    supply_ratio    REAL,
    unsold_delta_3m REAL,
    PRIMARY KEY (base_date, sgg_cd, area_type)
);
```

### 6.2 기존 테이블 변경

```sql
-- properties: L2 전용으로 역할 축소 + 컬럼 추가
ALTER TABLE properties ADD COLUMN area_type       TEXT;
ALTER TABLE properties ADD COLUMN exclusive_area  REAL;
ALTER TABLE properties ADD COLUMN deal_gap_pct    REAL;
ALTER TABLE properties ADD COLUMN floor_grade     TEXT;   -- LOW | MID | HIGH
ALTER TABLE properties ADD COLUMN score_v1        REAL;   -- 기존 점수 보존
ALTER TABLE properties ADD COLUMN last_seen_at    TEXT;
```

> `change_1m/3m/6m`, `high_price`, `drop_rate` 컬럼은 **삭제하지 않되 v2 스코어링에서 사용하지 않는다.** v1 병행 운영에 필요하다. (C6)

### 6.3 마이그레이션
현행 `common/database.py::init_db()`의 자동 마이그레이션 로직을 확장하되, **버전 테이블을 도입**한다.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT
);
```
`common/migrations/` 디렉토리에 `001_xxx.sql` 형태로 순차 적용. 멱등성 보장 필수.

---

## 7. 팩터 명세

### 7.1 블록 및 가중치 (초기값)

| 블록 | 가중치 | 팩터 수 | 최소 커버리지 |
| :-- | :--: | :--: | :--: |
| A. Value (가치) | 0.35 | 4 | 2개 |
| B. Flow (수급·흐름) | 0.25 | 4 | 2개 |
| C. Location (입지) | 0.20 | 3 | 2개 |
| D. Quality (자산품질) | 0.20 | 4 | 2개 |

### 7.2 Block A — Value (가중치 0.35)

| 팩터 ID | 명칭 | 계산식 | 방향 | 블록내 가중 | 비교군 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: | :--: |
| `A1` | 초과하락률 | 7.3 참조 | + | 0.45 | BELT | 1 |
| `A2` | 전세가율 | `median_jeonse_deposit_6m / median_price_3m` | + | 0.32 | BELT | 2 |
| `A3` | 상대 평단가 | `price_per_pyeong / peer_median_ppp` | − | 0.10 | SGG | 1 |
| `A4` | 환산 임대수익률 | `(monthly_rent×12 + (deposit×전환율)) / price` | + | 0.13 | SGG | 2 |

> `A3`는 §8.1.1의 경고에 따라 잠정 가중치 0.10으로 시작한다. 강남/서초 통합 유니버스에서 평단가가 낮은 것은 저평가가 아니라 입지 열위일 가능성이 높다. Phase 3 IC 측정 후 존치 여부를 결정한다.

**A2가 v1 대비 가장 큰 정보 증분이다.** 하락률만으로는 하락의 원인을 알 수 없으나, 매매가가 하락하는 동안 전세가율이 상승했다면 실수요는 유지된 채 투자수요만 이탈한 것이고, 전세가율까지 동반 하락했다면 지역 자체의 약화다. 완전히 다른 국면이며 대응도 반대다.

### 7.3 A1 초과하락률 — 상세 명세

현행 `drop_rate`를 4단계로 재정의한다. **v2 개선분의 가장 큰 비중을 차지하는 항목이다.**

**Step 1. 유효 거래 필터**
```
유효거래 = trades_sale WHERE
    is_cancelled = 0
    AND deal_type != '직거래'
    AND complex_code IS NOT NULL
    AND area_type IS NOT NULL
    AND NOT (registry_date IS NULL
             AND julianday(base_date) - julianday(deal_date) > 180)   -- §9.1.1
```

**Step 2. Robust 전고점**
단일 최대값 대신 롤링 윈도우 상위 분위수를 사용한다.
```
for each rolling 3-month window w in [base_date - 60M, base_date]:
    if count(유효거래 in w) >= MIN_WINDOW_TRADES(=2):
        p90[w] = percentile(deal_amount in w, 90)

peak_price_raw = max(p90)
peak_date      = argmax(p90)
```
> 윈도우 내 거래 2건 미만이면 해당 윈도우를 건너뛴다. 1건짜리 고가 거래가 전고점이 되는 것을 막는다.

**Step 3. 시간 감쇠**
2021년 고점과 2025년 고점은 동일한 기준선이 아니다.
```
months_elapsed = (base_date - peak_date) in months
decay = DECAY_FLOOR + (1 - DECAY_FLOOR) × exp(-months_elapsed / DECAY_TAU)

peak_price_adj = peak_price_raw × decay

# config 기본값
DECAY_TAU   = 36.0    # 반감 스케일(개월)
DECAY_FLOOR = 0.80    # 감쇠 하한
```

**Step 4. 초과하락률**
```
drop_rate = 1 - (median_price_3m / peak_price_adj)

excess_drop_rate = drop_rate - belt_stats.median_drop_rate
                   (강남벨트 2구 통합, 동일 area_type)
```

> **기준선을 시군구가 아니라 벨트(2구 통합)로 잡는 이유는 §8.1.2를 따른다.** 구별 중위 하락률로 정규화하면 "서초구가 강남구보다 더 빠졌는가"가 소거되는데, 이 사용자의 의사결정에는 구 선택이 포함되어 있다. 구별 중위값은 `region_stats`에 병행 저장하여 UI(§14.6)에서 참고 지표로만 노출한다.

**시장 전체가 20% 하락했는데 이 단지도 20% 하락한 것은 신호가 아니라 베타다.** 시장 요인을 제거한 잔차만을 팩터로 사용한다. 주식 퀀트의 residual momentum과 동일한 논리다.

**Step 5. 밸류 트랩 교차 조건 (알림 필터)**
초과하락률 단독으로는 매수 후보가 되지 않는다. 텔레그램 알림 대상은 아래를 모두 충족해야 한다.
```
alert_candidate =
      excess_drop_rate  >= peer_percentile_70
  AND volume_ratio      >  1.0        # 거래량 회복
  AND listing_delta_30d <  0          # 매물 감소
  AND supply_pressure   <  peer_median # 입주물량 압박 낮음
```
"싸진 것"과 "돌아서고 있는 것"이 동시에 성립할 때만 후보로 승격한다.

### 7.4 Block B — Flow (가중치 0.25)

| 팩터 ID | 명칭 | 계산식 | 방향 | 블록내 가중 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: |
| `B1` | 거래량 회복비 | `trade_count_3m / (trade_count_12m / 4)` | + | 0.30 | 2 |
| `B2` | 매물 증감률 | `(listing_now - listing_30d_ago) / listing_30d_ago` | − | 0.25 | 2* |
| `B3` | 입주물량 압박 | `향후 12M 입주세대 / 시군구 재고세대` | − | 0.25 | 2 |
| `B4` | 3개월 모멘텀 | `median_price_3m / median_price_3m_lag3 - 1` | + | 0.20 | 1 |

> *B2는 `listing_snapshots` 누적이 선행되어야 한다. 스냅샷 적재 시작 후 **최소 30일 경과 전에는 결측 처리**한다. 임의 대체 금지. (C5)

### 7.5 Block C — Location (가중치 0.20)

| 팩터 ID | 명칭 | 계산식 | 방향 | 블록내 가중 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: |
| `C1` | 역세권 감쇠 | `exp(-subway_dist_m / 400)` | + | 0.40 | 1 |
| `C2` | 업무지구 접근성 | `1 / (1 + cbd_transit_min / 30)` | + | 0.40 | 3 |
| `C3` | 초품아 | `exp(-elem_school_dist_m / 300)` | + | 0.20 | 3 |

**C1은 현행 계단함수를 연속 감쇠함수로 대체한다.** 절벽 효과(D6)가 제거된다.

```
현행:  도보 10분 이내 → 15점, 초과 → 10점  (불연속)
v2  :  exp(-d/400)                          (연속, d=400m에서 0.368)
```

`C2`는 강남역·여의도역·시청역 중 최소 대중교통 소요시간이다. 단순 최근접역 거리보다 설명력이 높다. 카카오 길찾기 계열 또는 ODsay API 사용 가능 여부를 Phase 3 착수 시 확인한다. **확보 불가 시 C1/C3 가중치를 재정규화하고 C2는 결측 처리한다.**

### 7.6 Block D — Quality (가중치 0.20)

| 팩터 ID | 명칭 | 계산식 | 방향 | 블록내 가중 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: |
| `D1` | 단지 규모 | `log(total_households)` | + | 0.30 | 1 |
| `D2` | 연식 곡선 | 아래 참조 | 역U자 | 0.30 | 1 |
| `D3` | 정비 사업성 | `1 / floor_area_ratio` (정규화) | + | 0.25 | 3 |
| `D4` | 브랜드 | 더미 (0/1) | + | 0.15 | 1 |

**D2 연식 곡선 — 선형 처리 금지**
신축 프리미엄과 재건축 기대가 양 끝에 있고, 중간 구간이 최저다.

```python
def age_score(age_years: float) -> float:
    """연식 선호도. 구간별 스플라인. config에서 노드 로드."""
    # 기본 노드 (age, score)
    #   0 → 1.00   (신축)
    #   5 → 0.85
    #  15 → 0.45
    #  25 → 0.40   (최저 구간)
    #  32 → 0.70   (재건축 기대 진입)
    #  40 → 0.95
    #  50 → 1.00
    # 노드 간 선형보간, 범위 밖은 클램프
```

**D4 브랜드 더미의 한계 인지**
현행 Scale 팩터(15점 vs 12점)와 달리 v2에서는 블록 내 가중 0.15 × 블록 가중 0.20 = **전체의 3%** 로 축소된다. 브랜드는 세대수·연식과 상관이 높아 독립적 설명력이 낮다. Phase 3에서 IC 측정 후 제거를 검토한다.

---

## 8. 정규화 및 집계 알고리즘

### 8.0 유니버스 확정 (2026-07-29 결정)

**대상 지역은 서초구(11650) + 강남구(11680) 2개 자치구로 확정한다. 이 범위를 확장하지 않는다.**

현행 `config.yaml`은 이 2개 구 중 **반포동·개포동 2개 법정동만** 활성화되어 있어 유니버스가 87단지에 그친다. Phase 1에서 확장할 대상은 자치구가 아니라 **같은 2개 구 안의 나머지 법정동 전체**다.

| 자치구 | LAWD_CD | 대상 법정동 |
| :-- | :-- | :-- |
| 서초구 | `11650` | 반포, 잠원, 서초, 방배, 양재, 우면, 내곡, 염곡, 원지, 신원 |
| 강남구 | `11680` | 역삼, 개포, 청담, 삼성, 대치, 논현, 압구정, 도곡, 일원, 수서, 세곡, 자곡, 신사, 율현 |

**구현 요구사항**
- 법정동 10자리 코드는 행정표준코드관리시스템(`www.code.go.kr`)에서 조회하여 `config/regions.yaml`에 명시한다. 코드를 추정하거나 하드코딩하지 않는다.
- 국토부 API는 5자리(`11650`, `11680`)만 사용하므로 **2개 스트림으로 전 지역 수집이 완결된다.** 60개월 소급 수집 시 페이징 포함 수백 회 호출이며, 일 쿼터 10,000건 대비 여유가 크다.
- 아파트 재고가 미미한 법정동(원지·신원·율현 등)은 수집은 하되 게이트 G1에서 자연 탈락하도록 둔다. 사전 제외 목록을 만들지 않는다.

### 8.1 비교군(Peer Group) 정의

유니버스가 2개 구로 고정되므로, 원안의 3단계 시도(市道) 폴백은 성립하지 않는다(`SIDO_AREA`와 `AREA`가 동일 집합으로 붕괴). **2단계 구조로 단순화하고, 대신 팩터별 정규화 스코프를 분리한다.**

```python
PEER_LEVELS = {
    "BELT_AREA": lambda r: (r.area_type,),               # 강남벨트(2구) × 평형
    "SGG_AREA":  lambda r: (r.sgg_cd, r.area_type),      # 시군구 × 평형
    "UMD_AREA":  lambda r: (r.umd_cd, r.area_type),      # 법정동 × 평형
}

def resolve_peer_group(target, universe, scope: str, min_n: int):
    """
    scope는 팩터별로 config에서 지정된다.
    지정 스코프에서 N < min_n 이면 한 단계 넓은 스코프로 1회만 폴백한다.
    BELT_AREA에서도 미달이면 None → gate G5 EXCLUDED.
    """
    order = ["UMD_AREA", "SGG_AREA", "BELT_AREA"]
    for level in order[order.index(scope):]:
        peers = [r for r in universe if PEER_LEVELS[level](r) == PEER_LEVELS[level](target)]
        if len(peers) >= min_n:
            return f"{level}:{key}", peers
    return None, []
```

#### 8.1.1 팩터별 정규화 스코프 (⚠️ 설계상 중요)

**모든 팩터에 동일한 비교군을 쓰면 안 된다.** 팩터의 성격에 따라 적정 스코프가 다르다.

| 팩터 유형 | 예시 | 적정 스코프 | 사유 |
| :-- | :-- | :-- | :-- |
| **변화율·비율형** | A1 초과하락, A2 전세가율, B1 거래량비, B4 모멘텀 | `BELT_AREA` | 각 단지의 자기 기준 대비 변화이므로 절대 가격 수준에 둔감. 넓은 비교군이 표본을 키워 통계 안정성만 개선 |
| **수준형** | A3 상대 평단가, A4 임대수익률 | `SGG_AREA` | 넓게 잡으면 "싼 것"과 "입지가 나쁜 것"을 구분하지 못함 |
| **입지·품질형** | C, D 블록 전체 | `BELT_AREA` | 입지 우열 자체가 신호이므로 지역 통제를 하면 안 됨 |

**A3(상대 평단가)에 대한 경고 — 실데이터로 확인됨 (2026-07-29)**
서초구+강남구를 통합 비교군으로 삼으면, 세곡동·내곡동 단지가 압구정·반포 대비 평단가가 낮다는 이유만으로 고득점을 받는다. 이는 저평가가 아니라 **입지 차이**다. 전형적인 가치 팩터 오작동이다.

CSV 샘플(서초구 2026-07, `A84` 버킷)에서 이미 관측된다.

| 단지 | 전용(㎡) | 거래금액 | 건축년도 |
| :-- | --: | --: | --: |
| 아크로리버뷰신반포 | 84.82 | 325,000 | 2018 |
| 서초래미안 | 84.95 | 284,000 | 2003 |
| 서초동 현대 | 84.33 | 249,000 | 1989 |
| 방배대성유니드 | 84.93 | 184,000 | 2003 |

**단일 자치구·단일 평형 버킷 안에서 1.77배 격차**다. 벨트 통합 시 더 확대된다. 이 분산의 대부분은 미가격오류가 아니라 입지·연식이며, D2(연식)·C1(역세권)이 이미 별도 팩터로 포착하고 있다. **A3는 중복 계상이거나 노이즈일 가능성이 높다.** Phase 3 IC 검증에서 유의하지 않으면 제거한다.

따라서 A3는 `SGG_AREA`로 좁히되, 그것으로도 완전히 해소되지 않는다(강남구 내 압구정 vs 세곡동 격차는 여전히 크다). **A3는 Phase 3 IC 측정 전까지 잠정 팩터로 취급하고, 블록 내 가중치를 0.20 → 0.10으로 낮춰 시작한다.** IC가 유의하지 않으면 제거한다.

#### 8.1.2 구(區) 선택을 소거하지 않을 것

초과하락률(A1)의 기준선을 `SGG_AREA`로 잡으면 "서초구가 강남구보다 더/덜 빠졌는가"라는 정보가 소거된다. **사용자의 의사결정 범위에 구 선택이 포함되어 있으므로, A1의 기준선은 `BELT_AREA`로 둔다.**

대신 구 간 차이를 UI에서 별도로 노출한다(§14.6 신설).

> 일반 원칙: **정규화 스코프는 의사결정 스코프와 일치시킨다.** 의사결정에 포함된 축을 정규화로 소거하면 그 축에 대한 판단 근거가 사라진다.

### 8.2 Robust z-score

```python
def robust_z(x: float, peers: list[float]) -> float | None:
    if len(peers) < MIN_PEER_N:
        return None
    med = median(peers)
    mad = median([abs(p - med) for p in peers])
    scale = 1.4826 * mad
    if scale < EPS:                      # 분산 소실
        return 0.0
    return clip((x - med) / scale, -3.0, 3.0)
```

평균/표준편차 대신 중위수/MAD를 사용하는 이유는 실거래 데이터의 이상치 내성 때문이다. 클리핑(winsorize) 범위 ±3은 config로 노출한다.

### 8.3 블록 점수 (결측 처리 포함)

```python
def block_score(factors: dict[str, float | None],
                weights: dict[str, float],
                min_coverage: int) -> tuple[float | None, float]:
    """
    반환: (블록점수, 커버리지비율)
    결측 팩터는 제외하고 남은 팩터의 가중치를 재정규화한다.
    0이나 평균값으로 대체하지 않는다. (C5)
    """
    available = {k: v for k, v in factors.items() if v is not None}
    if len(available) < min_coverage:
        return None, len(available) / len(factors)

    w_sum = sum(weights[k] for k in available)
    score = sum(available[k] * weights[k] for k in available) / w_sum
    return score, len(available) / len(factors)
```

### 8.4 최종 산식

```
# 1) 블록 가중합
Raw = Σ_b (w_b × Block_b) / Σ_b w_b        # 결측 블록 제외 후 재정규화

# 2) 유니버스 내 표준화 → 정규분포 CDF 매핑
Raw_z    = (Raw - mean(Raw_universe)) / std(Raw_universe)
BaseScore = Φ(Raw_z) × 100                 # 0~100, 중앙값 50

# 3) 리스크 승수 적용
MarketScore = BaseScore × RiskMultiplier
```

**상한 캡(`min(100, ...)`)을 쓰지 않고 CDF 매핑을 쓰는 이유**: 캡에 걸린 순간 상위권 내부의 순서 정보가 전부 소실된다. 현행 v1에서 하락률 25% 이상이면 전부 100점으로 붙는 문제가 이것이다.

**해석**: `MarketScore = 70` 은 "비교군 내 상위 30% 수준"을 의미한다. 절대적 매력도가 아니다. UI 툴팁에 반드시 명시한다.

### 8.5 리스크 승수 (곱셈 감점)

| 조건 | 승수 | Phase |
| :-- | :--: | :--: |
| 전세가율이 비교군 하위 10% (역전세 위험 구간) | × 0.80 | 2 |
| `supply_pressure` 비교군 상위 10% | × 0.70 | 2 |
| 정비사업 분쟁/소송 플래그 (수동 입력) | × 0.50 | 3 |
| 해당 없음 | × 1.00 | — |

승수는 **곱연산**이며 중복 적용된다. 하한 0.35로 클램프한다.

---

## 9. 데이터 품질 게이트

### 9.1 HARD EXCLUDE (스코어링 대상 제외)

| 게이트 ID | 조건 | `gate_reason` |
| :-- | :-- | :-- |
| `G1` | 최근 12개월 유효 실거래 < 3건 | `INSUFFICIENT_TRADES` |
| `G2` | 특수거래(직거래+해제) 비중 > 30% | `HIGH_SPECIAL_DEAL_RATIO` |
| `G2b` | 미등기 장기경과 거래 비중 > 20% | `HIGH_UNREGISTERED_RATIO` |
| `G3` | `complex_key_map.confidence < 0.85` | `KEY_MATCH_FAILED` |
| `G4` | `complexes.lat/lng` 결측 | `NO_GEOCODE` |
| `G5` | 비교군 N < `MIN_PEER_N` (전 레벨 폴백 실패) | `NO_PEER_GROUP` |
| `G6` | `area_type` 미해석 | `AREA_TYPE_UNRESOLVED` |
| `G7` | 전체 팩터 커버리지 < 0.50 | `LOW_COVERAGE` |

**제외된 단지는 삭제하지 않고 `gate_status='EXCLUDED'`로 `market_scores`에 적재한다.** UI에 별도 탭으로 노출하여 "왜 안 보이는지"를 확인할 수 있게 한다. 조용한 소실은 디버깅을 불가능하게 만든다.

### 9.1.1 G2b — 미등기 장기경과 거래 (신설)

```
미등기_장기경과 = registry_date IS NULL
                  AND (base_date - deal_date) > UNREGISTERED_GRACE_DAYS(=180)
```

`해제사유발생일`은 **이미 취소가 확정된** 거래만 포착한다. 반면 등기일자 결측은 **아직 취소되지 않았으나 신뢰도가 낮은** 거래를 포착한다. 계약 후 6개월이 지나도록 소유권 이전등기가 없는 거래는 실제 대금 지급이 이루어지지 않았을 가능성이 있으며, 과거 실거래가 조작(자전거래) 논란의 주된 판별 지표였다.

**전고점 탐지에 우선 적용한다.** §7.3 Step 2의 p90 윈도우 산출 시 미등기 장기경과 거래를 유효거래에서 제외한다. 고점을 형성한 거래가 미등기 상태로 방치되어 있다면 그 고점은 기준선으로 부적합하다.

> 단, 최근 계약(6개월 이내)은 정상적으로 등기가 진행 중일 수 있으므로 제외하지 않는다. `UNREGISTERED_GRACE_DAYS`를 config로 노출하고, 백필 후 실제 등기 소요기간 분포를 확인하여 재산정한다.

### 9.2 게이트 요약 리포트
매 실행 시 `score_runs`에 집계하고 로그로 출력한다.
```
[RUN 20260729-0930] universe=412 passed=287 excluded=125
  INSUFFICIENT_TRADES     : 68
  KEY_MATCH_FAILED        : 31
  NO_PEER_GROUP           : 18
  HIGH_SPECIAL_DEAL_RATIO :  5
  ...
```

---

## 10. L2 매물 괴리 (Deal Gap)

### 10.1 계산식

```
기준가 = complex_area_stats.median_price_3m
       × floor_adj(floor_grade)
       × dong_adj(building_dong)      # Phase 3, 기본 1.0

deal_gap_pct = (1 - asking_price / 기준가) × 100
```

### 10.2 층 조정계수 (초기 상수 → 추후 회귀 추정)

| floor_grade | 정의 | `floor_adj` (초기값) |
| :-- | :-- | :--: |
| `LOW` | 1~3층 또는 최상층 | 0.95 |
| `MID` | 4층 ~ 총층수×0.6 | 1.00 |
| `HIGH` | 총층수×0.6 초과 (최상층 제외) | 1.03 |

> Phase 3에서 `trades_sale`의 층·가격 데이터로 단지별 회귀 추정하여 상수를 대체한다. 초기값은 명시적으로 "가정"임을 `evidence_json`에 기록한다.

### 10.3 L2는 점수화하지 않는다
개별 호가는 표본 1건이므로 z-score를 계산할 근거가 없다. **`deal_gap_pct`를 % 그대로 표시**하고, 랭킹은 L1 점수로 하되 L2를 보조 축으로 병기한다.

---

## 11. 모듈 및 파일 구조

```text
property-screener/
│
├── config/
│   ├── scoring_v2.yaml              # [신규] 가중치·임계값 전량
│   └── regions.yaml                 # [신규] target_regions 확장 관리
│
├── common/
│   ├── models.py                    # [수정] 신규 테이블 스키마
│   ├── database.py                  # [수정] 버전 기반 마이그레이션
│   ├── migrations/                  # [신규] 001_*.sql ~
│   ├── area_mapper.py               # [신규] 전용면적 → area_type
│   └── peer_group.py                # [신규] 비교군 해석 + robust_z
│
├── oci/crawler/
│   ├── naver_crawler.py             # [수정] listing_snapshots 적재 추가
│   ├── molit_csv_loader.py          # [신규] rt.molit.go.kr CSV 파싱 (백필)
│   ├── molit_client.py              # [신규] 공공데이터포털 API 클라이언트 (증분)
│   ├── molit_schema.py              # [신규] CSV/API → CanonicalTrade 어댑터
│   └── molit_ingest.py              # [신규] 정규화 → DB 적재 (경로 무관 공통)
│
├── data/
│   └── raw/molit/<YYYY-MM-DD>/      # [신규] CSV 원본 아카이브 (PIT 복원용)
│
├── pc/
│   ├── keymap/
│   │   ├── matcher.py               # [신규] 3단계 단지 매칭
│   │   └── review_cli.py            # [신규] 수동 검수 CLI
│   │
│   ├── features/
│   │   ├── build_stats.py           # [신규] complex_area_stats 생성
│   │   ├── peak_detector.py         # [신규] robust 전고점 + 시간감쇠
│   │   ├── region_stats.py          # [신규] 시군구 중위값 산출
│   │   ├── factor_value.py          # [신규] Block A
│   │   ├── factor_flow.py           # [신규] Block B
│   │   ├── factor_location.py       # [신규] Block C
│   │   └── factor_quality.py        # [신규] Block D
│   │
│   ├── scoring/
│   │   ├── normalizer.py            # [신규] winsorize, robust_z, Φ 매핑
│   │   ├── gate.py                  # [신규] G1~G7 판정
│   │   ├── risk.py                  # [신규] RiskMultiplier
│   │   ├── aggregator.py            # [신규] 블록 가중합 + 결측 재정규화
│   │   ├── evidence.py              # [신규] evidence_json 빌더
│   │   └── scorer_v2.py             # [신규] 진입점
│   │
│   ├── l2/
│   │   └── deal_gap.py              # [신규] 매물 괴리율
│   │
│   ├── ml_engine/
│   │   └── scorer.py                # [유지] v1, 삭제 금지 (C6)
│   │
│   ├── backtest/
│   │   ├── pit_loader.py            # [신규] Point-In-Time 로더
│   │   ├── forward_return.py        # [신규] 12M 전방수익률
│   │   └── ic_report.py             # [신규] Spearman IC, 분위 스프레드
│   │
│   └── web_app.py                   # [수정] UI 명세 §12 반영
│
└── tests/
    ├── test_area_mapper.py
    ├── test_peak_detector.py        # 시간감쇠 · p90 윈도우
    ├── test_peer_group.py           # 폴백 3단계
    ├── test_normalizer.py           # MAD=0 엣지케이스
    ├── test_aggregator.py           # 결측 재정규화
    ├── test_gate.py                 # G1~G7 각각
    └── test_pit_loader.py           # 미래참조 차단 검증
```

### 11.1 공개 인터페이스 (C1 대상)

```python
# pc/scoring/scorer_v2.py
def run_scoring(base_date: str, config_path: str) -> ScoreRunResult:
    """
    L1 스코어링 전체 파이프라인 실행.
    market_scores / score_runs 테이블에 적재하고 요약을 반환한다.
    """

@dataclass(frozen=True)
class ScoreRunResult:
    run_id: str
    universe_total: int
    universe_passed: int
    excluded_by_reason: dict[str, int]
    duration_sec: float
```

```python
# pc/l2/deal_gap.py
def compute_deal_gaps(run_id: str, base_date: str) -> int:
    """properties.deal_gap_pct 갱신. 갱신 건수 반환."""
```

```python
# common/peer_group.py
def robust_z(x: float, peers: Sequence[float], clip_at: float = 3.0) -> float | None: ...
def resolve_peer_group(target: StatRow, universe: Sequence[StatRow],
                       min_n: int) -> tuple[str | None, list[StatRow]]: ...
```

---

## 12. Config 명세 (`config/scoring_v2.yaml`)

```yaml
version: "2.0.0"

universe:
  min_peer_n: 20
  target_sgg: ["11650", "11680"]        # 서초구, 강남구 — 확장 금지
  peer_levels: ["UMD_AREA", "SGG_AREA", "BELT_AREA"]
  default_peer_scope: "BELT_AREA"

normalization:
  clip_at: 3.0
  mad_epsilon: 1e-9

blocks:
  value:
    weight: 0.35
    min_coverage: 2
    factors:
      excess_drop:   { weight: 0.45, direction:  1, peer_scope: BELT_AREA }
      jeonse_ratio:  { weight: 0.32, direction:  1, peer_scope: BELT_AREA }
      relative_ppp:  { weight: 0.10, direction: -1, peer_scope: SGG_AREA  }  # 잠정, IC 확인 후 조정
      rent_yield:    { weight: 0.13, direction:  1, peer_scope: SGG_AREA  }
  flow:
    weight: 0.25
    min_coverage: 2
    factors:
      volume_ratio:      { weight: 0.30, direction:  1, peer_scope: BELT_AREA }
      listing_delta_30d: { weight: 0.25, direction: -1, peer_scope: BELT_AREA }
      supply_pressure:   { weight: 0.25, direction: -1, peer_scope: BELT_AREA }
      momentum_3m:       { weight: 0.20, direction:  1, peer_scope: BELT_AREA }
  location:
    weight: 0.20
    min_coverage: 2
    factors:
      subway_decay: { weight: 0.40, direction: 1, peer_scope: BELT_AREA }
      cbd_access:   { weight: 0.40, direction: 1, peer_scope: BELT_AREA }
      elem_school:  { weight: 0.20, direction: 1, peer_scope: BELT_AREA }
  quality:
    weight: 0.20
    min_coverage: 2
    factors:
      households_log: { weight: 0.30, direction: 1, peer_scope: BELT_AREA }
      age_curve:      { weight: 0.30, direction: 1, peer_scope: BELT_AREA }
      far_score:      { weight: 0.25, direction: 1, peer_scope: BELT_AREA }
      brand:          { weight: 0.15, direction: 1, peer_scope: BELT_AREA }

peak_detection:
  lookback_months: 60
  window_months: 3
  percentile: 90
  min_window_trades: 2
  decay_tau: 36.0
  decay_floor: 0.80

location:
  subway_decay_scale_m: 400.0
  school_decay_scale_m: 300.0
  cbd_half_min: 30.0
  cbd_targets: ["강남역", "여의도역", "시청역"]

age_curve_nodes:
  - [0,  1.00]
  - [5,  0.85]
  - [15, 0.45]
  - [25, 0.40]
  - [32, 0.70]
  - [40, 0.95]
  - [50, 1.00]

gates:
  min_trades_12m: 3
  max_special_deal_ratio: 0.30        # 백필 후 실분포 기준 재산정
  max_unregistered_ratio: 0.20
  unregistered_grace_days: 180
  min_key_confidence: 0.85
  min_total_coverage: 0.50

risk_multipliers:
  jeonse_ratio_bottom_decile: 0.80
  supply_pressure_top_decile: 0.70
  redevelopment_dispute: 0.50
  floor: 0.35

l2:
  floor_adj: { LOW: 0.95, MID: 1.00, HIGH: 1.03 }

alert:
  excess_drop_percentile: 70
  min_volume_ratio: 1.0
  max_listing_delta: 0.0
  min_market_score: 65
  min_deal_gap_pct: 5.0
```

---

## 13. 계산 예시 (구현 검증용 Fixture)

`tests/fixtures/example_case.json`으로 고정하고 회귀 테스트에 사용한다.

**대상**: 반포동 A단지, `area_type = A84`, `base_date = 2026-07-01`

```
[Step 1] 유효 거래 필터
  전체 거래 24건 → 해제 1건, 직거래 2건 제외 → 21건
  special_deal_ratio = 3/24 = 0.125  (< 0.30 → G2 PASS)
  sample_count_12m = 9  (>= 3 → G1 PASS)

[Step 2] Robust 전고점
  단일 최대값        : 452,000 (만원)  ← 2024-08 직거래 1건, 제외됨
  롤링 3M p90 최대값 : 441,000 (만원)
  peak_date          : 2024-09

[Step 3] 시간 감쇠
  months_elapsed = 22
  decay = 0.80 + 0.20 × exp(-22/36) = 0.80 + 0.20 × 0.5423 = 0.9085
  peak_price_adj = 441,000 × 0.9085 = 400,649

[Step 4] 하락률 / 초과하락률
  median_price_3m = 385,000
  drop_rate       = 1 - 385,000/400,649 = 0.0391  (3.91%)
  서초구 A84 median_drop_rate = 0.0620
  excess_drop_rate = 0.0391 - 0.0620 = -0.0229   ← 시장 대비 덜 빠짐

[Step 5] 비교군 정규화
  peer_group = SGG_AREA:11650|A84,  N = 34
  peers의 excess_drop 중위수 = -0.0050
  peers의 MAD               =  0.0180
  scale = 1.4826 × 0.0180  =  0.0267
  z_A1 = (-0.0229 - (-0.0050)) / 0.0267 = -0.670

[Step 6] Block A (Phase 1: A1, A3만 가용 → 커버리지 2/4 = 0.50)
  z_A1 = -0.670 (w 0.40)
  z_A3 = +0.320 (w 0.20)
  w_sum = 0.60
  Block_value = (-0.670×0.40 + 0.320×0.20) / 0.60 = -0.340

[Step 7] 나머지 블록 (예시값)
  Block_flow     = +0.210  (coverage 1/4 → min_coverage 2 미달 → None)
  Block_location = +0.880  (coverage 2/3)
  Block_quality  = +0.150  (coverage 3/4)

  → flow 결측이므로 가중치 재정규화
  w_sum = 0.35 + 0.20 + 0.20 = 0.75
  Raw = (-0.340×0.35 + 0.880×0.20 + 0.150×0.20) / 0.75
      = (-0.119 + 0.176 + 0.030) / 0.75 = 0.1160

[Step 8] 최종 점수
  universe mean(Raw) = 0.000, std(Raw) = 0.420
  Raw_z = 0.1160 / 0.420 = 0.276
  BaseScore = Φ(0.276) × 100 = 60.9
  RiskMultiplier = 1.00
  MarketScore = 60.9

[Step 9] 총 커버리지
  가용 팩터 7 / 전체 15 = 0.467  →  G7 (min 0.50) 위반
  gate_status = EXCLUDED, gate_reason = LOW_COVERAGE
```

> **위 예시는 Phase 1 단계에서 커버리지 게이트에 걸리는 상황을 의도적으로 보여준다.** Phase 1에서는 `min_total_coverage`를 0.35로 낮춰 운영하고, Phase 2 완료 후 0.50으로 상향한다. 이 값 조정 이력을 `score_runs.config_hash`로 추적한다.

---

## 14. UI 변경 명세 (`pc/web_app.py`)

### 14.1 [매물 퀀트 분석 대시보드] 탭 — 컬럼 재구성

```
순위 | 지역 | 단지명 | 평형 | 호가 | 기준가(3M중위) | 괴리율 | 초과하락 | 시장점수 | v1점수 | 근거 | 매물확인
```

| 컬럼 | 원천 | 표기 |
| :-- | :-- | :-- |
| 기준가(3M중위) | `complex_area_stats.median_price_3m` | 실거래 기준선임을 툴팁 명시 |
| 괴리율 | `properties.deal_gap_pct` | `+7.2%` (양수 = 기준가 대비 저가) |
| 초과하락 | `excess_drop_rate` | `-2.3%p` / `+5.1%p`, 시장 대비 |
| 시장점수 | `market_scores.market_score` | 0~100, **비교군 백분위임을 툴팁 명시** |
| v1점수 | `properties.score_v1` | 병행 비교용, Phase 4에서 제거 |
| 근거 | — | `[?]` 버튼 → evidence 모달 |

### 14.2 Evidence 모달 (신규, P5)
점수 셀 클릭 시 팩터별 기여 내역을 표시한다.

```
반포 A단지 · A84 · 시장점수 60.9
비교군: 서초구 × A84 (N=34)     커버리지: 7/15 (46.7%)

┌ Block            가중  블록점수  기여
│ Value            0.35   -0.340   -0.119
│ Flow             0.25    (결측)      —     ← 매물 스냅샷 30일 미달
│ Location         0.20   +0.880   +0.176
│ Quality          0.20   +0.150   +0.030
└ Raw = 0.116 → z = 0.276 → Φ → 60.9 × 1.00 = 60.9

▼ Value 상세
  초과하락률   -2.29%p   비교군중위 -0.50%p   z=-0.67   w=0.40
  상대 평단가   0.94배    비교군중위  1.00배   z=+0.32   w=0.20
  전세가율      —         (전월세 데이터 미수집)
  임대수익률    —         (전월세 데이터 미수집)
```

**이것이 v2에서 실무적으로 가장 가치가 큰 산출물이다.** 점수 자체보다 "왜 그 점수인지"가 임장 판단에 직접 쓰인다.

### 14.3 [제외 매물] 탭 (신규)
`gate_status='EXCLUDED'` 목록을 사유별로 그룹화하여 표시한다. 조용한 소실 방지.

### 14.4 [2차원 스캐터] 탭 (신규, Phase 3)
X = `deal_gap_pct`, Y = `market_score`, 점 크기 = 세대수, 색 = 지역.
우상단 사분면 하이라이트.

### 14.6 구(區) 비교 패널 (신규)
§8.1.2에 따라 A1의 정규화 스코프를 벨트 통합으로 잡았으므로, 구 간 차이는 점수에 흡수되지 않고 그대로 반영된다. 이를 사용자가 확인할 수 있도록 대시보드 상단에 요약 패널을 둔다.

```
기준일 2026-07-01 · A84 기준

              중위 하락률   중위 평단가   중위 전세가율   단지·평형 수
  서초구        -6.2%        7,120만/평      48.3%          142
  강남구        -8.7%        6,880만/평      51.1%          198
  ─────────────────────────────────────────────────────
  벨트 중위     -7.6%        6,980만/평      49.8%          340
```

`area_type` 전환 가능. **이 패널은 점수 계산에 영향을 주지 않는 참고 지표이며, 그 사실을 명시한다.**

### 14.5 유지 항목
- 평형 필터 버튼, 매매가 슬라이더: 유지 (`area_type` 값으로 매핑 변경)
- `[⚡ 즉시 재계산]` 버튼: **동작 변경**. 네이버 미호출 유지하되, L1 스코어링 전체를 재실행하고 신규 `run_id`를 발급한다. 소요 시간이 1초를 초과하므로 진행률 표시 추가.

---

## 15. 텔레그램 알림 변경 (`oci/notifier/telegram_bot.py`)

### 15.1 발송 조건 (§7.3 Step 5 + config)
```
market_score  >= 65
AND deal_gap_pct >= 5.0
AND alert_candidate == True     (밸류트랩 교차조건 통과)
AND gate_status == 'PASS'
AND property_id NOT IN sent_alerts
```

### 15.2 메시지 포맷
```
🏢 반포동 A단지 · 84㎡ · 12층

호가      38.5억  (기준가 41.2억 대비 -6.6%)
시장점수  71.3    (서초구 A84 상위 28.7%)
초과하락  +5.1%p  (시장 -6.2% / 단지 -11.3%)

강점  거래량 회복 1.4배 · 매물 -12% · 역세권 320m
주의  전세가율 하위 20% · 커버리지 60%

▸ 네이버 부동산 바로가기
```

**"주의" 라인을 반드시 포함한다.** 강점만 나열하면 확증편향을 증폭시킨다.

---

## 16. 검증 설계

### 16.1 Point-In-Time 로더 (C7)

```python
class PITLoader:
    def __init__(self, base_date: str):
        self._base = base_date

    def trades(self, complex_code, area_type, lookback_months):
        # deal_date <= base_date 조건을 SQL 레벨에서 강제
        # 위반 시 LookAheadError 발생
```

**신고 지연 처리 (§4.1.1 아카이빙과 연계)**
`trades_sale`은 계약일 기준이나 실제 공개는 신고 후이므로, 계약일이 base_date 이전이어도 그 시점에는 존재하지 않던 거래가 있다.

| 구간 | 처리 |
| :-- | :-- |
| CSV 스냅샷 축적 이전 기간 | `deal_date + 30일 <= base_date` 근사 적용. **한계임을 리포트에 명시** |
| CSV 스냅샷 축적 이후 기간 | `first_seen_date <= base_date` 로 **실측 필터링**. 근사 불필요 |

스냅샷을 매월 축적하면 근사 구간이 점차 줄어든다. **또한 스냅샷 간 차분으로 신고 지연 분포를 실측할 수 있으므로, 근사 구간의 30일 상수를 실측 중위값으로 대체하는 것을 Phase 3에서 검토한다.**

> 고가 거래가 상대적으로 늦게 신고되는 경향이 있다면 `median_price_3m`의 최근 구간에 하방 편향이 생긴다(§18 L5). 스냅샷 차분은 이 편향의 크기를 직접 측정할 수 있는 유일한 수단이다.

### 16.2 전방수익률
```
forward_return_12m(complex_code, area_type, base_date) =
    median_price_3m(base_date + 12M) / median_price_3m(base_date) - 1
```
`base_date + 12M` 시점에 유효 거래 3건 미만이면 결측 처리(제외). 이 결측이 무작위가 아님(거래가 없는 단지 = 유동성 낮은 단지)을 인지하고, 생존편향 방향을 리포트에 명시한다.

### 16.3 측정 지표

| 지표 | 정의 | 합격선(참고) |
| :-- | :-- | :-- |
| Rank IC | 분기별 Spearman(factor_z, forward_return) | 평균 > 0.03 |
| IC IR | mean(IC) / std(IC) | > 0.30 |
| 분위 스프레드 | Q5 평균수익 − Q1 평균수익 | > 0 (연속 8분기 중 6분기 이상) |
| 턴오버 | 분기별 상위 20% 교체율 | 참고용 |

### 16.4 백테스트 가능 범위 (⚠️ 한계 명시)

| 팩터 | 백테스트 | 사유 |
| :-- | :--: | :-- |
| A1 초과하락, A3 상대평단가 | ✅ | 국토부 실거래 2006~ 소급 가능 |
| A2 전세가율, A4 임대수익률 | ✅ | 전월세 실거래 소급 가능 |
| B1 거래량, B4 모멘텀 | ✅ | 실거래 소급 가능 |
| **B2 매물 증감률** | ❌ | 과거 스냅샷 부재. 누적 시작일 이후만 |
| B3 입주물량 | △ | 수기 데이터 확보 범위 내 |
| C, D 블록 | △ | 시불변 가정 하에서만. 지하철 신설·재건축 진행은 반영 불가 |

**B2는 v2 설계에서 유의미한 팩터로 배치했으나 검증이 불가능하다.** 스냅샷 누적을 즉시 시작하고, 최소 4분기 축적 후 IC를 측정한다. 그 전까지 B2의 가중치는 잠정값이다.

### 16.5 v1 vs v2 회귀 비교
Phase 4에서 4주간 병행 운영 후:
- 두 점수 간 Spearman 순위상관 (낮을수록 v2가 다른 정보를 담고 있다는 뜻)
- 각각의 상위 20%에 대한 12개월 전방수익률 비교
- v1 상위 / v2 하위 교집합 단지의 사후 성과 개별 검토

---

## 17. Phase 로드맵 및 수용 기준(AC)

### Phase 1 — 기반 재구축 (필수, 나머지의 선행조건)

**범위**: 국토부 매매 수집 · 단지 매칭 · L1/L2 분리 · 비교군 정규화 · A1/A3/B4/C1/D1/D2/D4

| AC ID | 수용 기준 |
| :-- | :-- |
| P1-AC1 | `config/regions.yaml`에 서초구·강남구 **전 법정동(§8.0 표)** 을 등록하고 크롤링을 완료한다. 자치구는 2개로 고정하며 확장하지 않는다. 수집 후 실제 단지 수를 로그로 출력하고, `BELT_AREA` 레벨에서 주요 `area_type`(A59/A84/A114)별 N ≥ 20을 충족하는지 검증한다. **미달 시 해당 area_type을 스코어링 대상에서 제외**하고 사유를 기록한다(단지 수를 늘리는 방향으로 대응하지 않는다). |
| P1-AC2 | **CSV 경로**로 서초구·강남구 매매 실거래 60개월분 백필 완료. 원본 파일을 `data/raw/molit/<날짜>/`에 무변경 보관하고, `trades_sale.source_snapshot_date`를 채운다. 적재 건수를 로그 출력. |
| P1-AC2b | CSV의 **해제사유발생일·거래유형 컬럼 존재 여부**를 검증하고 결과를 문서화한다. 부재 시 §4.1.1 폴백(최근 12개월 API 재수집)을 적용하고, API 키 발급 전까지 G2 게이트를 `SKIPPED`로 명시 기록한다(무조건 PASS 처리 금지). |
| P1-AC2c | `to_canonical()`이 CSV 입력과 API 입력에 대해 **동일한 `CanonicalTrade`를 산출**함을 검증하는 테스트가 존재한다. 동일 거래 1건을 양쪽 경로로 받아 비교. |
| P1-AC3 | `complex_key_map` 매칭률(CONFIRMED 기준) ≥ 85%. 미달 시 수동 검수로 보완. |
| P1-AC4 | `to_area_type()` 단위 테스트 전 케이스 통과. 경계값(50.0, 70.0, 100.0, 135.0) 포함. |
| P1-AC5 | `peak_detector`가 예시 §13 Step 2~3 결과를 재현한다 (허용오차 ±0.5%). |
| P1-AC6 | `resolve_peer_group` 3단계 폴백이 각각 트리거되는 테스트 케이스 존재. |
| P1-AC7 | `market_scores` 적재 후, 점수 분포의 중앙값이 50 ± 3 범위 내. (Φ 매핑 정상 동작 확인) |
| P1-AC8 | 게이트 요약 리포트가 로그 출력되고 `score_runs`에 저장된다. |
| P1-AC9 | UI에 §14.1 컬럼 및 §14.2 Evidence 모달이 렌더링된다. |
| P1-AC10 | v1 스코어러가 병행 실행되어 `properties.score_v1`이 채워진다. |
| P1-AC11 | 모든 외부 호출에 timeout이 명시되어 있다 (코드 grep 검증). |
| P1-AC12 | `naver_crawler.py`가 실행 시마다 `listing_snapshots`를 적재한다. (Phase 2 준비) |

**Phase 1 완료 시점의 기대 효과**: 초과하락률 전환 + 비교군 정규화 + L1/L2 분리만으로 v1 대비 판별력 개선분의 과반이 확보된다.

---

### Phase 2 — 수급·전세 팩터 (핵심 정보 증분)

**범위**: 전월세 수집 · A2/A4 · B1/B2/B3 · 리스크 승수

| AC ID | 수용 기준 |
| :-- | :-- |
| P2-AC1 | 국토부 전월세 최근 36개월분 수집 완료, `trades_rent` 적재. |
| P2-AC2 | 전세가율 산출 로직: 순수 전세(monthly_rent=0)만 사용. 반전세 제외 검증 테스트. |
| P2-AC3 | `listing_snapshots` 30일 이상 누적 확인 후 B2 활성화. 미달 시 결측 반환 테스트. |
| P2-AC4 | 입주물량 CSV 스키마 검증 및 로더 구현. 파일 부재 시 B3 결측(예외 아님). |
| P2-AC5 | RiskMultiplier 3종이 각각 적용되는 테스트 케이스 존재. 하한 0.35 클램프 검증. |
| P2-AC6 | `min_total_coverage`를 0.50으로 상향 후에도 유니버스 통과율 ≥ 70%. |
| P2-AC7 | 텔레그램 알림에 밸류트랩 교차조건이 적용되고, "주의" 라인이 포함된다. |

---

### Phase 3 — 입지 심화 · 검증 인프라

**범위**: C2/C3 · D3 · 2차원 UI · 백테스트 · IC 리포트

| AC ID | 수용 기준 |
| :-- | :-- |
| P3-AC1 | CBD 대중교통 소요시간 API 확보 여부 판정. 불가 시 C2 제거 및 가중치 재분배 문서화. |
| P3-AC2 | `PITLoader`가 base_date 이후 데이터 접근 시 `LookAheadError`를 발생시킨다. 테스트 필수. |
| P3-AC3 | 최소 8분기 백테스트 실행 및 팩터별 Rank IC 리포트 생성. |
| P3-AC4 | 층 조정계수를 회귀 추정으로 대체. 추정 불가 단지는 상수 폴백 + evidence 명시. |
| P3-AC5 | IC IR < 0.1 인 팩터를 식별하고 제거/가중치 조정 근거를 문서화한다. |

---

### Phase 4 — v1 폐기 및 안정화

| AC ID | 수용 기준 |
| :-- | :-- |
| P4-AC1 | v1/v2 4주 병행 운영 결과 리포트 작성 (§16.5 항목 전부). |
| P4-AC2 | v2 단독 운영 전환 결정 후 `scorer.py` deprecate 및 UI `v1점수` 컬럼 제거. |
| P4-AC3 | 전체 파이프라인 1회 실행 소요시간 측정 및 문서화. |

---

## 18. 알려진 한계 및 비목표

**설계 단계에서 명시적으로 인정하고 시작해야 하는 항목들이다. 개발 AI는 이 한계를 우회하려는 코드를 작성하지 말 것.**

### L1. 이 점수는 알파 모델이 아니라 스크리닝 도구다
`market_score` 상위 = 매수 신호가 아니다. **3,000개 단지를 20개 임장 후보로 좁히는 것**이 이 시스템의 역할이다. UI 어디에도 "추천", "매수" 문구를 넣지 않는다.

### L2. 거래비용이 팩터 알파를 압도할 가능성이 높다
취득세 + 중개수수료 + 양도세 왕복 비용이 수 %~10%대다. 백테스트에서 연 3~4%p 초과수익이 나와도 실전 순수익은 음수일 수 있다. **백테스트 리포트에 거래비용 차감 시나리오를 반드시 병기한다.**

### L3. 분산이 불가능하다
상위 100개 랭킹의 통계적 우위는 100개를 전부 보유할 때 성립한다. 실제로는 1채를 산다. 표본 1개에는 모델이 관측하지 못하는 개별 요인(누수, 이웃, 학군 배정 변경, 소음)이 팩터 효과보다 크게 작용한다.

### L4. 호가와 실거래의 시차
`deal_gap_pct`는 호가(실시간)와 실거래 중위값(최대 3개월 지연)의 비교다. 급변 국면에서는 기준가 자체가 낡았을 수 있다. 하락 국면에서는 괴리율이 과대 계상되고, 상승 국면에서는 과소 계상된다.

### L5. 신고 지연 편향
국토부 실거래는 계약일 기준 30일 이내 신고 의무이나 실제 공개는 더 늦다. 최근 1~2개월 데이터는 불완전하며, **고가 거래가 상대적으로 늦게 신고되는 경향**이 보고된 바 있다. `median_price_3m`의 최근 구간은 하방 편향 가능성이 있다.

### L6. 비교군 표본은 법정동 확장으로 해소되나, 소형·대형 평형은 여전히 부족할 수 있다
서초구+강남구 전 법정동을 수집하면 `A59`/`A84`/`A114`의 `BELT_AREA` 표본은 충분할 것으로 예상된다. 그러나 `A40`(소형)과 `A135P`(대형)은 강남권 재고 구성상 표본이 얇을 가능성이 있다. **P1-AC1에서 미달이 확인되면 해당 평형을 스코어링 대상에서 제외한다.** 표본을 억지로 채우려고 유니버스를 확장하지 않는다.

### L8. 강남권 전체의 밸류에이션은 이 점수로 알 수 없다 (2구 한정의 구조적 귀결)
유니버스가 서초구+강남구로 한정되므로, 모든 점수는 **"강남권 안에서의 상대 순위"** 다. 강남권 전체가 서울 평균 대비 고평가인지 저평가인지는 이 모델이 답할 수 없는 질문이며, 답하려 시도해서도 안 된다.

`MarketScore = 85`는 "강남권에서 매력적인 상위 15%"를 의미할 뿐, "지금이 살 때"를 의미하지 않는다. **시장 진입 타이밍은 이 모델 밖의 별도 판단**이며, 필요하다면 한국부동산원 매매가격지수·전세가격지수 같은 시장 수준 지표를 UI에 참고용으로 병기하되, 점수 계산에는 투입하지 않는다(투입하면 모든 단지 점수가 함께 움직여 순위 정보가 사라진다).

### L9. 강남권 내부 이질성이 수준형 팩터를 오염시킨다
압구정·반포와 세곡·내곡은 같은 유니버스에 있으나 사실상 다른 시장이다. 평단가·임대수익률 같은 수준형 팩터는 이 격차를 "저평가"로 오독한다. §8.1.1에서 비교군을 `SGG_AREA`로 좁혔으나 완전한 해소는 아니다. **A3/A4는 Phase 3 IC 검증을 통과하기 전까지 신뢰하지 않는다.**

### L7. B2(매물 증감)는 검증 불가 상태로 배치된다
과거 스냅샷이 없어 IC 측정이 최소 4분기 뒤에나 가능하다. 그 전까지 가중치 0.25는 근거 없는 가정이다.

---

## 19. 구현 우선순위 요약

개발 AI는 아래 순서를 따른다. **선행 항목 미완 상태에서 후행 항목에 착수하지 않는다.**

```
0.  [선행 확인] Q2 — 네이버 크롤러 응답에 전용면적(㎡)이 있는가
0b. [선행 확인] CSV 샘플 1건 다운로드 → 해제·거래유형 컬럼 존재 여부 (P1-AC2b)
1.  common/area_mapper.py + 테스트           ← 여기가 틀리면 전부 무의미
2.  DB 마이그레이션 (schema_version 포함)
3.  oci/crawler/molit_schema.py              ← CanonicalTrade 계약 먼저 확정
4.  oci/crawler/molit_csv_loader.py          ← 백필. API 키 불필요
5.  oci/crawler/molit_ingest.py + 원본 아카이빙
6.  pc/keymap/matcher.py + review_cli.py     ← 수동 검수 1회 필요
7.  pc/features/peak_detector.py + 테스트
8.  pc/features/region_stats.py (벨트/구 양쪽 산출)
9.  pc/features/build_stats.py
10. common/peer_group.py + 테스트 (팩터별 scope)
11. pc/scoring/normalizer.py, gate.py, aggregator.py, evidence.py
12. pc/scoring/scorer_v2.py
13. pc/l2/deal_gap.py
14. pc/web_app.py UI 반영 (§14.1, §14.2, §14.6)
15. oci/notifier 메시지 포맷
16. oci/crawler/molit_client.py              ← API 키 확보 후. 증분 갱신용
17. (Phase 2 이후) 전월세, Flow, 백테스트
```

> **API 키 발급이 지연되어도 1~15번은 전부 진행 가능하다.** `molit_client.py`(16번)는 증분 갱신 전용이므로 초기 구축의 임계 경로가 아니다.

---

## 20. 미해결 사항 (설계 확정 필요)

| # | 항목 | 필요한 결정 |
| :-- | :-- | :-- |
| ~~Q1~~ | ~~대상 지역 확장 범위~~ | **[해결 2026-07-29]** 서초구(11650) + 강남구(11680) 2개 구로 확정. 확장 없음. 대신 2개 구 안의 전 법정동을 활성화한다. §8.0 참조 |
| Q2 | 네이버 매물의 전용면적 확보 가능 여부 | 불가 시 L1-L2 조인 키 전략 재설계 필요 |
| Q3 | CBD 접근성 API | 카카오 길찾기 vs ODsay vs 제거. 비용·쿼터 확인 |
| Q4 | 단지 마스터(세대수·용적률) 수집 경로 | 네이버 단지 API에 포함되는지 확인 필요 |
| Q5 | OCI 실행 주기 | 국토부 API 일 10,000건 한도 내 지역별 분산 스케줄 |
| Q6 | 백테스트 실행 위치 | PC(RTX 4070) 배치 vs OCI. 데이터 복제 전략 |

**Q2는 Phase 1 착수 전 반드시 확정되어야 한다.** 네이버 매물의 전용면적을 확보할 수 없으면 L1(국토부, 전용면적 기준)과 L2(네이버 호가) 조인 키가 성립하지 않으며, §10의 괴리율 계산 전체가 무효가 된다. 크롤러 응답 필드를 먼저 확인할 것.
