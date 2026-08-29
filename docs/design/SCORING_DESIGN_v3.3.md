# 부동산 퀀트 스코어링 v3 설계 명세서

> **문서 버전**: v3.3.0
> **작성일**: 2026-07-29
> **대상 프로젝트**: `property-screener` (PC-OCI 하이브리드 부동산 퀀트 스크리너)
> **대상 독자**: 구현 담당 개발 AI
> **상태**: 데이터 확보 완료. 구현 착수 가능 (Q1 1건 제외)

---

## 0. 문서 정보

### 0.1 이 문서의 위치

| 문서 | 상태 |
| :-- | :-- |
| `docs/DEVELOPMENT_SUMMARY.md` (v1.0.0) | 현행 시스템 명세. 유효 |
| `docs/PROJECT_STATUS.md` | 개발 현황. 유효 |
| ~~`SCORING_V2_DESIGN.md`~~ | **본 문서로 대체됨. 참조하지 말 것** |
| **`SCORING_V3_DESIGN.md` (본 문서)** | **단일 기준 문서** |

v2는 데이터 확보 전 작성되어 다수의 가정과 조건부 분기를 포함했다. 데이터 확보가 완료되어 대부분의 분기가 해소되었으므로, 패치 누적 대신 전면 재작성했다.

### 0.1.1 개정 이력

| 버전 | 일자 | 내용 |
| :-- | :-- | :-- |
| v3.0.0 | 2026-07-29 | 최초 작성 (v2 대체) |
| v3.3.0 | 2026-07-30 | **과잉 제약 5건 완화** — C12(기술정보 차단→요청 시 제공), 금지어 적용범위 축소(사용자 화면·알림 한정), V8 삭제(근거 부족), 배지 조건부 허용(부정 배지 필수), Level 1 항목 상한 삭제(결과 기준으로 대체). 강점·주의 최대 2줄로 완화. |
| v3.2.0 | 2026-07-30 | **착수 지시(§0.6) 신설** — 1차 구현 결함 15건 정리 및 수정 순서. 어휘 규칙(§16.9), 상호 정합성 검증 X1~X6(§11.6), 단지 실재성·run 단위 게이트 V7~V11(§11.5), 자가검증 리포트(§19.0), 완료 판정 절차(§19.1) 신설. 제약 C12~C14 추가. |
| v3.1.0 | 2026-07-29 | **UI 명세 전면 재작성**(§16) — 테이블→카드, 3단 계층, 숫자→문장 변환 규칙, 표기 변환표. **가격 정합성 게이트 V1~V6 신설**(§11.5) — 조인 실패로 인한 비정상 가격 노출 차단. 제약 C10(코드성 데이터 비노출)·C11(규칙 기반 문장) 추가. 한계 L10 추가. |

### 0.2 목적
현행 5-Factor 스코어링(`pc/ml_engine/scorer.py`)을 **비교군 상대평가 기반 4-Block 팩터 모델**로 대체한다.

### 0.3 In Scope
- 스코어링 단위 재정의 (L1 시장 점수 / L2 매물 괴리)
- 국토부 실거래 데이터 적재 계층 신설
- DB 스키마 확장 및 마이그레이션
- 팩터 산출 · 정규화 · 집계 파이프라인
- 데이터 품질 게이트 및 리스크 승수
- v1/v3 병행(Shadow) 운영 및 IC 검증 체계

### 0.4 Out of Scope
- 머신러닝 기반 가중치 최적화 (IC 측정 안정화 이후 별도 검토)
- 네이버 크롤러 수집 로직 변경 (429 방어 로직 현행 유지)
- 텔레그램 발송 인프라 변경 (메시지 포맷만 변경)
- **유니버스 확장** (§3에서 확정. 논의 대상 아님)

### 0.5 개발 AI 준수 사항 (Hard Constraints)

| # | 제약 | 사유 |
| :-- | :-- | :-- |
| **C1** | 본 문서에 명시되지 않은 **공개 API/함수 시그니처를 임의 추가하지 않는다.** 필요 시 문서 갱신을 먼저 요청한다 | 계약 표류 방지 |
| **C2** | 팩터 가중치·임계값을 **코드에 하드코딩하지 않는다.** 전부 `config/scoring_v3.yaml`에서 로드 | 튜닝 가능성 |
| **C3** | 모든 외부 호출에 **timeout을 명시**한다. 기본 10초 | 무한 대기 방지 |
| **C4** | 점수 산출 결과는 **스냅샷 테이블에 적재**하고, UI/알림은 스냅샷만 조회한다. 조회 시점 재계산 금지 | 저장·조회 분리 |
| **C5** | 데이터 부족은 **감점이 아니라 제외(fail-closed)**. 결측을 0이나 평균으로 대체하지 않는다 | 허위 신호 방지 |
| **C6** | v1 스코어러(`scorer.py`)를 **삭제하지 않는다.** v3와 병행 산출 | 회귀 비교 |
| **C7** | 백테스트는 **Point-In-Time 로더**를 반드시 경유. 기준일 이후 데이터 접근 시 예외 발생 | 미래참조 차단 |
| **C8** | 원본 CSV는 **서울 전체**를 보관하되, `trades_*` 적재 시 **`sgg_cd IN ('11650','11680')` 필터를 강제**한다 | 유니버스 고정 |
| **C9** | 판정 불가 상태를 **PASS로 처리하지 않는다.** 별도 상태값(`SKIPPED`)으로 기록하고 evidence에 남긴다 | 게이트 무력화 방지 |
| **C10** | **내부 식별자를 1단계 화면에 노출하지 않는다.** `area_type`, `complex_code`, `peer_group_key`, `run_id`, 표본 수, z-score는 §16.2 표기 변환표를 거치거나 Level 2로 내린다 | 사용자 인지부하 |
| **C11** | **화면 문장은 규칙 기반으로 생성한다.** LLM 호출 금지. 동일 입력 → 동일 문장 (§16.3) | 회귀 테스트 가능성 |
| **C12** | **진단은 구현 담당이 직접 실행한다.** 발주자에게 "이 쿼리를 돌려보세요"라고 요청하지 않는다. 기본 산출물은 §19.0의 사람 말 리포트다. **단, 발주자가 기술 상세를 요청하면 제공한다** — 발주자는 기술 문서를 읽을 수 있으며, 제한의 목적은 정보 차단이 아니라 역할 분리다 | 역할 분리 |
| **C13** | **결측 항목은 화면에서 줄째로 숨긴다.** 대체 문구·`-`·`N/A`·기본값·추정값 모두 금지. 숨긴 건수는 리포트에 집계 | C5 확장 |
| **C14** | **검증 실패 시 화면을 갱신하지 않는다.** 이전 정상 결과를 유지하고 사유를 리포트에 기록한다. 틀린 화면보다 어제 화면이 낫다 | 오정보 차단 |

---

### 0.6 착수 지시 — 지금 고칠 것

**1차 구현 결과(2026-07-30) 검수에서 결함 15건이 확인되었다. 신규 기능보다 이 수정이 우선한다.**

#### 0.6.1 대표 사례

서초구 반포동 `금정노블` — 15세대 나홀로 아파트가 "강남권 상위 1%(99점)"로 표시되었다.

| 항목 | 원본(네이버) | 시스템 |
| :-- | :-- | :-- |
| 세대수 | 15세대, 총 1동 | "대단지 아파트" |
| 전용면적 | 73.09 ~ 109.52㎡ | "전용 59㎡" |
| 매매가 | 12억 | 호가 26.1억 |
| 전세 | 없음 | "전세가율이 높아 실수요 지지가 탄탄" |
| 점수 | — | 99점 (v1은 20점) |

**이 단지에는 전용 59㎡ 평형이 존재하지 않는다.** 없는 평형으로 분류한 뒤 다른 대상의 실거래를 붙였다.

화면 내부도 모순됐다. 평가 항목은 `가격 메리트 100/100`, 문장은 `"가격 매력은 낮습니다"`, 수치는 `초과하락률 +-38.58%p`. 셋이 서로 다른 말을 한다. 초과하락률은 역산하면 시장 중위 하락률이 −29.5%(전고점보다 상승) 또는 +47.6%(강남권 반토막)가 되어 어느 쪽도 성립하지 않는다.

#### 0.6.2 설계 결함 (본 문서에서 수정 완료)

**아래 7건은 구현 담당의 잘못이 아니다. 명세가 없었거나 틀렸다.**

| ID | 결함 | 조치 위치 |
| :-- | :-- | :-- |
| DS-1 | 자가검증 리포트 산출물을 요구하지 않았다 | §19.0 신설 |
| DS-2 | 시스템 용어 노출 금지 범위가 좁았다 (`v1`, `V-Gate`, `4-Block` 등이 화면에 노출) | §16.9 신설, C10 확장 |
| DS-3 | v1 점수를 화면에 노출하라고 지시했다 | §16.2에서 제거 완료 |
| DS-4 | 표시 항목 간 내적 정합성 검증이 없었다 | §11.6 신설 |
| DS-5 | 결측을 화면에 어떻게 표시할지 정의하지 않았다 | C13 신설 |
| DS-6 | 장식 요소(배지·이모지·막대)를 금지하지 않았다 | §16.2.1 신설 |
| DS-7 | 단지 실재성 검증 게이트가 없었다 | §11.5 V7~V9 신설 |

#### 0.6.3 구현 결함 (코드 수정 필요)

**아래 8건은 본 문서에 이미 명시되어 있으나 지켜지지 않았다.**

| ID | 결함 | 위반 조항 |
| :-- | :-- | :-- |
| **DEV-1** | **Φ 정규화 미구현.** 4개 평가 항목이 전부 94점 이상. 블록 점수를 0~100으로 직접 스케일링한 것으로 보인다. v1의 "하락률 25% 이상은 전부 100점" 문제가 재현됨 | §9.5 |
| **DEV-2** | **블록 구성 임의 변경.** Location+Quality를 합치고 Momentum을 분리했으며, 전세가율(A2)을 Value가 아닌 Flow에 배치. 이러면 IC 측정 결과를 설계와 대조할 수 없다 | §8.1, C1 |
| **DEV-3** | **결측 팩터에 값을 채웠다.** 전세 자료가 없는데 전세가율 문장이 생성됨 | C5 |
| **DEV-4** | **v1 전용 컬럼 사용.** `change_1m/3m/6m`을 "추세 모멘텀"으로 표시. v3 모멘텀은 B4로 산출해야 한다 | §7.2 |
| **DEV-5** | **area_type 매핑 오류.** 73~109㎡ 단지에 `A59` 부여. 범위 밖이면 `None` 반환 후 제외해야 한다 | §4.3 |
| **DEV-6** | **부호 처리 버그.** `+-38.58%p`. 부호 접두사와 값의 부호가 중복 적용됨 | — |
| **DEV-7** | **설계에 없는 UI 요소 추가.** 배지 3종·이모지·진행 막대 | C1, §16.2.1 |
| **DEV-8** | **AC 검증 없이 완료 보고.** P1-AC10(점수 중앙값 50±3)을 만족할 수 없는 상태로 제출 | §19.1 |

#### 0.6.4 수정 순서

**UI를 먼저 손대지 않는다. 숫자가 틀린 상태에서 화면을 다듬으면 더 그럴듯하게 틀린 화면이 된다.**

```
1.  DEV-5   area_mapper 수정 + V7 게이트         ← 이번 사례의 근원
2.  DEV-3   결측 처리(C5, C13) + X4 검증
3.  DEV-1   Φ 정규화 구현 + V10 / V11
4.  DEV-2   블록 구성을 §8.1대로 복원
5.  DEV-4   v1 컬럼 사용 제거
6.  DEV-6   부호 처리 + X1 / X2 / X6
7.  §19.0   자가검증 리포트 구현
8.  §16.9   금지어 검사 구현 + 화면 문구 전면 교체
9.  DEV-7   UI 요소 정리 (§16.2.1)
10. §19.1   완료 판정 절차 실행 후 보고
```

**1~6번을 마치기 전에 화면 작업(9번)에 착수하지 않는다.**

## 1. As-Is 진단

### 1.1 현행 5-Factor 모델의 구조적 결함

현행: `Valuation(30) + Momentum(25) + Location(20) + Scale(15) + Floor(10)`

| ID | 결함 | 근거 | 영향 |
| :-- | :-- | :-- | :-- |
| **D1** | 상수 점수 잔존 | Valuation 최소 10 + Scale 최소 12 + Floor 최소 7 = **29점 공통 부여** | 실효 판별 구간이 100점이 아닌 약 71점 |
| **D2** | Scale/Floor의 판별력 부재 | Scale 15\|12 (스프레드 3), Floor 10\|7 (스프레드 3) | 배점 25점 중 실제 순위 기여는 6점 |
| **D3** | 스코어링 단위 혼재 | `properties` 1행 = 개별 호가이나 `change_1m/3m/6m`, `high_price`는 단지 속성 | 동일 단지 매물이 모멘텀 점수 중복 수령 → 상위 랭킹 단지 편중 |
| **D4** | 하락률의 베타/알파 미분리 | `drop_rate` = 단지 자체 하락률 | 시장 전체 하락분을 개별 매력도로 오인 |
| **D5** | 전고점의 이상치 취약성 | `high_price` = 실거래 단일 최대값 | 직거래·해제거래 1건이 하락률을 인위적으로 부풀림 |
| **D6** | 입지 팩터 절벽 효과 | 도보 5분(20) / 10분(15) / 15분(10) 계단함수 | 도보 10분 0초 vs 1초 = 5점 차 |
| **D7** | 절대 점수의 비교 불가능성 | 지역·평형 무관 동일 척도 | 반포 84점과 개포 84점의 의미가 다름 |
| **D8** | 밸류 트랩 미방어 | 하락률이 높을수록 무조건 고득점 | 펀더멘털 악화 단지가 상위 랭크 |
| **D9** | 가격 데이터 성격 혼용 | `high_price`(실거래)와 `asking_price`(호가)의 직접 비율 | 호가 프리미엄이 하락률에 오염 |
| **D10** | 유니버스 협소 | 반포동 63 + 개포동 24 = 87단지 (법정동 2개만 활성) | 비교군 통계 산출 불가 |

