"""푸시 알림용 VAPID 키 생성. 한 번 실행 후 출력된 값을 .env에 넣으세요."""
try:
    from py_vapid import Vapid01
except ImportError:
    print("pip install py-vapid 후 다시 실행하세요.")
    exit(1)
v = Vapid01()
v.generate_keys()
pub = v.public_key.decode() if isinstance(v.public_key, bytes) else v.public_key
priv = v.private_key.decode() if isinstance(v.private_key, bytes) else v.private_key
print("\n아래 두 줄을 .env 파일에 추가하세요:\n")
print("VAPID_PUBLIC_KEY=" + pub)
print("VAPID_PRIVATE_KEY=" + priv)
print("\n(선택) VAPID_SUB_MAILTO=mailto:your@email.com")
