# 바구니삼촌 자동화 스크립트

## 0. DB 초기화

### 사용 DB

- **기본**: `DATABASE_URL` 미설정 시 `sqlite:///direct_trade_mall.db` (프로젝트 루트 또는 `instance/` 아래)
- **PostgreSQL**: Render 등에서 `DATABASE_URL`에 연결 문자열 설정

### 방법 1) 테이블 생성 + 누락 컬럼 추가 (기존 데이터 유지)

앱을 실행하면 `init_db()`가 자동 호출되어 테이블이 없으면 생성하고, 컬럼이 없으면 `ALTER TABLE`로 추가합니다.

```bash
# 서버 실행 시 자동 실행됨
python app.py
```

**서버 없이 init_db만 실행** (테이블/컬럼만 맞추고 싶을 때):

```bash
python -c "from app import app, init_db; app.app_context().push(); init_db(); print('DB 초기화(테이블·컬럼·기초데이터) 완료')"
```

### 방법 2) 완전 초기화 (DB 비우고 처음부터)

**SQLite 사용 시**

1. 앱/서버 중지
2. DB 파일 삭제  
   - 기본 경로: 프로젝트 루트의 `direct_trade_mall.db` 또는 `instance/direct_trade_mall.db`
3. 아래 중 하나 실행  
   - `python app.py` 로 서버 기동 (기동 시 `init_db()` 호출)  
   - 또는: `python -c "from app import app, init_db; app.app_context().push(); init_db(); print('OK')"`

**PostgreSQL 사용 시**

- 테이블만 지우고 다시 만들려면 `db.drop_all()` 후 `db.create_all()` 사용 (데이터 전부 삭제됨)
- 운영 DB에서는 **사용하지 말 것**. 필요 시 별도 스크립트로 백업 후 진행

```bash
# 로컬/개발용 예시 (데이터 전부 삭제됨!)
python -c "
from app import app, db, init_db
with app.app_context():
    db.drop_all()
    init_db()
    print('DB 완전 초기화 완료')
"
```

### 서버에서 DB 삭제 후 재시작 (Render 등)

**PostgreSQL 사용 시 (Render 등)**

1. **방법 A – One-off / Shell에서 초기화 후 재시작**
   - Render: **Shell** 탭에서 접속하거나, **Background Worker** 또는 **One-off Job**으로 아래 명령 실행 (Start Command를 일시적으로 아래로 변경해 한 번 실행 후 원복해도 됨).
   ```bash
   python -c "
   from app import app, db, init_db
   with app.app_context():
       db.drop_all()
       init_db()
       print('DB 완전 초기화 완료')
   "
   ```
   - 실행 후 **Web Service**를 **Manual Deploy** 또는 **Restart** 한 번 하면 앱이 새 DB 상태로 동작합니다.
2. **방법 B – DB만 새로 만들기**
   - Render Dashboard → **PostgreSQL** → 해당 DB 삭제 후 **새 PostgreSQL** 생성.
   - 새 DB의 **Internal Database URL**을 복사해 **Web Service** 환경 변수 `DATABASE_URL`에 넣고 **Save** → **Manual Deploy**.
   - 앱 기동 시 테이블이 없으면 `db.create_all()` 등으로 생성되므로, 최초 요청 전에 **Shell**에서 `init_db()` 한 번 실행해 두면 관리자 계정·기초 데이터까지 생성됩니다:
   ```bash
   python -c "from app import app, init_db; app.app_context().push(); init_db(); print('OK')"
   ```

**SQLite 사용 시 (Render Web Service)**

- 디스크가 휘발성이라 **재배포/재시작** 시 DB 파일이 사라질 수 있음. 그때는 새 인스턴스에서 앱이 뜨면서 새 DB 파일이 생기고, `python app.py`로 기동할 때만 `init_db()`가 자동 호출됩니다.
- **gunicorn**으로 기동 중이면 `init_db()`는 자동 호출되지 않으므로, **한 번만** 아래처럼 초기화해 두는 것을 권장합니다 (Shell 또는 One-off):
  ```bash
  python -c "from app import app, init_db; app.app_context().push(); init_db(); print('OK')"
  ```