### 1.2 D9 상세
현행 `drop_rate = 1 - asking_price / high_price`는 **실거래가와 호가를 혼합한 비율**이다. 호가는 직전 실거래 대비 상방 편향(seller's ask premium)이 있으므로, 이 값은 순수 하락분이 아니라 `실제 하락분 − 호가 프리미엄`이다. 호가 프리미엄은 시장 국면에 따라 변동하므로 시계열 비교가 성립하지 않는다.

**v3에서는 실거래 기준선(L1)과 호가 괴리(L2)를 완전히 분리한다.**

---

## 2. 설계 원칙

| # | 원칙 | 내용 |
| :-- | :-- | :-- |
| **P1** | 절대 점수 → 비교군 상대 점수 | 모든 팩터를 peer group 내 robust z-score로 변환 |
| **P2** | 개별 가점 → 블록 가중합 | 4개 블록 구조. 팩터별 IC 측정 가능 |
| **P3** | 스코어링 단위 2계층 분리 | L1(단지×평형, 실거래) / L2(개별 호가, 괴리율) |
| **P4** | 리스크·품질은 게이트 | 감점이 아닌 제외 또는 곱셈 승수 |
| **P5** | 점수는 결과, evidence는 근거 | 모든 점수에 팩터별 기여 내역 JSON 동반 |
| **P6** | 저장과 조회 분리 | 계산 결과 스냅샷 적재, 조회 계층은 읽기 전용 |
| **P7** | **정규화 스코프 = 의사결정 스코프** | 의사결정에 포함된 축을 정규화로 소거하지 않는다 (§9.2) |

---

## 3. 유니버스 확정

**대상 지역은 서초구(11650) + 강남구(11680) 2개 자치구로 확정한다. 확장하지 않는다.**

| 자치구 | LAWD_CD | 대상 법정동 |
| :-- | :-- | :-- |
| 서초구 | `11650` | 반포, 잠원, 서초, 방배, 양재, 우면, 내곡, 염곡, 원지, 신원 |
| 강남구 | `11680` | 역삼, 개포, 청담, 삼성, 대치, 논현, 압구정, 도곡, 일원, 수서, 세곡, 자곡, 신사, 율현 |

**현행 `config.yaml`은 반포동·개포동 2개 법정동만 활성화되어 있다(87단지). Phase 1에서 위 24개 법정동 전체로 확장한다.** 확장 대상은 자치구가 아니라 같은 2개 구 안의 나머지 법정동이다.

### 3.1 구현 요구사항
- 법정동 10자리 코드는 행정표준코드관리시스템(`www.code.go.kr`)에서 조회하여 `config/lawd_codes.yaml`에 명시한다. 코드를 추정하거나 하드코딩하지 않는다.
- 아파트 재고가 미미한 법정동(원지·신원·율현 등)도 등록하되, 게이트 `G1`에서 자연 탈락하도록 둔다. 사전 제외 목록을 만들지 않는다.
- **원본 CSV는 서울 전체를 보관하지만 적재는 위 2개 구만 한다.** (C8)

### 3.2 유니버스 확장 금지의 의미
데이터가 서울 전체로 존재한다는 이유로 유니버스를 넓히면 §9(비교군 설계)와 §19(한계 서술)가 모두 무효화된다. 서울 전체 데이터는 **참조 통계 표시 용도로만** 사용하며, 스코어 계산에 투입하지 않는다.

---

## 4. 스코어링 단위

### 4.1 2계층 구조

| 계층 | 단위 키 | 산출물 | 원천 | 통계 처리 |
| :-- | :-- | :-- | :-- | :-- |
| **L1 시장 점수** | `complex_code × area_type` | `market_score` (0~100) | 국토부 실거래 + 카카오 + 단지 마스터 | 비교군 z-score |
| **L2 매물 괴리** | `property_id` | `deal_gap_pct` (%) | 네이버 호가 | 통계 없음, 직접 계산 |

L1은 단지·평형당 실거래 수십 건을 근거로 하므로 통계 처리가 가능하다. L2는 개별 호가 1건이므로 z-score를 계산할 표본이 없다. **L2는 점수화하지 않고 괴리율(%)을 그대로 노출한다.**

### 4.2 최종 표현
단일 랭킹이 아니라 2차원으로 제시한다.

```
Y축: L1 market_score   (이 단지·평형이 매력적인가)
X축: L2 deal_gap_pct   (이 매물이 그 단지 안에서 싼가)

→ 우상단(고득점 + 고괴리)이 우선 임장 대상
```

### 4.3 area_type 정의 (⚠️ 최우선 검증 항목)

**현행 `area_pyeong`(20PY/30PY/40PY)은 네이버 기준 공급면적 추정치이나, 국토부 데이터는 전용면적(㎡)이다. 이 매핑을 틀리면 에러 없이 전체 지표가 오염된다.**

`area_type`은 **전용면적(㎡) 기준**으로 정의하고, 네이버 데이터를 이 기준으로 재매핑한다.

| area_type | 전용면적 범위(㎡) | 통칭 |
| :-- | :-- | :-- |
| `A40` | 33.0 ≤ x < 50.0 | 소형 |
| `A59` | 50.0 ≤ x < 70.0 | 20평형대 |
| `A84` | 70.0 ≤ x < 100.0 | 30평형대 |
| `A114` | 100.0 ≤ x < 135.0 | 40평형대 |
| `A135P` | 135.0 ≤ x | 대형 |

**구현 요구사항**
- `common/area_mapper.py::to_area_type(exclusive_area_m2: float) -> str | None`
- 범위 밖은 `None` 반환 → 스코어링 유니버스에서 제외 (C5)
- 네이버 매물의 전용면적을 확보할 수 없으면 해당 매물은 **L2에서만 사용하고 L1 집계에 투입하지 않는다.**
- 기존 `area_pyeong` 컬럼은 보존하고 `area_type` 컬럼을 신설한다.

---

## 5. 데이터 자산 현황

### 5.1 확보 완료 (2026-07-29)

| 항목 | 값 |
| :-- | :-- |
| 출처 | 국토교통부 실거래가 공개시스템 `rt.molit.go.kr` (자료제공) |
| 대상 | **서울특별시 전체** (적재는 11650/11680만 — C8) |
| 건물유형 | 아파트 |
| 구분 | **매매 + 전월세** |
| 기간 | **2018-01-01 ~ 2026-07** |
| 지번구분 | **지번주소** (본번·부번·도로명 동시 확보) |
| 분할 | 1년 단위 |
| 인증 | 불필요 (공공데이터포털 점검과 무관) |

### 5.2 CSV 컬럼 명세 (실물 확인 완료)

```
NO | 시군구 | 번지 | 본번 | 부번 | 단지명 | 전용면적(㎡) | 계약년월 | 계약일 |
거래금액(만원) | 동 | 층 | 매수자 | 매도자 | 건축년도 | 도로명 |
해제사유발생일 | 거래유형 | 중개사소재지 | 등기일자
```

| CSV 컬럼 | → `CanonicalTrade` | 변환 규칙 | 용도 |
| :-- | :-- | :-- | :-- |
| 시군구 | `sgg_cd`, `umd_nm` | **문자열 파싱** (§5.4) | `"서울특별시 서초구 방배동"` |
| 번지 / 본번 / 부번 | `jibun`, `bonbun`, `bubun` | 정수, 부번 0 허용 | **단지 매칭 주 키** (§6) |
| 단지명 | `apt_name_raw` | 원문 보존 | 매칭 보조, 브랜드 추출(D4) |
| 전용면적(㎡) | `exclusive_area` | float | `area_type` 산출 |
| 계약년월 + 계약일 | `deal_date` | `202607`+`16` → `2026-07-16` | 2개 컬럼 결합 |
| 거래금액(만원) | `deal_amount` | 콤마 제거 → int | `"184,000"` → `184000` |
| 동 | `building_dong` | `-` → NULL | 등기 완료 건만 공개 |
| 층 | `floor` | int | 층 조정계수 추정 |
| 매수자 / 매도자 | `buyer_type`, `seller_type` | 원문 | 저장만. 팩터화 보류 |
| 건축년도 | `build_year` | int | **D2 연식 팩터** |
| 도로명 | `road_name` | 원문 | 매칭 보조 키 |
| 해제사유발생일 | `cancel_date`, `is_cancelled` | `-`→NULL, 값 존재 시 1 | **유효거래 필터** |
| 거래유형 | `deal_type` | `중개거래` \| `직거래` | **게이트 G2** |
| 중개사소재지 | `agent_region` | `-` → NULL | 직거래는 항상 NULL |
| 등기일자 | `registry_date` | `YY.MM.DD` → `YYYY-MM-DD` | **게이트 G2b** (§11.2) |

**전월세 CSV**는 거래금액 대신 `보증금 / 월세` 컬럼을 가진다. 구조는 동일하다. 로더 구현 시 실물 헤더를 확인하고 `molit_schema.py`에 매핑을 등록한다.

### 5.3 CSV 파싱 함정

| 항목 | 대응 |
| :-- | :-- |
| 인코딩 | CP949(EUC-KR) 가능성이 높다. UTF-8 실패 시 폴백. **자동 감지 금지**, 명시적 시도 순서 지정 |
| 헤더 앞 안내문 | 실제 헤더 행 앞에 안내 문구가 존재한다. 고정 `skiprows` 대신 **헤더 키워드 탐색**으로 시작 행을 찾는다 |
| 거래금액 | `"450,000"` 문자열. 콤마 제거 후 int |
| 결측 표기 | 빈 문자열 / `-` / 공백 혼재. 명시적 결측 처리 |
| 파일 분할 | 1년 단위 파일 다수. **병합하지 말고 개별 로드 후 append** |

### 5.4 시군구 문자열 파싱

CSV는 지역을 코드가 아닌 한글 문자열 단일 필드로 제공한다.

```
"서울특별시 서초구 방배동"  →  sgg_nm="서초구", umd_nm="방배동"
                            →  sgg_cd="11650"   (config/lawd_codes.yaml 조회)
```

- 매핑 테이블 역조회를 우선한다. 토큰 수를 가정하지 않는다.
- 테이블에 없는 지역명은 **예외를 발생시킨다.** 조용한 NULL 처리 금지 (C5).

### 5.5 컬럼 결측의 시기 의존성 (⚠️ Phase 1 필수 검증)

**과거 연도 파일은 컬럼이 존재해도 값이 `-`로만 채워져 있을 수 있다.** 각 컬럼의 공개 개시 시점이 다르다.

**Phase 1 착수 시 수행할 것**
```
연도별 × 컬럼별 결측률 표를 산출하여 docs/molit_column_coverage.md에 기록.
대상: 거래유형, 해제사유발생일, 등기일자, 동, 매수자, 매도자
```

**설계 영향**

| 구간 | 유효거래 필터 강도 | 대응 |
| :-- | :-- | :-- |
| 플래그 결측 구간 (과거) | 직거래·해제·미등기 제거 불가 | **p90 롤링 윈도우(§8.3 Step 2)가 1차 방어.** 단일 이상거래는 고점이 될 수 없다 |
| 플래그 존재 구간 (최근) | 전량 적용 | 정상 |

게이트 `G1`/`G2`/`G2b`는 최근 12개월만 참조하므로 영향받지 않는다. **영향은 전고점 탐지 구간에 국한된다.**

`trades_sale`에 `flag_coverage` 파생 컬럼을 두어 해당 거래가 필터 가능 구간인지 기록하고, 백테스트 리포트에서 구간별 결과를 분리 제시한다.

### 5.6 원본 아카이빙 (필수)

```
data/raw/molit/
  2026-07-29/
    apt_trade_seoul_2018.csv ~ apt_trade_seoul_2026.csv
    apt_rent_seoul_2018.csv  ~ apt_rent_seoul_2026.csv
  2026-08-31/
    ...
```

**목적은 백업이 아니라 Point-In-Time 복원이다.** 실거래가공개시스템은 신고 변경·해제가 실시간 반영되므로, 동일 기간을 다른 날 받으면 내용이 달라진다. 각 원본 파일은 **"해당 다운로드 시점에 공개되어 있던 거래 집합"** 이라는 확정 스냅샷이다.

- `trades_sale.source_snapshot_date`에 다운로드일을 기록한다.
- 동일 `trade_id`가 이후 스냅샷에서 사라지면 해제된 거래이므로 `is_cancelled=1`로 갱신한다. **원본 행은 삭제하지 않는다.**
- 이를 축적하면 과거 데이터에 없던 `ingested_at`을 사후 복원할 수 있으며, §18.1의 미래참조 근사 처리를 실측으로 대체할 수 있다.

### 5.7 증분 갱신 (Phase 2 이후)

| | 백필 (완료) | 증분 |
| :-- | :-- | :-- |
| 경로 | `rt.molit.go.kr` CSV | 공공데이터포털 오픈 API |
| 엔드포인트 | — | `apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev`<br>`.../RTMSDataSvcAptRent/getRTMSDataSvcAptRent` |
| 파라미터 | — | `serviceKey`, `LAWD_CD`(11650/11680), `DEAL_YMD`(YYYYMM), `pageNo`, `numOfRows` |
| 주기 | 1회성 | 월 1회, 최근 3개월 재조회 |
| 호출량 | — | 2구 × 3개월 × 2구분 = 12회/월 |

**API 키 발급 유의**: 공공데이터포털 전환 작업(2026-07-29 19:00 ~ 08-02 18:00) 중 신규 활용신청이 불가하다. **증분 갱신은 임계 경로가 아니므로 Phase 2로 배치한다.** 백필 데이터만으로 Phase 1 전체가 완결된다.

**Encoding/Decoding 키 주의**: `requests`의 `params=`로 전달 시 **Decoding 키**, URL 직접 결합 시 Encoding 키를 사용한다. 이중 인코딩 오류가 잦다.

### 5.8 소스별 역할 분담

| 데이터 | 국토부 | 네이버 | 채택 |
| :-- | :--: | :--: | :-- |
| 매매 실거래 | 원천 | 재가공 | **국토부** (해제·직거래 플래그 보존) |
| 전월세 실거래 | 원천 | 일부 | **국토부** |
| 건축년도 | ○ | ○ | **국토부** |
| 지번·도로명 | ○ | ? | **국토부** (네이버는 매칭 대조용) |
| 현재 호가 | ✕ | ○ | **네이버** |
| 매물 건수 | ✕ | ○ | **네이버** |
| 세대수·용적률 | ✕ | ○ | **네이버** |

> 네이버가 노출하는 실거래가는 국토부 데이터의 재가공이다. 원천을 직접 받으면 네이버가 걸러낸 플래그가 복원되며, 이것이 §1.1 D5의 직접적 해법이다.

**복원력 특성**: L1 스코어링은 네이버 없이도 대부분 동작한다. 필수 의존은 D1(세대수)뿐이며, 좌표는 국토부 도로명 주소를 카카오 지오코딩으로 변환하여 대체 가능하다. **네이버 차단 시에도 L1은 유지되고 L2만 정지한다.**

---

## 6. 단지 키 매칭

### 6.1 문제
- 네이버: `complex_code` (예: `104721`)
- 국토부: `시군구 문자열 + 본번 + 부번 + 도로명 + 단지명 + 건축년도`

공통 식별자가 없다. 다만 **지번(본번/부번)과 도로명이 제공되므로** 단지명 문자열에만 의존했을 때보다 난이도가 크게 낮다. 단지명은 표기가 흔들리지만(`방배대성유니드아파트` / `대성유니드` / `방배 대성유니드`) 지번은 고정값이다.

### 6.2 매칭 전략 (5단계)

```
Tier 1. 지번 완전일치                       [주 경로]
  key = (sgg_cd, umd_nm, bonbun, bubun)
  → confidence 1.00, method 'JIBUN'

Tier 2. 도로명 정규화 일치                   [보조]
  normalize_road(도로명) 일치 + build_year 일치
  → confidence 0.95, method 'ROAD'

Tier 3. 단지명 정규화 + 건축년도              [폴백]
  normalize(name) = 공백/괄호/특수문자 제거 + "아파트" 접미사 제거 + NFC
  → confidence 0.90, method 'NAME'

Tier 4. 유사도                              [잔여]
  동일 (sgg_cd, umd_nm, build_year) 내 Levenshtein ratio >= 0.85
  → confidence = ratio, method 'FUZZY'

Tier 5. 수동 확정
  → confidence 1.00, method 'MANUAL'
```

**교차 검증 필수**: Tier 1로 매칭되어도 `build_year`가 불일치하면 경고 로그를 남기고 `status='PENDING'`으로 보류한다. 재개발로 신·구 단지가 같은 지번을 쓰는 경우가 있다.

### 6.3 다대일(N:1) 관계
**하나의 단지가 여러 지번에 걸치는 경우가 흔하다**(대단지, 통합 재건축). `complex_key_map`은 국토부 키 1행 → `complex_code` 1개의 N:1 매핑이다. `UNIQUE`에 `apt_name_norm`을 포함하는 이유는 동일 지번에 `○○1단지`/`○○2단지`가 공존할 수 있기 때문이다.

### 6.4 네이버 측 선행 조건 (Q1과 함께 확인)
Tier 1/2가 작동하려면 네이버 단지 정보에 지번 또는 도로명이 포함되어야 한다.

```sql
ALTER TABLE complexes ADD COLUMN bonbun    INTEGER;
ALTER TABLE complexes ADD COLUMN bubun     INTEGER;
ALTER TABLE complexes ADD COLUMN road_name TEXT;
```

둘 다 없으면 Tier 3부터 시작하며 수동 검수 부담이 증가한다.

### 6.5 게이트 및 예상 공수
`confidence < 0.85` 또는 `status != 'CONFIRMED'` 인 단지는 L1 유니버스에서 제외한다 (게이트 `G3`).

| 상황 | 예상 수동 검수 비율 |
| :-- | :-- |
| 네이버에 지번/도로명 존재 | 5% 미만 |
| 단지명만 존재 | 15~20% |

산출물: `pc/tools/match_review.py` — 미매칭 목록 + 후보 제시 + 수동 확정 CLI

---

## 7. DB 스키마

### 7.1 신규 테이블

```sql
-- ── 스키마 버전 관리 ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT
);

-- ── 단지 마스터 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS complexes (
    complex_code       TEXT PRIMARY KEY,
    complex_name       TEXT NOT NULL,
    sgg_cd             TEXT NOT NULL,
    umd_cd             TEXT,
    umd_nm             TEXT,
    bonbun             INTEGER,
    bubun              INTEGER,
    road_name          TEXT,
    build_year         INTEGER,
    total_households   INTEGER,
    total_dongs        INTEGER,
    floor_area_ratio   REAL,
    building_coverage  REAL,
    brand              TEXT,
    area_min_m2        REAL,          -- 단지 최소 전용면적 (V7 검증용)
    area_max_m2        REAL,          -- 단지 최대 전용면적 (V7 검증용)
    lat                REAL,
    lng                REAL,
    subway_dist_m      REAL,
    subway_name        TEXT,
    elem_school_dist_m REAL,
    cbd_transit_min    REAL,
    updated_at         TEXT NOT NULL
);

-- ── 단지 키 매핑 ───────────────────────────────────────────
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
    match_method    TEXT NOT NULL,   -- JIBUN|ROAD|NAME|FUZZY|MANUAL|UNMATCHED
    status          TEXT NOT NULL,   -- CONFIRMED|PENDING|UNMATCHED
    reviewed_at     TEXT,
    UNIQUE(sgg_cd, umd_nm, bonbun, bubun, apt_name_norm)
);

-- ── 매매 실거래 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades_sale (
    trade_id        TEXT PRIMARY KEY,   -- 해시(sgg|본번|부번|apt|area|date|floor|amount)
    complex_code    TEXT,
    sgg_cd          TEXT NOT NULL,
    umd_nm          TEXT,
    bonbun          INTEGER,
    bubun           INTEGER,
    road_name       TEXT,
    apt_name_raw    TEXT NOT NULL,
    exclusive_area  REAL NOT NULL,
    area_type       TEXT,
    deal_date       TEXT NOT NULL,      -- YYYY-MM-DD
    deal_amount     INTEGER NOT NULL,   -- 만원
    building_dong   TEXT,
    floor           INTEGER,
    buyer_type      TEXT,
    seller_type     TEXT,
    build_year      INTEGER,
    is_cancelled    INTEGER NOT NULL DEFAULT 0,
    cancel_date     TEXT,
    deal_type       TEXT,               -- 중개거래|직거래
    agent_region    TEXT,
    registry_date   TEXT,               -- NULL = 미등기
    flag_coverage   INTEGER NOT NULL DEFAULT 0,  -- 1 = 필터 가능 구간
    source          TEXT NOT NULL,      -- CSV|API
    source_snapshot_date TEXT,
    first_seen_date TEXT,
    last_seen_date  TEXT,
    ingested_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ts_key ON trades_sale(complex_code, area_type, deal_date);
CREATE INDEX IF NOT EXISTS idx_ts_sgg ON trades_sale(sgg_cd, area_type, deal_date);

-- ── 전월세 실거래 ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades_rent (
    rent_id         TEXT PRIMARY KEY,
    complex_code    TEXT,
    sgg_cd          TEXT NOT NULL,
    umd_nm          TEXT,
    bonbun          INTEGER,
    bubun           INTEGER,
    apt_name_raw    TEXT NOT NULL,
    exclusive_area  REAL NOT NULL,
    area_type       TEXT,
    deal_date       TEXT NOT NULL,
    deposit         INTEGER NOT NULL,   -- 만원
    monthly_rent    INTEGER NOT NULL DEFAULT 0,
    floor           INTEGER,
    build_year      INTEGER,
    contract_type   TEXT,               -- 신규|갱신
    source          TEXT NOT NULL,
    source_snapshot_date TEXT,
    ingested_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tr_key ON trades_rent(complex_code, area_type, deal_date);

-- ── 매물 수 스냅샷 (B2 팩터용) ─────────────────────────────
CREATE TABLE IF NOT EXISTS listing_snapshots (
    snapshot_date    TEXT NOT NULL,
    complex_code     TEXT NOT NULL,
    area_type        TEXT NOT NULL,
    listing_count    INTEGER NOT NULL,
    min_ask_price    INTEGER,
    median_ask_price INTEGER,
    PRIMARY KEY (snapshot_date, complex_code, area_type)
);

-- ── L1 집계 지표 ───────────────────────────────────────────
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
    unregistered_ratio   REAL,
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
    block_value      REAL,
    block_flow       REAL,
    block_location   REAL,
    block_quality    REAL,
    raw_score        REAL,
    base_score       REAL,      -- Φ 매핑 후 0~100
    risk_multiplier  REAL NOT NULL DEFAULT 1.0,
    market_score     REAL,
    gate_status      TEXT NOT NULL,   -- PASS|EXCLUDED
    gate_reason      TEXT,
    coverage_ratio   REAL,
    evidence_json    TEXT NOT NULL,
    PRIMARY KEY (run_id, complex_code, area_type)
);

-- ── 실행 이력 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS score_runs (
    run_id          TEXT PRIMARY KEY,
    run_at          TEXT NOT NULL,
    base_date       TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    scorer_version  TEXT NOT NULL,   -- v1|v3
    universe_total  INTEGER NOT NULL,
    universe_passed INTEGER NOT NULL,
    excluded_count  INTEGER NOT NULL,
    duration_sec    REAL
);

-- ── 지역 통계 (벨트/구 양쪽) ───────────────────────────────
CREATE TABLE IF NOT EXISTS region_stats (
    base_date           TEXT NOT NULL,
    scope               TEXT NOT NULL,   -- BELT|SGG
    scope_key           TEXT NOT NULL,   -- 'BELT' | '11650' | '11680'
    area_type           TEXT NOT NULL,
    median_drop_rate    REAL,
    median_ppp          REAL,
    median_jeonse_ratio REAL,
    sample_n            INTEGER NOT NULL,
    supply_ratio        REAL,
    unsold_delta_3m     REAL,
    PRIMARY KEY (base_date, scope, scope_key, area_type)
);
```

### 7.2 기존 테이블 변경

```sql
-- properties: L2 전용으로 역할 축소
ALTER TABLE properties ADD COLUMN area_type      TEXT;
ALTER TABLE properties ADD COLUMN exclusive_area REAL;
ALTER TABLE properties ADD COLUMN deal_gap_pct   REAL;
ALTER TABLE properties ADD COLUMN floor_grade    TEXT;   -- LOW|MID|HIGH
ALTER TABLE properties ADD COLUMN score_v1       REAL;
ALTER TABLE properties ADD COLUMN last_seen_at   TEXT;
```

`change_1m/3m/6m`, `high_price`, `drop_rate`는 **삭제하지 않되 v3 스코어링에서 사용하지 않는다.** v1 병행 운영에 필요하다 (C6).

### 7.3 마이그레이션
`common/migrations/` 에 `001_*.sql` 형태로 순차 적용. **멱등성 보장 필수.** `schema_version` 테이블로 적용 이력을 관리한다.

---

## 8. 팩터 명세

### 8.1 블록 구성 및 Phase 배정

| 블록 | 가중치 | 팩터 | Phase 1 가용 |
| :-- | :--: | :--: | :--: |
| A. Value | 0.35 | 4 | **3** |
| B. Flow | 0.25 | 4 | **2** |
| C. Location | 0.20 | 3 | **2** |
| D. Quality | 0.20 | 4 | **3** |
| **합계** | 1.00 | **15** | **10 (66.7%)** |

### 8.2 팩터 일람

#### Block A — Value (0.35)

| ID | 명칭 | 계산식 | 방향 | 블록내 가중 | 비교군 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: | :--: |
| `A1` | 초과하락률 | §8.3 | + | 0.45 | BELT | **1** |
| `A2` | 전세가율 | `median_jeonse_deposit_6m / median_price_3m` | + | 0.32 | BELT | **1** |
| `A4` | 환산 임대수익률 | `(monthly_rent×12 + deposit×전환율) / price` | + | 0.13 | SGG | **1** |
| `A3` | 상대 평단가 | `price_per_pyeong / peer_median_ppp` | − | 0.10 | SGG | **3** |

**A2가 v1 대비 가장 큰 정보 증분이다.** 하락률만으로는 하락의 원인을 알 수 없다. 매매가가 떨어지는 동안 전세가율이 올랐다면 실수요는 유지된 채 투자수요만 이탈한 것이고, 전세가율까지 동반 하락했다면 지역 자체의 약화다. 완전히 다른 국면이며 대응도 반대다.

**A2 산출 시 순수 전세만 사용한다** (`monthly_rent = 0`). 반전세를 섞으면 보증금이 과소 계상되어 전세가율이 왜곡된다.

**A3는 Phase 1에서 제외한다.** 아래 실데이터가 근거다 (서초구 2026-07, `A84` 버킷).

| 단지 | 전용(㎡) | 거래금액(만원) | 건축년도 |
| :-- | --: | --: | --: |
| 아크로리버뷰신반포 | 84.82 | 325,000 | 2018 |
| 서초래미안 | 84.95 | 284,000 | 2003 |
| 서초동 현대 | 84.33 | 249,000 | 1989 |
| 방배대성유니드 | 84.93 | 184,000 | 2003 |

**단일 자치구·단일 평형 버킷 안에서 1.77배 격차**다. 이 분산의 대부분은 가격오류가 아니라 입지·연식이며, `D2`(연식)와 `C1`(역세권)이 이미 별도로 포착하고 있다. A3는 중복 계상이거나 노이즈일 가능성이 높다. **Phase 3에서 IC를 측정한 뒤 유의할 때만 편입한다.**

#### Block B — Flow (0.25)

| ID | 명칭 | 계산식 | 방향 | 블록내 가중 | 비교군 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: | :--: |
| `B1` | 거래량 회복비 | `trade_count_3m / (trade_count_12m / 4)` | + | 0.30 | BELT | **1** |
| `B4` | 3개월 모멘텀 | `median_price_3m / median_price_3m_lag3 − 1` | + | 0.20 | BELT | **1** |
| `B2` | 매물 증감률 | `(listing_now − listing_30d_ago) / listing_30d_ago` | − | 0.25 | BELT | 2 |
| `B3` | 입주물량 압박 | `향후 12M 입주세대 / 시군구 재고세대` | − | 0.25 | BELT | 2 |

`B2`는 `listing_snapshots` 누적이 선행되어야 한다. **스냅샷 시작 후 30일 미경과 시 결측을 반환한다. 임의 대체 금지** (C5).

`B3`는 수기 CSV(`data/manual/supply_schedule.csv`)로 관리한다. 자동 크롤링하지 않는다 — 유지보수 부담이 수집 가치를 초과한다. 파일 부재 시 결측 반환(예외 아님).

#### Block C — Location (0.20)

| ID | 명칭 | 계산식 | 방향 | 블록내 가중 | 비교군 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: | :--: |
| `C1` | 역세권 감쇠 | `exp(−subway_dist_m / 400)` | + | 0.40 | BELT | **1** |
| `C3` | 초품아 | `exp(−elem_school_dist_m / 300)` | + | 0.20 | BELT | **1** |
| `C2` | 업무지구 접근성 | `1 / (1 + cbd_transit_min / 30)` | + | 0.40 | BELT | 3 |

**C1은 현행 계단함수를 연속 감쇠함수로 대체한다.** 절벽 효과(D6)가 제거된다.

```
현행:  도보 10분 이내 → 15점, 초과 → 10점   (불연속)
v3  :  exp(−d/400)                          (연속, 400m에서 0.368)
```

`C3`는 카카오 로컬 API POI 검색으로 `C1`과 동일한 방식으로 산출한다. 추가 API 계약이 필요 없다.

`C2`(강남역·여의도역·시청역 중 최소 대중교통 소요시간)는 별도 경로탐색 API가 필요하다. **확보 불가 시 C2를 제거하고 C1/C3 가중치를 재정규화한다.**

#### Block D — Quality (0.20)

| ID | 명칭 | 계산식 | 방향 | 블록내 가중 | 비교군 | Phase |
| :-- | :-- | :-- | :--: | :--: | :--: | :--: |
| `D1` | 단지 규모 | `log(total_households)` | + | 0.30 | BELT | **1** |
| `D2` | 연식 곡선 | §8.4 | 역U자 | 0.30 | BELT | **1** |
| `D4` | 브랜드 | 더미 (0/1) | + | 0.15 | BELT | **1** |
| `D3` | 정비 사업성 | `1 / floor_area_ratio` 정규화 | + | 0.25 | BELT | 3 |

`D2`, `D4`는 국토부 데이터만으로 산출 가능하다(건축년도, 단지명 문자열). `D1`만 네이버 단지 정보에 의존한다.

**D4 브랜드의 한계 인지**: 전체 가중치의 `0.20 × 0.15 = 3%`다. 브랜드는 세대수·연식과 상관이 높아 독립적 설명력이 낮다. Phase 3 IC 측정 후 제거를 검토한다.

### 8.3 A1 초과하락률 — 상세 명세

현행 `drop_rate`를 5단계로 재정의한다. **v3 개선분에서 가장 큰 비중을 차지한다.**

**Step 1. 유효 거래 필터**
```sql
유효거래 = trades_sale WHERE
      is_cancelled = 0
  AND deal_type != '직거래'
  AND complex_code IS NOT NULL
  AND area_type IS NOT NULL
  AND NOT (registry_date IS NULL
           AND julianday(base_date) - julianday(deal_date) > 180)   -- §11.2
```

**Step 2. Robust 전고점**
단일 최대값 대신 롤링 윈도우 상위 분위수를 쓴다.
```
for each rolling 3-month window w in [base_date − 60M, base_date]:
    if count(유효거래 in w) >= MIN_WINDOW_TRADES(=2):
        p90[w] = percentile(deal_amount in w, 90)

peak_price_raw = max(p90)
peak_date      = argmax(p90)
```
윈도우 내 거래 2건 미만이면 건너뛴다. **1건짜리 고가 거래가 전고점이 되는 것을 막는다.**

**Step 3. 시간 감쇠**
2021년 고점과 2025년 고점은 같은 기준선이 아니다.
```
months_elapsed = (base_date − peak_date) in months
decay          = DECAY_FLOOR + (1 − DECAY_FLOOR) × exp(−months_elapsed / DECAY_TAU)
peak_price_adj = peak_price_raw × decay

DECAY_TAU   = 36.0   # 감쇠 스케일(개월)
DECAY_FLOOR = 0.80   # 감쇠 하한
```

**Step 4. 초과하락률**
```
drop_rate        = 1 − (median_price_3m / peak_price_adj)
excess_drop_rate = drop_rate − region_stats[scope='BELT'].median_drop_rate
```

**시장 전체가 20% 빠졌는데 이 단지도 20% 빠진 것은 신호가 아니라 베타다.** 시장 요인을 제거한 잔차만 팩터로 쓴다. 주식 퀀트의 residual momentum과 동일한 논리다.

기준선을 시군구가 아닌 **벨트(2구 통합)** 로 잡는 이유는 §9.2를 따른다.

**Step 5. 밸류 트랩 교차 조건 (알림 필터)**
초과하락률 단독으로는 매수 후보가 되지 않는다. 텔레그램 알림은 아래를 모두 충족해야 한다.
```
alert_candidate =
      excess_drop_rate  >= peer_percentile_70
  AND volume_ratio      >  1.0            # 거래량 회복
  AND listing_delta_30d <  0              # 매물 감소     (Phase 2~)
  AND supply_pressure   <  peer_median    # 입주물량 낮음 (Phase 2~)
```
**"싸진 것"과 "돌아서고 있는 것"이 동시에 성립할 때만 후보로 승격한다.**

> Phase 1에서는 `listing_delta_30d`, `supply_pressure`가 결측이다. 이 경우 해당 조건을 **PASS로 간주하지 않고 알림 자체를 보류한다** (C9). 알림 기능은 Phase 2부터 활성화한다.

### 8.4 D2 연식 곡선 — 선형 처리 금지

신축 프리미엄과 재건축 기대가 양 끝에 있고 중간 구간이 최저다.

```python
def age_score(age_years: float) -> float:
    """구간별 선형보간. 노드는 config에서 로드. 범위 밖은 클램프."""
    # (age, score)
    #   0 → 1.00   신축
    #   5 → 0.85
    #  15 → 0.45
    #  25 → 0.40   최저 구간
    #  32 → 0.70   재건축 기대 진입
    #  40 → 0.95
    #  50 → 1.00
```

---

## 9. 정규화 및 집계

### 9.1 비교군(Peer Group)

유니버스가 2개 구로 고정되므로 시도 단위 폴백은 성립하지 않는다. **2단계 구조 + 팩터별 스코프 분리**를 채택한다.

```python
PEER_LEVELS = {
    "UMD_AREA":  lambda r: (r.umd_cd, r.area_type),   # 법정동 × 평형
    "SGG_AREA":  lambda r: (r.sgg_cd, r.area_type),   # 시군구 × 평형
    "BELT_AREA": lambda r: (r.area_type,),            # 2구 통합 × 평형
}

def resolve_peer_group(target, universe, scope: str, min_n: int):
    """지정 스코프에서 N < min_n 이면 한 단계 넓은 스코프로 폴백.
       BELT_AREA에서도 미달이면 None → 게이트 G5 EXCLUDED."""
    order = ["UMD_AREA", "SGG_AREA", "BELT_AREA"]
    for level in order[order.index(scope):]:
        peers = [r for r in universe
                 if PEER_LEVELS[level](r) == PEER_LEVELS[level](target)]
        if len(peers) >= min_n:
            return f"{level}:{key}", peers
    return None, []
```

### 9.2 팩터별 정규화 스코프 (⚠️ 설계 핵심)

**모든 팩터에 동일한 비교군을 쓰면 안 된다.**

| 팩터 유형 | 예시 | 스코프 | 사유 |
| :-- | :-- | :--: | :-- |
| **변화율·비율형** | A1, A2, B1, B4 | `BELT_AREA` | 자기 기준 대비 변화이므로 절대 가격 수준에 둔감. 넓은 비교군이 표본만 키움 |
| **수준형** | A3, A4 | `SGG_AREA` | 넓게 잡으면 "싼 것"과 "입지가 나쁜 것"을 구분하지 못함 |
| **입지·품질형** | C, D 블록 | `BELT_AREA` | 입지 우열 자체가 신호. 지역 통제를 하면 안 됨 |

#### 구(區) 선택을 소거하지 말 것

초과하락률의 기준선을 `SGG_AREA`로 잡으면 **"서초구가 강남구보다 더/덜 빠졌는가"가 소거된다.** 사용자의 의사결정 범위에 구 선택이 포함되어 있으므로 `A1`의 기준선은 `BELT_AREA`로 둔다. 구별 중위값은 `region_stats`에 병행 저장하여 UI(§16.6)에서 참고 지표로만 노출한다.

> **일반 원칙 (P7)**: 정규화 스코프는 의사결정 스코프와 일치시킨다. 의사결정에 포함된 축을 정규화로 소거하면 그 축을 판단할 근거가 사라진다.

### 9.3 Robust z-score

```python
def robust_z(x: float, peers: Sequence[float], clip_at: float = 3.0) -> float | None:
    if len(peers) < MIN_PEER_N:
        return None
    med   = median(peers)
    mad   = median([abs(p - med) for p in peers])
    scale = 1.4826 * mad
    if scale < EPS:            # 분산 소실
        return 0.0
    return clip((x - med) / scale, -clip_at, clip_at)
```

평균/표준편차 대신 중위수/MAD를 쓰는 이유는 실거래 데이터의 이상치 내성이다.

### 9.4 블록 점수 (결측 처리)

```python
def block_score(factors: dict[str, float | None],
                weights: dict[str, float],
                min_coverage: int) -> tuple[float | None, float]:
    """결측 팩터는 제외하고 남은 가중치를 재정규화.
       0이나 평균으로 대체하지 않는다 (C5)."""
    available = {k: v for k, v in factors.items() if v is not None}
    if len(available) < min_coverage:
        return None, len(available) / len(factors)
    w_sum = sum(weights[k] for k in available)
    return (sum(available[k] * weights[k] for k in available) / w_sum,
            len(available) / len(factors))
```

### 9.5 최종 산식

```
# 1) 블록 가중합 (결측 블록 제외 후 재정규화)
Raw = Σ_b (w_b × Block_b) / Σ_b w_b

# 2) 유니버스 내 표준화 → 정규분포 CDF 매핑
Raw_z     = (Raw − mean(Raw_universe)) / std(Raw_universe)
BaseScore = Φ(Raw_z) × 100                 # 0~100, 중앙값 50

# 3) 리스크 승수
MarketScore = BaseScore × RiskMultiplier
```

**상한 캡(`min(100, ...)`)을 쓰지 않고 CDF 매핑을 쓰는 이유**: 캡에 걸리는 순간 상위권 내부의 순서 정보가 소실된다. 현행 v1에서 하락률 25% 이상이 전부 100점으로 붙는 문제가 이것이다.

**해석**: `MarketScore = 70`은 **"비교군 내 상위 30%"** 를 의미한다. 절대적 매력도가 아니다. UI 툴팁에 반드시 명시한다.

### 9.6 리스크 승수 (곱셈 감점)

| 조건 | 승수 | Phase |
| :-- | :--: | :--: |
| 전세가율이 비교군 하위 10% (역전세 위험) | × 0.80 | 2 |
| `supply_pressure` 비교군 상위 10% | × 0.70 | 2 |
| 정비사업 분쟁·소송 플래그 (수동) | × 0.50 | 3 |
| 해당 없음 | × 1.00 | — |

곱연산이며 중복 적용된다. **하한 0.35로 클램프**한다.

---

## 10. L2 매물 괴리 (Deal Gap)

### 10.1 계산식
```
기준가 = complex_area_stats.median_price_3m
       × floor_adj(floor_grade)
       × dong_adj(building_dong)      # Phase 3, 기본 1.0

deal_gap_pct = (1 − asking_price / 기준가) × 100
```

### 10.2 층 조정계수

| floor_grade | 정의 | `floor_adj` (초기값) |
| :-- | :-- | :--: |
| `LOW` | 1~3층 또는 최상층 | 0.95 |
| `MID` | 4층 ~ 총층수×0.6 | 1.00 |
| `HIGH` | 총층수×0.6 초과 (최상층 제외) | 1.03 |

Phase 3에서 `trades_sale`의 층·가격으로 단지별 회귀 추정하여 대체한다. 초기값은 **"가정"임을 `evidence_json`에 명시 기록**한다.

### 10.3 점수화하지 않는다
개별 호가는 표본 1건이므로 z-score를 계산할 근거가 없다. 괴리율(%)을 그대로 표시하고, 랭킹은 L1 점수로 하되 L2를 보조 축으로 병기한다.

---

## 11. 데이터 품질 게이트

### 11.1 HARD EXCLUDE

| ID | 조건 | `gate_reason` |
| :-- | :-- | :-- |
| `G1` | 최근 12개월 유효 실거래 < 3건 | `INSUFFICIENT_TRADES` |
| `G2` | 특수거래(직거래+해제) 비중 > 30% | `HIGH_SPECIAL_DEAL_RATIO` |
| `G2b` | 미등기 장기경과 비중 > 20% | `HIGH_UNREGISTERED_RATIO` |
| `G3` | `complex_key_map.confidence < 0.85` | `KEY_MATCH_FAILED` |
| `G4` | 좌표(`lat`/`lng`) 결측 | `NO_GEOCODE` |
| `G5` | 비교군 N < `MIN_PEER_N` (전 레벨 폴백 실패) | `NO_PEER_GROUP` |
| `G6` | `area_type` 미해석 | `AREA_TYPE_UNRESOLVED` |
| `G7` | 전체 팩터 커버리지 < 임계값 | `LOW_COVERAGE` |
| `V1`~`V6` | 가격 정합성 위반 (§11.5) | `PRICE_SANITY_FAILED` |

**제외된 단지는 삭제하지 않고 `gate_status='EXCLUDED'`로 `market_scores`에 적재한다.** UI에 별도 탭으로 노출하여 "왜 안 보이는지"를 확인할 수 있게 한다. **조용한 소실은 디버깅을 불가능하게 만든다.**

### 11.2 G2b — 미등기 장기경과

```
미등기_장기경과 = registry_date IS NULL
                  AND (base_date − deal_date) > UNREGISTERED_GRACE_DAYS(=180)
```

`해제사유발생일`은 **이미 취소가 확정된** 거래만 포착한다. 반면 등기일자 결측은 **아직 취소되지 않았으나 신뢰도가 낮은** 거래를 포착한다. 계약 후 6개월이 지나도록 소유권 이전등기가 없다면 실제 대금 지급이 이루어지지 않았을 가능성이 있으며, 과거 실거래가 조작(자전거래) 논란의 주된 판별 지표였다.

**§8.3 Step 1의 유효거래 필터에 우선 적용한다.** 고점을 형성한 거래가 미등기 상태로 방치되어 있다면 그 고점은 기준선으로 부적합하다.

최근 계약(6개월 이내)은 정상적으로 등기가 진행 중일 수 있으므로 제외하지 않는다. 백필 후 실제 등기 소요기간 분포를 확인하여 `UNREGISTERED_GRACE_DAYS`를 재산정한다.

### 11.3 SKIPPED 처리 (C9)
플래그 결측으로 판정이 불가능한 경우, **PASS가 아니라 `SKIPPED`로 기록**하고 `evidence_json`에 사유를 남긴다. 예: 2018~2020 구간 데이터에 거래유형이 없어 G2 판정 불가.

### 11.5 가격 정합성 검증 (V 게이트) — 신설

**v3.0에서 누락된 항목이다.** 조인 키가 깨지면 `호가 26.13억 / 기준가 8.65억 / 전고점 13.97억` 같은 물리적으로 불가능한 조합이 화면까지 올라온다. 이런 값이 한 번이라도 노출되면 나머지 숫자의 신뢰도까지 함께 무너진다.

**말이 안 되는 숫자는 표시하지 않는다. 계산 오차가 아니라 조인 실패의 징후로 취급한다.**

| ID | 조건 | 조치 | 검출하는 결함 |
| :-- | :-- | :-- | :-- |
| `V1` | `median_price_3m > peak_price_adj` | L1 EXCLUDED (`PRICE_SANITY_FAILED`) | 전고점 탐지 오류 |
| `V2` | `asking_price / median_price_3m` ∉ [0.6, 1.8] | 해당 매물 L2 미표시 | **area_type 조인 실패** |
| `V3` | 기준가 산출에 쓰인 거래의 `area_type`이 단일하지 않음 | L1 EXCLUDED | `WHERE area_type` 누락 |
| `V4` | `price_per_pyeong` 이 비교군 [P1, P99] 밖 | L1 EXCLUDED | 단지 오매칭 |
| `V5` | `trades_sale.sgg_cd` 가 `('11650','11680')` 밖인 행이 적재됨 | **적재 단계에서 예외** | C8 위반 |
| `V6` | 호가·기준가·전고점 중 하나라도 NULL 또는 ≤ 0 | 해당 매물 미표시 | 결측 전파 |

#### V2 위반 시 진단 절차 (필수 구현)
`V2` 위반은 **거의 항상 조인 키 문제**다. 위반 건은 로그에 아래를 함께 출력한다.

```
[V2 VIOLATION] complex_code=? area_type=? ratio=?
  호가측  : exclusive_area=?, area_type=?, source=naver
  기준가측: area_type=?, 산출 거래 수=?, exclusive_area 범위=[min, max]
  매칭    : match_method=?, confidence=?
```

`exclusive_area 범위`가 한 버킷에 몰려 있지 않으면 §4.3의 area_type 매핑 오류다.

#### 검증 시점
`V1`·`V3`·`V4`는 `build_stats.py` 직후, `V2`·`V6`는 `deal_gap.py` 직후에 실행한다. **UI 렌더링 시점이 아니라 산출 시점에 걸러야 한다** (C4).

### 11.5.1 단지 실재성 검증 (V7~V9) — 신설

가격만 검증해서는 §0.6.1 사례를 잡을 수 없다. **단지 자체가 말이 되는지**를 본다.

| ID | 조건 | 조치 | 검출 대상 |
| :-- | :-- | :-- | :-- |
| `V7` | 매물 전용면적이 `complexes.area_min_m2 ~ area_max_m2` 밖 | 제외 | **그 단지에 없는 평형** |
| `V9` | 연 실거래 건수 / 세대수 > 0.3 | 제외 | 단지 오매칭 |

`V7`이 §0.6.1의 직접 검출 게이트다. 단지 마스터에 전용면적 범위를 적재해야 한다(§7.1).

> **소규모 단지를 세대수만으로 제외하지 않는다.** §0.6.1 사례의 문제는 "15세대라서"가 아니라 "15세대에 실거래 3건이 붙어서"다. 회전율 이상은 `V9`가 잡는다. 강남권에는 재건축 초기 단계의 소규모 단지가 존재하며 이들이 후보에서 조용히 빠지면 안 된다.
>
> 대신 `total_households < 50` 인 단지는 §16.3의 주의 문장으로 처리한다 — `"세대수가 적어 거래가 드뭅니다. 가격 판단의 근거가 얇습니다"`.

### 11.5.2 run 단위 검증 (V10~V11) — 신설

개별 매물이 아니라 **실행 전체**를 검증한다.

| ID | 조건 | 조치 |
| :-- | :-- | :-- |
| `V10` | 4개 블록 점수가 전부 상위 10%인 매물이 존재 | **run 실패.** 정규화 미작동 |
| `V11` | 점수 중앙값이 **50 ± 5** 밖 | **run 실패** |<br>(2026-08-28 개정: 붕괴 검출은 V10 과 꼬리 비율 검사가 담당. 중앙값은 Φ 매핑 특성상 원점수가 치우치면 50 에서 벗어나며, 옛 허용폭 50±3 은 정상 실행을 반려했다)

**run이 실패하면 화면을 갱신하지 않는다** (C14). 이전 정상 run의 결과를 유지하고 사유를 §19.0 리포트에 기록한다.

### 11.6 상호 정합성 검증 (X1~X6) — 신설

**화면에 함께 표시되는 값들끼리 산수가 맞는지 검증한다.** §0.6.1의 "가격 메리트 100점 / 가격 매력 낮음 / +38.58%p" 모순이 이 검증의 부재로 통과했다.

| ID | 조건 | 검출 대상 |
| :-- | :-- | :-- |
| `X1` | 표시 하락률 ≠ `1 − 기준가/전고점` (오차 0.5%p 초과) | 계산 불일치 |
| `X2` | 표시 초과하락률 ≠ `하락률 − 시장중위` (오차 0.5%p 초과) | 기준선 불일치 |
| `X3` | 가격 블록 점수가 상위 20%인데 문장이 부정형 | 문장·점수 참조값 불일치 |
| `X4` | 문장이 참조하는 팩터가 `None` | 결측에 문장 생성 (C5 위반) |
| `X5` | 배지·라벨이 실제 값과 모순 (세대수 15에 "대단지") | 표시 로직 오류 |
| `X6` | 초과하락률로 역산한 시장 중위가 [−5%, +60%] 밖 | 부호·단위 오류 |

**`X3`~`X5`는 렌더링 직전에 실행한다.** 하나라도 걸리면 해당 매물을 렌더링하지 않고 리포트에 집계한다.

### 11.7 게이트 요약 리포트
매 실행 시 `score_runs`에 집계하고 로그 출력한다.
```
[RUN 20260729-0930] universe=612 passed=431 excluded=181
  INSUFFICIENT_TRADES     : 98
  KEY_MATCH_FAILED        : 34
  NO_PEER_GROUP           : 21
  HIGH_SPECIAL_DEAL_RATIO : 15
  HIGH_UNREGISTERED_RATIO :  8
  ...
```

---

## 12. 모듈 구조

```text
property-screener/
│
├── config/
│   ├── scoring_v3.yaml              # [신규] 가중치·임계값 전량
│   ├── regions.yaml                 # [신규] 대상 법정동 24개
│   └── lawd_codes.yaml              # [신규] 법정동명 ↔ 코드 매핑
│
├── data/
│   ├── raw/molit/<YYYY-MM-DD>/      # [신규] CSV 원본 아카이브
│   └── manual/                      # [신규] supply_schedule.csv 등
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
│   ├── molit_csv_loader.py          # [신규] CSV 파싱 (백필 주 경로)
│   ├── molit_client.py              # [신규] 오픈 API (증분, Phase 2)
│   ├── molit_schema.py              # [신규] CSV/API → CanonicalTrade
│   └── molit_ingest.py              # [신규] 정규화 → DB 적재 (경로 무관)
│
├── pc/
│   ├── keymap/
│   │   ├── matcher.py               # [신규] 5단계 단지 매칭
│   │   └── review_cli.py            # [신규] 수동 검수 CLI
│   │
│   ├── features/
│   │   ├── build_stats.py           # [신규] complex_area_stats 생성
│   │   ├── peak_detector.py         # [신규] robust 전고점 + 시간감쇠
│   │   ├── region_stats.py          # [신규] BELT/SGG 중위값
│   │   ├── factor_value.py          # [신규] Block A
│   │   ├── factor_flow.py           # [신규] Block B
│   │   ├── factor_location.py       # [신규] Block C
│   │   └── factor_quality.py        # [신규] Block D
│   │
│   ├── scoring/
│   │   ├── normalizer.py            # [신규] winsorize, robust_z, Φ
│   │   ├── gate.py                  # [신규] G1~G7 판정
│   │   ├── risk.py                  # [신규] RiskMultiplier
│   │   ├── aggregator.py            # [신규] 블록 가중합 + 재정규화
│   │   ├── evidence.py              # [신규] evidence_json 빌더
│   │   └── scorer_v3.py             # [신규] 진입점
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
│   ├── tools/
│   │   ├── match_review.py          # [신규] 매칭 수동 검수
│   │   └── column_coverage.py       # [신규] 연도별 결측률 산출 (§5.5)
│   │
│   └── web_app.py                   # [수정] §16 반영
│
└── tests/
    ├── fixtures/
    │   ├── molit_seocho_2026.csv    # 서초동 샘플 (파서 픽스처)
    │   └── example_case.json        # §15 계산 예시
    ├── test_area_mapper.py          # 경계값 50/70/100/135
    ├── test_molit_schema.py         # CSV↔API 동일 CanonicalTrade
    ├── test_peak_detector.py        # p90 윈도우 · 시간감쇠
    ├── test_matcher.py              # Tier 1~4 각각
    ├── test_peer_group.py           # 폴백 · 팩터별 스코프
    ├── test_normalizer.py           # MAD=0 엣지케이스
    ├── test_aggregator.py           # 결측 재정규화
    ├── test_gate.py                 # G1~G7 + SKIPPED
    └── test_pit_loader.py           # 미래참조 차단
```

### 12.1 공개 인터페이스 (C1 대상)

```python
# pc/scoring/scorer_v3.py
def run_scoring(base_date: str, config_path: str) -> ScoreRunResult:
    """L1 스코어링 전체 파이프라인. market_scores/score_runs 적재 후 요약 반환."""

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

# common/peer_group.py
def robust_z(x: float, peers: Sequence[float], clip_at: float = 3.0) -> float | None: ...
def resolve_peer_group(target, universe, scope: str, min_n: int) -> tuple[str | None, list]: ...

# common/area_mapper.py
def to_area_type(exclusive_area_m2: float) -> str | None: ...

# oci/crawler/molit_schema.py
def to_canonical(row: dict, source: Literal["CSV", "API"]) -> CanonicalTrade: ...
```

---

## 13. Config 명세 (`config/scoring_v3.yaml`)

```yaml
version: "3.0.0"

universe:
  target_sgg: ["11650", "11680"]        # 서초구, 강남구 — 확장 금지 (C8)
  min_peer_n: 20
  peer_levels: ["UMD_AREA", "SGG_AREA", "BELT_AREA"]

normalization:
  clip_at: 3.0
  mad_epsilon: 1e-9

blocks:
  value:
    weight: 0.35
    min_coverage: 2
    factors:
      excess_drop:   { weight: 0.45, direction:  1, peer_scope: BELT_AREA, phase: 1 }
      jeonse_ratio:  { weight: 0.32, direction:  1, peer_scope: BELT_AREA, phase: 1 }
      rent_yield:    { weight: 0.13, direction:  1, peer_scope: SGG_AREA,  phase: 1 }
      relative_ppp:  { weight: 0.10, direction: -1, peer_scope: SGG_AREA,  phase: 3 }
  flow:
    weight: 0.25
    min_coverage: 2
    factors:
      volume_ratio:      { weight: 0.30, direction:  1, peer_scope: BELT_AREA, phase: 1 }
      momentum_3m:       { weight: 0.20, direction:  1, peer_scope: BELT_AREA, phase: 1 }
      listing_delta_30d: { weight: 0.25, direction: -1, peer_scope: BELT_AREA, phase: 2 }
      supply_pressure:   { weight: 0.25, direction: -1, peer_scope: BELT_AREA, phase: 2 }
  location:
    weight: 0.20
    min_coverage: 2
    factors:
      subway_decay: { weight: 0.40, direction: 1, peer_scope: BELT_AREA, phase: 1 }
      elem_school:  { weight: 0.20, direction: 1, peer_scope: BELT_AREA, phase: 1 }
      cbd_access:   { weight: 0.40, direction: 1, peer_scope: BELT_AREA, phase: 3 }
  quality:
    weight: 0.20
    min_coverage: 2
    factors:
      households_log: { weight: 0.30, direction: 1, peer_scope: BELT_AREA, phase: 1 }
      age_curve:      { weight: 0.30, direction: 1, peer_scope: BELT_AREA, phase: 1 }
      brand:          { weight: 0.15, direction: 1, peer_scope: BELT_AREA, phase: 1 }
      far_score:      { weight: 0.25, direction: 1, peer_scope: BELT_AREA, phase: 3 }

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
  # 가격 정합성 (§11.5)
  ask_to_median_ratio_min: 0.6
  ask_to_median_ratio_max: 1.8
  ppp_percentile_min: 1
  ppp_percentile_max: 99
  max_special_deal_ratio: 0.30        # 백필 후 실분포 기준 재산정
  max_unregistered_ratio: 0.20
  unregistered_grace_days: 180
  min_key_confidence: 0.85
  min_total_coverage: 0.50            # Phase 1 실제 커버리지 0.667

risk_multipliers:
  jeonse_ratio_bottom_decile: 0.80
  supply_pressure_top_decile: 0.70
  redevelopment_dispute: 0.50
  floor: 0.35

l2:
  floor_adj: { LOW: 0.95, MID: 1.00, HIGH: 1.03 }

ui:
  area_labels:            # §16.2 표기 변환 (C10)
    A40:   "18평형 · 전용 40㎡"
    A59:   "25평형 · 전용 59㎡"
    A84:   "34평형 · 전용 84㎡"
    A114:  "44평형 · 전용 114㎡"
    A135P: "50평형 이상"
  sentence_thresholds:    # §16.3 문장 생성 (C11)
    price_gap_pct: 0.03
    excess_drop_strong: 0.05
    volume_ratio_recovery: 1.0
    volume_ratio_active: 1.3
    volume_ratio_stale: 0.6
    low_sample_count: 5
    low_coverage: 0.60
    subway_near_m: 400

alert:
  enabled_from_phase: 2               # Phase 1에서는 알림 비활성 (§8.3 Step 5)
  excess_drop_percentile: 70
  min_volume_ratio: 1.0
  max_listing_delta: 0.0
  min_market_score: 65
  min_deal_gap_pct: 5.0

backtest:
  data_start: "2018-01"
  lookback_months: 60
  forward_months: 12
  frequency: "Q"
```

---

## 14. 데이터 커버리지 및 백테스트 가용 범위

보유 데이터가 `2018-01 ~ 2026-07`이므로 백테스트 범위가 다음과 같이 확정된다.

```
최이른 base_date = 2018-01 + 60M(lookback) = 2023-01
최늦은 base_date = 2026-07 − 12M(forward)  = 2025-07

분기별 base_date:
  2023-01, 2023-04, 2023-07, 2023-10,
  2024-01, 2024-04, 2024-07, 2024-10,
  2025-01, 2025-04, 2025-07
                              → 총 11개 분기
```

**§18.3의 최소 요건(8분기)을 충족한다.** 추가 소급이 필요하면 2016~2017년 파일을 나중에 받아도 무방하다 — 해당 구간은 이미 확정된 데이터라 스냅샷 변동이 거의 없다.

**주의**: 2023-01 base_date의 lookback 구간(2018-01~2023-01)에는 §5.5의 플래그 결측 구간이 포함된다. 백테스트 리포트에서 `flag_coverage` 기준으로 결과를 분리 제시한다.

---

## 15. 계산 예시 (구현 검증 Fixture)

`tests/fixtures/example_case.json`으로 고정하고 회귀 테스트에 사용한다.

**대상**: 서초구 반포동 A단지, `area_type = A84`, `base_date = 2026-07-01`, Phase 1 팩터 구성

```
[Step 1] 유효 거래 필터
  전체 24건 → 해제 1, 직거래 2, 미등기장기 1 제외 → 20건
  special_deal_ratio  = 3/24 = 0.125   (< 0.30 → G2  PASS)
  unregistered_ratio  = 1/24 = 0.042   (< 0.20 → G2b PASS)
  sample_count_12m    = 9              (>= 3   → G1  PASS)

[Step 2] Robust 전고점
  단일 최대값        : 452,000 (만원)  ← 2024-08 직거래, 제외됨
  롤링 3M p90 최대값 : 441,000
  peak_date          : 2024-09

[Step 3] 시간 감쇠
  months_elapsed = 22
  decay          = 0.80 + 0.20 × exp(−22/36) = 0.80 + 0.20 × 0.5427 = 0.90854
  peak_price_adj = 441,000 × 0.90854 = 400,666

[Step 4] 하락률 / 초과하락률
  median_price_3m       = 385,000
  drop_rate             = 1 − 385,000/400,666 = 0.0391  (3.91%)
  BELT A84 median_drop  = 0.0620
  excess_drop_rate      = 0.0391 − 0.0620 = −0.0229     ← 시장 대비 덜 빠짐

[Step 5] A1 정규화
  peer_group = BELT_AREA:A84,  N = 340
  peers median(excess_drop) = −0.0050
  peers MAD                 =  0.0180
  scale = 1.4826 × 0.0180   =  0.02669
  z_A1  = (−0.0229 + 0.0050) / 0.02669 = −0.670

[Step 6] 블록 점수 (Phase 1: 10개 팩터 가용)

  Block A  Value      coverage 3/4
    z_A1 = −0.670 (w 0.45)   z_A2 = +0.850 (w 0.32)   z_A4 = +0.200 (w 0.13)
    w_sum = 0.90
    = (−0.3015 + 0.2720 + 0.0260) / 0.90 = −0.0039

  Block B  Flow       coverage 2/4
    z_B1 = +1.100 (w 0.30)   z_B4 = +0.350 (w 0.20)
    w_sum = 0.50
    = (0.3300 + 0.0700) / 0.50 = +0.800

  Block C  Location   coverage 2/3
    z_C1 = +1.250 (w 0.40)   z_C3 = −0.300 (w 0.20)
    w_sum = 0.60
    = (0.5000 − 0.0600) / 0.60 = +0.733

  Block D  Quality    coverage 3/4
    z_D1 = +0.900 (w 0.30)   z_D2 = −0.550 (w 0.30)   z_D4 = +0.600 (w 0.15)
    w_sum = 0.75
    = (0.2700 − 0.1650 + 0.0900) / 0.75 = +0.260

[Step 7] Raw (전 블록 가용 → 재정규화 불필요)
  Raw = 0.35×(−0.0039) + 0.25×(0.800) + 0.20×(0.733) + 0.20×(0.260)
      = −0.0014 + 0.2000 + 0.1466 + 0.0520
      = 0.3972

[Step 8] 커버리지 게이트
  총 커버리지 = 10/15 = 0.667   (>= 0.50 → G7 PASS)

[Step 9] 최종 점수
  universe mean(Raw) = 0.000,  std(Raw) = 0.420
  Raw_z       = 0.3972 / 0.420 = 0.9457
  BaseScore   = Φ(0.9457) × 100 = 82.8
  RiskMult    = 1.00   (Phase 1 미적용)
  MarketScore = 82.8

  해석: 강남벨트 A84 비교군 내 상위 17.2%
```

---

## 16. UI 명세 (`pc/web_app.py`)

### 16.0 설계 원칙 (⚠️ v3.0 실패 원인)

v3.0 UI는 테이블에 컬럼을 추가하는 방식으로 설계되어 다음 문제를 낳았다.

| 관측된 문제 | 원인 |
| :-- | :-- |
| 글자가 잘려 다음 줄로 넘어감 | 컬럼 과다. 680px 폭에 11개 컬럼 |
| 사용자가 판단을 내리지 못함 | **원시 숫자만 표시하고 해석을 제공하지 않음** |
| 코드성 데이터 노출 (`A114`, `complex_code`, 표본 수) | 내부 식별자와 진단값이 표시 계층으로 누출 |
| 세대수 등 기본 정보 부재 | 팩터로만 소비하고 표시하지 않음 |

**근본 원인은 정보량이 아니라 해석의 부재다.** 팩터가 정확히 계산되는지에만 집중하고, 그 숫자를 보고 사람이 무슨 판단을 하는지를 설계하지 않았다.

#### 원칙

| # | 원칙 | 적용 |
| :-- | :-- | :-- |
| **U1** | **숫자가 아니라 문장으로 표시한다** | `초과하락 +5.1%p` → `"강남권 평균보다 5%p 더 떨어졌습니다"` |
| **U2** | **1단계 화면에 코드성 데이터를 노출하지 않는다** | `area_type`, `complex_code`, `peer_group_key`, `run_id`, 표본 수, z-score 전부 금지 |
| **U3** | **계층을 3단으로 분리한다** | 카드 목록 → 매물 상세 → 벤치마크 |
| **U4** | **테이블 대신 카드를 쓴다** | 컬럼 잘림 구조적 해소 |
| **U5** | **진단값은 경고 문구로 변환한다** | `표본 4건` → `"거래가 드물어 기준가 신뢰도가 낮습니다"` |
| **U6** | **정합성 실패는 표시하지 않는다** | §11.5 위반 시 렌더링 제외 |

### 16.1 계층 구조

| 단계 | 화면 | 내용 | 숫자 노출 |
| :--: | :-- | :-- | :-- |
| **1** | 카드 목록 | 점수 1, 가격 2, 단지정보 3, 강점·주의 각 1줄 | 최소 |
| **2** | 매물 상세 | 팩터 기여도, 실거래 이력, 전세가율 추이, 게이트 상태 | 전체 |
| **3** | 벤치마크 | 구·평형별 분포, 단지 목록, 드릴다운 | 비교 맥락 |

### 16.2 Level 1 — 카드 목록 (기본 화면)

```
┌──────────────────────────────────────────────────┐
│ 반포 A아파트                                  83 │
│ 34평형 · 전용 84㎡ · 12층          강남권 상위 17% │
├──────────────────────────────────────────────────┤
│ 38.5억          최근 실거래 41.2억                │
│ 최근 실거래보다 2.7억 낮은 호가입니다              │
├──────────────────────────────────────────────────┤
│ 1,220세대 · 2004년 22년차 · 고속터미널역 도보 5분  │
├──────────────────────────────────────────────────┤
│ ↗ 강남권 평균보다 5%p 더 떨어졌는데,               │
│   거래량은 회복 중입니다                          │
│ ⚠ 전세가율이 낮아 하방 지지가 약합니다             │
│   (강남권 하위 20%)                              │
├──────────────────────────────────────────────────┤
│      [자세히 보기]      [네이버 부동산 ↗]         │
└──────────────────────────────────────────────────┘
```

#### 표시 항목 (이 외 금지)

| 영역 | 항목 | 원천 | 표기 규칙 |
| :-- | :-- | :-- | :-- |
| 헤더 | 단지명 | `complex_name` | |
| 헤더 | 평형 | `area_type` → **한글 통칭 변환** | `A84` → `34평형 · 전용 84㎡` |
| 헤더 | 층 | `floor` | |
| 헤더 | 점수 | `market_score` | 정수. 아래에 `"강남권 상위 N%"` 병기 |
| 가격 | 호가 | `asking_price` | 억 단위 소수 1자리 |
| 가격 | 기준가 | `median_price_3m` | **"최근 실거래"** 로 표기. "기준가"라는 내부 용어 금지 |
| 가격 | 해석 | 파생 | §16.3 규칙 |
| 정보 | 세대수·연식·역세권 | `complexes` | 아이콘 + 한 줄 |
| 판단 | 강점 1줄 | 파생 | §16.3 규칙 |
| 판단 | 주의 1줄 | 파생 | §16.3 규칙 |

#### 표기 변환표 (필수)

| 내부 값 | 화면 표기 |
| :-- | :-- |
| `A40` | `18평형 · 전용 40㎡` |
| `A59` | `25평형 · 전용 59㎡` |
| `A84` | `34평형 · 전용 84㎡` |
| `A114` | `44평형 · 전용 114㎡` |
| `A135P` | `50평형 이상` |
| `complex_code`, `peer_group_key`, `run_id` | **표시하지 않음** |
| `sample_count_12m` | **표시하지 않음** (경고로 변환, §16.3) |
| z-score, 블록 점수 | **Level 2에서만** |

### 16.2.1 표시 밀도 기준

**항목 수를 세지 않는다. 결과로 판정한다.**

> **판정 기준: 노트북 화면에서 스크롤 없이 카드 3~4개가 보여야 한다.**
> 넘치면 항목을 줄이거나 Level 2로 내린다. 어떤 항목을 줄일지는 구현 담당이 판단한다.

권장 구성은 §16.2 표를 따른다. 강점·주의 문장은 **각 최대 2줄**이되, **주의 사항이 존재하면 반드시 1줄 이상 표시한다** — 강점만 나열하면 확증편향을 증폭시킨다.

#### 금지 요소

| 요소 | 사유 |
| :-- | :-- |
| 이모지 | 정보 밀도 저하 |
| 진행 막대 (Level 1) | 대부분 꽉 차서 변별력 없음 |
| 게이트·검증 상태 | 통과는 기본 상태. 표시할 이유가 없다 |
| v1 점수 | 발주자와 무관한 개발용 값 |

#### 조건부 허용 — 배지·태그

§0.6.1에서 15세대 단지에 "대단지" 배지가 붙은 것은 **배지라는 형식이 아니라 데이터가 틀렸기 때문**이다. 형식을 금지하지 않고 조건을 건다.

| # | 조건 |
| :-- | :-- |
| B1 | `X5`(배지·라벨이 실제 값과 모순) 검증을 통과해야 렌더링한다 |
| B2 | **부정 배지를 표시할 수 있어야 한다.** 긍정 배지만 구현하면 사용 금지 |
| B3 | 배지 문구는 §16.9 어휘 규칙을 따른다 |
| B4 | 카드당 최대 3개 |

부정 배지 예시: `거래 드묾`, `소규모 단지`, `전세 자료 없음`, `구축`.

#### 결측 표시 (C13)
**결측 항목은 그 줄을 통째로 숨긴다.** 대체 문구·`-`·`N/A`·기본값 모두 금지. 숨긴 건수는 §19.0 리포트 4번에 집계한다.

### 16.3 문장 생성 규칙 (결정론적)

**LLM을 쓰지 않는다. 규칙 기반으로 구현한다.** 동일 입력에 동일 문장이 나와야 회귀 테스트가 가능하다.

#### 가격 해석 (1개)
```
gap = median_price_3m - asking_price
gap_pct = gap / median_price_3m

gap_pct >= 0.03   → "최근 실거래보다 {gap}억 낮은 호가입니다"
|gap_pct| < 0.03  → "최근 실거래와 비슷한 호가입니다"
gap_pct <= -0.03  → "최근 실거래보다 {|gap|}억 높은 호가입니다"
```

#### 강점 (최대 1줄, 우선순위 순 첫 번째)
```
1. excess_drop_rate >= +0.05 AND volume_ratio > 1.0
   → "강남권 평균보다 {x}%p 더 떨어졌는데, 거래량은 회복 중입니다"
2. excess_drop_rate >= +0.05
   → "강남권 평균보다 {x}%p 더 떨어졌습니다"
3. jeonse_ratio 상위 20%
   → "전세가율이 높아 실수요 지지가 탄탄합니다"
4. volume_ratio > 1.3
   → "최근 거래가 평소보다 활발합니다"
5. subway_dist_m <= 400
   → "{역명} 도보 {n}분 거리입니다"
6. (해당 없음) → 강점 줄 미표시
```

#### 주의 (최대 1줄, 우선순위 순 첫 번째)
```
1. sample_count_12m < 5
   → "거래가 드물어 기준가 신뢰도가 낮습니다"
2. jeonse_ratio 하위 20%
   → "전세가율이 낮아 하방 지지가 약합니다 (강남권 하위 20%)"
3. excess_drop_rate <= -0.05
   → "강남권 평균보다 덜 떨어져 가격 매력은 낮습니다"
4. volume_ratio < 0.6
   → "거래가 뜸해져 매도까지 오래 걸릴 수 있습니다"
5. coverage_ratio < 0.60
   → "일부 지표를 산출하지 못해 점수 신뢰도가 낮습니다"
6. age_years in [15, 28]
   → "재건축 기대는 이르고 신축 프리미엄은 지난 연식대입니다"
7. (해당 없음) → 주의 줄 미표시
```

> 강점·주의는 **각각 최대 1줄**이다. 여러 개를 나열하면 Level 1의 목적(빠른 선별)이 무너진다. 나머지는 Level 2에서 전부 보여준다.

### 16.4 Level 2 — 매물 상세

Level 1에서 `[자세히 보기]` 진입. **여기서 처음 숫자를 노출한다.**

| 섹션 | 내용 |
| :-- | :-- |
| 가격 요약 | 호가 / 최근 실거래 중위 / 조정 전고점 / 괴리율 |
| 실거래 이력 | 최근 24개월 산점도 + 3M 중위선 + 전고점선. 제외된 거래(직거래·해제·미등기)는 회색으로 구분 표시 |
| 점수 구성 | 4개 블록 기여도 막대. 클릭 시 팩터별 z-score 전개 |
| 전세가율 추이 | 최근 24개월 라인. 매매 중위가와 함께 이중축 |
| 단지 정보 | 세대수, 동수, 연식, 용적률, 브랜드, 역세권, 초등학교 |
| 데이터 품질 | 게이트 판정, 표본 수, 커버리지, 매칭 신뢰도, `SKIPPED` 사유 |

> 데이터 품질 섹션은 **접힌 상태(기본)** 로 두고 `[데이터 근거 보기]`로 펼친다. 필요한 사람만 본다.

### 16.5 Level 3 — 벤치마크 (드릴다운)

v3.0의 구 비교 패널은 정적 표여서 죽은 정보였다. **클릭 진입을 추가한다.**

```
[벤치마크] 34평형 기준

           중위 하락률   중위 평단가   중위 전세가율   단지 수
 서초구      −6.2%       7,120만/평     48.3%        42  →
 강남구      −8.7%       6,880만/평     51.1%        58  →
 ───────────────────────────────────────────────────────
 강남권      −7.6%       6,980만/평     49.8%       100

        [서초구 →] 클릭
              ↓
 서초구 34평형 단지 42곳
   정렬: 많이 떨어진 순 / 점수 순 / 평단가 순
   각 단지를 구 중위선 기준 막대로 표시
   단지 클릭 → Level 2 상세
```

**참고 지표이며 점수 계산에 영향을 주지 않음을 명시한다.**

### 16.6 [제외 매물] 탭
`gate_status='EXCLUDED'` 목록을 사유별 그룹화. 사유는 **한글 문장으로 변환**한다.

| `gate_reason` | 화면 표기 |
| :-- | :-- |
| `INSUFFICIENT_TRADES` | 최근 1년 실거래가 3건 미만입니다 |
| `HIGH_SPECIAL_DEAL_RATIO` | 직거래·취소 거래 비중이 높아 가격 신뢰도가 낮습니다 |
| `HIGH_UNREGISTERED_RATIO` | 등기가 완료되지 않은 거래가 많습니다 |
| `KEY_MATCH_FAILED` | 실거래 데이터와 연결하지 못했습니다 |
| `PRICE_SANITY_FAILED` | 가격 정보가 비정상이라 제외했습니다 |
| 기타 | 각각 문장으로 정의 |

### 16.7 [2차원 스캐터] 탭 (Phase 3)
X = 괴리율, Y = 시장점수, 점 크기 = 세대수, 색 = 지역. 우상단 사분면 하이라이트.

### 16.8 유지 항목
- 평형 필터 버튼: 유지하되 **한글 통칭**으로 표기 (`25평형` / `34평형` / `44평형 이상`)
- 매매가 슬라이더: 유지
- `[⚡ 즉시 재계산]`: L1 전체 재실행 + 신규 `run_id`. 1초 초과하므로 진행률 표시


### 16.9 어휘 규칙 — 사람이 쓰는 말

#### 판정 기준

> **부동산 중개인이 손님에게 그 말을 그대로 할 수 있는가?**
> 못 하겠으면 화면에 넣지 않는다. 바꿔 쓸 말이 없으면 그 정보 자체를 화면에서 뺀다.

`"L2가 없어서 exclude되었습니다"`는 사람이 쓰는 말이 아니다.

#### 적용 범위

| 대상 | 적용 |
| :-- | :--: |
| Level 1 카드 · Level 2 상세 · Level 3 벤치마크 | **전면 적용** |
| 텔레그램 알림 | **전면 적용** |
| §19.0 자가검증 리포트 | 사람 말 우선. 정확도가 필요하면 괄호 병기 허용 |
| 설계 문서 · 코드 · 로그 · 개발자 간 소통 | 미적용 |

#### 금지어 (사용자 화면 · 알림)

```
v1  v3  L1  L2  exclude  EXCLUDED  PASS  FAIL  gate  V-Gate  G1~G7
4-Block  block  factor  팩터  z-score  Φ  CDF  coverage  커버리지
area_type  A59  A84  A114  complex_code  run_id  peer_group
스코어링  파이프라인  robust  MAD  IC
momentum  valuation  quality  flow
```

#### 변환표

| 내부 표현 | 화면 표현 |
| :-- | :-- |
| `EXCLUDED: LOW_COVERAGE` | 확인할 수 있는 정보가 부족해 순위에서 뺐습니다 |
| `EXCLUDED: INSUFFICIENT_TRADES` | 최근 1년간 실제 거래가 거의 없어 가격을 판단하기 어렵습니다 |
| `EXCLUDED: KEY_MATCH_FAILED` | 실거래 자료와 연결하지 못했습니다 |
| `EXCLUDED: PRICE_SANITY_FAILED` | 가격 정보가 앞뒤가 맞지 않습니다 |
| `V-Gate PASS` | **표시하지 않음** (통과는 기본 상태) |
| `4-Block 퀀트 스코어 구성` | 평가 항목 |
| `가격 메리트 (Valuation)` | 가격 |
| `수급 및 거래 활성도 (Flow)` | 거래 상황 |
| `추세 모멘텀` | 최근 가격 흐름 |
| `커버리지 67%` | **표시하지 않음.** 부족하면 "판단 근거가 일부 부족합니다" |
| `강남권 초과하락률 +5.1%p` | 강남권 평균보다 5%p 더 떨어졌습니다 |
| `조정 전고점` | 가장 비쌌을 때 (2024년 9월) |
| `최근 실거래 중위 (3M)` | 최근 3개월 실제 거래가 |
| `V1 점수 20점` | **표시하지 않음** |

#### 검사 방법
화면·리포트·알림에 출력되는 **모든 문자열을 추출하여 금지어 목록과 대조**한다. 1건이라도 걸리면 완료 보고를 하지 않는다 (§19.1).

## 17. 텔레그램 알림 (`oci/notifier/telegram_bot.py`)

### 17.1 발송 조건
```
market_score  >= 65
AND deal_gap_pct >= 5.0
AND alert_candidate == True     (§8.3 Step 5)
AND gate_status == 'PASS'
AND property_id NOT IN sent_alerts
```

**Phase 1에서는 알림을 비활성화한다.** 밸류트랩 교차조건의 두 항목(`listing_delta_30d`, `supply_pressure`)이 결측이며, 이를 PASS로 간주하면 게이트가 무력화된다 (C9).

### 17.2 메시지 포맷
```
🏢 반포동 A단지 · 84㎡ · 12층

호가      38.5억  (기준가 41.2억 대비 −6.6%)
시장점수  82.8    (강남벨트 A84 상위 17.2%)
초과하락  +5.1%p  (시장 −6.2% / 단지 −11.3%)

강점  거래량 회복 1.4배 · 매물 −12% · 역세권 320m
주의  전세가율 하위 20% · 커버리지 67%

▸ 네이버 부동산 바로가기
```

**"주의" 라인을 반드시 포함한다.** 강점만 나열하면 확증편향을 증폭시킨다.

---

## 18. 검증 설계

### 18.1 Point-In-Time 로더 (C7)

```python
class PITLoader:
    def __init__(self, base_date: str): ...
    def trades(self, complex_code, area_type, lookback_months):
        """deal_date <= base_date 를 SQL 레벨에서 강제.
           위반 시 LookAheadError."""
```

**신고 지연 처리**

| 구간 | 처리 |
| :-- | :-- |
| CSV 스냅샷 축적 이전 | `deal_date + 30일 <= base_date` 근사. **한계임을 리포트에 명시** |
| CSV 스냅샷 축적 이후 | `first_seen_date <= base_date` 로 **실측 필터링** |

스냅샷을 매월 축적하면 근사 구간이 줄어든다. 또한 **스냅샷 차분으로 신고 지연 분포를 실측**할 수 있으므로, 근사 구간의 30일 상수를 실측 중위값으로 대체하는 것을 Phase 3에서 검토한다.

### 18.2 전방수익률
```
forward_return_12m = median_price_3m(base_date + 12M) / median_price_3m(base_date) − 1
```
`base_date + 12M`에 유효 거래 3건 미만이면 결측 처리(제외). **이 결측이 무작위가 아님**(거래 없는 단지 = 유동성 낮은 단지)을 인지하고 생존편향 방향을 리포트에 명시한다.

### 18.3 측정 지표

| 지표 | 정의 | 참고 합격선 |
| :-- | :-- | :-- |
| Rank IC | 분기별 Spearman(factor_z, forward_return) | 평균 > 0.03 |
| IC IR | mean(IC) / std(IC) | > 0.30 |
| 분위 스프레드 | Q5 − Q1 평균수익 | 11분기 중 7분기 이상 > 0 |
| 턴오버 | 분기별 상위 20% 교체율 | 참고용 |

### 18.4 백테스트 가능 범위 (⚠️ 한계)

| 팩터 | 백테스트 | 사유 |
| :-- | :--: | :-- |
| A1, A2, A4, B1, B4 | ✅ | 실거래 소급 가능 (2018~) |
| **B2 매물 증감률** | ❌ | **과거 스냅샷 부재.** 누적 시작일 이후만 |
| B3 입주물량 | △ | 수기 데이터 확보 범위 내 |
| C, D 블록 | △ | 시불변 가정 하에서만. 지하철 신설·재건축 진행 미반영 |
| A3 | ✅ | Phase 3 편입 판정용 |

**B2는 유의미한 팩터로 배치했으나 검증이 불가능하다.** 스냅샷 누적을 Phase 1부터 즉시 시작하고, 최소 4분기 축적 후 IC를 측정한다. 그 전까지 가중치 0.25는 근거 없는 가정이다.

### 18.5 v1 vs v3 회귀 비교
Phase 4에서 4주 병행 운영 후:
- 두 점수 간 Spearman 순위상관 (낮을수록 v3가 다른 정보를 담고 있다는 뜻)
- 각각의 상위 20%에 대한 12개월 전방수익률 비교
- v1 상위 / v3 하위 교집합 단지의 사후 성과 개별 검토

---

## 19. 완료 판정 및 Phase 로드맵

### 19.0 자가검증 리포트 (필수 산출물)

**매 실행 시 아래 리포트를 생성하여 발주자에게 제출한다. 코드·쿼리·로그를 대신 보여주지 않는다** (C12).

경로: `reports/self_check_YYYYMMDD.md`

```
■ 데이터 점검 결과 · 2026년 7월 30일

──────────────────────────────────────────
1. 얼마나 봤나

  살펴본 단지         612곳
  점수를 매긴 단지    431곳
  뺀 단지             181곳

  뺀 이유
    최근 1년 실거래가 3건 미만        98곳
    실거래 자료와 연결하지 못함       34곳
    비교할 만한 비슷한 단지가 부족    21곳
    직거래·취소 거래가 너무 많음      15곳
    가격 정보가 앞뒤가 안 맞음        13곳

──────────────────────────────────────────
2. 점수가 제대로 퍼져 있나

  중간 점수      47점        (정상: 45~55점)     ✓
  90점 이상      15곳 (8.3%)  (정상: 12% 이하)    ✓
  10점 이하      12곳 (6.6%)  (정상: 12% 이하)    ✓

  → 정상입니다

──────────────────────────────────────────
3. 이상한 게 있나

  발견된 이상 징후: 2건

  ① 15세대 단지가 상위 1%에 올라 있습니다
     대상: 금정노블 (서초구 반포동)
     원인: 붙어 있는 실거래 3건이 다른 단지 것으로 보입니다
     조치: 순위에서 제외했습니다

  ② 호가와 실거래 가격이 완전히 같은 매물 4건
     원인: 실거래 자료가 1건뿐이라 중간값이 그 1건과 같아졌습니다
     조치: 순위에서 제외했습니다

──────────────────────────────────────────
4. 화면에 안 보이는 정보

  전세 자료가 없어 전세 항목을 숨긴 단지      62곳
  세대수를 확인하지 못해 규모를 숨긴 단지     18곳

  → 이 단지들은 점수는 나오지만 판단 근거가 일부 빠져 있습니다

──────────────────────────────────────────
5. 예전 방식과 비교

  두 방식의 순위가 크게 다른 단지    23곳
  가장 차이가 큰 곳                 금정노블 (예전 20점 → 지금 99점)

  → 차이가 큰 곳은 확인이 필요합니다
```

#### 점수 분포 판정 기준 (v4.3 개정)

| 지표 | 정상 범위 | 근거 |
| :-- | :-- | :-- |
| 중앙값 | **45 ~ 55** | 2026-08-28 개정. 붕괴 검출은 V10 과 꼬리 비율 검사가 담당하며, 중앙값은 Φ 매핑 특성상 치우침에 따라 50 에서 벗어난다 |
| 90점 이상 비율 | **12% 이하** (상한만) | §9.5 Φ(CDF) 매핑은 정규분포를 균등분포로 바꾼다. 균등분포에서 상위 10%가 90점을 넘는 것이 정상이다 |
| 10점 이하 비율 | **12% 이하** (상한만) | 위와 같음(하위 꼬리) |

> 개정 전 기준은 상·하위 모두 `0~2%` 였다. 이는 점수를 원점수 그대로 쓰는
> 전제의 값으로, Φ 매핑과 양립하지 않는다. 옛 기준을 그대로 두면 정상 실행에도
> 매번 ✕ 가 찍힌다.
>
> **꼬리는 상한만 검사한다.** 꼬리가 두꺼운 것은 계산 붕괴 신호지만, 얇은 것은
> 문제가 아니다. "점수가 충분히 퍼져 있나"는 중앙값과 서로 다른 점수 개수가
> 이미 잡아준다. 또한 표본이 작으면 꼬리 비율이 크게 흔들려(181건이면 10%
> 꼬리의 표준편차가 약 2.2%p) 하한을 두면 정상 실행이 위반으로 찍힌다.
>
> 판정 코드는 `pc/verification/score_distribution.py` 한 곳에 있다.
> `python -m pc.verification.score_distribution` 으로 현재 분포와 판정을 볼 수 있다.

#### 작성 규칙

| # | 규칙 |
| :-- | :-- |
| R1 | **숫자에 "정상 범위"를 반드시 병기**한다. 숫자만으로는 좋은지 나쁜지 알 수 없다 |
| R2 | **판정(`✓`/`✕`)을 붙인다.** 발주자가 해석하게 두지 않는다 |
| R3 | 이상 징후는 **대상 · 원인 · 조치** 3종을 모두 적는다 |
| R4 | 이상 징후가 0건이면 "0건"이라고 쓴다. 항목을 생략하지 않는다 |
| R5 | 코드·쿼리·테이블명·컬럼명·예외 메시지를 쓰지 않는다 (C12) |

#### 이상 징후 자동 탐지 목록

| # | 탐지 조건 | 리포트 문구 |
| :-- | :-- | :-- |
| 1 | 세대수 < 50 인데 점수 상위 10% | "N세대 단지가 상위 N%에 올라 있습니다" |
| 2 | 호가 = 실거래 중위 (오차 1% 이내) | "호가와 실거래 가격이 완전히 같은 매물 N건" |
| 3 | 연 실거래 건수 / 세대수 > 0.3 | "세대수에 비해 거래가 지나치게 많습니다" |
| 4 | 매물 전용면적이 단지 면적 범위 밖 | "그 단지에 없는 평형입니다" |
| 5 | 점수 중앙값이 50 ± 5 밖, 또는 90점 이상/10점 이하 비율이 12% 초과 | "점수가 한쪽으로 몰려 있습니다" |
| 6 | 4개 블록이 모두 상위 10% | "모든 항목이 만점에 가까워 계산 오류가 의심됩니다" |
| 7 | v1 대비 점수 차이 > 40점 | "예전 방식과 결과가 크게 다릅니다" |
| 8 | 결측 팩터로 문장이 생성됨 | (내부 오류. 즉시 실패 처리) |

### 19.1 완료 판정 절차

**아래를 순서대로 통과해야 완료 보고를 한다. 하나라도 실패하면 보고하지 않는다.**

```
1. 금지어 검사 (§16.9)          화면·리포트·알림 문자열 전체 → 금지어 0건
2. run 단위 게이트 (§11.5.2)     V10, V11 통과
3. 이상 징후 검사 (§19.0)        8개 항목 전부 실행 → 리포트 기록
4. 상호 정합성 (§11.6)           X1~X6 위반 0건
5. 표시 요소 검사 (§16.2.1)      Level 1 항목 수 ≤ 10, 금지 요소 0건
6. AC 검사 (§19.2~)              각 항목 통과/미통과 명시
7. 리포트 제출 (§19.0)           reports/self_check_YYYYMMDD.md
```

#### 보고 형식

```
■ 작업 완료 보고

수정한 것
  · 점수가 한쪽으로 몰리던 문제를 고쳤습니다
  · 그 단지에 없는 평형이 섞이던 문제를 고쳤습니다
  · 전세 자료가 없는데 전세 설명이 나오던 문제를 고쳤습니다

확인한 것
  · 화면 문구가 모두 사람이 쓰는 말인지 확인했습니다        (통과)
  · 점수가 고르게 퍼져 있는지 확인했습니다                  (통과)
  · 화면 숫자끼리 계산이 맞는지 확인했습니다                (통과)

아직 안 된 것
  · (있으면 사람 말로 기재)

점검 결과는 첨부한 리포트를 봐주세요.
```

**"통과했습니다"만 쓰고 근거를 안 붙이면 그 보고는 무효다.**

### 19.2 Phase 로드맵 및 수용 기준(AC)

### Phase 1 — 기반 구축 + 10개 팩터 (핵심)

**범위**: 법정동 확장 · CSV 적재 · 단지 매칭 · L1/L2 분리 · 비교군 정규화 · 팩터 10종 · 게이트 · UI

| AC ID | 수용 기준 |
| :-- | :-- |
| **P1-AC1** | `config/regions.yaml`에 §3의 법정동 24개를 등록하고 크롤링 완료. 실제 단지 수를 로그 출력. `BELT_AREA` 레벨에서 `A59`/`A84`/`A114`별 N ≥ 20 검증. **미달 시 해당 area_type을 제외**하고 사유 기록(유니버스 확장 금지) |
| **P1-AC2** | CSV 백필 적재 완료. `sgg_cd IN ('11650','11680')` 필터가 적용되었음을 건수로 검증. 원본은 서울 전체가 `data/raw/molit/`에 보관 |
| **P1-AC3** | 연도별 × 컬럼별 결측률 표를 `docs/molit_column_coverage.md`에 기록. 거래유형·해제사유발생일·등기일자의 값 개시 연도 명시 (§5.5) |
| **P1-AC4** | `to_area_type()` 경계값 테스트 통과 (50.0 / 70.0 / 100.0 / 135.0) |
| **P1-AC5** | `to_canonical()`이 CSV 입력에 대해 `CanonicalTrade`를 정확히 산출. 인코딩·헤더 탐색·콤마 제거 각각 테스트 |
| **P1-AC6** | `complex_key_map` 매칭률(CONFIRMED) ≥ 95% (Tier 1/2 가용 시). 네이버에 지번/도로명이 없으면 ≥ 85% |
| **P1-AC7** | `peak_detector`가 §15 Step 2~3을 재현 (허용오차 ±0.5%) |
| **P1-AC8** | `resolve_peer_group`의 팩터별 스코프가 config대로 적용됨을 검증. 폴백 트리거 테스트 존재 |
| **P1-AC9** | 팩터 10종 산출. 총 커버리지 ≥ 0.60 인 단지가 전체의 70% 이상 |
| **P1-AC10** | `market_scores` 점수 분포의 중앙값이 50 ± 3 (Φ 매핑 정상 동작) |
| **P1-AC11** | 게이트 요약 리포트가 로그 출력되고 `score_runs`에 저장. `SKIPPED` 상태가 별도 집계됨 (C9) |
| **P1-AC12** | UI Level 1 카드 목록이 §16.2 표시 항목만 노출. **코드성 데이터(`area_type` 원값, `complex_code`, 표본 수, z-score) 0건**을 코드 grep + 화면 검수로 확인 (C10) |
| **P1-AC12b** | §16.3 문장 생성 규칙이 결정론적으로 구현되고, 규칙별 단위 테스트 존재. 강점·주의 각 최대 1줄 검증 (C11) |
| **P1-AC12c** | Level 2 매물 상세, Level 3 벤치마크 드릴다운 구현 (§16.4, §16.5) |
| **P1-AC12d** | §11.5 V1~V6 검증이 산출 시점에 실행되고, 위반 건이 화면에 노출되지 않음을 확인. V2 위반 로그 포맷 구현 |
| **P1-AC13** | v1 스코어러 병행 실행되어 `properties.score_v1`이 채워짐 |
| **P1-AC14** | 모든 외부 호출에 timeout 명시 (코드 grep 검증) |
| **P1-AC15** | `naver_crawler.py`가 실행 시마다 `listing_snapshots` 적재 (Phase 2 준비) |
| **P1-AC16** | 텔레그램 알림이 **비활성** 상태임을 확인 (§17.1) |

### Phase 2 — 수급 팩터 + 리스크 승수 + 알림

| AC ID | 수용 기준 |
| :-- | :-- |
| **P2-AC1** | `listing_snapshots` 30일 이상 누적 확인 후 B2 활성화. 미달 시 결측 반환 테스트 |
| **P2-AC2** | 입주물량 CSV 스키마 검증 및 로더 구현. 파일 부재 시 B3 결측(예외 아님) |
| **P2-AC3** | RiskMultiplier 3종 각각 적용 테스트. 하한 0.35 클램프 검증 |
| **P2-AC4** | 커버리지 12/15(0.80) 달성. 유니버스 통과율 ≥ 70% |
| **P2-AC5** | 텔레그램 알림 활성화. 밸류트랩 교차조건 적용 및 "주의" 라인 포함 |
| **P2-AC6** | 오픈 API 키 발급 후 `molit_client.py` 증분 갱신 동작. CSV/API 산출물 동일성 테스트 (`test_molit_schema.py`) |
| **P2-AC7** | `max_special_deal_ratio`를 백필 실분포 기준으로 재산정하고 근거 문서화 |

### Phase 3 — 입지 심화 + 검증 인프라

| AC ID | 수용 기준 |
| :-- | :-- |
| **P3-AC1** | CBD 대중교통 소요시간 API 확보 여부 판정. 불가 시 C2 제거 및 가중치 재분배 문서화 |
| **P3-AC2** | `PITLoader`가 base_date 이후 접근 시 `LookAheadError` 발생. 테스트 필수 |
| **P3-AC3** | 11분기 백테스트 실행 및 팩터별 Rank IC 리포트 생성 (§14). `flag_coverage` 기준 구간 분리 제시 |
| **P3-AC4** | **A3 편입 판정**. IC IR ≥ 0.30 이면 편입, 미만이면 제거하고 근거 문서화 |
| **P3-AC5** | 층 조정계수를 회귀 추정으로 대체. 추정 불가 단지는 상수 폴백 + evidence 명시 |
| **P3-AC6** | IC IR < 0.1 팩터를 식별하고 제거/가중치 조정 근거 문서화 (D4 브랜드 포함) |
| **P3-AC7** | 백테스트 리포트에 **거래비용 차감 시나리오 병기** (§20 L2) |

### Phase 4 — v1 폐기

| AC ID | 수용 기준 |
| :-- | :-- |
| **P4-AC1** | v1/v3 4주 병행 결과 리포트 (§18.5 전 항목) |
| **P4-AC2** | v3 단독 전환 결정 후 `scorer.py` deprecate 및 UI `v1점수` 컬럼 제거 |
| **P4-AC3** | 전체 파이프라인 1회 실행 소요시간 측정 및 문서화 |

---

## 20. 알려진 한계 및 비목표

**설계 단계에서 명시적으로 인정하고 시작하는 항목이다. 개발 AI는 이 한계를 우회하려는 코드를 작성하지 말 것.**

### L1. 알파 모델이 아니라 스크리닝 도구다
`market_score` 상위 = 매수 신호가 아니다. **수백 개 단지·평형을 임장 후보 20개로 좁히는 것**이 이 시스템의 역할이다. UI 어디에도 "추천", "매수" 문구를 넣지 않는다.

### L2. 거래비용이 팩터 알파를 압도할 가능성이 높다
취득세 + 중개수수료 + 양도세 왕복 비용이 수 %~10%대다. 백테스트에서 연 3~4%p 초과수익이 나와도 실전 순수익은 음수일 수 있다. **백테스트 리포트에 거래비용 차감 시나리오를 반드시 병기한다** (P3-AC7).

### L3. 분산이 불가능하다
상위 100개 랭킹의 통계적 우위는 100개를 전부 보유할 때 성립한다. 실제로는 1채를 산다. **표본 1개에는 모델이 관측하지 못하는 개별 요인(누수, 이웃, 학군 배정 변경, 소음)이 팩터 효과보다 크게 작용한다.**

### L4. 호가와 실거래의 시차
`deal_gap_pct`는 호가(실시간)와 실거래 중위값(최대 3개월 지연)의 비교다. 급변 국면에서는 기준가가 낡았을 수 있다. **하락 국면에서 괴리율 과대 계상, 상승 국면에서 과소 계상.**

### L5. 신고 지연 편향
국토부 실거래는 계약일 기준 30일 이내 신고 의무이나 실제 공개는 더 늦다. 최근 1~2개월 데이터는 불완전하며, 고가 거래가 상대적으로 늦게 신고되는 경향이 있다면 `median_price_3m`의 최근 구간에 **하방 편향**이 생긴다. §18.1의 스냅샷 차분이 이 편향을 측정할 수 있는 유일한 수단이다.

### L6. 소형·대형 평형은 표본이 부족할 수 있다
`A59`/`A84`/`A114`는 충분할 것으로 예상되나, `A40`·`A135P`는 강남권 재고 구성상 얇을 가능성이 있다. **미달 시 해당 평형을 스코어링 대상에서 제외한다.** 표본을 채우려고 유니버스를 확장하지 않는다.

### L7. 강남권 전체의 밸류에이션은 알 수 없다
유니버스가 서초구+강남구로 한정되므로 모든 점수는 **"강남권 안에서의 상대 순위"** 다. `MarketScore = 85`는 "강남권 상위 15%"일 뿐 **"지금이 살 때"가 아니다.**

시장 진입 타이밍은 이 모델 밖의 판단이다. 필요하면 한국부동산원 지수 등을 UI에 참고용으로 병기하되 **점수 계산에는 투입하지 않는다** — 투입하면 모든 단지 점수가 함께 움직여 순위 정보가 사라진다.

> 서울 전체 원본 CSV를 보유하고 있으므로 서울 대비 상대 위치를 **참고 지표로 표시**하는 것은 가능하다. 그러나 이는 표시 전용이며 스코어에 반영하지 않는다 (C8).

### L8. 강남권 내부 이질성이 수준형 팩터를 오염시킨다
압구정·반포와 세곡·내곡은 같은 유니버스에 있으나 사실상 다른 시장이다. §8.2의 실데이터가 보여주듯 **단일 구·단일 평형 안에서도 1.77배 격차**가 존재한다. 평단가·임대수익률 같은 수준형 팩터는 이 격차를 "저평가"로 오독한다. `A3`를 Phase 3로 미루고 `A4`를 SGG 스코프로 좁힌 것이 부분적 대응이며, **완전한 해소는 아니다.**

### L9. B2는 검증 불가 상태로 배치된다
과거 스냅샷이 없어 IC 측정이 최소 4분기 뒤에나 가능하다. 그 전까지 가중치 0.25는 근거 없는 가정이다.

### L10. 점수는 선별 신호이지 설명이 아니다
`market_score`는 비교군 백분위일 뿐, 그 단지를 왜 사야 하는지를 설명하지 않는다. §16.3의 문장 생성은 **가장 두드러진 요인 하나를 골라 말로 옮긴 것**이지 인과 설명이 아니다. 사용자는 Level 2에서 근거를 직접 확인해야 하며, UI는 그 확인을 유도하도록 설계되어야 한다.

### L11. 플래그 결측 구간의 필터 비대칭
2018~2020 구간은 거래유형·해제·등기 플래그가 없거나 불완전할 수 있다(§5.5). 이 구간을 lookback에 포함하는 base_date의 전고점은 **필터가 약한 상태로 산출**된다. p90 롤링 윈도우가 1차 방어를 하지만 완전하지 않다.

---

## 21. 구현 우선순위

**선행 항목 미완 상태에서 후행 항목에 착수하지 않는다.**

```
0.  [선행] Q1 확인 — 네이버 응답의 전용면적 / 지번·도로명    ← §22
1.  common/area_mapper.py + 테스트              ← 여기가 틀리면 전부 무의미
2.  DB 마이그레이션 (schema_version 포함)
3.  oci/crawler/molit_schema.py                 ← CanonicalTrade 계약 확정
4.  oci/crawler/molit_csv_loader.py             ← 백필. API 키 불필요
5.  oci/crawler/molit_ingest.py + 원본 아카이빙 + sgg 필터(C8)
6.  pc/tools/column_coverage.py                 ← P1-AC3
7.  pc/keymap/matcher.py + review_cli.py        ← 수동 검수 1회
8.  pc/features/peak_detector.py + 테스트
9.  pc/features/region_stats.py (BELT/SGG 양쪽)
10. pc/features/build_stats.py
11. common/peer_group.py + 테스트 (팩터별 scope)
12. pc/features/factor_*.py (Block A~D)
13. pc/scoring/normalizer.py, gate.py, aggregator.py, evidence.py
14. pc/scoring/scorer_v3.py
15. pc/l2/deal_gap.py
16. pc/web_app.py UI (§16.1, 16.2, 16.3, 16.6)
17. naver_crawler.py — listing_snapshots 적재 (Phase 2 준비)
─────────────────── Phase 1 완료 ───────────────────
18. oci/crawler/molit_client.py                 ← API 키 확보 후
19. Phase 2 팩터 (B2, B3) + 리스크 승수 + 알림
20. Phase 3 백테스트 + IC + A3 판정
```

---

## 22. 미해결 사항

| # | 항목 | 필요한 확인 | 영향 |
| :-- | :-- | :-- | :-- |
| **Q1** | **네이버 크롤러 응답 필드** | ① 매물의 **전용면적(㎡)**<br>② 단지의 **지번(본번/부번) 또는 도로명** | ①없으면 L1↔L2 조인 불가 → §10 전체 무효<br>②없으면 매칭 Tier 3부터 → 수동 검수 15~20% |

**Q1은 Phase 1 착수 전 반드시 확인한다.** 크롤러 응답 1건을 덤프하여 두 항목을 동시에 확인할 수 있다.

### 해결된 항목 (참고)

| # | 항목 | 결정 |
| :-- | :-- | :-- |
| ~~대상 지역 범위~~ | 서초구+강남구 2개 구 확정. 법정동 24개 전체 활성화 (§3) |
| ~~CSV vs API~~ | CSV 백필(완료) + API 증분(Phase 2). CSV가 임계 경로 (§5) |
| ~~해제·거래유형 컬럼 유무~~ | 모두 존재 확인. API 폴백 불필요 (§5.2) |
| ~~지번주소 vs 도로명주소~~ | 지번주소 선택. 본번·부번·도로명 동시 확보 (§5.1) |
| ~~데이터 기간~~ | 2018-01 ~ 2026-07 확보. 백테스트 11분기 가용 (§14) |
| ~~CBD 접근성 API~~ | Phase 3로 이연. 확보 불가 시 C2 제거 (§8.2) |
| ~~백테스트 실행 위치~~ | PC(RTX 4070) 배치. OCI는 수집·알림 전담 |
