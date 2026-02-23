"""푸시 알림용 VAPID 키 생성. 한 번 실행 후 출력된 값을 .env에 넣으세요."""
import base64

def _to_base64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

def _key_to_str(key, is_public):
    """bytes/str이면 그대로, cryptography 키 객체면 base64url 문자열로 변환."""
    if isinstance(key, str):
        return key
    if isinstance(key, bytes):
        return key.decode("utf-8", errors="replace") if is_public else _to_base64url(key)
    # cryptography 키 객체 (py_vapid 최신 버전)
    try:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        if is_public:
            raw = key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
            return _to_base64url(raw)
        raw = key.private_numbers().private_value.to_bytes(32, "big")
        return _to_base64url(raw)
    except Exception:
        return str(key)

try:
    from py_vapid import Vapid01
except ImportError:
    print("pip install py-vapid 후 다시 실행하세요.")
    exit(1)
v = Vapid01()
v.generate_keys()
pub = _key_to_str(v.public_key, is_public=True)
priv = _key_to_str(v.private_key, is_public=False)
print("\n아래 두 줄을 .env 파일에 추가하세요:\n")
print("VAPID_PUBLIC_KEY=" + pub)
print("VAPID_PRIVATE_KEY=" + priv)
print("\n(선택) VAPID_SUB_MAILTO=mailto:your@email.com")