- 서버에서 **DB 파일만 지우고** 다시 초기화하려면 (SSH/Shell 접속 가능한 경우):
  1. 앱 중지(또는 해당 프로세스만 종료)
  2. DB 파일 삭제: `rm -f instance/direct_trade_mall.db direct_trade_mall.db` (실제 사용 경로에 맞게)
  3. 위 `python -c "from app import app, init_db; ..."` 실행 후 앱 재시작

**요약**

| 환경 | DB 삭제 후 재시작 방법 |
|------|------------------------|
| **PostgreSQL (Render)** | Shell/One-off에서 `db.drop_all()` + `init_db()` 실행 → Web Service **Restart** 또는 **Manual Deploy** |
| **PostgreSQL (Render)** | 또는 Dashboard에서 DB 삭제 → 새 DB 생성 → `DATABASE_URL` 변경 → Deploy 후 Shell에서 `init_db()` 1회 실행 |
| **SQLite (로컬/일반 서버)** | 앱 중지 → DB 파일 삭제 → `python app.py` 또는 `init_db()` 한 줄 실행 후 앱 재시작 |

### init_db()가 하는 일

- `db.create_all()` 로 모든 테이블 생성
- 기존 테이블에 없는 컬럼 `ALTER TABLE` 로 추가
- 관리자 계정 없으면 생성: `admin@uncle.com` / `1234`
- 카테고리 없으면 샘플 카테고리 2개 생성

---

## 1. DB 연동 개인화 알림톡 (휴면 고객 재방문 유도)

- **대상**: 최근 N주간 주문이 없는 **송도** 고객 (SQL로 추출)
- **동작**: 카카오 알림톡 API로 할인 쿠폰 메시지 발송
- **ROAS 검증**: `utils.get_roas_metrics()`로 발송 건수 대비 재방문 주문 수·재방문율 조회

### 테이블 생성 (최초 1회)

알림톡 발송 로그용 테이블이 없으면 Flask 셸에서 생성:

```bash
python -c "from app import app, db; from models import MarketingAlimtalkLog; app.app_context().push(); db.create_all(); print('OK')"
```

### 환경변수 (.env)

```env
# 카카오 알림톡 (업체 연동 후 실제 발송 URL·키 설정)
KAKAO_REST_API_KEY=your_rest_api_key
KAKAO_ALIMTALK_SENDER_KEY=your_sender_key
KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY=your_template_code
KAKAO_ALIMTALK_API_URL=https://your-provider.com/v2/send/kakao
```

### 실행

```bash
# 대상만 확인 (발송 안 함)
python scripts/run_reengagement_alimtalk.py --dry-run

# 실제 발송 (최대 100명, 최근 2주 미주문)
python scripts/run_reengagement_alimtalk.py --weeks=2 --limit=100
```

### ROAS 확인

- Flask 앱 내에서 `from utils import get_roas_metrics; get_roas_metrics(days_since=30)` 호출
- 또는 관리자 화면에 “알림톡 발송 대비 재방문율” API/페이지를 추가해 사용

---

## 2. 당근마켓 비즈프로필 소식 자동 포스팅

- **동작**: Selenium으로 당근 비즈 로그인 후, 오늘의 특가/소식 텍스트를 비즈프로필 소식에 게시
- **실행**: 매일 아침 cron 등으로 실행

### 환경변수

```env
DAANGN_LOGIN_PHONE=01012345678
DAANGN_LOGIN_PASSWORD=비밀번호
DAANGN_BIZ_PROFILE_URL=https://business.daangn.com/...
DAANGN_TODAY_MESSAGE=[바구니삼촌] 오늘의 특가: 당근 1kg 2,000원 ...
```

### 실행

```bash
pip install selenium
python scripts/daangn_auto_post.py
# 또는 메시지 직접 전달
python scripts/daangn_auto_post.py "오늘의 특가: 상품명 00원"
```

- 로그인·소식 발행 버튼 등 셀렉터는 당근 비즈 페이지 구조에 맞게 `daangn_auto_post.py` 내부에서 수정해야 할 수 있습니다.

---

## 3. 검증 포인트 (ROAS·전환율)

- **알림톡**: 발송 비용 대비 재방문 주문 건수·재방문율을 `marketing_alimtalk_log` + 주문 테이블로 SQL 조회 (`get_roas_metrics()`).
- **당근**: 유입 단가는 당근 광고/소식 유입 UTM으로 추적하고, 결제까지 전환율은 기존 주문/유입 분석으로 비교하면 됩니다.
