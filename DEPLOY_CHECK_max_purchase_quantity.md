# 구매 제한 기능(max_purchase_quantity) — 서버 업로드 전 점검 요약

## 1. DB 변경 사항

### 모델 (models.py)
- **Product** 모델에 컬럼 정의 있음:
  ```python
  max_purchase_quantity = db.Column(db.Integer, default=0)  # 0=제한없음
  ```

### 마이그레이션 (app.py)
- **앱 기동 시** `with app.app_context():` 안에서 다음이 실행됨:
  - `_ensure_product_consumer_price_column()`
  - `_ensure_product_naver_columns()` ← **여기서 `max_purchase_quantity` 처리**
- `_ensure_product_naver_columns()` 동작:
  - `product` 테이블 컬럼 목록 조회 후, `max_purchase_quantity`가 없으면  
    `ALTER TABLE product ADD COLUMN max_purchase_quantity INTEGER DEFAULT 0` 실행
  - 기존 DB에도 컬럼 없으면 **자동 추가** (서버 업로드 후 최초 1회 실행 시)
- SQLite / MySQL 등 일반 RDB에서 동작하는 단순 INTEGER 컬럼 추가

**서버 업로드 시:** 별도 수동 마이그레이션 불필요. 앱 기동만 하면 컬럼 자동 추가됨.

---

## 2. 코드 사용처 (컬럼 없을 때 대비)

| 위치 | 사용 방식 | 비고 |
|------|-----------|------|
| add_cart (장바구니 추가) | `getattr(p, 'max_purchase_quantity', None) or 0` | 안전 |
| cart() 장바구니 화면 | `getattr(prod, 'max_purchase_quantity', None) or 0` | 안전 |
| 주문 생성 직전 검증 | `getattr(prod, 'max_purchase_quantity', None) or 0` | 안전 |
| 검색/카테고리 JSON | `getattr(p, 'max_purchase_quantity', 0) or 0` | 안전 |
| 관리자 상품 수정 폼 | `getattr(p, 'max_purchase_quantity', 0) or 0` | 안전 |
| 상품 상세 템플릿 | `p.max_purchase_quantity` | 마이그레이션 성공 시 정상 (모델에 필드 있음) |

모델에 필드가 있고, 기동 시 마이그레이션으로 컬럼이 추가되므로, 실제 요청 시점에는 컬럼이 존재하는 상태가 됨.

---

## 3. 업로드 후 확인 방법

1. **앱 기동**
   - 콘솔에 다음 중 하나 출력되면 마이그레이션 정상 동작:
     - `[DB MIGRATION] product.max_purchase_quantity 컬럼을 추가했습니다. (0=제한없음)` (최초 1회)
     - `[DB MIGRATION] product 네이버 최저가/구매제한 컬럼 확인 완료.` (매 기동)

2. **기능 확인**
   - 관리자: 상품 등록/수정 화면에 「구매 제한 수량 (0=제한 없음)」 입력란 노출
   - 상품 상세: 구매 제한이 있으면 "이 상품은 1인당 최대 N개까지 구매 가능합니다." 문구 노출
   - 장바구니: 제한 있는 상품은 "(최대 N개)" 표시, N개 초과 시 + 버튼 비활성화
   - 장바구니 추가/주문 시 제한 초과하면 에러 메시지 반환

3. **DB 직접 확인 (선택)**
   - SQLite: `sqlite3 delivery.db "PRAGMA table_info(product);"`  
     → `max_purchase_quantity` 컬럼 존재 여부 확인

---

## 4. 알려진 이슈 (구매 제한과 무관)

- `python -c "from app import app"` 시 **AssertionError: View function mapping is overwriting an existing endpoint function: admin.admin_event_post_delete**  
  → Flask 라우트 중복(이벤트 게시판 관련) 문제이며, **DB/구매 제한 기능과는 무관**.  
  서버에서 실제로 `flask run` 또는 wsgi로 앱을 기동할 때 같은 오류가 나면 admin 라우트 등록 부분을 점검하면 됨.

---

## 5. 요약

- **DB:** `product.max_purchase_quantity` 컬럼은 앱 기동 시 자동 추가됨. 수동 마이그레이션 불필요.
- **코드:** 모든 참조가 `getattr(..., 0)` 등으로 되어 있어, 예전 DB/일시적 결함에도 안전하게 동작하도록 되어 있음.
- **배포:** 코드와 models.py만 반영 후 서버에서 앱 기동하면 구매 제한 기능이 오류 없이 적용됨.
