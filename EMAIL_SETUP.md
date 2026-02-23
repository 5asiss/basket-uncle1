# 이메일 발송 키(비밀번호) 받는 방법

판매자 발주 이메일 발송 기능을 쓰려면 **SMTP 설정**이 필요합니다. 아래 중 하나를 선택해 환경 변수에 넣어 주세요.

## 1. Gmail

1. Google 계정 → [보안](https://myaccount.google.com/security) → **2단계 인증**을 켭니다.
2. **앱 비밀번호** 생성: [앱 비밀번호](https://myaccount.google.com/apppasswords)에서 "메일" / "Windows 컴퓨터" 등 선택 후 16자리 비밀번호를 생성합니다.
3. 환경 변수 설정:
   - `MAIL_SERVER=smtp.gmail.com`
   - `MAIL_PORT=587`
   - `MAIL_USERNAME=본인@gmail.com`
   - `MAIL_PASSWORD=방금 생성한 16자리 앱 비밀번호`
   - `MAIL_USE_TLS=1`
   - `DEFAULT_MAIL_FROM=본인@gmail.com` (선택)

## 2. Naver 메일

1. [네이버 메일](https://mail.naver.com) → 환경설정 → **POP3/IMAP 설정**에서 "IMAP/SMTP 사용"을 켭니다.
2. 환경 변수:
   - `MAIL_SERVER=smtp.naver.com`
   - `MAIL_PORT=587`
   - `MAIL_USERNAME=네이버아이디@naver.com`
   - `MAIL_PASSWORD=네이버 로그인 비밀번호`
   - `MAIL_USE_TLS=1`
   - `DEFAULT_MAIL_FROM=네이버아이디@naver.com` (선택)

## 3. 기타 (SendGrid, AWS SES 등)

- **SendGrid**: 대시보드에서 API 키 생성 후 SMTP 주소/포트 사용. `MAIL_USERNAME=apikey`, `MAIL_PASSWORD=발급받은 API 키`.
- **AWS SES**: SMTP 자격 증명 생성 후 해당 호스트/포트/사용자명/비밀번호를 `MAIL_*`에 설정.

## 환경 변수 요약

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `MAIL_SERVER` | ✅ | SMTP 서버 주소 (예: smtp.gmail.com) |
| `MAIL_PORT` | ✅ | 587(TLS) 또는 465(SSL) |
| `MAIL_USERNAME` | ✅ | SMTP 로그인 이메일 또는 사용자명 |
| `MAIL_PASSWORD` | ✅ | SMTP 비밀번호(앱 비밀번호 등) |
| `MAIL_USE_TLS` | 선택 | 1이면 TLS 사용 (기본 1) |
| `DEFAULT_MAIL_FROM` | 선택 | 발신 주소 (기본: MAIL_USERNAME) |

설정 후 **관리자 → 판매자 요청** 탭에서 "이메일 보내기"로 발주 메일을 보낼 수 있습니다.
