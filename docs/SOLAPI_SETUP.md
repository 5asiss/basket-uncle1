# 솔라피(Solapi) 카카오 알림톡 설정 방법

바구니삼촌 프로젝트에서 솔라피를 이용해 카카오 알림톡을 발송하려면 아래 순서대로 진행하세요.

---

## 1. 솔라피 가입 및 API 키 발급

1. **[솔라피](https://solapi.com)** 접속 후 **시작하기**로 가입·로그인
2. **[콘솔](https://console.solapi.com)** → **계정** → **API 키 관리**
3. **API Key**, **API Secret** 복사해 두기 (나중에 `.env`에 입력)

---

## 2. 카카오톡 비즈니스 채널 개설

알림톡은 **카카오 비즈니스 채널**을 통해만 발송할 수 있습니다.

1. **[카카오 비즈니스](https://business.kakao.com)** 에서 채널 개설
2. **채널 검색 허용** 설정, **고객센터 정보** 입력 필수
3. 솔라피 연동 전 위 설정을 반드시 완료할 것  
   → 상세: [솔라피 가이드: 카카오 채널 만들기](https://solapi.com/guides/kakao-make-channel/)

---

## 3. 솔라피에 카카오 채널 연동 (pfId 발급)

1. **[솔라피 콘솔](https://console.solapi.com)** 로그인
2. **카카오 채널 연동** 메뉴 이동:  
   [카카오 채널 연동](https://console.solapi.com/kakao/plus-friends)
3. 채널 정보 입력 후 **연동** 완료
4. 연동된 채널에 부여된 **PFID** 확인·복사  
   → 알림톡 발송 시 `SOLAPI_KAKAO_PF_ID`로 사용

---

## 4. 알림톡 템플릿 등록 (templateId 발급)

알림톡은 **승인된 템플릿**으로만 발송 가능합니다.

1. **[솔라피 콘솔 → 카카오 알림톡 템플릿](https://console.solapi.com/kakao/templates)**
2. **템플릿 생성** 클릭 후 내용 작성
   - **변수**는 `#{변수명}` 형식 (예: `#{고객명}`, `#{주문번호}`, `#{쿠폰}`)
   - 카카오 정책·심사 기준: [알림톡 제작 가이드](https://kakaobusiness.gitbook.io/main/ad/bizmessage/notice-friend/content-guide)
3. **템플릿 등록 완료** 클릭 → 카카오 검수 요청
4. 검수 통과 후(영업일 기준 1~3일) 솔라피에 **템플릿 ID** 표시됨 → 복사

### 바구니삼촌에서 쓰는 템플릿 예시

| 용도 | 환경 변수 | 추천 변수 |
|------|-----------|-----------|
| 회원가입 환영 | `SOLAPI_KAKAO_TEMPLATE_ID_WELCOME` | `#{고객명}` |
| 재방문 쿠폰 (휴면 고객) | `SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY` | `#{고객명}`, `#{쿠폰}` |
| 주문 완료 알림 | `SOLAPI_KAKAO_TEMPLATE_ID_ORDER_CREATED` | `#{고객명}`, `#{주문번호}` |
| 배송 완료 알림 | `SOLAPI_KAKAO_TEMPLATE_ID_DELIVERY_COMPLETE` | `#{고객명}`, `#{주문번호}` |
| 회원가입 환영 | `SOLAPI_KAKAO_TEMPLATE_ID_WELCOME` | `#{고객명}` |

템플릿에 등록한 변수명과 코드의 `variables` 키가 **완전히 동일**해야 합니다 (예: `#{고객명}`).

---

## 5. 대체발송용 발신번호 등록 (선택)

알림톡 발송 실패 시 SMS/LMS로 대체 발송하려면:

1. **[솔라피 콘솔 → 발신번호 관리](https://console.solapi.com/senderids)**
2. 발신번호 등록·인증 완료
3. 해당 번호를 `.env`의 `SOLAPI_SENDER_PHONE`에 입력 (하이픈 없이, 예: `01012345678`)

---

## 6. 프로젝트 .env 설정

프로젝트 루트의 `.env` 파일에 아래 값을 채웁니다. (`.env.example` 참고)

```env
# 솔라피 인증 (필수)
SOLAPI_API_KEY=발급받은_API_키
SOLAPI_API_SECRET=발급받은_API_시크릿

# 카테고리 3단계에서 복사한 채널 ID (필수)
SOLAPI_KAKAO_PF_ID=연동한_채널의_PFID

# 템플릿 ID (4단계에서 복사, 용도별로 필요한 것만 설정)
SOLAPI_KAKAO_TEMPLATE_ID_WELCOME=회원가입환영_템플릿ID
SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY=재방문쿠폰_템플릿ID
SOLAPI_KAKAO_TEMPLATE_ID_ORDER_CREATED=주문완료_템플릿ID
SOLAPI_KAKAO_TEMPLATE_ID_DELIVERY_COMPLETE=배송완료_템플릿ID

# 대체발송용 발신번호 (5단계에서 등록한 번호, 선택)
SOLAPI_SENDER_PHONE=01012345678
```

- **최소 동작**: `SOLAPI_API_KEY`, `SOLAPI_API_SECRET`, `SOLAPI_KAKAO_PF_ID` + 사용할 템플릿 1개 이상
- 주문/배송 알림을 쓰려면 해당 템플릿 ID까지 설정

---

## 7. 동작 확인

- **회원가입 환영**: 회원가입 완료 시 가입자 휴대폰으로 알림톡 발송 (회원가입 템플릿 설정 시)
- **주문 완료 알림**: 사이트에서 결제 완료 시 고객 휴대폰으로 알림톡 발송 (주문 완료 템플릿 설정 시)
- **배송 완료 알림**: 관리자/배송 시스템에서 배송 완료 처리 시 알림톡 발송 (배송 완료 템플릿 설정 시)
- **재방문 쿠폰**: 터미널에서  
  `python scripts/run_reengagement_alimtalk.py --dry-run --weeks=2 --limit=10`  
  으로 대상만 확인 후, `--dry-run` 빼고 실행하면 실제 발송

---

## 참고 링크

| 항목 | URL |
|------|-----|
| 솔라피 공식 | https://solapi.com |
| 솔라피 콘솔 | https://console.solapi.com |
| 카카오 알림톡 가이드 (솔라피) | https://solapi.com/guides/kakao-ata-guide |
| 카카오 채널 연동 (솔라피) | https://console.solapi.com/kakao/plus-friends |
| 알림톡 템플릿 (솔라피) | https://console.solapi.com/kakao/templates |
| 발신번호 등록 (솔라피) | https://console.solapi.com/senderids |
| 솔라피 개발자 문서 (알림톡) | https://developers.solapi.com |

프로젝트 내 발송 로직은 `utils.py`의 `send_solapi_kakao_alimtalk`, `send_alimtalk_order_event`와 `docs/MARKETING_STRATEGY_AND_VERIFICATION.md`를 참고하면 됩니다.
