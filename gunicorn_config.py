# Render 등 호스팅: PORT 환경변수를 Python에서 읽어 바인딩 (Start Command에서 $PORT 미확장 시 대비)
import os

bind = "0.0.0.0:%s" % os.environ.get("PORT", "10000")
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
timeout = 300
worker_tmp_dir = "/dev/shm"  # Render/일부 환경에서 메모리 기반 tmp 사용
