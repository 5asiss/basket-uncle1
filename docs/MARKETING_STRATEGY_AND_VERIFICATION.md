# 바구니삼촌 마케팅 자동화 및 검증 가이드

광고와 기술을 결합한 효율적인 운영을 위한 자동화·전략·검증 포인트 정리입니다.

---

## 1. DB 연동 개인화 알림톡 (자동화)

### 개요
- **SQL**로 주문 DB를 분석해 **최근 N주간 주문이 없는 송도 고객** 리스트를 추출합니다.
- **카카오 알림톡 API**를 연동해 해당 고객에게 **할인 쿠폰이 담긴 알림톡**을 자동 발송합니다.

### 구현 위치
- `utils.py`: `get_inactive_songdo_customers()`, `send_kakao_alimtalk()`, `run_reengagement_alimtalk()`
- `scripts/run_reengagement_alimtalk.py`: CLI 실행 스크립트

### 환경 변수 (config.py / .env)

**솔라피(Solapi) 사용 시 (권장)** — [solapi.com](https://solapi.com) 가입 후:
- `SOLAPI_API_KEY`, `SOLAPI_API_SECRET`: 솔라피 API 인증
- `SOLAPI_KAKAO_PF_ID`: 솔라피에 연동한 카카오 비즈니스 채널 ID (pfId)
- `SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY`: 재방문 유도용 알림톡 템플릿 ID
- `SOLAPI_KAKAO_TEMPLATE_ID_ORDER_CREATED`: 주문 완료 알림 템플릿 ID (선택)
- `SOLAPI_KAKAO_TEMPLATE_ID_DELIVERY_COMPLETE`: 배송 완료 알림 템플릿 ID (선택)
- `SOLAPI_SENDER_PHONE`: 대체발송(SMS/LMS)용 발신번호 (사전 등록 필수)

**기타 업체(NHN/카페24 등) 사용 시**:
- `KAKAO_REST_API_KEY`, `KAKAO_ALIMTALK_SENDER_KEY`, `KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY`
- `KAKAO_ALIMTALK_API_URL`: 해당 업체 발송 API URL
- `KAKAO_ALIMTALK_COST_PER_MSG`: 건당 비용(원, ROAS 계산용, 선택)

### 실행 방법
```bash
# 대상만 확인 (실제 발송 없음)
python scripts/run_reengagement_alimtalk.py --dry-run --weeks=2 --limit=100

# 실제 발송 (최근 2주 미주문 송도 고객, 최대 100명)
python scripts/run_reengagement_alimtalk.py --weeks=2 --limit=100 --coupon=WELCOME2WEEKS
```

### 솔라피 카카오 알림톡 구현 요약
- **패키지**: `pip install solapi` (requirements.txt 포함)
- **발송 함수** (`utils.py`):
  - `send_solapi_kakao_alimtalk(phone, template_id, variables, from_phone)` — 1건 발송
  - `send_kakao_alimtalk(phone, customer_name, coupon_code)` — 재방문 쿠폰 (솔라피 우선)
  - `send_alimtalk_order_event(msg_type, phone, customer_name, order_id)` — 주문/배송 알림
- **자동 발송 시점** (`app.py`):
  - **주문 완료** 직후: `send_alimtalk_order_event('order_created', ...)` (템플릿 ID 설정 시)
  - **배송 완료** 처리 시: `send_alimtalk_order_event('delivery_complete', ...)`
- **템플릿 변수**: `#{고객명}`, `#{주문번호}` 등 카카오 비즈니스센터에 등록한 변수명과 동일하게 설정

### SQL 개념 (송도 휴면 고객)
- `order` 테이블에서 `delivery_address LIKE '%송도%'`, `status NOT IN ('결제취소')` 조건으로 주문 집계
- 전화번호별 `MAX(created_at)`이 **N일 이전**인 고객만 추출

---

## 2. 당근마켓 소식 자동 포스팅

### 개요
- **Selenium**으로 당근 비즈프로필 로그인 후, **소식(글)**을 자동 발행합니다.
- 농수산물 가격 변동, 오늘의 특가 등을 **매일 아침** 올리면 운영 리소스를 줄일 수 있습니다.

### 구현 위치
- `scripts/daangn_auto_post.py`: Selenium 기반 자동 포스팅
- `utils.py`: `get_daangn_today_message()` — 오늘 날짜·특가 문구 반영 메시지 생성

### 환경 변수
- `DAANGN_LOGIN_PHONE`: 로그인 전화번호
- `DAANGN_LOGIN_PASSWORD`: 비밀번호 (휴대폰 인증 시 불필요할 수 있음)
- `DAANGN_BIZ_PROFILE_URL`: 비즈 프로필/소식 페이지 URL
- `DAANGN_TODAY_MESSAGE`: 고정 메시지 (없으면 기본 문구)
- `DAANGN_USE_UTILS=1`: 1이면 `utils.get_daangn_today_message()` 사용
- `DAANGN_EXTRA_LINE`: 오늘의 특가 등 한 줄 추가 문구
- `DAANGN_HEADLESS=1`: 헤드리스 모드
- `DAANGN_KEEP_OPEN=1`: 실행 후 브라우저 유지 (엔터 시 종료)

### 실행 방법
```bash
# 기본 메시지로 발행
python scripts/daangn_auto_post.py

# 커스텀 메시지 인자로 전달
python scripts/daangn_auto_post.py "[바구니삼촌] 오늘의 특가: 당근 1kg 2,500원. 선착순 10분 한정."

# utils 메시지 생성 + 특가 한 줄
set DAANGN_USE_UTILS=1
set DAANGN_EXTRA_LINE=오늘의 특가: 감자 2kg 4,000원
python scripts/daangn_auto_post.py
```

### 참고
- 당근 비즈 로그인·소식 페이지 HTML 구조가 바뀌면 셀렉터 수정이 필요할 수 있습니다.
- 당근 비즈니스 API를 제공한다면 API 연동으로 전환하면 더 안정적입니다.

---

## 3. 검증 포인트 (ROAS·전환율)

### 3-1. 알림톡 ROAS (광고비 대비 매출)
- **지표**: 발송 건수 × 건당 비용 = 광고비, 재방문 주문의 `total_price` 합 = 매출 → **ROAS = 매출 / 광고비**
- **구현**: `utils.get_roas_metrics(days_since=30)` — 재방문 건수·재방문율  
  `utils.get_roas_with_revenue(days_since=30)` — 매출·광고비·ROAS

```python
from utils import get_roas_metrics, get_roas_with_revenue

# 재방문율만
m = get_roas_metrics(30)  # sent_total, revisit_orders, revisit_rate

# 매출·ROAS (KAKAO_ALIMTALK_COST_PER_MSG 설정 시)
r = get_roas_with_revenue(30)  # ad_spend, revisit_revenue, roas
```

### 3-2. 당근 유입 전환율
- **지표**: 당근(utm_source) 유입 수 대비 **결제 완료 건수** → 전환율. 유입 단가는 낮지만 **결제까지 이어지는지** 확인 필요.
- **구현**: `utils.get_daangn_conversion_metrics(days_since=30)` — visits, orders_paid, conversion_rate, revenue

```python
from utils import get_daangn_conversion_metrics

d = get_daangn_conversion_metrics(30)
# d["visits"], d["orders_paid"], d["conversion_rate"], d["revenue"]
```

### 3-3. SQL로 직접 비교할 때 예시 (참고용)
- 알림톡 발송 후 재주문 금액 합계(개념):
```sql
-- 발송 로그와 주문 조인 (전화번호 매칭, 발송 이후 주문만)
SELECT SUM(o.total_price) AS revisit_revenue
FROM marketing_alimtalk_log l
JOIN "order" o ON REPLACE(o.customer_phone, '-', '') LIKE '%' || SUBSTR(REPLACE(l.phone, '-', ''), -10) || '%'
 AND o.created_at > l.sent_at
 AND o.status NOT IN ('결제취소')
WHERE l.success = 1 AND l.sent_at >= date('now', '-30 days');
```
- 당근 유입 결제 전환(개념):
```sql
SELECT COUNT(*) AS visits,
       SUM(CASE WHEN status NOT IN ('결제취소') THEN 1 ELSE 0 END) AS orders_paid,
       SUM(CASE WHEN status NOT IN ('결제취소') THEN total_price ELSE 0 END) AS revenue
FROM "order"
WHERE created_at >= date('now', '-30 days')
 AND (LOWER(utm_source) LIKE '%daangn%' OR LOWER(utm_source) LIKE '%당근%');
```

---

## 4. 정리
| 항목 | 도구 | 검증 포인트 |
|------|------|-------------|
| 알림톡 | `run_reengagement_alimtalk`, `get_roas_metrics`, `get_roas_with_revenue` | 메시지 비용 대비 재방문·매출(ROAS) |
| 당근 | `daangn_auto_post.py`, `get_daangn_today_message`, `get_daangn_conversion_metrics` | 유입 대비 결제 전환율·매출 |

위 자동화와 지표를 주기적으로 확인하면, **카카오 알림톡 비용 대비 재방문율**과 **당근 유입의 결제 전환율**을 데이터로 비교·분석할 수 있습니다.
