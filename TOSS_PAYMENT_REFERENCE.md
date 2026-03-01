# 토스페이먼츠 API · 우리 구현 대조 (Version 2024-06-01 기준)

개발자센터 문서(결제 · Payment 객체 · 결제 승인 · 결제 취소)와 프로젝트 내 결제 연동 코드를 대조한 요약입니다.

---

## 1. 결제 승인 (POST /v1/payments/confirm)

| 문서 요구사항 | 우리 구현 (app.py `payment_success`) |
|---------------|--------------------------------------|
| **paymentKey** 필수, string, 최대 200자 | 리다이렉트 쿼리 `paymentKey` → 그대로 JSON에 전달 ✓ |
| **orderId** 필수, 6자 이상 64자 이하, 영문 대소문자·숫자·`-`·`_` | 리다이렉트 쿼리 `orderId` → 그대로 전달 (결제창에서 동일 규칙으로 생성) ✓ |
| **amount** 필수, number | `int(amt)` 로 정수 변환 후 전달 ✓ |
| 요청 본문 | `Content-Type: application/json`, JSON 본문 ✓ |
| 인증 | `Authorization: Basic {시크릿키}:` (config `TOSS_SECRET_KEY`) ✓ |
| 응답 | HTTP 200 + Payment 객체. 실패 시 에러 객체(code, message) 및 v2 시 traceId 로그 ✓ |

- **인증 전 10분 이내** 승인 API 미호출 시 결제 만료. 우리는 success 리다이렉트 시 즉시 confirm 호출 ✓

---

## 2. 결제창 요청 (requestPayment)

- **SDK**: 토스페이먼츠 **JavaScript v1 결제창** (`https://js.tosspayments.com/v1/payment`) 사용. `TossPayments(clientKey)` 후 `requestPayment('CARD', { ... })` 호출. (v2 standard 스크립트는 결제위젯용이라 결제창 연동 시 미사용.)

| 문서 요구사항 | 우리 구현 (app.py `order_payment` 페이지 내 JS) |
|---------------|------------------------------------------------|
| **orderId** 6~64자, 영문·숫자·`-`·`_` | `order_id_js` 앞 24자 + `_` + 타임스탬프, 64자 초과 시 앞 64자만 사용 ✓ |
| **amount** number, 금액 > 0 | `Math.floor(Number(total))`, 1원 미만이면 요청 전 중단 ✓ |
| **orderName** 최대 100자 | `(order_name or "주문")[:100]` ✓ |
| **successUrl / failUrl** | `window.location.origin + '/payment/success'`, `'/payment/fail'` ✓ |
| customerEmail / customerName | 이스케이프 후 전달, 없으면 `order@customer.local` / `주문고객` ✓ |

- 결제 허용 URL은 **successUrl·failUrl 파라미터로 설정** (별도 개발자센터 등록 아님).

---

## 3. 결제 취소 (POST /v1/payments/{paymentKey}/cancel)

| 문서 요구사항 | 우리 구현 |
|---------------|-----------|
| **Path** paymentKey | `order.payment_key` (승인 시 저장한 값) ✓ |
| **cancelReason** 필수, string, 최대 200자 | 부분: `"품목 부분 취소"`, 전액: `"주문 전액 취소"` ✓ |
| **cancelAmount** (부분 취소 시) | 부분 취소 시 `cancel_amount` 전달 ✓ |
| **taxFreeAmount** (면세 취소액) | 부분/전액 시 해당 있으면 `taxFreeAmount` 포함 ✓ |
| 전액 취소 시 cancelAmount 생략 | body에 `cancelReason` 만 전달 ✓ |

- 위치: 품목 부분 취소 `order_cancel_item` → `_do_partial_cancel`, 전액 취소 `_do_full_order_cancel`.

---

## 4. Payment 객체 저장

승인 응답으로 받는 Payment 객체 중 우리가 DB에 쓰는 값:

