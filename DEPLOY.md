# 1차 GitHub 업로드 & Render 배포 점검

## 1. 점검 사항 (배포 전)

- [x] **.gitignore** – `.env`, `*.db`, `__pycache__/`, `instance/` 제외
- [x] **requirements.txt** – 패키지만 포함, `gunicorn` 포함 (메모는 PROJECT_MEMO.txt로 분리)
- [x] **비밀키** – 코드에 하드코딩 없음, `os.getenv()` 사용
- [ ] **.env** – 로컬에만 두고 **절대 커밋하지 않기**
- [ ] **DB 파일** – `*.db`는 .gitignore에 있으므로 업로드 안 됨

## 2. 환경 변수 (Render Dashboard에 설정)

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `FLASK_SECRET_KEY` | ✅ | 세션/쿠키 암호화 (랜덤 문자열 권장) |
| `DATABASE_URL` | ⚠️ | SQLite 쓰면 생략 가능(휘발). 영구 DB는 PostgreSQL 연결 |
| `DELIVERY_DATABASE_URL` | ⚠️ | 배송 DB. SQLite 쓰면 `sqlite:///delivery.db` 등 |
| `TOSS_CLIENT_KEY` | ✅ | 토스 결제 (결제 사용 시) |
| `TOSS_SECRET_KEY` | ✅ | 토스 결제 시크릿 |
| `KAKAO_MAP_APP_KEY` | 선택 | 배송구역 지도 |
| `VAPID_PUBLIC_KEY` | 선택 | 푸시 알림 |
| `VAPID_PRIVATE_KEY` | 선택 | 푸시 알림 |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS` | 선택 | 판매자 발주 이메일 발송 (관리자 → 판매자 요청). **이메일 키 받는 방법**: 프로젝트 내 `EMAIL_SETUP.md` 또는 관리자 화면 **이메일 키 설정 안내** 링크 참고 |
| `SITE_URL` | 선택 | 판매자 확인 링크에 사용 (예: `https://your-app.onrender.com`). 없으면 요청 URL 기준으로 생성 |
| `GITHUB_BACKUP_TOKEN` | 선택 | GitHub Personal Access Token (repo 권한). 설정 시 백업 zip을 해당 저장소 Release로 업로드 |
| `GITHUB_BACKUP_REPO` | 선택 | 백업 대상 저장소 (형식: owner/repo). 예: myid/basket-uncle |
| `BACKUP_CRON_SECRET` | 선택 | 매일 새벽 4시(KST) Cron이 `/admin/backup/cron` 호출 시 쿼리 key 값. Web·Cron 서비스 둘 다 동일 값 설정 |
| `BACKUP_APP_URL` | 선택 | **Cron 서비스 전용.** 백업 호출 대상 URL (예: `https://basket-uncle.onrender.com`) |

## 2-1. 백업 전략 (인프라·외부·법적)

| 구분 | 설명 |
|------|------|
| **Render 자동 백업 (인프라 레벨)** | `render.yaml`의 Cron 서비스가 매일 **04:00 KST**에 Web 서비스의 `GET /admin/backup/cron?key=BACKUP_CRON_SECRET` 호출. Cron 서비스에 `BACKUP_APP_URL`, `BACKUP_CRON_SECRET` 환경변수 설정 필요. |
| **pg_dump + 외부 저장소** | `DATABASE_URL`이 PostgreSQL이면 `pg_dump`로 전체 덤프 후 zip에 포함. `GITHUB_BACKUP_TOKEN`·`GITHUB_BACKUP_REPO` 설정 시 동일 zip을 GitHub Release로 업로드 → **Render 계정/DB가 날아가도 복구 가능.** (Web 서버에 `postgresql-client`가 없으면 pg_dump 실패. 이 경우 프로젝트 루트의 `Dockerfile.backup` 참고해 Docker 빌드로 전환하거나, 수동 백업 시 로컬에서 pg_dump 실행 후 업로드.) |
| **엑셀/리포트 (법적·실무용)** | 매 백업 시 최근 30일 **수익 리포트 CSV**가 zip 내 `reports/revenue_report_30d.csv`로 포함. 관리자 화면에서 기간별 수익통계·주문 엑셀 다운로드로 별도 기록용 백업 가능. |

