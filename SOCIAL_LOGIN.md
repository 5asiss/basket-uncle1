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
   KAKAO_CLIENT_SECRET=  # 선택 (보안 강화 시)1c27b53b6287a15e0ad5ce39a9c2cfc6
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
