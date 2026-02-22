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

## 6. 참고

- **SQLite만 사용 시**: Render 재시작 시 DB가 초기화될 수 있음. 영구 저장이 필요하면 Render PostgreSQL 생성 후 `DATABASE_URL` 연결.
- **정적 파일**: `static/uploads/`는 빌드 시 비어 있음. 상품 이미지는 관리자 업로드 또는 외부 URL 사용.
