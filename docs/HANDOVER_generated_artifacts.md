# 생성물(build artifact)의 Git 추적 문제 — 처리 완료 기록

> 제기: 2026-08-15 (맥 환경 셋업 중 발견) · **처리 완료: 2026-08-16 (발주자 판단 반영)**

## 1. 무엇이 문제였나
`pc/viewer/report.html` 과 루트의 `ml_results.json` 은 **생성물인데 git에 추적**되고 있었고,
`start.bat` / `start.sh` 기동 시마다 `report.html` 이 재생성되어 **매 실행마다 작업 트리가 더러워졌습니다.**

내용은 `screener.db`(gitignore 대상)에서 만들어지므로, 커밋된 파일은 특정 PC의 로컬 데이터 스냅샷이었습니다.
PC ↔ 맥 양쪽에서 실행하면 20만 자 규모의 HTML diff가 상시 충돌합니다.

## 2. 조사 결과 — 최초 우려는 사실이 아니었음
초안에서 "`sync_manager.py` 가 `ml_results.json` 을 매개로 OCI에 전달하므로 추적 해제 시 영향 확인 필요"라고 적었으나,
확인 결과 **그런 전달 경로는 존재하지 않았습니다.**

- `SyncManager.download_db()` / `upload_results()` 는 전송을 하지 않는 스텁이었습니다. 코드베이스 전체에 SFTP/SCP 구현이 없고, `.env.example` 의 `OCI_SSH_*` 4개 변수는 읽는 코드가 없습니다.
- OCI의 텔레그램 봇(`oci/notifier/telegram_bot.py`)은 `ml_results.json` 을 **열지 않습니다.** `screener.db` 의 `properties` / `market_scores` / `complex_area_stats` / `sent_alerts` 를 직접 조회합니다.
- OCI는 `git clone` 후 자체적으로 크롤링해 **자기 `screener.db` 를 만들어** 동작합니다.

**오판의 원인은 코드와 어긋난 주석 및 조용히 통과하는 스텁이었습니다.** 그래서 아래 4번을 함께 처리했습니다.

## 3. 처리 내역

### (A) 출력 위치 이동 — `pc/` 아래에 생성물을 두지 않음
| 이전 | 이후 |
| :-- | :-- |
| `pc/viewer/report.html` | `reports/report.html` |
| `ml_results.json` (루트) | `reports/ml_results.json` |

반영: `pc/viewer/generate_report.py`(입·출력), `pc/ml_engine/scorer.py`(출력).

### (B) 추적 해제
`git rm --cached` 로 두 파일의 추적을 해제하고 `.gitignore` 에 추가했습니다.
```
reports/*.html
reports/ml_results.json
```
`reports/self_check_*.md` 는 점검 이력이므로 **추적을 유지**합니다.

### (C) 기동 시 생성 제거
`start.sh` / `start.bat` 에서 리포트 생성 단계를 뺐습니다(단계 `[0..4]` → `[0..3]`). 웹 대시보드는 이 파일을 쓰지 않습니다.
삭제가 아니라 온디맨드 명령으로 분리했습니다.
```bash
python -m pc.viewer.generate_report
```

### (D) 오해를 만든 코드 정리
- `oci/main.py` 의 `# ... ml_results.json 기반` 주석을 실제 동작(`screener.db` 조회)대로 수정.
- `pc/sync/sync_manager.py`: `download_db()` / `upload_results()` 가 호출 시
  `NotImplementedError("OCI 동기화는 아직 구현되지 않았습니다")` 를 발생시키도록 변경.
  전송과 무관하던 로컬 폴백 로직은 `ensure_local_db()` 로 이름과 함께 분리했습니다.
- 설계 문서 §9 에 **§9.7 인프라·동기화 / 항목 29 (OCI 파일 동기화)** 를 추가했습니다.
  (기존 §9.7 진행 상태 표기법 → §9.8)

## 4. 남은 사항
`pc/main.py` 는 `SyncManager` 의 유일한 호출처였으므로 함께 정리했습니다.
`ensure_local_db()` 를 호출하고, 중복이던 업로드 단계는 제거했습니다
(`MLEngine.run()` 이 이미 `reports/ml_results.json` 을 직접 기록합니다).
