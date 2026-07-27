# OCI 무료티어 (Docker 미사용) Native 배포 가이드

OCI 무료티어(1GB RAM Micro VM 또는 ARM VM) 등 다른 무거운 프로젝트가 실행 중이어서 **Docker를 사용할 수 없는 환경**에 최적화된 Native 배포 가이드입니다.

---

## 1. OCI 서버에서 Git Clone 및 환경 설정

1. **Git 저장소 복제**:
   ```bash
   cd ~
   git clone https://github.com/사용자계정/property.git
   cd property
   ```

2. **환경 변수 파일 (`.env`) 생성**:
   ```bash
   nano .env
   ```
   ```env
   # 카카오맵 로컬 API REST API 키
   KAKAO_REST_API_KEY=발급받은_REST_API_KEY

   # 텔레그램 봇 토큰 및 채팅 ID
   TELEGRAM_BOT_TOKEN=텔레그램_봇_토큰
   TELEGRAM_CHAT_ID=텔레그램_채팅방_ID
   ```

---

## 2. 수동 1회 실행 테스트

제공된 Native 실행 스크립트(`deploy/oci_run.sh`)를 실행하면 Python 가상 환경 생성 및 패키지 설치, 크롤러 및 알림 파이프라인이 자동으로 동작합니다.
```bash
chmod +x deploy/oci_run.sh
./deploy/oci_run.sh
```

---

## 3. 주기적 실행 (CronJob 등록 방법 - 추천)

Docker 없이 가장 가볍게 정기 수집(예: 매일 아침 8시 및 오후 6시)을 하려면 `crontab`을 권장합니다.

```bash
crontab -e
```
아래 라인 추가 (매일 08:00, 18:00 실행 로그 기록):
```cron
0 8,18 * * * /home/ubuntu/property/deploy/oci_run.sh >> /home/ubuntu/property/oci_cron.log 2>&1
```

---

## 4. 항상 켜두는 상주 서비스로 등록 (Systemd - 선택 사항)

백그라운드에서 데몬으로 상주하게 하려면 아래 방법으로 systemd 서비스를 등록합니다.

```bash
sudo cp deploy/oci-property-screener.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oci-property-screener.service
sudo systemctl start oci-property-screener.service
```

* **서비스 상태 확인**: `sudo systemctl status oci-property-screener`
* **로그 실시간 확인**: `sudo journalctl -u oci-property-screener -f`