**배포 환경에서 매일 새벽 4시 자동 백업 설정**은 → **[BACKUP_SETUP.md](BACKUP_SETUP.md)** 참고 (cron-job.org / GitHub Actions / Render Cron 단계별 안내).

## 3. GitHub 1차 업로드

```bash
cd c:\Users\new\Documents\GitHub\basket-uncle

# 상태 확인 (.env, *.db 제외되는지)
git status

# 전부 스테이징
git add .

# .env가 올라가면 안 됨
git status

git commit -m "1차: PWA, 메시지/푸시, 바로가기 안내, 배포 설정"
git branch -M main
git remote add origin https://github.com/본인아이디/basket-uncle.git
git push -u origin main
```

## 4. Render 배포

1. https://dashboard.render.com 로그인
2. **New +** → **Web Service**
3. **Connect repository** → GitHub에서 `basket-uncle` 선택
4. 설정:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT app:app`
   - **Environment:** 위 표의 환경 변수 추가 (비밀키는 Secret으로)
5. **Create Web Service** 후 빌드/배포 완료될 때까지 대기
6. 배포 URL로 접속해 동작 확인

## 5. 배포 후 확인

- [ ] 메인 페이지 로드
- [ ] 로그인/회원가입
- [ ] 결제 테스트 (토스 키 설정 시)
- [ ] 관리자 `/admin` 접속
- [ ] 푸시 알림 (VAPID 설정 시) – 마이페이지에서 「알림 켜기」

## 5-1. 보안 점검 요약

- **비밀키**: `FLASK_SECRET_KEY`는 반드시 환경변수로 설정(랜덤 문자열). 코드에 하드코딩된 기본값은 개발용이며 배포 시 교체 필요.
- **관리자 라우트**: `/admin/*`, 게시판 댓글·숨김 등은 모두 `@login_required` 후 `current_user.is_admin` 검사로 보호됨.
- **업로드**: 이미지 업로드(상품·리뷰·게시판·배송증빙·팝업)는 허용 확장자(.jpg, .jpeg, .png, .gif, .webp)만 저장되며, 저장 경로는 서버가 생성한 파일명만 사용해 경로 트래버설 방지.
- **DB**: 스키마 변경(ALTER)은 고정 목록만 사용하며, 사용자 입력이 SQL에 직접 삽입되지 않음.

## 6. 참고

- **SQLite만 사용 시**: Render 재시작 시 DB가 초기화될 수 있음. 영구 저장이 필요하면 Render PostgreSQL 생성 후 `DATABASE_URL` 연결.
- **정적 파일·업로드**: `static/uploads/`는 로컬과 동일하게 사용. 배포 후에도 상품 엑셀 업로드 시 **이미지 파일을 서버의 `static/uploads/`에 넣고 엑셀에는 파일명만 입력**하는 방식 유지. 빌드 시 폴더는 비어 있으므로, 상품 이미지는 관리자 업로드 또는 해당 경로에 파일 배치 후 엑셀 업로드.
- **DB 마이그레이션**: 앱 기동 시 `init_db()`가 실행되어 게시판(제휴문의·맛집요청) 등 누락된 컬럼이 있으면 자동 추가되므로, 배포 후에도 DB 오류 없이 동작.
- **판매자 발주 이메일**: 관리자 → **판매자 요청** 탭에서 카테고리(판매자)별로 "이메일 보내기" 시 오늘 발주 품목이 메일로 전송되고, 6자리 확인코드·확인 링크가 생성됨. 판매자는 `/seller/confirm`에서 코드 입력 또는 링크 클릭으로 발주 확인 시 **판매자 발주확인**이 체크됨. 이메일 발송을 쓰려면 `EMAIL_SETUP.md` 참고해 SMTP 환경 변수 설정.
