# 바구니삼촌 자동화 스크립트

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