- **paymentKey** → `Order.payment_key` (결제 조회·취소에 사용)
- **orderId** → `Order.order_id` (주문 식별, 토스 문서와 동일 규칙)
- **totalAmount** → 주문 총액은 우리가 장바구니 기준으로 계산해 `Order.total_price` 등에 저장 (포인트 사용 반영)

---

## 5. 설정 (config.py)

- **TOSS_CLIENT_KEY**: 결제창 SDK용 (브라우저 노출). 테스트 `test_ck_` / 라이브 `live_ck_`.
- **TOSS_SECRET_KEY**: 결제 승인·취소 API용 (서버만 사용). 테스트 `test_sk_` / 라이브 `live_sk_`.
- **TOSS_CONFIRM_KEY**: 웹훅 서명 검증용(선택). 현재 일반 결제만 사용 시 필수 아님.

---

## 6. 라이브 키 사용 시 점검 (결제 실패 시)

1. **클라이언트 키·시크릿 키 세트**
   - 같은 상점(MID)의 **한 세트**만 사용해야 합니다.  
   - 테스트 키와 라이브 키를 섞거나, 서로 다른 MID의 키를 조합하면 `INVALID_API_KEY` / `UNAUTHORIZED_KEY` 등이 납니다.  
   - 라이브 전환 시 **클라이언트 키(live_ck_...)와 시크릿 키(live_sk_...)** 를 개발자센터 API 키 메뉴에서 같은 세트로 확인 후 입력하세요.

2. **시크릿 키 인코딩**
   - API 호출 시 **시크릿 키 뒤에 `:` 를 붙인 뒤** base64 인코딩해서 사용합니다.  
   - 우리 코드: `base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()` → 콜론 포함 후 인코딩 ✓

3. **주요 에러 코드**
   - **UNAUTHORIZED_KEY**: 클라이언트 키와 매칭된 시크릿 키 사용 여부·시크릿 키 인코딩(콜론 포함 base64) 재확인.
   - **FORBIDDEN_REQUEST**: 결제 요청(결제창)에 쓴 클라이언트 키와 결제 승인 API에 쓴 시크릿 키가 **한 세트**인지 확인.
   - **NOT_FOUND_PAYMENT_SESSION**: 결제 요청 후 **10분 이내**에 결제 승인 API 호출 필요. 결제창 클라이언트 키와 승인 시크릿 키가 같은 세트인지 확인.

4. **API 키 확인**
   - 개발자센터 → **API 키** 메뉴에서 라이브 키(클라이언트 키·시크릿 키) 확인.

---

## 7. 에러 처리

- **결제 승인 실패**: v1 `{ code, message }`, v2 `{ error: { code, message }, traceId }` 모두 파싱 후 `/payment/fail` 로 리다이렉트, traceId는 로그 출력.
- **결제창 에러**: `COMMON_ERROR` 시 "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요." 표시. 화면에 **토스가 반환한 상세 메시지**를 함께 노출해 원인 파악에 활용(개발자 도구 콘솔에도 전체 error 객체 출력). **INVALID_ORDER_NAME** 시 주문명(특수문자/길이) 안내, **INVALID_ORDER_ID** 시 주문번호 형식(6~64자, 영문·숫자·-·_) 안내.
- **COMMON_ERROR 가능 원인**: 파라미터 형식/누락, 결제 기관 일시 오류, **라이브 키 사용 시 결제 허용 URL(도메인) 미등록** 등. 라이브 환경이면 개발자센터에서 **결제 허용 URL**에 현재 접속 중인 도메인(예: `https://yourdomain.com`)이 등록되어 있는지 확인하세요. 지속 시 토스 고객센터(1666-8320) 문의 권장.

이 문서는 토스페이먼츠 개발자센터(API & SDK, 결제 · Payment 객체 · 결제 승인 · 결제 취소) 내용을 기준으로 작성되었습니다.
