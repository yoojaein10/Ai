# INSA 운영 배포 가이드

대상 시나리오: **사내 단일 호스트 — nginx(FE 정적 + /api 프록시) + uvicorn(BE) + 사내 MSSQL**

> 외부(Vercel) 배포는 BE를 공인망에 노출해야 하므로 HR PII 보호 차원에서 권장하지 않음. 본 문서는 사내망 단일 호스트 시나리오만 다룬다.

---

## 1. 아키텍처

```
사용자(사내 PC) ──HTTPS──▶ nginx (443)
                             ├─ /          → /var/www/insa/dist (Vite 빌드)
                             ├─ /api/*     → 127.0.0.1:8000 (uvicorn)
                             └─ /health    → 127.0.0.1:8000

                          uvicorn ──pyodbc──▶ 인사 MSSQL  (운영 — 별도)
                                              근태 ACSDB  (read-only)
                                              업무 apworksdw (read-only)
```

- **동일 origin** 이라 CORS 무관, refresh 쿠키 SameSite=Lax 유지 가능.
- 운영 DB는 개발 DB(`192.0.2.10/insa`, 계정 `dh`)와 **반드시 분리**.

---

## 2. 사전 준비

### 2.1 호스트 (Linux 가정)

| 항목 | 권장 |
|---|---|
| OS | Ubuntu 22.04 LTS / RHEL 8+ |
| CPU/RAM | 2 vCPU, 4 GB (160명 규모 기준) |
| 디스크 | 20 GB (로그 회전 포함) |
| Python | 3.11+ |
| nginx | 1.22+ |
| ODBC | `msodbcsql17` 또는 `msodbcsql18` |

### 2.2 디렉터리 레이아웃

```
/opt/insa/
├─ backend/
│  ├─ .venv/              # python -m venv
│  ├─ .env                # .env.production.example 기반 (chmod 600, owner: insa)
│  ├─ app/, alembic/, ...
│  └─ requirements.txt
└─ frontend/dist/         # 또는 /var/www/insa/dist 로 심볼릭 링크

/var/log/insa/
├─ backend.log
└─ backend.err.log
```

### 2.3 OS 사용자

```bash
sudo useradd -r -m -d /opt/insa -s /bin/bash insa
sudo mkdir -p /var/log/insa
sudo chown -R insa:insa /opt/insa /var/log/insa
```

---

## 3. 백엔드 배포

### 3.1 코드 배치 + 의존성

```bash
sudo -u insa -i
cd /opt/insa
git clone https://github.com/hi2ilwoo/INSA.git tmp && mv tmp/backend . && rm -rf tmp
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 환경변수

```bash
cp .env.production.example .env
chmod 600 .env
$EDITOR .env       # DB/JWT/AES_KEY 입력
```

- `JWT_SECRET_KEY` 생성: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- `AES_KEY` 생성: `python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"`
- **AES_KEY 변경 시 기존 EmpAccount.account_no_enc 모두 복호화 불가.** 회전 정책 사전 합의.

### 3.3 DB 마이그레이션

운영 DB에 모델 테이블이 이미 존재하면 baseline만 stamp:

```bash
alembic stamp head
```

신규 DB라면:

```bash
alembic upgrade head
python scripts/seed_eval.py    # 평가 회차/스케줄 시드 (idempotent)
```

> 평가 모듈 시드는 `insa_eval_round` / `insa_eval_schedule` 등을 검사한 뒤 비어있을 때만 입력하므로 재실행 안전.

### 3.4 systemd 서비스 등록

`docs/insa-backend.service` 파일 사용:

```bash
sudo cp /opt/insa/backend/docs/insa-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now insa-backend
sudo systemctl status insa-backend
curl http://127.0.0.1:8000/health   # {"status":"ok"} 확인
```

### 3.5 로그 회전

`/etc/logrotate.d/insa`:

```
/var/log/insa/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        systemctl reload insa-backend > /dev/null 2>&1 || true
    endscript
}
```

---

## 4. 프런트엔드 배포

### 4.1 빌드 (CI 또는 운영 호스트)

```bash
cd frontend
npm ci
npm run build       # dist/ 생성
```

### 4.2 정적 파일 배치

```bash
sudo mkdir -p /var/www/insa
sudo rsync -a --delete frontend/dist/ /var/www/insa/dist/
sudo chown -R nginx:nginx /var/www/insa
```

> 라우트별 코드 분할이 적용되어 있어 (`react-vendor`, `antd`, `antd-deps`, `query`, `vendor` + 47개 페이지 청크) 페이지 변경 시 해당 청크만 재다운로드된다.

### 4.3 nginx 설정

