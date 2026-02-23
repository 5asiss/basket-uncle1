# 네이버 · 구글 · 카카오 통합 로그인 설정

로그인 페이지에서 **네이버 → 구글 → 카카오** 순으로 버튼이 노출됩니다. 아래 **「다시 시작」** 순서대로 하면 됩니다.

---

## 통합 로그인 다시 시작 (처음부터 설정)

아래 순서대로만 하면 됩니다. **순서를 바꾸지 마세요.**

### 0단계: 서비스 주소 정하기

- **로컬 테스트**: `http://localhost:5000` (Flask 기본 포트)
- **운영 서버**: 실제 도메인만 (끝에 `/` 없음). 예: `https://basam.co.kr`

이 주소를 **기준 URL**이라고 부릅니다. 아래 콜백 주소는 모두 `기준URL + 경로` 입니다.

### 1단계: .env 필수 값

프로젝트 루트 `.env`에 **반드시** 있어야 합니다.

```env
FLASK_SECRET_KEY=32자이상아무랜덤문자
```

- 없거나 비어 있으면: 네이버/구글/카카오 클릭 후 콜백에서 **"잘못된 요청입니다."** 로 돌아옵니다.
- **운영 서버(프록시/호스팅) 사용 시** redirect_uri 오류를 막으려면 여기에도 추가:

```env
OAUTH_REDIRECT_BASE=https://실제도메인
```

예: `OAUTH_REDIRECT_BASE=https://basam.co.kr` (끝 `/` 없음)

### 2단계: 진단 페이지로 redirect_uri 확인

1. **관리자 계정**으로 로그인
2. 브라우저에서 접속 (둘 중 하나):
   - `https://your-domain.com/auth/status`
   - 또는 `https://your-domain.com/admin/auth-status`
3. JSON에 **각 제공자별 `redirect_uri`** 가 나옵니다. 이 값을 **그대로** 복사해 둡니다.

예시:

```json
{
  "naver": { "redirect_uri": "https://basam.co.kr/auth/naver/callback", ... },
  "google": { "redirect_uri": "https://basam.co.kr/auth/google/callback", ... },
  "kakao":  { "redirect_uri": "https://basam.co.kr/auth/kakao/callback", ... }
}
```

→ **이 redirect_uri 문자열을 각 개발자 콘솔에 한 글자도 틀리지 않게 등록**해야 합니다.

### 3단계: 개발자 콘솔에 콜백 URL 등록

- **네이버**: [네이버 개발자센터] → 애플리케이션 → 로그인 오픈 API 서비스 환경(웹) → **Callback URL** = 2단계에서 본 `redirect_uri` (네이버)
- **구글**: [Google Cloud Console] → 사용자 인증 정보 → 해당 OAuth 클라이언트 → **승인된 리디렉션 URI** = 2단계에서 본 `redirect_uri` (구글)
- **카카오**: [카카오 개발자] → 내 애플리케이션 → 카카오 로그인 → **Redirect URI** = 2단계에서 본 `redirect_uri` (카카오)

`http`/`https`, 도메인, 경로, 끝 `/` 유무까지 **완전히 동일**해야 합니다.

### 4단계: .env에 소셜 키 넣기

각 제공자 앱에서 **Client ID / Client Secret(또는 REST API 키)** 발급 후 `.env`에 추가:

```env
NAVER_CLIENT_ID=발급값
NAVER_CLIENT_SECRET=발급값
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=발급값
KAKAO_REST_API_KEY=발급값
# KAKAO_CLIENT_SECRET=  (선택)
```

저장 후 **서버 재시작** (로컬이면 Flask 프로세스 다시 실행).

### 5단계: 로그인 테스트

- 로그인 페이지에서 네이버/구글/카카오 버튼 클릭
- 각 제공자 로그인 → 콜백 후 사이트로 돌아와 로그인된 상태면 성공

**정리:**  
0) 기준 URL 정함 → 1) FLASK_SECRET_KEY + (운영 시 OAUTH_REDIRECT_BASE) → 2) 관리자로 `/auth/status` 접속해 redirect_uri 확인 → 3) 그 redirect_uri를 각 개발자 콘솔에 등록 → 4) .env에 키 입력 후 재시작 → 5) 로그인 테스트

