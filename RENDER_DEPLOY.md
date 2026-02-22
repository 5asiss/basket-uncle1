# 1차 GitHub 업로드 & Render 배포 점검

## 1. GitHub 업로드 전 점검

- [ ] **비밀키/민감 정보**
  - `.env` 가 `.gitignore` 에 포함되어 있는지 확인 (이미 포함됨)
  - `*.db`, `instance/` 도 제외되는지 확인
  - 코드 안에 API 키/비밀번호가 하드코딩되어 있지 않은지 확인

- [ ] **requirements.txt**
  - 패키지 이름만 있는 줄이 위쪽에 있고, 메모는 `#` 주석으로 처리되어 있음
  - `gunicorn` 포함 여부 확인

- [ ] **실행 가능 여부**
  - 로컬에서 `pip install -r requirements.txt` 후 `python app.py` 로 실행해 보기
  - (선택) `gunicorn --bind 0.0.0.0:5000 app:app` 로 실행해 보기

- [ ] **Git 상태**
  - 커밋할 파일만 스테이징 (`.env`, `*.db` 제외되는지 확인)
  - `git status` 로 한 번 더 확인

---

## 2. GitHub 업로드 순서

```bash
cd c:\Users\new\Documents\GitHub\basket-uncle

# 이미 리모트가 있으면 생략
git remote -v

# 스테이징 ( .env, *.db 는 자동 제외됨 )
git add .
git status

# 커밋
git commit -m "1차 배포: PWA, 메시지/푸시, 바로가기 안내, Render 배포 준비"

# 푸시 ( main 브랜치 기준 )
git push -u origin main
```

---

## 3. Render 배포 전 점검

- [ ] **환경 변수**
  - Render Dashboard → 해당 Web Service → Environment
  - `.env.example` 참고해서 최소한 아래 설정:
    - `FLASK_SECRET_KEY` (필수, 랜덤 문자열)
    - `TOSS_CLIENT_KEY`, `TOSS_SECRET_KEY` (결제 사용 시)
    - `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (푸시 알림 사용 시, 선택)

- [ ] **Build / Start 명령**
  - Build Command: `pip install -r requirements.txt`
  - Start Command: `gunicorn --bind 0.0.0.0:$PORT app:app`
  - Render 가 `PORT` 를 자동으로 넣어 주므로 `$PORT` 사용

- [ ] **Python 버전**
  - Render → Build & Deploy → Environment 에서 `PYTHON_VERSION=3.12.0` (또는 3.11) 설정 가능

- [ ] **DB 안내**
  - 기본값은 SQLite. Render 무료 플랜에서는 디스크가 재시작 시 초기화될 수 있음.
  - 영구 DB 가 필요하면 Render PostgreSQL 생성 후 `DATABASE_URL` 에 연결 문자열 설정.

---

## 4. Render에서 서비스 만들기

1. https://dashboard.render.com 로그인
2. **New +** → **Web Service**
3. GitHub 리포지토리 `basket-uncle` 연결 (권한 허용)
4. 설정:
   - **Name**: basket-uncle (원하는 이름)
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT app:app`
5. **Environment** 탭에서 `.env.example` 참고해 변수 추가
6. **Create Web Service** → 빌드 후 URL 로 접속해 동작 확인

---

## 5. 배포 후 확인

- [ ] 메인 페이지(/) 열리는지
- [ ] 로그인/회원가입 동작하는지
- [ ] (결제 설정한 경우) 테스트 결제 플로우
- [ ] 관리자(/admin) 접속
- [ ] 배송 시스템(/logi) 접속 (배송 DB 별도이면 DELIVERY_DATABASE_URL 동일하게 SQLite 가능)

이 문서는 1차 업로드·Render 배포용 점검과 순서만 정리한 것입니다.