`docs/nginx.conf.sample` 참조. 핵심:

- `/assets/` → 1년 캐시 (해시 파일명)
- `/` → `try_files $uri /index.html` (SPA 폴백)
- `/api/` → `proxy_pass http://127.0.0.1:8000`, `client_max_body_size 50m` (엑셀 업로드)
- TLS 인증서는 사내 PKI 사용

```bash
sudo cp /opt/insa/backend/docs/nginx.conf.sample /etc/nginx/conf.d/insa.conf
$EDITOR /etc/nginx/conf.d/insa.conf      # 도메인/인증서 경로 수정
sudo nginx -t
sudo systemctl reload nginx
```

---

## 5. Windows 호스트로 배포하는 경우

OS만 다를 뿐 구조는 동일. 차이점:

| 영역 | Windows |
|---|---|
| 서비스 등록 | systemd 대신 [NSSM](https://nssm.cc/) 사용 |
| nginx | `C:\nginx` 풀어쓰기, 같은 conf 사용 가능 |
| 정적 파일 | `C:\inetpub\insa\dist` 등에 복사 |
| 로그 | NSSM이 stdout/stderr 회전 지원 (`AppRotateFiles=1`) |

NSSM 등록 예:

```
nssm install insa-backend "C:\opt\insa\backend\.venv\Scripts\python.exe"
nssm set insa-backend AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers"
nssm set insa-backend AppDirectory "C:\opt\insa\backend"
nssm set insa-backend AppEnvironmentExtra :PYTHONPATH=C:\opt\insa\backend
nssm set insa-backend AppStdout "C:\opt\insa\logs\backend.log"
nssm set insa-backend AppStderr "C:\opt\insa\logs\backend.err.log"
nssm set insa-backend AppRotateFiles 1
nssm set insa-backend AppRotateBytes 10485760
nssm start insa-backend
```

`.env` 대신 `nssm set ... AppEnvironmentExtra` 로 환경변수를 주입하거나, `python-dotenv` 가 자동 로딩하도록 `.env` 파일을 워킹 디렉터리에 둔다.

---

## 6. 배포 후 검증 체크리스트

- [ ] `curl https://insa.example.local/health` → `{"status":"ok"}`
- [ ] 브라우저에서 로그인 (HR_ADMIN) → `/hr/employees` 진입
- [ ] 평가 회차 목록 노출 (`/eval/rounds`)
- [ ] 권한 분리 검증 — EMPLOYEE 계정으로 `/admin/*` 차단 확인
- [ ] 엑셀 업로드 (교육 이수, 건강검진) 50MB 한계 동작
- [ ] nginx 로그에 `/assets/` 응답 코드 200 + Cache-Control 헤더 확인
- [ ] systemd: `systemctl status insa-backend` Active(running)
- [ ] 로그 회전: 다음날 `/var/log/insa/backend.log.1.gz` 생성 확인

---

## 7. 롤백

```bash
# 코드 롤백
cd /opt/insa/backend
git fetch && git checkout <previous-tag>
sudo systemctl restart insa-backend

# FE 롤백 (이전 빌드 디렉터리 보존 시)
sudo rsync -a --delete /var/www/insa/dist.prev/ /var/www/insa/dist/
```

배포 직전에 `cp -a dist dist.prev` 백업 권장.

---

## 8. 시크릿 회전

| 시크릿 | 회전 주기 | 영향 |
|---|---|---|
| `JWT_SECRET_KEY` | 90일 | 모든 사용자 즉시 로그아웃 (refresh 토큰 무효) |
| `AES_KEY` | 변경 불가 (생성 후 고정) | 변경 시 EmpAccount 전체 복호화 불가 — 마이그레이션 절차 별도 필요 |
| DB 패스워드 | 정책에 맞게 | `.env` 수정 후 `systemctl restart insa-backend` |

---

## 9. 모니터링 권장

- nginx access/error 로그를 사내 SIEM에 흘리거나 `goaccess` 로 일별 리포트
- `/health` 를 1분 주기 외부 모니터링 (사내 Zabbix/Prometheus blackbox)
- DB 연결 풀 고갈 알람 — 향후 `/health` 에 DB ping 결과 포함하도록 확장 검토

---

## 10. 미해결 사항

- 운영 DB 호스트/계정 미정 — 인프라팀 확정 후 `.env` 입력
- 사내 PKI 인증서 발급 절차 미문서화
- 알림 시스템 (`알림(3)` placeholder) 운영 트리거 정책 미정
- `leave` / `benefit_event` / `attendance_export` 의 APW_DB/ATT_DB 운영 접근 권한 확보 필요
