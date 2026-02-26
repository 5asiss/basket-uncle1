# --------------------------------------------------------------------------------
# 유틸리티 (이메일, 백업, 재고 초기화, 알림톡 재방문 유도, ROAS)
# --------------------------------------------------------------------------------
import os
import re
import zipfile
import tempfile
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta
from urllib.parse import urlparse
import requests

from config import (
    MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_USE_TLS, DEFAULT_MAIL_FROM,
    GITHUB_BACKUP_TOKEN, GITHUB_BACKUP_REPO,
    KAKAO_REST_API_KEY, KAKAO_ALIMTALK_SENDER_KEY, KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY,
    KAKAO_ALIMTALK_API_URL, KAKAO_ALIMTALK_COST_PER_MSG,
    SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_KAKAO_PF_ID,
    SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY, SOLAPI_KAKAO_TEMPLATE_ID_ORDER_CREATED,
    SOLAPI_KAKAO_TEMPLATE_ID_DELIVERY_COMPLETE, SOLAPI_SENDER_PHONE,
)
from delivery_system import db_delivery
from models import Product

db = db_delivery


def _get_main_db_path():
    """메인 DB(주문 등) SQLite 파일 경로. Flask 컨텍스트 또는 delivery_system 경로 사용."""
    try:
        from flask import current_app
        uri = (current_app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
        if uri and "sqlite" in uri.lower():
            parsed = urlparse(uri)
            path = (parsed.path or "").lstrip("/")
            if path:
                root = getattr(current_app, "root_path", None) or os.getcwd()
                for base in [root, os.path.join(root, "instance"), os.getcwd()]:
                    full = os.path.abspath(os.path.join(base, path))
                    if os.path.isfile(full):
                        return full
                return os.path.abspath(path)
    except Exception:
        pass
    try:
        from delivery_system import logi_get_main_db_path
        return logi_get_main_db_path()
    except Exception:
        pass
    return os.path.abspath(
        os.getenv("MAIN_DB_PATH") or os.path.join(os.path.dirname(__file__), "instance", "direct_trade_mall.db")
    )


def get_inactive_songdo_customers(weeks=2, limit=500):
    """
    SQL로 '최근 N주간 주문이 없는 송도 고객' 리스트 추출.
    반환: [ {"customer_phone": "...", "customer_name": "...", "last_order_at": "..."}, ... ]
    """
    path = _get_main_db_path()
    if not os.path.isfile(path):
        return []
    days = max(1, int(weeks) * 7)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            WITH last_orders AS (
                SELECT 
                    customer_phone,
                    customer_name,
                    MAX(created_at) AS last_order_at
                FROM "order"
                WHERE delivery_address LIKE '%송도%'
                  AND status NOT IN ('결제취소')
                  AND customer_phone IS NOT NULL AND TRIM(customer_phone) != ''
                GROUP BY customer_phone
            )
            SELECT customer_phone, customer_name, last_order_at
            FROM last_orders
            WHERE last_order_at < datetime('now', ?)
            ORDER BY last_order_at DESC
            LIMIT ?
        """, (f"-{days} days", limit))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "customer_phone": re.sub(r"\D", "", (r["customer_phone"] or "")),
                "customer_name": (r["customer_name"] or "").strip() or "고객",
                "last_order_at": r["last_order_at"],
            }
            for r in rows
        ]
    except Exception:
        return []


def send_solapi_kakao_alimtalk(phone, template_id, variables=None, from_phone=None):
    """
    솔라피(Solapi)를 이용해 카카오 알림톡 1건 발송.
    variables: 템플릿 변수 dict. 키는 카카오 템플릿의 치환문구와 일치 (예: {"#{고객명}": "홍길동"}).
    from_phone: 대체발송(SMS/LMS)용 발신번호. 미설정 시 SOLAPI_SENDER_PHONE 사용.
    반환: (성공 여부, 에러 메시지 또는 None)
    """
    if not (SOLAPI_API_KEY and SOLAPI_API_SECRET and SOLAPI_KAKAO_PF_ID and template_id):
        return False, "SOLAPI_API_KEY, SOLAPI_API_SECRET, SOLAPI_KAKAO_PF_ID, template_id 중 하나가 비어 있습니다."
    phone_clean = re.sub(r"\D", "", str(phone).strip())
    if len(phone_clean) < 10:
        return False, "전화번호 형식이 올바르지 않습니다."
    variables = variables or {}
    # Solapi 변수는 문자열만 허용
    variables = {k: str(v)[:1000] for k, v in variables.items()}
    from_ = (from_phone or SOLAPI_SENDER_PHONE or "").strip().replace("-", "").replace(" ", "")
    try:
        from solapi import SolapiMessageService
        from solapi.model import RequestMessage
        from solapi.model.kakao.kakao_option import KakaoOption
        message_service = SolapiMessageService(api_key=SOLAPI_API_KEY, api_secret=SOLAPI_API_SECRET)
        kakao_option = KakaoOption(
            pf_id=SOLAPI_KAKAO_PF_ID,
            template_id=template_id,
            variables=variables if variables else None,
        )
        message = RequestMessage(
            from_=from_ or None,
            to=phone_clean,
            kakao_options=kakao_option,
        )
        response = message_service.send(message)
        try:
            c = getattr(response, "group_info", None) and getattr(response.group_info, "count", None)
            success = (getattr(c, "registered_success", 0) or getattr(c, "registered", 0)) >= 1
        except Exception:
            success = True  # 요청 수락 시 성공으로 간주
        return success, None
    except Exception as e:
        return False, str(e)


def send_kakao_alimtalk(phone, customer_name, coupon_code=None, template_code=None):
    """
    카카오 알림톡 발송 (할인 쿠폰 등).
    솔라피(SOLAPI_*) 설정이 있으면 솔라피로 발송, 없으면 기존 KAKAO_ALIMTALK_API_URL 사용.
    반환: (성공 여부, 에러 메시지 또는 None)
    """
    phone_clean = re.sub(r"\D", "", str(phone).strip())
    if len(phone_clean) < 10:
        return False, "전화번호 형식이 올바르지 않습니다."
    template_code = template_code or KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY

    # 1) 솔라피 사용 (우선)
    if SOLAPI_API_KEY and SOLAPI_API_SECRET and SOLAPI_KAKAO_PF_ID and SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY:
        variables = {"#{고객명}": (customer_name or "고객")[:20], "#{쿠폰}": (coupon_code or "WELCOME2WEEKS")[:20]}
        # 템플릿에 맞게 변수명 조정 (솔라피/카카오에 등록한 변수명에 맞춤)
        ok, err = send_solapi_kakao_alimtalk(
            phone_clean,
            SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY,
            variables=variables,
        )
        try:
            from flask import current_app
            with current_app.app_context():
                from models import MarketingAlimtalkLog
                log = MarketingAlimtalkLog(
                    phone=phone_clean,
                    customer_name=customer_name,
                    template_code=SOLAPI_KAKAO_TEMPLATE_ID_RECOVERY,
                    coupon_code=(coupon_code or "WELCOME2WEEKS"),
                    success=ok,
                    memo=err,
                )
                db.session.add(log)
                db.session.commit()
        except Exception:
            pass
        return ok, err

    # 2) 기존 API (NHN/카페24 등) — 솔라피 미설정 시에만
    if not (KAKAO_ALIMTALK_API_URL and KAKAO_REST_API_KEY and template_code):
        return False, "알림톡 발송 설정이 없습니다. 솔라피(SOLAPI_*) 또는 KAKAO_ALIMTALK_API_URL·KAKAO_REST_API_KEY·템플릿 코드를 설정해 주세요."
    payload = {
        "sender_key": KAKAO_ALIMTALK_SENDER_KEY or "",
        "template_code": template_code,
        "phone_number": phone_clean,
        "message": {
            "name": customer_name[:10],
            "coupon": (coupon_code or "WELCOME2WEEKS")[:20],
        },
    }
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(KAKAO_ALIMTALK_API_URL, json=payload, headers=headers, timeout=15)
        success = r.status_code in (200, 201)
        err = None if success else (r.text or str(r.status_code))
        try:
            from flask import current_app
            with current_app.app_context():
                from models import MarketingAlimtalkLog
                log = MarketingAlimtalkLog(
                    phone=phone_clean,
                    customer_name=customer_name,
                    template_code=template_code,
                    coupon_code=(coupon_code or "WELCOME2WEEKS"),
                    success=success,
                    memo=err,
                )
                db.session.add(log)
                db.session.commit()
        except Exception:
            pass
        return success, err
    except Exception as e:
        return False, str(e)


def send_alimtalk_order_event(msg_type, phone, customer_name, order_id, **extra_variables):
    """
    주문/배송 이벤트에 따른 솔라피 카카오 알림톡 발송 (템플릿이 등록된 경우만).
    msg_type: 'order_created' | 'delivery_complete'
    extra_variables: 템플릿 변수 추가 (예: {"#{상품명}": "사과 2kg"})
    반환: (성공 여부, 에러 메시지 또는 None)
    """
    if not (SOLAPI_API_KEY and SOLAPI_API_SECRET and SOLAPI_KAKAO_PF_ID):
        return False, None
    template_id = None
    if msg_type == "order_created":
        template_id = SOLAPI_KAKAO_TEMPLATE_ID_ORDER_CREATED
    elif msg_type == "delivery_complete":
        template_id = SOLAPI_KAKAO_TEMPLATE_ID_DELIVERY_COMPLETE
    if not template_id:
        return False, None
    variables = {"#{주문번호}": (order_id or "")[:50], "#{고객명}": (customer_name or "고객")[:20]}
    variables.update(extra_variables)
    return send_solapi_kakao_alimtalk(phone, template_id, variables=variables)


def run_reengagement_alimtalk(weeks=2, dry_run=True, limit=100, coupon_code="WELCOME2WEEKS"):
    """
    휴면 송도 고객에게 할인 쿠폰 알림톡 일괄 발송.
    dry_run=True면 발송 없이 대상 인원만 반환.
    반환: {"sent": N, "failed": M, "list": [...] }
    """
    from config import KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY
    customers = get_inactive_songdo_customers(weeks=weeks, limit=limit)
    if not customers:
        return {"sent": 0, "failed": 0, "list": []}
    if dry_run:
        return {"sent": 0, "failed": 0, "list": [c["customer_phone"] for c in customers], "dry_run": True}
    sent, failed = 0, 0
    for c in customers:
        ok, _ = send_kakao_alimtalk(
            c["customer_phone"],
            c["customer_name"],
            coupon_code=coupon_code,
            template_code=KAKAO_ALIMTALK_TEMPLATE_CODE_RECOVERY,
        )
        if ok:
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "list": [c["customer_phone"] for c in customers]}


def send_alimtalk_welcome(phone, customer_name, coupon_code="WELCOME2WEEKS"):
    """
    신규 회원 환영 알림톡 발송용 헬퍼.
    1순위: 솔라피 WELCOME 템플릿(SOLAPI_KAKAO_TEMPLATE_ID_WELCOME) 사용.
    2순위: 기존 재방문 쿠폰 템플릿(send_kakao_alimtalk) 재사용.
    """
    phone_clean = re.sub(r"\D", "", str(phone).strip())
    if len(phone_clean) < 10:
        return False, "전화번호 형식이 올바르지 않습니다."
    # 1) 솔라피 WELCOME 템플릿이 설정된 경우 우선 사용
    if SOLAPI_API_KEY and SOLAPI_API_SECRET and SOLAPI_KAKAO_PF_ID and SOLAPI_KAKAO_TEMPLATE_ID_WELCOME:
        variables = {"#{고객명}": (customer_name or "고객")[:20], "#{쿠폰}": (coupon_code or "WELCOME2WEEKS")[:20]}
        ok, err = send_solapi_kakao_alimtalk(
            phone_clean,
            SOLAPI_KAKAO_TEMPLATE_ID_WELCOME,
            variables=variables,
        )
        try:
            from flask import current_app
            with current_app.app_context():
                from models import MarketingAlimtalkLog
                log = MarketingAlimtalkLog(
                    phone=phone_clean,
                    customer_name=customer_name,
                    template_code=SOLAPI_KAKAO_TEMPLATE_ID_WELCOME,
                    coupon_code=(coupon_code or "WELCOME2WEEKS"),
                    success=ok,
                    memo=err,
                )
                db.session.add(log)
                db.session.commit()
        except Exception:
            pass
        return ok, err
    # 2) 솔라피 WELCOME 미설정 시, 기존 쿠폰 알림톡 로직 사용
    return send_kakao_alimtalk(phone, customer_name, coupon_code=coupon_code)


def get_roas_metrics(days_since=30):
    """
    알림톡 발송 대비 재방문(주문) 비율로 ROAS 검증 포인트 제공.
    SQL: 발송 로그와 주문 테이블을 이용해 재방문 건수·비율 계산.
    반환: { "sent_total", "revisit_orders", "revisit_rate" }
    """
    try:
        from flask import current_app
        with current_app.app_context():
            from models import MarketingAlimtalkLog, Order
            since = datetime.now() - timedelta(days=days_since)
            logs = MarketingAlimtalkLog.query.filter(
                MarketingAlimtalkLog.sent_at >= since,
                MarketingAlimtalkLog.success == True,
            ).all()
            if not logs:
                return {"sent_total": 0, "revisit_orders": 0, "revisit_rate": 0.0}
            phones = {l.phone for l in logs}
            phone_to_sent = {l.phone: l.sent_at for l in logs}
            # 발송 이후에 주문한 건만 재방문으로 집계 (같은 기간 내)
            revisit_count = 0
            for phone in phones:
                sent_at = phone_to_sent.get(phone)
                if not sent_at:
                    continue
                if isinstance(sent_at, str):
                    sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
                q = Order.query.filter(
                    Order.customer_phone.isnot(None),
                    db.func.replace(Order.customer_phone, "-", "").like(f"%{phone[-10:]}%"),
                    Order.created_at > sent_at,
                    Order.created_at >= since,
                    ~Order.status.in_(["결제취소"]),
                )
                revisit_count += q.count()
            sent_total = len(logs)
            return {
                "sent_total": sent_total,
                "revisit_orders": revisit_count,
                "revisit_rate": round(revisit_count / sent_total, 4) if sent_total else 0.0,
            }
    except Exception as e:
        return {"sent_total": 0, "revisit_orders": 0, "revisit_rate": 0.0, "error": str(e)}


def get_roas_with_revenue(days_since=30, cost_per_msg=None):
    """
    알림톡 비용 대비 매출(ROAS) 검증.
    - 발송 건수 × 건당 비용 = 총 광고비
    - 재방문 주문의 total_price 합계 = 매출
    - ROAS = 매출 / 광고비 (광고비 0이면 0 반환)
    반환: { "ad_spend", "revisit_revenue", "roas", "revisit_orders", "sent_total" }
    """
    cost_per_msg = cost_per_msg if cost_per_msg is not None else KAKAO_ALIMTALK_COST_PER_MSG
    try:
        from flask import current_app
        with current_app.app_context():
            from models import MarketingAlimtalkLog, Order
            since = datetime.now() - timedelta(days=days_since)
            logs = MarketingAlimtalkLog.query.filter(
                MarketingAlimtalkLog.sent_at >= since,
                MarketingAlimtalkLog.success == True,
            ).all()
            if not logs:
                return {
                    "sent_total": 0, "revisit_orders": 0, "revisit_revenue": 0,
                    "ad_spend": 0, "roas": 0.0,
                }
            phones = {l.phone for l in logs}
            phone_to_sent = {l.phone: l.sent_at for l in logs}
            revisit_revenue = 0
            revisit_count = 0
            for phone in phones:
                sent_at = phone_to_sent.get(phone)
                if not sent_at:
                    continue
                if isinstance(sent_at, str):
                    sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
                orders = Order.query.filter(
                    Order.customer_phone.isnot(None),
                    db.func.replace(Order.customer_phone, "-", "").like(f"%{phone[-10:]}%"),
                    Order.created_at > sent_at,
                    Order.created_at >= since,
                    ~Order.status.in_(["결제취소"]),
                ).all()
                for o in orders:
                    revisit_count += 1
                    revisit_revenue += (o.total_price or 0)
            ad_spend = len(logs) * max(0, cost_per_msg)
            roas = (revisit_revenue / ad_spend) if ad_spend else 0.0
            return {
                "sent_total": len(logs),
                "revisit_orders": revisit_count,
                "revisit_revenue": revisit_revenue,
                "ad_spend": ad_spend,
                "roas": round(roas, 2),
            }
    except Exception as e:
        return {
            "sent_total": 0, "revisit_orders": 0, "revisit_revenue": 0,
            "ad_spend": 0, "roas": 0.0, "error": str(e),
        }


def get_daangn_conversion_metrics(days_since=30):
    """
    당근마켓 유입 전환율 검증. utm_source에 'daangn' 또는 '당근' 포함된 주문 기준.
    반환: { "visits" (유입 주문/세션 수), "orders_paid" (결제 완료 건수), "conversion_rate", "revenue" }
    """
    try:
        from flask import current_app
        with current_app.app_context():
            from models import Order
            since = datetime.now() - timedelta(days=days_since)
            from sqlalchemy import or_
            cond = or_(
                db.func.lower(Order.utm_source).like("%daangn%"),
                db.func.lower(Order.utm_source).like("%당근%"),
            )
            q = Order.query.filter(Order.created_at >= since, cond)
            visits = q.count()
            q2 = Order.query.filter(
                Order.created_at >= since,
                ~Order.status.in_(["결제취소"]),
                cond,
            )
            orders_paid = q2.count()
            revenue = sum((o.total_price or 0) for o in q2.all())
            rate = (orders_paid / visits) if visits else 0.0
            return {
                "visits": visits,
                "orders_paid": orders_paid,
                "conversion_rate": round(rate, 4),
                "revenue": revenue,
            }
    except Exception as e:
        return {"visits": 0, "orders_paid": 0, "conversion_rate": 0.0, "revenue": 0, "error": str(e)}


def send_mail(to_email, subject, body_plain):
    """SMTP로 이메일 발송. MAIL_* 환경변수 설정 필요. 실패 시 예외."""
    if not to_email or not (MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD):
        raise ValueError("이메일 설정이 되어 있지 않습니다. 관리자 → 이메일 설정 안내를 확인하세요.")
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formataddr
    msg = MIMEText(body_plain, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("바구니삼촌", DEFAULT_MAIL_FROM))
    msg["To"] = to_email
    with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as smtp:
        if MAIL_USE_TLS:
            smtp.starttls()
        smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
        smtp.sendmail(DEFAULT_MAIL_FROM, [to_email], msg.as_string())


def _sqlite_path_from_uri(uri, app_root):
    """SQLite URI에서 실제 파일 경로 반환. 없으면 None."""
    if not uri or "sqlite" not in uri.lower():
        return None
    parsed = urlparse(uri)
    path = (parsed.path or "").lstrip("/")
    if not path:
        return None
    for base in [app_root, os.path.dirname(app_root), os.path.join(app_root, "instance"), os.getcwd()]:
        full = os.path.join(base, path) if base else path
        full = os.path.abspath(full)
        if os.path.isfile(full):
            return full
    return os.path.abspath(path) if os.path.isfile(path) else None


def _is_postgres_uri(uri):
    """PostgreSQL 연결 문자열 여부."""
    if not uri or not isinstance(uri, str):
        return False
    u = (uri or "").strip().lower()
    return u.startswith("postgresql://") or u.startswith("postgres://")


def _run_pg_dump(database_url, out_path, timeout_sec=300):
    """
    pg_dump로 PostgreSQL 전체 덤프 (plain SQL).
    서버에 postgresql-client(pg_dump)가 설치되어 있어야 함.
    반환: (성공 여부, 에러 메시지 또는 None)
    """
    database_url = (database_url or "").strip()
    if not database_url:
        return False, "DATABASE_URL이 비어 있습니다."
    # Render 등에서는 postgres:// 인데 pg_dump는 둘 다 허용. sslmode 필요 시 쿼리 추가
    if database_url.startswith("postgres://") and "sslmode" not in database_url:
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        if "?" in database_url:
            database_url += "&sslmode=require"
        else:
            database_url += "?sslmode=require"
    try:
        env = os.environ.copy()
        # 비밀번호에 특수문자가 있으면 URI에 이미 인코딩되어 있으므로 그대로 사용
        proc = subprocess.run(
            ["pg_dump", database_url, "-F", "p", "-f", out_path, "--no-owner", "--no-acl"],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[:500]
            return False, f"pg_dump 실패 (code={proc.returncode}): {err}"
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            return False, "pg_dump 출력 파일이 비어 있거나 없습니다."
        return True, None
    except FileNotFoundError:
        return False, "pg_dump를 찾을 수 없습니다. 서버에 postgresql-client 설치가 필요합니다 (예: Dockerfile에서 apt-get install -y postgresql-client)."
    except subprocess.TimeoutExpired:
        return False, "pg_dump 시간 초과 ({}초).".format(timeout_sec)
    except Exception as e:
        return False, str(e) or "pg_dump 실행 중 오류"


def _generate_report_backup_files(tmp_dir):
    """
    법적/실무용 엑셀·리포트 백업 파일 생성 (최근 30일).
    반환: [(절대경로, zip 내 arcname), ...]. 실패 시 빈 리스트 또는 부분 리스트.
    """
    out = []
    try:
        from flask import current_app
        from models import Order, Settlement
        from sqlalchemy import func
        # app에서 사용하는 db (db_delivery = Flask-SQLAlchemy 인스턴스)
        db_session = current_app.extensions["sqlalchemy"].session
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=30)
        orders_in_range = Order.query.filter(
            Order.created_at >= start_dt, Order.created_at <= end_dt
        ).order_by(Order.created_at.desc()).all()
        order_ids = [o.id for o in orders_in_range]
        settlement_by_order = {}
        if order_ids:
            sett_rows = db_session.query(Settlement.order_id, func.sum(Settlement.settlement_total).label("s")).filter(
                Settlement.order_id.in_(order_ids), Settlement.settlement_status == "입금완료"
            ).group_by(Settlement.order_id).all()
            for sid, s in sett_rows:
                settlement_by_order[sid] = int(s or 0)
        import csv
        from io import StringIO
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["결제넘버", "주문일시", "상태", "주문원금", "포인트사용", "실제수입", "정산지급"])
        for o in orders_in_range:
            pay_rec = (o.total_price or 0) - (o.points_used or 0) if getattr(o, "status", None) != "결제취소" else 0
            writer.writerow([
                getattr(o, "order_id", None) or "-",
                (o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "-"),
                getattr(o, "status", None) or "-",
                o.total_price or 0,
                getattr(o, "points_used", None) or 0,
                pay_rec,
                settlement_by_order.get(o.id, 0),
            ])
        csv_path = os.path.join(tmp_dir, "revenue_report_30d.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
        out.append((csv_path, "reports/revenue_report_30d.csv"))
    except Exception:
        pass
    return out


def run_backup():
    """DB 백업: SQLite는 파일 zip, PostgreSQL은 pg_dump 후 zip. GITHUB_BACKUP_* 설정 시 GitHub Release로 업로드. 엑셀/리포트(법적·실무용) 포함. 반환: (성공 여부, 메시지)"""
    from flask import current_app
    app = current_app._get_current_object() if hasattr(current_app, "_get_current_object") else current_app
    app_root = app.root_path
    main_uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    binds = app.config.get("SQLALCHEMY_BINDS") or {}
    files_to_backup = []
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    tmp_dir = tempfile.mkdtemp(prefix="basket_backup_")

    # 1) 메인 DB: SQLite 파일 또는 PostgreSQL pg_dump
    if main_uri and _is_postgres_uri(main_uri):
        dump_path = os.path.join(tmp_dir, "main_dump.sql")
        ok, err = _run_pg_dump(main_uri, dump_path)
        if not ok:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
            return False, f"PostgreSQL 백업 실패: {err}"
        files_to_backup.append((dump_path, "main_dump.sql"))
    elif main_uri and "sqlite" in main_uri.lower():
        p = _sqlite_path_from_uri(main_uri, app_root)
        if p:
            files_to_backup.append((p, "main.db"))

    # 바인드된 SQLite DB (배송 등)
    for name, uri in binds.items():
        if uri and "sqlite" in uri.lower():
            p = _sqlite_path_from_uri(uri, app_root)
            if p:
                files_to_backup.append((p, f"{name}.db"))

    if not files_to_backup:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        return False, "백업할 DB가 없습니다. (SQLite: 파일 경로 확인, PostgreSQL: pg_dump 설치 및 DATABASE_URL 확인)"

    # 2) 법적/실무용 엑셀·리포트 백업 (최근 30일) 추가
    report_files = _generate_report_backup_files(tmp_dir)
    for path, arcname in report_files:
        if os.path.isfile(path):
            files_to_backup.append((path, arcname))

    zip_name = f"backup_{ts}.zip"
    try:
        zip_path = os.path.join(tmp_dir, zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, arcname in files_to_backup:
                if os.path.isfile(src):
                    zf.write(src, arcname)
        if not GITHUB_BACKUP_TOKEN or not GITHUB_BACKUP_REPO:
            dest_dir = os.path.join(app_root, "instance", "backups")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, zip_name)
            shutil.copy2(zip_path, dest)
            return True, f"로컬 백업 완료: {dest}"
        repo = GITHUB_BACKUP_REPO.replace(".git", "").strip()
        if "/" not in repo:
            return False, "GITHUB_BACKUP_REPO 형식: owner/repo"
        tag_name = f"backup-{ts}"
        headers = {"Authorization": f"token {GITHUB_BACKUP_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        create_url = f"https://api.github.com/repos/{repo}/releases"
        r = requests.post(create_url, headers=headers, json={
            "tag_name": tag_name,
            "name": f"Backup {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "body": "자동 백업 (바구니삼촌) — pg_dump/DB + 엑셀·리포트",
        }, timeout=30)
        if r.status_code not in (200, 201):
            return False, f"GitHub Release 생성 실패: {r.status_code} {r.text[:200]}"
        data = r.json()
        upload_url = (data.get("upload_url") or "").split("{")[0].rstrip("?")
        if not upload_url:
            return False, "upload_url 없음"
        with open(zip_path, "rb") as f:
            up = requests.post(f"{upload_url}?name={zip_name}", headers={**headers, "Content-Type": "application/zip"}, data=f, timeout=120)
        if up.status_code not in (200, 201):
            return False, f"GitHub 업로드 실패: {up.status_code} {up.text[:200]}"
        return True, f"GitHub 백업 완료: {repo} release {tag_name}"
    except Exception as e:
        return False, str(e) or "백업 중 오류"
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def get_daangn_today_message(template=None, extra_line=""):
    """
    당근 비즈 소식용 오늘 메시지 생성.
    - template: None이면 기본 문구. "{{date}}" 있으면 오늘 날짜로 치환.
    - extra_line: 오늘의 특가/농수산 가격 등 한 줄 추가.
    """
    from datetime import date
    today = date.today().strftime("%m/%d")
    default = "[바구니삼촌] 오늘도 신선한 농수산으로 찾아뵙겠습니다. 문의 환영합니다."
    msg = (template or default).strip()
    msg = msg.replace("{{date}}", today)
    if extra_line:
        msg = msg.rstrip() + "\n\n" + extra_line.strip()
    return msg


def run_product_stock_reset():
    """마감일 없고 재고 초기화 시간이 설정된 상품: 해당 시각이 지나면 당일 1회 재고를 reset_to_quantity로 복원."""
    now = datetime.now()
    today = now.date()
    try:
        products = Product.query.filter(
            Product.deadline.is_(None),
            Product.reset_time.isnot(None),
            Product.reset_to_quantity.isnot(None),
        ).all()
        for p in products:
            if not p.reset_time or p.reset_to_quantity is None:
                continue
            try:
                t = datetime.strptime(p.reset_time.strip()[:5], "%H:%M").time()
            except (ValueError, TypeError):
                continue
            if now.time() < t:
                continue
            if p.last_reset_at and p.last_reset_at.date() >= today:
                continue
            p.stock = p.reset_to_quantity
            p.last_reset_at = now
        if products:
            db.session.commit()
    except Exception:
        db.session.rollback()
