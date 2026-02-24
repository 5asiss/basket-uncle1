# --------------------------------------------------------------------------------
# 설정·상수 (환경변수 기반)
# --------------------------------------------------------------------------------
import os

# 결제 연동 (Toss Payments)
TOSS_CLIENT_KEY = (os.getenv("TOSS_CLIENT_KEY") or "").strip() or "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = (os.getenv("TOSS_SECRET_KEY") or "").strip() or "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"
TOSS_CONFIRM_KEY = (os.getenv("TOSS_CONFIRM_KEY") or "").strip() or "f888f57918e6b0de7463b6d5ac1edd05adf1cde50a28b2c8699983fa88541dda"

# 카카오맵(다음지도) - 배송구역 관리 탭
KAKAO_MAP_APP_KEY = os.getenv("KAKAO_MAP_APP_KEY", "").strip()

# 이메일 발송 (판매자 발주 등)
MAIL_SERVER = os.getenv("MAIL_SERVER", "").strip()
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "").strip()
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").strip()
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1").strip().lower() in ("1", "true", "yes")
DEFAULT_MAIL_FROM = os.getenv("DEFAULT_MAIL_FROM", MAIL_USERNAME or "noreply@localhost").strip()

# GitHub 백업
GITHUB_BACKUP_TOKEN = os.getenv("GITHUB_BACKUP_TOKEN", "").strip()
GITHUB_BACKUP_REPO = os.getenv("GITHUB_BACKUP_REPO", "").strip()

# 카카오 알림톡 (재방문 유도 등 마케팅 메시지)
# 발송 API는 업체(카카오 비즈메시지, NHN, 카페24 등)별로 상이. 아래는 공통으로 쓰는 값.
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
KAKAO_ALIMTALK_SENDER_KEY = os.getenv("KAKAO_ALIMTALK_SENDER_KEY", "").strip()
KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY = os.getenv("KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY", "").strip()
# 실제 발송 URL (예: NHN 시 "https://api-alimtalk.nhn.cloud/...") 설정 시 사용
KAKAO_ALIMTALK_API_URL = os.getenv("KAKAO_ALIMTALK_API_URL", "").strip()
# 알림톡 건당 비용(원). ROAS 계산용. 미설정 시 0으로 계산.
KAKAO_ALIMTALK_COST_PER_MSG = int(os.getenv("KAKAO_ALIMTALK_COST_PER_MSG", "0").strip() or "0")

# 당근마켓 자동 포스팅 (Selenium)
DAANGN_LOGIN_PHONE = os.getenv("DAANGN_LOGIN_PHONE", "").strip()
DAANGN_LOGIN_PASSWORD = os.getenv("DAANGN_LOGIN_PASSWORD", "").strip()
DAANGN_BIZ_PROFILE_URL = os.getenv("DAANGN_BIZ_PROFILE_URL", "").strip()
