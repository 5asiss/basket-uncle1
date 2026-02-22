# 네이버 · 구글 · 카카오 통합 로그인 설정

로그인 페이지에서 **네이버 → 구글 → 카카오** 순으로 버튼이 노출됩니다. 각 개발자 콘솔에서 앱을 등록한 뒤 `.env`에 키를 넣으면 됩니다.

---

## 1. 네이버 로그인

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

## 2. 구글 로그인

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

## 3. 카카오 로그인

1. [카카오 개발자](https://developers.kakao.com/) → **내 애플리케이션** → **애플리케이션 추가**
2. **앱 설정** → **플랫폼** → **Web** 추가 → **사이트 도메인**: `https://your-domain.com` (로컬: `http://localhost:5000`)
3. **카카오 로그인** → **활성화** ON → **Redirect URI**: `https://basam.co.kr/auth/kakao/callback` (로컬: `http://localhost:5000/auth/kakao/callback`)
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

### 3. 콜백 URL(Redirect URI) 일치

- 앱이 실제로 동작하는 **도메인·프로토콜** 기준으로 콜백 URL이 생성됩니다.
  - 로컬: `http://localhost:5000/auth/naver/callback` 등
  - 운영: `https://your-domain.com/auth/naver/callback` 등
- **관리자 로그인 후** 브라우저에서 `https://your-domain.com/admin/auth-status` 접속 시, 각 제공자별 `redirect_uri`가 JSON으로 나옵니다. 이 값과 아래 개발자 콘솔에 등록한 URL이 **완전히 동일**해야 합니다.
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