---

## 1. 네이버 로그인 (상세)

1. [네이버 개발자센터](https://developers.naver.com/) 로그인 → **Application** → **애플리케이션 등록**
2. **사용 API**: 네이버 로그인 선택, **로그인 오픈 API 서비스 환경**에 **웹** 추가
3. **웹 서비스 URL**: `https://your-domain.com` (로컬 테스트 시 `http://localhost:5000`)
4. **Callback URL**: `https://your-domain.com/auth/naver/callback` (로컬: `http://localhost:5000/auth/naver/callback`)
5. 등록 후 **Client ID**, **Client Secret** 확인
6. `.env`에 추가:
   ```env
   NAVER_CLIENT_ID=발급받은_클라이언트ID
   NAVER_CLIENT_SECRET=발급받은_시크릿
   ```

---

## 2. 구글 로그인 (상세)

1. [Google Cloud Console](https://console.cloud.google.com/) → **API 및 서비스** → **사용자 인증 정보** → **사용자 인증 정보 만들기** → **OAuth 2.0 클라이언트 ID**
2. **애플리케이션 유형**: 웹 애플리케이션
3. **승인된 리디렉션 URI**에 추가: `https://your-domain.com/auth/google/callback` (로컬: `http://localhost:5000/auth/google/callback`)
4. **클라이언트 ID**, **클라이언트 보안 비밀** 복사
5. `.env`에 추가:
   ```env
   GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=시크릿값
   ```

---

## 3. 카카오 로그인 (상세)

1. [카카오 개발자](https://developers.kakao.com/) → **내 애플리케이션** → **애플리케이션 추가**
2. **앱 설정** → **플랫폼** → **Web** 추가 → **사이트 도메인**: `https://your-domain.com` (로컬: `http://localhost:5000`)
3. **카카오 로그인** → **활성화** ON → **Redirect URI**: `https://your-domain.com/auth/kakao/callback` (로컬: `http://localhost:5000/auth/kakao/callback`)
4. **앱 키**에서 **REST API 키** 복사. (선택) **카카오 로그인** → **보안**에서 **Client Secret** 생성 후 사용
5. `.env`에 추가:
   ```env
   KAKAO_REST_API_KEY=발급받은_REST_API_키
   KAKAO_CLIENT_SECRET=  # 선택 (보안 강화 시)
   ```
   또는 `KAKAO_CLIENT_ID` 로 같은 REST API 키를 넣어도 동작합니다.

---

## 동작 요약

| 구분   | 진입 URL           | 콜백 URL                  | 환경 변수                          |
|--------|--------------------|----------------------------|------------------------------------|
| 네이버 | `/auth/naver`     | `/auth/naver/callback`     | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| 구글   | `/auth/google`    | `/auth/google/callback`    | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| 카카오 | `/auth/kakao`     | `/auth/kakao/callback`     | `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET`(선택) |

설정하지 않은 항목은 로그인 페이지에 노출되어 있어도, 클릭 시 "○○ 로그인이 설정되지 않았습니다." 메시지 후 로그인 페이지로 돌아갑니다.

---

## 통합 로그인 오류 점검 (전체 오류 시)

통합 로그인이 전부 오류일 때 아래 순서로 확인하세요.

### 1. 환경 변수(.env) 로드 여부

- **로컬**: 프로젝트 루트에 `.env` 파일이 있는지, `FLASK_SECRET_KEY`와 소셜 로그인 키가 **한 줄에 하나씩**, `KEY=값` 형식으로 들어가 있는지 확인.
- **Render 등 호스팅**: 대시보드 → Environment에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `KAKAO_REST_API_KEY` 등이 설정되어 있는지 확인. 키 이름 오타(예: `KAKAO_API_KEY`만 있고 `KAKAO_REST_API_KEY` 없음) 주의.

### 2. FLASK_SECRET_KEY

- **반드시 설정.** 비어 있거나 없으면 **세션이 유지되지 않아** `/auth/xxx` → 콜백 이동 시 `oauth_state`가 맞지 않아 "잘못된 요청입니다."로 돌아옵니다.
- `.env`에 `FLASK_SECRET_KEY=32자이상랜덤문자` 형태로 넣고 서버 재시작.

### 3. 콜백 URL(Redirect URI) 일치 — **Error 400: redirect_uri_mismatch** 해결

- Google/네이버/카카오는 **리다이렉트 URI**가 개발자 콘솔에 등록한 값과 **한 글자도 달라도 안 됩니다** (프로토콜, 도메인, 경로, 끝 슬래시 여부까지 동일해야 함).
- **프록시/호스팅(Render 등) 사용 시** 서버가 받는 요청이 `http` 또는 내부 주소일 수 있어, 앱이 만드는 redirect_uri가 `http://...` 또는 잘못된 도메인으로 나가 **redirect_uri_mismatch**가 발생할 수 있습니다.
- **해결:** `.env`에 **실제 서비스 주소**를 넣어 두세요 (끝에 `/` 없이).
  ```env
  OAUTH_REDIRECT_BASE=https://basam.co.kr
  ```
  이렇게 하면 redirect_uri가 항상 `https://basam.co.kr/auth/google/callback` 등으로 고정됩니다.
- **관리자 로그인 후** `https://your-domain.com/auth/status` 또는 `/admin/auth-status` 에 접속하면, 각 제공자별 **redirect_uri**가 JSON으로 나옵니다. 이 값과 개발자 콘솔에 등록한 URL이 **완전히 동일**해야 합니다.
  - 네이버: [네이버 개발자센터] → 애플리케이션 → 로그인 오픈 API 서비스 환경(웹) → **Callback URL**
  - 구글: [Google Cloud Console] → 사용자 인증 정보 → 해당 OAuth 클라이언트 → **승인된 리디렉션 URI**
  - 카카오: [카카오 개발자] → 내 애플리케이션 → 카카오 로그인 → **Redirect URI**
- `http` / `https`, 맨 뒤 `/` 유무, 포트 번호까지 모두 일치해야 합니다.

### 4. 개발자 콘솔 설정

- **네이버**: 사용 API에 "네이버 로그인" 포함, **웹** 환경 추가 후 Callback URL 등록.
- **구글**: OAuth 동의 화면 구성 완료, **웹 애플리케이션** 타입의 클라이언트 ID 사용, 리디렉션 URI 추가.
- **카카오**: 플랫폼에 **Web** 추가, 카카오 로그인 **활성화**, Redirect URI에 콜백 URL 등록.

### 5. 오류 메시지별 대응

| 메시지 | 확인할 것 |
|--------|-----------|
| "○○ 로그인이 설정되지 않았습니다." | 해당 제공자의 CLIENT_ID / CLIENT_SECRET(또는 REST API 키)가 .env/환경 변수에 있는지 |
| "잘못된 요청입니다." | FLASK_SECRET_KEY 설정, 세션 쿠키(브라우저에서 로그인 페이지와 같은 도메인으로 콜백 오는지) |
| "○○ 로그인(토큰)에 실패했습니다." | CLIENT_SECRET 포함 키 값 정확한지, **콜백 URL이 개발자 콘솔과 일치하는지** |
| "프로필 조회에 실패했습니다." | 위와 동일 + 해당 제공자 API 정책(이메일/프로필 동의 여부) |

### 6. 관리자 진단 URL

- 관리자 계정으로 로그인한 뒤 아래 **둘 중 하나**에 접속하면, 키 설정 여부와 현재 서버가 사용하는 **redirect_uri** 를 JSON으로 볼 수 있습니다. 여기 나온 `redirect_uri`를 각 개발자 콘솔에 그대로 등록해 두면 됩니다.
  - **`/admin/auth-status`**
  - **`/auth/status`** (앞 주소가 404일 때 사용. 예: 배포 환경에서 `/admin` 경로가 다르게 동작하는 경우)
