# 서버 배포 시 설정 방법

배포 플랫폼(Render, basam.co.kr, VPS 등)에 basket-uncle을 올릴 때 필요한 설정을 정리한 문서입니다.

---

## 1. 필수 설정 요약

| 구분 | 값 |
|------|-----|
| **빌드 명령** | `pip install -r requirements.txt` |
| **시작 명령** | `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app` |
| **필수 환경 변수** | `FLASK_SECRET_KEY` (세션/쿠키 암호화용, 랜덤 문자열 권장) |

- `$PORT`는 호스팅이 제공하는 환경 변수 그대로 사용합니다. (Render는 자동 주입)
- 타임아웃 300초는 상품 대량등록·엑셀 업로드 등 긴 요청을 위해 필요합니다.

---

## 2. 환경 변수 (Environment Variables)

로컬은 프로젝트 루트의 **`.env`** 파일, Render 등은 **대시보드 → Environment**에 설정합니다.  
`.env.example`을 복사해 `.env`로 만든 뒤 값을 채우면 됩니다.

### 필수

| 변수명 | 설명 |
|--------|------|
| `FLASK_SECRET_KEY` | 세션·쿠키 암호화. **배포 시 반드시 랜덤 문자열로 설정.** (미설정 시 기본값 사용 → 보안 취약) |

### DB

| 변수명 | 설명 |
|--------|------|
| `DATABASE_URL` | 메인 DB. 미설정 시 `sqlite:///direct_trade_mall.db` (Render 재시작 시 SQLite는 초기화될 수 있음) |
| `DELIVERY_DATABASE_URL` | 배송 시스템 DB. 미설정 시 SQLite 사용 가능 |

- **영구 저장**이 필요하면 Render **PostgreSQL** 생성 후 연결 문자열을 `DATABASE_URL`에 넣습니다.

### 결제 (토스페이먼츠)

| 변수명 | 설명 |
|--------|------|
| `TOSS_CLIENT_KEY` | 결제창용 API 키 (ck_ 로 시작) |
| `TOSS_SECRET_KEY` | 시크릿 키 (테스트: test_sk_, 라이브: live_sk_) |
| `TOSS_CONFIRM_KEY` | (선택) 웹훅 서명 검증용 |

- 라이브 결제 시 토스 개발자센터에 **리다이렉트 URL**·**결제 요청 허용 도메인** 등록 필요.

### 선택 기능

| 변수명 | 설명 |
|--------|------|
| `SITE_URL` | 실서비스 URL (끝에 `/` 없이). 예: `https://your-app.onrender.com` |
| `CLOUDINARY_URL` | 이미지 업로드(상품·리뷰·게시판·자유게시판 사진/동영상 등)를 클라우드에 저장. **설정 시 재배포해도 이미지 유지** |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | 푸시 알림 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 로그인 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | 구글 로그인 |
| `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET` | 카카오 로그인 |
| `OAUTH_REDIRECT_BASE` | 소셜 로그인 콜백 기준 URL (보통 `SITE_URL`과 동일) |
| `KAKAO_MAP_APP_KEY` | 배송구역 지도 |
| `MASTER_ADMIN_EMAIL` | 마스터 관리자 이메일 (DB 초기화 등 일부 기능 제한용) |
| `SOLAPI_*` | 솔라피(Solapi) 카카오 알림톡 (문자/알림톡 발송) |

### 백업 (매일 새벽 4시 자동 백업)

| 변수명 | 설명 |
|--------|------|
| `BACKUP_CRON_SECRET` | Cron이 `/admin/backup/cron` 호출 시 쿼리 `key` 값과 일치해야 함 |
| `BACKUP_APP_URL` | **Cron 서비스 전용.** 백업을 호출할 앱 URL (예: `https://basket-uncle.onrender.com`) |
| `GITHUB_BACKUP_TOKEN` | GitHub Personal Access Token (repo 권한). 설정 시 백업 zip을 Release로 업로드 |
| `GITHUB_BACKUP_REPO` | 백업 저장소 (형식: `owner/repo`) |

---

## 3. Render 배포 절차

1. [dashboard.render.com](https://dashboard.render.com) 로그인
2. **New +** → **Web Service**
3. GitHub 리포지토리 **basket-uncle** 연결
4. 설정:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app`
5. **Environment** 탭에서 위 환경 변수 추가 (비밀키는 **Secret**으로)
6. **Create Web Service** 후 빌드 완료되면 배포 URL로 접속해 동작 확인

자세한 점검 항목은 **[DEPLOY.md](DEPLOY.md)**, **[RENDER_DEPLOY.md](RENDER_DEPLOY.md)** 참고.

---

## 4. "0.0.0.0에서 열린 HTTP 포트가 감지되지 않았습니다" 해결

호스팅에서 이 메시지가 나오면:

1. **시작 명령**이 `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app` 인지 확인
2. **시작/헬스체크 대기 시간**을 **60초 이상**(권장 90~120초)으로 설정
3. 저장 후 **재배포**

상세 체크리스트는 **[HOSTING_DASHBOARD.md](HOSTING_DASHBOARD.md)** 참고.

---

## 5. 배포 후 확인

- [ ] 메인 페이지(/) 접속
- [ ] 로그인·회원가입
- [ ] 결제 테스트 (토스 키 설정 시)
- [ ] 관리자 `/admin` 접속
- [ ] 배송 시스템 `/logi` 접속 (배송 DB 사용 시)

---

## 6. 참고 문서

| 문서 | 내용 |
|------|------|
| [DEPLOY.md](DEPLOY.md) | 1차 배포 점검, 환경 변수 표, 백업 전략 |
| [RENDER_DEPLOY.md](RENDER_DEPLOY.md) | Render 배포 전 점검·순서 |
| [HOSTING_DASHBOARD.md](HOSTING_DASHBOARD.md) | 포트·시작 명령·헬스체크, Cloudinary·토스 방화벽 |
| [BACKUP_SETUP.md](BACKUP_SETUP.md) | 매일 새벽 4시 자동 백업 (cron-job.org / GitHub Actions / Render Cron) |
| [.env.example](.env.example) | 환경 변수 예시 (복사 후 `.env`로 저장해 사용) |

---

## 7. 한 줄 요약

**시작 명령:** `gunicorn --bind 0.0.0.0:$PORT --timeout 300 app:app`  
**필수 환경 변수:** `FLASK_SECRET_KEY`  
**영구 DB:** Render PostgreSQL 연결 후 `DATABASE_URL` 설정  
**이미지 유지:** `CLOUDINARY_URL` 설정 시 재배포해도 업로드 이미지 유지
