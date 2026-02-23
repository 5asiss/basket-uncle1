import os
import requests
from dotenv import load_dotenv
import base64
from datetime import datetime, timedelta
from io import BytesIO
import re
import json
import random # 최신상품 랜덤 노출을 위해 추가

import pandas as pd
from flask import Flask, render_template_string, request, redirect, url_for, session, send_file, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text, or_
from delivery_system import logi_bp # 배송 시스템 파일에서 Blueprint 가져오기
load_dotenv()

# --------------------------------------------------------------------------------
# 1. 초기 설정 및 Flask 인스턴스 생성
# --------------------------------------------------------------------------------
# --- 수정 전 기존 코드 ---
# app = Flask(__name__)
# app.register_blueprint(logi_bp) 
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db'
# db = SQLAlchemy(app)

# --- 수정 후 (이 부분으로 교체하세요) ---
from delivery_system import logi_bp, db_delivery

app = Flask(__name__)
# 프록시(Render, nginx 등) 뒤에서 redirect_uri가 올바르게 https·실도메인으로 생성되도록
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_fallback_key")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# 1. 모든 DB 경로 설정
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///direct_trade_mall.db")
app.config['SQLALCHEMY_BINDS'] = {
    'delivery': os.getenv("DELIVERY_DATABASE_URL", "sqlite:///delivery.db")
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. DB 연결 (공백 제거 버전)
db = db_delivery
db.init_app(app)

# 3. 배송 관리 시스템 Blueprint 등록 (주소 접두어 /logi 적용됨)
app.register_blueprint(logi_bp)


@app.route('/admin/logi')
@app.route('/admin/logi/')
def admin_logi_redirect():
    """/admin/logi 접속 시 배송(로지) 시스템(/logi)으로 리다이렉트"""
    return redirect('/logi')

# 결제 연동 키 (Toss Payments). 비어 있으면 아래 테스트 키 사용.
# - 고객 취소: 마이페이지 → [품목 취소] 또는 [전체 주문 취소] → 확인 → POST /order/cancel_item 또는 /order/cancel → 토스 취소 API 호출 후 DB 반영.
# - 직접(관리자) 취소: 관리자 주문/품목에서 상태를 '품절취소' 등으로 변경 시 동일 토스 부분취소 API 호출.
TOSS_CLIENT_KEY = (os.getenv("TOSS_CLIENT_KEY") or "").strip() or "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = (os.getenv("TOSS_SECRET_KEY") or "").strip() or "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"
TOSS_CONFIRM_KEY = (os.getenv("TOSS_CONFIRM_KEY") or "").strip() or "f888f57918e6b0de7463b6d5ac1edd05adf1cde50a28b2c8699983fa88541dda"  # 웹훅 서명 검증 등 보안키

# 카카오맵(다음지도) JavaScript 키 - 배송구역 관리 탭에서 사용. 없으면 Leaflet(OSM) 사용
KAKAO_MAP_APP_KEY = os.getenv("KAKAO_MAP_APP_KEY", "").strip()

# 파일 업로드 경로 설정
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


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


# PWA: manifest (역할별 이름: 소비자=바구니삼촌, 관리자=바삼관리자, 기사=바삼배송관리)
@app.route('/manifest.json')
def pwa_manifest():
    base = request.url_root.rstrip('/')
    app_type = request.args.get('app', 'consumer')
    if app_type == 'admin':
        name, short_name = '바삼관리자', '바삼관리자'
        start_url = base + '/admin'
    elif app_type == 'driver':
        name, short_name = '바삼배송관리', '바삼기사'
        start_url = base + '/logi/'
    else:
        name, short_name = '바구니삼촌', '바구니삼촌'
        start_url = base + '/'
    # PWA 로고: static/logo/icon-192.png, icon-512.png 있으면 사용, 없으면 side1.jpg
    logo_dir = os.path.join(app.root_path, app.static_folder or 'static', 'logo')
    icon_192 = base + '/static/logo/icon-192.png' if os.path.isfile(os.path.join(logo_dir, 'icon-192.png')) else base + '/static/logo/side1.jpg'
    icon_512 = base + '/static/logo/icon-512.png' if os.path.isfile(os.path.join(logo_dir, 'icon-512.png')) else base + '/static/logo/side1.jpg'
    icon_type_192 = 'image/png' if icon_192.endswith('.png') else 'image/jpeg'
    icon_type_512 = 'image/png' if icon_512.endswith('.png') else 'image/jpeg'
    icons = [
        {'src': icon_192, 'sizes': '192x192', 'type': icon_type_192, 'purpose': 'any'},
        {'src': icon_512, 'sizes': '512x512', 'type': icon_type_512, 'purpose': 'any'},
        {'src': icon_192, 'sizes': '192x192', 'type': icon_type_192, 'purpose': 'maskable'},
        {'src': icon_512, 'sizes': '512x512', 'type': icon_type_512, 'purpose': 'maskable'},
    ]
    return jsonify({
        'name': name,
        'short_name': short_name,
        'description': '농산물·식자재 배송 신개념 6PL 생활서비스',
        'start_url': start_url,
        'scope': base + '/',
        'id': base + '/',
        'display': 'standalone',
        'background_color': '#fafaf9',
        'theme_color': '#0d9488',
        'orientation': 'portrait-primary',
        'icons': icons
    })


@app.route('/sw.js')
def pwa_sw():
    """Service Worker: 루트에 두어 전체 스코프 적용. 업데이트 반영을 위해 캐시 제한."""
    path = os.path.join(app.root_path, app.static_folder or 'static', 'sw.js')
    r = send_file(path, mimetype='application/javascript')
    r.headers['Cache-Control'] = 'no-cache, max-age=0'
    r.headers['Service-Worker-Allowed'] = '/'
    return r


login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --------------------------------------------------------------------------------
# 2. 데이터베이스 모델 설계 (DB 구조 변경 금지 규칙 준수)
# --------------------------------------------------------------------------------

class CategorySettlement(db.Model):
    """카테고리별 정산 내역 모델 (요청·완료 처리용)"""
    __tablename__ = "category_settlement"
    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(50), nullable=False)
    manager_email = db.Column(db.String(120), nullable=False)
    total_sales = db.Column(db.Integer, default=0)
    delivery_fee_sum = db.Column(db.Integer, default=0)
    settlement_amount = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='입금대기')  # 입금대기, 입금완료, 보류
    requested_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)


class User(db.Model, UserMixin):
    """사용자 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=True)  # 소셜 전용 회원은 이메일 없을 수 있음
    password = db.Column(db.String(200), nullable=True)  # 소셜 로그인 전용 회원은 비밀번호 없음
    name = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))          
    address_detail = db.Column(db.String(200)) 
    entrance_pw = db.Column(db.String(100))    
    request_memo = db.Column(db.String(500))
    is_admin = db.Column(db.Boolean, default=False)
    consent_marketing = db.Column(db.Boolean, default=False)
    # 회원 등급 1~5 (보이지 않게 운영용). 등급별 카테고리 공개·메시지 발송 등에 사용
    member_grade = db.Column(db.Integer, default=1)  # 1, 2, 3, 4, 5
    member_grade_overridden = db.Column(db.Boolean, default=False)  # True면 구매이력 자동반영 안 함
    # 포인트 (회원별 적립·사용)
    points = db.Column(db.Integer, default=0)
    # 소셜 로그인: naver, google, kakao / 해당 provider의 고유 id
    auth_provider = db.Column(db.String(20), nullable=True)
    auth_provider_id = db.Column(db.String(100), nullable=True)
    __table_args__ = (db.UniqueConstraint('auth_provider', 'auth_provider_id', name='uq_user_auth_provider'),)

class Category(db.Model):
    """카테고리 및 판매 사업자 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    tax_type = db.Column(db.String(20), default='과세') 
    manager_email = db.Column(db.String(120), nullable=True) 
    seller_name = db.Column(db.String(100), nullable=True)
    seller_inquiry_link = db.Column(db.String(500), nullable=True)
    order = db.Column(db.Integer, default=0) 
    description = db.Column(db.String(200), nullable=True)
    biz_name = db.Column(db.String(100), nullable=True)
    biz_representative = db.Column(db.String(50), nullable=True)
    biz_reg_number = db.Column(db.String(50), nullable=True)
    biz_address = db.Column(db.String(200), nullable=True)
    biz_contact = db.Column(db.String(50), nullable=True)
    # 정산 계좌 정보 (Seller Business Profile)
    bank_name = db.Column(db.String(50), nullable=True)           # 은행명
    account_holder = db.Column(db.String(100), nullable=True)      # 예금주
    settlement_account = db.Column(db.String(50), nullable=True)  # 정산계좌
    # 등급별 카테고리 공개: 이 값 이상 등급 회원에게만 노출 (None이면 전체)
    min_member_grade = db.Column(db.Integer, nullable=True)  # 1~5 중 하나 또는 None (몇 등급 이상)

class Product(db.Model):
    """상품 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50)) 
    description = db.Column(db.String(200)) 
    name = db.Column(db.String(200))
    price = db.Column(db.Integer)
    spec = db.Column(db.String(100))     
    origin = db.Column(db.String(100))   
    farmer = db.Column(db.String(50))    
    image_url = db.Column(db.String(500)) 
    detail_image_url = db.Column(db.Text) 
    stock = db.Column(db.Integer, default=10) 
    deadline = db.Column(db.DateTime, nullable=True)
    reset_time = db.Column(db.String(5), nullable=True)  # "HH:MM" 마감일 없을 때 매일 이 시각에 재고 초기화
    reset_to_quantity = db.Column(db.Integer, nullable=True)  # 초기화 시 복원할 수량
    last_reset_at = db.Column(db.DateTime, nullable=True)  # 마지막 초기화 시각 (중복 실행 방지)
    is_active = db.Column(db.Boolean, default=True)
    tax_type = db.Column(db.String(20), default='과세') 
    badge = db.Column(db.String(50), default='')

class Cart(db.Model):
    """장바구니 모델"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    product_category = db.Column(db.String(50)) 
    price = db.Column(db.Integer)
    quantity = db.Column(db.Integer, default=1)
    tax_type = db.Column(db.String(20), default='과세')

class Order(db.Model):
    """주문 내역 모델"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    customer_name = db.Column(db.String(50))
    customer_phone = db.Column(db.String(20))
    customer_email = db.Column(db.String(120))
    product_details = db.Column(db.Text) 
    total_price = db.Column(db.Integer)
    delivery_fee = db.Column(db.Integer, default=0) 
    tax_free_amount = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='결제완료')
    is_settled = db.Column(db.Boolean, default=False)  # 정산 완료 여부
    settled_at = db.Column(db.DateTime, nullable=True) # 정산 처리 일시
    settlement_status = db.Column(db.String(20), default='입금대기')  # 입금대기, 입금완료, 취소, 보류    
    order_id = db.Column(db.String(100)) 
    payment_key = db.Column(db.String(200)) 
    delivery_address = db.Column(db.String(500))
    request_memo = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)
    points_used = db.Column(db.Integer, default=0)  # 이 주문에서 사용한 포인트(원)
    quick_extra_fee = db.Column(db.Integer, default=0)  # 퀵폴리곤 지역 추가 배송료(원). 0이면 일반 구역

class OrderItem(db.Model):
    """주문 품목 (품목별 ID·부분취소·배송상태 적용)"""
    __tablename__ = "order_item"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    product_category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    tax_type = db.Column(db.String(20), default='과세')
    cancelled = db.Column(db.Boolean, default=False)  # True면 해당 품목 취소됨
    # 품목별 상태: 결제완료, 배송요청, 배송중, 배송완료, 품절취소, 배송지연, 부분취소
    item_status = db.Column(db.String(30), default='결제완료')
    status_message = db.Column(db.Text, nullable=True)  # 품절·배송지연 등 사유 메시지
    # 품목별 입금상태 (품목ID 기준 개별 적용)
    settlement_status = db.Column(db.String(20), default='입금대기')  # 입금대기, 입금완료, 취소, 보류
    settled_at = db.Column(db.DateTime, nullable=True)  # 해당 품목 입금완료 처리 일시


class OrderItemLog(db.Model):
    """품목별 결제현황·정산상태 변경 이력 (시간별 기록)"""
    __tablename__ = "order_item_log"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    order_item_id = db.Column(db.Integer, nullable=True)  # None이면 주문 단위(정산상태) 로그
    log_type = db.Column(db.String(30), nullable=False)   # 'item_status', 'settlement_status'
    old_value = db.Column(db.String(50), nullable=True)
    new_value = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class UserMessage(db.Model):
    """회원 대상 메시지 (관리자 발송·자동 발송). 가입인사/이벤트/공지/안내/주문·배송 알림 등"""
    __tablename__ = "user_message"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    msg_type = db.Column(db.String(30), default='custom')  # welcome, event, notice, guide, order_created, order_cancelled, delivery_requested, delivery_in_progress, delivery_complete, delivery_delayed, part_cancelled, out_of_stock, custom
    related_order_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    read_at = db.Column(db.DateTime, nullable=True)


class MessageTemplate(db.Model):
    """자동 발송/기본 문구 템플릿. msg_type별 1건. 없으면 기본 문구 사용."""
    __tablename__ = "message_template"
    id = db.Column(db.Integer, primary_key=True)
    msg_type = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class PushSubscription(db.Model):
    """Web Push 구독 정보. 사용자별 복수 기기 등록 가능."""
    __tablename__ = "push_subscription"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint = db.Column(db.String(512), nullable=False)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'endpoint', name='uq_push_user_endpoint'),)


class RestaurantRequest(db.Model):
    """전국맛집요청 게시판. 사진·업체정보·메뉴 등록, 추천 100개 이상 시 당일배송 문구 노출."""
    __tablename__ = "restaurant_request"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    store_name = db.Column(db.String(200), nullable=False)
    store_info = db.Column(db.Text, nullable=True)
    menu = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_hidden = db.Column(db.Boolean, default=False)


class RestaurantRecommend(db.Model):
    """전국맛집요청 추천. 로그인 사용자 1인 1추천."""
    __tablename__ = "restaurant_recommend"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    restaurant_request_id = db.Column(db.Integer, db.ForeignKey('restaurant_request.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'restaurant_request_id', name='uq_restaurant_recommend_user_post'),)


class PartnershipInquiry(db.Model):
    """제휴문의 게시판. 비밀글, 제휴종류·아이템 등 작성, 관리자 관리."""
    __tablename__ = "partnership_inquiry"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    partnership_type = db.Column(db.String(100), nullable=True)
    content = db.Column(db.Text, nullable=True)
    is_secret = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    admin_notes = db.Column(db.Text, nullable=True)
    is_hidden = db.Column(db.Boolean, default=False)


class SitePopup(db.Model):
    """접속 시 알림 팝업. 공지/이벤트/알림 등, 노출 기간·이미지·날짜 설정."""
    __tablename__ = "site_popup"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    popup_type = db.Column(db.String(30), default='notice')  # notice, event, alert
    image_url = db.Column(db.String(500), nullable=True)
    display_date = db.Column(db.String(100), nullable=True)  # 노출용 날짜/기간 문구 (예: 2025.02.22 ~ 02.28)
    start_at = db.Column(db.DateTime, nullable=True)  # 노출 시작
    end_at = db.Column(db.DateTime, nullable=True)    # 노출 종료
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class DeliveryZone(db.Model):
    """배송가능 구역 (폴리곤 좌표 또는 퀵지역 이름/좌표). 그 외 지역은 배송불가."""
    __tablename__ = "delivery_zone"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default="기본 구역")
    polygon_json = db.Column(db.Text, nullable=True)  # JSON: [[lat,lng],...] — 일반 배송구역
    quick_region_polygon_json = db.Column(db.Text, nullable=True)  # JSON: [[lat,lng],...] — 퀵지역(추가료 동의 시 배송)
    quick_region_names = db.Column(db.Text, nullable=True)  # JSON: ["송도동","선린동"] — 주소 문자열 포함 시 배송가능
    use_quick_region_only = db.Column(db.Boolean, default=False)  # 보관용
    quick_extra_fee = db.Column(db.Integer, default=10000)  # 퀵폴리곤 지역 추가 배송료 (원). 관리자 수정 가능
    quick_extra_message = db.Column(db.Text, nullable=True)  # 퀵 지역 안내 문구. 관리자 수정 가능
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class MemberGradeConfig(db.Model):
    """회원 등급 자동 부여 기준 (구매 누적 금액). key: min_amount_grade2~5 / value: 정수 문자열(원)"""
    __tablename__ = "member_grade_config"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(50), nullable=True)  # 정수 문자열 (원)


class PointConfig(db.Model):
    """포인트 정책. key: accumulation_rate(1=0.1%), min_order_to_use, max_points_per_order / value: 정수 문자열"""
    __tablename__ = "point_config"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(50), nullable=True)


class PointLog(db.Model):
    """포인트 적립/사용 내역 (양수=적립, 음수=사용). 배송완료 적립 시 order_item_id로 중복 방지."""
    __tablename__ = "point_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # + 적립, - 사용
    order_id = db.Column(db.Integer, nullable=True)  # 주문 연계 시
    order_item_id = db.Column(db.Integer, nullable=True)  # 배송완료 적립 시 OrderItem.id (중복 적립 방지)
    memo = db.Column(db.String(200), nullable=True)  # 적립/사용/관리자 조정 등
    created_at = db.Column(db.DateTime, default=datetime.now)
    adjusted_by = db.Column(db.Integer, nullable=True)  # 관리자 조정 시 수정자 User.id


def send_message(user_id, title, body, msg_type='custom', related_order_id=None):
    """회원에게 메시지 1건 저장 (자동 발송·관리자 발송 공통). 푸시 알림도 발송 시도."""
    try:
        m = UserMessage(user_id=user_id, title=title, body=body or '', msg_type=msg_type or 'custom', related_order_id=related_order_id)
        db.session.add(m)
        db.session.flush()
        mid = m.id
        try:
            send_push_for_user(user_id, title, (body or '')[:200], url='/mypage/messages')
        except Exception:
            pass
        return mid
    except Exception:
        return None


def send_push_for_user(user_id, title, body, url='/mypage/messages'):
    """해당 사용자에게 등록된 모든 구독으로 Web Push 발송. 실패한 구독은 삭제."""
    vapid_private = os.getenv('VAPID_PRIVATE_KEY')
    if not vapid_private:
        return
    try:
        from pywebpush import webpush, WebPushException  # pyright: ignore[reportMissingImports]
    except ImportError:
        return
    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    vapid_claims = {"sub": os.getenv("VAPID_SUB_MAILTO", "mailto:admin@basket-uncle.local")}
    payload = json.dumps({"title": title or "알림", "body": body or "", "url": url or "/mypage/messages"}, ensure_ascii=False)
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims=vapid_claims,
            )
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                db.session.delete(sub)
        except Exception:
            pass
    # commit은 호출자(send_message 등)에서 수행


# 자동 발송용 기본 문구 (템플릿 없을 때)
_DEFAULT_MESSAGES = {
    'welcome': ('가입을 환영합니다', '바구니삼촌에 오신 것을 환영합니다. 신선한 농산물·식자재를 문 앞까지 배송해 드리겠습니다. 궁금한 점은 1666-8320으로 연락 주세요.'),
    'order_created': ('주문이 접수되었습니다', '주문번호 {order_id}로 결제가 완료되었습니다. 배송 진행 시 알려 드리겠습니다. 문의: 1666-8320'),
    'order_cancelled': ('주문이 취소되었습니다', '주문번호 {order_id}가 전액 취소·환불 처리되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다.'),
    'part_cancelled': ('일부 품목이 취소되었습니다', '주문번호 {order_id}에서 해당 품목이 취소·환불 처리되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다.'),
    'out_of_stock': ('품절로 인한 부분 취소 안내', '주문번호 {order_id}의 일부 상품이 품절로 취소되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다.'),
    'delivery_requested': ('배송 준비가 시작되었습니다', '주문번호 {order_id} 상품의 배송 준비가 시작되었습니다. 곧 배송해 드리겠습니다.'),
    'delivery_in_progress': ('배송 중입니다', '주문번호 {order_id} 상품이 배송 중입니다. 곧 도착할 예정입니다.'),
    'delivery_complete': ('배송이 완료되었습니다', '주문번호 {order_id} 상품이 배송 완료되었습니다. 이용해 주셔서 감사합니다.'),
    'delivery_delayed': ('배송이 지연되고 있습니다', '주문번호 {order_id} 상품의 배송이 일시 지연되고 있습니다. 빠른 배송을 위해 노력하겠습니다. 문의: 1666-8320'),
}


def get_template_content(msg_type, **replace):
    """msg_type에 해당하는 제목/내용 반환. replace에 order_id 등 치환할 값 전달 가능."""
    t = MessageTemplate.query.filter_by(msg_type=msg_type).first()
    if t and t.title:
        title, body = t.title, (t.body or '')
    else:
        title, body = _DEFAULT_MESSAGES.get(msg_type, ('알림', ''))
    if replace:
        for k, v in (replace or {}).items():
            body = body.replace('{' + k + '}', str(v))
    return title, body


def _point_in_polygon(px, py, polygon):
    """점 (px, py)이 polygon [[x,y],...] 안에 있는지 (ray casting)."""
    if not polygon or len(polygon) < 3:
        return False
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _geocode_address(address_str):
    """주소 문자열을 (lat, lng)로 변환. 실패 시 None."""
    if not address_str or not address_str.strip():
        return None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address_str.strip(), "format": "json", "limit": 1},
            headers={"User-Agent": "BasketUncle/1.0"},
            timeout=5,
        )
        if r.status_code != 200 or not r.json():
            return None
        data = r.json()[0]
        return (float(data["lat"]), float(data["lon"]))
    except Exception:
        return None


def _get_quick_region_list(zone):
    """DeliveryZone.quick_region_names JSON 파싱. 비어있거나 오류 시 빈 리스트."""
    if not zone or not getattr(zone, 'quick_region_names', None):
        return []
    try:
        names = json.loads(zone.quick_region_names)
        return [str(n).strip() for n in names if n and str(n).strip()]
    except Exception:
        return []


def _get_zone():
    """최신 배송구역 1건."""
    return DeliveryZone.query.order_by(DeliveryZone.updated_at.desc()).first()


def is_address_in_main_polygon(address_str):
    """주소가 일반 폴리곤 안에 있으면 True (배송가능지역, 추가료 없음)."""
    zone = _get_zone()
    addr = (address_str or "").strip()
    if not addr or not zone or not zone.polygon_json:
        return False
    try:
        polygon = json.loads(zone.polygon_json)
        if not polygon or len(polygon) < 3:
            return False
        coords = _geocode_address(addr)
        return bool(coords and _point_in_polygon(coords[0], coords[1], polygon))
    except Exception:
        return False


def is_address_in_quick_polygon(address_str):
    """주소가 퀵 폴리곤 안에 있으면 True (추가료 동의 시 퀵 배송)."""
    zone = _get_zone()
    addr = (address_str or "").strip()
    if not addr or not zone or not getattr(zone, 'quick_region_polygon_json', None):
        return False
    try:
        quick_poly = json.loads(zone.quick_region_polygon_json)
        if not quick_poly or len(quick_poly) < 3:
            return False
        coords = _geocode_address(addr)
        return bool(coords and _point_in_polygon(coords[0], coords[1], quick_poly))
    except Exception:
        return False


def get_delivery_zone_type(address_str):
    """주소 기준 구역 구분. 'normal'=일반폴리곤(배송가능), 'quick'=퀵폴리곤만(추가료 동의 시), 'unavailable'=배송불가."""
    addr = (address_str or "").strip()
    if not addr:
        return 'unavailable'
    if is_address_in_main_polygon(addr):
        return 'normal'
    if is_address_in_quick_polygon(addr):
        return 'quick'
    zone = _get_zone()
    quick = _get_quick_region_list(zone) if zone else []
    if quick and any(name in addr for name in quick):
        return 'normal'
    return 'unavailable'


def get_quick_extra_config():
    """퀵폴리곤 추가료(원)와 안내 문구. (fee, message)."""
    zone = _get_zone()
    fee = 10000
    msg = "해당 주소는 배송지역이 아닙니다. 배송료 추가 시 퀵으로 배송됩니다. 추가하시고 주문하시겠습니까?"
    if zone:
        fee = int(getattr(zone, 'quick_extra_fee', None) or 10000)
        if getattr(zone, 'quick_extra_message', None):
            msg = (zone.quick_extra_message or "").strip() or msg
    return fee, msg


def is_address_in_delivery_zone(address_str):
    """주소가 배송 가능한지 (일반 폴리곤 또는 퀵 폴리곤 또는 퀵 이름). 퀵만 있으면 퀵만, 그 외 전부 배송불가."""
    zone = _get_zone()
    addr = (address_str or "").strip()
    if not addr:
        return False
    if is_address_in_main_polygon(addr):
        return True
    if is_address_in_quick_polygon(addr):
        return True
    quick = _get_quick_region_list(zone) if zone else []
    if quick:
        return any(name in addr for name in quick)
    if zone and zone.polygon_json:
        try:
            polygon = json.loads(zone.polygon_json)
            if polygon and len(polygon) >= 3:
                coords = _geocode_address(addr)
                if coords:
                    return _point_in_polygon(coords[0], coords[1], polygon)
        except Exception:
            pass
    return False


def _get_user_total_paid(user_id):
    """회원 등급 산정용 누적 구매금액: 배송완료된 품목 금액만 인정 (취소·환불 주문 제외)."""
    from sqlalchemy import func
    total = db.session.query(
        func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0)
    ).join(Order, OrderItem.order_id == Order.id).filter(
        Order.user_id == user_id,
        Order.status.notin_(['취소', '환불']),
        OrderItem.cancelled == False,
        OrderItem.item_status == '배송완료'
    ).scalar()
    return int(total) if total is not None else 0


def _get_member_grade_config():
    """자동 등급 기준 금액 반환. (min_grade2, min_grade3, min_grade4, min_grade5) 원 단위."""
    def get_val(k, default=0):
        row = MemberGradeConfig.query.filter_by(key=k).first()
        if not row or not row.value:
            return default
        try:
            return int(row.value)
        except (ValueError, TypeError):
            return default
    return (
        get_val('min_amount_grade2', 100000),
        get_val('min_amount_grade3', 500000),
        get_val('min_amount_grade4', 1000000),
        get_val('min_amount_grade5', 2000000),
    )


def recompute_member_grade_for_user(user):
    """구매 누적액 기준으로 등급 계산. member_grade_overridden 이면 변경하지 않음. 반환: 변경 여부."""
    if getattr(user, 'member_grade_overridden', False):
        return False
    total = _get_user_total_paid(user.id)
    min2, min3, min4, min5 = _get_member_grade_config()
    new_grade = 1
    if total >= min5:
        new_grade = 5
    elif total >= min4:
        new_grade = 4
    elif total >= min3:
        new_grade = 3
    elif total >= min2:
        new_grade = 2
    if user.member_grade != new_grade:
        user.member_grade = new_grade
        return True
    return False


def categories_for_member_grade(member_grade):
    """해당 등급 회원에게 노출할 카테고리 쿼리. member_grade는 1~5, 비로그인은 1로 간주."""
    grade = 1 if member_grade is None else max(1, min(5, member_grade))
    return Category.query.filter(
        db.or_(Category.min_member_grade.is_(None), Category.min_member_grade <= grade)
    ).order_by(Category.order.asc(), Category.id.asc())


def _get_point_config():
    """포인트 정책 반환. accumulation_rate: 1=0.1%, min_order_to_use(원), max_points_per_order(원)"""
    def get_val(k, default=0):
        row = PointConfig.query.filter_by(key=k).first()
        if not row or not row.value:
            return default
        try:
            return int(row.value)
        except (ValueError, TypeError):
            return default
    return (
        get_val('accumulation_rate', 1),   # 1 = 0.1%
        get_val('min_order_to_use', 30000),
        get_val('max_points_per_order', 3000),
    )


def apply_order_points(user, order_total, points_used, order_id=None):
    """결제 완료 시: 포인트 사용분만 차감. 적립은 배송완료 시 정산 금액 기준으로 별도 지급."""
    user_obj = user if hasattr(user, 'points') else User.query.get(user)
    if not user_obj:
        return
    if points_used > 0:
        user_obj.points = (user_obj.points or 0) - points_used
        db.session.add(PointLog(user_id=user_obj.id, amount=-points_used, order_id=order_id, memo='주문 사용'))


def apply_points_on_delivery_complete(order_item):
    """품목이 배송완료로 바뀔 때, 해당 품목의 정산번호(sales_amount) 기준으로 포인트 적립. 1회만 지급."""
    if not order_item or getattr(order_item, 'cancelled', False):
        return
    order = Order.query.get(order_item.order_id) if order_item.order_id else None
    if not order or not order.user_id:
        return
    # 이미 이 품목에 대해 배송완료 적립한 적 있는지 확인
    if PointLog.query.filter_by(order_item_id=order_item.id).filter(PointLog.amount > 0).first():
        return
    st = Settlement.query.filter_by(order_item_id=order_item.id).first()
    if not st or not getattr(st, 'sales_amount', 0):
        return
    rate, _, _ = _get_point_config()
    earned = int(st.sales_amount * rate / 1000) if rate else 0
    if earned <= 0:
        return
    u = User.query.get(order.user_id)
    if not u:
        return
    u.points = (getattr(u, 'points', 0) or 0) + earned
    db.session.add(PointLog(user_id=u.id, amount=earned, order_id=order.id, order_item_id=order_item.id, memo='배송완료 적립'))


class Settlement(db.Model):
    """정산 전용 테이블 (고객 결제 시 품목별 고유 n넘버 기준)"""
    __tablename__ = "settlement"
    id = db.Column(db.Integer, primary_key=True)
    settlement_no = db.Column(db.String(32), unique=True, nullable=False)  # 품목별 고유 n넘버
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    order_item_id = db.Column(db.Integer, nullable=True)  # OrderItem.id
    sale_dt = db.Column(db.DateTime, nullable=False)  # 판매일시
    category = db.Column(db.String(50), nullable=False)  # 카테고리
    tax_exempt = db.Column(db.Boolean, default=False)  # 면세여부
    product_name = db.Column(db.String(200), nullable=False)  # 품목
    sales_amount = db.Column(db.Integer, default=0)  # 판매금액
    fee = db.Column(db.Integer, default=0)  # 수수료
    delivery_fee = db.Column(db.Integer, default=0)  # 배송관리비
    settlement_total = db.Column(db.Integer, default=0)  # 정산합계
    settlement_status = db.Column(db.String(20), default='입금대기')  # 입금대기, 입금완료, 취소, 보류
    settled_at = db.Column(db.DateTime, nullable=True)  # 입금일
    created_at = db.Column(db.DateTime, default=datetime.now)


class Review(db.Model):
    """사진 리뷰 모델 (판매자=카테고리별로 묶여 상품 상세에서 해당 판매자 후기 노출)"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, unique=True)
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(50))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)  # 판매자(카테고리) id
    content = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)

class UserConsent(db.Model):
    """이용 동의 내역 모델"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    email = db.Column(db.String(120))
    consent_privacy = db.Column(db.Boolean, default=True)
    consent_third_party = db.Column(db.Boolean, default=True)
    consent_purchase_agency = db.Column(db.Boolean, default=True)
    consent_terms = db.Column(db.Boolean, default=True)
    consent_marketing = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --------------------------------------------------------------------------------
# 3. 공통 유틸리티 함수
# --------------------------------------------------------------------------------

from PIL import Image, ImageOps

def save_uploaded_file(file):
    """핸드폰 사진 공백 제거(중앙 크롭) 및 WebP 변환"""
    if file and file.filename != '':
        # 파일명 설정 (.webp로 통일하여 용량 절감)
        new_filename = f"uncle_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.webp"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

        # 1. 이미지 열기
        img = Image.open(file)

        # 2. 핸드폰 사진 회전 방지 (EXIF 정보 바탕으로 방향 바로잡기)
        img = ImageOps.exif_transpose(img)

        # 3. 정사각형으로 중앙 크롭 (가로세로 800px)
        # ImageOps.fit은 이미지의 중심을 기준으로 비율에 맞춰 꽉 채워 자릅니다.
        size = (800, 800)
        img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)

        # 4. WebP로 저장 (용량 최적화)
        img.save(save_path, "WEBP", quality=85)
        
        return f"/static/uploads/{new_filename}"
    return None


def save_review_image(file):
    """리뷰용 이미지 최적화 후 저장 (최대 640px, WebP, uploads/reviews/)"""
    if not file or file.filename == '':
        return None
    review_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reviews')
    os.makedirs(review_folder, exist_ok=True)
    new_filename = f"review_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.webp"
    save_path = os.path.join(review_folder, new_filename)
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
        size = (640, 640)
        img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
        img.save(save_path, "WEBP", quality=82)
        return f"/static/uploads/reviews/{new_filename}"
    except Exception:
        return None

def save_board_image(file):
    """게시판(전국맛집요청 등) 이미지 최적화 저장"""
    if not file or file.filename == '':
        return None
    board_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'board')
    os.makedirs(board_folder, exist_ok=True)
    new_filename = f"board_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.webp"
    save_path = os.path.join(board_folder, new_filename)
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
        size = (800, 800)
        img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
        img.save(save_path, "WEBP", quality=85)
        return f"/static/uploads/board/{new_filename}"
    except Exception:
        return None


def check_admin_permission(category_name=None):
    """관리자 권한 체크"""
    if not current_user.is_authenticated: return False
    if current_user.is_admin: return True 
    if category_name:
        cat = Category.query.filter_by(name=category_name).first()
        if cat and cat.manager_email == current_user.email: return True
    return False

# --------------------------------------------------------------------------------
# 4. HTML 공통 레이아웃 (Header / Footer / Global Styles)
# --------------------------------------------------------------------------------

HEADER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="naver-site-verification" content="11c3f5256fbdca16c2d7008b7cf7d0feff9b056b" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="description" content="바구니 삼촌은 농산물·식자재를 중간 유통 없이 직접 연결하고 최소 배송비만 받는 신개념 물류·구매대행 서비스입니다.">
    <link rel="manifest" id="pwa-manifest-link" href="/manifest.json">
    <script>(function(){var p=window.location.pathname,l=document.getElementById('pwa-manifest-link');if(l){var app='consumer';if(p.indexOf('/admin')===0)app='admin';else if(p.indexOf('/logi')===0)app='driver';l.href='/manifest.json?app='+app;}})();</script>
    <meta name="theme-color" content="#0d9488">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <link rel="apple-touch-icon" href="/static/logo/side1.jpg">
    <link rel="apple-touch-icon" sizes="180x180" href="/static/logo/side1.jpg">
    <link rel="apple-touch-icon" sizes="152x152" href="/static/logo/side1.jpg">
    <link rel="apple-touch-icon" sizes="120x120" href="/static/logo/side1.jpg">
<title>바구니 삼촌 |  basam</title>

    <title>바구니삼촌 - 농산물·식자재 배송 신개념 6PL 생활서비스 basam </title>
    <script src="https://js.tosspayments.com/v1/payment"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;800;900&display=swap');
    
    :root {
        --color-bg: #fafaf9;
        --color-bg-elevated: #ffffff;
        --color-text: #1c1917;
        --color-text-muted: #57534e;
        --color-border: #e7e5e4;
        --color-accent: #0d9488;
        --color-accent-hover: #0f766e;
        --color-accent-light: rgba(13, 148, 136, 0.08);
        --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
        --shadow-md: 0 4px 12px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
        --shadow-lg: 0 12px 40px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04);
        --radius-sm: 10px;
        --radius-md: 14px;
        --radius-lg: 20px;
        --radius-xl: 28px;
        --ease: cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }
    
    body { 
        font-family: 'Noto Sans KR', sans-serif; 
        background-color: var(--color-bg);
        color: var(--color-text);
        -webkit-tap-highlight-color: transparent; 
        overflow-x: hidden; 
        line-height: 1.6;
        font-weight: 500;
        letter-spacing: -0.01em;
        text-align: left;
    }
    @media (max-width: 768px) {
        body { font-size: 15px; }
        .touch-target { min-height: 44px; min-width: 44px; }
        .mobile-px { padding-left: env(safe-area-inset-left); padding-right: env(safe-area-inset-right); }
        .mobile-pb { padding-bottom: env(safe-area-inset-bottom); }
    }
    
    .item-badge {
        display: inline-block;
        padding: 5px 12px;
        border-radius: var(--radius-sm);
        font-weight: 700;
        font-size: 0.7rem;
        line-height: 1.4;
        margin-bottom: 4px;
        white-space: nowrap;
        letter-spacing: 0.02em;
    }

    .sold-out { filter: grayscale(100%) blur(1px); opacity: 0.5; transition: 0.35s var(--ease); }
    .sold-out-badge { 
        position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: rgba(28, 25, 23, 0.92);
        color: white; padding: 14px 28px; 
        border-radius: var(--radius-md); font-weight: 800; z-index: 10; 
        border: 1px solid rgba(255,255,255,0.15);
        box-shadow: var(--shadow-lg);
        letter-spacing: -0.03em;
    }
    .no-scrollbar::-webkit-scrollbar { display: none; }
    
    .horizontal-scroll {
        display: flex; overflow-x: auto; scroll-snap-type: x mandatory; 
        gap: 20px; padding: 12px 24px 28px; 
        -webkit-overflow-scrolling: touch;
    }
    .horizontal-scroll > div { scroll-snap-align: start; flex-shrink: 0; }
    
    #sidebar {
        position: fixed; top: 0; left: -300px; width: 300px; height: 100%;
        background: var(--color-bg-elevated); z-index: 5001;
        transition: transform 0.4s var(--ease), box-shadow 0.4s var(--ease);
        box-shadow: 24px 0 60px rgba(0,0,0,0.08); overflow-y: auto;
        border-right: 1px solid var(--color-border);
    }
    #sidebar.open { left: 0; }
    #sidebar-overlay {
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(28, 25, 23, 0.4); z-index: 5000; display: none;
        backdrop-filter: blur(8px);
        transition: opacity 0.3s var(--ease);
    }
    #sidebar-overlay.show { display: block; }

    #toast {
        visibility: hidden; min-width: 80%; max-width: 360px;
        background: linear-gradient(180deg, #1c1917 0%, #292524 100%);
        color: #fff; text-align: center;
        border-radius: var(--radius-lg); padding: 18px 24px;
        position: fixed; z-index: 9999; left: 50%; bottom: 48px;
        transform: translateX(-50%) translateY(16px); font-size: 14px; font-weight: 700;
        transition: 0.35s var(--ease); opacity: 0;
        box-shadow: var(--shadow-lg);
        border: 1px solid rgba(255,255,255,0.06);
    }
    #toast.show { visibility: visible; opacity: 1; transform: translateX(-50%) translateY(0); }

    #term-modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(28, 25, 23, 0.6); z-index:6000; align-items:center; justify-content:center; padding:20px; backdrop-filter: blur(8px); }
    #term-modal-content { background:white; width:100%; max-width:520px; max-height:85vh; border-radius:var(--radius-xl); overflow:hidden; display:flex; flex-direction:column; box-shadow:0 32px 64px rgba(0,0,0,0.12), 0 0 0 1px var(--color-border); }
    #term-modal-body { overflow-y:auto; padding:2rem; font-size:0.95rem; line-height:1.75; color:var(--color-text-muted); }

    input[type="text"], input[type="email"], input[type="password"], input[type="number"], textarea, select {
        font-family: 'Noto Sans KR', sans-serif;
        transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease);
    }
    input:focus, textarea:focus, select:focus {
        outline: none;
        box-shadow: 0 0 0 3px var(--color-accent-light);
    }

    a { transition: color 0.2s var(--ease), opacity 0.2s var(--ease); }
    button { transition: transform 0.2s var(--ease), box-shadow 0.2s var(--ease), background-color 0.2s var(--ease); }

    @media (max-width: 640px) {
        .hero-title { font-size: 2rem !important; line-height: 1.2 !important; font-weight: 800; }
        .hero-desc { font-size: 0.95rem !important; opacity: 0.88; }
        .card-padding { padding: 1rem !important; }
    }
    /* PWA 스플래시: 앱 클릭 시 로딩 전 2초 표시 */
    #splash-screen {
        position: fixed; inset: 0; z-index: 99999; display: flex; flex-direction: column;
        align-items: center; justify-content: center; text-align: center;
        background: linear-gradient(165deg, #0d9488 0%, #0f766e 40%, #134e4a 100%);
        color: #fff; padding: 2rem; box-sizing: border-box;
        transition: opacity 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }
    #splash-screen.hide { opacity: 0; pointer-events: none; }
    #splash-screen .splash-logo { width: 88px; height: 88px; border-radius: 22px; object-fit: cover; box-shadow: 0 12px 40px rgba(0,0,0,0.25); margin-bottom: 1.5rem; }
    #splash-screen .splash-title { font-size: 1.6rem; font-weight: 900; letter-spacing: -0.04em; margin-bottom: 0.5rem; text-shadow: 0 2px 8px rgba(0,0,0,0.15); }
    #splash-screen .splash-desc { font-size: 0.85rem; font-weight: 600; opacity: 0.95; line-height: 1.5; max-width: 280px; }
    #splash-screen .splash-dot { width: 6px; height: 6px; background: rgba(255,255,255,0.6); border-radius: 50%; margin: 1.25rem auto 0; animation: splash-pulse 1s ease-in-out infinite; }
    @keyframes splash-pulse { 0%,100% { opacity: 0.5; transform: scale(1); } 50% { opacity: 1; transform: scale(1.2); } }
</style>
</head>
<body class="text-left antialiased">
    <!-- PWA 스플래시: 세션당 1회, 2초 후 페이드아웃 -->
    <div id="splash-screen">
        <img src="/static/logo/side1.jpg" alt="바구니삼촌" class="splash-logo" onerror="this.style.display='none'">
        <h1 class="splash-title">바구니삼촌</h1>
        <p class="splash-desc">중간 없이, 당신 곁으로.<br>농산물·식자재 신개념 6PL 배송</p>
        <div class="splash-dot"></div>
    </div>
    <script>
    (function(){
        if (sessionStorage.getItem('splash_done')) {
            var s = document.getElementById('splash-screen'); if (s) s.classList.add('hide');
            setTimeout(function(){ if (s) s.remove(); }, 600);
            return;
        }
        setTimeout(function(){
            var s = document.getElementById('splash-screen');
            if (s) { s.classList.add('hide'); sessionStorage.setItem('splash_done', '1'); }
            setTimeout(function(){ if (s) s.remove(); }, 600);
        }, 2000);
    })();
    </script>
    <div id="toast">메시지가 표시됩니다. 🧺</div>

    <div id="logout-warning-modal" class="fixed inset-0 z-[9999] hidden flex items-center justify-center p-4 bg-stone-900/50 backdrop-blur-md">
        <div class="bg-white w-full max-w-sm rounded-[28px] p-10 text-center shadow-[0_24px_48px_rgba(0,0,0,0.12),0_0_0_1px_rgba(0,0,0,0.06)]">
            <div class="w-16 h-16 bg-amber-50 text-amber-600 rounded-2xl flex items-center justify-center mx-auto mb-6 text-2xl">
                <i class="fas fa-clock animate-pulse"></i>
            </div>
            <h3 class="text-xl font-extrabold text-stone-800 mb-2 tracking-tight">자동 로그아웃 안내</h3>
            <p class="text-stone-500 font-semibold text-sm mb-8 leading-relaxed">
                장시간 활동이 없어 <span id="logout-timer" class="text-amber-600 font-extrabold">60</span>초 후<br>로그아웃 됩니다. 로그인 상태를 유지할까요?
            </p>
            <div class="flex gap-3">
                <button onclick="location.href='/logout'" class="flex-1 py-4 bg-stone-100 text-stone-500 rounded-2xl font-bold text-sm hover:bg-stone-200 transition">로그아웃</button>
                <button onclick="extendSession()" class="flex-1 py-4 bg-teal-600 text-white rounded-2xl font-bold text-sm shadow-lg shadow-teal-600/25 hover:bg-teal-700 hover:shadow-teal-600/30 transition">로그인 유지</button>
            </div>
        </div>
    </div>
    
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
    <div id="sidebar" class="p-8 flex flex-col h-full">
        <div class="flex justify-between items-center mb-10">
            <div class="flex items-center gap-3">
                <img src="/static/logo/side1.jpg" class="h-7 w-auto rounded-lg shadow-sm" onerror="this.style.display='none'">
                <span class="text-sm font-extrabold text-teal-600 uppercase tracking-wider">Categories</span>
            </div>
            <button onclick="toggleSidebar()" class="w-10 h-10 rounded-xl text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center transition"><i class="fas fa-times"></i></button>
        </div>
        <nav class="space-y-1 flex-1">
            <a href="/" class="group flex items-center gap-3 py-3 px-4 rounded-xl text-stone-700 hover:bg-teal-50 hover:text-teal-700 font-semibold transition">
                <i class="fas fa-th-large text-stone-300 group-hover:text-teal-500 w-5 text-center"></i> 전체상품보기
            </a>
            <div class="h-px bg-stone-100 my-4"></div>
            {% for c in nav_categories %}
            <a href="/category/{{ c.name }}" class="flex items-center justify-between py-3 px-4 rounded-xl text-stone-600 hover:bg-stone-50 hover:text-teal-600 transition font-medium">
                <span>{{ c.name }}</span>
                <i class="fas fa-chevron-right text-[10px] text-stone-300"></i>
            </a>
            {% endfor %}
            <div class="h-px bg-stone-100 my-4"></div>
            <a href="/about" class="block py-3 px-4 rounded-xl text-sky-600 hover:bg-sky-50 font-semibold transition">바구니삼촌이란?</a>
            <a href="/guide" class="block py-3 px-4 rounded-xl text-stone-600 hover:bg-stone-50 hover:text-teal-600 font-medium transition">이용안내</a>
            <a href="/board/restaurant-request" class="block py-3 px-4 rounded-xl text-stone-600 hover:bg-stone-50 hover:text-teal-600 font-medium transition">전국맛집요청</a>
            <a href="/board/partnership" class="block py-3 px-4 rounded-xl text-stone-600 hover:bg-stone-50 hover:text-teal-600 font-medium transition">제휴문의</a>
        </nav>
    </div>
    <nav class="bg-white/98 backdrop-blur-xl border-b border-stone-100 sticky top-0 z-50 shadow-[0_1px_0_0_rgba(0,0,0,0.03)] mobile-px">
        <div class="max-w-7xl mx-auto px-4 md:px-6">
            <div class="flex justify-between h-14 md:h-[72px] items-center">
                <div class="flex items-center gap-2 md:gap-6">
                    <button type="button" onclick="toggleSidebar()" class="touch-target w-10 h-10 min-w-[44px] min-h-[44px] rounded-xl text-stone-500 hover:text-teal-600 hover:bg-stone-50 flex items-center justify-center transition">
                        <i class="fas fa-bars text-lg"></i>
                    </button>
                    <a href="/" id="admin-shortcut-header" class="flex items-center gap-2.5 group">
                        <img src="/static/logo/side1.jpg" alt="바구니삼촌" class="h-8 md:h-9 w-auto rounded-lg shadow-sm group-hover:opacity-90 transition" onerror="this.style.display='none'">
                        <span class="font-extrabold text-teal-600 text-base md:text-lg tracking-tight group-hover:text-teal-700 transition">바구니삼촌</span>
                    </a>
                </div>

                <div class="flex items-center gap-2 md:gap-4 flex-1 justify-end max-w-md">
                    {% if current_user.is_authenticated %}
                        <a href="/mypage/points" class="touch-target hidden md:flex items-center gap-1.5 text-stone-500 hover:text-teal-600 text-xs font-bold py-2.5 px-3 rounded-xl hover:bg-stone-50 transition">
                            <i class="fas fa-coins text-sm"></i> 포인트 내역
                        </a>
                    {% endif %}
                    <button type="button" id="header-search-toggle" class="md:hidden w-10 h-10 rounded-xl text-stone-500 hover:bg-stone-50 flex items-center justify-center" aria-label="검색">
                        <i class="fas fa-search"></i>
                    </button>

                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="touch-target relative w-10 h-10 md:w-11 md:h-11 min-w-[44px] min-h-[44px] rounded-xl text-stone-500 hover:text-teal-600 hover:bg-stone-50 flex items-center justify-center transition">
                            <i class="fas fa-shopping-cart text-lg md:text-xl"></i>
                            <span id="cart-count-badge" class="absolute top-0.5 right-0.5 min-w-[18px] h-[18px] bg-rose-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-white shadow-sm">{{ cart_count }}</span>
                        </a>
                        <a href="/mypage" class="touch-target relative text-stone-600 font-bold bg-stone-100 px-4 py-2.5 min-h-[44px] rounded-xl text-xs hover:bg-stone-200 transition flex items-center">MY{% if unread_message_count and unread_message_count > 0 %}<span class="ml-1 min-w-[16px] h-[16px] bg-teal-500 text-white text-[9px] font-black rounded-full flex items-center justify-center border-2 border-white">{{ unread_message_count }}</span>{% endif %}</a>
                    {% else %}
                        <a href="/login" class="touch-target text-stone-600 font-bold text-sm hover:text-teal-600 transition py-2 min-h-[44px] flex items-center">로그인</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>
    <div id="scroll-search-bar" class="fixed left-0 right-0 z-40 bg-white/98 backdrop-blur-xl border-b border-stone-100 shadow-sm transition-transform duration-300 -translate-y-full" style="top: 3.5rem;">
        <div class="max-w-7xl mx-auto px-4 md:px-6 py-3">
            <form action="/search" method="GET" class="relative mb-3">
                <input name="q" placeholder="상품 검색" class="w-full bg-stone-50 py-2.5 pl-5 pr-12 rounded-xl text-sm font-medium text-stone-800 placeholder-stone-400 border border-stone-100 focus:border-teal-200 focus:ring-2 focus:ring-teal-500/10 outline-none transition">
                <button type="submit" class="absolute right-3 top-1/2 -translate-y-1/2 w-8 h-8 rounded-lg text-stone-400 hover:text-teal-600 hover:bg-teal-50 flex items-center justify-center transition"><i class="fas fa-search text-sm"></i></button>
            </form>
            <div class="flex items-center gap-3">
                <div class="horizontal-scroll no-scrollbar flex gap-2 flex-1 min-w-0">
                    {% for c in nav_categories %}
                    <a href="/category/{{ c.name }}" class="shrink-0 px-4 py-2 rounded-xl bg-stone-100 text-stone-600 text-xs font-bold hover:bg-teal-100 hover:text-teal-700 transition">{{ c.name }}</a>
                    {% endfor %}
                </div>
                <button type="button" id="scroll-search-bar-close" class="shrink-0 px-4 py-2 rounded-xl text-stone-500 hover:text-stone-700 hover:bg-stone-100 flex items-center justify-center transition text-xs font-bold" aria-label="닫기">닫기</button>
            </div>
        </div>
    </div>
    <button type="button" id="scroll-search-bar-open" class="fixed z-30 hidden right-4 rounded-full bg-teal-600 text-white shadow-lg py-2 px-3 text-xs font-bold hover:bg-teal-700 transition flex items-center gap-1.5" style="top: 4rem;" aria-label="검색 열기"><i class="fas fa-search"></i> 검색</button>
    <div id="mobile-search-nav" class="hidden md:hidden pb-4 border-b border-stone-100 mobile-px">
        <div class="max-w-7xl mx-auto px-4 pt-2 pb-3">
            <form action="/search" method="GET" class="relative">
                <input name="q" placeholder="상품 검색" class="w-full bg-stone-50 py-3.5 px-5 rounded-xl text-base font-medium border border-stone-100 focus:border-teal-200 focus:ring-2 focus:ring-teal-500/10 outline-none transition">
                <button type="submit" class="absolute right-4 top-1/2 -translate-y-1/2 text-teal-600"><i class="fas fa-search"></i></button>
            </form>
        </div>
    </div>
    <main class="min-h-screen">
    <script>
    (function(){
        var toggle = document.getElementById('header-search-toggle');
        var mobileNav = document.getElementById('mobile-search-nav');
        if (toggle && mobileNav) toggle.addEventListener('click', function() { mobileNav.classList.toggle('hidden'); });
        var scrollBar = document.getElementById('scroll-search-bar');
        var openBtn = document.getElementById('scroll-search-bar-open');
        var closeBtn = document.getElementById('scroll-search-bar-close');
        var STORAGE_KEY = 'scroll_search_bar_closed';
        function isUserClosed() { return sessionStorage.getItem(STORAGE_KEY) === '1'; }
        function setUserClosed(v) { if (v) sessionStorage.setItem(STORAGE_KEY, '1'); else sessionStorage.removeItem(STORAGE_KEY); }
        function showBar() { if (scrollBar) { scrollBar.classList.remove('-translate-y-full'); scrollBar.classList.add('translate-y-0'); } if (openBtn) openBtn.classList.add('hidden'); setUserClosed(false); }
        function hideBar() { if (scrollBar) { scrollBar.classList.add('-translate-y-full'); scrollBar.classList.remove('translate-y-0'); } setUserClosed(true); }
        function updateOpenBtn(y) {
            if (!openBtn) return;
            if (y > 80 && isUserClosed()) { openBtn.classList.remove('hidden'); openBtn.classList.add('flex'); }
            else { openBtn.classList.add('hidden'); openBtn.classList.remove('flex'); }
        }
        if (closeBtn && scrollBar) closeBtn.addEventListener('click', function() { hideBar(); updateOpenBtn(window.scrollY || 0); });
        if (openBtn) openBtn.addEventListener('click', function() { showBar(); });
        if (scrollBar) {
            var ticking = false;
            function updateBar() {
                var y = window.scrollY || document.documentElement.scrollTop;
                if (isUserClosed()) { updateOpenBtn(y); ticking = false; return; }
                if (y > 100) { scrollBar.classList.remove('-translate-y-full'); scrollBar.classList.add('translate-y-0'); if (openBtn) openBtn.classList.add('hidden'); }
                else { scrollBar.classList.add('-translate-y-full'); scrollBar.classList.remove('translate-y-0'); updateOpenBtn(y); }
                ticking = false;
            }
            window.addEventListener('scroll', function() {
                if (!ticking) { requestAnimationFrame(updateBar); ticking = true; }
            }, { passive: true });
            updateOpenBtn(window.scrollY || 0);
        }
    })();
    // Flask에서 설정한 세션 타임아웃 시간 (초 단위, 예: 30분 = 1800초)
    const SESSION_TIMEOUT = 30 * 60; 
    const WARNING_TIME = 60; // 로그아웃 60초 전에 경고창 표시
    
    let warningTimer;
    let countdownInterval;

    function startLogoutTimer() {
        // 1. 기존 타이머가 있다면 제거
        clearTimeout(warningTimer);
        
        // 2. 경고창을 띄울 시간 계산 (전체 시간 - 60초)
        warningTimer = setTimeout(() => {
            showLogoutWarning();
        }, (SESSION_TIMEOUT - WARNING_TIME) * 1000);
    }

    function showLogoutWarning() {
        const modal = document.getElementById('logout-warning-modal');
        const timerDisplay = document.getElementById('logout-timer');
        let timeLeft = WARNING_TIME;

        modal.classList.remove('hidden');
        
        // 1초마다 숫자를 깎는 카운트다운 시작
        countdownInterval = setInterval(() => {
            timeLeft -= 1;
            timerDisplay.innerText = timeLeft;
            
            if (timeLeft <= 0) {
                clearInterval(countdownInterval);
                location.href = '/logout'; // 0초가 되면 로그아웃 실행
            }
        }, 1000);
    }

    function extendSession() {
        // 서버에 가벼운 요청을 보내 세션을 연장시킵니다 (가장 간단한 방법)
        fetch('/').then(() => {
            // 경고창 숨기기 및 타이머 리셋
            document.getElementById('logout-warning-modal').classList.add('hidden');
            clearInterval(countdownInterval);
            startLogoutTimer(); 
            showToast("로그인 시간이 연장되었습니다. 😊");
        });
    }

    // 사용자가 로그인한 상태일 때만 타이머 작동
    {% if current_user.is_authenticated %}
    startLogoutTimer();
    {% endif %}
</script>
"""

FOOTER_HTML = """
    <!-- 새 메시지 알림 바 (로그인 사용자, 미읽음 있을 때만 상단에서 내려옴) -->
    <div id="message-notice-bar" class="fixed top-0 left-0 right-0 z-[62] bg-teal-600 text-white shadow-lg transform -translate-y-full transition-transform duration-300 flex items-center justify-center gap-3 px-4 py-3 text-sm font-bold" style="display: none;">
        <span id="message-notice-text">새 메시지가 있습니다.</span>
        <a href="/mypage/messages" class="bg-white text-teal-600 px-4 py-1.5 rounded-lg font-black hover:bg-teal-50">확인</a>
        <button type="button" id="message-notice-close" class="text-white/90 hover:text-white text-xl leading-none" aria-label="닫기">×</button>
    </div>
    <script>
    (function(){
        if (!{{ 'true' if current_user.is_authenticated else 'false' }}) return;
        var bar = document.getElementById('message-notice-bar');
        if (!bar) return;
        var key = 'message_notice_dismissed_at';
        var dismissMinutes = 10;
        function shouldShow() {
            var t = sessionStorage.getItem(key);
            if (!t) return true;
            return (Date.now() - parseInt(t, 10)) > dismissMinutes * 60 * 1000;
        }
        function dismiss() { sessionStorage.setItem(key, String(Date.now())); bar.style.display = 'none'; bar.classList.add('-translate-y-full'); }
        function showBar(count) {
            if (count <= 0 || !shouldShow()) return;
            var textEl = document.getElementById('message-notice-text');
            if (textEl) textEl.textContent = count === 1 ? '새 메시지가 1건 있습니다.' : '새 메시지가 ' + count + '건 있습니다.';
            bar.style.display = 'flex';
            bar.classList.remove('-translate-y-full');
        }
        fetch('/api/messages/unread_count', { credentials: 'same-origin' }).then(function(r) {
            if (r.status !== 200) return;
            return r.json();
        }).then(function(data) {
            if (data && data.count > 0) showBar(data.count);
        }).catch(function(){});
        var closeBtn = document.getElementById('message-notice-close');
        if (closeBtn) closeBtn.addEventListener('click', dismiss);
        setInterval(function() {
            if (!shouldShow()) return;
            fetch('/api/messages/unread_count', { credentials: 'same-origin' }).then(function(r) { if (r.status !== 200) return; return r.json(); }).then(function(data) { if (data && data.count > 0) showBar(data.count); }).catch(function(){});
        }, 60000);
    })();
    </script>

    </main>

    <footer class="bg-stone-900 text-stone-400 py-14 md:py-24 mt-24 border-t border-stone-700/50">
        <div class="max-w-7xl mx-auto px-6">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-10 pb-12 mb-12 border-b border-stone-700/50">
                <div class="text-left">
                    <p id="admin-shortcut-footer" class="text-teal-400 font-extrabold text-2xl tracking-tight mb-2 cursor-pointer select-none">바구니삼촌</p>
                    <p id="admin-shortcut-tagline" class="text-xs text-amber-400/90 font-semibold tracking-wide cursor-pointer select-none">인천 연수구 송도동 전용 구매대행 및 배송 서비스</p>
                </div>
                <div class="flex flex-col md:items-end gap-4 w-full md:w-auto">
                    <p class="text-stone-300 font-bold text-sm tracking-wide">Customer Center</p>
                    <div class="flex flex-wrap md:justify-end gap-3 items-center">
                        <a href="http://pf.kakao.com/_AIuxkn" target="_blank" class="bg-[#FEE500] text-stone-900 px-5 py-3 rounded-xl font-bold text-xs flex items-center gap-2 shadow-lg hover:shadow-xl hover:scale-[1.02] transition">
                            <i class="fas fa-comment"></i> 카카오톡 문의
                        </a>
                        <span class="text-lg font-extrabold text-white">1666-8320</span>
                    </div>
                    <p class="text-[11px] text-stone-500 font-medium">평일 09:00 ~ 18:00 (점심 12:00 ~ 13:00)</p>
                    <div class="flex flex-col sm:flex-row sm:items-center gap-3 pt-2 border-t border-stone-700/50 mt-2 w-full md:w-auto">
                        <button type="button" id="pwa-footer-add-home-btn" class="touch-target inline-flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-500 text-white px-4 py-2.5 rounded-xl font-bold text-xs transition shrink-0">
                            <i class="fas fa-plus-square"></i> 홈화면에 바로가기 추가
                        </button>
                        <p class="text-[11px] text-stone-500 font-medium max-w-xs">
                            <span class="text-stone-400 font-semibold">설치방법</span> Android: Chrome <strong>메뉴(⋮)</strong> → 홈 화면에 추가 / iOS: Safari <strong>공유</strong> → 홈 화면에 추가
                        </p>
                    </div>
                </div>
            </div>

            <div class="flex flex-wrap gap-x-8 gap-y-2 mb-10 text-xs font-semibold">
                <a href="javascript:void(0)" onclick="openUncleModal('terms')" class="text-stone-500 hover:text-white transition">이용약관</a>
                <a href="javascript:void(0)" onclick="openUncleModal('privacy')" class="text-stone-500 hover:text-white transition">개인정보처리방침</a>
                <a href="javascript:void(0)" onclick="openUncleModal('agency')" class="text-stone-500 hover:text-white transition">이용 안내</a>
                <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="text-stone-500 hover:text-white transition">전자상거래 유의사항</a>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-10 items-end">
                <div class="text-left">
                    <button type="button" id="footer-business-info-toggle" class="touch-target text-stone-500 hover:text-white text-xs font-semibold transition flex items-center gap-1.5">
                        <i class="fas fa-building opacity-70"></i> 사업자 정보보기
                    </button>
                    <div id="footer-business-info-body" class="hidden mt-3 text-[11px] md:text-xs space-y-2 text-stone-500 leading-relaxed font-medium text-left">
                        <p>상호: 바구니삼촌 | 대표: 금창권 | 개인정보관리책임자: 금창권</p>
                        <p>주소: 인천광역시 연수구 하모니로158, D동 317호 (송도동, 송도 타임스페이스)</p>
                        <p>사업자등록번호: 472-93-02262 | 통신판매업신고: 제 2025-인천연수-3388호</p>
                        <p>이메일: basamsongdo@gmail.com</p>
                        <p class="pt-4 text-stone-600 font-bold uppercase tracking-widest">© 2026 BASAM. All Rights Reserved.</p>
                    </div>
                </div>
                <div class="hidden md:flex justify-end">
                    <span class="w-14 h-14 rounded-2xl bg-stone-800 flex items-center justify-center text-stone-600">
                        <i class="fas fa-truck-fast text-2xl"></i>
                    </span>
                </div>
            </div>
        </div>
    </footer>
    <script>
    (function(){
        var ADMIN_CLICKS = 5, RESET_MS = 2000, SINGLE_CLICK_MS = 350, count = 0, t, tSingle;
        function goAdmin() { location.href = '/admin'; }
        function goHome() { location.href = '/'; }
        function reset() { count = 0; }
        function onClick(e) {
            if (e.currentTarget.id === 'admin-shortcut-header') {
                e.preventDefault();
                count++;
                clearTimeout(t);
                clearTimeout(tSingle);
                if (count >= ADMIN_CLICKS) goAdmin();
                else {
                    t = setTimeout(reset, RESET_MS);
                    if (count === 1) tSingle = setTimeout(function(){ goHome(); reset(); }, SINGLE_CLICK_MS);
                }
                return;
            }
            count++;
            clearTimeout(t);
            if (count >= ADMIN_CLICKS) goAdmin();
            else t = setTimeout(reset, RESET_MS);
        }
        ['admin-shortcut-header','admin-shortcut-footer','admin-shortcut-tagline'].forEach(function(id){
            var el = document.getElementById(id);
            if (el) el.addEventListener('click', onClick);
        });
    })();
    (function(){
        var btn = document.getElementById('footer-business-info-toggle');
        var body = document.getElementById('footer-business-info-body');
        if (!btn || !body) return;
        btn.addEventListener('click', function() {
            var isHidden = body.classList.contains('hidden');
            body.classList.toggle('hidden');
            btn.innerHTML = isHidden ? '<i class="fas fa-chevron-up opacity-70"></i> 사업자 정보 접기' : '<i class="fas fa-building opacity-70"></i> 사업자 정보보기';
        });
    })();
    </script>

    <!-- 모바일 전용: 홈 화면에 추가(앱 설치). 홈화면 설치하기 / 자세히보기 -->
    <div id="pwa-add-home-banner" class="fixed bottom-0 left-0 right-0 z-40 hidden bg-teal-700 text-white shadow-[0_-4px_20px_rgba(0,0,0,0.15)]" style="padding-bottom: max(0.25rem, env(safe-area-inset-bottom));">
        <div class="max-w-lg mx-auto px-4 py-4 flex items-start gap-3">
            <div class="flex-1 min-w-0">
                <div class="flex gap-2">
                    <button type="button" id="pwa-add-home-btn" class="flex-1 py-3.5 px-4 rounded-xl bg-white text-teal-700 font-black text-sm shadow-lg hover:bg-teal-50 transition active:scale-[0.98] flex items-center justify-center gap-2">
                        <i class="fas fa-download text-base"></i> 홈화면 설치하기
                    </button>
                    <button type="button" id="pwa-detail-guide-btn" class="py-3.5 px-4 rounded-xl bg-teal-600 text-white font-black text-sm border border-teal-500 hover:bg-teal-500 transition active:scale-[0.98] whitespace-nowrap">자세히보기</button>
                </div>
                <p class="font-black text-sm mt-3 mb-0.5" id="pwa-banner-title">📱 상품·배송 알림, 한 번에 받으세요</p>
                <p class="text-[11px] text-teal-200 font-bold mb-1" id="pwa-banner-desc">홈 화면에 앱을 설치하면 신상품·주문·배송 정보를 놓치지 않아요</p>
                <div id="pwa-explain-after" class="hidden mt-2 space-y-2">
                    <p id="pwa-add-home-text-android" class="text-xs text-teal-100 leading-relaxed hidden">Chrome <strong>메뉴(⋮)</strong> → <strong>홈 화면에 추가</strong> 또는 <strong>앱 설치</strong></p>
                    <p id="pwa-add-home-text-ios" class="text-xs text-teal-100 leading-relaxed hidden">아이폰: Safari <strong>하단 [공유]</strong> → <strong>홈 화면에 추가</strong></p>
                    <button type="button" id="pwa-install-guide-btn" class="text-xs font-black text-teal-200 underline hover:text-white transition block">자세한 설치방법</button>
                    <div id="pwa-permission-block" class="pt-2 mt-2 border-t border-teal-600/50">
                        <p class="text-xs text-teal-100 font-bold mb-2">🔔 주문·배송 알림을 받으시려면 알림 권한을 허용해 주세요.</p>
                        <button type="button" id="pwa-permission-btn" class="w-full py-2.5 px-3 rounded-xl bg-teal-500 text-white text-xs font-black hover:bg-teal-600 transition">알림 허용하기</button>
                        <span id="pwa-permission-status" class="block mt-1.5 text-[10px] text-teal-200"></span>
                    </div>
                </div>
            </div>
            <button type="button" id="pwa-add-home-close" class="flex-shrink-0 w-8 h-8 rounded-full bg-white/20 hover:bg-white/30 flex items-center justify-center text-white text-lg leading-none" aria-label="닫기">×</button>
        </div>
    </div>

    <!-- 설치방법 상세 모달 (Android / 아이폰 나눠서 설명) -->
    <div id="pwa-install-guide-modal" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/50 p-4" style="padding-bottom: env(safe-area-inset-bottom);">
        <div class="bg-white rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div class="flex justify-between items-center px-5 py-4 border-b border-gray-100">
                <h3 class="text-lg font-black text-gray-800">홈 화면에 추가하는 방법</h3>
                <button type="button" id="pwa-install-guide-close" class="w-10 h-10 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center text-xl leading-none">×</button>
            </div>
            <div class="p-5 overflow-y-auto flex-1 text-left text-sm">
                <div class="mb-6">
                    <h4 class="font-black text-teal-700 text-base mb-3 flex items-center gap-2"><span class="w-6 h-6 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs">A</span> Android (크롬)</h4>
                    <ol class="space-y-2 text-gray-700 font-medium list-decimal list-inside">
                        <li>화면 <strong>오른쪽 위</strong>에 있는 <strong>점 세 개(⋮)</strong> 메뉴를 누릅니다.</li>
                        <li>메뉴 목록에서 <strong>「홈 화면에 추가」</strong> 또는 <strong>「앱 설치」</strong>를 찾아 누릅니다.</li>
                        <li>나오는 창에서 <strong>「추가」</strong> 또는 <strong>「설치」</strong>를 누르면 홈 화면에 아이콘이 생깁니다.</li>
                        <li>이후 홈 화면의 <strong>바구니삼촌</strong> 아이콘을 누르면 앱처럼 바로 이용할 수 있습니다.</li>
                    </ol>
                </div>
                <div>
                    <h4 class="font-black text-gray-800 text-base mb-3 flex items-center gap-2"><span class="w-6 h-6 rounded-full bg-gray-200 text-gray-700 flex items-center justify-center text-xs">i</span> 아이폰·아이패드 (Safari)</h4>
                    <ol class="space-y-2 text-gray-700 font-medium list-decimal list-inside">
                        <li><strong>Safari</strong> 브라우저로 이 페이지를 연 상태에서, 화면 <strong>맨 아래 가운데</strong> 있는 <strong>「공유」</strong> 버튼(□ 위에 ↑ 모양)을 누릅니다.</li>
                        <li>공유 메뉴가 위로 올라오면, 아래로 조금 스크롤합니다.</li>
                        <li><strong>「홈 화면에 추가」</strong>를 누릅니다. (아이콘은 더하기(+)가 있는 사각형 모양입니다.)</li>
                        <li>이름을 확인한 뒤 오른쪽 위 <strong>「추가」</strong>를 누르면 홈 화면에 바로가기가 생깁니다.</li>
                        <li>이후 홈 화면의 <strong>바구니삼촌</strong> 아이콘을 누르면 앱처럼 이용할 수 있습니다.</li>
                    </ol>
                    <p class="mt-3 text-xs text-gray-500">※ 반드시 Safari에서 진행해 주세요. Chrome 등 다른 앱에서는 「홈 화면에 추가」가 없을 수 있습니다.</p>
                </div>
            </div>
        </div>
    </div>
    <script>
    (function() {
        var banner = document.getElementById('pwa-add-home-banner');
        var closeBtn = document.getElementById('pwa-add-home-close');
        var guideModal = document.getElementById('pwa-install-guide-modal');
        var guideClose = document.getElementById('pwa-install-guide-close');
        if (!banner || !closeBtn) return;
        if (sessionStorage.getItem('pwa_add_home_dismissed') === '1') { banner.remove(); return; }
        var isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.matchMedia('(display-mode: fullscreen)').matches || window.matchMedia('(display-mode: minimal-ui)').matches || (navigator.standalone === true);
        if (isStandalone) { banner.remove(); return; }
        var ua = navigator.userAgent || '';
        var isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        var isAndroid = /Android/.test(ua);
        var isMobile = /Mobi|Android/i.test(ua) || window.innerWidth < 768;
        if (!isMobile) { banner.remove(); return; }
        var textAndroid = document.getElementById('pwa-add-home-text-android');
        var textIos = document.getElementById('pwa-add-home-text-ios');
        var explainAfter = document.getElementById('pwa-explain-after');
        if (isIOS && textIos) textIos.classList.remove('hidden'); else if (textAndroid) textAndroid.classList.remove('hidden');
        if (isIOS && textAndroid) textAndroid.classList.add('hidden');
        if (!isIOS && textIos) textIos.classList.add('hidden');
        banner.classList.remove('hidden');
        banner.classList.add('flex');
        closeBtn.addEventListener('click', function() { sessionStorage.setItem('pwa_add_home_dismissed', '1'); banner.remove(); });
        var p=window.location.pathname; var title=document.getElementById('pwa-banner-title'); var desc=document.getElementById('pwa-banner-desc');
        if(p.indexOf('/admin')===0&&title&&desc){ title.textContent='📱 바삼관리자, 홈에서 바로 열기'; desc.textContent='홈 화면에 앱을 설치하면 바삼관리자로 바로 열 수 있어요'; }
        function openInstallGuideModal() {
            if (guideModal) { guideModal.classList.remove('hidden'); guideModal.classList.add('flex'); document.body.style.overflow = 'hidden'; }
        }
        if (guideClose && guideModal) {
            guideClose.addEventListener('click', function() { guideModal.classList.add('hidden'); guideModal.classList.remove('flex'); document.body.style.overflow = ''; });
            guideModal.addEventListener('click', function(e) { if (e.target === guideModal) { guideModal.classList.add('hidden'); guideModal.classList.remove('flex'); document.body.style.overflow = ''; } });
        }
        var detailGuideBtn = document.getElementById('pwa-detail-guide-btn');
        if (detailGuideBtn) detailGuideBtn.addEventListener('click', openInstallGuideModal);
        if (typeof window.deferredPrompt === 'undefined') window.deferredPrompt = null;
        if (!window._pwaPromptBound) { window._pwaPromptBound = true; window.addEventListener('beforeinstallprompt', function(e) { e.preventDefault(); window.deferredPrompt = e; }); }
        var addHomeBtn = document.getElementById('pwa-add-home-btn');
        if (addHomeBtn) {
            addHomeBtn.addEventListener('click', function() {
                if (window.deferredPrompt) {
                    window.deferredPrompt.prompt();
                    window.deferredPrompt.userChoice.then(function(r) {
                        if (r.outcome === 'accepted') {
                            window.deferredPrompt = null;
                            sessionStorage.setItem('pwa_add_home_dismissed', '1');
                            banner.remove();
                        } else if (explainAfter) {
                            explainAfter.classList.remove('hidden');
                        }
                    });
                } else {
                    if (explainAfter) explainAfter.classList.remove('hidden');
                }
            });
        }
        (function setupPermissionBtn() {
            var permBtn = document.getElementById('pwa-permission-btn');
            var permStatus = document.getElementById('pwa-permission-status');
            if (!permBtn) return;
            function setStatus(t) { if (permStatus) permStatus.textContent = t; }
            permBtn.addEventListener('click', function() {
                if (!('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) {
                    setStatus('Chrome·Safari 앱에서 직접 열어 주세요. 앱 내 브라우저에서는 지원되지 않습니다.'); return;
                }
                if (Notification.permission === 'denied') {
                    setStatus('알림이 차단되었습니다. 브라우저 설정에서 허용해 주세요.'); return;
                }
                if (Notification.permission === 'granted') {
                    doSubscribe(); return;
                }
                setStatus('권한 요청 중...');
                Notification.requestPermission().then(function(p) {
                    if (p === 'granted') { doSubscribe(); } else { setStatus('알림 권한을 허용해 주시면 주문·배송 알림을 받을 수 있어요.'); }
                });
                function doSubscribe() {
                    setStatus('등록 중...');
                    fetch('/api/push/vapid-public').then(function(r) { return r.json(); }).then(function(d) {
                        if (d.error || !d.publicKey) { setStatus('알림 기능이 설정되지 않았습니다.'); return; }
                        var key = d.publicKey.replace(/-/g, '+').replace(/_/g, '/');
                        var keyBytes = new Uint8Array(atob(key).split('').map(function(c) { return c.charCodeAt(0); }));
                        return (navigator.serviceWorker.controller ? Promise.resolve(navigator.serviceWorker.ready) : navigator.serviceWorker.register('/sw.js').then(function() { return navigator.serviceWorker.ready; })).then(function(reg) {
                            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes });
                        }).then(function(sub) {
                            function abToB64Url(buf) { var b = new Uint8Array(buf); var s = ''; for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); }
                            var subJson = { endpoint: sub.endpoint, keys: { p256dh: abToB64Url(sub.getKey('p256dh')), auth: abToB64Url(sub.getKey('auth')) } };
                            return fetch('/api/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: subJson }), credentials: 'same-origin' });
                        }).then(function(r) {
                            if (r.status === 401 || r.status === 403) { setStatus('로그인한 뒤 알림 허용을 시도해 주세요.'); return; }
                            return r.json();
                        }).then(function(d) {
                            if (!d) return;
                            if (d.success) { setStatus('알림이 켜졌습니다.'); permBtn.textContent = '알림 켜짐'; permBtn.disabled = true; } else { setStatus(d.message || '등록 실패'); }
                        });
                    }).catch(function() { setStatus('등록 중 오류가 났습니다.'); });
                }
            });
        })();
        var guideBtn = document.getElementById('pwa-install-guide-btn');
        if (guideBtn) guideBtn.addEventListener('click', openInstallGuideModal);
    })();
    (function(){
        var btn = document.getElementById('pwa-footer-add-home-btn');
        if (!btn) return;
        if (typeof window.deferredPrompt === 'undefined') window.deferredPrompt = null;
        if (!window._pwaPromptBound) { window._pwaPromptBound = true; window.addEventListener('beforeinstallprompt', function(e) { e.preventDefault(); window.deferredPrompt = e; }); }
        btn.addEventListener('click', function() {
            if (window.deferredPrompt) {
                window.deferredPrompt.prompt();
                window.deferredPrompt.userChoice.then(function(r) { if (r.outcome === 'accepted') window.deferredPrompt = null; });
            } else {
                var m = document.getElementById('pwa-install-guide-modal');
                if (m) { m.classList.remove('hidden'); m.classList.add('flex'); document.body.style.overflow = 'hidden'; }
            }
        });
    })();
    </script>

<div id="uncleModal" class="fixed inset-0 bg-stone-900/60 backdrop-blur-sm hidden items-center justify-center z-50 p-4">
  <div class="bg-white text-stone-800 max-w-3xl w-full rounded-2xl shadow-[0_24px_48px_rgba(0,0,0,0.15),0_0_0_1px_rgba(0,0,0,0.06)] overflow-hidden max-h-[85vh] flex flex-col">
    <div class="flex justify-between items-center px-6 py-5 border-b border-stone-100">
      <h2 id="uncleModalTitle" class="text-lg font-extrabold text-stone-800 tracking-tight"></h2>
      <button onclick="closeUncleModal()" class="w-10 h-10 rounded-xl text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center transition">✕</button>
    </div>
    <div id="uncleModalContent" class="p-6 text-sm leading-relaxed space-y-4 text-stone-600 overflow-y-auto"></div>
  </div>
</div>

    <!-- 접속 시 알림 팝업 (공지/이벤트/알림, 표시 기간 내만 노출) -->
    <div id="site-popup-modal" class="fixed inset-0 z-[60] hidden items-center justify-center bg-black/50 p-4">
        <div class="bg-white rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div class="flex justify-between items-center px-5 py-4 border-b border-gray-100">
                <span id="site-popup-type-badge" class="text-[10px] px-2 py-1 rounded font-black">공지</span>
                <button type="button" id="site-popup-close" class="w-10 h-10 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center text-xl leading-none">✕</button>
            </div>
            <div class="p-5 overflow-y-auto flex-1 text-left">
                <h3 id="site-popup-title" class="text-lg font-black text-gray-800 mb-2"></h3>
                <p id="site-popup-date" class="text-xs text-gray-500 mb-3 hidden"></p>
                <div id="site-popup-image-wrap" class="mb-4 hidden"><img id="site-popup-image" src="" alt="" class="w-full rounded-xl object-cover max-h-48"></div>
                <div id="site-popup-body" class="text-sm text-gray-700 whitespace-pre-wrap"></div>
            </div>
            <div class="px-5 py-4 border-t border-gray-100 flex justify-between items-center gap-3">
                <label class="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
                    <input type="checkbox" id="site-popup-today-hide" class="rounded">
                    <span>오늘 하루 안 보기</span>
                </label>
                <button type="button" id="site-popup-confirm" class="px-5 py-2.5 bg-teal-600 text-white rounded-xl font-black text-sm">확인</button>
            </div>
        </div>
    </div>
    <script>
    (function(){
        var modal = document.getElementById('site-popup-modal');
        if (!modal) return;
        var todayKey = function(id) { return 'popup_hide_' + id + '_' + new Date().toDateString(); };
        fetch('/api/popup/current').then(function(r){ return r.json(); }).then(function(data){
            if (!data || !data.id) return;
            if (sessionStorage.getItem(todayKey(data.id))) return;
            var typeBadge = document.getElementById('site-popup-type-badge');
            var titleEl = document.getElementById('site-popup-title');
            var dateEl = document.getElementById('site-popup-date');
            var imgWrap = document.getElementById('site-popup-image-wrap');
            var imgEl = document.getElementById('site-popup-image');
            var bodyEl = document.getElementById('site-popup-body');
            var closeBtn = document.getElementById('site-popup-close');
            var confirmBtn = document.getElementById('site-popup-confirm');
            var todayHide = document.getElementById('site-popup-today-hide');
            typeBadge.textContent = data.popup_type === 'event' ? '이벤트' : (data.popup_type === 'alert' ? '알림' : '공지');
            typeBadge.className = 'text-[10px] px-2 py-1 rounded font-black ' + (data.popup_type === 'event' ? 'bg-amber-100 text-amber-800' : (data.popup_type === 'alert' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-700'));
            titleEl.textContent = data.title || '';
            if (data.display_date) { dateEl.textContent = data.display_date; dateEl.classList.remove('hidden'); } else { dateEl.classList.add('hidden'); }
            if (data.image_url) { imgEl.src = data.image_url.indexOf('/') === 0 ? data.image_url : '/' + data.image_url; imgWrap.classList.remove('hidden'); } else { imgWrap.classList.add('hidden'); }
            bodyEl.textContent = data.body || '';
            function closeModal() { modal.classList.add('hidden'); modal.classList.remove('flex'); modal.style.display = 'none'; document.body.style.overflow = ''; }
            if (todayHide.checked) sessionStorage.setItem(todayKey(data.id), '1');
            closeBtn.onclick = function() { if (todayHide.checked) sessionStorage.setItem(todayKey(data.id), '1'); closeModal(); };
            confirmBtn.onclick = function() { if (todayHide.checked) sessionStorage.setItem(todayKey(data.id), '1'); closeModal(); };
            modal.onclick = function(e) { if (e.target === modal) { if (todayHide.checked) sessionStorage.setItem(todayKey(data.id), '1'); closeModal(); } };
            modal.classList.remove('hidden'); modal.classList.add('flex'); modal.style.display = 'flex'; document.body.style.overflow = 'hidden';
        }).catch(function(){});
    })();
    </script>

    <script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            sidebar.classList.toggle('open');
            overlay.classList.toggle('show');
        }

        const UNCLE_TERMS = {
    'terms': {
        'title': '바구니삼촌 서비스 이용약관',
        'content': `
            <b>제1조 (목적)</b><br>
            본 약관은 바구니삼촌(이하 “회사”)이 제공하는 구매대행 및 물류·배송 관리 서비스의 이용과 관련하여 회사와 이용자 간의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.<br><br>
            <b>제2조 (서비스의 성격 및 정의)</b><br>
            ① 회사는 이용자의 요청에 따라 상품을 대신 구매하고, 결제, 배송 관리, 고객 응대, 환불 처리 등 거래 전반을 회사가 직접 관리·운영하는 구매대행 서비스를 제공합니다.<br>
            ② 본 서비스는 <b>통신판매중개업(오픈마켓)이 아니며</b>, 회사가 거래 및 운영의 주체로서 서비스를 제공합니다.<br><br>
            <b>제4조 (회사의 역할 및 책임)</b><br>
            회사는 구매대행 과정에서 발생하는 주문, 결제, 배송, 환불 등 거래 전반에 대해 관계 법령에 따라 책임을 부담합니다.`
    },
    'privacy': {
        'title': '개인정보처리방침',
        'content': '<b>개인정보 수집 및 이용</b><br>수집항목: 이름, 연락처, 주소, 결제정보<br>이용목적: 상품 구매대행 및 송도 지역 직영 배송 서비스 제공<br>보관기간: 관련 법령에 따른 보존 기간 종료 후 즉시 파기'
    },
            'privacy': {
                'title': '개인정보처리방침',
                'content': '<b>개인정보의 수집 및 이용</b><br>바구니삼촌은 주문 처리, 상품 배송, 고객 상담을 위해 필수적인 개인정보를 수집하며, 관계 법령에 따라 안전하게 보호합니다.'
            },
            'agency': {
                'title': '서비스 이용 안내',
                'content': '<b>서비스 지역:</b> 인천광역시 연수구 송도동 일대 (인천대입구역 중심 동선)<br><b>운영 시간:</b> 평일 오전 9시 ~ 오후 6시<br><b>배송 원칙:</b> 신속하고 정확한 근거리 직접 배송'
            },
            'e_commerce': {
                'title': '전자상거래 이용자 유의사항',
                'content': '<b>거래 형태:</b> 본 서비스는 물류 인프라를 활용한 통합 유통 모델입니다.<br><b>환불 및 취소:</b> 상품 특성(신선식품 등)에 따라 환불이 제한될 수 있으며, 취소 시 이미 발생한 배송 비용이 청구될 수 있습니다.'
            }
        };

        function openUncleModal(type) {
            const data = UNCLE_TERMS[type];
            if(!data) return;
            document.getElementById('term-title').innerText = data.title;
            document.getElementById('term-modal-body').innerHTML = data.content;
            document.getElementById('term-modal').style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }

        function closeUncleModal() {
            document.getElementById('term-modal').style.display = 'none';
            document.body.style.overflow = 'auto';
        }

        async function addToCart(productId) {
            try {
                const response = await fetch(`/cart/add/${productId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.redirected) { window.location.href = response.url; return; }
                const result = await response.json();
                if (result.success) {
                    showToast("장바구니에 상품을 담았습니다! 🧺");
                    const badge = document.getElementById('cart-count-badge');
                    if(badge) badge.innerText = result.cart_count;
                    if(window.location.pathname === '/cart') location.reload();
                } else { 
                    showToast(result.message || "추가 실패");
                }
            } catch (error) { 
                console.error('Error:', error); 
                showToast("일시적인 오류가 발생했습니다.");
            }
        }

        async function minusFromCart(productId) {
            try {
                const response = await fetch(`/cart/minus/${productId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();
                if (result.success) {
                    const badge = document.getElementById('cart-count-badge');
                    if(badge) badge.innerText = result.cart_count;
                    location.reload(); 
                } else { alert(result.message); }
            } catch (error) { console.error('Error:', error); }
        }

        function showToast(msg) {
            const t = document.getElementById("toast");
            if(!t) return;
            t.innerText = msg;
            t.className = "show";
            setTimeout(() => { t.className = t.className.replace("show", ""); }, 2500);
        }

        function updateCountdowns() {
            const timers = document.querySelectorAll('.countdown-timer');
            const now = new Date().getTime();
            timers.forEach(timer => {
                if(!timer.dataset.deadline) { timer.innerText = "📅 상시판매"; return; }
                const deadline = new Date(timer.dataset.deadline).getTime();
                const diff = deadline - now;
                if (diff <= 0) {
                    timer.innerText = "판매마감";
                    const card = timer.closest('.product-card');
                    if (card && !card.classList.contains('sold-out')) { card.classList.add('sold-out'); }
                } else {
                    const h = Math.floor(diff / (1000 * 60 * 60));
                    const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                    const s = Math.floor((diff % (1000 * 60)) / 1000);
                    timer.innerText = `📦 ${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')} 남음`;
                }
            });
        }
        setInterval(updateCountdowns, 1000);
        updateCountdowns();
        
        function execDaumPostcode() {
            if (typeof daum === 'undefined' || !daum.Postcode) { alert('주소 검색 서비스를 불러오는 중입니다. 잠시 후 다시 시도해 주세요.'); return; }
            new daum.Postcode({
                oncomplete: function(data) {
                    var addr = data.userSelectedType === 'R' ? data.roadAddress : data.jibunAddress;
                    if (data.buildingName) addr += (addr ? ' ' : '') + data.buildingName;
                    var el = document.getElementById('address');
                    if (el) { el.value = addr; el.blur(); }
                    var detail = document.getElementById('address_detail');
                    if (detail) { setTimeout(function() { detail.focus(); }, 150); }
                }
            }).open();
        }
    </script>
<script>
function openUncleModal(type) {
  const title = document.getElementById('uncleModalTitle');
  const content = document.getElementById('uncleModalContent');

  const data = {
    terms: {
      title: '이용약관',
      content: `
      <p><strong>제1조 (목적)</strong><br>
      본 약관은 바구니삼촌(이하 "회사")이 제공하는 구매대행 및 배송 중개 서비스의 이용과 관련하여
      회사와 이용자 간의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.</p>

      <p><strong>제2조 (서비스의 정의)</strong><br>
      회사는 상품을 직접 판매하지 않으며,
      소비자의 요청에 따라 판매자(산지, 도매처 등)와 소비자를 연결하는
      구매대행 및 배송 중개 서비스를 제공합니다.</p>

      <p><strong>제3조 (서비스 이용 계약)</strong><br>
      이용자는 본 약관에 동의함으로써 서비스 이용 계약이 성립되며,
      결제 완료 시 구매대행 서비스 이용에 동의한 것으로 간주합니다.</p>

      <p><strong>제4조 (책임의 구분)</strong><br>
      상품의 품질, 원산지, 유통기한, 하자에 대한 책임은 판매자에게 있으며,
      회사는 주문 접수, 결제 처리, 배송 중개 및 고객 응대에 대한 책임을 집니다.</p>

      <p><strong>제5조 (면책 조항)</strong><br>
      천재지변, 배송사 사정, 판매자 사정 등 회사의 합리적인 통제 범위를 벗어난 사유로
      발생한 손해에 대하여 회사는 책임을 지지 않습니다.</p>
      `
    },

    privacy: {
      title: '개인정보처리방침',
      content: `
      <p><strong>1. 개인정보 수집 항목</strong><br>
      회사는 서비스 제공을 위해 다음과 같은 개인정보를 수집합니다.<br>
      - 필수항목: 이름, 휴대전화번호, 배송지 주소, 결제 정보</p>

      <p><strong>2. 개인정보 이용 목적</strong><br>
      수집된 개인정보는 다음 목적에 한하여 이용됩니다.<br>
      - 주문 처리 및 배송<br>
      - 고객 상담 및 민원 처리<br>
      - 결제 및 환불 처리</p>

      <p><strong>3. 개인정보 보관 및 이용 기간</strong><br>
      개인정보는 수집 및 이용 목적 달성 시까지 보관하며,
      관계 법령에 따라 일정 기간 보관 후 안전하게 파기합니다.</p>

      <p><strong>4. 개인정보 제3자 제공</strong><br>
      회사는 배송 및 주문 처리를 위해 판매자 및 배송업체에 한해
      최소한의 개인정보를 제공합니다.</p>

      <p><strong>5. 개인정보 보호</strong><br>
      회사는 개인정보 보호를 위해 기술적·관리적 보호 조치를 취하고 있습니다.</p>
      `
    },

    agency: {
      title: '이용안내',
      content: `
      <p><strong>서비스 안내</strong><br>
      바구니삼촌은 상품을 직접 보유하거나 판매하지 않는
      구매대행 및 배송 중개 플랫폼입니다.</p>

      <p><strong>주문 절차</strong><br>
      ① 이용자가 상품 선택 및 결제<br>
      ② 회사가 판매자에게 구매 요청<br>
      ③ 판매자가 상품 준비<br>
      ④ 배송을 통해 고객에게 전달</p>

      <p><strong>결제 안내</strong><br>
      결제 금액은 상품 대금과 배송비로 구성되며,
      구매대행 수수료는 별도로 청구되지 않습니다.</p>

      <p><strong>유의사항</strong><br>
      상품 정보는 판매자가 제공하며,
      실제 상품은 이미지와 다소 차이가 있을 수 있습니다.</p>
      `
    },

    e_commerce: {
      title: '전자상거래 유의사항',
      content: `
      <p><strong>1. 청약 철회 및 환불</strong><br>
      일반 상품의 경우 전자상거래법에 따라
      상품 수령 후 7일 이내 청약 철회가 가능합니다.</p>

      <p><strong>2. 농산물 및 신선식품</strong><br>
      농산물·신선식품은 특성상 단순 변심에 의한
      환불이 제한될 수 있습니다.</p>

      <p><strong>3. 환불 가능 사유</strong><br>
      - 상품 하자<br>
      - 오배송<br>
      - 상품 훼손</p>

      <p><strong>4. 환불 절차</strong><br>
      고객센터 접수 후 확인 절차를 거쳐
      결제 수단으로 환불 처리됩니다.</p>

      <p><strong>5. 분쟁 처리</strong><br>
      분쟁 발생 시 전자상거래 관련 법령 및
      소비자 분쟁 해결 기준을 따릅니다.</p>
      `
    }
  };

  title.innerText = data[type].title;
  content.innerHTML = data[type].content;
  document.getElementById('uncleModal').classList.remove('hidden');
  document.getElementById('uncleModal').classList.add('flex');
}

function closeUncleModal() {
  document.getElementById('uncleModal').classList.add('hidden');
  document.getElementById('uncleModal').classList.remove('flex');
}
</script>
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function() { navigator.serviceWorker.register('/sw.js').catch(function() {}); });
}
</script>

</body>

</html>
"""

# --------------------------------------------------------------------------------
# 5. 비즈니스 로직 및 라우팅
# --------------------------------------------------------------------------------

# --------------------------------------------------------------------------------
# 5. 비즈니스 로직 및 라우팅 (보완 완료 버전)
# --------------------------------------------------------------------------------
@app.route('/admin/settlement/complete', methods=['POST'])
@login_required
def admin_settlement_complete():
    """마스터 관리자가 특정 카테고리의 매출을 정산 완료 처리"""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403

    data = request.get_json()
    cat_name = data.get('category_name')
    amount = data.get('amount')
    manager_email = data.get('manager_email')

    try:
        # 1. 정산 기록 생성 (카테고리별 정산 내역)
        new_settle = CategorySettlement(
            category_name=cat_name,
            manager_email=manager_email,
            total_sales=amount,
            settlement_amount=amount,
            status='입금완료',
            completed_at=datetime.now()
        )
        db.session.add(new_settle)
        
        # 2. 해당 기간/카테고리의 주문 상태를 '정산완료'로 업데이트하고 싶다면 
        # 여기에 추가 로직을 작성할 수 있습니다. (현재는 기록만 남김)
        
        db.session.commit()
        return jsonify({"success": True, "message": f"{cat_name} 정산 처리가 완료되었습니다."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/settlement/order_status', methods=['POST'])
@login_required
def admin_settlement_order_status():
    """관리자·카테고리관리자: 주문별 정산상태(입금상태) 변경 (입금대기/입금완료/취소/보류)"""
    data = request.get_json() or {}
    try:
        order_id = data.get('order_id')
        if order_id is None:
            return jsonify({"success": False, "message": "order_id가 없습니다."}), 400
        order_id = int(order_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "order_id가 올바르지 않습니다."}), 400
    settlement_status = (data.get('settlement_status') or '').strip()
    if settlement_status not in ('입금대기', '입금완료', '취소', '보류'):
        return jsonify({"success": False, "message": "유효한 입금상태가 아닙니다."}), 400
    o = Order.query.get(order_id)
    if not o:
        return jsonify({"success": False, "message": "주문을 찾을 수 없습니다."}), 404
    if not current_user.is_admin:
        my_cats = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
        if not my_cats:
            return jsonify({"success": False, "message": "권한이 없습니다."}), 403
        order_items = OrderItem.query.filter_by(order_id=o.id).all()
        if not any(getattr(oi, 'product_category', None) in my_cats for oi in order_items):
            return jsonify({"success": False, "message": "해당 주문에 대한 권한이 없습니다."}), 403
    # 이미 요청한 상태와 같으면 성공 처리 (재클릭 시 오류 방지)
    if getattr(o, 'settlement_status', None) == settlement_status:
        return jsonify({"success": True, "message": "이미 해당 상태입니다."})
    if getattr(o, 'settlement_status', None) == '입금완료' and settlement_status != '입금완료':
        return jsonify({"success": False, "message": "이미 입금완료된 주문은 다른 상태로 변경할 수 없습니다."}), 400
    old_settlement = getattr(o, 'settlement_status', None) or '입금대기'
    o.settlement_status = settlement_status
    if settlement_status == '입금완료':
        o.is_settled = True
        o.settled_at = datetime.now()
    else:
        o.is_settled = False
        o.settled_at = None
    # 해당 주문의 모든 품목(OrderItem)도 동일한 입금상태로 일괄 반영 (정산상세는 품목 단위 표시)
    for oi in OrderItem.query.filter_by(order_id=o.id).all():
        oi.settlement_status = settlement_status
        if settlement_status == '입금완료':
            oi.settled_at = datetime.now()
        else:
            oi.settled_at = None
        db.session.add(OrderItemLog(order_id=o.id, order_item_id=oi.id, log_type='settlement_status', old_value=old_settlement, new_value=settlement_status, created_at=datetime.now()))
    db.session.add(OrderItemLog(order_id=o.id, order_item_id=None, log_type='settlement_status', old_value=old_settlement, new_value=settlement_status, created_at=datetime.now()))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "저장 중 오류가 발생했습니다: " + str(e)}), 500
    return jsonify({"success": True, "message": "입금상태가 변경되었습니다."})


@app.route('/admin/settlement/item_status', methods=['POST'])
@login_required
def admin_settlement_item_status():
    """품목ID(OrderItem) 기준 입금상태 개별 변경 (입금완료는 품목별 적용)"""
    data = request.get_json() or {}
    order_id = data.get('order_id')  # Order.id (pk)
    item_id = data.get('item_id')    # OrderItem.id (pk)
    settlement_status = (data.get('settlement_status') or '').strip()
    if settlement_status not in ('입금대기', '입금완료', '취소', '보류'):
        return jsonify({"success": False, "message": "유효한 입금상태가 아닙니다."}), 400
    if not order_id or not item_id:
        return jsonify({"success": False, "message": "order_id와 item_id가 필요합니다."}), 400
    o = Order.query.get(order_id)
    if not o:
        return jsonify({"success": False, "message": "주문을 찾을 수 없습니다."}), 404
    oi = OrderItem.query.filter_by(id=int(item_id), order_id=int(order_id)).first()
    if not oi:
        return jsonify({"success": False, "message": "품목을 찾을 수 없습니다."}), 404
    if not current_user.is_admin:
        my_cats = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
        if not my_cats or oi.product_category not in my_cats:
            return jsonify({"success": False, "message": "해당 품목에 대한 권한이 없습니다."}), 403
    old_settlement = getattr(oi, 'settlement_status', None) or '입금대기'
    oi.settlement_status = settlement_status
    if settlement_status == '입금완료':
        oi.settled_at = datetime.now()
    else:
        oi.settled_at = None
    db.session.add(OrderItemLog(order_id=o.id, order_item_id=oi.id, log_type='settlement_status', old_value=old_settlement, new_value=settlement_status, created_at=datetime.now()))
    # Settlement 테이블도 동기화 (정산 상세는 Settlement 기준 조회)
    st = Settlement.query.filter_by(order_item_id=oi.id).first()
    if st:
        st.settlement_status = settlement_status
        st.settled_at = datetime.now() if settlement_status == '입금완료' else None
    db.session.commit()
    return jsonify({"success": True, "message": "품목 입금상태가 변경되었습니다."})


@app.route('/admin/settlement/bulk_item_status', methods=['POST'])
@login_required
def admin_settlement_bulk_item_status():
    """정산 상세에서 선택한 품목들(OrderItem) 입금상태 일괄 변경"""
    data = request.get_json() or {}
    item_ids = data.get('order_item_ids') or data.get('item_ids') or []
    if isinstance(item_ids, str):
        item_ids = [x.strip() for x in item_ids.split(',') if x.strip()]
    item_ids = [int(x) for x in item_ids if str(x).isdigit()]
    settlement_status = (data.get('settlement_status') or '').strip()
    if settlement_status not in ('입금대기', '입금완료', '취소', '보류'):
        return jsonify({"success": False, "message": "유효한 입금상태가 아닙니다."}), 400
    if not item_ids:
        return jsonify({"success": False, "message": "선택한 품목이 없습니다."}), 400
    is_master = current_user.is_admin
    my_cats = [] if is_master else [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
    updated = 0
    for oi_id in item_ids:
        oi = OrderItem.query.get(oi_id)
        if not oi:
            continue
        if not is_master and (not my_cats or getattr(oi, 'product_category', None) not in my_cats):
            continue
        old_st = getattr(oi, 'settlement_status', None) or '입금대기'
        oi.settlement_status = settlement_status
        if settlement_status == '입금완료':
            oi.settled_at = datetime.now()
        else:
            oi.settled_at = None
        db.session.add(OrderItemLog(order_id=oi.order_id, order_item_id=oi.id, log_type='settlement_status', old_value=old_st, new_value=settlement_status, created_at=datetime.now()))
        st = Settlement.query.filter_by(order_item_id=oi.id).first()
        if st:
            st.settlement_status = settlement_status
            st.settled_at = datetime.now() if settlement_status == '입금완료' else None
        updated += 1
    db.session.commit()
    return jsonify({"success": True, "message": f"{updated}건 입금상태가 변경되었습니다.", "updated": updated})


@app.route('/admin/messages/send', methods=['POST'])
@login_required
def admin_messages_send():
    """관리자: 회원 등급별로 메시지 일괄 발송 (가입인사·이벤트·공지·안내·직접작성)"""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    data = request.get_json() or request.form
    target = data.get('target_grade', 'all')  # 1,2,3,4,5 or 'all'
    msg_type = (data.get('msg_type') or 'custom').strip() or 'custom'
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title:
        return jsonify({"success": False, "message": "제목을 입력해 주세요."})
    q = User.query.filter(User.is_admin == False)
    if target != 'all' and str(target).isdigit():
        g = int(target)
        if 1 <= g <= 5:
            q = q.filter(User.member_grade == g)
    users = q.all()
    count = 0
    for u in users:
        send_message(u.id, title, body, msg_type, None)
        count += 1
    db.session.commit()
    return jsonify({"success": True, "message": f"{count}명에게 발송되었습니다.", "count": count})


@app.route('/admin/messages/template', methods=['POST'])
@login_required
def admin_messages_template():
    """관리자: 자동 발송 템플릿 저장. msg_type, title, body. {order_id}는 발송 시 주문번호로 치환됨."""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    data = request.get_json() or request.form
    msg_type = (data.get('msg_type') or '').strip()
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not msg_type:
        return jsonify({"success": False, "message": "msg_type이 필요합니다."})
    t = MessageTemplate.query.filter_by(msg_type=msg_type).first()
    if not t:
        t = MessageTemplate(msg_type=msg_type, title=title or '알림', body=body)
        db.session.add(t)
    else:
        t.title = title or t.title or '알림'
        t.body = body
    db.session.commit()
    return jsonify({"success": True, "message": "템플릿이 저장되었습니다."})


@app.route('/api/messages/unread_count')
@login_required
def api_messages_unread_count():
    """로그인 사용자의 미읽음 메시지 개수 (알림 바 표시용)."""
    n = UserMessage.query.filter_by(user_id=current_user.id, read_at=None).count()
    return jsonify({"count": n})


@app.route('/api/popup/current')
def api_popup_current():
    """현재 노출할 알림 팝업 1건. 노출 기간 내·활성만. 없으면 null."""
    now = datetime.now()
    q = SitePopup.query.filter(
        SitePopup.is_active == True,
        db.or_(SitePopup.start_at.is_(None), SitePopup.start_at <= now),
        db.or_(SitePopup.end_at.is_(None), SitePopup.end_at >= now)
    ).order_by(SitePopup.sort_order.asc(), SitePopup.end_at.asc().nullslast())
    pop = q.first()
    if not pop:
        return jsonify(None)
    return jsonify({
        'id': pop.id,
        'title': pop.title or '',
        'body': pop.body or '',
        'popup_type': pop.popup_type or 'notice',
        'image_url': pop.image_url or '',
        'display_date': pop.display_date or ''
    })


@app.route('/admin/popup/save', methods=['POST'])
@login_required
def admin_popup_save():
    """알림 팝업 저장. id 있으면 수정, 없으면 신규."""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    data = request.get_json() or request.form
    try:
        pid = data.get('id')
        pid = int(pid) if pid not in (None, '') else None
    except (TypeError, ValueError):
        pid = None
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({"success": False, "message": "제목을 입력해 주세요."})
    body = (data.get('body') or '').strip()
    popup_type = (data.get('popup_type') or 'notice').strip() or 'notice'
    image_url = (data.get('image_url') or '').strip() or None
    display_date = (data.get('display_date') or '').strip() or None
    start_at = None
    if data.get('start_at'):
        try:
            start_at = datetime.strptime(data.get('start_at')[:19], '%Y-%m-%dT%H:%M:%S')
        except Exception:
            try:
                start_at = datetime.strptime(data.get('start_at')[:16], '%Y-%m-%dT%H:%M')
            except Exception:
                pass
    end_at = None
    if data.get('end_at'):
        try:
            end_at = datetime.strptime(data.get('end_at')[:19], '%Y-%m-%dT%H:%M:%S')
        except Exception:
            try:
                end_at = datetime.strptime(data.get('end_at')[:16], '%Y-%m-%dT%H:%M')
            except Exception:
                pass
    is_active = data.get('is_active') not in (False, 'false', '0', 0)
    sort_order = int(data.get('sort_order') or 0)
    if pid:
        pop = SitePopup.query.get(pid)
        if not pop:
            return jsonify({"success": False, "message": "해당 팝업이 없습니다."})
    else:
        pop = SitePopup()
    pop.title = title
    pop.body = body
    pop.popup_type = popup_type
    pop.image_url = image_url
    pop.display_date = display_date
    pop.start_at = start_at
    pop.end_at = end_at
    pop.is_active = is_active
    pop.sort_order = sort_order
    if not pid:
        db.session.add(pop)
    db.session.commit()
    return jsonify({"success": True, "message": "저장되었습니다.", "id": pop.id})


@app.route('/admin/popup/delete/<int:pid>', methods=['POST'])
@login_required
def admin_popup_delete(pid):
    if not current_user.is_admin:
        return jsonify({"success": False}), 403
    pop = SitePopup.query.get(pid)
    if pop:
        db.session.delete(pop)
        db.session.commit()
    return jsonify({"success": True})


@app.route('/admin/popup/upload', methods=['POST'])
@login_required
def admin_popup_upload():
    """알림 팝업용 이미지 업로드. 반환: { url: /static/uploads/... }"""
    if not current_user.is_admin:
        return jsonify({"success": False}), 403
    f = request.files.get('image')
    if not f or f.filename == '':
        return jsonify({"success": False, "message": "이미지 파일을 선택해 주세요."}), 400
    path = save_uploaded_file(f)
    if not path:
        return jsonify({"success": False, "message": "업로드 실패"}), 400
    return jsonify({"success": True, "url": path})


@app.route('/api/push/vapid-public')
def api_push_vapid_public():
    """Web Push 구독 시 필요한 VAPID 공개키. 로그인 불필요."""
    key = os.getenv('VAPID_PUBLIC_KEY')
    if not key:
        return jsonify({"error": "푸시 알림이 설정되지 않았습니다."}), 503
    return jsonify({"publicKey": key})


@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    """현재 사용자의 푸시 구독 등록. body: { subscription: { endpoint, keys: { p256dh, auth } } }"""
    key = os.getenv('VAPID_PUBLIC_KEY')
    if not key:
        return jsonify({"success": False, "message": "푸시 알림이 설정되지 않았습니다."}), 503
    data = request.get_json()
    if not data or not data.get('subscription'):
        return jsonify({"success": False, "message": "subscription이 필요합니다."}), 400
    sub = data['subscription']
    endpoint = (sub.get('endpoint') or '').strip()
    keys = sub.get('keys') or {}
    p256dh = (keys.get('p256dh') or keys.get('p256dh') or '').strip()
    auth = (keys.get('auth') or '').strip()
    if not endpoint or not p256dh or not auth:
        return jsonify({"success": False, "message": "endpoint, keys.p256dh, keys.auth가 필요합니다."}), 400
    existing = PushSubscription.query.filter_by(user_id=current_user.id, endpoint=endpoint).first()
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.session.add(PushSubscription(user_id=current_user.id, endpoint=endpoint, p256dh=p256dh, auth=auth))
    db.session.commit()
    return jsonify({"success": True, "message": "알림이 켜졌습니다."})


@app.route('/admin/order/print')
@login_required
def admin_order_print():
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        return "권한이 없습니다.", 403

    categories = Category.query.all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    is_master = current_user.is_admin

    order_ids = request.args.get('ids', '').split(',')
    target_orders = Order.query.filter(Order.order_id.in_(order_ids)).all()

    # 데이터 가공 (마스킹 및 요약)
    processed_orders = []
    for o in target_orders:
        # 성함/번호 마스킹 동일
        name = o.customer_name or ""
        masked_name = name[0] + "*" * (len(name)-1) if len(name) > 1 else name
        
        phone = o.customer_phone or ""
        phone_parts = phone.split('-')
        masked_phone = f"{phone_parts[0]}-****-{phone_parts[2]}" if len(phone_parts) == 3 else "****"

        # ✅ 품목: 마스터는 전체, 카테고리 매니저는 해당 카테고리 품목만
        all_items = []
        if o.product_details:
            parts = o.product_details.split(' | ')
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*)', part)
                if match:
                    cat_n = match.group(1).strip()
                    items_str = match.group(2).strip()
                    if is_master or cat_n in my_categories:
                        for item in items_str.split(', '):
                            clean_item = item.strip()
                            if clean_item:
                                all_items.append(clean_item)

        # 카테고리 매니저는 해당 품목이 없는 주문은 송장에서 제외
        if not is_master and not all_items:
            continue

        # ✅ 현관 비밀번호 제외 로직 (숫자 포함 단어 필터링 강화)
        raw_memo = o.request_memo or ""
        clean_words = [w for w in raw_memo.split() if not (any(c.isdigit() for c in w) or any(k in w for k in ['비번', '번호', '현관', '#', '*']))]
        clean_memo = " ".join(clean_words) if clean_words else "요청사항 없음"

        processed_orders.append({
            'order_id': o.order_id,
            'masked_name': masked_name,
            'masked_phone': masked_phone,
            'all_items': all_items,
            'delivery_address': o.delivery_address,
            'clean_memo': clean_memo,
            'created_at': o.created_at
        })
# SyntaxWarning 방지를 위해 시작 부분에 r을 붙여 r""" 로 작성합니다.
    invoice_html = r"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
            body { font-family: 'Noto Sans KR', sans-serif; background: #f1f1f1; margin: 0; padding: 0; --inv-scale: 1; --inv-width-mm: 80; }
            .print-container { display: flex; flex-wrap: wrap; justify-content: center; gap: 1rem; padding: 1rem; align-items: flex-start; }
            .invoice-card { background: white; border: 2px solid #000; box-sizing: border-box; display: flex; flex-direction: column; position: relative; transform-origin: top left; }
            .item-list { overflow: hidden; }
            .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

            /* A4 1장: 1건이 A4 한 페이지 전체 */
            body.layout-a4-1 .invoice-card { width: 21cm; min-height: 29.2cm; padding: 1.5rem; margin: 0 auto 1rem; }
            body.layout-a4-1 .item-list { max-height: 12cm; }
            /* A4 2분할 */
            body.layout-a4-2 .print-container { flex-direction: column; align-items: center; }
            body.layout-a4-2 .invoice-card { width: 21cm; height: 14.6cm; padding: 1rem; margin: 0 auto 0.5rem; }
            body.layout-a4-2 .item-list { max-height: 4.2cm; }
            /* A4 3분할 */
            body.layout-a4-3 .print-container { flex-direction: column; align-items: center; }
            body.layout-a4-3 .invoice-card { width: 21cm; height: 9.7cm; padding: 0.6rem; margin: 0 auto 0.3rem; }
            body.layout-a4-3 .item-list { max-height: 2.6cm; }
            /* A4 4등분: 세로 2열(2x2), 비율맞춰 셀 안에 축소 */
            body.layout-a4-4 .print-container {
                display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 14.6cm;
                gap: 0; padding: 0; max-width: 21cm; margin: 0 auto;
            }
            body.layout-a4-4 .invoice-card {
                width: 100%; height: 100%; min-height: 0; padding: 0.4rem;
                box-sizing: border-box; margin: 0; overflow: hidden;
            }
            body.layout-a4-4 .invoice-card .text-4xl { font-size: 1rem !important; }
            body.layout-a4-4 .invoice-card .text-2xl { font-size: 0.8rem !important; }
            body.layout-a4-4 .invoice-card .text-xl { font-size: 0.7rem !important; }
            body.layout-a4-4 .item-list { max-height: 4.5cm; }
            /* 휴대용: 가로폭 mm + 스케일로 조절 */
            body.layout-portable .invoice-card {
                width: calc(var(--inv-width-mm) * 0.2645833rem);
                min-height: 8cm;
                padding: 0.4rem;
                transform: scale(var(--inv-scale));
                margin: 0.5rem;
            }
            body.layout-portable .item-list { max-height: 3.5cm; }

            @media print {
                @page { size: A4; margin: 8mm; }
                .no-print { display: none !important; }
                body { background: white; }
                .print-container { gap: 0; padding: 0; }
                .invoice-card { border: 1.5px solid #000; page-break-inside: avoid; }
                body.layout-a4-1 .invoice-card { margin: 0 auto; page-break-after: always; }
                body.layout-a4-1 .invoice-card:last-child { page-break-after: auto; }
                body.layout-a4-2 .invoice-card { margin: 0 auto; }
                body.layout-a4-2 .invoice-card:nth-child(2n) { page-break-after: always; }
                body.layout-a4-2 .invoice-card:last-child:nth-child(2n-1) { page-break-after: always; }
                body.layout-a4-3 .invoice-card { margin: 0 auto; }
                body.layout-a4-3 .invoice-card:nth-child(3n) { page-break-after: always; }
                body.layout-a4-3 .invoice-card:last-child { page-break-after: always; }
                body.layout-a4-4 .print-container { display: grid; grid-template-columns: 1fr 1fr; grid-auto-rows: 14.6cm; max-width: 21cm; }
                body.layout-a4-4 .invoice-card { margin: 0; }
                body.layout-a4-4 .invoice-card:nth-child(4n) { page-break-after: always; }
                body.layout-a4-4 .invoice-card:last-child { page-break-after: always; }
                body.layout-portable .invoice-card {
                    width: calc(var(--inv-width-mm) * 0.2645833rem) !important;
                    transform: scale(var(--inv-scale)) !important;
                    margin: 0 auto 2mm !important;
                    page-break-after: always;
                }
                body.layout-portable .invoice-card:last-child { page-break-after: auto; }
            }
        </style>
    </head>
    <body class="layout-a4-2">
        <div class="no-print p-4 bg-white border-b sticky top-0 z-50 shadow-md">
            <p class="text-sm font-bold text-blue-600 mb-3">총 {{ orders|length }}건 · 출력 양식 선택 후 인쇄하세요.</p>
            <div class="flex flex-wrap items-center gap-3 mb-2">
                <span class="text-xs font-black text-gray-500">양식:</span>
                <button type="button" onclick="setLayout('layout-a4-1')" class="layout-btn px-4 py-2 rounded-xl text-xs font-black border-2 border-gray-300 hover:border-teal-500 hover:bg-teal-50" data-layout="layout-a4-1">A4 1장</button>
                <button type="button" onclick="setLayout('layout-a4-2')" class="layout-btn px-4 py-2 rounded-xl text-xs font-black border-2 border-teal-500 bg-teal-50 text-teal-700" data-layout="layout-a4-2">A4 2분할</button>
                <button type="button" onclick="setLayout('layout-a4-3')" class="layout-btn px-4 py-2 rounded-xl text-xs font-black border-2 border-gray-300 hover:border-teal-500 hover:bg-teal-50" data-layout="layout-a4-3">A4 3분할</button>
                <button type="button" onclick="setLayout('layout-a4-4')" class="layout-btn px-4 py-2 rounded-xl text-xs font-black border-2 border-gray-300 hover:border-teal-500 hover:bg-teal-50" data-layout="layout-a4-4">A4 4등분</button>
                <button type="button" onclick="setLayout('layout-portable')" class="layout-btn px-4 py-2 rounded-xl text-xs font-black border-2 border-gray-300 hover:border-teal-500 hover:bg-teal-50" data-layout="layout-portable">휴대용</button>
            </div>
            <div id="portable-options" class="hidden flex-wrap items-center gap-4 mt-3 p-3 bg-gray-50 rounded-xl">
                <label class="flex items-center gap-2">
                    <span class="text-xs font-black text-gray-600">폭(mm):</span>
                    <select id="portable-width" onchange="applyPortableSize()" class="border rounded-lg px-2 py-1 text-xs font-black">
                        <option value="58">58mm</option>
                        <option value="80" selected>80mm</option>
                        <option value="100">100mm</option>
                    </select>
                </label>
                <label class="flex items-center gap-2">
                    <span class="text-xs font-black text-gray-600">크기:</span>
                    <input type="range" id="portable-scale" min="0.5" max="1.5" step="0.05" value="1" oninput="applyPortableSize()" class="w-24">
                    <span id="portable-scale-val" class="text-xs font-black text-gray-700">100%</span>
                </label>
            </div>
            <div class="mt-3">
                <button onclick="window.print()" class="bg-blue-600 text-white px-8 py-2.5 rounded-xl font-black text-sm shadow-lg hover:bg-blue-700">🖨️ 인쇄</button>
            </div>
        </div>

        <div class="print-container">
            {% for o in orders %}
            <div class="invoice-card">
                <div class="flex justify-between items-center border-b-4 border-black pb-2 mb-2">
                    <h1 class="text-2xl font-black tracking-tighter text-teal-700 italic">바구니삼촌</h1>
                    <p class="text-[11px] font-black bg-black text-white px-3 py-1 rounded">송도 전용 배송</p>
                </div>
                <div class="flex justify-between items-start mb-2">
                    <div class="w-2/3">
                        <p class="text-[9px] text-gray-400 font-black uppercase mb-1">Recipient</p>
                        <p class="text-4xl font-black text-gray-900 leading-none mb-1">{{ o.masked_name }}</p>
                        <p class="text-2xl font-black text-gray-700">{{ o.masked_phone }}</p>
                    </div>
                    <div class="w-1/3 text-right">
                        <p class="text-[9px] text-gray-400 font-black uppercase mb-1">Order ID</p>
                        <p class="text-xs font-black bg-gray-100 px-2 py-1 inline-block rounded">{{ o.order_id[-8:] }}</p>
                        <p class="text-[10px] text-gray-400 mt-1 font-bold">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                    </div>
                </div>
                <div class="bg-gray-50 p-3 rounded-xl border-l-8 border-teal-600 mb-2">
                    <p class="text-[9px] text-gray-400 font-black mb-1 uppercase">Shipping Address</p>
                    <p class="text-xl font-black text-black leading-tight mb-1">{{ o.delivery_address }}</p>
                    <div class="bg-white px-2 py-1.5 rounded-lg border border-red-100 mt-1">
                        <p class="text-[11px] font-black text-red-600">요청: {{ o.clean_memo }}</p>
                    </div>
                </div>
                <div class="flex-grow overflow-hidden">
                    <p class="text-[9px] text-gray-400 font-black mb-1 border-b pb-1 uppercase">Order Items</p>
                    <div class="item-list space-y-1">
                        {% for item in o.all_items %}
                        <div class="flex items-center justify-between border-b border-gray-50 pb-0.5">
                            <span class="text-[13px] font-black text-gray-800 line-clamp-1">□ {{ item }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                <div class="pt-2 border-t border-dashed border-gray-300 text-center opacity-40">
                    <p class="text-[8px] font-black italic uppercase">Basket Uncle</p>
                </div>
            </div>
            {% endfor %}
        </div>
        <script>
        function setLayout(cls) {
            document.body.className = cls;
            document.querySelectorAll('.layout-btn').forEach(function(b) {
                b.classList.remove('border-teal-500', 'bg-teal-50', 'text-teal-700');
                b.classList.add('border-gray-300');
                if (b.getAttribute('data-layout') === cls) {
                    b.classList.add('border-teal-500', 'bg-teal-50', 'text-teal-700');
                    b.classList.remove('border-gray-300');
                }
            });
            var po = document.getElementById('portable-options');
            if (po) po.classList.toggle('hidden', cls !== 'layout-portable');
        }
        function applyPortableSize() {
            var w = document.getElementById('portable-width');
            var s = document.getElementById('portable-scale');
            var v = document.getElementById('portable-scale-val');
            if (w) document.body.style.setProperty('--inv-width-mm', w.value);
            if (s) {
                document.body.style.setProperty('--inv-scale', s.value);
                if (v) v.textContent = Math.round(parseFloat(s.value) * 100) + '%';
            }
        }
        </script>
    </body>
    </html>
    """
    return render_template_string(invoice_html, orders=processed_orders)
@app.context_processor
def inject_globals():
    """전역 템플릿 변수 주입"""
    cart_count = 0
    unread_message_count = 0
    grade = 1
    if current_user.is_authenticated:
        total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar()
        cart_count = total_qty if total_qty else 0
        grade = getattr(current_user, 'member_grade', 1) or 1
        unread_message_count = UserMessage.query.filter_by(user_id=current_user.id, read_at=None).count()
    categories = categories_for_member_grade(grade).all()
    managers = [c.manager_email for c in categories if c.manager_email]
    return dict(cart_count=cart_count, unread_message_count=unread_message_count, now=datetime.now(), managers=managers, nav_categories=categories)

@app.route('/api/search')
def api_search():
    """검색 무한 스크롤용 API (30개 단위, offset/limit)"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    offset = int(request.args.get('offset', 0))
    limit = min(int(request.args.get('limit', 30)), 50)
    query = Product.query.filter(Product.is_active == True, Product.name.contains(q)).order_by(Product.id.desc())
    products = query.offset(offset).limit(limit).all()
    return jsonify([{
        "id": p.id, "name": p.name, "price": p.price, "image_url": p.image_url,
        "description": p.description or "", "stock": p.stock,
        "is_sold_out": (p.deadline and p.deadline < datetime.now()) or p.stock <= 0,
    } for p in products])


@app.route('/search')
def search_view():
    """검색 결과 전용 페이지 (30개 초기 로딩 + 무한 스크롤, 트래픽 절감)"""
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))

    base_query = Product.query.filter(Product.is_active == True, Product.name.contains(query)).order_by(Product.id.desc())
    total_count = base_query.count()
    search_products = base_query.limit(30).all()
    search_has_more = total_count > 30

    grade = (getattr(current_user, 'member_grade', 1) or 1) if current_user.is_authenticated else 1
    recommend_cats = categories_for_member_grade(grade).limit(3).all()
    cat_previews = {cat: Product.query.filter_by(category=cat.name, is_active=True).limit(4).all() for cat in recommend_cats}

    content = """
    <div class="max-w-7xl mx-auto px-4 md:px-6 py-12 md:py-20 text-left">
        <h2 class="text-2xl md:text-4xl font-black text-gray-800 mb-8">
            <span class="text-teal-600">"{{ query }}"</span> 검색 결과 ({{ total_count }}건)
        </h2>

        {% if search_products %}
        <div id="search-product-grid" class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-6 mb-12">
            {% for p in search_products %}
            <div class="product-card bg-white rounded-3xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-2xl {% if p.stock <= 0 %}sold-out{% endif %}">
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                    <img src="{{ p.image_url }}" loading="lazy" class="w-full h-full object-cover p-2 md:p-6">
                </a>
                <div class="p-3 md:p-8 flex flex-col flex-1">
                    <h3 class="font-black text-gray-800 text-[11px] md:text-base mb-1 truncate">{{ p.name }}</h3>
                    <div class="mt-auto flex justify-between items-end">
                        <span class="text-[13px] md:text-2xl font-black text-teal-600">{{ "{:,}".format(p.price) }}원</span>
                        <button onclick="addToCart('{{p.id}}')" class="bg-teal-600 w-8 h-8 md:w-14 md:h-14 rounded-xl text-white flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        <div id="search-load-more-trigger" class="h-4"></div>
        <div id="search-spinner" class="hidden py-8 text-center text-gray-400"><i class="fas fa-spinner fa-spin text-2xl"></i></div>
        <div id="search-end-message" class="hidden py-6 text-center text-gray-400 text-sm font-bold">모든 검색 결과를 불러왔습니다.</div>
        {% else %}
            <div class="py-20 text-center bg-gray-50 rounded-[3rem] border-2 border-dashed border-gray-200 mb-20">
                <p class="text-gray-400 font-black text-lg">찾으시는 상품이 없습니다. 😥</p>
            </div>
        {% endif %}

        <hr class="border-gray-100 mb-20">
        
        <h3 class="text-xl md:text-3xl font-black text-gray-800 mb-10 italic">이런 상품은 어떠세요?</h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-10">
            {% for cat, prods in cat_previews.items() %}
            <div class="bg-gray-50 p-8 rounded-[3rem] border border-gray-100 shadow-inner">
                <h3 class="text-xl font-black mb-6">{{ cat.name }} <a href="/category/{{ cat.name }}" class="text-xs text-gray-400 ml-2">더보기 ></a></h3>
                <div class="grid grid-cols-2 gap-4">
                    {% for cp in prods %}
                    <a href="/product/{{ cp.id }}" class="bg-white p-3 rounded-2xl shadow-sm hover:scale-105 transition"><img src="{{ cp.image_url }}" class="w-full aspect-square object-contain"></a>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="mt-20 text-center">
            <a href="/" class="inline-block bg-gray-800 text-white px-12 py-5 rounded-full font-black shadow-xl hover:bg-black transition">메인으로 이동</a>
        </div>
    </div>
    {% if search_has_more %}
    <script>
    (function(){
        var searchOffset = 30;
        var searchLoading = false;
        var searchHasMore = true;
        var searchQ = {{ query|tojson }};
        var scrollDebounceTimer = null;
        function searchLoadMore(){
            if (searchLoading || !searchHasMore) return;
            searchLoading = true;
            document.getElementById('search-spinner').classList.remove('hidden');
            fetch('/api/search?q=' + encodeURIComponent(searchQ) + '&offset=' + searchOffset + '&limit=30')
                .then(function(r){ return r.json(); })
                .then(function(data){
                    if (!data || data.length === 0){ searchHasMore = false; document.getElementById('search-end-message').classList.remove('hidden'); }
                    else {
                        var grid = document.getElementById('search-product-grid');
                        data.forEach(function(p){
                            var sold = p.is_sold_out ? ' sold-out' : '';
                            grid.insertAdjacentHTML('beforeend',
                                '<div class="product-card bg-white rounded-3xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-2xl' + sold + '">'
                                + '<a href="/product/' + p.id + '" class="relative aspect-square block bg-white overflow-hidden"><img src="' + p.image_url + '" loading="lazy" class="w-full h-full object-cover p-2 md:p-6"></a>'
                                + '<div class="p-3 md:p-8 flex flex-col flex-1"><h3 class="font-black text-gray-800 text-[11px] md:text-base mb-1 truncate">' + p.name + '</h3>'
                                + '<div class="mt-auto flex justify-between items-end"><span class="text-[13px] md:text-2xl font-black text-teal-600">' + (p.price || 0).toLocaleString() + '원</span>'
                                + '<button onclick="addToCart(\\'' + p.id + '\\')" class="bg-teal-600 w-8 h-8 md:w-14 md:h-14 rounded-xl text-white flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-xl"></i></button></div></div></div>');
                        });
                        searchOffset += data.length;
                        if (data.length < 30) { searchHasMore = false; document.getElementById('search-end-message').classList.remove('hidden'); }
                    }
                })
                .catch(function(e){ searchHasMore = false; })
                .finally(function(){
                    searchLoading = false;
                    document.getElementById('search-spinner').classList.add('hidden');
                });
        }
        var searchTrigger = document.getElementById('search-load-more-trigger');
        if (searchTrigger){
            var searchObserver = new IntersectionObserver(function(entries){
                if (!entries[0].isIntersecting) return;
                if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
                scrollDebounceTimer = setTimeout(function(){ searchLoadMore(); scrollDebounceTimer = null; }, 1000);
            }, { threshold: 0.1, rootMargin: '300px' });
            searchObserver.observe(searchTrigger);
        }
    })();
    </script>
    {% endif %}
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, query=query, search_products=search_products, total_count=total_count, search_has_more=search_has_more, cat_previews=cat_previews, recommend_cats=recommend_cats)

@app.route('/')
def index():
    """메인 페이지 (디자인 유지)"""
    run_product_stock_reset()
    grade = (getattr(current_user, 'member_grade', 1) or 1) if current_user.is_authenticated else 1
    categories = categories_for_member_grade(grade).all()
    grouped_products = {}
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    
    latest_all = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).limit(30).all()
    random_latest = random.sample(latest_all, min(len(latest_all), 30)) if latest_all else []
    
    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    closing_today = Product.query.filter(Product.is_active == True, Product.deadline > datetime.now(), Product.deadline <= today_end).order_by(Product.deadline.asc()).limit(50).all()
    latest_reviews = Review.query.order_by(Review.created_at.desc()).limit(4).all()

    for cat in categories:
        prods = Product.query.filter_by(category=cat.name, is_active=True).order_by(order_logic, Product.id.desc()).limit(20).all()
        if prods: grouped_products[cat] = prods
    
    content = """
<style>
/* ========== 메인 페이지 전용 프리미엄 스타일 ========== */
.page-main { --hero-bg: linear-gradient(165deg, #0c1222 0%, #1a2744 35%, #0f172a 70%, #020617 100%); }
.page-main .hero-wrap {
    background: var(--hero-bg);
    color: #f8fafc;
    padding: clamp(4rem, 12vw, 8rem) 1.5rem;
    position: relative;
    overflow: hidden;
    min-height: 70vh;
    display: flex;
    align-items: center;
}
.page-main .hero-wrap::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(13, 148, 136, 0.18) 0%, transparent 50%),
                radial-gradient(ellipse 60% 40% at 80% 60%, rgba(13, 148, 136, 0.08) 0%, transparent 40%);
    pointer-events: none;
}
.page-main .hero-wrap::after {
    content: '';
    position: absolute;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E");
    pointer-events: none;
    opacity: 0.6;
}
.page-main .hero-inner { position: relative; z-index: 1; max-width: 56rem; margin: 0 auto; text-align: center; }
.page-main .hero-label {
    font-size: clamp(0.65rem, 1.5vw, 0.8rem);
    font-weight: 800;
    letter-spacing: 0.35em;
    text-transform: uppercase;
    color: rgba(134, 239, 172, 0.9);
    margin-bottom: 1.5rem;
    display: inline-block;
}
.page-main .hero-title {
    font-size: clamp(1.75rem, 5vw, 3.75rem);
    font-weight: 900;
    line-height: 1.1;
    letter-spacing: -0.03em;
    margin-bottom: 1.5rem;
    color: #f1f5f9;
}
.page-main .hero-title .accent { color: #4ade80; font-weight: 900; letter-spacing: -0.02em; }
.page-main .hero-divider {
    width: 4rem;
    height: 3px;
    background: linear-gradient(90deg, transparent, rgba(74, 222, 128, 0.6), transparent);
    margin: 0 auto 2rem;
    border-radius: 2px;
}
.page-main .hero-desc {
    font-size: clamp(0.9rem, 1.8vw, 1.15rem);
    color: rgba(226, 232, 240, 0.85);
    line-height: 1.7;
    max-width: 36rem;
    margin: 0 auto 2.5rem;
    font-weight: 600;
}
.page-main .hero-desc .highlight { color: #e2e8f0; text-decoration: underline; text-underline-offset: 6px; text-decoration-color: rgba(45, 212, 191, 0.8); }
.page-main .hero-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 1rem 2.25rem;
    font-weight: 800;
    font-size: 0.95rem;
    color: #fff;
    background: linear-gradient(135deg, #0d9488 0%, #0f766e 100%);
    border-radius: 9999px;
    box-shadow: 0 4px 20px rgba(13, 148, 136, 0.35), 0 1px 0 rgba(255,255,255,0.1) inset;
    transition: transform 0.2s ease, box-shadow 0.25s ease;
}
.page-main .hero-cta:hover { transform: translateY(-2px); box-shadow: 0 8px 28px rgba(13, 148, 136, 0.45); }
.page-main .hero-link {
    color: rgba(248, 250, 252, 0.7);
    font-weight: 700;
    font-size: 0.85rem;
    border-bottom: 1px solid rgba(255,255,255,0.2);
    padding-bottom: 2px;
    transition: color 0.2s, border-color 0.2s;
}
.page-main .hero-link:hover { color: #fff; border-color: rgba(255,255,255,0.5); }
.page-main #products {
    max-width: 80rem;
    margin: 0 auto;
    padding: clamp(3rem, 8vw, 5rem) 1.5rem;
}
.page-main .section-title {
    font-size: clamp(1.15rem, 2.2vw, 1.6rem);
    font-weight: 900;
    color: #1c1917;
    letter-spacing: -0.02em;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
}
.page-main .section-title .bar { width: 4px; height: 1.5rem; border-radius: 2px; flex-shrink: 0; }
.page-main .section-title.bar-orange .bar { background: linear-gradient(180deg, #fb923c, #ea580c); }
.page-main .section-title.bar-green .bar { background: linear-gradient(180deg, #14b8a6, #0d9488); }
.page-main .review-card {
    background: #fff;
    border-radius: 1rem;
    padding: 0.6rem;
    border: 1px solid #f1f5f9;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    transition: transform 0.25s ease, box-shadow 0.25s ease;
}
.page-main .review-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.06); }
.page-main .review-card img { border-radius: 0.5rem; object-fit: cover; max-height: 5rem; width: 100%; }
.page-main .review-card .review-meta { font-size: 0.5rem; }
.page-main .review-card .review-content { font-size: 0.6rem; line-height: 1.3; }
.page-main .product-card {
    background: #fff;
    border-radius: 1.75rem;
    border: 1px solid #f1f5f9;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.35s ease, border-color 0.25s;
}
.page-main .product-card:hover { transform: translateY(-6px); box-shadow: 0 20px 50px rgba(0,0,0,0.08); border-color: #d6d3d1; }
.page-main .product-card .price { font-weight: 900; color: #0f766e; letter-spacing: -0.02em; }
.page-main .product-card .add-btn {
    width: 2.5rem;
    height: 2.5rem;
    border-radius: 0.75rem;
    background: linear-gradient(135deg, #0d9488, #0f766e);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 12px rgba(13, 148, 136, 0.3);
    transition: transform 0.2s, box-shadow 0.2s;
}
@media (min-width: 768px) { .page-main .product-card .add-btn { width: 3.5rem; height: 3.5rem; border-radius: 1.25rem; } }
.page-main .product-card .add-btn:hover { transform: scale(1.05); box-shadow: 0 6px 18px rgba(13, 148, 136, 0.4); }
.page-main .product-card .add-btn:active { transform: scale(0.96); }
</style>

<div class="page-main">
<div class="hero-wrap">
    <div class="hero-inner">
        <span class="hero-label">Direct Delivery & Agency Service</span>
        <h1 class="hero-title">
            판매가 아닌, <span class="accent">배송 서비스</span> 입니다.<br>
            <span class="accent">Premium 6PL Service</span>
        </h1>
        <div class="hero-divider"></div>
        <p class="hero-desc">
            바구니삼촌은 재고를 쌓아두는 판매처가 아닌, <br class="hidden md:block">
            이용자의 요청에 따라 <span class="highlight">구매와 배송을 책임 대행</span>하는 물류 인프라입니다.
        </p>
        <div class="flex flex-col md:flex-row justify-center items-center gap-6">
            <a href="#products" class="hero-cta">대행 서비스 이용하기</a>
            <a href="/about" class="hero-link">6PL 구매대행이란? <i class="fas fa-arrow-right ml-2"></i></a>
        </div>
    </div>
</div>

<div id="products">
    {% if latest_reviews %}
    <section class="mb-8">
        <div class="flex justify-between items-end border-b border-slate-100 pb-3 mb-4">
            <h2 class="section-title bar-orange"><span class="bar"></span> 📸 생생한 구매 후기</h2>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
            {% for r in latest_reviews %}
            <div class="review-card flex flex-col gap-1.5">
                {% if r.image_url %}<img src="{{ r.image_url }}" class="bg-slate-50" alt="" loading="lazy">{% else %}<div class="bg-slate-100 rounded-lg h-16 flex items-center justify-center text-slate-400 text-[10px] font-bold">사진 없음</div>{% endif %}
                <div>
                    <p class="review-meta text-slate-400 font-bold mb-0.5">{{ r.user_name[:1] }}**님 | {{ r.product_name }}</p>
                    <p class="review-content font-bold text-slate-700 line-clamp-2">{{ r.content }}</p>
                </div>
            </div>
            {% endfor %}
        </div>
    </section>
    {% endif %}

    {% for cat, products in grouped_products.items() %}
    <section class="mb-8">
        <div class="flex justify-between items-end border-b border-slate-100 pb-3 mb-4">
            <div>
                <h2 class="section-title bar-green"><span class="bar"></span> {{ cat.name }} 리스트</h2>
            </div>
            <a href="/category/{{ cat.name }}" class="text-xs md:text-sm font-bold text-stone-400 hover:text-teal-600 flex items-center gap-1 transition">전체보기 <i class="fas fa-chevron-right text-[8px]"></i></a>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 md:gap-5">
            {% for p in products %}
            <div class="product-card flex flex-col overflow-hidden relative rounded-2xl border border-slate-100 bg-white shadow-sm hover:shadow-lg transition-all {% if p.stock <= 0 %}sold-out opacity-80{% endif %}">
                {% if p.description %}
                <div class="absolute top-2 left-0 z-20">
                    <span class="px-2 py-0.5 text-[8px] md:text-[10px] font-black text-white shadow-md rounded-r-full
                        {% if '당일' in p.description %} bg-red-600
                        {% elif '+1' in p.description %} bg-blue-600
                        {% elif '+2' in p.description %} bg-emerald-600
                        {% else %} bg-slate-600 {% endif %}">
                        <i class="fas fa-truck-fast mr-1"></i> {{ p.description }}
                    </span>
                </div>
                {% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-slate-50 overflow-hidden">
                    <img src="{{ p.image_url or 'https://placehold.co/400x400/f1f5f9/64748b?text=상품' }}" loading="lazy" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/400x400/f1f5f9/64748b?text=상품'">
                </a>
                <div class="p-3 md:p-4 flex flex-col flex-1">
                    <h3 class="font-black text-slate-800 text-[11px] md:text-sm mb-1 line-clamp-2">
                        {{ p.name }}
                        {% if p.badge %}<span class="text-[9px] text-orange-500 font-bold ml-0.5">| {{ p.badge }}</span>{% endif %}
                    </h3>
                    <div class="flex items-center gap-1.5 mb-2">
                        <span class="text-[8px] md:text-[10px] text-slate-400 font-bold bg-slate-100 px-1.5 py-0.5 rounded">{{ p.spec or '일반' }}</span>
                    </div>
                    <div class="mt-auto flex justify-between items-end gap-2">
                        <span class="price text-[12px] md:text-lg font-black text-teal-700">{{ "{:,}".format(p.price) }}원</span>
                        <button onclick="addToCart('{{p.id}}')" class="add-btn shrink-0"><i class="fas fa-plus text-[10px] md:text-base"></i></button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </section>
    {% endfor %}
</div>
</div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, 
                                  grouped_products=grouped_products, 
                                  random_latest=random_latest, 
                                  closing_today=closing_today, 
                                  latest_reviews=latest_reviews)

# --- 상단 HEADER_HTML 내의 검색창 부분도 아래와 같이 반드시 수정되어야 합니다 ---
# (HEADER_HTML 변수를 찾아서 해당 부분의 action="/"을 action="/search"로 바꾸세요)
# 1. <form action="/search" method="GET" class="relative hidden md:block max-w-xs flex-1">
# 2. <form action="/search" method="GET" class="relative">
    """메인 페이지"""
    query = request.args.get('q', '').strip()
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    grouped_products = {}
    
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    
    # 최신 상품 30개 중 30개 랜덤
    latest_all = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).limit(30).all()
    random_latest = random.sample(latest_all, min(len(latest_all), 30)) if latest_all else []
    
    # 오늘 마감 상품 (트래픽 절감용 상한)
    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    closing_today = Product.query.filter(
        Product.is_active == True,
        Product.deadline > datetime.now(),
        Product.deadline <= today_end
    ).order_by(Product.deadline.asc()).limit(50).all()

    # 최신 리뷰 4개 (메인 노출)
    latest_reviews = Review.query.order_by(Review.created_at.desc()).limit(4).all()

    for cat in categories:
        q_obj = Product.query.filter_by(category=cat.name, is_active=True)
        if query: q_obj = q_obj.filter(Product.name.contains(query))
        products = q_obj.order_by(order_logic, Product.id.desc(), Product.deadline.asc()).limit(20).all()
        if products: grouped_products[cat] = products
    
    content = """
   <div class="bg-gray-900 text-white py-20 md:py-32 px-4 shadow-inner relative overflow-hidden text-center">
    <div class="max-w-7xl mx-auto relative z-10 font-black text-center">
        
        <span class="text-teal-400 text-[10px] md:text-sm font-black mb-6 inline-block uppercase tracking-[0.3em]">
            Direct Delivery Service
        </span>

        <h1 class="hero-title text-3xl md:text-7xl font-black mb-8 leading-tight tracking-tighter">
            판매가 아닌, <span class="text-teal-500 uppercase">배송 서비스</span> 입니다.<br>
            <span class="text-teal-500 uppercase text-2xl md:text-4xl mt-4 inline-block">Premium Service</span>
        </h1>

        <div class="w-12 h-1 bg-white/20 mx-auto mb-8"></div>

        <p class="hero-desc text-gray-400 text-sm md:text-2xl font-bold max-w-2xl mx-auto mb-12">
            바구니삼촌은 재고를 쌓아두는 판매처가 아닌, 이용자의 요청에 따라 구매와 배송을 책임 대행하는 물류 인프라입니다.
        </p>

        <div class="flex flex-col md:flex-row justify-center items-center gap-6">
            <a href="#products"
               class="bg-teal-600 text-white px-10 py-4 md:px-12 md:py-5 rounded-full font-black shadow-2xl hover:bg-teal-700 transition active:scale-95">
                쇼핑하러 가기
            </a>

            <a href="/about"
               class="text-white/60 hover:text-white font-bold border-b border-white/20 pb-1 transition text-xs md:text-base">
                바구니삼촌이란? <i class="fas fa-arrow-right ml-2"></i>
            </a>
        </div>

    </div>

    <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/dark-matter.png')] opacity-30"></div>
</div>

    <div id="products" class="max-w-7xl mx-auto px-4 py-10 text-left">
        {% if query %}
            <p class="mb-5 font-black text-gray-400 text-lg md:text-xl border-b border-gray-100 pb-3 text-left">
                <span class="text-teal-600">"{{ query }}"</span>에 대한 상품 검색 결과입니다.
            </p>
        {% endif %}

        {% if latest_reviews and not query %}
        <section class="mb-8 text-left">
            <div class="mb-4 flex justify-between items-end border-b border-gray-100 pb-3 text-left">
                <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                    <span class="w-1.5 h-8 bg-orange-400 rounded-full"></span> 📸 생생한 구매 후기
                </h2>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-6 text-left">
                {% for r in latest_reviews %}
                <div class="bg-white rounded-[2rem] p-4 shadow-sm border border-gray-50 flex flex-col gap-3 transition hover:shadow-xl hover:-translate-y-1">
                    <img src="{{ r.image_url }}" class="w-full aspect-square object-cover rounded-2xl bg-gray-50">
                    <div>
                        <p class="text-[10px] text-gray-400 font-bold mb-1">{{ r.user_name[:1] }}**님 | {{ r.product_name }}</p>
                        <p class="text-[11px] font-bold text-gray-700 line-clamp-2 leading-relaxed">{{ r.content }}</p>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}

        {% if random_latest and not query %}
        <section class="mb-8 text-left">
            <div class="mb-4 flex justify-between items-end border-b border-gray-100 pb-3 text-left">
                <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                    <span class="w-1.5 h-8 bg-blue-500 rounded-full"></span> ✨ 최신 상품
                </h2>
                <a href="/category/최신상품" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-teal-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 md:gap-5 text-left">
                {% for p in random_latest %}
                <div class="product-card bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-gray-50 overflow-hidden">
                        <img src="{{ p.image_url or 'https://placehold.co/400x400?text=NEW' }}" loading="lazy" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/400x400/f1f5f9/64748b?text=상품'">
                        <div class="absolute top-2 left-2"><span class="bg-blue-500 text-white text-[9px] md:text-[10px] px-2 py-0.5 rounded-lg uppercase font-black">NEW</span></div>
                    </a>
                    <div class="p-3 md:p-4 flex flex-col flex-1 text-left">
                        <h3 class="font-black text-gray-800 text-[11px] md:text-sm line-clamp-2 mb-0.5">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-teal-600 mb-2 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[12px] md:text-lg text-gray-900 font-black">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-teal-600 w-8 h-8 md:w-10 md:h-10 rounded-xl text-white flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px]"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}

        {% if closing_today and not query %}
        <section class="mb-8 text-left">
            <div class="mb-4 flex justify-between items-end border-b border-gray-100 pb-3 text-left">
                <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                    <span class="w-1.5 h-8 bg-red-500 rounded-full"></span> 🔥 오늘 마감 임박!
                </h2>
                <a href="/category/오늘마감" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-teal-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 md:gap-5 text-left">
                {% for p in closing_today %}
                <div class="product-card bg-white rounded-2xl shadow-sm border border-red-50 overflow-hidden relative flex flex-col transition-all hover:shadow-xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}"loading="lazy" class="w-full h-full object-cover p-1.5 md:p-5">
                        <div class="absolute bottom-2 left-2 md:bottom-5 md:left-5"><span class="bg-red-600 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg font-black animate-pulse uppercase">CLOSING</span></div>
                    </a>
                    <div class="p-3 md:p-7 flex flex-col flex-1 text-left">
                        <p class="countdown-timer text-[8px] md:text-[10px] font-bold text-red-500 mb-1.5" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-teal-600 mb-2 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[13px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-teal-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-teal-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}
        
        {% for cat, products in grouped_products.items() %}
        <section class="mb-8 text-left">
            <div class="mb-4 flex justify-between items-end border-b border-gray-100 pb-3 text-left">
                <div class="text-left">
                    <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter text-left">
                        <span class="w-1.5 h-8 bg-teal-500 rounded-full"></span> {{ cat.name }} 리스트
                    </h2>
                    {% if cat.description %}<p class="text-[11px] md:text-sm text-gray-400 mt-2 font-bold text-left">{{ cat.description }}</p>{% endif %}
                </div>
                <a href="/category/{{ cat.name }}" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-teal-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4 md:gap-5 text-left">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-xl {% if is_expired or p.stock <= 0 %}sold-out opacity-80{% endif %} text-left">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge absolute top-2 right-2 z-10 bg-gray-800 text-white text-[9px] px-2 py-1 rounded-lg font-black">판매마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-gray-50 overflow-hidden text-left">
                        <img src="{{ p.image_url or 'https://placehold.co/400x400/f1f5f9/64748b?text=상품' }}" loading="lazy" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/400x400/f1f5f9/64748b?text=상품'">
                        <div class="absolute bottom-2 left-2 text-left">
                            <span class="bg-black/70 text-white text-[9px] md:text-[10px] px-2 py-0.5 rounded font-black backdrop-blur-sm">잔여 {{ p.stock }}</span>
                        </div>
                    </a>
                    <div class="p-3 md:p-8 flex flex-col flex-1 text-left">
                        <p class="countdown-timer text-[8px] md:text-[10px] font-bold text-red-500 mb-1.5 text-left" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5 text-left">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-teal-600 mb-2 font-medium truncate text-left">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end text-left">
                            <span class="text-[13px] md:text-2xl font-black text-teal-600 text-left">{{ "{:,}".format(p.price) }}원</span>
                            {% if not is_expired and p.stock > 0 %}
                            <button onclick="addToCart('{{p.id}}')" class="bg-teal-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-teal-700 flex items-center justify-center transition active:scale-90 text-center">
                                <i class="fas fa-plus text-[10px] md:text-xl"></i>
                            </button>
                            {% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endfor %}
    </div>

    <!-- 메인 하단: 홈화면 바로가기 배너 (설명 + 설치 버튼 + 닫기) -->
    <div id="home-add-bar" class="fixed bottom-0 left-0 right-0 z-50 bg-stone-800/98 backdrop-blur border-t border-stone-600 shadow-2xl px-4 py-4 md:py-3 transition-transform duration-300" style="display: none;">
        <div class="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
            <div class="flex flex-col sm:flex-row items-center gap-3 flex-1 min-w-0">
                <button type="button" id="home-add-bar-install-btn" class="shrink-0 inline-flex items-center justify-center gap-2 bg-teal-500 hover:bg-teal-400 text-white font-black py-3 px-6 rounded-2xl shadow-lg transition text-sm">
                    <i class="fas fa-home"></i> 홈화면 바로가기
                </button>
                <p class="text-stone-300 text-xs md:text-sm font-bold text-center sm:text-left max-w-md">
                    <span class="text-teal-400 font-extrabold">설치 방법:</span> 앱처럼 빠르게 쇼핑하세요. Android는 Chrome <strong>메뉴(⋮)</strong> → 홈 화면에 추가, iOS는 Safari <strong>공유</strong> → 홈 화면에 추가
                </p>
            </div>
            <button type="button" id="home-add-bar-close" class="shrink-0 w-10 h-10 rounded-full bg-stone-600 hover:bg-stone-500 text-stone-300 hover:text-white flex items-center justify-center transition font-bold text-lg" aria-label="닫기">×</button>
        </div>
    </div>
    <script>
    (function(){
        var bar = document.getElementById('home-add-bar');
        if (!bar) return;
        var key = 'home_add_bar_closed';
        if (sessionStorage.getItem(key)) return;
        bar.style.display = 'block';
        if (typeof window.deferredPrompt === 'undefined') window.deferredPrompt = null;
        if (!window._pwaPromptBound) { window._pwaPromptBound = true; window.addEventListener('beforeinstallprompt', function(e) { e.preventDefault(); window.deferredPrompt = e; }); }
        document.getElementById('home-add-bar-install-btn').addEventListener('click', function(){
            if (window.deferredPrompt) {
                window.deferredPrompt.prompt();
                window.deferredPrompt.userChoice.then(function(r) { if (r.outcome === 'accepted') window.deferredPrompt = null; });
            } else {
                alert('Android: Chrome 메뉴(⋮) → 홈 화면에 추가\\niOS: Safari 공유 버튼 → 홈 화면에 추가');
            }
        });
        document.getElementById('home-add-bar-close').addEventListener('click', function(){
            sessionStorage.setItem(key, '1');
            bar.style.transform = 'translateY(100%)';
            setTimeout(function(){ bar.style.display = 'none'; }, 300);
        });
    })();
    </script>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products, random_latest=random_latest, closing_today=closing_today, latest_reviews=latest_reviews)

@app.route('/about')
def about_page():
    """제공된 HTML 형식을 반영한 바구니삼촌 브랜드 소개 페이지"""
    content = """
    <style>
        /* 소개 페이지 전용 스타일 */
        .about-body {
            margin: 0;
            background-color: #f9fafb;
            color: #111827;
            line-height: 1.7;
            font-family: "Pretendard", "Noto Sans KR", sans-serif;
        }

        .about-container {
            max-width: 1100px;
            margin: 0 auto;
            padding: 80px 20px;
            text-align: left; /* 왼쪽 정렬 유지 */
        }

        .about-container h1 {
            font-size: 42px;
            font-weight: 800;
            margin-bottom: 24px;
            letter-spacing: -0.02em;
        }

        .about-container h2 {
            font-size: 28px;
            font-weight: 800;
            margin: 80px 0 24px;
            color: #111827;
        }

        .about-container p {
            font-size: 17px;
            margin-bottom: 20px;
            color: #374151;
        }

        .about-container b {
            color: #111827;
        }

        .about-highlight {
            font-weight: 700;
            color: #059669;
        }

        /* Core Value Boxes */
        .core-values {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 24px;
            margin-top: 40px;
        }

        .value-box {
            background: #ffffff;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.05);
            border: 1px solid #f3f4f6;
        }

        .value-box span {
            display: block;
            font-size: 14px;
            font-weight: 700;
            color: #6b7280;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        .value-box strong {
            font-size: 48px;
            color: #059669;
            font-weight: 900;
            font-style: italic;
        }

        /* Premium 6PL Model Section */
        .premium-section {
            margin-top: 100px;
            background: #111827;
            color: #ffffff;
            border-radius: 32px;
            padding: 60px 50px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
        }

        .premium-section h2 {
            color: #ffffff;
            margin-top: 0;
            font-size: 32px;
        }

        .premium-list {
            margin-top: 32px;
            padding: 0;
        }

        .premium-list li {
            list-style: none;
            font-size: 19px;
            margin-bottom: 18px;
            position: relative;
            padding-left: 32px;
            font-weight: 500;
            color: #d1d5db;
        }

        .premium-list li::before {
            content: "✔";
            position: absolute;
            left: 0;
            color: #10b981;
            font-weight: 900;
        }

        .premium-list li b {
            color: #ffffff;
        }

        /* Call To Action Button */
        .about-cta {
            text-align: center;
            margin-top: 100px;
            padding-bottom: 40px;
        }

        .about-cta a {
            display: inline-block;
            padding: 20px 48px;
            font-size: 20px;
            font-weight: 800;
            background: #059669;
            color: #ffffff;
            border-radius: 999px;
            text-decoration: none;
            transition: all 0.3s ease;
            box-shadow: 0 10px 20px rgba(5, 150, 105, 0.2);
        }

        .about-cta a:hover {
            background: #047857;
            transform: translateY(-3px);
            box-shadow: 0 15px 30px rgba(5, 150, 105, 0.3);
        }

        @media (max-width: 640px) {
            .about-container { padding: 60px 24px; }
            .about-container h1 { font-size: 32px; }
            .premium-section { padding: 40px 30px; }
            .value-box strong { font-size: 38px; }
        }
    </style>

    <div class="about-body">
        <div class="about-container">
    <h1>바구니 삼촌몰</h1>
    <p>
        바구니 삼촌몰은 <span class="about-highlight">물류 인프라를 직접 운영하며 주문 전 과정을 책임지는 구매대행 서비스</span>입니다.
    </p>
    <p>
        우리는 기존 유통의 불필요한 단계를 제거하기 위해 <b>상품 대리 구매 · 직영 물류 · 라스트마일 배송</b>을 하나의 시스템으로 통합했습니다.
    </p>
    <p>
        단순히 판매자와 구매자를 연결하는 중개 플랫폼이 아니라, 이용자의 요청을 받아 <span class="about-highlight">삼촌이 직접 검수하고 구매하여 문 앞까지 배송</span>하는 책임 대행 모델을 지향합니다.
    </p>
    <p>
        직구/구매대행 방식의 효율적인 물류 시스템을 통해 광고비와 유통 거품을 뺐으며, 그 혜택을 <b>상품의 실제 조달 원가와 합리적인 배송비</b>에 그대로 반영합니다.
    </p>

    <h2>Our Core Value</h2>
    <div class="core-values">
        <div class="value-box">
            <span>불필요 유통 마진</span>
            <strong>ZERO</strong>
        </div>
        <div class="value-box">
            <span>배송 책임 서비스</span>
            <strong>DIRECT</strong>
        </div>
    </div>

    <p style="margin-top: 60px; font-size: 19px; font-weight: 700; border-left: 4px solid #10b981; padding-left: 20px;">
        바구니 삼촌은 중개만 하는 장터가 아니라, <br>
        <span class="about-highlight">‘구매부터 배송까지 당사가 직접 책임지고 완료하는 대행 플랫폼’</span>입니다.
    </p>

            <div class="premium-section">
                <h2>Premium 6PL Model</h2>
                <ul class="premium-list">
                    <li><b>송도 생활권 중심</b>의 직영 배송 네트워크</li>
                    <li>산지 소싱부터 문 앞까지 <b>삼촌이 직접 관리</b></li>
                    <li>자체 기술 인프라를 통한 <b>압도적 비용 절감</b></li>
                    <li>불필요한 마케팅비를 뺀 <b>원가 중심 유통</b></li>
                    <li>가장 합리적인 유통을 <b>송도에서 실현</b></li>
                </ul>
            </div>

            <div class="about-cta">
                <a href="/">지금 상품 확인하기</a>
            </div>
            <p class="text-center mt-6">
                <a href="/guide" class="text-teal-600 font-bold hover:text-teal-700 underline underline-offset-4">이용안내</a>
            </p>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)


GUIDE_HTML = """
<div class="max-w-3xl mx-auto px-4 py-12 md:py-20">
    <h1 class="text-2xl md:text-3xl font-black text-gray-900 mb-8">🛒 바구니삼촌몰 이용안내</h1>
    <div class="border border-gray-200 rounded-2xl p-6 md:p-8 bg-gray-50/80 text-gray-700 text-sm md:text-base leading-relaxed">
        <p class="mb-4">
            바구니삼촌몰은 <b class="text-gray-900">6PL 구매대행 기반 공동구매 플랫폼</b>으로 운영됩니다.<br>
            재고 보관과 오프라인 매장을 없애고, 고객 주문 후 도매처에 직접 발주하는 방식으로
            <b class="text-gray-900">유통 거품을 최소화</b>하여 합리적인 가격을 제공합니다.
        </p>
        <ul class="list-disc pl-5 mb-6 space-y-1">
            <li><b>가격 정책:</b> 공동구매 도매가 그대로 공급 + 배송비 1,900원</li>
            <li><b>운영 구조:</b> 무재고 · 무매장 · 도매처 직발주 시스템</li>
            <li><b>배송 방식:</b> 도매처 → 고객 집앞 직배송</li>
            <li><b>묶음 배송:</b> 가능 (상품별 조건 상이)</li>
        </ul>
        <h2 class="text-lg font-black text-gray-900 mt-6 mb-2">🥬 농산·축산 신선 배송 프로세스</h2>
        <p class="mb-2">
            바구니삼촌몰의 농산·축산 상품은 <b>당일 경매 · 당일 도축 상품만 취급</b>합니다.
        </p>
        <ul class="list-disc pl-5 mb-4 space-y-1">
            <li>밤 12시 주문 마감</li>
            <li>도매처 주문 정보 자동 전송</li>
            <li>당일 경매 및 도축 진행</li>
            <li>오전 상품 픽업</li>
            <li>오후 고객 배송</li>
        </ul>
        <p class="mb-6">
            → 재고 보관 상품이 아닌 <b>실시간 수급 기반 신선 상품</b>으로 더욱 신선하고 합리적인 가격에 공급됩니다.
        </p>
        <h2 class="text-lg font-black text-gray-900 mt-6 mb-2">🏭 공산품 운영 방식</h2>
        <ul class="list-disc pl-5 mb-6 space-y-1">
            <li>주문 후 도매처 구매 진행</li>
            <li>무재고 운영으로 보관 비용 최소화</li>
            <li>공동구매 단가 적용</li>
            <li>매장 운영비 절감으로 가격 경쟁력 확보</li>
        </ul>
        <h2 class="text-lg font-black text-gray-900 mt-6 mb-2">🚚 배송 안내</h2>
        <ul class="list-disc pl-5 mb-4 space-y-1">
            <li><b>기본 배송비:</b> 1,900원</li>
            <li>냉장/냉동, 부피 초과, 산지직송 상품은 추가 배송비가 발생할 수 있습니다.</li>
            <li>추가 배송비는 상품 상세페이지에 별도 안내됩니다.</li>
        </ul>
        <p class="mb-8">
            향후 주문 고객 증가 시 <b>오전 · 새벽 · 저녁 배송</b>으로 단계적 확대 예정이며,<br>
            지역 로컬맛집 및 배달 음식점 상품도 <b>최대 20% 할인</b> 형태로 제공될 예정입니다.
        </p>
        <hr class="border-gray-200 my-6">
        <h2 class="text-lg font-black text-gray-900 mb-3">⚠️ 주문 전 필수 확인</h2>
        <ul class="list-disc pl-5 space-y-2">
            <li>장바구니 단계에서는 언제든지 주문 취소가 가능합니다.</li>
            <li>본 서비스는 공동구매 및 실시간 수급 기반 특성상 도매처 품절, 수급 변동 등의 사유로 <b>부분 또는 전체 취소</b>가 발생할 수 있습니다.</li>
            <li>비정상적, 상업적 재판매 목적, 시스템 악용이 의심되는 주문은 <b>관리자 판단에 따라 사전 안내 후 취소</b>될 수 있습니다.</li>
            <li>상품 준비가 시작된 이후에는 취소·변경이 제한될 수 있습니다.</li>
        </ul>
        <p class="mt-8 text-center">
            <a href="/" class="inline-block bg-teal-600 text-white px-8 py-3 rounded-xl font-bold hover:bg-teal-700 transition">쇼핑하러 가기</a>
            <a href="/about" class="inline-block ml-3 text-teal-600 font-bold hover:underline">바구니삼촌이란?</a>
        </p>
    </div>
</div>
"""


@app.route('/guide')
def guide_page():
    """바구니삼촌몰 이용안내 전용 페이지 (결제 버튼 없음)"""
    return render_template_string(HEADER_HTML + GUIDE_HTML + FOOTER_HTML)


# ---------- 전국맛집요청 / 제휴문의 게시판 ----------
def _restaurant_recommend_count(rid):
    return RestaurantRecommend.query.filter_by(restaurant_request_id=rid).count()


def _user_recommended_restaurant(rid):
    if not current_user.is_authenticated:
        return False
    return RestaurantRecommend.query.filter_by(restaurant_request_id=rid, user_id=current_user.id).first() is not None


@app.route('/board/restaurant-request')
def board_restaurant_request():
    """전국맛집요청 목록"""
    posts = RestaurantRequest.query.filter_by(is_hidden=False).order_by(RestaurantRequest.id.desc()).all()
    recommend_counts = {p.id: _restaurant_recommend_count(p.id) for p in posts}
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-3xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <a href="/" class="text-gray-400 hover:text-teal-600 text-sm font-bold mb-6 inline-block">← 홈</a>
            <h1 class="text-2xl md:text-3xl font-black text-gray-900 mb-2">전국맛집요청</h1>
            <p class="text-gray-500 text-sm mb-6">사진·업체정보·메뉴를 등록해 보세요. 추천 100개 이상 시 전국 어디든 포장 가능하면 당일 배송 소싱을 진행합니다.</p>
            <a href="/board/restaurant-request/write" class="inline-block mb-6 px-5 py-3 bg-teal-600 text-white rounded-xl text-sm font-black hover:bg-teal-700 transition">글쓰기</a>
            <div class="space-y-4">
                {% for p in posts %}
                <a href="/board/restaurant-request/{{ p.id }}" class="block bg-white rounded-2xl border border-gray-100 p-4 shadow-sm hover:shadow-md transition text-left">
                    <div class="flex gap-4">
                        {% if p.image_url %}<img src="{{ p.image_url }}" class="w-24 h-24 rounded-xl object-cover shrink-0" alt="">{% endif %}
                        <div class="flex-1 min-w-0">
                            <p class="font-black text-gray-800 truncate">{{ p.store_name }}</p>
                            <p class="text-[10px] text-gray-400 mt-1">{{ p.created_at.strftime('%Y.%m.%d') if p.created_at else '' }}</p>
                            <p class="text-sm text-gray-600 mt-1 line-clamp-2">{{ (p.store_info or p.menu or '')[:80] }}...</p>
                            <span class="inline-block mt-2 text-teal-600 text-xs font-black">👍 추천 {{ recommend_counts.get(p.id, 0) }}개</span>
                            {% if recommend_counts.get(p.id, 0) >= 100 %}
                            <span class="ml-2 text-amber-600 text-[10px] font-black">✓ 100개 달성 · 당일배송 소싱 대상</span>
                            {% endif %}
                        </div>
                    </div>
                </a>
                {% else %}
                <div class="bg-gray-50 rounded-2xl p-12 text-center text-gray-500">등록된 글이 없습니다.</div>
                {% endfor %}
            </div>
        </div>
        """ + FOOTER_HTML,
        posts=posts, recommend_counts=recommend_counts
    )


@app.route('/board/restaurant-request/write', methods=['GET', 'POST'])
@login_required
def board_restaurant_request_write():
    """전국맛집요청 글쓰기 폼"""
    if request.method == 'POST':
        store_name = (request.form.get('store_name') or '').strip()
        if not store_name:
            flash("업체명을 입력해 주세요.")
            return redirect(url_for('board_restaurant_request_write'))
        store_info = (request.form.get('store_info') or '').strip()
        menu = (request.form.get('menu') or '').strip()
        img_url = save_board_image(request.files.get('image'))
        r = RestaurantRequest(
            user_id=current_user.id,
            user_name=current_user.name,
            store_name=store_name,
            store_info=store_info or None,
            menu=menu or None,
            image_url=img_url
        )
        db.session.add(r)
        db.session.commit()
        flash("등록되었습니다.")
        return redirect(url_for('board_restaurant_request_detail', rid=r.id))
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-2xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <a href="/board/restaurant-request" class="text-gray-400 hover:text-teal-600 text-sm font-bold mb-6 inline-block">← 목록</a>
            <h1 class="text-2xl font-black text-gray-900 mb-6">전국맛집요청 글쓰기</h1>
            <form method="POST" action="/board/restaurant-request/write" enctype="multipart/form-data" class="space-y-4">
                <div><label class="block text-[10px] text-gray-500 uppercase mb-1">업체명 *</label><input type="text" name="store_name" required class="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-bold" placeholder="맛집 이름"></div>
                <div><label class="block text-[10px] text-gray-500 uppercase mb-1">업체 정보 (주소·연락처 등)</label><textarea name="store_info" rows="3" class="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-bold" placeholder="업체 정보"></textarea></div>
                <div><label class="block text-[10px] text-gray-500 uppercase mb-1">메뉴</label><textarea name="menu" rows="4" class="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-bold" placeholder="메뉴·대표 요리"></textarea></div>
                <div><label class="block text-[10px] text-gray-500 uppercase mb-1">사진</label><input type="file" name="image" accept="image/*" class="w-full text-sm p-3 rounded-xl border border-gray-200"></div>
                <button type="submit" class="w-full py-4 bg-teal-600 text-white rounded-xl font-black hover:bg-teal-700 transition">등록</button>
            </form>
        </div>
        """ + FOOTER_HTML
    )


@app.route('/board/restaurant-request/<int:rid>')
def board_restaurant_request_detail(rid):
    """전국맛집요청 상세 (추천 버튼: 로그인 1인 1추천)"""
    p = RestaurantRequest.query.filter_by(id=rid, is_hidden=False).first_or_404()
    rec_count = _restaurant_recommend_count(p.id)
    user_recommended = _user_recommended_restaurant(p.id)
    show_100_notice = rec_count >= 100
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-3xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <a href="/board/restaurant-request" class="text-gray-400 hover:text-teal-600 text-sm font-bold mb-6 inline-block">← 목록</a>
            <div class="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
                {% if p.image_url %}<img src="{{ p.image_url }}" class="w-full max-h-80 object-cover rounded-xl mb-4" alt="">{% endif %}
                <h1 class="text-xl font-black text-gray-900 mb-2">{{ p.store_name }}</h1>
                <p class="text-[10px] text-gray-400 mb-4">{{ p.created_at.strftime('%Y.%m.%d %H:%M') if p.created_at else '' }} · {{ p.user_name or '비회원' }}</p>
                {% if p.store_info %}<div class="mb-4"><p class="text-[10px] text-gray-500 uppercase mb-1">업체정보</p><p class="text-gray-700 text-sm whitespace-pre-wrap">{{ p.store_info }}</p></div>{% endif %}
                {% if p.menu %}<div class="mb-4"><p class="text-[10px] text-gray-500 uppercase mb-1">메뉴</p><p class="text-gray-700 text-sm whitespace-pre-wrap">{{ p.menu }}</p></div>{% endif %}
                <div class="flex items-center gap-4 pt-4 border-t border-gray-100">
                    <span class="text-teal-600 font-black">👍 추천 {{ rec_count }}개</span>
                    {% if current_user.is_authenticated %}
                    {% if user_recommended %}
                    <span class="text-gray-400 text-sm">이미 추천하셨습니다.</span>
                    {% else %}
                    <form action="/board/restaurant-request/{{ p.id }}/recommend" method="POST" class="inline">
                        <button type="submit" class="px-4 py-2 bg-teal-600 text-white rounded-xl text-xs font-black hover:bg-teal-700 transition">추천하기</button>
                    </form>
                    {% endif %}
                    {% else %}
                    <span class="text-gray-400 text-sm">로그인 후 추천할 수 있습니다.</span>
                    {% endif %}
                </div>
                {% if show_100_notice %}
                <div class="mt-6 p-4 bg-amber-50 border border-amber-200 rounded-xl text-amber-800 text-sm font-bold">
                    ✓ 추천 100개 달성 · 전국 어디맛집이든 포장만 가능하다면 상품 소싱 후 당일 배송을 진행합니다.
                </div>
                {% endif %}
            </div>
        </div>
        """ + FOOTER_HTML,
        p=p, rec_count=rec_count, user_recommended=user_recommended, show_100_notice=show_100_notice
    )


@app.route('/board/restaurant-request/<int:rid>/recommend', methods=['POST'])
@login_required
def board_restaurant_request_recommend(rid):
    """추천 (1인 1개)"""
    post = RestaurantRequest.query.filter_by(id=rid, is_hidden=False).first_or_404()
    existing = RestaurantRecommend.query.filter_by(restaurant_request_id=rid, user_id=current_user.id).first()
    if existing:
        flash("이미 추천하셨습니다.")
    else:
        db.session.add(RestaurantRecommend(restaurant_request_id=rid, user_id=current_user.id))
        db.session.commit()
        flash("추천되었습니다.")
    return redirect(url_for('board_restaurant_request_detail', rid=rid))


@app.route('/board/partnership', methods=['GET', 'POST'])
def board_partnership():
    """제휴문의 목록 및 작성 (비밀글)"""
    if request.method == 'POST':
        partnership_type = (request.form.get('partnership_type') or '').strip()
        content = (request.form.get('content') or '').strip()
        is_secret = request.form.get('is_secret') in ('1', 'on', 'yes')
        user_id = current_user.id if current_user.is_authenticated else None
        user_name = current_user.name if current_user.is_authenticated else (request.form.get('writer_name') or '비회원')[:50]
        r = PartnershipInquiry(
            user_id=user_id,
            user_name=user_name,
            partnership_type=partnership_type or None,
            content=content or None,
            is_secret=is_secret
        )
        db.session.add(r)
        db.session.commit()
        flash("등록되었습니다.")
        return redirect(url_for('board_partnership'))
    posts = PartnershipInquiry.query.filter_by(is_hidden=False).order_by(PartnershipInquiry.id.desc()).all()
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-3xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <a href="/" class="text-gray-400 hover:text-teal-600 text-sm font-bold mb-6 inline-block">← 홈</a>
            <h1 class="text-2xl md:text-3xl font-black text-gray-900 mb-2">제휴문의</h1>
            <p class="text-gray-500 text-sm mb-6">제휴 종류·아이템 등을 작성해 주세요. 비밀글로 등록됩니다.</p>
            <div class="mb-6 p-4 bg-gray-50 rounded-2xl border border-gray-100">
                <form method="POST" action="/board/partnership" class="space-y-4">
                    <div><label class="block text-[10px] text-gray-500 uppercase mb-1">제휴 종류</label><input type="text" name="partnership_type" placeholder="예: 로컬맛집, 배달업체" class="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-bold"></div>
                    <div><label class="block text-[10px] text-gray-500 uppercase mb-1">내용 (아이템·문의사항)</label><textarea name="content" rows="4" placeholder="제휴 희망 아이템, 연락처 등" class="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-bold"></textarea></div>
                    <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="is_secret" value="1" checked class="rounded"> <span class="text-sm font-bold">비밀글로 등록</span></label>
                    <button type="submit" class="px-5 py-3 bg-teal-600 text-white rounded-xl text-sm font-black hover:bg-teal-700 transition">등록</button>
                </form>
            </div>
            <div class="space-y-3">
                {% for p in posts %}
                <a href="/board/partnership/{{ p.id }}" class="block bg-white rounded-2xl border border-gray-100 p-4 shadow-sm hover:shadow-md transition text-left">
                    <p class="font-black text-gray-800">{% if p.is_secret %}🔒 비밀글{% else %}제휴 문의{% endif %} · {{ p.partnership_type or '-' }}</p>
                    <p class="text-[10px] text-gray-400 mt-1">{{ p.created_at.strftime('%Y.%m.%d') if p.created_at else '' }} · {{ p.user_name or '비회원' }}</p>
                </a>
                {% else %}
                <div class="bg-gray-50 rounded-2xl p-12 text-center text-gray-500">등록된 글이 없습니다.</div>
                {% endfor %}
            </div>
        </div>
        """ + FOOTER_HTML,
        posts=posts
    )


@app.route('/board/partnership/<int:pid>')
def board_partnership_detail(pid):
    """제휴문의 상세 (비밀글은 본인·관리자만)"""
    p = PartnershipInquiry.query.filter_by(id=pid, is_hidden=False).first_or_404()
    can_view = not p.is_secret or (current_user.is_authenticated and (p.user_id == current_user.id or current_user.is_admin))
    if not can_view:
        flash("비밀글은 작성자만 볼 수 있습니다.")
        return redirect(url_for('board_partnership'))
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-3xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <a href="/board/partnership" class="text-gray-400 hover:text-teal-600 text-sm font-bold mb-6 inline-block">← 목록</a>
            <div class="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
                <p class="text-[10px] text-gray-500 uppercase mb-1">제휴 종류</p>
                <p class="font-black text-gray-900 mb-4">{{ p.partnership_type or '-' }}</p>
                <p class="text-[10px] text-gray-400 mb-2">{{ p.created_at.strftime('%Y.%m.%d %H:%M') if p.created_at else '' }} · {{ p.user_name or '비회원' }}</p>
                <p class="text-[10px] text-gray-500 uppercase mb-1">내용</p>
                <p class="text-gray-700 text-sm whitespace-pre-wrap">{{ p.content or '' }}</p>
            </div>
        </div>
        """ + FOOTER_HTML,
        p=p
    )


# [추가] 무한 스크롤을 위한 상품 데이터 제공 API
@app.route('/api/category_products/<string:cat_name>')
def api_category_products(cat_name):
    """무한 스크롤용 데이터 제공 API (30개 단위)"""
    page = int(request.args.get('page', 1))
    per_page = 30
    offset = (page - 1) * per_page
    
    query = Product.query.filter_by(is_active=True)
    if cat_name == '최신상품':
        query = query.order_by(Product.id.desc())
    elif cat_name == '오늘마감':
        today_end = datetime.now().replace(hour=23, minute=59, second=59)
        query = query.filter(Product.deadline > datetime.now(), Product.deadline <= today_end).order_by(Product.deadline.asc())
    else:
        query = query.filter_by(category=cat_name).order_by(Product.id.desc())
    
    products = query.offset(offset).limit(per_page).all()
    
    res_data = []
    for p in products:
        res_data.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "image_url": p.image_url,
            "description": p.description or "",
            "stock": p.stock,
            "is_sold_out": (p.deadline and p.deadline < datetime.now()) or p.stock <= 0,
            "deadline": p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else ""
        })
    return jsonify(res_data)
@app.route('/category/<string:cat_name>')
def category_view(cat_name):
    """카테고리별 상품 목록 뷰 (무한 스크롤, 30개 단위, 스크롤 시 1초 대기 후 추가 로딩)"""
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    cat = None
    limit_num = 30
    
    if cat_name == '최신상품':
        products = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).limit(limit_num).all()
        display_name = "✨ 최신 상품"
    elif cat_name == '오늘마감':
        today_end = datetime.now().replace(hour=23, minute=59, second=59)
        products = Product.query.filter(Product.is_active == True, Product.deadline > datetime.now(), Product.deadline <= today_end).order_by(Product.deadline.asc()).limit(limit_num).all()
        display_name = "🔥 오늘 마감 임박!"
    else:
        cat = Category.query.filter_by(name=cat_name).first_or_404()
        user_grade = (getattr(current_user, 'member_grade', 1) or 1) if current_user.is_authenticated else 1
        if getattr(cat, 'min_member_grade', None) is not None and user_grade < cat.min_member_grade:
            abort(404)
        products = Product.query.filter_by(category=cat_name, is_active=True).order_by(order_logic, Product.id.desc()).limit(limit_num).all()
        display_name = f"{cat_name} 상품 리스트"

    # 하단 추천 섹션 데이터 (등급별 카테고리)
    grade = (getattr(current_user, 'member_grade', 1) or 1) if current_user.is_authenticated else 1
    latest_all = Product.query.filter(Product.is_active == True, Product.category != cat_name).order_by(Product.id.desc()).limit(10).all()
    recommend_cats = categories_for_member_grade(grade).filter(Category.name != cat_name).limit(3).all()
    cat_previews = {c: Product.query.filter_by(category=c.name, is_active=True).limit(4).all() for c in recommend_cats}

    content = """
    <div class="max-w-7xl mx-auto px-4 md:px-6 py-20 text-left">
        <div class="mb-16 text-left">
            <h2 class="text-3xl md:text-5xl text-gray-800 font-black text-left">{{ display_name }}</h2>
            {% if cat and cat.description %}<p class="text-gray-400 font-bold mt-4 text-base md:text-xl text-left">{{ cat.description }}</p>{% endif %}
        </div>
        
        <div id="product-grid" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 md:gap-10 text-left mb-12">
            {% for p in products %}
            <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-2xl {% if p.stock <= 0 %}sold-out{% endif %}">
                
                {% if p.description %}
                <div class="absolute top-4 left-0 z-20">
                    <span class="px-3 py-1.5 text-[9px] md:text-[11px] font-black text-white shadow-md rounded-r-full 
                        {% if '당일' in p.description %} bg-red-600 
                        {% elif '+1' in p.description %} bg-blue-600 
                        {% elif '+2' in p.description %} bg-emerald-600 
                        {% else %} bg-gray-600 {% endif %}">
                        <i class="fas fa-truck-fast mr-1"></i> {{ p.description }}
                    </span>
                </div>
                {% endif %}

                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                    <img src="{{ p.image_url }}" loading="lazy" class="w-full h-full object-cover p-4 md:p-8">
                </a>
                <div class="p-5 md:p-10 flex flex-col flex-1 text-left">
                    <a href="/product/{{p.id}}">
                        <h3 class="font-black text-gray-800 text-sm md:text-lg truncate mb-2 text-left">{{ p.name }}</h3>
                    </a>
                    
                    <p class="text-[10px] md:text-xs text-gray-400 font-bold mb-3">{{ p.spec or '일반' }}</p>

                    <div class="mt-auto flex justify-between items-center text-left">
                        <span class="text-base md:text-2xl font-black text-teal-600 text-left">{{ "{:,}".format(p.price) }}원</span>
                        <button onclick="addToCart('{{p.id}}')" class="bg-teal-600 w-8 h-8 md:w-12 md:h-12 rounded-full text-white shadow-lg flex items-center justify-center transition active:scale-90 text-center">
                            <i class="fas fa-plus text-[10px] md:text-base"></i>
                        </button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>

        <div id="load-more-trigger" class="w-full min-h-[100px] flex flex-col items-center justify-center py-10">
            <div id="spinner" class="w-10 h-10 border-4 border-teal-100 border-t-teal-600 rounded-full animate-spin hidden"></div>
            <div id="end-message" class="hidden text-gray-300 font-black text-lg py-4 w-full text-center">마지막 상품입니다. 😊</div>
        </div>

        <hr class="border-gray-100 mb-24">

        <div class="grid grid-cols-1 md:grid-cols-3 gap-10 text-left mb-24">
            {% for c_info, c_prods in cat_previews.items() %}
            <div class="bg-gray-50 p-6 md:p-8 rounded-[3rem] border border-gray-100 shadow-inner text-left">
                <h3 class="text-xl font-black mb-6 flex justify-between items-center text-left">
                    {{ c_info.name }}
                    <a href="/category/{{ c_info.name }}" class="text-xs text-gray-400 font-bold hover:text-teal-600">전체보기 ></a>
                </h3>
                <div class="grid grid-cols-2 gap-4">
                    {% for cp in c_prods %}
                    <div class="bg-white p-3 rounded-2xl shadow-sm relative flex flex-col">
                        {% if cp.description %}
                        <div class="absolute top-2 left-0 z-20">
                            <span class="px-2 py-1 text-[7px] md:text-[9px] font-black text-white shadow-sm rounded-r-full 
                                {% if '당일' in cp.description %} bg-red-600 
                                {% elif '+1' in cp.description %} bg-blue-600 
                                {% elif '+2' in cp.description %} bg-emerald-600 
                                {% else %} bg-gray-600 {% endif %}">
                                {{ cp.description }}
                            </span>
                        </div>
                        {% endif %}

                        <a href="/product/{{ cp.id }}" class="block mb-2">
                            <img src="{{ cp.image_url }}" class="w-full aspect-square object-contain rounded-xl p-1">
                        </a>
                        <div class="px-1">
                            <p class="text-[10px] md:text-xs font-black text-gray-800 truncate">{{ cp.name }}</p>
                            <p class="text-[8px] md:text-[10px] text-gray-400 font-bold mb-1">{{ cp.spec or '일반' }}</p>
                            <p class="text-xs md:text-sm font-black text-teal-600">{{ "{:,}".format(cp.price) }}원</p>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="flex justify-center mt-24">
            <a href="/" class="bg-gray-800 text-white px-12 py-5 rounded-full font-black shadow-xl hover:bg-black transition active:scale-95 text-center">
                <i class="fas fa-home mr-2"></i> 메인화면으로 이동하기
            </a>
        </div>
    </div>

    <script>
    let page = 1;
    let loading = false;
    let hasMore = true;
    const catName = "{{ cat_name }}";

    async function loadMore() {
        if (loading || !hasMore) return;
        loading = true;
        document.getElementById('spinner').classList.remove('hidden');

        page++;
        try {
            const res = await fetch(`/api/category_products/${encodeURIComponent(catName)}?page=${page}&per_page=30`);
            const data = await res.json();

            if (!data || data.length === 0) {
                hasMore = false;
                document.getElementById('end-message').classList.remove('hidden');
                document.getElementById('spinner').classList.add('hidden');
                return;
            }

            const grid = document.getElementById('product-grid');
            data.forEach(p => {
                const soldOutClass = p.is_sold_out ? 'sold-out' : '';
                
                // ✅ 배송 일정 배지 색상 결정 로직 (JS)
                let badgeColor = 'bg-gray-600';
                if (p.description.includes('당일')) badgeColor = 'bg-red-600';
                else if (p.description.includes('+1')) badgeColor = 'bg-blue-600';
                else if (p.description.includes('+2')) badgeColor = 'bg-emerald-600';

                // ✅ 배송 일정 HTML
                const deliveryBadge = p.description ? `
                    <div class="absolute top-4 left-0 z-20">
                        <span class="px-3 py-1.5 text-[9px] md:text-[11px] font-black text-white shadow-md rounded-r-full ${badgeColor}">
                            <i class="fas fa-truck-fast mr-1"></i> ${p.description}
                        </span>
                    </div>` : '';

                const html = `
                    <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-2xl ${soldOutClass}">
                        ${deliveryBadge}
                        <a href="/product/${p.id}" class="relative aspect-square block bg-white overflow-hidden">
                            <img src="${p.image_url}" loading="lazy" class="w-full h-full object-cover p-4 md:p-10">
                        </a>
                        <div class="p-5 md:p-10 flex flex-col flex-1 text-left">
                            <a href="/product/${p.id}">
                                <h3 class="font-black text-gray-800 text-sm md:text-lg truncate mb-2 text-left">${p.name}</h3>
                            </a>
                            <div class="mt-auto flex justify-between items-center text-left">
                                <span class="text-base md:text-2xl font-black text-teal-600 text-left">${p.price.toLocaleString()}원</span>
                                <button onclick="addToCart('${p.id}')" class="bg-teal-600 w-8 h-8 md:w-12 md:h-12 rounded-full text-white shadow-lg flex items-center justify-center transition active:scale-90">
                                    <i class="fas fa-plus text-[10px] md:text-base"></i>
                                </button>
                            </div>
                        </div>
                    </div>`;
                grid.insertAdjacentHTML('beforeend', html);
            });

            if (data.length < 30) {
                hasMore = false;
                document.getElementById('end-message').classList.remove('hidden');
            }
        } catch (e) { console.error("Infinity Scroll Error:", e); }
        finally {
            loading = false;
            if (hasMore) document.getElementById('spinner').classList.add('hidden');
        }
    }

    let scrollDebounceTimer = null;
    const observer = new IntersectionObserver((entries) => {
        if (!entries[0].isIntersecting) return;
        if (scrollDebounceTimer) clearTimeout(scrollDebounceTimer);
        scrollDebounceTimer = setTimeout(() => { loadMore(); scrollDebounceTimer = null; }, 1000);
    }, { threshold: 0.1, rootMargin: '300px' });

    observer.observe(document.getElementById('load-more-trigger'));
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, **locals())

@app.route('/api/product_reviews')
def api_product_reviews():
    """상품 상세 구매후기 더보기용 API (페이지당 5개)"""
    category_id = request.args.get('category_id', type=int)
    product_id = request.args.get('product_id', type=int)
    page = max(1, int(request.args.get('page', 1)))
    per_page = 5
    offset = (page - 1) * per_page
    if category_id is not None:
        q = Review.query.filter_by(category_id=category_id).order_by(Review.created_at.desc())
    elif product_id is not None:
        q = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc())
    else:
        return jsonify([])
    reviews = q.offset(offset).limit(per_page).all()
    return jsonify([{
        "id": r.id,
        "image_url": r.image_url or "",
        "user_name": (r.user_name or "")[:1] + "**",
        "created_at": r.created_at.strftime("%Y.%m.%d") if r.created_at else "",
        "content": r.content or "",
    } for r in reviews])


@app.route('/product/<int:pid>')
def product_detail(pid):
    """상품 상세 정보 페이지 (최근등록상품 복구 및 추천 카테고리 추가 완료본)"""
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    detail_images = p.detail_image_url.split(',') if p.detail_image_url else []
    cat_info = Category.query.filter_by(name=p.category).first()
    
    # 1. 연관 추천 상품: 키워드(상품명 첫 단어) 기반
    keyword = p.name.split()[0] if p.name else ""
    keyword_recommends = Product.query.filter(
        Product.name.contains(keyword),
        Product.id != pid,
        Product.is_active == True,
        Product.stock > 0
    ).limit(10).all()

    # 2. 최근 등록 상품 10개 (이 데이터가 정상적으로 전달되어야 합니다)
    latest_all = Product.query.filter(Product.is_active == True, Product.id != pid).order_by(Product.id.desc()).limit(10).all()
    
    # 3. 하단 노출용 추천 카테고리 3개 및 미리보기 상품
    recommend_cats_detail = Category.query.filter(Category.name != p.category).order_by(Category.order.asc()).limit(3).all()
    cat_previews_detail = {c: Product.query.filter_by(category=c.name, is_active=True).limit(4).all() for c in recommend_cats_detail}
    
    # 4. 리뷰: 해당 상품의 판매자(카테고리)별로 묶어서 노출, 5개만 초기 로딩·더보기 5개씩
    if cat_info:
        review_base = Review.query.filter_by(category_id=cat_info.id).order_by(Review.created_at.desc())
    else:
        review_base = Review.query.filter_by(product_id=pid).order_by(Review.created_at.desc())
    reviews_total_count = review_base.count()
    product_reviews = review_base.limit(5).all()
    reviews_has_more = reviews_total_count > 5

    content = """
    <div class="max-w-5xl mx-auto px-0 md:px-6 pb-16 font-black text-left">
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-0 md:gap-16 items-start">
            <div class="relative w-full aspect-square bg-white overflow-hidden md:rounded-[3rem] md:shadow-xl border-b md:border border-gray-100">
                {% if p.description %}
                <div class="absolute top-6 left-0 z-20">
                    <span class="px-5 py-2 text-xs md:text-sm font-black text-white shadow-xl rounded-r-full 
                        {% if '당일' in p.description %} bg-red-600 
                        {% elif '+1' in p.description %} bg-blue-600 
                        {% elif '+2' in p.description %} bg-emerald-600 
                        {% else %} bg-gray-600 {% endif %}">
                        <i class="fas fa-truck-fast mr-2"></i> {{ p.description }}
                    </span>
                </div>
                {% endif %}

                <img src="{{ p.image_url }}" class="w-full h-full object-contain p-6 md:p-12" loading="lazy">
                
                {% if is_expired or p.stock <= 0 %}
                <div class="absolute inset-0 bg-black/50 flex items-center justify-center backdrop-blur-[2px]">
                    <span class="text-white font-black text-2xl border-4 border-white px-8 py-3 rounded-2xl rotate-[-5deg]">판매마감</span>
                </div>
                {% endif %}
            </div>

            <div class="p-6 md:p-0 flex flex-col justify-start">
                <nav class="flex items-center gap-2 text-[10px] md:text-xs text-gray-400 mb-6 uppercase tracking-[0.2em] font-bold">
                    <a href="/" class="hover:text-teal-600">Home</a>
                    <i class="fas fa-chevron-right text-[8px]"></i>
                    <a href="/category/{{ p.category }}" class="hover:text-teal-600 text-teal-600">{{ p.category }}</a>
                </nav>

                <h2 class="text-3xl md:text-5xl text-gray-900 mb-4 leading-tight tracking-tighter break-keep">
                    {{ p.name }}
                    {% if p.badge %}
                    <span class="block mt-2 text-orange-500 text-sm md:text-lg font-black italic tracking-normal">
                        # {{ p.badge }}
                    </span>
                    {% endif %}
                </h2>

                <div class="flex items-baseline gap-2 mb-10">
                    <span class="text-4xl md:text-6xl text-teal-600 font-black italic tracking-tighter">{{ "{:,}".format(p.price) }}</span>
                    <span class="text-xl text-gray-400 font-bold">원</span>
                </div>

                <div class="grid grid-cols-2 gap-3 mb-10">
                    <div class="bg-gray-50 p-5 rounded-2xl border border-gray-100 shadow-sm">
                        <p class="text-[9px] text-gray-400 uppercase mb-1 font-black">Standard</p>
                        <p class="text-sm md:text-base font-black text-gray-700">{{ p.spec or '기본규격' }}</p>
                    </div>
                    <div class="bg-gray-50 p-5 rounded-2xl border border-gray-100 shadow-sm">
                        <p class="text-[9px] text-gray-400 uppercase mb-1 font-black">Stock Status</p>
                        <p class="text-sm md:text-base font-black text-gray-700">{{ p.stock }}개 남음</p>
                    </div>
                    <div class="bg-blue-50 p-5 rounded-2xl border border-blue-100 col-span-2 shadow-sm">
                        <p class="text-[9px] text-blue-400 uppercase mb-1 font-black">Direct Delivery (송도전용)</p>
                        <p class="text-sm md:text-base font-black text-blue-700">
                            <i class="fas fa-truck-fast mr-2"></i>바구니삼촌 {{ p.description }} 내 직접 배송
                        </p>
                    </div>
                </div>

                <div class="bg-gray-50 p-4 rounded-2xl mb-6 border border-gray-100">
                    <p class="text-[11px] text-gray-500 leading-relaxed font-bold">
                        <i class="fas fa-info-circle mr-1"></i> 바구니삼촌은 구매대행형 서비스로서 본 상품의 실제 판매처와 고객을 연결하고 결제 및 배송 전반을 책임 관리합니다.
                    </p>
                </div>
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-teal-600 text-white py-5 md:py-7 rounded-[2rem] font-black text-xl md:text-2xl shadow-2xl hover:bg-teal-700 transition active:scale-95 flex items-center justify-center gap-2">
                    <i class="fas fa-shopping-basket"></i> 물건 담기
                </button>
                {% else %}
                <button class="w-full bg-gray-200 text-gray-400 py-5 md:py-7 rounded-[2rem] font-black text-xl md:text-2xl cursor-not-allowed italic" disabled>판매가 마감되었습니다</button>
                {% endif %}
            </div>
        </div>

        <div class="mt-20 md:mt-32">
            <div class="sticky top-16 md:top-20 bg-white/90 backdrop-blur-md z-30 border-y border-gray-100 flex justify-around mb-12 shadow-sm">
                <a href="#details" class="py-5 px-4 text-sm font-black text-gray-800 border-b-4 border-teal-600 transition-all">상세정보</a>
                <a href="#reviews" class="py-5 px-4 text-sm font-black text-gray-400 hover:text-orange-500 transition-all">구매후기 ({{ reviews_total_count }})</a>
                <a href="#related" class="py-5 px-4 text-sm font-black text-gray-400 hover:text-blue-500 transition-all">추천상품</a>
            </div>

            <div id="details" class="space-y-12 px-4 md:px-0">
                <div class="bg-teal-50/50 p-10 md:p-20 rounded-[2.5rem] md:rounded-[4.5rem] text-center border-none shadow-inner">
                    <i class="fas fa-quote-left text-teal-200 text-4xl mb-6"></i>
                    <p class="text-xl md:text-3xl font-black text-gray-800 leading-relaxed break-keep">
                        {{ p.origin or '바구니삼촌이 꼼꼼하게 검수하여\\n송도 이웃에게 보내드리는 믿을 수 있는 상품입니다.' }}
                    </p>
                    <i class="fas fa-quote-right text-teal-200 text-4xl mt-6"></i>
                </div>
                <div class="flex flex-col gap-0 max-w-4xl mx-auto">
                    {% if detail_images %}
                        {% for img in detail_images %}
                        <img src="{{ img.strip() }}" class="w-full shadow-sm" loading="lazy" onerror="this.style.display='none'">
                        {% endfor %}
                    {% else %}
                        <img src="{{ p.image_url }}" class="w-full rounded-3xl opacity-60 grayscale p-10">
                    {% endif %}
                </div>
            </div>
        </div>

        <div id="reviews" class="mt-40 px-4 md:px-0">
            <h3 class="text-2xl md:text-4xl font-black text-gray-900 mb-12 flex items-center gap-4 tracking-tighter">
                <span class="w-2 h-10 bg-orange-400 rounded-full"></span> 📸 생생한 구매 후기
            </h3>
            {% if product_reviews %}
            <div id="reviews-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4">
                {% for r in product_reviews %}
                <div class="bg-white p-4 rounded-2xl border border-gray-100 shadow-sm flex flex-col sm:flex-row gap-4 hover:shadow-md transition-all">
                    {% if r.image_url %}<img src="{{ r.image_url }}" class="w-full sm:w-20 h-20 rounded-xl object-cover flex-shrink-0 bg-gray-50" loading="lazy" alt="">{% else %}<div class="w-full sm:w-20 h-20 rounded-xl bg-gray-100 flex items-center justify-center text-gray-400 text-[10px] font-bold flex-shrink-0">사진 없음</div>{% endif %}
                    <div class="flex-1 text-left min-w-0">
                        <div class="flex items-center justify-between mb-1.5 gap-2">
                            <span class="text-[10px] font-black text-gray-800 truncate">{{ r.user_name[:1] }}**님</span>
                            <span class="text-[9px] text-gray-300 font-bold shrink-0">{{ r.created_at.strftime('%Y.%m.%d') if r.created_at else '' }}</span>
                        </div>
                        <p class="text-[11px] font-bold text-gray-600 leading-relaxed line-clamp-4">{{ r.content }}</p>
                    </div>
                </div>
                {% endfor %}
            </div>
            <div id="reviews-load-more-wrap" class="mt-10 text-center {% if not reviews_has_more %}hidden{% endif %}">
                <button type="button" id="reviews-load-more-btn" class="bg-orange-500 hover:bg-orange-600 text-white font-black py-4 px-10 rounded-2xl shadow-lg transition">
                    더보기 ({{ reviews_total_count - 5 }}개 더)
                </button>
            </div>
            <div id="reviews-end-msg" class="hidden mt-8 text-center text-gray-400 text-sm font-bold">마지막 후기입니다.</div>
            {% if reviews_has_more %}
            <script>
            (function(){
                var reviewsTotal = {{ reviews_total_count }};
                var reviewsLoaded = 5;
                var reviewPage = 2;
                var categoryId = {{ cat_info.id if cat_info else 'null' }};
                var productId = {{ p.id }};
                var btn = document.getElementById('reviews-load-more-btn');
                var wrap = document.getElementById('reviews-load-more-wrap');
                var endMsg = document.getElementById('reviews-end-msg');
                var grid = document.getElementById('reviews-grid');
                function updateBtnText(){ var left = reviewsTotal - reviewsLoaded; btn.textContent = left > 0 ? '더보기 (' + left + '개 더)' : '더보기'; }
                btn.addEventListener('click', function(){
                    if (btn.disabled) return;
                    btn.disabled = true;
                    var url = '/api/product_reviews?page=' + reviewPage + '&per_page=5';
                    if (categoryId != null) url += '&category_id=' + categoryId; else url += '&product_id=' + productId;
                    fetch(url).then(function(r){ return r.json(); }).then(function(data){
                        data.forEach(function(r){
                            var imgPart = r.image_url ? '<img src="' + r.image_url.replace(/"/g,'&quot;') + '" class="w-full sm:w-20 h-20 rounded-xl object-cover flex-shrink-0 bg-gray-50" loading="lazy" alt="">' : '<div class="w-full sm:w-20 h-20 rounded-xl bg-gray-100 flex items-center justify-center text-gray-400 text-[10px] font-bold flex-shrink-0">사진 없음</div>';
                            var el = document.createElement('div');
                            el.className = 'bg-white p-4 rounded-2xl border border-gray-100 shadow-sm flex flex-col sm:flex-row gap-4 hover:shadow-md transition-all';
                            el.innerHTML = imgPart + '<div class="flex-1 text-left min-w-0"><div class="flex items-center justify-between mb-1.5 gap-2"><span class="text-[10px] font-black text-gray-800 truncate">' + (r.user_name || '') + '님</span><span class="text-[9px] text-gray-300 font-bold shrink-0">' + (r.created_at || '') + '</span></div><p class="text-[11px] font-bold text-gray-600 leading-relaxed line-clamp-4">' + (r.content || '').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</p></div>';
                            grid.appendChild(el);
                        });
                        reviewsLoaded += data.length;
                        reviewPage++;
                        updateBtnText();
                        if (reviewsLoaded >= reviewsTotal || data.length < 5){ wrap.classList.add('hidden'); endMsg.classList.remove('hidden'); }
                        else { btn.disabled = false; }
                    }).catch(function(){ btn.disabled = false; });
                });
            })();
            </script>
            {% endif %}
            {% else %}
            <div class="py-24 text-center bg-gray-50 rounded-[3rem] border-2 border-dashed border-gray-200">
                <p class="text-gray-300 font-black text-lg">아직 등록된 후기가 없습니다. 첫 후기를 남겨보세요! 😊</p>
            </div>
            {% endif %}
        </div>

        <div id="related" class="mt-40">
            {% if keyword_recommends %}
            <div class="border-t border-gray-100 pt-24">
                <h3 class="font-black text-2xl md:text-4xl mb-12 flex items-center gap-4 tracking-tighter px-4 md:px-0">
                    <span class="w-2 h-10 bg-teal-500 rounded-full"></span> ⭐ 연관 추천 상품
                </h3>
                <div class="horizontal-scroll no-scrollbar px-4 md:px-0">
                    {% for rp in keyword_recommends %}
                    <a href="/product/{{rp.id}}" class="group flex-shrink-0 w-44 md:w-64 relative">
                        {% if rp.description %}
                        <div class="absolute top-2 left-0 z-20">
                            <span class="px-2 py-1 text-[7px] md:text-[10px] font-black text-white shadow-sm rounded-r-full 
                                {% if '당일' in rp.description %} bg-red-600 {% elif '+1' in rp.description %} bg-blue-600 {% elif '+2' in rp.description %} bg-emerald-600 {% else %} bg-gray-600 {% endif %}">
                                {{ rp.description }}
                            </span>
                        </div>
                        {% endif %}
                        <div class="bg-white rounded-[2rem] border border-gray-100 p-4 shadow-sm transition hover:shadow-2xl hover:-translate-y-2 text-left h-full flex flex-col">
                            <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-4 rounded-2xl bg-gray-50 p-2">
                            <p class="text-xs md:text-sm font-black text-gray-800 truncate mb-1">{{ rp.name }}</p>
                            <p class="text-[9px] md:text-[11px] text-gray-400 font-bold mb-3">{{ rp.spec or '일반' }}</p>
                            <p class="text-sm md:text-lg font-black text-teal-600 mt-auto">{{ "{:,}".format(rp.price) }}원</p>
                        </div>
                    </a>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
        </div>

        {% if latest_all %}
        <div class="mt-20">
            <h3 class="font-black text-2xl md:text-4xl mb-12 flex items-center gap-4 tracking-tighter px-4 md:px-0">
                <span class="w-2 h-10 bg-blue-500 rounded-full"></span> ✨ 최근 등록 상품
            </h3>
            <div class="horizontal-scroll no-scrollbar px-4 md:px-0">
                {% for rp in latest_all %}
                <a href="/product/{{rp.id}}" class="group flex-shrink-0 w-44 md:w-64 relative">
                    {% if rp.description %}
                    <div class="absolute top-2 left-0 z-20">
                        <span class="px-2 py-1 text-[7px] md:text-[10px] font-black text-white shadow-sm rounded-r-full 
                            {% if '당일' in rp.description %} bg-red-600 {% elif '+1' in rp.description %} bg-blue-600 {% elif '+2' in rp.description %} bg-emerald-600 {% else %} bg-gray-600 {% endif %}">
                            {{ rp.description }}
                        </span>
                    </div>
                    {% endif %}
                    <div class="bg-white rounded-[2rem] border border-gray-100 p-4 shadow-sm transition hover:shadow-2xl hover:-translate-y-2 text-left h-full flex flex-col">
                        <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-4 rounded-2xl bg-gray-50 p-2">
                        <p class="text-xs md:text-sm font-black text-gray-800 truncate mb-1">{{ rp.name }}</p>
                        <p class="text-[9px] md:text-[11px] text-gray-400 font-bold mb-3">{{ rp.spec or '일반' }}</p>
                        <p class="text-sm md:text-lg font-black text-teal-600 mt-auto">{{ "{:,}".format(rp.price) }}원</p>
                    </div>
                </a>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="mt-40 border-t border-gray-100 pt-24 px-4 md:px-0">
            <h3 class="font-black text-2xl md:text-4xl mb-12 flex items-center gap-4 tracking-tighter text-left">
                <span class="w-2 h-10 bg-teal-600 rounded-full"></span> 📦 카테고리 더 둘러보기
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-10">
                {% for c_info in recommend_cats_detail %}
                <div class="bg-gray-50 p-6 md:p-8 rounded-[3rem] border border-gray-100 shadow-inner text-left">
                    <h3 class="text-lg md:text-xl font-black mb-6 flex justify-between items-center">
                        {{ c_info.name }}
                        <a href="/category/{{ c_info.name }}" class="text-xs text-gray-400 font-bold hover:text-teal-600">전체보기 ></a>
                    </h3>
                    <div class="grid grid-cols-2 gap-4">
                        {% for cp in cat_previews_detail[c_info] %}
                        <div class="bg-white p-3 rounded-2xl shadow-sm relative flex flex-col">
                            {% if cp.description %}
                            <div class="absolute top-2 left-0 z-20">
                                <span class="px-2 py-1 text-[7px] font-black text-white shadow-sm rounded-r-full 
                                    {% if '당일' in cp.description %} bg-red-600 {% elif '+1' in cp.description %} bg-blue-600 {% elif '+2' in cp.description %} bg-emerald-600 {% else %} bg-gray-600 {% endif %}">
                                    {{ cp.description }}
                                </span>
                            </div>
                            {% endif %}
                            <a href="/product/{{ cp.id }}" class="block mb-2">
                                <img src="{{ cp.image_url }}" class="w-full aspect-square object-contain rounded-xl p-1 bg-gray-50">
                            </a>
                            <div class="px-1">
                                <p class="text-[10px] font-black text-gray-800 truncate">{{ cp.name }}</p>
                                <p class="text-[9px] text-gray-400 font-bold">{{ "{:,}".format(cp.price) }}원</p>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="mt-24 px-4 md:px-0 grid grid-cols-1 md:grid-cols-2 gap-6">
            <a href="/category/최신상품" class="bg-gray-800 text-white py-8 rounded-[2.5rem] text-center text-base font-black shadow-xl hover:bg-black transition flex items-center justify-center gap-4">
                <i class="fas fa-rocket text-xl text-blue-400"></i> 최신 상품 전체보기
            </a>
            <a href="/" class="bg-white border-2 border-teal-600 text-teal-600 py-8 rounded-[2.5rem] text-center text-base font-black shadow-sm hover:bg-teal-50 transition flex items-center justify-center gap-4">
                <i class="fas fa-home text-xl"></i> 바구니삼촌 홈으로
            </a>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, 
                                  p=p, is_expired=is_expired, detail_images=detail_images, 
                                  cat_info=cat_info, latest_all=latest_all, 
                                  keyword_recommends=keyword_recommends, 
                                  product_reviews=product_reviews,
                                  reviews_total_count=reviews_total_count,
                                  reviews_has_more=reviews_has_more,
                                  recommend_cats_detail=recommend_cats_detail,
                                  cat_previews_detail=cat_previews_detail)
@app.route('/category/seller/<int:cid>')
def seller_info_page(cid):
    """판매 사업자 정보 상세 페이지"""
    cat = Category.query.get_or_404(cid)
    content = """
    <div class="max-w-xl mx-auto py-24 md:py-32 px-6 font-black text-left">
        <nav class="mb-12 text-left"><a href="javascript:history.back()" class="text-teal-600 font-black hover:underline flex items-center gap-2"><i class="fas fa-arrow-left"></i> 이전으로 돌아가기</a></nav>
        <div class="bg-white rounded-[3rem] md:rounded-[5rem] shadow-2xl border border-gray-100 overflow-hidden text-left">
            <div class="bg-teal-600 p-12 md:p-16 text-white text-center">
                <div class="w-20 h-20 md:w-24 md:h-24 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-8 text-3xl md:text-4xl text-center"><i class="fas fa-store"></i></div>
                <h2 class="text-3xl md:text-4xl font-black tracking-tight mb-3 italic uppercase text-center">Business Info</h2>
                <p class="opacity-80 font-bold text-sm md:text-lg text-center">본 상품의 실제 판매 사업자 정보입니다.</p>
            </div>
            
            <div class="p-10 md:p-20 space-y-10 md:space-y-14 text-left">
                <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Company Name</p><p class="text-2xl md:text-3xl text-gray-800 font-black text-left">상호명 : {{ cat.biz_name or '-' }}</p></div>
                <div class="grid grid-cols-2 gap-10 text-left">
                    <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Representative</p><p class="text-gray-800 font-black text-lg md:text-xl text-left">대표자 : {{ cat.biz_representative or '-' }}</p></div>
                    <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Tax ID</p><p class="text-gray-800 font-black text-lg md:text-xl text-left">{{ cat.biz_reg_number or '-' }}</p></div>
                </div>
                <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Location</p><p class="text-gray-700 font-bold leading-relaxed text-sm md:text-lg text-left">{{ cat.biz_address or '-' }}</p></div>
                <div class="p-8 md:p-12 bg-gray-50 rounded-[2rem] md:rounded-[3rem] border border-dashed border-gray-200 text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Inquiry Center</p><p class="text-teal-600 text-2xl md:text-4xl font-black italic text-left">{{ cat.biz_contact or '-' }}</p></div>
            </div>
            
            <div class="bg-gray-50 p-8 text-center border-t border-gray-100 text-[11px] text-gray-400 font-black uppercase tracking-[0.5em] text-center">
                바구니 삼촌 Premium Service
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, cat=cat)

def _find_or_create_social_user(provider, provider_id, email, name):
    """소셜 로그인: provider+provider_id 또는 email로 회원 찾기, 없으면 생성. 반환: User"""
    user = User.query.filter_by(auth_provider=provider, auth_provider_id=str(provider_id)).first()
    if user:
        if (email and not user.email):
            user.email = email
        if name and not user.name:
            user.name = name
        db.session.commit()
        return user
    if email:
        user = User.query.filter_by(email=email).first()
        if user:
            user.auth_provider = provider
            user.auth_provider_id = str(provider_id)
            if name and not user.name:
                user.name = name
            db.session.commit()
            return user
    new_user = User(
        email=email or (provider + '_' + str(provider_id) + '@social.local'),
        password=None,
        name=name or '',
        auth_provider=provider,
        auth_provider_id=str(provider_id)
    )
    db.session.add(new_user)
    db.session.commit()
    return new_user


def _oauth_redirect_base():
    """OAuth redirect_uri 기준 URL. OAUTH_REDIRECT_BASE 또는 SITE_URL 설정 시 사용(redirect_uri_mismatch 방지)."""
    base = (os.getenv('OAUTH_REDIRECT_BASE') or os.getenv('SITE_URL') or '').strip().rstrip('/')
    if base:
        return base
    return request.url_root.rstrip('/')


@app.route('/auth/naver')
def auth_naver():
    """네이버 로그인 진입: 네이버 인증 페이지로 리다이렉트"""
    client_id = os.getenv('NAVER_CLIENT_ID')
    if not client_id:
        flash("네이버 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/naver/callback'
    state = os.urandom(16).hex()
    session['oauth_state'] = state
    session['oauth_next'] = request.args.get('next') or '/'
    url = (
        'https://nid.naver.com/oauth2.0/authorize'
        '?response_type=code&client_id={}&redirect_uri={}&state={}'
    ).format(client_id, requests.utils.quote(redirect_uri), state)
    # 테스트 시 동의 화면 캡처용: .env에 FORCE_NAVER_CONSENT_SCREEN=1 설정 시 동의 화면 재표시 파라미터 추가 (네이버가 미지원 시 무시됨)
    if os.getenv('FORCE_NAVER_CONSENT_SCREEN', '').strip() in ('1', 'true', 'yes'):
        url += '&auth_type=reprompt&prompt=consent'
    return redirect(url)


@app.route('/auth/naver/callback')
def auth_naver_callback():
    """네이버 로그인 콜백: code로 토큰·프로필 조회 후 로그인 처리"""
    state = request.args.get('state')
    if not state or state != session.get('oauth_state'):
        flash("잘못된 요청입니다."); return redirect('/login')
    session.pop('oauth_state', None)
    next_url = session.pop('oauth_next', '/')
    code = request.args.get('code')
    if not code:
        flash("네이버 로그인에 실패했습니다."); return redirect('/login')
    client_id = os.getenv('NAVER_CLIENT_ID')
    client_secret = os.getenv('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        flash("네이버 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/naver/callback'
    token_res = requests.post(
        'https://nid.naver.com/oauth2.0/token',
        data={
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'state': state,
            'redirect_uri': redirect_uri
        },
        headers={'Accept': 'application/json'}
    )
    if token_res.status_code != 200:
        flash("네이버 로그인(토큰)에 실패했습니다."); return redirect('/login')
    try:
        token_data = token_res.json()
        access_token = token_data.get('access_token')
    except Exception:
        flash("네이버 로그인 응답 오류."); return redirect('/login')
    if not access_token:
        flash("네이버 로그인에 실패했습니다."); return redirect('/login')
    profile_res = requests.get(
        'https://openapi.naver.com/v1/nid/me',
        headers={'Authorization': 'Bearer ' + access_token}
    )
    if profile_res.status_code != 200:
        flash("프로필 조회에 실패했습니다."); return redirect('/login')
    try:
        profile_data = profile_res.json()
        res = profile_data.get('response') or {}
        pid = res.get('id')
        email = (res.get('email') or '').strip() or None
        name = (res.get('name') or '').strip() or None
    except Exception:
        flash("프로필 형식 오류."); return redirect('/login')
    if not pid:
        flash("네이버 프로필을 가져올 수 없습니다."); return redirect('/login')
    user = _find_or_create_social_user('naver', pid, email, name)
    session.permanent = True
    login_user(user)
    if user.email and user.email.endswith('@social.local'):
        flash("네이버로 로그인했습니다. 마이페이지에서 이메일·주소를 보완해 주세요.")
    resp = redirect(next_url)
    resp.set_cookie('last_login_method', 'naver', max_age=365*24*3600, samesite='Lax')
    return resp


@app.route('/auth/google')
def auth_google():
    """구글 로그인 진입: 구글 인증 페이지로 리다이렉트"""
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    if not client_id:
        flash("구글 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/google/callback'
    state = os.urandom(16).hex()
    session['oauth_state'] = state
    session['oauth_next'] = request.args.get('next') or '/'
    scope = requests.utils.quote('openid email profile')
    url = (
        'https://accounts.google.com/o/oauth2/v2/auth'
        '?client_id={}&redirect_uri={}&response_type=code&scope={}&state={}&access_type=offline&prompt=consent'
    ).format(client_id, requests.utils.quote(redirect_uri), scope, state)
    return redirect(url)


@app.route('/auth/google/callback')
def auth_google_callback():
    """구글 로그인 콜백"""
    state = request.args.get('state')
    if not state or state != session.get('oauth_state'):
        flash("잘못된 요청입니다."); return redirect('/login')
    session.pop('oauth_state', None)
    next_url = session.pop('oauth_next', '/')
    code = request.args.get('code')
    if not code:
        flash("구글 로그인에 실패했습니다."); return redirect('/login')
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        flash("구글 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/google/callback'
    token_res = requests.post(
        'https://oauth2.googleapis.com/token',
        data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    if token_res.status_code != 200:
        flash("구글 로그인(토큰)에 실패했습니다."); return redirect('/login')
    try:
        token_data = token_res.json()
        access_token = token_data.get('access_token')
    except Exception:
        flash("구글 로그인 응답 오류."); return redirect('/login')
    if not access_token:
        flash("구글 로그인에 실패했습니다."); return redirect('/login')
    profile_res = requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': 'Bearer ' + access_token}
    )
    if profile_res.status_code != 200:
        flash("프로필 조회에 실패했습니다."); return redirect('/login')
    try:
        res = profile_res.json()
        pid = res.get('id')
        email = (res.get('email') or '').strip() or None
        name = (res.get('name') or '').strip() or None
    except Exception:
        flash("프로필 형식 오류."); return redirect('/login')
    if not pid:
        flash("구글 프로필을 가져올 수 없습니다."); return redirect('/login')
    user = _find_or_create_social_user('google', str(pid), email, name)
    session.permanent = True
    login_user(user)
    if user.email and user.email.endswith('@social.local'):
        flash("구글로 로그인했습니다. 마이페이지에서 이메일·주소를 보완해 주세요.")
    resp = redirect(next_url)
    resp.set_cookie('last_login_method', 'google', max_age=365*24*3600, samesite='Lax')
    return resp


@app.route('/auth/kakao')
def auth_kakao():
    """카카오 로그인 진입: 카카오 인증 페이지로 리다이렉트"""
    client_id = os.getenv('KAKAO_REST_API_KEY') or os.getenv('KAKAO_CLIENT_ID')
    if not client_id:
        flash("카카오 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/kakao/callback'
    state = os.urandom(16).hex()
    session['oauth_state'] = state
    session['oauth_next'] = request.args.get('next') or '/'
    url = (
        'https://kauth.kakao.com/oauth/authorize'
        '?client_id={}&redirect_uri={}&response_type=code&state={}'
    ).format(client_id, requests.utils.quote(redirect_uri), state)
    return redirect(url)


@app.route('/auth/kakao/callback')
def auth_kakao_callback():
    """카카오 로그인 콜백"""
    state = request.args.get('state')
    if not state or state != session.get('oauth_state'):
        flash("잘못된 요청입니다."); return redirect('/login')
    session.pop('oauth_state', None)
    next_url = session.pop('oauth_next', '/')
    code = request.args.get('code')
    if not code:
        flash("카카오 로그인에 실패했습니다."); return redirect('/login')
    client_id = os.getenv('KAKAO_REST_API_KEY') or os.getenv('KAKAO_CLIENT_ID')
    client_secret = os.getenv('KAKAO_CLIENT_SECRET', '')  # 카카오는 선택
    if not client_id:
        flash("카카오 로그인이 설정되지 않았습니다."); return redirect('/login')
    redirect_uri = _oauth_redirect_base() + '/auth/kakao/callback'
    token_payload = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'code': code
    }
    if client_secret:
        token_payload['client_secret'] = client_secret
    token_res = requests.post(
        'https://kauth.kakao.com/oauth/token',
        data=token_payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    if token_res.status_code != 200:
        flash("카카오 로그인(토큰)에 실패했습니다."); return redirect('/login')
    try:
        token_data = token_res.json()
        access_token = token_data.get('access_token')
    except Exception:
        flash("카카오 로그인 응답 오류."); return redirect('/login')
    if not access_token:
        flash("카카오 로그인에 실패했습니다."); return redirect('/login')
    profile_res = requests.get(
        'https://kapi.kakao.com/v2/user/me',
        headers={'Authorization': 'Bearer ' + access_token}
    )
    if profile_res.status_code != 200:
        flash("카카오 프로필 조회에 실패했습니다."); return redirect('/login')
    try:
        res = profile_res.json()
        pid = res.get('id')
        acc = res.get('kakao_account') or {}
        email = (acc.get('email') or '').strip() or None
        prof = acc.get('profile') or {}
        name = (prof.get('nickname') or '').strip() or None
    except Exception:
        flash("카카오 프로필 형식 오류."); return redirect('/login')
    if not pid:
        flash("카카오 프로필을 가져올 수 없습니다."); return redirect('/login')
    user = _find_or_create_social_user('kakao', str(pid), email, name)
    session.permanent = True
    login_user(user)
    if user.email and user.email.endswith('@social.local'):
        flash("카카오로 로그인했습니다. 마이페이지에서 이메일·주소를 보완해 주세요.")
    resp = redirect(next_url)
    resp.set_cookie('last_login_method', 'kakao', max_age=365*24*3600, samesite='Lax')
    return resp


def _auth_status_json():
    """통합 로그인 설정 점검 JSON (관리자 확인 후 반환)."""
    base = _oauth_redirect_base()
    return jsonify({
        "flask_secret_set": bool(os.getenv("FLASK_SECRET_KEY")),
        "naver": {
            "client_id_set": bool(os.getenv("NAVER_CLIENT_ID")),
            "client_secret_set": bool(os.getenv("NAVER_CLIENT_SECRET")),
            "redirect_uri": base + "/auth/naver/callback",
        },
        "google": {
            "client_id_set": bool(os.getenv("GOOGLE_CLIENT_ID")),
            "client_secret_set": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
            "redirect_uri": base + "/auth/google/callback",
        },
        "kakao": {
            "rest_api_key_set": bool(os.getenv("KAKAO_REST_API_KEY") or os.getenv("KAKAO_CLIENT_ID")),
            "client_secret_set": bool(os.getenv("KAKAO_CLIENT_SECRET")),
            "redirect_uri": base + "/auth/kakao/callback",
        },
        "hint": "각 redirect_uri를 해당 개발자 콘솔에 동일하게 등록해야 합니다. FLASK_SECRET_KEY가 없으면 세션이 유지되지 않아 콜백 시 오류가 납니다.",
    })


@app.route('/admin/auth-status')
@login_required
def admin_auth_status():
    """통합 로그인 설정 점검 (관리자 전용)."""
    if not getattr(current_user, 'is_admin', False):
        return jsonify({"error": "권한 없음"}), 403
    return _auth_status_json()


@app.route('/auth/status')
@login_required
def auth_status():
    """통합 로그인 설정 점검 (관리자 전용). /admin/auth-status 가 404일 때 이 URL 사용."""
    if not getattr(current_user, 'is_admin', False):
        return jsonify({"error": "권한 없음"}), 403
    return _auth_status_json()


@app.route('/login', methods=['GET', 'POST'])
def login():
    """로그인 라우트"""
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.password and check_password_hash(user.password, request.form.get('password')):
            session.permanent = True
            login_user(user)
            resp = redirect(request.args.get('next') or '/')
            resp.set_cookie('last_login_method', 'email', max_age=365*24*3600, samesite='Lax')
            return resp
        flash("로그인 정보를 다시 한 번 확인해주세요.")
    next_arg = request.args.get('next', '')
    next_q = ('?next=' + requests.utils.quote(next_arg)) if next_arg else ''
    recent_login = request.cookies.get('last_login_method') or ''
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-24 p-10 md:p-16 bg-white rounded-[3rem] md:rounded-[4rem] shadow-2xl border text-left">
        <h2 class="text-3xl font-black text-center mb-8 text-teal-600 uppercase italic tracking-tighter text-center">Login</h2>
        <div class="mb-8">
            <p class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-center mb-4">네이버 · 구글 · 카카오 통합 로그인</p>
            <div class="flex flex-col gap-3">
                <div class="relative" id="login-option-naver">
                    {% if recent_login == 'naver' %}<p class="text-[10px] text-teal-600 font-black mb-1.5 flex items-center justify-center gap-1.5"><span class="inline-block">최근 로그인 (네이버)</span><span class="inline-block text-teal-500 text-sm" aria-hidden="true">↓</span></p>{% endif %}
                    <a href="/auth/naver{{ next_q }}" class="flex items-center justify-center gap-3 w-full py-4 rounded-2xl font-black text-sm bg-[#03C75A] text-white hover:opacity-90 transition shadow-sm{% if recent_login == 'naver' %} ring-2 ring-teal-400 ring-offset-2{% endif %}"><span class="w-5 h-5 rounded-full bg-white/20 flex items-center justify-center text-[10px]">N</span> 네이버로 로그인</a>
                </div>
                <div class="relative" id="login-option-google">
                    {% if recent_login == 'google' %}<p class="text-[10px] text-teal-600 font-black mb-1.5 flex items-center justify-center gap-1.5"><span class="inline-block">최근 로그인 (구글)</span><span class="inline-block text-teal-500 text-sm" aria-hidden="true">↓</span></p>{% endif %}
                    <a href="/auth/google{{ next_q }}" class="flex items-center justify-center gap-3 w-full py-4 rounded-2xl font-black text-sm bg-white border-2 border-gray-200 text-gray-700 hover:bg-gray-50 transition{% if recent_login == 'google' %} ring-2 ring-teal-400 ring-offset-2{% endif %}"><span class="w-5 h-5 rounded-full bg-[#4285F4] flex items-center justify-center text-white text-[10px]">G</span> 구글로 로그인</a>
                </div>
                <div class="relative" id="login-option-kakao">
                    {% if recent_login == 'kakao' %}<p class="text-[10px] text-teal-600 font-black mb-1.5 flex items-center justify-center gap-1.5"><span class="inline-block">최근 로그인 (카카오)</span><span class="inline-block text-teal-500 text-sm" aria-hidden="true">↓</span></p>{% endif %}
                    <a href="/auth/kakao{{ next_q }}" class="flex items-center justify-center gap-3 w-full py-4 rounded-2xl font-black text-sm bg-[#FEE500] text-[#191919] hover:opacity-90 transition{% if recent_login == 'kakao' %} ring-2 ring-teal-400 ring-offset-2{% endif %}"><span class="w-5 h-5 rounded-full bg-[#191919] flex items-center justify-center text-[#FEE500] text-[10px]">K</span> 카카오로 로그인</a>
                </div>
            </div>
        </div>
        <div class="pt-8 border-t border-gray-100" id="login-option-email">
            <p class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-center mb-4">이메일 로그인</p>
            {% if recent_login == 'email' %}<p class="text-[10px] text-teal-600 font-black mb-1.5 flex items-center justify-center gap-1.5"><span class="inline-block">최근 로그인 (이메일)</span><span class="inline-block text-teal-500 text-sm" aria-hidden="true">↓</span></p>{% endif %}
            <div class="relative{% if recent_login == 'email' %} rounded-2xl ring-2 ring-teal-400 p-1{% endif %}">
            <form method="POST" class="space-y-8 text-left">
                <div class="space-y-2 text-left">
                    <label class="text-[10px] text-gray-300 font-black uppercase tracking-widest ml-4 text-left">ID (Email)</label>
                    <input name="email" type="email" placeholder="email@example.com" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-teal-100 outline-none text-sm text-left" required>
                </div>
                <div class="space-y-2 text-left">
                    <label class="text-[10px] text-gray-300 font-black uppercase tracking-widest ml-4 text-left">Password</label>
                    <input name="password" type="password" placeholder="••••••••" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-teal-100 outline-none text-sm text-left" required>
                </div>
                <button class="w-full bg-teal-600 text-white py-6 rounded-3xl font-black text-lg md:text-xl shadow-xl hover:bg-teal-700 transition active:scale-95 text-center">로그인</button>
            </form>
            </div>
        </div>
        <div class="text-center mt-10 text-center"><a href="/register" class="text-gray-400 text-xs font-black hover:text-teal-600 transition text-center text-center">아직 회원이 아니신가요? 회원가입</a></div>
    </div>""" + FOOTER_HTML, next_q=next_q, recent_login=recent_login)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """회원가입 라우트 (전자상거래 동의 포함)"""
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        
        # 배송구역 체크 (관리자 설정 폴리곤 또는 기본 송도동)
        if not is_address_in_delivery_zone(addr or ""):
            flash("해당 주소는 배송 가능 구역이 아닙니다. 설정된 퀵지역 내 주소만 가입 가능하며, 그 외 지역은 배송 불가입니다."); return redirect('/register')

        if not request.form.get('consent_e_commerce'):
            flash("전자상거래 이용 약관 및 유의사항에 동의해야 합니다."); return redirect('/register')

        if User.query.filter_by(email=email).first(): flash("이미 가입된 이메일입니다."); return redirect('/register')
        new_user = User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo)
        db.session.add(new_user)
        db.session.commit()
        title, body = get_template_content('welcome')
        send_message(new_user.id, title, body, 'welcome')
        db.session.commit()
        return redirect('/login')
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-12 mb-24 p-10 md:p-16 bg-white rounded-[3rem] md:rounded-[4rem] shadow-2xl border text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-12 tracking-tighter uppercase text-teal-600 text-left">Join Us</h2>
        <form method="POST" class="space-y-6 text-left">
            <div class="space-y-4 text-left">
                <input name="name" placeholder="실명 (성함)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="email" type="email" placeholder="이메일 주소" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="password" type="password" placeholder="비밀번호" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="phone" placeholder="휴대폰 번호 ( - 제외 )" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
            </div>
            
            <div class="space-y-4 border-t border-gray-100 pt-6 text-left">
                <div class="flex gap-2 text-left text-left">
                    <input id="address" name="address" placeholder="인천광역시 연수구 송도동..." class="flex-1 p-5 bg-gray-100 rounded-2xl font-black text-xs md:text-sm text-left" readonly onclick="execDaumPostcode()">
                    <button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-6 rounded-2xl font-black text-xs text-center">검색</button>
                </div>
                <input id="address_detail" name="address_detail" placeholder="상세주소 (동/호수)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="entrance_pw" placeholder="공동현관 비밀번호 (필수)" class="w-full p-5 bg-red-50 rounded-2xl font-black border border-red-100 text-sm text-left" required>
                <textarea name="request_memo" placeholder="배송 시 요청사항을 남겨주세요" class="w-full p-5 bg-white border border-gray-100 rounded-2xl font-black h-28 text-sm text-left"></textarea>
            </div>
            
            <div class="p-5 bg-gray-50 rounded-2xl border border-gray-100 text-[10px] space-y-3 mt-6 text-left">
                <label class="flex items-start gap-3 cursor-pointer group text-left text-left">
                    <span class="group-hover:text-gray-800 transition leading-normal md:leading-relaxed break-keep text-[11px] md:text-sm">
    [필수] 본 서비스는 <b>구매대행형 통합 물류 서비스</b>이며, 이용자의 주문 요청에 따라 당사가 상품을 구매 및 배송함을 확인하고 이에 동의합니다.
</span>
                </label>
            </div>

            <button class="w-full bg-teal-600 text-white py-6 rounded-3xl font-black text-lg shadow-xl mt-6 hover:bg-teal-700 transition active:scale-95 text-center text-center">가입 완료</button>
        </form>
    </div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): 
    """로그아웃"""
    logout_user(); return redirect('/')
@app.route('/mypage/update_address', methods=['POST'])
@login_required
def update_address():
    """마이페이지 주소 업데이트 및 강제 데이터 갱신"""
    addr = request.form.get('address')
    addr_d = request.form.get('address_detail')
    ent_pw = request.form.get('entrance_pw')

    if not addr or not is_address_in_delivery_zone(addr):
        flash("해당 주소는 배송 가능 구역이 아닙니다. 퀵지역 설정 구역 내 주소만 배송 가능하며, 그 외 지역은 배송 불가입니다.")
        return redirect(url_for('mypage'))

    try:
        # 1. DB 데이터 업데이트
        current_user.address = addr
        current_user.address_detail = addr_d
        current_user.entrance_pw = ent_pw
        
        # 2. 변경사항 저장 및 객체 새로고침 (핵심)
        db.session.commit()
        db.session.refresh(current_user) 
        
        flash("회원 정보가 성공적으로 수정되었습니다! ✨")
    except Exception as e:
        db.session.rollback()
        flash("저장 중 오류가 발생했습니다.")
        print(f"Error: {e}")

    return redirect(url_for('mypage'))

@app.route('/mypage/messages')
@login_required
def mypage_messages():
    """내 메시지 목록 (읽음 처리 지원). ?id= 있으면 해당 메시지 열기 및 읽음 처리."""
    msg_id = request.args.get('id', type=int)
    open_msg = None
    if msg_id:
        open_msg = UserMessage.query.filter_by(id=msg_id, user_id=current_user.id).first()
        if open_msg and not open_msg.read_at:
            open_msg.read_at = datetime.now()
            db.session.commit()
    messages = UserMessage.query.filter_by(user_id=current_user.id).order_by(UserMessage.created_at.desc()).limit(200).all()
    unread_count = UserMessage.query.filter_by(user_id=current_user.id, read_at=None).count()
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-2xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <div class="flex justify-between items-center mb-8">
                <a href="/mypage" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-sm font-bold"><i class="fas fa-arrow-left"></i> 마이페이지</a>
                <a href="/logout" class="text-gray-400 hover:text-red-500 transition text-sm font-black">로그아웃</a>
            </div>
            <h2 class="text-2xl md:text-3xl font-black text-gray-800 mb-2">내 메시지</h2>
            <p class="text-gray-500 text-sm mb-4">주문·배송 알림과 공지사항을 확인하세요.</p>
            {% if unread_count and unread_count > 0 %}
            <div class="mb-6 flex justify-end">
                <button type="button" id="messages-read-all-btn" class="touch-target px-4 py-2.5 bg-gray-100 text-gray-700 rounded-xl text-xs font-black hover:bg-gray-200 transition">읽음처리</button>
            </div>
            {% endif %}
            {% if open_msg %}
            <div class="bg-teal-50/50 border border-teal-100 rounded-2xl p-6 mb-8 relative">
                <div class="flex justify-between items-start gap-3 mb-3">
                    <span class="text-[10px] text-teal-600 font-bold">{{ open_msg.created_at.strftime('%Y-%m-%d %H:%M') if open_msg.created_at else '' }}</span>
                    <a href="/mypage/messages" class="touch-target inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gray-100 text-gray-600 text-xs font-black hover:bg-gray-200 transition">닫기 <i class="fas fa-times"></i></a>
                </div>
                <h3 class="font-black text-gray-800 text-lg">{{ open_msg.title or '알림' }}</h3>
                <p class="text-gray-700 text-sm mt-3 whitespace-pre-wrap">{{ open_msg.body or '' }}</p>
            </div>
            {% endif %}
            <div class="space-y-3">
                {% for m in messages %}
                <div class="rounded-2xl border shadow-sm overflow-hidden {% if m.read_at %}bg-gray-50 border-gray-200{% else %}bg-white border-gray-100 border-l-4 border-l-teal-500{% endif %} {% if open_msg and open_msg.id == m.id %}ring-2 ring-teal-300{% endif %}">
                    <div class="p-5 text-left flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                        <a href="/mypage/messages?id={{ m.id }}" class="flex-1 min-w-0 hover:opacity-90 transition">
                            <div class="flex justify-between items-start gap-3">
                                <span class="text-[10px] font-bold {% if m.read_at %}text-gray-400{% else %}text-gray-500{% endif %}">{{ m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '' }}</span>
                                <span class="text-[10px] px-2 py-0.5 rounded-full {% if m.read_at %}bg-gray-200 text-gray-500{% elif m.msg_type in ['order_created','delivery_requested','delivery_in_progress','delivery_complete'] %}bg-teal-100 text-teal-700{% elif m.msg_type in ['order_cancelled','part_cancelled','out_of_stock'] %}bg-red-100 text-red-700{% else %}bg-gray-100 text-gray-600{% endif %}">{{ m.msg_type or '알림' }}</span>
                            </div>
                            <h3 class="font-black mt-2 {% if m.read_at %}text-gray-500{% else %}text-gray-800{% endif %}">{{ m.title or '알림' }}</h3>
                            <p class="text-sm mt-1 line-clamp-2 {% if m.read_at %}text-gray-400{% else %}text-gray-600{% endif %}">{{ (m.body or '')[:120] }}{% if (m.body or '')|length > 120 %}...{% endif %}</p>
                            {% if m.related_order_id %}<p class="text-[10px] mt-2 {% if m.read_at %}text-gray-400{% else %}text-teal-600{% endif %}">주문 관련</p>{% endif %}
                        </a>
                        {% if m.read_at %}
                        <span class="shrink-0 px-4 py-2.5 bg-gray-200 text-gray-400 rounded-xl text-xs font-black text-center cursor-default">확인됨</span>
                        {% else %}
                        <a href="/mypage/messages?id={{ m.id }}" class="touch-target shrink-0 px-4 py-2.5 bg-teal-600 text-white rounded-xl text-xs font-black hover:bg-teal-700 transition text-center">확인</a>
                        {% endif %}
                    </div>
                </div>
                {% else %}
                <div class="bg-gray-50 rounded-2xl p-12 text-center text-gray-500">받은 메시지가 없습니다.</div>
                {% endfor %}
            </div>
        </div>
        <script>
        (function(){
            var btn = document.getElementById('messages-read-all-btn');
            if (!btn) return;
            btn.addEventListener('click', function() {
                btn.disabled = true;
                btn.textContent = '처리 중...';
                fetch('/mypage/messages/read-all', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
                    .then(function(r) { return r.json(); })
                    .then(function(d) { if (d.success) location.reload(); else btn.disabled = false; })
                    .catch(function() { btn.disabled = false; btn.textContent = '읽음처리'; });
            });
        })();
        </script>
        """ + FOOTER_HTML,
        messages=messages, unread_count=unread_count, open_msg=open_msg
    )


@app.route('/mypage/messages/<int:msg_id>/read', methods=['POST'])
@login_required
def mypage_message_read(msg_id):
    """메시지 읽음 처리"""
    m = UserMessage.query.filter_by(id=msg_id, user_id=current_user.id).first()
    if not m:
        return jsonify({"success": False}), 404
    if not m.read_at:
        m.read_at = datetime.now()
        db.session.commit()
    return jsonify({"success": True})


@app.route('/mypage/messages/read-all', methods=['POST'])
@login_required
def mypage_messages_read_all():
    """전체 메시지 읽음 처리"""
    now = datetime.now()
    unread = UserMessage.query.filter_by(user_id=current_user.id, read_at=None).all()
    for m in unread:
        m.read_at = now
    db.session.commit()
    return jsonify({"success": True, "count": len(unread)})


@app.route('/mypage/points')
@login_required
def mypage_points():
    """포인트 내역 (회원 본인) - 적립내역 / 사용내역 구분"""
    all_logs = PointLog.query.filter_by(user_id=current_user.id).order_by(PointLog.created_at.desc()).limit(200).all()
    earned_logs = [l for l in all_logs if l.amount > 0]
    used_logs = [l for l in all_logs if l.amount < 0]
    current_points = getattr(current_user, 'points', 0) or 0
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-2xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <div class="flex justify-between items-center mb-8">
                <a href="/mypage" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-sm font-bold"><i class="fas fa-arrow-left"></i> 마이페이지</a>
                <a href="/logout" class="text-gray-400 hover:text-red-500 transition text-sm font-black">로그아웃</a>
            </div>
            <h2 class="text-2xl md:text-3xl font-black text-gray-800 mb-2">포인트 내역</h2>
            <p class="text-gray-500 text-sm mb-6">보유 포인트: <span class="text-teal-600 font-black">{{ current_points }}</span> P</p>

            <div class="mb-8">
                <h3 class="text-lg font-black text-gray-700 mb-3 flex items-center gap-2"><i class="fas fa-plus-circle text-teal-500"></i> 적립내역</h3>
                <div class="space-y-2">
                    {% for log in earned_logs %}
                    <div class="bg-white rounded-2xl border border-gray-100 p-4 flex justify-between items-center">
                        <div>
                            <span class="text-[10px] text-gray-400 font-bold">{{ log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else '' }}</span>
                            <p class="text-sm font-bold text-gray-800 mt-0.5">{{ log.memo or '적립' }}</p>
                        </div>
                        <span class="font-black text-teal-600">+{{ log.amount }} P</span>
                    </div>
                    {% else %}
                    <div class="bg-gray-50 rounded-2xl p-8 text-center text-gray-500 text-sm">적립 내역이 없습니다.</div>
                    {% endfor %}
                </div>
            </div>

            <div>
                <h3 class="text-lg font-black text-gray-700 mb-3 flex items-center gap-2"><i class="fas fa-minus-circle text-amber-500"></i> 사용내역</h3>
                <div class="space-y-2">
                    {% for log in used_logs %}
                    <div class="bg-white rounded-2xl border border-gray-100 p-4 flex justify-between items-center">
                        <div>
                            <span class="text-[10px] text-gray-400 font-bold">{{ log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else '' }}</span>
                            <p class="text-sm font-bold text-gray-800 mt-0.5">{{ log.memo or '사용' }}</p>
                        </div>
                        <span class="font-black text-gray-500">{{ log.amount }} P</span>
                    </div>
                    {% else %}
                    <div class="bg-gray-50 rounded-2xl p-8 text-center text-gray-500 text-sm">사용 내역이 없습니다.</div>
                    {% endfor %}
                </div>
            </div>
        </div>
        """ + FOOTER_HTML,
        earned_logs=earned_logs, used_logs=used_logs, current_points=current_points
    )


@app.route('/mypage/reviews')
@login_required
def mypage_reviews():
    """내가 등록한 리뷰 목록"""
    reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).all()
    return render_template_string(
        HEADER_HTML + """
        <div class="max-w-2xl mx-auto py-8 md:py-12 px-4 font-black text-left">
            <div class="flex justify-between items-center mb-8">
                <a href="/mypage" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-sm font-bold"><i class="fas fa-arrow-left"></i> 마이페이지</a>
                <a href="/logout" class="text-gray-400 hover:text-red-500 transition text-sm font-black">로그아웃</a>
            </div>
            <h2 class="text-2xl md:text-3xl font-black text-gray-800 mb-2">리뷰관리</h2>
            <p class="text-gray-500 text-sm mb-6">내가 작성한 구매 후기입니다.</p>
            <div class="space-y-4">
                {% for r in reviews %}
                <div class="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden flex flex-col sm:flex-row gap-4 p-4">
                    {% if r.image_url %}
                    {% if r.product_id %}<a href="/product/{{ r.product_id }}" class="shrink-0 w-20 h-20 rounded-xl overflow-hidden bg-gray-50">{% else %}<div class="shrink-0 w-20 h-20 rounded-xl overflow-hidden bg-gray-50">{% endif %}
                        <img src="{{ r.image_url }}" class="w-full h-full object-cover" alt="" loading="lazy">
                    {% if r.product_id %}</a>{% else %}</div>{% endif %}
                    {% else %}
                    <div class="shrink-0 w-20 h-20 rounded-xl bg-gray-100 flex items-center justify-center text-gray-400 text-[10px] font-bold">사진 없음</div>
                    {% endif %}
                    <div class="flex-1 min-w-0">
                        <p class="text-[10px] text-gray-400 font-bold">{{ r.created_at.strftime('%Y.%m.%d') if r.created_at else '' }}</p>
                        <p class="font-black text-gray-800 mt-0.5 truncate">{{ r.product_name or '상품' }}</p>
                        <p class="text-sm text-gray-600 mt-1 line-clamp-2">{{ (r.content or '')[:100] }}{% if (r.content or '')|length > 100 %}...{% endif %}</p>
                        {% if r.product_id %}
                        <a href="/product/{{ r.product_id }}" class="inline-block mt-2 text-[10px] font-black text-teal-600 hover:underline">상품 보기</a>
                        {% endif %}
                    </div>
                </div>
                {% else %}
                <div class="bg-gray-50 rounded-2xl p-12 text-center text-gray-500">등록한 리뷰가 없습니다.</div>
                {% endfor %}
            </div>
        </div>
        """ + FOOTER_HTML,
        reviews=reviews
    )


@app.route('/mypage')
@login_required
def mypage():
    """마이페이지 (최종 완성본: 폰트 최적화 및 한글화 버전). 주소 수정은 여기서만 가능."""
    db.session.refresh(current_user)
    need_address = request.args.get("need_address") == "1"
    from_cart = request.args.get("from") == "cart"
    if need_address:
        flash("주소를 입력해 주세요.")
    # 알림 이미 허용한 회원에게는 '알림 켜기' 블록 미표시
    push_sub_count = PushSubscription.query.filter_by(user_id=current_user.id).count()
    push_already_set = push_sub_count > 0  # True면 알림 허용됨 → 알림 켜기 숨김
    unread_message_count = UserMessage.query.filter_by(user_id=current_user.id, read_at=None).count()
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    cutoff_7d = datetime.now() - timedelta(days=7)

    # 품목별 금액 상세 + 품목별 취소용 OrderItem 목록 (취소 품목도 표기)
    enhanced_orders = []
    for o in orders:
        o.order_items = OrderItem.query.filter_by(order_id=o.id).order_by(OrderItem.id.asc()).all()
        details_with_price = []
        if o.order_items:
            for oi in o.order_items:
                if oi.cancelled:
                    details_with_price.append(f"{oi.product_name}({oi.quantity}개) --- 취소")
                else:
                    details_with_price.append(f"{oi.product_name}({oi.quantity}개) --- {(oi.price * oi.quantity):,}원")
        elif o.product_details:
            parts = o.product_details.split(' | ')
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*?)\((\d+)\)', part)
                if match:
                    cat_n, p_name, qty = match.groups()
                    p_obj = Product.query.filter_by(name=p_name.strip()).first()
                    price = p_obj.price if p_obj else 0
                    line_total = price * int(qty)
                    details_with_price.append(f"{p_name.strip()}({qty}개) --- {line_total:,}원")
                else:
                    details_with_price.append(part)
        o.enhanced_details = "\\n".join(details_with_price) if details_with_price else "주문 취소됨"
        if o.order_items:
            o.display_summary = ", ".join(f"{oi.product_name}({oi.quantity})" + (" [취소]" if oi.cancelled else "") for oi in o.order_items)
            o.can_cancel_order = o.status == '결제완료' and not any(not getattr(oi, 'cancelled', False) and getattr(oi, 'item_status', None) in ('배송요청', '배송중', '배송완료') for oi in o.order_items)
        else:
            o.display_summary = (o.product_details or "주문 취소됨")[:80]
            o.can_cancel_order = (o.status == '결제완료')
        enhanced_orders.append(o)
    recent_orders = [o for o in enhanced_orders if not o.created_at or o.created_at >= cutoff_7d]
    older_orders = [o for o in enhanced_orders if o.created_at and o.created_at < cutoff_7d]

    # 최근 주문 상품 10개 (클릭 시 해당 카테고리로 이동)
    recent_order_items = db.session.query(OrderItem).join(Order, OrderItem.order_id == Order.id).filter(
        Order.user_id == current_user.id, OrderItem.cancelled == False
    ).order_by(Order.created_at.desc()).limit(10).all()
    # 주문일 포함하려면 Order도 가져와야 함
    recent_items_with_date = []
    for oi in recent_order_items:
        o = Order.query.get(oi.order_id)
        recent_items_with_date.append({"item": oi, "order_date": o.created_at if o else None})
    recent_items_with_date = recent_items_with_date[:10]

    content = """
    <div class="max-w-4xl mx-auto py-6 md:py-12 px-4 md:px-6 font-black text-left mobile-px">
        {% if from_cart %}
        <div class="mb-6 p-4 bg-teal-50 border border-teal-200 rounded-2xl text-teal-800 text-sm font-bold flex flex-wrap items-center justify-between gap-3">
            <span><i class="fas fa-shopping-cart mr-2"></i>주소 수정 후 장바구니에서 다시 주문하기를 눌러 주세요.</span>
            <a href="/cart" class="shrink-0 px-5 py-2.5 bg-teal-600 text-white rounded-xl text-xs font-black hover:bg-teal-700 transition">장바구니로 이동</a>
        </div>
        {% endif %}
        <div class="flex flex-col md:flex-row md:justify-between md:items-center gap-4 mb-8">
            <div class="flex flex-wrap items-center gap-3">
                <a href="/" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-xs md:text-sm font-bold touch-target">
                    <i class="fas fa-home"></i> 홈으로
                </a>
                <a href="/mypage/messages" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-xs md:text-sm font-bold touch-target">
                    <i class="fas fa-envelope"></i> 내 메시지
                    {% if unread_message_count and unread_message_count > 0 %}<span class="bg-teal-500 text-white text-[10px] px-1.5 py-0.5 rounded-full">{{ unread_message_count }}</span>{% endif %}
                </a>
                <a href="/mypage/reviews" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-xs md:text-sm font-bold touch-target">
                    <i class="fas fa-star"></i> 리뷰관리
                </a>
                <a href="/mypage/points" class="text-gray-400 hover:text-teal-600 transition flex items-center gap-1.5 text-xs md:text-sm font-bold touch-target">
                    <i class="fas fa-coins"></i> 포인트 내역
                </a>
                <a href="/logout" class="text-gray-400 hover:text-red-500 transition flex items-center gap-1.5 text-xs md:text-sm font-black touch-target">
                    로그아웃 <i class="fas fa-sign-out-alt"></i>
                </a>
            </div>
            {% if not push_already_set %}
            <div id="push-enable-block" class="p-4 bg-teal-50/50 border border-teal-100 rounded-2xl text-left">
                <p class="text-[11px] md:text-xs text-teal-800 font-bold mb-2">알림 허용 시 이벤트 및 배송 현황을 안내받을 수 있습니다.</p>
                <button type="button" id="push-enable-btn" class="touch-target px-4 py-2.5 bg-teal-600 text-white rounded-xl text-xs font-black hover:bg-teal-700 transition">알림 켜기</button>
                <span id="push-enable-status" class="ml-3 text-xs text-gray-500"></span>
            </div>
            {% endif %}
        </div>

        <div class="bg-white rounded-2xl md:rounded-[2.5rem] shadow-sm border border-gray-100 mb-8 md:mb-10 overflow-hidden">
            <div class="p-6 md:p-12">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 md:gap-6 mb-8 md:mb-10">
                    <div class="text-left w-full">
                        <span class="bg-teal-100 text-teal-700 text-[10px] px-3 py-1 rounded-lg tracking-widest uppercase mb-2 inline-block font-black">우수 회원</span>
                        <h2 class="text-2xl md:text-4xl font-black text-gray-800 leading-tight">
                            {{ current_user.name }} <span class="text-gray-400 font-medium text-lg md:text-xl">님</span>
                        </h2>
                        <p class="text-gray-400 text-xs md:text-sm mt-1 font-bold break-all">{{ current_user.email }}</p>
                    </div>
                    <button type="button" onclick="toggleAddressEdit()" id="edit-btn" class="touch-target bg-gray-50 text-gray-600 px-5 py-3 rounded-xl text-xs md:text-sm font-black hover:bg-gray-100 transition border border-gray-100 shrink-0">
                        {% if need_address %}<i class="fas fa-times"></i> 취소{% else %}<i class="fas fa-edit mr-1"></i> 주소 수정{% endif %}
                    </button>
                </div>

                <div class="pt-8 border-t border-gray-50 text-left">
                    {% if need_address %}
                    <div class="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-2xl text-amber-800 font-black text-sm flex items-center gap-2">
                        <i class="fas fa-map-marker-alt"></i> 주소를 입력해 주세요.
                    </div>
                    {% endif %}
                    <div id="address-display" class="grid grid-cols-1 md:grid-cols-2 gap-4 {% if need_address %}hidden{% endif %}">
                        <div class="bg-gray-50/50 p-5 md:p-6 rounded-2xl md:rounded-3xl border border-gray-50 text-left">
                            <p class="text-[10px] text-gray-400 uppercase mb-2 tracking-widest font-black">기본 배송지</p>
                            <p class="text-gray-700 text-sm md:text-base leading-snug font-black break-keep">
                                {{ current_user.address or '정보 없음' }}<br>
                                <span class="text-gray-400 text-xs md:text-sm font-bold">{{ current_user.address_detail or '' }}</span>
                            </p>
                        </div>
                        <div class="bg-orange-50/30 p-5 md:p-6 rounded-2xl md:rounded-3xl border border-orange-50 text-left">
                            <p class="text-[10px] text-orange-400 uppercase mb-2 tracking-widest font-black">공동현관 비밀번호</p>
                            <p class="text-orange-600 text-base md:text-lg flex items-center gap-2 font-black">
                                <span class="text-xl md:text-2xl">🔑</span> {{ current_user.entrance_pw or '미등록' }}
                            </p>
                        </div>
                    </div>

                    <form id="address-edit-form" action="/mypage/update_address" method="POST" class="space-y-4 {% if not need_address %}hidden{% endif %}">
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
                            <div class="space-y-3">
                                <div class="flex gap-2">
                                    <input id="address" name="address" value="{{ current_user.address or '' }}" class="flex-1 min-w-0 p-4 md:p-5 bg-gray-50 rounded-xl md:rounded-2xl text-xs md:text-sm font-black border border-gray-100" readonly onclick="execDaumPostcode()" placeholder="주소 검색">
                                    <button type="button" onclick="execDaumPostcode()" class="touch-target shrink-0 bg-gray-800 text-white px-4 md:px-6 rounded-xl md:rounded-2xl text-xs font-black">검색</button>
                                </div>
                                <input id="address_detail" name="address_detail" value="{{ current_user.address_detail or '' }}" class="w-full p-4 md:p-5 bg-gray-50 rounded-xl md:rounded-2xl text-xs md:text-sm font-black border border-gray-100" required placeholder="상세주소 (동/호수)">
                            </div>
                            <div class="space-y-3">
                                <input name="entrance_pw" value="{{ current_user.entrance_pw or '' }}" class="w-full p-4 md:p-5 bg-orange-50 rounded-xl md:rounded-2xl text-xs md:text-sm font-black border border-orange-100" required placeholder="공동현관 비밀번호">
                                <div class="flex gap-2">
                                    <button type="button" onclick="toggleAddressEdit()" class="flex-1 touch-target py-4 md:py-5 bg-gray-100 text-gray-500 rounded-xl md:rounded-2xl text-xs md:text-sm font-black">취소</button>
                                    <button type="submit" class="flex-[2] touch-target py-4 md:py-5 bg-teal-600 text-white rounded-xl md:rounded-2xl text-xs md:text-sm font-black shadow-lg">저장하기</button>
                                </div>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>

        <a href="/mypage/points" class="block mb-8 p-5 md:p-6 rounded-2xl border border-gray-100 bg-white hover:shadow-md transition text-left touch-target">
            <div class="flex justify-between items-center">
                <div class="flex items-center gap-3">
                    <span class="w-12 h-12 rounded-xl bg-teal-50 flex items-center justify-center shrink-0"><i class="fas fa-coins text-teal-600 text-xl"></i></span>
                    <div>
                        <p class="text-[10px] text-gray-500 font-bold uppercase tracking-wider">보유 포인트</p>
                        <p class="text-xl font-black text-gray-800">{{ getattr(current_user, 'points', 0) or 0 }} P</p>
                    </div>
                </div>
                <span class="text-teal-600 text-sm font-black">적립/사용 내역 <i class="fas fa-chevron-right ml-1"></i></span>
            </div>
        </a>

        <h3 class="text-lg md:text-2xl font-black text-gray-800 mb-4 md:mb-6 flex items-center gap-3 px-1 text-left">
            <span class="w-1.5 h-6 md:h-8 bg-blue-500 rounded-full shrink-0"></span> 최근 주문 상품
        </h3>
        <div class="mb-8 overflow-x-auto rounded-2xl border border-gray-100 bg-white shadow-sm">
            <table class="w-full text-left text-sm font-black min-w-[280px]">
                <thead>
                    <tr class="bg-gray-50 border-b border-gray-100">
                        <th class="py-3 px-4 text-[10px] uppercase text-gray-500 font-black">주문일</th>
                        <th class="py-3 px-4 text-[10px] uppercase text-gray-500 font-black">상품명</th>
                        <th class="py-3 px-4 text-[10px] uppercase text-gray-500 font-black">카테고리</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in recent_items_with_date %}
                    <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition">
                        <td class="py-3 px-4 text-[10px] text-gray-500">{{ row.order_date.strftime('%Y.%m.%d') if row.order_date else '-' }}</td>
                        <td class="py-3 px-4 text-gray-800 truncate max-w-[180px]">{{ row.item.product_name }}</td>
                        <td class="py-3 px-4">
                            <a href="/category/{{ row.item.product_category }}" class="text-teal-600 hover:underline font-bold">{{ row.item.product_category }}</a>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" class="py-8 text-center text-gray-400 text-sm">최근 주문 상품이 없습니다.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <h3 class="text-lg md:text-2xl font-black text-gray-800 mb-4 md:mb-6 flex items-center gap-3 px-1 text-left">
            <span class="w-1.5 h-6 md:h-8 bg-teal-500 rounded-full shrink-0"></span> 최근 주문 내역
        </h3>
        <div class="mb-6 flex flex-col sm:flex-row gap-3">
            <input type="text" id="mypage-order-search" placeholder="주문 검색 (상품명, 주문번호, 상태)" class="flex-1 min-w-0 px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium placeholder-gray-400 focus:ring-2 focus:ring-teal-500/20 focus:border-teal-300 outline-none transition">
        </div>

        <div class="space-y-4 md:space-y-6 text-left" id="mypage-orders-wrap">
            {% if recent_orders or older_orders %}
                <div id="mypage-orders-recent" class="space-y-4 md:space-y-6">
                {% for o in recent_orders %}
                <div class="mypage-order-card bg-white p-5 md:p-8 rounded-2xl md:rounded-[2.5rem] border border-gray-100 transition-all hover:shadow-md text-left" data-order-search="{{ (o.order_id or '') }} {{ (o.display_summary or o.product_details or '') }} {{ (o.status or '') }} {{ o.created_at.strftime('%Y.%m.%d') if o.created_at else '' }}">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 md:gap-4 mb-4">
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2 md:gap-3 mb-2 flex-wrap">
                                <span class="text-[10px] md:text-xs text-gray-400 font-bold">{{ o.created_at.strftime('%Y.%m.%d') }}</span>
                                <span class="text-[10px] md:text-xs font-black {% if o.status == '결제취소' %}text-red-400{% else %}text-teal-500{% endif %}">[{{ o.status }}]</span>
                            </div>
                            <p class="text-sm md:text-xl font-black text-gray-700 leading-tight break-keep">
                                {{ (o.display_summary or o.product_details or '주문 취소됨')[:80] }}{% if (o.display_summary or o.product_details or '')|length > 80 %}...{% endif %}
                            </p>
                        </div>
                        <div class="flex items-center gap-3 md:gap-4 flex-wrap shrink-0">
                            <span class="text-base md:text-2xl font-black text-gray-800 tracking-tighter">{{ "{:,}".format(o.total_price) }}원</span>
                            <div class="flex gap-2">
                                <button onclick='openReceiptModal({{ o.id }}, {{ o.enhanced_details | tojson }}, "{{ o.total_price }}", {{ (o.delivery_address or "") | tojson }}, "{{ o.order_id }}", "{{ o.delivery_fee }}")' class="text-xs font-black text-gray-400 bg-gray-50 px-4 py-2.5 rounded-xl border border-gray-100 hover:bg-gray-100 transition">영수증</button>
                                {% if o.status == '결제완료' %}
                                    {% set existing_review = Review.query.filter_by(order_id=o.id).first() %}
                                    {% if existing_review %}
                                        <button class="text-xs font-black text-gray-300 bg-gray-50 px-4 py-2.5 rounded-xl border border-gray-100 cursor-not-allowed" disabled>작성완료</button>
                                    {% else %}
                                        <button onclick='openReviewModal({{ o.id }}, "{{ (o.product_details or "")[:80]|e }}")' class="text-xs font-black text-orange-500 bg-orange-50 px-4 py-2.5 rounded-xl border border-orange-100 hover:bg-orange-100 transition shadow-sm">후기작성</button>
                                    {% endif %}
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% if o.order_items %}
                    <div class="border-t border-gray-100 pt-4 mt-4 space-y-2">
                        <p class="text-[10px] text-gray-400 font-black uppercase tracking-widest mb-2">품목별 상태</p>
                        {% for oi in o.order_items %}
                        <div class="flex flex-wrap items-center justify-between gap-2 py-2 {% if oi.cancelled %}opacity-60{% endif %}">
                            <div class="flex-1 min-w-0">
                                <span class="{% if oi.cancelled %}line-through text-gray-400{% else %}text-gray-700 font-bold{% endif %}">{{ oi.product_name }} × {{ oi.quantity }} — {{ "{:,}".format(oi.price * oi.quantity) }}원</span>
                                {% if oi.item_status and oi.item_status not in ('결제완료', '') %}
                                <span class="ml-2 text-[10px] font-black {% if oi.item_status == '품절취소' or oi.item_status == '부분취소' %}text-red-500{% elif oi.item_status == '배송지연' %}text-amber-600{% else %}text-teal-600{% endif %}">[{{ oi.item_status }}]</span>
                                {% endif %}
                                {% if oi.status_message %}
                                <p class="text-[10px] text-gray-500 mt-0.5">{{ oi.status_message }}</p>
                                {% endif %}
                            </div>
                            {% if oi.cancelled %}
                                <span class="text-red-500 text-xs font-black">취소됨</span>
                            {% elif o.status == '결제완료' and (not oi.item_status or oi.item_status == '결제완료') %}
                                <form action="/order/cancel_item/{{ o.id }}/{{ oi.id }}" method="POST" class="inline" onsubmit="return confirm('이 품목만 취소하고 해당 금액을 환불받으시겠습니까?');">
                                    <button type="submit" class="text-xs font-black text-red-500 bg-red-50 px-3 py-1.5 rounded-lg border border-red-100 hover:bg-red-100 transition">품목 취소</button>
                                </form>
                            {% endif %}
                        </div>
                        {% endfor %}
                        {% if o.can_cancel_order %}
                        <form action="/order/cancel/{{ o.id }}" method="POST" class="pt-2 border-t border-gray-100" onsubmit="return confirm('주문 전체를 취소하시겠습니까?');">
                            <button type="submit" class="text-xs font-black text-gray-500 bg-gray-100 px-4 py-2 rounded-xl hover:bg-gray-200 transition">전체 주문 취소</button>
                        </form>
                        {% else %}
                        <p class="pt-2 border-t border-gray-100 text-[10px] text-amber-600 font-black">배송 요청/진행된 품목이 있어 취소할 수 없습니다.</p>
                        {% endif %}
                    </div>
                    {% elif o.status == '결제완료' and o.can_cancel_order %}
                    <div class="border-t border-gray-100 pt-4 mt-4">
                        <form action="/order/cancel/{{ o.id }}" method="POST" class="inline" onsubmit="return confirm('주문 전체를 취소하시겠습니까?');">
                            <button type="submit" class="text-xs font-black text-red-500 bg-red-50 px-4 py-2 rounded-xl border border-red-100 hover:bg-red-100 transition">전체 주문 취소</button>
                        </form>
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
                </div>
                {% if older_orders %}
                <div class="mt-6 pt-6 border-t border-gray-100">
                    <button type="button" id="mypage-orders-more-btn" class="w-full py-4 rounded-2xl bg-gray-100 text-gray-600 font-black text-sm hover:bg-gray-200 transition">
                        목록 더보기 (1주일 이전 주문 {{ older_orders|length }}건)
                    </button>
                    <div id="mypage-orders-older" class="hidden space-y-4 md:space-y-6 mt-6">
                    {% for o in older_orders %}
                    <div class="mypage-order-card mypage-order-older bg-white p-5 md:p-8 rounded-2xl md:rounded-[2.5rem] border border-gray-100 transition-all hover:shadow-md text-left" data-order-search="{{ (o.order_id or '') }} {{ (o.display_summary or o.product_details or '') }} {{ (o.status or '') }} {{ o.created_at.strftime('%Y.%m.%d') if o.created_at else '' }}">
                    <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-3 md:gap-4 mb-4">
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2 md:gap-3 mb-2 flex-wrap">
                                <span class="text-[10px] md:text-xs text-gray-400 font-bold">{{ o.created_at.strftime('%Y.%m.%d') if o.created_at else '' }}</span>
                                <span class="text-[10px] md:text-xs font-black {% if o.status == '결제취소' %}text-red-400{% else %}text-teal-500{% endif %}">[{{ o.status }}]</span>
                            </div>
                            <p class="text-sm md:text-xl font-black text-gray-700 leading-tight break-keep">
                                {{ (o.display_summary or o.product_details or '주문 취소됨')[:80] }}{% if (o.display_summary or o.product_details or '')|length > 80 %}...{% endif %}
                            </p>
                        </div>
                        <div class="flex items-center gap-3 md:gap-4 flex-wrap shrink-0">
                            <span class="text-base md:text-2xl font-black text-gray-800 tracking-tighter">{{ "{:,}".format(o.total_price) }}원</span>
                            <div class="flex gap-2">
                                <button onclick='openReceiptModal({{ o.id }}, {{ o.enhanced_details | tojson }}, "{{ o.total_price }}", {{ (o.delivery_address or "") | tojson }}, "{{ o.order_id }}", "{{ o.delivery_fee }}")' class="text-xs font-black text-gray-400 bg-gray-50 px-4 py-2.5 rounded-xl border border-gray-100 hover:bg-gray-100 transition">영수증</button>
                                {% if o.status == '결제완료' %}
                                    {% set existing_review = Review.query.filter_by(order_id=o.id).first() %}
                                    {% if existing_review %}
                                        <button class="text-xs font-black text-gray-300 bg-gray-50 px-4 py-2.5 rounded-xl border border-gray-100 cursor-not-allowed" disabled>작성완료</button>
                                    {% else %}
                                        <button onclick='openReviewModal({{ o.id }}, "{{ (o.product_details or "")[:80]|e }}")' class="text-xs font-black text-orange-500 bg-orange-50 px-4 py-2.5 rounded-xl border border-orange-100 hover:bg-orange-100 transition shadow-sm">후기작성</button>
                                    {% endif %}
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% if o.order_items %}
                    <div class="border-t border-gray-100 pt-4 mt-4 space-y-2">
                        <p class="text-[10px] text-gray-400 font-black uppercase tracking-widest mb-2">품목별 상태</p>
                        {% for oi in o.order_items %}
                        <div class="flex flex-wrap items-center justify-between gap-2 py-2 {% if oi.cancelled %}opacity-60{% endif %}">
                            <div class="flex-1 min-w-0">
                                <span class="{% if oi.cancelled %}line-through text-gray-400{% else %}text-gray-700 font-bold{% endif %}">{{ oi.product_name }} × {{ oi.quantity }} — {{ "{:,}".format(oi.price * oi.quantity) }}원</span>
                                {% if oi.item_status and oi.item_status not in ('결제완료', '') %}
                                <span class="ml-2 text-[10px] font-black {% if oi.item_status == '품절취소' or oi.item_status == '부분취소' %}text-red-500{% elif oi.item_status == '배송지연' %}text-amber-600{% else %}text-teal-600{% endif %}">[{{ oi.item_status }}]</span>
                                {% endif %}
                                {% if oi.status_message %}
                                <p class="text-[10px] text-gray-500 mt-0.5">{{ oi.status_message }}</p>
                                {% endif %}
                            </div>
                            {% if oi.cancelled %}
                                <span class="text-red-500 text-xs font-black">취소됨</span>
                            {% elif o.status == '결제완료' and (not oi.item_status or oi.item_status == '결제완료') %}
                                <form action="/order/cancel_item/{{ o.id }}/{{ oi.id }}" method="POST" class="inline" onsubmit="return confirm('이 품목만 취소하고 해당 금액을 환불받으시겠습니까?');">
                                    <button type="submit" class="text-xs font-black text-red-500 bg-red-50 px-3 py-1.5 rounded-lg border border-red-100 hover:bg-red-100 transition">품목 취소</button>
                                </form>
                            {% endif %}
                        </div>
                        {% endfor %}
                        {% if o.can_cancel_order %}
                        <form action="/order/cancel/{{ o.id }}" method="POST" class="pt-2 border-t border-gray-100" onsubmit="return confirm('주문 전체를 취소하시겠습니까?');">
                            <button type="submit" class="text-xs font-black text-gray-500 bg-gray-100 px-4 py-2 rounded-xl hover:bg-gray-200 transition">전체 주문 취소</button>
                        </form>
                        {% else %}
                        <p class="pt-2 border-t border-gray-100 text-[10px] text-amber-600 font-black">배송 요청/진행된 품목이 있어 취소할 수 없습니다.</p>
                        {% endif %}
                    </div>
                    {% elif o.status == '결제완료' and o.can_cancel_order %}
                    <div class="border-t border-gray-100 pt-4 mt-4">
                        <form action="/order/cancel/{{ o.id }}" method="POST" class="inline" onsubmit="return confirm('주문 전체를 취소하시겠습니까?');">
                            <button type="submit" class="text-xs font-black text-red-500 bg-red-50 px-4 py-2 rounded-xl border border-red-100 hover:bg-red-100 transition">전체 주문 취소</button>
                        </form>
                    </div>
                    {% endif %}
                </div>
                    {% endfor %}
                    </div>
                    <button type="button" id="mypage-orders-fold-btn" class="hidden w-full mt-4 py-3 rounded-xl bg-gray-100 text-gray-500 font-bold text-xs hover:bg-gray-200 transition">목록 접기</button>
                </div>
                {% endif %}
            {% else %}
                <div class="py-32 text-center bg-white rounded-[2.5rem] border-2 border-dashed border-gray-100">
                    <p class="text-gray-300 text-lg font-black">아직 주문 내역이 없습니다. 😊</p>
                </div>
            {% endif %}
        </div>
    </div>

    <div id="receipt-modal" class="fixed inset-0 bg-black/60 z-[6000] hidden flex items-center justify-center p-4 backdrop-blur-sm">
        <div id="printable-receipt" class="bg-white w-full max-w-sm rounded-2xl overflow-hidden shadow-2xl animate-in zoom-in duration-200 flex flex-col">
            <div class="p-5 bg-gray-50 border-b border-gray-100 flex justify-between items-center no-print">
                <h4 class="text-xs font-black uppercase tracking-widest text-gray-500">신용카드 매출전표</h4>
                <button onclick="closeReceiptModal()" class="text-gray-300 text-2xl hover:text-black transition">✕</button>
            </div>
            
            <div class="p-8 space-y-8 text-left bg-white">
                <div class="text-center border-b-2 border-gray-800 pb-6">
                    <h3 class="text-2xl font-black text-gray-900 mb-2 italic">바구니삼촌</h3>
                    <div class="text-[10px] text-gray-500 font-bold space-y-1">
                        <p>사업자번호: 472-93-02262</p>
                        <p>대표: 금창권 | 고객센터: 1666-8320</p>
                        <p>인천광역시 연수구 하모니로158, D동 317호</p>
                    </div>
                </div>

                <div class="space-y-5 font-bold">
                    <div class="flex justify-between text-xs font-black"><span class="text-gray-400">주문번호</span><span id="modal-order-id" class="text-gray-700"></span></div>
                    <div>
                        <p class="text-[10px] text-gray-400 uppercase font-black mb-2 tracking-widest">구매 내역</p>
                        <p id="modal-items" class="text-gray-800 text-sm leading-relaxed whitespace-pre-wrap border-y border-gray-50 py-4 font-black"></p>
                    </div>
                    <div>
                        <p class="text-[10px] text-gray-400 uppercase font-black mb-2 tracking-widest">배송지</p>
                        <p id="modal-address" class="text-gray-700 text-xs font-black"></p>
                    </div>
                </div>

                <div class="pt-6 border-t-4 border-double border-gray-200 flex justify-between items-center">
                    <span class="text-base font-black text-gray-800">합계 금액</span>
                    <span id="modal-total" class="text-3xl font-black text-teal-600 italic tracking-tighter"></span>
                </div>
                <div class="text-center opacity-30 pt-4"><p class="text-[9px] font-black uppercase tracking-[0.4em]">이용해 주셔서 감사합니다</p></div>
            </div>

            <div class="p-6 bg-gray-50 flex gap-3 no-print">
                <button onclick="closeReceiptModal()" class="flex-1 py-5 bg-gray-200 text-gray-500 rounded-2xl text-sm font-black">닫기</button>
                <button onclick="printReceipt()" class="flex-[2] py-5 bg-gray-800 text-white rounded-2xl text-sm font-black shadow-lg hover:bg-black transition">출력하기</button>
            </div>
        </div>
    </div>

    <div id="review-modal" class="fixed inset-0 bg-black/60 z-[6000] hidden flex items-center justify-center p-4 backdrop-blur-sm">
        <div class="bg-white w-full max-w-sm rounded-[2.5rem] overflow-hidden shadow-2xl">
            <div class="p-6 bg-orange-500 text-white flex justify-between items-center">
                <h4 class="text-base font-black">📸 소중한 후기 작성</h4>
                <button onclick="closeReviewModal()" class="text-white/60 text-2xl hover:text-white transition">✕</button>
            </div>
            <form action="/review/add" method="POST" enctype="multipart/form-data" class="p-8 space-y-6 text-left">
                <input type="hidden" name="order_id" id="review-order-id">
                <input type="hidden" name="rating" id="review-rating-value" value="5">
                <div>
                    <p id="review-product-name" class="text-gray-800 font-black text-sm mb-4"></p>
                    <div class="flex gap-2 text-3xl text-gray-200" id="star-rating-container">
                        {% for i in range(1, 6) %}<i class="fas fa-star cursor-pointer transition-colors" data-value="{{i}}"></i>{% endfor %}
                    </div>
                </div>
                <div class="space-y-2">
                    <label class="text-[10px] text-gray-400 font-black ml-2 uppercase">사진 첨부 (선택)</label>
                    <input type="file" name="review_image" id="review_image_input" class="w-full text-xs p-4 bg-gray-50 rounded-2xl border border-dashed border-gray-200" accept="image/*">
                    <div id="review_image_preview" class="hidden mt-2 rounded-xl overflow-hidden bg-gray-100 border border-gray-200 max-h-32"><img id="review_image_preview_img" src="" alt="" class="w-full h-full object-contain max-h-32"></div>
                </div>
                <textarea name="content" class="w-full p-5 h-32 bg-gray-50 rounded-2xl border-none text-sm font-black" placeholder="맛과 신선함은 어땠나요? 다른 이웃들을 위해 솔직한 후기를 남겨주세요! 😊" required></textarea>
                <button type="submit" class="w-full py-5 bg-teal-600 text-white rounded-[1.5rem] text-base font-black shadow-xl shadow-teal-100 hover:bg-teal-700 transition">등록 완료</button>
            </form>
        </div>
    </div>

    <style>
        @media print {
            .no-print { display: none !important; }
            body * { visibility: hidden; }
            #printable-receipt, #printable-receipt * { visibility: visible; }
            #printable-receipt { position: absolute; left: 0; top: 0; width: 100%; box-shadow: none; border: none; }
        }
    </style>

    <script>
        function toggleAddressEdit() {
            const f = document.getElementById('address-edit-form');
            const d = document.getElementById('address-display');
            const b = document.getElementById('edit-btn');
            const isHidden = f.classList.contains('hidden');
            f.classList.toggle('hidden', !isHidden);
            d.classList.toggle('hidden', isHidden);
            b.innerHTML = isHidden ? '<i class="fas fa-times"></i> 취소' : '<i class="fas fa-edit mr-1"></i> 주소 수정';
        }

        function openReceiptModal(id, items, total, address, orderFullId, deliveryFee) {
            document.getElementById('modal-order-id').innerText = orderFullId || ('ORD-' + id);
            let itemText = items.replace(/\\\\n/g, '\\n');
            const fee = parseInt(deliveryFee) || 0;
            if (fee > 0) { itemText += "\\n[배송비] --- " + fee.toLocaleString() + "원"; }
            else { itemText += "\\n[배송비] --- 0원 (무료)"; }
            document.getElementById('modal-items').innerText = itemText;
            document.getElementById('modal-address').innerText = address;
            document.getElementById('modal-total').innerText = Number(total).toLocaleString() + '원';
            document.getElementById('receipt-modal').classList.remove('hidden');
        }

        function closeReceiptModal() { document.getElementById('receipt-modal').classList.add('hidden'); }
        function printReceipt() { window.print(); }

        const stars = document.querySelectorAll('#star-rating-container i');
        const ratingInput = document.getElementById('review-rating-value');
        stars.forEach(star => {
            star.addEventListener('click', function() {
                ratingInput.value = this.dataset.value;
                updateStars(this.dataset.value);
            });
            star.addEventListener('mouseover', function() { updateStars(this.dataset.value); });
            star.addEventListener('mouseleave', function() { updateStars(ratingInput.value); });
        });
        function updateStars(value) {
            stars.forEach(s => {
                const active = parseInt(s.dataset.value) <= parseInt(value);
                s.classList.toggle('text-orange-400', active);
                s.classList.toggle('text-gray-200', !active);
            });
        }

        function openReviewModal(oid, pName) {
            document.getElementById('review-order-id').value = oid;
            document.getElementById('review-product-name').innerText = pName;
            ratingInput.value = 5; updateStars(5);
            var inp = document.getElementById('review_image_input');
            if (inp) { inp.value = ''; }
            var prev = document.getElementById('review_image_preview');
            if (prev) { prev.classList.add('hidden'); }
            document.getElementById('review-modal').classList.remove('hidden');
        }
        function closeReviewModal() { document.getElementById('review-modal').classList.add('hidden'); }
        var reviewImageInput = document.getElementById('review_image_input');
        if (reviewImageInput) {
            reviewImageInput.addEventListener('change', function() {
                var prev = document.getElementById('review_image_preview');
                var img = document.getElementById('review_image_preview_img');
                if (!prev || !img) return;
                if (this.files && this.files[0]) {
                    var r = new FileReader();
                    r.onload = function(e) { img.src = e.target.result; prev.classList.remove('hidden'); };
                    r.readAsDataURL(this.files[0]);
                } else { prev.classList.add('hidden'); img.src = ''; }
            });
        }

        (function mypageOrdersMore() {
            var moreBtn = document.getElementById('mypage-orders-more-btn');
            var foldBtn = document.getElementById('mypage-orders-fold-btn');
            var olderWrap = document.getElementById('mypage-orders-older');
            if (moreBtn && olderWrap) {
                moreBtn.addEventListener('click', function() {
                    olderWrap.classList.remove('hidden');
                    moreBtn.classList.add('hidden');
                    if (foldBtn) foldBtn.classList.remove('hidden');
                });
            }
            if (foldBtn && olderWrap) {
                foldBtn.addEventListener('click', function() {
                    olderWrap.classList.add('hidden');
                    if (moreBtn) moreBtn.classList.remove('hidden');
                    foldBtn.classList.add('hidden');
                });
            }
            var searchInput = document.getElementById('mypage-order-search');
            var cards = document.querySelectorAll('.mypage-order-card');
            if (searchInput && cards.length) {
                searchInput.addEventListener('input', function() {
                    var q = (this.value || '').trim().toLowerCase();
                    cards.forEach(function(card) {
                        var text = (card.getAttribute('data-order-search') || '').toLowerCase();
                        card.style.display = q === '' || text.indexOf(q) !== -1 ? '' : 'none';
                    });
                    if (q && olderWrap && olderWrap.classList.contains('hidden')) {
                        olderWrap.classList.remove('hidden');
                        if (moreBtn) moreBtn.classList.add('hidden');
                        if (foldBtn) foldBtn.classList.remove('hidden');
                    }
                    if (moreBtn) moreBtn.style.display = olderWrap && olderWrap.classList.contains('hidden') ? '' : 'none';
                    if (foldBtn) foldBtn.style.display = olderWrap && !olderWrap.classList.contains('hidden') ? '' : 'none';
                });
            }
        })();

        (function pushEnable() {
            var block = document.getElementById('push-enable-block');
            var btn = document.getElementById('push-enable-btn');
            var status = document.getElementById('push-enable-status');
            if (!block || !btn) return;
            function setStatus(t, isErr) { if (status) { status.textContent = t; status.className = 'ml-3 text-xs ' + (isErr ? 'text-red-600' : 'text-teal-600'); } }
            btn.addEventListener('click', function() {
                if (!('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) {
                    setStatus('Chrome 또는 Safari 앱을 열고, 주소창에 이 사이트 주소를 입력해 접속한 뒤 다시 시도해 주세요. 카카오·네이버 등 앱 안에서 연 창에서는 푸시 알림을 지원하지 않습니다.', true); return;
                }
                if (typeof window.isSecureContext !== 'undefined' && !window.isSecureContext) {
                    setStatus('푸시 알림은 https 주소에서만 사용할 수 있습니다. 주소가 https:// 로 시작하는지 확인해 주세요.', true); return;
                }
                if (Notification.permission === 'denied') { setStatus('알림이 차단되었습니다. 브라우저 설정에서 허용해 주세요.', true); return; }
                setStatus('처리 중...', false);
                fetch('/api/push/vapid-public').then(function(r) { return r.json(); }).then(function(d) {
                    if (d.error || !d.publicKey) { setStatus('알림 기능이 설정되지 않았습니다.', true); return; }
                    var key = d.publicKey.replace(/-/g, '+').replace(/_/g, '/');
                    var keyBytes = new Uint8Array(atob(key).split('').map(function(c) { return c.charCodeAt(0); }));
                    return navigator.serviceWorker.ready.then(function(reg) {
                        return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes });
                    }).then(function(sub) {
                        function abToB64Url(buf) { var b = new Uint8Array(buf); var s = ''; for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return btoa(s).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); }
                        var subJson = { endpoint: sub.endpoint, keys: { p256dh: abToB64Url(sub.getKey('p256dh')), auth: abToB64Url(sub.getKey('auth')) } };
                        return fetch('/api/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subscription: subJson }), credentials: 'same-origin' });
                    }).then(function(r) { return r.json(); }).then(function(d) {
                        if (d.success) { setStatus('알림이 켜졌습니다.'); btn.disabled = true; btn.textContent = '알림 켜짐'; } else { setStatus(d.message || '등록 실패', true); }
                    });
                }).catch(function() { setStatus('등록 중 오류가 났습니다.', true); });
            });
        })();
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, recent_orders=recent_orders, older_orders=older_orders, recent_items_with_date=recent_items_with_date, Review=Review, unread_message_count=unread_message_count, push_already_set=push_already_set)
def _recalc_order_from_items(order):
    """OrderItem 기준으로 주문 합계·배송비·product_details 재계산 (취소 반영)"""
    remaining = OrderItem.query.filter_by(order_id=order.id, cancelled=False).all()
    if not remaining:
        order.status = '결제취소'
        order.product_details = ''
        order.total_price = 0
        order.delivery_fee = 0
        order.tax_free_amount = 0
        return
    cat_groups = {}
    for oi in remaining:
        cat_groups.setdefault(oi.product_category, []).append(f"{oi.product_name}({oi.quantity})")
    order.product_details = " | ".join([f"[{cat}] {', '.join(prods)}" for cat, prods in cat_groups.items()])
    cat_price_sums = {}
    for oi in remaining:
        cat_price_sums[oi.product_category] = cat_price_sums.get(oi.product_category, 0) + (oi.price * oi.quantity)
    order.delivery_fee = sum(1900 + (1900 if amt >= 50000 else 0) for amt in cat_price_sums.values())
    order.total_price = sum(oi.price * oi.quantity for oi in remaining) + order.delivery_fee
    order.tax_free_amount = sum(oi.price * oi.quantity for oi in remaining if oi.tax_type == '면세')

@app.route('/order/cancel_item/<int:order_id>/<int:item_id>', methods=['POST'])
@login_required
def order_cancel_item(order_id, item_id):
    """품목별 부분 취소 (토스 부분 취소 API 호출)"""
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("본인 주문만 취소할 수 있습니다."); return redirect('/mypage')
    if order.status != '결제완료':
        flash("취소 가능한 상태가 아닙니다."); return redirect('/mypage')
    oi = OrderItem.query.filter_by(id=item_id, order_id=order_id).first()
    if not oi or oi.cancelled:
        flash("해당 품목을 취소할 수 없습니다."); return redirect('/mypage')
    if getattr(oi, 'item_status', None) in ('배송요청', '배송중', '배송완료'):
        flash("배송 요청/진행된 품목은 취소할 수 없습니다."); return redirect('/mypage')

    cancel_amount = oi.price * oi.quantity
    tax_free_cancel = (oi.price * oi.quantity) if (oi.tax_type == '면세') else 0

    # 토스페이먼츠 부분 취소 API
    if order.payment_key:
        url = f"https://api.tosspayments.com/v1/payments/{order.payment_key}/cancel"
        auth_key = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
        body = {"cancelAmount": cancel_amount, "cancelReason": "품목 부분 취소"}
        if tax_free_cancel:
            body["taxFreeAmount"] = tax_free_cancel
        res = requests.post(url, json=body, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
        if res.status_code not in (200, 201):
            try:
                err = res.json()
                flash(err.get("message", "환불 요청이 실패했습니다. 고객센터로 문의해 주세요."))
            except Exception:
                flash("환불 요청이 실패했습니다. 고객센터로 문의해 주세요.")
            return redirect('/mypage')

    oi.cancelled = True
    oi.item_status = '부분취소'
    p = Product.query.get(oi.product_id)
    if p:
        p.stock += oi.quantity
    _recalc_order_from_items(order)
    db.session.commit()
    title, body = get_template_content('part_cancelled', order_id=order.order_id)
    send_message(order.user_id, title, body, 'part_cancelled', order.id)
    db.session.commit()
    flash("해당 품목이 취소되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다.")
    return redirect('/mypage')

@app.route('/order/cancel/<int:oid>', methods=['POST'])
@login_required
def order_cancel(oid):
    """전액 결제 취소 (재고 복구 + 토스 전액 취소)"""
    order = Order.query.get_or_404(oid)
    if order.user_id != current_user.id: return redirect('/mypage')
    if order.status != '결제완료':
        flash("취소 가능한 상태가 아닙니다. 이미 배송이 시작되었을 수 있습니다."); return redirect('/mypage')
    order_items_check = OrderItem.query.filter_by(order_id=order.id).all()
    if order_items_check and any(not getattr(oi, 'cancelled', False) and getattr(oi, 'item_status', None) in ('배송요청', '배송중', '배송완료') for oi in order_items_check):
        flash("배송 요청/진행된 품목이 있어 주문 전체 취소가 불가능합니다."); return redirect('/mypage')

    # 토스페이먼츠 전액 취소
    if order.payment_key and order.total_price and order.total_price > 0:
        url = f"https://api.tosspayments.com/v1/payments/{order.payment_key}/cancel"
        auth_key = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
        res = requests.post(url, json={"cancelReason": "주문 전액 취소"}, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
        if res.status_code not in (200, 201):
            try:
                err = res.json()
                flash(err.get("message", "환불 요청이 실패했습니다. 고객센터로 문의해 주세요."))
            except Exception:
                flash("환불 요청이 실패했습니다. 고객센터로 문의해 주세요.")
            return redirect('/mypage')

    order.status = '결제취소'
    title, body = get_template_content('order_cancelled', order_id=order.order_id)
    send_message(order.user_id, title, body, 'order_cancelled', order.id)
    # 재고 복구: OrderItem 있으면 품목별, 없으면 product_details 파싱
    order_items = OrderItem.query.filter_by(order_id=order.id).all()
    if order_items:
        for oi in order_items:
            if not oi.cancelled:
                p = Product.query.get(oi.product_id)
                if p: p.stock += oi.quantity
        for oi in order_items:
            oi.cancelled = True
    else:
        try:
            parts = order.product_details.split(' | ')
            for part in parts:
                item_match = re.search(r'\] (.*?)\((\d+)\)', part)
                if item_match:
                    p_name, qty = item_match.groups()
                    p = Product.query.filter_by(name=p_name.strip()).first()
                    if p: p.stock += int(qty)
        except Exception as e:
            print(f"Stock recovery error: {str(e)}")
    db.session.commit()
    flash("결제가 성공적으로 취소되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다.")
    return redirect('/mypage')

@app.route('/review/add', methods=['POST'])
@login_required
def review_add():
    """사진 리뷰 등록 (주문당 1개 제한 로직 적용)"""
    oid = request.form.get('order_id')
    content = request.form.get('content')
    
    # 1. [검증] 해당 주문에 이미 작성된 후기가 있는지 체크
    existing_review = Review.query.filter_by(order_id=oid).first()
    if existing_review:
        flash("이미 후기를 작성하신 주문입니다. 😊")
        return redirect('/mypage')
        
    order = Order.query.get(oid)
    if not order or order.user_id != current_user.id: 
        return redirect('/mypage')
    
    img_path = save_review_image(request.files.get('review_image'))
    
    # 리뷰 대상 상품 정보 파싱
    p_name = order.product_details.split('(')[0].split(']')[-1].strip()
    match = re.search(r'\[(.*?)\] (.*?)\(', order.product_details)
    p_id = 0
    category_id = None
    if match:
        first_p = Product.query.filter_by(name=match.group(2).strip()).first()
        if first_p:
            p_id = first_p.id
            cat = Category.query.filter_by(name=first_p.category).first()
            if cat:
                category_id = cat.id  # 판매자(카테고리) id별로 후기 묶음

    # 2. [저장] Review 생성 시 order_id, category_id(판매자) 함께 기록
    new_review = Review(
        user_id=current_user.id,
        user_name=current_user.name,
        product_id=p_id,
        product_name=p_name,
        category_id=category_id,
        content=content,
        image_url=img_path or None,
        order_id=oid
    )
    db.session.add(new_review)
    db.session.commit()
    flash("소중한 후기가 등록되었습니다. 감사합니다!"); 
    return redirect('/mypage')

@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    """장바구니 추가 (판매중 체크 포함)"""
    p = Product.query.get_or_404(pid)
    if (p.deadline and p.deadline < datetime.now()) or p.stock <= 0: 
        return jsonify({"success": False, "message": "판매가 마감된 상품입니다."})
    
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, product_category=p.category, price=p.price, tax_type=p.tax_type))
    
    db.session.commit()
    total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar() or 0
    return jsonify({"success": True, "cart_count": total_qty})

@app.route('/cart/minus/<int:pid>', methods=['POST'])
@login_required
def minus_cart(pid):
    """장바구니 수량 차감"""
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item:
        if item.quantity > 1: item.quantity -= 1
        else: db.session.delete(item)
    db.session.commit()
    total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar() or 0
    return jsonify({"success": True, "cart_count": total_qty})

@app.route('/cart/delete/<int:pid>', methods=['POST'])
@login_required
def delete_cart(pid): 
    """장바구니 항목 삭제"""
    Cart.query.filter_by(user_id=current_user.id, product_id=pid).delete(); db.session.commit(); return redirect('/cart')

@app.route('/cart')
@login_required
def cart():
    """장바구니 화면 (한글화 및 폰트 사이즈 최적화 버전). 고객 주소 없으면 마이페이지로 이동."""
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if items and not (current_user.address or "").strip():
        flash("주문하려면 배송지 주소를 먼저 입력해 주세요.")
        return redirect(url_for("mypage", need_address=1))

    # 배송비: 카테고리별 1,900원 + (카테고리 합계 50,000원 이상이면 1,900원 추가) — 합산이 아닌 카테고리별 따로 계산
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum(1900 + (1900 if amt >= 50000 else 0) for amt in cat_price_sums.values()) if items else 0
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    
    # 상단 헤더 및 빈 장바구니 처리
    content = f"""
    <div class="max-w-4xl mx-auto py-10 md:py-20 px-4 md:px-6 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-10 border-l-8 border-teal-600 pl-4 md:pl-6 tracking-tighter uppercase italic">
            장바구니
        </h2>
        
        <div class="bg-white rounded-[2rem] md:rounded-[3rem] shadow-xl border border-gray-50 overflow-hidden">
            {" " if items else f'''
            <div class="py-32 md:py-48 text-center">
                <p class="text-7xl md:text-8xl mb-8 opacity-20">🧺</p>
                <p class="text-lg md:text-2xl mb-10 text-gray-400 font-bold">장바구니가 비어있습니다.</p>
                <a href="/" class="inline-block bg-teal-600 text-white px-10 py-4 rounded-full shadow-lg font-black text-base md:text-lg hover:bg-teal-700 transition">
                    인기 상품 보러가기
                </a>
            </div>
            '''}
    """

    # 장바구니 상품 리스트
    if items:
        content += '<div class="p-6 md:p-12 space-y-8">'
        for i in items:
            content += f"""
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-gray-50 pb-8 gap-4">
                <div class="flex-1 text-left">
                    <p class="text-[10px] text-teal-600 font-black mb-1 uppercase tracking-widest">[{ i.product_category }]</p>
                    <p class="font-black text-lg md:text-xl text-gray-800 leading-tight mb-2">{ i.product_name }</p>
                    <p class="text-gray-400 font-bold text-sm">{ "{:,}".format(i.price) }원</p>
                </div>
                
                <div class="flex items-center justify-between w-full md:w-auto gap-4">
                    <div class="flex items-center gap-6 bg-gray-50 px-5 py-3 rounded-2xl border border-gray-100">
                        <button onclick="minusFromCart({i.product_id})" class="text-gray-400 hover:text-red-500 transition text-xl">
                            <i class="fas fa-minus"></i>
                        </button>
                        <span class="font-black text-lg w-6 text-center">{ i.quantity }</span>
                        <button onclick="addToCart({i.product_id})" class="text-gray-400 hover:text-teal-600 transition text-xl">
                            <i class="fas fa-plus"></i>
                        </button>
                    </div>
                    
                    <form action="/cart/delete/{i.product_id}" method="POST" class="md:ml-4">
                        <button class="text-gray-200 hover:text-red-500 transition text-2xl p-2">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </form>
                </div>
            </div>
            """
        
        # 결제 요약 영역
        content += f"""
            <div class="bg-gray-50 p-8 md:p-10 rounded-[2rem] md:rounded-[2.5rem] space-y-4 mt-12 border border-gray-100">
                <div class="flex justify-between text-sm md:text-base text-gray-500 font-bold">
                    <span>주문 상품 합계</span>
                    <span>{ "{:,}".format(subtotal) }원</span>
                </div>
                <div class="flex justify-between text-sm md:text-base text-orange-500 font-bold">
                    <span>카테고리별 배송료</span>
                    <span>+ { "{:,}".format(delivery_fee) }원</span>
                </div>
                <div class="flex justify-between items-center pt-6 border-t border-gray-200 mt-6">
                    <span class="text-lg md:text-xl text-gray-800 font-black">최종 결제 금액</span>
                    <span class="text-3xl md:text-5xl text-teal-600 font-black italic tracking-tighter">
                        { "{:,}".format(total) }원
                    </span>
                </div>
                <p class="text-[10px] md:text-xs text-gray-400 mt-6 leading-relaxed font-medium">
                    ※ 배송비: 카테고리별 1,900원. 카테고리별 합계금액이 50,000원 이상이면 해당 카테고리에 1,900원 추가 (카테고리마다 따로 계산).
                </p>
                <p class="text-[10px] md:text-xs text-teal-600 mt-2 font-bold">💡 다음 단계에서 배송지 확인·변경이 가능하며, 변경 주소를 회원정보에 저장할 수 있습니다.</p>
            </div>
            
            <a href="/order/confirm" class="block text-center bg-teal-600 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2rem] font-black text-xl md:text-2xl shadow-xl shadow-teal-100 mt-12 hover:bg-teal-700 hover:-translate-y-1 transition active:scale-95">
                주문하기
            </a>
        </div>
        """

    content += "</div>"
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, subtotal=subtotal, delivery_fee=delivery_fee, total=total)
@app.route('/order/confirm')
@login_required
def order_confirm():
    """결제 전 확인. 1차 주소 확인(일반 구역) 통과 시 바로 결제 페이지로, 미통과 시 2차 퀵 구역 확인 후 추가배송료 적용."""
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    
    # 1차: 주소(배송 구역) 확인
    zone_type = get_delivery_zone_type(current_user.address or "")
    
    # 1차 통과(일반 구역) → 바로 결제 모듈 호출: session 세팅 후 결제 페이지로 리다이렉트
    if zone_type == 'normal':
        session['order_address'] = current_user.address or ""
        session['order_address_detail'] = current_user.address_detail or ""
        session['order_entrance_pw'] = current_user.entrance_pw or ""
        session['save_address_to_profile'] = False
        session['points_used'] = 0
        session['quick_extra_fee'] = 0
        return redirect(url_for('order_payment'))
    
    # 1차 미통과: 퀵 구역 또는 배송 불가. 퀵이면 2차 추가배송료 적용 후 결제 가능
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum(1900 + (1900 if amt >= 50000 else 0) for amt in cat_price_sums.values())
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    
    _, min_order_to_use, max_points_per_order = _get_point_config()
    user_points = getattr(current_user, 'points', 0) or 0
    can_use_points = total >= min_order_to_use and user_points > 0
    max_use = min(user_points, max_points_per_order, total) if can_use_points else 0
    
    quick_extra_fee, quick_extra_message = get_quick_extra_config()
    is_songdo = zone_type in ('normal', 'quick')
    is_quick_zone = (zone_type == 'quick')
    total_with_quick = total + quick_extra_fee if is_quick_zone else total

    content = f"""
    <div class="max-w-xl mx-auto py-12 md:py-20 px-4 md:px-6 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-10 border-b-4 border-teal-600 pb-4 text-center uppercase italic">
            주문 확인 (2차: 퀵 구역 확인)
        </h2>
        
        <div class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] shadow-2xl border border-gray-50 space-y-10 text-left">
            <div class="p-4 rounded-2xl bg-gray-100 border border-gray-200 text-[11px] text-gray-600 font-bold">
                <p class="mb-1">1차: 일반 배송 구역이 아닙니다.</p>
                <p class="text-amber-700 font-black">2차: 퀵 지정 구역 적용 여부를 확인해 주세요.</p>
            </div>
            
            <div class="p-6 md:p-8 {'bg-amber-50 border-amber-200' if zone_type == 'quick' else 'bg-red-50 border-red-100'} rounded-3xl border relative overflow-hidden">
                <span class="{'text-amber-700' if zone_type == 'quick' else 'text-red-600'} text-[10px] block uppercase font-black mb-3 tracking-widest">
                    배송지 정보
                </span>
                <p class="text-sm text-gray-500 mb-3 font-bold leading-relaxed">주소 수정은 마이페이지에서만 가능합니다. 수정 후 장바구니에서 다시 주문하기를 눌러 주세요.</p>
                <div id="address-display-block">
                    <p class="text-lg md:text-xl text-gray-800 font-black leading-snug" id="display-address-text">
                        { (current_user.address or '정보 없음').replace('<', '&lt;').replace('>', '&gt;') }<br>
                        <span class="text-gray-500">{ (current_user.address_detail or '').replace('<', '&lt;').replace('>', '&gt;') }</span>
                    </p>
                    <a href="/mypage?from=cart" class="inline-flex items-center gap-2 mt-4 px-5 py-2.5 bg-teal-600 text-white rounded-xl text-sm font-black hover:bg-teal-700 transition">
                        <i class="fas fa-edit"></i> 마이페이지에서 주소 수정
                    </a>
                </div>
                <p class="mt-4 font-black text-sm" id="zone-status-msg">
                    {'<span class="text-amber-700 flex items-center gap-2"><i class="fas fa-truck-fast"></i> 2차 확인: 퀵 지정 구역입니다. 추가 배송료 동의 시 주문 가능.</span>' if zone_type == 'quick' else '<span class="text-red-600 flex items-center gap-2"><i class="fas fa-exclamation-triangle"></i> 2차: 퀵 지정 구역도 아닙니다. 배송 불가.</span>'}
                </p>
            </div>

            {f'<div class="p-6 bg-red-100 rounded-2xl text-red-700 text-xs md:text-sm font-bold leading-relaxed">⚠️ 1차·2차 모두 해당 구역이 없습니다. 배송 가능 주소로 수정해 주세요.</div>' if zone_type == 'unavailable' else ''}
            {f'''<div class="p-6 bg-amber-50 border border-amber-200 rounded-2xl text-amber-900 text-xs md:text-sm font-bold leading-relaxed">
                <p class="mb-2 font-black">2차: 퀵 지정 구역 — 추가 배송료 적용</p>
                <p class="mb-3">{ quick_extra_message }</p>
                <p class="mb-3">퀵 추가 배송료: <strong>{ "{:,}".format(quick_extra_fee) }원</strong></p>
                <label class="flex items-start gap-3 cursor-pointer mt-4">
                    <input type="checkbox" id="quick_agree" class="mt-1 w-4 h-4 rounded border-amber-400 text-amber-600 focus:ring-amber-500">
                    <span>위 추가 배송료에 동의하고 퀵으로 주문합니다.</span>
                </label>
            </div>''' if is_quick_zone else ''}

            <div class="space-y-4 pt-4">
                <div class="flex justify-between items-end font-black">
                    <span class="text-gray-400 text-xs uppercase tracking-widest">주문 금액</span>
                    <span class="text-2xl text-gray-700">{ "{:,}".format(total) }원</span>
                </div>
                {f'''<div class="bg-amber-50 p-5 rounded-2xl border border-amber-100 text-[10px] md:text-xs text-amber-800 font-bold">
                    🎁 보유 포인트: { "{:,}".format(user_points) }원 ({ "{:,}".format(min_order_to_use) }원 이상 구매 시 최대 { "{:,}".format(max_points_per_order) }원까지 사용 가능)
                    <div class="mt-3 flex items-center gap-2 flex-wrap">
                        <label class="font-black">사용할 포인트</label>
                        <input type="number" id="points_used_input" min="0" max="{ max_use }" value="0" step="1" class="w-28 border border-amber-200 rounded-lg px-2 py-1.5 text-sm font-black">
                        <span>원 (최대 { "{:,}".format(max_use) }원)</span>
                    </div>
                </div>''' if can_use_points else f'<div class="bg-gray-50 p-4 rounded-2xl text-[10px] text-gray-500 font-bold">보유 포인트: { "{:,}".format(user_points) }원. { min_order_to_use and total < min_order_to_use and ("{:,}".format(min_order_to_use) + "원 이상 구매 시 사용 가능합니다.") or "사용 가능한 포인트가 없습니다." }</div>'}
                <div class="flex justify-between items-end font-black border-t border-gray-100 pt-4">
                    <span class="text-gray-400 text-xs uppercase tracking-widest">최종 결제 금액</span>
                    <span class="text-4xl md:text-5xl text-teal-600 font-black italic underline underline-offset-8" id="final_amount_display">{ "{:,}".format(total if not is_quick_zone else total) }원</span>
                </div>
                {f'<p class="text-[10px] text-amber-700 font-bold">퀵 동의 시 결제 금액: <span id="final_with_quick_display">{ "{:,}".format(total_with_quick) }원</span></p>' if is_quick_zone else ''}
                <div class="bg-orange-50 p-5 rounded-2xl border border-orange-100 text-[10px] md:text-xs text-orange-700 font-bold leading-relaxed">
                    📢 배송비: 카테고리별 1,900원, 카테고리 합계 50,000원 이상이면 1,900원 추가. 현재 배송비: { "{:,}".format(delivery_fee) }원
                </div>
            </div>

            <div class="p-6 md:p-8 bg-gray-50 rounded-3xl text-[11px] md:text-xs text-gray-500 space-y-6 font-black border border-gray-100">
                <div class="bg-gray-100 border border-gray-200 rounded-2xl p-4 text-gray-700 text-[10px] md:text-[11px] leading-relaxed">
                    <span class="font-extrabold text-gray-900">⚠️ 주문 전 필수 확인</span>
                    <ul class="mt-2 pl-4 space-y-1 list-disc">
                        <li>장바구니 단계에서는 언제든지 주문 취소가 가능합니다.</li>
                        <li>공동구매·실시간 수급 특성상 도매처 품절·수급 변동으로 <b>부분 또는 전체 취소</b>가 발생할 수 있습니다.</li>
                        <li>비정상적·상업적 재판매·시스템 악용 시 <b>관리자 판단에 따라 사전 안내 후 취소</b>될 수 있습니다.</li>
                        <li>상품 준비가 시작된 이후에는 취소·변경이 제한될 수 있습니다.</li>
                    </ul>
                    <p class="mt-2"><a href="/guide" class="text-teal-600 hover:underline font-bold">이용안내 자세히 보기</a></p>
                </div>
                <div class="bg-amber-50/80 border border-amber-200 rounded-2xl p-4 text-amber-800 text-[10px] md:text-[11px] leading-relaxed">
                    <span class="font-extrabold">⚠️ 주문·결제 전 취소 안내</span><br>
                    공동구매 방식의 구매 특성상 재고 소진 시 품절 처리될 수 있으며, 관리자 판단에 따라 상업적·비상식적·악의적 이용으로 보이는 경우 해당 품목이 부분 취소될 수 있습니다.
                </div>
                <label class="flex items-start gap-4 cursor-pointer group">
                    <input type="checkbox" id="consent_partial_cancel" class="mt-1 w-4 h-4 rounded-full border-gray-300 text-teal-600 focus:ring-teal-500" required>
                    <span class="group-hover:text-gray-800 transition leading-relaxed">
                        [필수] 위 취소 안내(품절·부분 취소 가능)를 확인했으며 이에 동의합니다.
                    </span>
                </label>
                <label class="flex items-start gap-4 pt-4 border-t border-gray-200 cursor-pointer group">
                    <input type="checkbox" id="consent_agency" class="mt-1 w-4 h-4 rounded-full border-gray-300 text-teal-600 focus:ring-teal-500" required>
                    <span class="group-hover:text-gray-800 transition leading-relaxed">
                        [필수] 본인은 바구니삼촌이 상품 판매자가 아니며, 요청에 따라 구매 및 배송을 대행하는 서비스임을 확인하고 이에 동의합니다.
                    </span>
                </label>
                <label class="flex items-start gap-4 pt-4 border-t border-gray-200 cursor-pointer group">
                    <input type="checkbox" id="consent_third_party_order" class="mt-1 w-4 h-4 rounded-full border-gray-300 text-teal-600 focus:ring-teal-500" required>
                    <span class="group-hover:text-gray-800 transition leading-relaxed">
                        [필수] 개인정보 제3자 제공 동의: 원활한 배송 처리를 위해 판매처 및 배송 담당자에게 정보가 제공됨을 확인했습니다.
                    </span>
                </label>
            </div>

            <form id="payForm" action="/order/payment" method="POST" class="mt-4">
                <input type="hidden" name="points_used" id="points_used_hidden" value="0">
                <input type="hidden" name="quick_agree" id="quick_agree_hidden" value="0">
                <input type="hidden" name="order_address" id="order_address_hidden" value="{ (current_user.address or '').replace('&', '&amp;').replace('"', '&quot;') }">
                <input type="hidden" name="order_address_detail" id="order_address_detail_hidden" value="{ (current_user.address_detail or '').replace('&', '&amp;').replace('"', '&quot;') }">
                <input type="hidden" name="order_entrance_pw" id="order_entrance_pw_hidden" value="{ (current_user.entrance_pw or '').replace('&', '&amp;').replace('"', '&quot;') }">
                <input type="hidden" name="save_address_to_profile" id="save_address_to_profile_hidden" value="0">
                {f'<button type="button" id="payBtn" onclick="startPayment()" class="w-full bg-teal-600 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2rem] font-black text-xl md:text-2xl shadow-xl shadow-teal-100 hover:bg-teal-700 transition active:scale-95">안전 결제하기</button>' if zone_type == 'normal' else f'<button type="button" id="payBtn" onclick="startPayment()" class="w-full bg-amber-500 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2rem] font-black text-xl md:text-2xl shadow-xl hover:bg-amber-600 transition active:scale-95">퀵 추가료 동의 후 결제하기</button>' if zone_type == 'quick' else '<button type="button" class="w-full bg-gray-300 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2rem] font-black text-xl cursor-not-allowed" disabled>배송지를 확인해 주세요</button>'}
            </form>
        </div>
    </div>

    <script>
    var orderTotal = { total };
    var quickExtraFee = { quick_extra_fee };
    var isQuickZone = { 'true' if is_quick_zone else 'false' };
    var totalWithQuick = { total_with_quick };
    function startPayment() {{
        if(!document.getElementById('consent_partial_cancel').checked) {{ alert("주문·결제 전 취소 안내(품절·부분 취소 가능)에 동의해 주세요."); return; }}
        if(!document.getElementById('consent_agency').checked) {{ alert("구매 대행 서비스 이용 동의가 필요합니다."); return; }}
        if(!document.getElementById('consent_third_party_order').checked) {{ alert("개인정보 제공 동의가 필요합니다."); return; }}
        if (isQuickZone) {{
            var q = document.getElementById('quick_agree');
            if (!q || !q.checked) {{ alert("퀵 추가 배송료에 동의해 주세요."); return; }}
            document.getElementById('quick_agree_hidden').value = '1';
        }}
        var ptsInput = document.getElementById('points_used_input');
        var pts = ptsInput ? parseInt(ptsInput.value, 10) || 0 : 0;
        var maxUse = { max_use };
        if (pts < 0) pts = 0;
        if (pts > maxUse) pts = maxUse;
        document.getElementById('points_used_hidden').value = pts;
        document.getElementById('payForm').submit();
    }}
    var ptsIn = document.getElementById('points_used_input');
    if (ptsIn) {{
        ptsIn.addEventListener('input', function() {{
            var v = parseInt(this.value, 10) || 0;
            var m = { max_use };
            if (v > m) this.value = m;
            var base = orderTotal;
            if (isQuickZone) base = totalWithQuick;
            var final = base - (parseInt(this.value, 10) || 0);
            var el = document.getElementById('final_amount_display');
            if (el) el.textContent = final.toLocaleString() + '원';
        }});
    }}
    if (isQuickZone) {{
        var qAgree = document.getElementById('quick_agree');
        if (qAgree) qAgree.addEventListener('change', function() {{
            var el = document.getElementById('final_amount_display');
            if (el) el.textContent = (this.checked ? totalWithQuick : orderTotal).toLocaleString() + '원';
        }});
    }}
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, total=total, delivery_fee=delivery_fee, is_songdo=is_songdo, zone_type=zone_type, quick_extra_fee=quick_extra_fee, quick_extra_message=quick_extra_message, total_with_quick=total_with_quick, is_quick_zone=is_quick_zone, user_points=user_points, max_use=max_use, min_order_to_use=min_order_to_use)
@app.route('/order/payment', methods=['GET', 'POST'])
@login_required
def order_payment():
    """토스페이먼츠 결제창 호출 및 보안 강화 버전"""
    if request.method == 'POST':
        points_used = request.form.get('points_used', '0').strip()
        try:
            points_used = int(points_used) if points_used else 0
        except ValueError:
            points_used = 0
        quick_agree = request.form.get('quick_agree', '0').strip() in ('1', 'on', 'yes')
        order_address = request.form.get('order_address', '').strip()
        order_address_detail = request.form.get('order_address_detail', '').strip()
        order_entrance_pw = request.form.get('order_entrance_pw', '').strip()
        save_address_to_profile = request.form.get('save_address_to_profile', '0').strip() in ('1', 'on', 'yes')
        effective_address = order_address if order_address else (current_user.address or "")
        items = Cart.query.filter_by(user_id=current_user.id).all()
        if not items:
            return redirect('/order/confirm')
        if not is_address_in_delivery_zone(effective_address):
            flash("선택한 배송지는 배송 가능 구역이 아닙니다. 주소를 확인해 주세요.")
            return redirect('/order/confirm')
        zone_type = get_delivery_zone_type(effective_address)
        if zone_type == 'quick' and not quick_agree:
            return redirect('/order/confirm')
        session['order_address'] = effective_address
        session['order_address_detail'] = order_address_detail if order_address else (current_user.address_detail or "")
        session['order_entrance_pw'] = order_entrance_pw if order_address else (current_user.entrance_pw or "")
        session['save_address_to_profile'] = save_address_to_profile
        subtotal = sum(i.price * i.quantity for i in items)
        cat_price_sums = {}
        for i in items:
            cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
        delivery_fee = sum(1900 + (1900 if amt >= 50000 else 0) for amt in cat_price_sums.values())
        total = subtotal + delivery_fee
        quick_extra_fee_val = 0
        if zone_type == 'quick' and quick_agree:
            quick_extra_fee_val, _ = get_quick_extra_config()
            total += quick_extra_fee_val
        _, min_order_to_use, max_points_per_order = _get_point_config()
        user_points = getattr(current_user, 'points', 0) or 0
        if points_used < 0:
            points_used = 0
        if total < min_order_to_use or points_used > min(user_points, max_points_per_order, total):
            points_used = 0
        session['points_used'] = points_used
        session['quick_extra_fee'] = quick_extra_fee_val
        return redirect(url_for('order_payment'))
    items = Cart.query.filter_by(user_id=current_user.id).all()
    effective_addr = session.get('order_address') or current_user.address or ""
    if not items or not is_address_in_delivery_zone(effective_addr):
        return redirect('/order/confirm')
    
    subtotal = sum(i.price * i.quantity for i in items)
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum(1900 + (1900 if amt >= 50000 else 0) for amt in cat_price_sums.values())
    points_used = session.get('points_used', 0) or 0
    quick_extra_fee_val = session.get('quick_extra_fee', 0) or 0
    total_before_points = int(subtotal + delivery_fee + quick_extra_fee_val)
    total = total_before_points - points_used  # 토스에 넘길 실제 결제 금액
    tax_free = int(sum(i.price * i.quantity for i in items if i.tax_type == '면세'))
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    
    content = f"""
    <div class="max-w-md mx-auto py-24 md:py-40 px-6 text-center font-black">
        <div class="w-24 h-24 bg-blue-50 rounded-full flex items-center justify-center text-5xl mx-auto mb-10 text-blue-600 shadow-inner animate-pulse">
            <i class="fas fa-shield-alt"></i>
        </div>
        
        <h2 class="text-2xl md:text-3xl font-black mb-4 text-gray-800 tracking-tighter">
            안전 결제 시스템 연결
        </h2>
        <p class="text-gray-400 font-bold text-sm md:text-base mb-12 leading-relaxed">
            바구니삼촌은 토스페이먼츠의 보안망을 통해<br>고객님의 결제 정보를 안전하게 보호합니다.
        </p>

        <div class="bg-white p-8 rounded-3xl border border-gray-100 shadow-xl mb-12 text-left space-y-4">
            <div class="flex justify-between text-xs font-bold text-gray-400 uppercase tracking-widest">
                <span>주문 상품</span>
                <span class="text-gray-800">{ order_name }</span>
            </div>
            {f'<div class="flex justify-between items-center text-sm text-amber-700 font-bold">포인트 사용 <span>- { "{:,}".format(points_used) }원</span></div>' if points_used else ''}
            <div class="flex justify-between items-center border-t border-gray-50 pt-4 font-black">
                <span class="text-sm text-gray-600">총 결제 금액</span>
                <span class="text-2xl text-teal-600 italic underline underline-offset-4">{ "{:,}".format(total) }원</span>
            </div>
        </div>

        <button id="payment-button" class="w-full bg-blue-600 text-white py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-xl shadow-xl shadow-blue-100 hover:bg-blue-700 transition active:scale-95 flex items-center justify-center gap-3">
            <i class="fas fa-credit-card"></i> 결제창 열기
        </button>
        
        <p class="mt-8 text-[10px] text-gray-300 font-medium">
            결제창이 열리지 않거나 오류가 발생할 경우<br>고객센터(1666-8320)로 문의해 주세요.
        </p>
    </div>

    <script>
    // 1. 토스페이먼츠 초기화
    var tossPayments = TossPayments("{TOSS_CLIENT_KEY}");
    var isProcessing = false; // 중복 결제 방지 상태 변수

    document.getElementById('payment-button').addEventListener('click', function() {{
        // 2. 중복 클릭 체크
        if (isProcessing) {{
            alert("현재 결제가 진행 중입니다. 잠시만 기다려 주세요.");
            return;
        }}

        try {{
            isProcessing = true; // 처리 시작
            this.innerHTML = '<i class="fas fa-spinner animate-spin"></i> 연결 중...';
            this.classList.add('opacity-50', 'cursor-not-allowed');

            tossPayments.requestPayment('카드', {{
                amount: { total },
                taxFreeAmount: { min(tax_free, total) },
                orderId: '{ order_id }',
                orderName: '{ order_name }',
                customerName: '{ current_user.name }',
                successUrl: window.location.origin + '/payment/success',
                failUrl: window.location.origin + '/payment/fail'
            }}).catch(function (error) {{
                // 결제창 호출 실패 시 상태 복구
                isProcessing = false;
                document.getElementById('payment-button').innerHTML = '<i class="fas fa-credit-card"></i> 결제창 열기';
                document.getElementById('payment-button').classList.remove('opacity-50', 'cursor-not-allowed');
                
                if (error.code === 'USER_CANCEL') {{
                    alert("결제가 취소되었습니다.");
                }} else {{
                    alert("결제 오류: " + error.message);
                }}
            }});
        }} catch (err) {{
            alert("시스템 오류가 발생했습니다: " + err.message);
            isProcessing = false;
        }}
    }});
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

# [수정] 결제 성공 화면 내 '바로가기 추가' 버튼 포함
@app.route('/payment/success')
@login_required
def payment_success():
    """결제 성공 및 주문 생성 (세련된 디자인 및 폰트 최적화 버전)"""
    pk, oid, amt = request.args.get('paymentKey'), request.args.get('orderId'), request.args.get('amount')
    url, auth_key = "https://api.tosspayments.com/v1/payments/confirm", base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    res = requests.post(url, json={"paymentKey": pk, "amount": amt, "orderId": oid}, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
    
    if res.status_code == 200:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        if not items: return redirect('/') # 중복 새로고침 방지

        cat_groups = {i.product_category: [] for i in items}
        for i in items: cat_groups[i.product_category].append(f"{i.product_name}({i.quantity})")
        details = " | ".join([f"[{cat}] {', '.join(prods)}" for cat, prods in cat_groups.items()])
        
        cat_price_sums = {}
        for i in items: cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
        delivery_fee = sum(1900 + (1900 if amt_ >= 50000 else 0) for amt_ in cat_price_sums.values())
        points_used = session.get('points_used', 0) or 0
        quick_extra = session.get('quick_extra_fee', 0) or 0
        original_total = int(amt) + points_used  # 결제창에 넘긴 금액(amt) + 사용 포인트 = 주문 원금액

        # 주문 시 변경한 배송지가 있으면 session 값 사용, 없으면 회원 기본 주소 사용
        delivery_addr = session.get('order_address') or current_user.address or ""
        delivery_addr_detail = session.get('order_address_detail') or current_user.address_detail or ""
        delivery_entrance_pw = session.get('order_entrance_pw') or current_user.entrance_pw or ""
        delivery_address_str = f"({delivery_addr}) {delivery_addr_detail} (현관:{delivery_entrance_pw})"

        # 주문 저장 후 품목별 OrderItem 생성 (부분 취소 가능하도록). 퀵 추가료는 주문에 기록.
        order = Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=original_total, delivery_fee=delivery_fee, tax_free_amount=sum(i.price * i.quantity for i in items if i.tax_type == '면세'), order_id=oid, payment_key=pk, delivery_address=delivery_address_str, request_memo=current_user.request_memo, status='결제완료', points_used=points_used, quick_extra_fee=quick_extra)
        db.session.add(order)
        db.session.flush()  # order.id 확보
        for i in items:
            db.session.add(OrderItem(order_id=order.id, product_id=i.product_id, product_name=i.product_name, product_category=i.product_category, price=i.price, quantity=i.quantity, tax_type=i.tax_type or '과세', item_status='결제완료'))
        db.session.flush()  # OrderItem.id 확보
        
        # 정산 전용 테이블: 품목별 고유 n넘버(settlement_no) 부여. 정산합계=판매금액-수수료5.5%-배송관리비990원(전체항목 VAT포함가격)
        order_items = OrderItem.query.filter_by(order_id=order.id).order_by(OrderItem.id.asc()).all()
        delivery_fee_per_settlement = 990  # 정산번호당 배송관리비 990원
        for oi in order_items:
            sales_amount = oi.price * oi.quantity
            fee = round(sales_amount * 0.055)
            total = sales_amount - fee - delivery_fee_per_settlement
            settlement_no = "N" + str(oi.id).zfill(10)  # 품목별 고유 중복 없는 n넘버
            # 면세여부: 판매자 관리(카테고리)의 과세/면세 설정 기준
            cat = Category.query.filter_by(name=oi.product_category).first()
            tax_exempt_val = (getattr(cat, 'tax_type', None) or '과세') == '면세'
            db.session.add(Settlement(
                settlement_no=settlement_no, order_id=order.id, order_item_id=oi.id,
                sale_dt=order.created_at, category=oi.product_category,
                tax_exempt=tax_exempt_val,
                product_name=oi.product_name, sales_amount=sales_amount, fee=fee,
                delivery_fee=delivery_fee_per_settlement, settlement_total=total,
                settlement_status='입금대기', settled_at=None
            ))
        
        # 재고 차감
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        
        apply_order_points(current_user, original_total, points_used, order.id)
        if session.get('save_address_to_profile') and delivery_addr:
            try:
                current_user.address = delivery_addr
                current_user.address_detail = delivery_addr_detail
                current_user.entrance_pw = delivery_entrance_pw
            except Exception:
                pass
        session.pop('points_used', None)
        session.pop('quick_extra_fee', None)
        session.pop('order_address', None)
        session.pop('order_address_detail', None)
        session.pop('order_entrance_pw', None)
        session.pop('save_address_to_profile', None)
        Cart.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        title, body = get_template_content('order_created', order_id=oid)
        send_message(current_user.id, title, body, 'order_created', order.id)
        db.session.commit()

        # ✅ 세련된 성공 화면 구성 (품목 수·합계 금액 안내 + 앱/알림 안내)
        item_count = sum(i.quantity for i in items)
        total_amount = int(amt)
        success_content = f"""
        <div class="max-w-md mx-auto py-20 md:py-32 px-6 text-center font-black">
            <div class="w-24 h-24 bg-teal-500 rounded-full flex items-center justify-center text-white text-4xl mx-auto mb-10 shadow-2xl animate-bounce">
                <i class="fas fa-check"></i>
            </div>
            
            <h2 class="text-3xl md:text-4xl font-black mb-4 text-gray-800 tracking-tighter italic uppercase">
                주문 성공!
            </h2>
            <p class="text-gray-700 font-bold text-sm md:text-base mb-4 leading-relaxed">
                품목 {item_count}개, 합계 {total_amount:,}원이 주문되었습니다.
            </p>
            <p class="text-gray-400 font-bold text-xs md:text-sm mb-12 leading-relaxed">
                앱 설치 후 알림 설정 시 배송 진행 과정을 안내받으실 수 있습니다.
            </p>

            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-xl mb-12 text-left space-y-5">
                <div class="pb-4 border-b border-gray-50">
                    <p class="text-[10px] text-gray-400 uppercase tracking-widest mb-1 font-black">Order ID</p>
                    <p class="text-sm font-black text-gray-700">{ oid }</p>
                </div>
                <div>
                    <p class="text-[10px] text-gray-400 uppercase tracking-widest mb-1 font-black">결제 금액</p>
                    <p class="text-2xl font-black text-teal-600 italic">{ "{:,}".format(total_amount) }원</p>
                </div>
            </div>

            <div class="flex flex-col gap-4">
                <a href="/mypage" class="bg-gray-800 text-white py-6 rounded-3xl font-black text-lg shadow-xl hover:bg-black transition active:scale-95">
                    주문 내역 확인하기
                </a>
                <a href="/" class="bg-white text-gray-400 py-4 rounded-3xl font-black text-sm hover:text-teal-600 transition">
                    메인으로 돌아가기
                </a>
            </div>
            
            <p class="mt-12 text-[10px] text-gray-300 font-medium">
                문의 사항이 있으시면 1666-8320으로 연락주세요.
            </p>
        </div>
        """
        return render_template_string(HEADER_HTML + success_content + FOOTER_HTML)

    return redirect('/')

# --------------------------------------------------------------------------------
# 6. 관리자 전용 기능 (Dashboard / Bulk Upload / Excel)
# --------------------------------------------------------------------------------
# --- [신규 추가] 카테고리 관리자의 배송 요청 기능 ---
# ✅ 개별 정산 승인을 위한 라우트 신설
@app.route('/admin/settle_order/<int:order_id>', methods=['POST'])
@login_required
def admin_settle_order(order_id):
    """주문별 정산 확정 처리 및 DB 저장"""
    if not current_user.is_admin:
        flash("관리자 권한이 필요합니다.")
        return redirect('/')
    
    order = Order.query.get_or_404(order_id)
    
    if not order.is_settled:
        order.is_settled = True
        order.settled_at = datetime.now() # 정산 시점 기록
        
        try:
            db.session.commit() # ✅ 실제 DB에 강제 기록
            flash(f"주문 {order.order_id[-8:]} 입금 승인 완료!")
        except Exception as e:
            db.session.rollback()
            flash(f"저장 오류: {str(e)}")
    else:
        flash("이미 처리된 주문입니다.")
        
    # ✅ 사용자가 보던 날짜 필터가 유지되도록 이전 페이지(referrer)로 리다이렉트
    return redirect(request.referrer or url_for('admin_dashboard', tab='orders'))

# admin() 함수 내 주문 조회 부분은 기존과 동일하게 유지하되 UI에서 필드를 사용함
@app.route('/admin/order/bulk_request_delivery', methods=['POST'])
@login_required
def admin_bulk_request_delivery():
    """여러 주문을 한꺼번에 배송 요청 상태로 변경 (새로고침 없음)"""
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    
    data = request.get_json()
    order_ids = data.get('order_ids', [])
    
    if not order_ids:
        return jsonify({"success": False, "message": "선택된 주문이 없습니다."})

    # '결제완료' 상태인 주문들만 찾아서 '배송요청'으로 일괄 변경 + 품목별 상태 반영
    orders = Order.query.filter(Order.order_id.in_(order_ids), Order.status == '결제완료').all()
    
    count = 0
    for o in orders:
        o.status = '배송요청'
        # 해당 주문의 모든 품목에도 배송요청 상태 적용
        for oi in OrderItem.query.filter_by(order_id=o.id, cancelled=False).all():
            oi.item_status = '배송요청'
        title, body = get_template_content('delivery_requested', order_id=o.order_id)
        send_message(o.user_id, title, body, 'delivery_requested', o.id)
        count += 1

    db.session.commit()
    return jsonify({"success": True, "message": f"{count}건의 배송 요청이 완료되었습니다."})


@app.route('/admin/order/item_status', methods=['POST'])
@login_required
def admin_order_item_status():
    """관리자: 품목별 상태 적용 (품절취소·배송지연·배송중·배송완료 등)"""
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    data = request.get_json()
    order_id = data.get('order_id')  # Order.id
    item_id = data.get('item_id')    # OrderItem.id
    item_status = (data.get('item_status') or '').strip()
    status_message = (data.get('status_message') or '').strip() or None
    if not order_id or not item_id or not item_status:
        return jsonify({"success": False, "message": "order_id, item_id, item_status가 필요합니다."})
    order = Order.query.get(order_id)
    oi = OrderItem.query.filter_by(id=item_id, order_id=order_id).first()
    if not order or not oi:
        return jsonify({"success": False, "message": "주문 또는 품목을 찾을 수 없습니다."})
    # 카테고리 매니저는 자기 카테고리 품목만
    if not current_user.is_admin and oi.product_category not in [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]:
        return jsonify({"success": False, "message": "해당 카테고리 관리 권한이 없습니다."}), 403
    allowed = ('결제완료', '배송요청', '배송중', '배송완료', '품절취소', '배송지연', '부분취소')
    if item_status not in allowed:
        return jsonify({"success": False, "message": f"item_status는 {allowed} 중 하나여야 합니다."})

    old_item_status = getattr(oi, 'item_status', None) or '결제완료'
    if item_status == '품절취소':
        if oi.cancelled:
            return jsonify({"success": False, "message": "이미 취소된 품목입니다."})
        cancel_amount = oi.price * oi.quantity
        tax_free_cancel = (oi.price * oi.quantity) if (oi.tax_type == '면세') else 0
        if order.payment_key and cancel_amount > 0:
            url = f"https://api.tosspayments.com/v1/payments/{order.payment_key}/cancel"
            auth_key = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
            body = {"cancelAmount": cancel_amount, "cancelReason": "품절로 인한 부분 취소"}
            if tax_free_cancel:
                body["taxFreeAmount"] = tax_free_cancel
            res = requests.post(url, json=body, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
            if res.status_code not in (200, 201):
                try:
                    err = res.json()
                    return jsonify({"success": False, "message": err.get("message", "환불 요청 실패")})
                except Exception:
                    return jsonify({"success": False, "message": "환불 요청 실패"})
        oi.cancelled = True
        oi.item_status = '품절취소'
        oi.status_message = status_message or "품절로 인한 부분 취소"
        p = Product.query.get(oi.product_id)
        if p:
            p.stock += oi.quantity
        _recalc_order_from_items(order)
        title, body = get_template_content('out_of_stock', order_id=order.order_id)
        send_message(order.user_id, title, body, 'out_of_stock', order.id)
    else:
        oi.item_status = item_status
        oi.status_message = status_message
        if not oi.cancelled and item_status == '배송완료':
            apply_points_on_delivery_complete(oi)  # 정산번호(sales_amount) 기준 포인트 적립 (1회만)

    db.session.add(OrderItemLog(order_id=order_id, order_item_id=item_id, log_type='item_status', old_value=old_item_status, new_value=item_status, created_at=datetime.now()))
    db.session.commit()
    # 배송 상태 변경 시 회원에게 자동 메시지
    if item_status in ('배송요청', '배송중', '배송완료', '배송지연'):
        if item_status == '배송요청':
            title, body = get_template_content('delivery_requested', order_id=order.order_id)
            send_message(order.user_id, title, body, 'delivery_requested', order.id)
        elif item_status == '배송중':
            title, body = get_template_content('delivery_in_progress', order_id=order.order_id)
            send_message(order.user_id, title, body, 'delivery_in_progress', order.id)
        elif item_status == '배송완료':
            title, body = get_template_content('delivery_complete', order_id=order.order_id)
            send_message(order.user_id, title, body, 'delivery_complete', order.id)
        elif item_status == '배송지연':
            title, body = get_template_content('delivery_delayed', order_id=order.order_id)
            send_message(order.user_id, title, body, 'delivery_delayed', order.id)
        db.session.commit()
    return jsonify({"success": True, "message": f"품목 상태가 '{item_status}'(으)로 적용되었습니다."})


@app.route('/admin/order/<int:order_id>/items')
@login_required
def admin_order_items(order_id):
    """관리자: 주문별 품목 목록 및 품목별 상태/메시지 적용 화면"""
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        flash("권한이 없습니다.")
        return redirect('/admin')
    order = Order.query.get_or_404(order_id)
    my_categories = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
    if not current_user.is_admin and order.id:  # 주문에 내 카테고리 품목이 있는지 확인
        items = OrderItem.query.filter_by(order_id=order_id).all()
        if not any(oi.product_category in my_categories for oi in items):
            flash("해당 주문에 대한 권한이 없습니다.")
            return redirect('/admin?tab=orders')
    order_items = OrderItem.query.filter_by(order_id=order_id).order_by(OrderItem.id.asc()).all()
    _order_item_status_tpl = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 p-6 font-sans text-sm">
        <div class="max-w-4xl mx-auto">
            <div class="flex items-center justify-between mb-6">
                <h1 class="text-xl font-black text-gray-800">품목별 상태 관리 · 주문 {{ order.order_id[-12:] if order.order_id else order_id }}</h1>
                <a href="/admin?tab=orders" class="bg-gray-200 text-gray-700 px-4 py-2 rounded-xl font-bold hover:bg-gray-300">목록으로</a>
            </div>
            <p class="text-gray-500 mb-4">각 품목에 상태(품절취소·배송지연·배송중·배송완료 등)와 사유 메시지를 적용할 수 있습니다.</p>
            <div class="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-gray-100 border-b border-gray-200">
                        <tr>
                            <th class="p-4 font-black">품목</th>
                            <th class="p-4 font-black">수량/금액</th>
                            <th class="p-4 font-black">현재 상태</th>
                            <th class="p-4 font-black">상태 변경</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for oi in order_items %}
                        <tr class="border-b border-gray-50 hover:bg-gray-50/50" data-item-id="{{ oi.id }}">
                            <td class="p-4">
                                <span class="font-bold text-gray-800">{{ oi.product_name }}</span>
                                {% if oi.cancelled %}<span class="ml-2 text-red-500 text-xs font-black">취소됨</span>{% endif %}
                            </td>
                            <td class="p-4 text-gray-600">{{ oi.quantity }}개 · {{ "{:,}".format(oi.price * oi.quantity) }}원</td>
                            <td class="p-4">
                                <span class="font-bold {% if oi.item_status in ['품절취소','부분취소'] %}text-red-600{% elif oi.item_status == '배송지연' %}text-amber-600{% else %}text-teal-600{% endif %}">{{ oi.item_status or '결제완료' }}</span>
                                {% if oi.status_message %}<p class="text-xs text-gray-500 mt-1">{{ oi.status_message }}</p>{% endif %}
                            </td>
                            <td class="p-4">
                                {% if not oi.cancelled %}
                                <div class="flex flex-wrap gap-2 items-end">
                                    <select class="item-status-select border border-gray-200 rounded-lg px-3 py-2 font-bold text-xs" data-order-id="{{ order.id }}" data-item-id="{{ oi.id }}">
                                        {% set current = oi.item_status or '결제완료' %}
                                        <option value="결제완료" {% if current == '결제완료' %}selected{% endif %}>결제완료</option>
                                        <option value="배송요청" {% if current == '배송요청' %}selected{% endif %}>배송요청</option>
                                        <option value="배송지연" {% if current == '배송지연' %}selected{% endif %}>배송지연</option>
                                        <option value="배송중" {% if current == '배송중' %}selected{% endif %}>배송중</option>
                                        <option value="배송완료" {% if current == '배송완료' %}selected{% endif %}>배송완료</option>
                                        <option value="품절취소" {% if current == '품절취소' %}selected{% endif %}>품절취소</option>
                                    </select>
                                    <input type="text" class="item-message border border-gray-200 rounded-lg px-3 py-2 w-40 text-xs" placeholder="사유 메시지" value="{{ oi.status_message or '' }}">
                                    <button type="button" class="apply-item-status bg-teal-600 text-white px-4 py-2 rounded-lg font-bold text-xs hover:bg-teal-700" data-order-id="{{ order.id }}" data-item-id="{{ oi.id }}">적용</button>
                                </div>
                                {% else %}
                                <span class="text-gray-400 text-xs">취소된 품목</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <p id="api-message" class="mt-4 text-sm font-bold hidden"></p>
        </div>
        <script>
        document.querySelectorAll('.apply-item-status').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var orderId = this.dataset.orderId;
                var itemId = this.dataset.itemId;
                var row = this.closest('tr');
                var select = row.querySelector('.item-status-select');
                var message = row.querySelector('.item-message');
                var status = select ? select.value : '';
                var msg = message ? message.value.trim() : '';
                fetch('/admin/order/item_status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ order_id: parseInt(orderId), item_id: parseInt(itemId), item_status: status, status_message: msg || null })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    var el = document.getElementById('api-message');
                    el.textContent = data.message || (data.success ? '적용되었습니다.' : '오류');
                    el.classList.remove('hidden');
                    el.className = 'mt-4 text-sm font-bold ' + (data.success ? 'text-teal-600' : 'text-red-600');
                    if (data.success) setTimeout(function() { location.reload(); }, 800);
                }).catch(function() {
                    document.getElementById('api-message').textContent = '통신 오류';
                    document.getElementById('api-message').classList.remove('hidden', 'text-teal-600').classList.add('text-red-600');
                });
            });
        });
        </script>
    </body>
    </html>
    """
    return render_template_string(_order_item_status_tpl, order=order, order_items=order_items)


def _ensure_delivery_zone_columns():
    """delivery_zone 테이블에 퀵지역·그 외 배송불가용 컬럼이 없으면 추가 (기존 DB 호환)."""
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('delivery_zone')]
        if 'quick_region_names' not in cols:
            db.session.execute(text("ALTER TABLE delivery_zone ADD COLUMN quick_region_names TEXT"))
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('delivery_zone')]
        if 'use_quick_region_only' not in cols:
            db.session.execute(text("ALTER TABLE delivery_zone ADD COLUMN use_quick_region_only BOOLEAN DEFAULT 0"))
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('delivery_zone')]
        if 'quick_region_polygon_json' not in cols:
            db.session.execute(text("ALTER TABLE delivery_zone ADD COLUMN quick_region_polygon_json TEXT"))
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    for col, sql in [
        ('quick_extra_fee', 'ALTER TABLE delivery_zone ADD COLUMN quick_extra_fee INTEGER DEFAULT 10000'),
        ('quick_extra_message', 'ALTER TABLE delivery_zone ADD COLUMN quick_extra_message TEXT'),
    ]:
        try:
            insp = inspect(db.engine)
            cols = [c['name'] for c in insp.get_columns('delivery_zone')]
            if col not in cols:
                db.session.execute(text(sql))
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('order')]
        if 'quick_extra_fee' not in cols:
            db.session.execute(text("ALTER TABLE \"order\" ADD COLUMN quick_extra_fee INTEGER DEFAULT 0"))
            db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


@app.route('/admin/delivery_zone/api', methods=['GET', 'POST'])
@login_required
def admin_delivery_zone_api():
    """배송구역: GET=폴리곤·퀵지역 반환, POST=폴리곤 또는 퀵지역 저장 (마스터 관리자 전용). 퀵지역만 사용 시 그 외 지역 배송불가."""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    _ensure_delivery_zone_columns()
    if request.method == 'GET':
        z = DeliveryZone.query.order_by(DeliveryZone.updated_at.desc()).first()
        polygon = []
        quick_region_polygon = []
        quick_region_names = []
        use_quick_region_only = False
        quick_extra_fee = 10000
        quick_extra_message = ''
        if z:
            if z.polygon_json:
                try:
                    polygon = json.loads(z.polygon_json)
                except Exception:
                    pass
            if getattr(z, 'quick_region_polygon_json', None):
                try:
                    quick_region_polygon = json.loads(z.quick_region_polygon_json) or []
                except Exception:
                    pass
            if getattr(z, 'quick_region_names', None):
                try:
                    quick_region_names = json.loads(z.quick_region_names) or []
                except Exception:
                    pass
            use_quick_region_only = bool(getattr(z, 'use_quick_region_only', False))
            quick_extra_fee = int(getattr(z, 'quick_extra_fee', None) or 10000)
            quick_extra_message = (getattr(z, 'quick_extra_message', None) or '') or ''
        return jsonify({'polygon': polygon, 'quick_region_polygon': quick_region_polygon, 'quick_region_names': quick_region_names, 'use_quick_region_only': use_quick_region_only, 'quick_extra_fee': quick_extra_fee, 'quick_extra_message': quick_extra_message})
    # POST
    data = request.get_json() or {}
    z = DeliveryZone.query.order_by(DeliveryZone.updated_at.desc()).first()
    if not z:
        z = DeliveryZone(name='연수구')
        db.session.add(z)
        db.session.flush()
    updated = False
    if 'polygon' in data:
        polygon = data['polygon']
        if polygon is not None:
            if not isinstance(polygon, list) or len(polygon) < 3:
                return jsonify({'error': '꼭짓점 3개 이상 필요'}), 400
            try:
                json.dumps(polygon)
            except (TypeError, ValueError):
                return jsonify({'error': '유효한 좌표 배열이 아님'}), 400
            z.polygon_json = json.dumps(polygon)
            updated = True
    if 'quick_region_names' in data:
        val = data['quick_region_names']
        if isinstance(val, str):
            val = [n.strip() for n in val.replace('，', ',').split(',') if n.strip()]
        if isinstance(val, list):
            z.quick_region_names = json.dumps([str(n).strip() for n in val if str(n).strip()])
            updated = True
    if 'use_quick_region_only' in data:
        z.use_quick_region_only = data['use_quick_region_only'] in (True, 'true', '1', 1)
        updated = True
    if 'quick_region_polygon' in data:
        qrp = data['quick_region_polygon']
        if qrp is None or (isinstance(qrp, list) and len(qrp) == 0):
            z.quick_region_polygon_json = None
            updated = True
        elif isinstance(qrp, list) and len(qrp) >= 3:
            try:
                json.dumps(qrp)
                z.quick_region_polygon_json = json.dumps(qrp)
                updated = True
            except (TypeError, ValueError):
                return jsonify({'error': '퀵지역 폴리곤 좌표가 유효하지 않습니다.'}), 400
        else:
            return jsonify({'error': '퀵지역 폴리곤은 꼭짓점 3개 이상 필요합니다.'}), 400
    if 'quick_extra_fee' in data:
        try:
            v = data['quick_extra_fee']
            z.quick_extra_fee = int(v) if v not in (None, '') else 10000
            updated = True
        except (TypeError, ValueError):
            z.quick_extra_fee = 10000
            updated = True
    if 'quick_extra_message' in data:
        z.quick_extra_message = (data['quick_extra_message'] or '').strip() or None
        updated = True
    if updated:
        z.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/admin/member_grade/set', methods=['POST'])
@login_required
def admin_member_grade_set():
    """회원 등급 직접 설정 (마스터 전용). user_id, grade(1~5), overridden(true|false)"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    data = request.get_json() or request.form
    try:
        uid = int(data.get('user_id', 0))
        grade = int(data.get('grade', 1))
        overridden = data.get('overridden', 'true').lower() in ('1', 'true', 'yes')
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id, grade 필요'}), 400
    if grade not in (1, 2, 3, 4, 5):
        return jsonify({'error': 'grade는 1~5만 가능'}), 400
    u = User.query.get(uid)
    if not u:
        return jsonify({'error': '회원 없음'}), 404
    u.member_grade = grade
    u.member_grade_overridden = overridden
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/admin/member_grade/config', methods=['POST'])
@login_required
def admin_member_grade_config():
    """자동 등급 기준 저장 (마스터 전용). min_amount_grade2~5 (원)"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    data = request.get_json() or request.form
    def set_val(k, v):
        try:
            val = str(int(v)) if v not in (None, '') else '0'
        except (TypeError, ValueError):
            val = '0'
        row = MemberGradeConfig.query.filter_by(key=k).first()
        if not row:
            row = MemberGradeConfig(key=k, value=val)
            db.session.add(row)
        else:
            row.value = val
    set_val('min_amount_grade2', data.get('min_amount_grade2'))
    set_val('min_amount_grade3', data.get('min_amount_grade3'))
    set_val('min_amount_grade4', data.get('min_amount_grade4'))
    set_val('min_amount_grade5', data.get('min_amount_grade5'))
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/admin/member_grade/auto_apply', methods=['POST'])
@login_required
def admin_member_grade_auto_apply():
    """구매이력으로 등급 자동 반영 (직접설정 아닌 회원만, 마스터 전용)"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    count = 0
    for u in User.query.filter_by(member_grade_overridden=False).all():
        if recompute_member_grade_for_user(u):
            count += 1
    db.session.commit()
    return jsonify({'ok': True, 'updated': count})


@app.route('/admin/point/config', methods=['POST'])
@login_required
def admin_point_config():
    """포인트 정책 저장 (마스터 전용). accumulation_rate(1=0.1%), min_order_to_use, max_points_per_order"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    data = request.get_json() or request.form
    def set_val(k, v):
        try:
            val = str(int(v)) if v not in (None, '') else '0'
        except (TypeError, ValueError):
            val = '0'
        row = PointConfig.query.filter_by(key=k).first()
        if not row:
            row = PointConfig(key=k, value=val)
            db.session.add(row)
        else:
            row.value = val
    set_val('accumulation_rate', data.get('accumulation_rate'))
    set_val('min_order_to_use', data.get('min_order_to_use'))
    set_val('max_points_per_order', data.get('max_points_per_order'))
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/admin/point/adjust', methods=['POST'])
@login_required
def admin_point_adjust():
    """회원 포인트 지급/차감 (마스터 전용). user_id, amount(양수=지급/음수=차감), memo"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    data = request.get_json() or request.form
    try:
        uid = int(data.get('user_id', 0))
        amount = int(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id, amount 필요'}), 400
    u = User.query.get(uid)
    if not u:
        return jsonify({'error': '회원 없음'}), 404
    memo = (data.get('memo') or '')[:200]
    current_pts = getattr(u, 'points', 0) or 0
    after = current_pts + amount
    if after < 0:
        return jsonify({'error': '포인트가 음수가 될 수 없습니다.'}), 400
    u.points = after
    db.session.add(PointLog(user_id=u.id, amount=amount, memo=memo or ('관리자 조정' if amount >= 0 else '관리자 차감'), adjusted_by=current_user.id))
    db.session.commit()
    return jsonify({'ok': True, 'after': after})


@app.route('/admin/point/log')
@login_required
def admin_point_log():
    """회원별 포인트 내역 (마스터 전용). user_id, limit 기본 30"""
    if not current_user.is_admin:
        return jsonify({'error': '권한 없음'}), 403
    uid = request.args.get('user_id', type=int)
    limit = min(100, max(1, request.args.get('limit', type=int) or 30))
    if not uid:
        return jsonify({'error': 'user_id 필요'}), 400
    logs = PointLog.query.filter_by(user_id=uid).order_by(PointLog.created_at.desc()).limit(limit).all()
    out = []
    for l in logs:
        modifier = None
        if getattr(l, 'adjusted_by', None):
            mod_user = User.query.get(l.adjusted_by)
            modifier = mod_user.email if mod_user else str(l.adjusted_by)
        out.append({
            'id': l.id, 'amount': l.amount, 'order_id': l.order_id, 'memo': l.memo or '',
            'created_at': l.created_at.strftime('%Y-%m-%d %H:%M') if l.created_at else '',
            'date': l.created_at.strftime('%Y-%m-%d') if l.created_at else '',
            'modifier': modifier  # 수정자 이메일(관리자), 없으면 시스템
        })
    return jsonify({'logs': out})


@app.route('/admin/api/member/<int:uid>/message', methods=['POST'])
@login_required
def admin_member_send_message(uid):
    """관리자: 특정 회원에게 메시지 발송 (제목·내용). 푸시 알림 포함."""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    u = User.query.get(uid)
    if not u:
        return jsonify({"success": False, "message": "회원을 찾을 수 없습니다."}), 404
    data = request.get_json() or request.form
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    if not title:
        return jsonify({"success": False, "message": "제목을 입력해 주세요."})
    mid = send_message(uid, title, body, 'custom', None)
    if mid:
        db.session.commit()
        return jsonify({"success": True, "message": "메시지를 발송했습니다."})
    return jsonify({"success": False, "message": "발송에 실패했습니다."}), 500


@app.route('/admin/api/member/<int:uid>/delete', methods=['POST'])
@login_required
def admin_member_delete(uid):
    """관리자: 회원 삭제. 주문 이력이 있으면 삭제 불가. 관리자 계정은 삭제 불가."""
    if not current_user.is_admin:
        return jsonify({"success": False, "message": "권한이 없습니다."}), 403
    u = User.query.get(uid)
    if not u:
        return jsonify({"success": False, "message": "회원을 찾을 수 없습니다."}), 404
    if u.is_admin:
        return jsonify({"success": False, "message": "관리자 계정은 삭제할 수 없습니다."}), 400
    if uid == current_user.id:
        return jsonify({"success": False, "message": "본인 계정은 삭제할 수 없습니다."}), 400
    order_count = Order.query.filter_by(user_id=uid).count()
    if order_count > 0:
        return jsonify({"success": False, "message": f"주문 이력이 있는 회원({order_count}건)은 삭제할 수 없습니다."}), 400
    try:
        PointLog.query.filter_by(user_id=uid).delete()
        PushSubscription.query.filter_by(user_id=uid).delete()
        UserMessage.query.filter_by(user_id=uid).delete()
        Cart.query.filter_by(user_id=uid).delete()
        db.session.delete(u)
        db.session.commit()
        return jsonify({"success": True, "message": "회원이 삭제되었습니다."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e) or "삭제 중 오류가 발생했습니다."}), 500


@app.route('/admin')
@login_required
def admin_dashboard():
    """관리자 대시보드 - [매출+물류+카테고리+리뷰] 전체 기능 통합 복구본"""
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    managers = [c.manager_email for c in categories if c.manager_email]
    
    if not (current_user.is_admin or current_user.email in managers):
        flash("관리자 권한이 없습니다.")
        return redirect('/')
    
    is_master = current_user.is_admin
    tab = request.args.get('tab', 'products')
    seller_tax = request.args.get('seller_tax', '전체')  # 판매자 관리 서브탭: 전체 / 과세 / 면세
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    # 카테고리 선택: 권한 있는 카테고리만 (마스터=전체, 매니저=자기 카테고리만)
    selectable_categories = [c for c in categories if is_master or c.name in my_categories]
    sellers_categories = categories
    if tab == 'sellers' and seller_tax in ('과세', '면세'):
        sellers_categories = [c for c in categories if (getattr(c, 'tax_type', None) or '과세') == seller_tax]
    
    # 1. 날짜 변수 정의
    now = datetime.now()
    start_date_str = request.args.get('start_date', now.strftime('%Y-%m-%d 00:00')).replace('T', ' ')
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d 23:59')).replace('T', ' ')
    
    # 2. 공통 변수 초기화
    sel_cat = request.args.get('category', '전체')
    sel_order_cat = request.args.get('order_cat', '전체')
    products, filtered_orders, summary, daily_stats, reviews = [], [], {}, {}, []
    product_q, product_page, products_total, product_total_pages, per_page = '', 1, 0, 1, 30
    stats = {"sales": 0, "delivery": 0, "count": 0, "grand_total": 0}
    category_names = {}
    order_total_qty, order_total_subtotal = 0, 0
    sales_table_rows = []
    sales_total_quantity = 0
    product_summary_rows = []
    settlement_detail_rows = []
    settlement_detail_orders = []
    settlement_category_totals = {}

    if tab == 'products':
        product_q = (request.args.get('q') or request.args.get('product_q') or '').strip()
        product_page = max(1, int(request.args.get('page', 1)))
        per_page = 30
        q = Product.query
        if not is_master:
            q = q.filter(Product.category.in_(my_categories))
        if product_q:
            q = q.filter(or_(
                Product.name.contains(product_q),
                Product.description.contains(product_q),
                Product.category.contains(product_q)
            ))
        else:
            if sel_cat != '전체':
                q = q.filter_by(category=sel_cat)
        q = q.order_by(Product.id.desc())
        products_total = q.count()
        products = q.offset((product_page - 1) * per_page).limit(per_page).all()
        product_total_pages = max(1, (products_total + per_page - 1) // per_page)
     
    elif tab in ('orders', 'settlement'):
        try:
            # 날짜 파싱 시도
            start_dt = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M')
            end_dt = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M')
        except Exception as e:
            # 파싱 실패 시 기본값 (오늘 00:00 ~ 23:59)
            print(f"Date parsing error: {e}")
            start_dt = now.replace(hour=0, minute=0, second=0)
            end_dt = now.replace(hour=23, minute=59, second=59)

        # 결제취소 제외 주문 필터링
        all_orders = Order.query.filter(
            Order.created_at >= start_dt, 
            Order.created_at <= end_dt,
            Order.status != '결제취소'
        ).order_by(Order.created_at.desc()).all()
        
        for o in all_orders:
            order_date = o.created_at.strftime('%Y-%m-%d')
            if order_date not in daily_stats:
                daily_stats[order_date] = {"sales": 0, "count": 0}

            order_show_flag = False
            current_order_sales = 0  # 매니저별 정산 대상 금액 변수
            manager_items_list = []  # 오더별 정산: 내 카테고리 품목 목록
            manager_qty_total = 0    # 오더별 정산: 내 카테고리 수량 합계

            # OrderItem이 있으면 DB 기준으로 금액·수량 집계 (취소 품목 제외)
            items = OrderItem.query.filter_by(order_id=o.id, cancelled=False).order_by(OrderItem.id.asc()).all()
            if items:
                for oi in items:
                    if is_master or oi.product_category in my_categories:
                        order_show_flag = True
                        if oi.product_category not in summary:
                            summary[oi.product_category] = {"product_list": {}, "subtotal": 0}
                        item_price = oi.price * oi.quantity
                        manager_qty_total += oi.quantity
                        current_order_sales += item_price
                        summary[oi.product_category]["subtotal"] += item_price
                        summary[oi.product_category]["product_list"][oi.product_name] = summary[oi.product_category]["product_list"].get(oi.product_name, 0) + oi.quantity
                        manager_items_list.append(f"{oi.product_name}({oi.quantity})")
            else:
                # OrderItem 없을 때만 product_details 텍스트 파싱
                parts = (o.product_details or '').split(' | ')
                for part in parts:
                    match = re.search(r'\[(.*?)\] (.*)', part)
                    if match:
                        cat_n = match.group(1).strip()
                        items_str = match.group(2).strip()
                        if is_master or cat_n in my_categories:
                            order_show_flag = True
                            if cat_n not in summary:
                                summary[cat_n] = {"product_list": {}, "subtotal": 0}
                            for item in items_str.split(', '):
                                it_match = re.search(r'(.*?)\((\d+)\)', item)
                                if it_match:
                                    pn = it_match.group(1).strip()
                                    qt = int(it_match.group(2))
                                    manager_items_list.append(f"{pn}({qt})")
                                    manager_qty_total += qt
                                    p_obj = Product.query.filter_by(name=pn).first()
                                    if p_obj:
                                        item_price = p_obj.price * qt
                                        summary[cat_n]["subtotal"] += item_price
                                        summary[cat_n]["product_list"][pn] = summary[cat_n]["product_list"].get(pn, 0) + qt
                                        current_order_sales += item_price

            # 권한이 있는 주문 데이터만 통계에 반영 + 오더별 정산용 속성
            if order_show_flag:
                o._manager_items = manager_items_list
                o._manager_qty = manager_qty_total
                o._manager_subtotal = current_order_sales
                filtered_orders.append(o)
                stats["sales"] += current_order_sales
                stats["count"] += 1
                daily_stats[order_date]["sales"] += current_order_sales
                daily_stats[order_date]["count"] += 1
                if is_master: stats["delivery"] += (o.delivery_fee or 0)

        daily_stats = dict(sorted(daily_stats.items(), reverse=True))
        stats["grand_total"] = stats["sales"] + stats["delivery"]
        # 오더별 정산 현황 하단 총합계용
        order_total_qty = sum(getattr(o, '_manager_qty', 0) for o in filtered_orders)
        order_total_subtotal = sum(getattr(o, '_manager_subtotal', 0) for o in filtered_orders)
        # 매출 상세 테이블용: 상단 카테고리 선택 시 선택된 카테고리만 표시
        sales_table_rows = []
        for o in filtered_orders:
            order_date_str = o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else ''
            status_str = o.status or '결제완료'
            items = OrderItem.query.filter_by(order_id=o.id).order_by(OrderItem.id.asc()).all()
            if items:
                for oi in items:
                    if (is_master or oi.product_category in my_categories) and (sel_order_cat == '전체' or oi.product_category == sel_order_cat):
                        is_cancelled = getattr(oi, 'cancelled', False) or (getattr(oi, 'item_status', None) in ('부분취소', '품절취소'))
                        sales_table_rows.append({
                            'order_date': order_date_str,
                            'product_name': oi.product_name,
                            'category': oi.product_category,
                            'quantity': 0 if is_cancelled else oi.quantity,
                            'status': '취소' if is_cancelled else (getattr(oi, 'item_status', None) or status_str)
                        })
            else:
                parts = (o.product_details or '').split(' | ')
                for part in parts:
                    match = re.search(r'\[(.*?)\] (.*)', part)
                    if match:
                        cat_n, items_str = match.groups()
                        if (is_master or cat_n in my_categories) and (sel_order_cat == '전체' or cat_n == sel_order_cat):
                            for item in items_str.split(', '):
                                it_match = re.search(r'(.*?)\((\d+)\)', item)
                                if it_match:
                                    pn, qt = it_match.groups()
                                    sales_table_rows.append({'order_date': order_date_str, 'product_name': pn.strip(), 'category': cat_n, 'quantity': int(qt), 'status': status_str})
        # 조회 결과 총합계 수량 + 품목·판매상품명별 판매수량 총합계 (집계 테이블용)
        sales_total_quantity = sum(r.get('quantity', 0) for r in sales_table_rows)
        product_summary_rows = []
        from collections import defaultdict
        agg = defaultdict(int)
        for r in sales_table_rows:
            key = (r.get('category') or '', r.get('product_name') or '')
            agg[key] += r.get('quantity', 0)
        for (cat, pname), total_qty in sorted(agg.items(), key=lambda x: (x[0][0], x[0][1])):
            product_summary_rows.append({'category': cat, 'product_name': pname, 'total_quantity': total_qty})

        # 정산 전용 테이블(Settlement) 기준: n넘버(정산번호), 판매일시, 카테고리, 면세여부, 품목, 판매금액, 수수료, 배송관리비, 정산합계, 입금상태(입금일)
        sel_settlement_status = request.args.get('settlement_status', '전체')
        if sel_settlement_status == '정산대기': sel_settlement_status = '입금대기'
        if sel_settlement_status == '정산완료': sel_settlement_status = '입금완료'
        # 기존 OrderItem에 대한 Settlement 백필 (결제 시 생성 누락분 보충)
        for o in filtered_orders:
            items = OrderItem.query.filter_by(order_id=o.id, cancelled=False).order_by(OrderItem.id.asc()).all()
            if not items:
                continue
            for oi in items:
                if not (is_master or oi.product_category in my_categories):
                    continue
                if Settlement.query.filter_by(order_item_id=oi.id).first():
                    continue
                delivery_fee_per_settlement = 990  # 정산번호당 배송관리비 990원
                sales_amount = oi.price * oi.quantity
                fee = round(sales_amount * 0.055)
                total = sales_amount - fee - delivery_fee_per_settlement
                settlement_no = "N" + str(oi.id).zfill(10)
                st = getattr(oi, 'settlement_status', None) or getattr(o, 'settlement_status', None) or '입금대기'
                if st not in ('입금대기', '입금완료', '취소', '보류'):
                    st = '입금대기'
                # 면세여부: 판매자 관리(카테고리)의 과세/면세 설정 기준
                cat = Category.query.filter_by(name=oi.product_category).first()
                tax_exempt_val = (getattr(cat, 'tax_type', None) or '과세') == '면세'
                db.session.add(Settlement(
                    settlement_no=settlement_no, order_id=o.id, order_item_id=oi.id,
                    sale_dt=o.created_at, category=oi.product_category,
                    tax_exempt=tax_exempt_val,
                    product_name=oi.product_name, sales_amount=sales_amount, fee=fee,
                    delivery_fee=delivery_fee_per_settlement, settlement_total=total,
                    settlement_status=st, settled_at=getattr(oi, 'settled_at', None)
                ))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        # 정산 전용 테이블에서 조회 (판매일시, 카테고리, 면세여부, 품목, 판매금액, 수수료, 배송관리비, 정산합계, 입금상태(입금일))
        q = Settlement.query.filter(Settlement.sale_dt >= start_dt, Settlement.sale_dt <= end_dt)
        if not is_master:
            q = q.filter(Settlement.category.in_(my_categories))
        if sel_order_cat != '전체':
            q = q.filter(Settlement.category == sel_order_cat)
        if sel_settlement_status and sel_settlement_status != '전체':
            q = q.filter(Settlement.settlement_status == sel_settlement_status)
        for s in q.order_by(Settlement.sale_dt.desc()).all():
            settlement_detail_rows.append({
                'settlement_no': s.settlement_no,
                'order_item_id': s.order_item_id,
                'order_pk': s.order_id,
                'sale_dt': s.sale_dt.strftime('%Y-%m-%d %H:%M') if s.sale_dt else '-',
                'category': s.category,
                'tax_exempt': '면세' if s.tax_exempt else '과세',
                'product_name': s.product_name,
                'sales_amount': s.sales_amount,
                'fee': s.fee,
                'delivery_fee': s.delivery_fee,
                'settlement_total': s.settlement_total,
                'settlement_status': s.settlement_status,
                'settled_at': s.settled_at.strftime('%Y-%m-%d %H:%M') if s.settled_at else None,
            })
        # 정산 상세 카테고리별 총합계
        settlement_category_totals = {}
        for r in settlement_detail_rows:
            cat = r.get('category', '')
            row_total = r.get('settlement_total', 0)
            settlement_category_totals[cat] = settlement_category_totals.get(cat, 0) + row_total
        # 오더 목록 (정산 테이블은 n넘버 기준이므로 빈 목록 유지)
        settlement_detail_orders = []
            
    elif tab == 'reviews':
        reviews = Review.query.order_by(Review.created_at.desc()).all()
        category_names = {c.id: c.name for c in Category.query.all()}  # 리뷰 테이블에서 판매자명 표시용

    delivery_zone_polygon = []
    delivery_zone_quick_polygon = []
    delivery_zone_quick_regions = []
    delivery_zone_use_quick_only = False
    delivery_zone_quick_extra_fee = 10000
    delivery_zone_quick_extra_message = ''
    kakao_map_app_key = KAKAO_MAP_APP_KEY
    if tab == 'delivery_zone' and is_master:
        _ensure_delivery_zone_columns()
        z = DeliveryZone.query.order_by(DeliveryZone.updated_at.desc()).first()
        if z:
            if z.polygon_json:
                try:
                    delivery_zone_polygon = json.loads(z.polygon_json)
                except Exception:
                    pass
            if getattr(z, 'quick_region_polygon_json', None):
                try:
                    delivery_zone_quick_polygon = json.loads(z.quick_region_polygon_json) or []
                except Exception:
                    pass
            if getattr(z, 'quick_region_names', None):
                try:
                    delivery_zone_quick_regions = json.loads(z.quick_region_names) or []
                except Exception:
                    pass
            delivery_zone_use_quick_only = bool(getattr(z, 'use_quick_region_only', False))
            delivery_zone_quick_extra_fee = int(getattr(z, 'quick_extra_fee', None) or 10000)
            delivery_zone_quick_extra_message = (getattr(z, 'quick_extra_message', None) or '').strip() or '해당 주소는 배송지역이 아닙니다. 배송료 추가 시 퀵으로 배송됩니다. 추가하시고 주문하시겠습니까?'

    member_grade_users = []
    member_grade_min2 = member_grade_min3 = member_grade_min4 = member_grade_min5 = 0
    if tab == 'member_grade' and is_master:
        min2, min3, min4, min5 = _get_member_grade_config()
        member_grade_min2, member_grade_min3 = min2, min3
        member_grade_min4, member_grade_min5 = min4, min5
        for u in User.query.order_by(User.id.asc()).all():
            if u.is_admin:
                continue
            total_paid = _get_user_total_paid(u.id)
            order_count = Order.query.filter(Order.user_id == u.id, Order.status.notin_(['취소', '환불'])).count()
            member_grade_users.append({
                'id': u.id, 'email': u.email or '', 'name': u.name or '',
                'member_grade': getattr(u, 'member_grade', 1) or 1,
                'member_grade_overridden': getattr(u, 'member_grade_overridden', False),
                'total_paid': total_paid, 'order_count': order_count
            })

    point_accumulation_rate = point_min_order = point_max_use = 0
    point_users = []
    if tab == 'point_manage' and is_master:
        rate, min_ord, max_pts = _get_point_config()
        point_accumulation_rate, point_min_order, point_max_use = rate, min_ord, max_pts
        for u in User.query.order_by(User.id.asc()).all():
            point_users.append({
                'id': u.id, 'email': u.email or '', 'name': u.name or '',
                'points': getattr(u, 'points', 0) or 0
            })

    admin_members = []
    if tab == 'members' and is_master:
        admin_members = User.query.order_by(User.id.asc()).all()

    message_templates = []
    messages_history = []
    if tab == 'messages' and is_master:
        template_types = ['welcome', 'order_created', 'order_cancelled', 'part_cancelled', 'out_of_stock', 'delivery_requested', 'delivery_in_progress', 'delivery_complete', 'delivery_delayed']
        for mt in template_types:
            t = MessageTemplate.query.filter_by(msg_type=mt).first()
            def_title, def_body = _DEFAULT_MESSAGES.get(mt, ('', ''))
            message_templates.append({'msg_type': mt, 'title': t.title if t else def_title, 'body': t.body if t else def_body})
        history_rows = db.session.query(UserMessage, User).join(User, UserMessage.user_id == User.id).order_by(UserMessage.created_at.desc()).limit(150).all()
        messages_history = [{'msg': m, 'user_email': u.email or '', 'user_name': u.name or ''} for m, u in history_rows]

    popup_list = []
    if tab == 'popup' and is_master:
        popup_list = SitePopup.query.order_by(SitePopup.sort_order.asc(), SitePopup.start_at.desc().nullslast()).all()

    admin_restaurant_requests = []
    admin_partnership_inquiries = []
    restaurant_recommend_counts = {}  # tab==restaurant_request일 때 채움
    if tab == 'restaurant_request' and is_master:
        admin_restaurant_requests = RestaurantRequest.query.order_by(RestaurantRequest.id.desc()).all()
        restaurant_recommend_counts = {p.id: RestaurantRecommend.query.filter_by(restaurant_request_id=p.id).count() for p in admin_restaurant_requests}
    if tab == 'partnership' and is_master:
        admin_partnership_inquiries = PartnershipInquiry.query.order_by(PartnershipInquiry.id.desc()).all()

    # 3. HTML 템플릿 코드
    # 3. HTML 템플릿 코드 (카테고리 설정 탭 완벽 복구본)
    admin_html = """
    <div class="max-w-7xl mx-auto py-12 px-4 md:px-6 font-black text-xs md:text-sm text-left">
        <div class="flex justify-between items-center mb-10">
            <h2 class="text-2xl md:text-3xl font-black text-orange-700 italic">Admin Panel</h2>
            <div class="flex gap-2">
                 <a href="/" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] hover:bg-gray-200 transition">홈으로</a>
                 <a href="/logout" class="px-4 py-2 bg-red-50 text-red-500 rounded-xl text-[10px] hover:bg-red-100 transition">로그아웃</a>
            </div>
        </div>
        
        <div class="flex border-b border-gray-100 mb-12 bg-white rounded-t-3xl overflow-x-auto">
            <a href="/admin?tab=products" class="px-8 py-5 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품 관리</a>
            <a href="/admin?tab=orders" class="px-8 py-5 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문 및 매출 집계</a>
            <a href="/admin?tab=settlement" class="px-8 py-5 {% if tab == 'settlement' %}border-b-4 border-orange-500 text-orange-600{% endif %}">정산관리</a>
            {% if is_master %}<a href="/admin?tab=categories" class="px-8 py-5 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리 설정</a>{% endif %}
            <a href="/admin?tab=reviews" class="px-8 py-5 {% if tab == 'reviews' %}border-b-4 border-orange-500 text-orange-600{% endif %}">리뷰 관리</a>
            {% if is_master %}<a href="/admin?tab=sellers" class="px-8 py-5 {% if tab == 'sellers' %}border-b-4 border-orange-500 text-orange-600{% endif %}">판매자 관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=delivery_zone" class="px-8 py-5 {% if tab == 'delivery_zone' %}border-b-4 border-orange-500 text-orange-600{% endif %}">배송구역관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=member_grade" class="px-8 py-5 {% if tab == 'member_grade' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원 등급</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=point_manage" class="px-8 py-5 {% if tab == 'point_manage' %}border-b-4 border-orange-500 text-orange-600{% endif %}">포인트 관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=members" class="px-8 py-5 {% if tab == 'members' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=messages" class="px-8 py-5 {% if tab == 'messages' %}border-b-4 border-orange-500 text-orange-600{% endif %}">메시지 발송</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=popup" class="px-8 py-5 {% if tab == 'popup' %}border-b-4 border-orange-500 text-orange-600{% endif %}">알림팝업</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=restaurant_request" class="px-8 py-5 {% if tab == 'restaurant_request' %}border-b-4 border-orange-500 text-orange-600{% endif %}">전국맛집요청</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=partnership" class="px-8 py-5 {% if tab == 'partnership' %}border-b-4 border-orange-500 text-orange-600{% endif %}">제휴문의</a>{% endif %}
        </div>

        {% if tab == 'products' %}
            <div class="mb-8 p-6 rounded-[2rem] border-2 border-amber-200 bg-amber-50/80 text-left">
                <p class="font-black text-amber-800 text-sm mb-3 flex items-center gap-2"><span class="text-lg">👋</span> 처음 사용하시는 관리자용 안내</p>
                <ul class="text-[11px] text-gray-700 space-y-1.5 mb-4">
                    <li><b>엑셀 대량 등록</b>: 아래 「엑셀 업로드」 버튼을 누르면 양식 다운로드와 업로드 창이 나옵니다.</li>
                    <li><b>양식 다운로드</b>: <a href="/admin/product/bulk_upload_template" class="text-blue-600 font-black underline hover:no-underline">📥 상품 엑셀 업로드 양식 다운로드</a></li>
                    <li><b>필수 컬럼</b>: 카테고리, 상품명, 규격, 가격, 이미지파일명 (첫 줄 헤더 이름을 정확히 맞춰주세요)</li>
                    <li><b>이미지 폴더 위치</b>: 서버/프로젝트의 <code class="bg-white px-1.5 py-0.5 rounded border border-amber-200 font-mono text-[10px]">static/uploads/</code> 폴더에 이미지 파일을 넣고, 엑셀에는 <b>파일명만</b> 입력 (예: apple.jpg)</li>
                    <li>카테고리는 먼저 「카테고리 설정」 탭에서 등록한 이름과 동일해야 합니다. 가격은 숫자만 입력하세요.</li>
                </ul>
                <p class="text-[10px] text-amber-700/90">개별 상품은 「+ 상품 등록」으로 하나씩 등록할 수 있습니다.</p>
            </div>
            <div id="excel_upload_form" class="hidden mb-8 bg-blue-50 p-8 rounded-[2rem] border border-blue-100">
                <p class="font-black text-blue-700 mb-4">📦 엑셀 상품 대량 등록</p>
                <div class="flex flex-wrap items-center gap-3 mb-4">
                    <a href="/admin/product/bulk_upload_template" class="bg-white text-blue-600 border border-blue-200 px-5 py-2.5 rounded-xl font-black text-[10px] shadow-sm hover:bg-blue-50 transition">📥 업로드 양식 다운</a>
                </div>
                <form action="/admin/product/bulk_upload" method="POST" enctype="multipart/form-data" class="flex gap-4">
                    <input type="file" name="excel_file" class="bg-white p-3 rounded-xl flex-1 text-xs" accept=".xlsx,.xls" required>
                    <button type="submit" class="bg-blue-600 text-white px-8 rounded-xl font-black">업로드 시작</button>
                </form>
                <div class="mt-5 p-5 bg-white/70 rounded-xl border border-blue-100 text-left text-[11px] text-gray-700 space-y-2">
                    <p class="font-black text-gray-800 mb-2">📋 업로드 양식 사용법 (상세)</p>
                    <p>· <b>필수 컬럼</b>: 카테고리, 상품명, 규격, 가격, 이미지파일명 (헤더 이름 정확히 일치)</p>
                    <p>· <b>이미지 파일 폴더 위치</b>: 프로젝트 내 <code class="bg-gray-100 px-1 rounded">static/uploads/</code> 폴더에 상품 이미지 파일을 넣고, 엑셀의 「이미지파일명」란에는 <b>파일명만</b> 입력 (예: apple.jpg). 해당 경로에 없는 파일명은 이미지 없이 등록됩니다.</p>
                    <p>· 카테고리는 미리 「카테고리 설정」에서 등록된 이름과 동일해야 합니다. 가격은 숫자만 입력하세요.</p>
                </div>
            </div>
            <div class="flex flex-wrap justify-between items-center gap-4 mb-8">
                <form action="/admin" method="GET" class="flex flex-wrap gap-3 items-center">
                    <input type="hidden" name="tab" value="products">
                    <input type="text" name="q" value="{{ product_q or '' }}" placeholder="상품명·설명·카테고리 검색" class="border border-gray-200 rounded-2xl px-4 py-2.5 text-[11px] font-black w-52 focus:ring-2 focus:ring-teal-500">
                    <select name="category" onchange="this.form.submit()" class="border-none bg-white shadow-sm p-3 rounded-2xl text-[11px] font-black">
                        <option value="전체">전체 카테고리</option>
                        {% for c in selectable_categories %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}
                    </select>
                    <button type="submit" class="bg-teal-600 text-white px-5 py-2.5 rounded-2xl font-black text-[10px]">검색</button>
                    {% if product_q %}<a href="/admin?tab=products" class="text-gray-500 text-[10px]">검색초기화</a>{% endif %}
                </form>
                <div class="flex gap-3">
                    <button onclick="document.getElementById('excel_upload_form').classList.toggle('hidden')" class="bg-blue-600 text-white px-5 py-3 rounded-2xl font-black text-[10px] shadow-lg">엑셀 업로드</button>
                    <a href="/admin/add" class="bg-teal-600 text-white px-5 py-3 rounded-2xl font-black text-[10px] shadow-lg">+ 상품 등록</a>
                    {% if is_master %}<a href="/admin/seed_test_data" class="bg-amber-500 text-white px-5 py-3 rounded-2xl font-black text-[10px] shadow-lg hover:bg-amber-600" onclick="return confirm('테스트 카테고리 3개(테스트-채소/과일/수산)와 각 10개씩 가상 상품을 생성합니다. 계속할까요?');">🧪 테스트 데이터 생성</a><a href="/admin/seed_virtual_reviews" class="bg-violet-500 text-white px-5 py-3 rounded-2xl font-black text-[10px] shadow-lg hover:bg-violet-600" onclick="return confirm('전체 상품별로 가상 구매 후기 10개씩 생성합니다. 계속할까요?');">📝 가상 후기 10개씩</a>{% endif %}
                </div>
            </div>
            <div class="bg-white rounded-[2rem] shadow-sm border border-gray-50 overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 border-b border-gray-100 text-gray-400 text-[10px]">
                        <tr><th class="p-6">상품정보</th><th class="p-6 text-center">재고</th><th class="p-6 text-center">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for p in products %}
                        <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition">
                            <td class="p-6"><b class="text-gray-800 text-sm">{{ p.name }}</b><br><span class="text-teal-600 text-[10px]">{{ p.description or '' }}</span></td>
                            <td class="p-6 text-center font-black">{{ p.stock }}개</td>
                            <td class="p-6 text-center space-x-2"><a href="/admin/edit/{{p.id}}" class="text-blue-500">수정</a><a href="/admin/delete/{{p.id}}" class="text-red-300" onclick="return confirm('삭제?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                        {% if not products %}
                        <tr><td colspan="3" class="p-10 text-center text-gray-400 font-bold">조회된 상품이 없습니다.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
            {% if products_total > per_page or product_page > 1 %}
            <div class="flex flex-wrap items-center justify-between gap-4 mt-6">
                <p class="text-[11px] text-gray-500 font-bold">총 {{ products_total }}건 · {{ product_page }} / {{ product_total_pages }} 페이지 (30개씩)</p>
                <div class="flex gap-2">
                    {% if product_page > 1 %}
                    <a href="/admin?tab=products&page={{ product_page - 1 }}{% if product_q %}&q={{ product_q | e }}{% endif %}{% if sel_cat != '전체' %}&category={{ sel_cat }}{% endif %}" class="bg-gray-200 text-gray-700 px-4 py-2 rounded-xl font-black text-[10px] hover:bg-gray-300">이전</a>
                    {% endif %}
                    {% if product_page < product_total_pages %}
                    <a href="/admin?tab=products&page={{ product_page + 1 }}{% if product_q %}&q={{ product_q | e }}{% endif %}{% if sel_cat != '전체' %}&category={{ sel_cat }}{% endif %}" class="bg-gray-200 text-gray-700 px-4 py-2 rounded-xl font-black text-[10px] hover:bg-gray-300">다음</a>
                    {% endif %}
                </div>
            </div>
            {% endif %}

        {% elif tab == 'categories' %}
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-10 text-left">
                <div class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] border border-gray-50 shadow-sm h-fit">
                    <h3 class="text-[11px] md:text-sm text-gray-400 uppercase tracking-widest mb-10 font-black">판매 카테고리 및 사업자 추가</h3>
                    <form action="/admin/category/add" method="POST" class="space-y-5">
                        <input name="cat_name" placeholder="카테고리명 (예: 산지직송 농산물)" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm" required>
                        <textarea name="description" placeholder="카테고리 설명 (배송 정책 등)" class="border border-gray-100 p-5 rounded-2xl w-full h-24 font-black text-sm"></textarea>
                        <input name="manager_email" placeholder="관리 매니저 이메일 (로그인 ID)" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm">
                        <select name="tax_type" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm bg-white">
                            <option value="과세">일반 과세 상품</option>
                            <option value="면세">면세 농축산물</option>
                        </select>
                        <p class="text-[10px] text-amber-600 font-bold uppercase mt-2">노출 회원등급 (몇 등급 이상)</p>
                        <select name="min_member_grade" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs bg-white">
                            <option value="">전체 회원</option>
                            <option value="1">1단계 이상</option>
                            <option value="2">2단계 이상</option>
                            <option value="3">3단계 이상</option>
                            <option value="4">4단계 이상</option>
                            <option value="5">5단계만</option>
                        </select>
                        <div class="border-t border-gray-100 pt-8 space-y-4">
                            <p class="text-[10px] text-teal-600 font-bold tracking-widest uppercase">Seller Business Profile</p>
                            <input name="biz_name" placeholder="사업자 상호명" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="biz_representative" placeholder="대표자 성함" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="biz_reg_number" placeholder="사업자 등록번호 ( - 포함 )" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="biz_address" placeholder="사업장 소재지" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="biz_contact" placeholder="고객 센터 번호" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="seller_link" placeholder="판매자 문의 링크" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <p class="text-[10px] text-blue-600 font-bold tracking-widest uppercase pt-2">정산 계좌</p>
                            <input name="bank_name" placeholder="은행명" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="account_holder" placeholder="예금주" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                            <input name="settlement_account" placeholder="정산계좌 (계좌번호)" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm">
                        </div>
                        <button class="w-full bg-teal-600 text-white py-5 rounded-3xl font-black text-base md:text-lg shadow-xl hover:bg-teal-700 transition">신규 카테고리 생성</button>
                    </form>
                </div>
                
                <div class="bg-white rounded-[2.5rem] md:rounded-[3.5rem] border border-gray-50 shadow-sm overflow-hidden h-fit">
                    <table class="w-full text-left">
                        <thead class="bg-gray-50 border-b border-gray-100 font-bold uppercase text-[10px] md:text-xs">
                            <tr><th class="p-6">순서</th><th class="p-6">카테고리 정보</th><th class="p-6 text-center">관리</th></tr>
                        </thead>
                        <tbody>
                            {% for c in categories %}
                            <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition">
                                <td class="p-6 flex gap-2">
                                    <a href="/admin/category/move/{{c.id}}/up" class="text-blue-500 hover:scale-125 transition"><i class="fas fa-chevron-up"></i></a>
                                    <a href="/admin/category/move/{{c.id}}/down" class="text-red-500 hover:scale-125 transition"><i class="fas fa-chevron-down"></i></a>
                                </td>
                                <td class="p-6">
                                    <b class="text-gray-800">{{ c.name }}</b><br>
                                    <span class="text-gray-400 text-[10px]">매니저: {{ c.manager_email or '미지정' }}</span>
                                </td>
                                <td class="p-6 text-center space-x-3 text-[10px]">
                                    <a href="/admin/category/edit/{{c.id}}" class="text-blue-500 font-bold hover:underline">수정</a>
                                    <a href="/admin/category/delete/{{c.id}}" class="text-red-200 hover:text-red-500 transition" onclick="return confirm('삭제하시겠습니까?')">삭제</a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        {% elif tab == 'delivery_zone' %}
            {% if kakao_map_app_key %}
            <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={{ kakao_map_app_key }}"></script>
            {% else %}
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="">
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
            {% endif %}
            <div class="mb-10 p-6 bg-teal-50 border border-teal-200 rounded-2xl">
                <h3 class="text-base font-black text-teal-800 italic mb-2">퀵지역 설정 <span class="text-teal-600 text-xs font-bold">(우선 적용, 그 외 배송불가)</span></h3>
                <p class="text-[11px] text-teal-700 font-bold mb-3"><strong>방법 1) 지도에서 좌표로 설정</strong> — 아래 지도에서 「퀵지역 편집」 선택 후 클릭해 꼭짓점을 찍고 <strong>퀵지역 폴리곤 저장</strong>. <strong>방법 2) 지역명 입력</strong> — 주소에 포함되면 배송가능인 지역명을 쉼표로 입력.</p>
                <p class="text-[10px] text-teal-600 mb-3">※ 퀵지역 좌표(폴리곤)가 있으면 좌표로만 판단합니다. 없으면 지역명으로 판단하며, 둘 다 없으면 일반 폴리곤만 사용합니다.</p>
                <div class="flex gap-2 flex-wrap items-center mb-3">
                    <input type="text" id="quick_region_input" value="{{ delivery_zone_quick_regions | join(', ') }}" placeholder="송도동, 선린동 (좌표 대신 사용 시)" class="flex-1 min-w-[200px] border border-teal-200 rounded-xl px-4 py-2.5 text-sm font-bold text-gray-800">
                    <button type="button" id="quick_region_save_btn" class="px-5 py-2.5 bg-teal-600 text-white rounded-xl font-black text-xs shadow hover:bg-teal-700">퀵지역(이름) 저장</button>
                </div>
                <label class="flex items-center gap-2 cursor-pointer mb-2">
                    <input type="checkbox" id="use_quick_region_only" {% if delivery_zone_use_quick_only %}checked{% endif %} class="rounded border-teal-300 text-teal-600 focus:ring-teal-500">
                    <span class="text-sm font-bold text-teal-800">퀵지역만 사용 — 퀵지역(좌표/이름) 있으면 그만 배송가능, 그 외 배송불가</span>
                </label>
            </div>
            <div class="mb-10 p-6 bg-amber-50 border border-amber-200 rounded-2xl">
                <h3 class="text-base font-black text-amber-800 italic mb-2">퀵 지역 추가 배송료 · 안내 문구 <span class="text-amber-600 text-xs font-bold">(수정 가능)</span></h3>
                <p class="text-[11px] text-amber-700 font-bold mb-3">퀵 폴리곤 지역 주문 시 결제 화면에 안내되는 문구와 추가 배송료(원)입니다. 동의 시 해당 금액이 결제에 포함됩니다.</p>
                <div class="flex flex-wrap gap-3 items-end mb-3">
                    <label class="flex flex-col gap-1">
                        <span class="text-[10px] text-amber-700 font-black uppercase">퀵 추가 배송료 (원)</span>
                        <input type="number" id="quick_extra_fee_input" min="0" step="1" value="{{ delivery_zone_quick_extra_fee }}" class="w-32 border border-amber-200 rounded-xl px-3 py-2 text-sm font-black text-gray-800">
                    </label>
                    <button type="button" id="quick_extra_save_btn" class="px-5 py-2.5 bg-amber-600 text-white rounded-xl font-black text-xs shadow hover:bg-amber-700">저장</button>
                </div>
                <label class="flex flex-col gap-1">
                    <span class="text-[10px] text-amber-700 font-black uppercase">퀵 배송 안내 문구 (결제 전 고객에게 표시)</span>
                    <textarea id="quick_extra_message_input" rows="3" class="w-full border border-amber-200 rounded-xl px-4 py-3 text-sm font-bold text-gray-800 placeholder-gray-400" placeholder="해당 주소는 배송지역이 아닙니다. 배송료 추가 시 퀵으로 배송됩니다. 추가하시고 주문하시겠습니까?">{{ delivery_zone_quick_extra_message }}</textarea>
                </label>
            </div>
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">지도에서 배송구역 설정 (좌표 클릭)</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-2">편집할 구역을 선택한 뒤 지도를 클릭해 꼭짓점을 추가하세요. <span class="text-orange-600 font-black">주황색 = 일반 배송구역</span> (퀵지역 비었을 때만 사용), <span class="text-teal-600 font-black">틸색 = 퀵지역</span> (우선 적용).</p>
                <div class="flex flex-wrap gap-3 mb-3 items-center">
                    <span class="text-xs font-black text-gray-600">지금 편집:</span>
                    <button type="button" id="dz_edit_main_btn" class="px-4 py-2 rounded-xl font-black text-xs bg-orange-100 text-orange-700 border-2 border-orange-300">일반 폴리곤</button>
                    <button type="button" id="dz_edit_quick_btn" class="px-4 py-2 rounded-xl font-black text-xs bg-teal-100 text-teal-700 border-2 border-teal-300">퀵지역 폴리곤</button>
                </div>
                <div class="flex gap-3 mb-3 items-center flex-wrap">
                    <button type="button" id="dz_save_btn" class="px-5 py-2.5 bg-orange-600 text-white rounded-xl font-black text-xs shadow hover:bg-orange-700">일반 폴리곤 저장</button>
                    <button type="button" id="dz_reset_btn" class="px-5 py-2.5 bg-gray-200 text-gray-700 rounded-xl font-black text-xs hover:bg-gray-300">일반 초기화</button>
                    <span id="dz_coords_display" class="text-[11px] text-gray-600 font-bold"></span>
                </div>
                <div class="flex gap-3 mb-3 items-center flex-wrap">
                    <button type="button" id="dz_quick_save_btn" class="px-5 py-2.5 bg-teal-600 text-white rounded-xl font-black text-xs shadow hover:bg-teal-700">퀵지역 폴리곤 저장</button>
                    <button type="button" id="dz_quick_reset_btn" class="px-5 py-2.5 bg-gray-200 text-gray-700 rounded-xl font-black text-xs hover:bg-gray-300">퀵지역 초기화</button>
                    <span id="dz_quick_coords_display" class="text-[11px] text-teal-700 font-bold"></span>
                </div>
                <div id="delivery_zone_map" class="w-full rounded-2xl border border-gray-200 overflow-hidden" style="height: 500px;"></div>
                <p class="text-[10px] text-gray-500 mt-2">꼭짓점 3개 이상 필요. {% if not kakao_map_app_key %}(카카오맵: KAKAO_MAP_APP_KEY 설정){% endif %}</p>
            </div>
            <script>
            (function(){
                var initialPolygon = {{ delivery_zone_polygon | tojson }};
                var initialQuickPolygon = {{ delivery_zone_quick_polygon | tojson }};
                var yeonsu = [37.3931, 126.6397];
                var points = Array.isArray(initialPolygon) ? initialPolygon.slice() : [];
                var quickPoints = Array.isArray(initialQuickPolygon) ? initialQuickPolygon.slice() : [];
                var editMode = 'main';
                var useKakao = {{ 'true' if kakao_map_app_key else 'false' }};

                function updateCoordsDisplay() {
                    var el = document.getElementById('dz_coords_display');
                    if (el) el.textContent = points.length ? '일반 꼭짓점 ' + points.length + '개' : '';
                    var qel = document.getElementById('dz_quick_coords_display');
                    if (qel) qel.textContent = quickPoints.length ? '퀵지역 꼭짓점 ' + quickPoints.length + '개' : '';
                    var mainBtn = document.getElementById('dz_edit_main_btn');
                    var quickBtn = document.getElementById('dz_edit_quick_btn');
                    if (mainBtn) { mainBtn.className = editMode === 'main' ? 'px-4 py-2 rounded-xl font-black text-xs bg-orange-600 text-white border-2 border-orange-700' : 'px-4 py-2 rounded-xl font-black text-xs bg-orange-100 text-orange-700 border-2 border-orange-300'; }
                    if (quickBtn) { quickBtn.className = editMode === 'quick' ? 'px-4 py-2 rounded-xl font-black text-xs bg-teal-600 text-white border-2 border-teal-700' : 'px-4 py-2 rounded-xl font-black text-xs bg-teal-100 text-teal-700 border-2 border-teal-300'; }
                }

                function bindButtons() {
                    document.getElementById('dz_save_btn').addEventListener('click', function() {
                        if (points.length < 3) { alert('일반 폴리곤 꼭짓점을 3개 이상 찍어주세요.'); return; }
                        fetch('/admin/delivery_zone/api', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify({ polygon: points }) })
                        .then(function(r) { return r.json(); }).then(function(d) { if (d.error) alert(d.error); else alert('일반 폴리곤 저장되었습니다.'); }).catch(function() { alert('저장 실패'); });
                    });
                    document.getElementById('dz_reset_btn').addEventListener('click', function() { points = []; if (window.dzRedraw) window.dzRedraw(); updateCoordsDisplay(); });
                    document.getElementById('dz_quick_save_btn').addEventListener('click', function() {
                        if (quickPoints.length < 3) { alert('퀵지역 폴리곤 꼭짓점을 3개 이상 찍어주세요.'); return; }
                        fetch('/admin/delivery_zone/api', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify({ quick_region_polygon: quickPoints }) })
                        .then(function(r) { return r.json(); }).then(function(d) { if (d.error) alert(d.error); else alert('퀵지역 폴리곤 저장되었습니다. 그 외 지역 배송불가 적용.'); }).catch(function() { alert('저장 실패'); });
                    });
                    document.getElementById('dz_quick_reset_btn').addEventListener('click', function() { quickPoints = []; if (window.dzRedraw) window.dzRedraw(); updateCoordsDisplay(); });
                    document.getElementById('dz_edit_main_btn').addEventListener('click', function() { editMode = 'main'; updateCoordsDisplay(); });
                    document.getElementById('dz_edit_quick_btn').addEventListener('click', function() { editMode = 'quick'; updateCoordsDisplay(); });
                    var qrInput = document.getElementById('quick_region_input');
                    var useQuickOnlyCb = document.getElementById('use_quick_region_only');
                    document.getElementById('quick_region_save_btn').addEventListener('click', function() {
                        var raw = (qrInput && qrInput.value) ? qrInput.value.trim() : '';
                        var list = raw ? raw.replace(/，/g, ',').split(',').map(function(s){ return s.trim(); }).filter(Boolean) : [];
                        var useQuickOnly = useQuickOnlyCb && useQuickOnlyCb.checked;
                        fetch('/admin/delivery_zone/api', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify({ quick_region_names: list, use_quick_region_only: useQuickOnly }) })
                        .then(function(r) { return r.json(); }).then(function(d) { if (d.error) alert(d.error); else alert('퀵지역(이름) 저장되었습니다.'); }).catch(function() { alert('저장 실패'); });
                    });
                    var feeIn = document.getElementById('quick_extra_fee_input');
                    var msgIn = document.getElementById('quick_extra_message_input');
                    document.getElementById('quick_extra_save_btn').addEventListener('click', function() {
                        var fee = feeIn ? (parseInt(feeIn.value, 10) || 0) : 10000;
                        var msg = (msgIn && msgIn.value) ? msgIn.value.trim() : '';
                        fetch('/admin/delivery_zone/api', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify({ quick_extra_fee: fee, quick_extra_message: msg }) })
                        .then(function(r) { return r.json(); }).then(function(d) { if (d.error) alert(d.error); else alert('퀵 추가 배송료·안내 문구가 저장되었습니다.'); }).catch(function() { alert('저장 실패'); });
                    });
                }

                if (useKakao && typeof kakao !== 'undefined') {
                    kakao.maps.load(function() {
                        var container = document.getElementById('delivery_zone_map');
                        var map = new kakao.maps.Map(container, { center: new kakao.maps.LatLng(yeonsu[0], yeonsu[1]), level: 5 });
                        var mainMarkers = [], mainLine = null, quickMarkers = [], quickLine = null;

                        window.dzRedraw = function() {
                            mainMarkers.forEach(function(m) { m.setMap(null); }); mainMarkers = [];
                            if (mainLine) { mainLine.setMap(null); mainLine = null; }
                            points.forEach(function(p) { mainMarkers.push(new kakao.maps.Marker({ position: new kakao.maps.LatLng(p[0], p[1]), map: map })); });
                            if (points.length >= 2) { mainLine = new kakao.maps.Polyline({ path: points.map(function(p){ return new kakao.maps.LatLng(p[0],p[1]); }), strokeColor: '#ea580c', strokeWeight: 4 }); mainLine.setMap(map); }
                            quickMarkers.forEach(function(m) { m.setMap(null); }); quickMarkers = [];
                            if (quickLine) { quickLine.setMap(null); quickLine = null; }
                            quickPoints.forEach(function(p) { quickMarkers.push(new kakao.maps.Marker({ position: new kakao.maps.LatLng(p[0], p[1]), map: map })); });
                            if (quickPoints.length >= 2) { quickLine = new kakao.maps.Polyline({ path: quickPoints.map(function(p){ return new kakao.maps.LatLng(p[0],p[1]); }), strokeColor: '#0d9488', strokeWeight: 5 }); quickLine.setMap(map); }
                            updateCoordsDisplay();
                        };

                        kakao.maps.event.addListener(map, 'click', function(ev) {
                            var lat = ev.latLng.getLat(), lng = ev.latLng.getLng();
                            if (editMode === 'main') points.push([lat, lng]); else quickPoints.push([lat, lng]);
                            window.dzRedraw();
                        });

                        bindButtons();
                        window.dzRedraw();
                    });
                } else {
                    var map = L.map('delivery_zone_map').setView(yeonsu, 14);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(map);
                    var mainLayer = L.layerGroup().addTo(map), quickLayer = L.layerGroup().addTo(map);
                    var mainPoly = null, quickPoly = null;

                    window.dzRedraw = function() {
                        mainLayer.clearLayers(); quickLayer.clearLayers();
                        if (mainPoly) { map.removeLayer(mainPoly); mainPoly = null; }
                        if (quickPoly) { map.removeLayer(quickPoly); quickPoly = null; }
                        points.forEach(function(p) { L.marker(p).addTo(mainLayer); });
                        quickPoints.forEach(function(p) { L.marker(p).addTo(quickLayer); });
                        if (points.length >= 2) { mainPoly = L.polyline(points, { color: '#ea580c', weight: 4 }).addTo(map); }
                        if (quickPoints.length >= 2) { quickPoly = L.polyline(quickPoints, { color: '#0d9488', weight: 5 }).addTo(map); }
                        updateCoordsDisplay();
                    };

                    map.on('click', function(e) {
                        var pt = [e.latlng.lat, e.latlng.lng];
                        if (editMode === 'main') points.push(pt); else quickPoints.push(pt);
                        window.dzRedraw();
                    });

                    bindButtons();
                    window.dzRedraw();
                }
            })();
            </script>

        {% elif tab == 'restaurant_request' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">전국맛집요청 관리</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">고객이 등록한 전국맛집 요청 글. 숨기면 목록/상세에서 비노출.</p>
                <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                    <table class="w-full text-left text-[11px]">
                        <thead class="bg-gray-50 border-b border-gray-100"><tr><th class="p-4">ID</th><th class="p-4">업체명</th><th class="p-4">작성자</th><th class="p-4">작성일</th><th class="p-4">추천수</th><th class="p-4">관리</th></tr></thead>
                        <tbody>
                            {% for p in admin_restaurant_requests %}
                            <tr class="border-b border-gray-50 hover:bg-gray-50/50">
                                <td class="p-4">{{ p.id }}</td>
                                <td class="p-4 font-bold">{{ p.store_name }}</td>
                                <td class="p-4">{{ p.user_name or '-' }}</td>
                                <td class="p-4">{{ p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '-' }}</td>
                                <td class="p-4">{{ restaurant_recommend_counts.get(p.id, 0) }}</td>
                                <td class="p-4">
                                    <a href="/board/restaurant-request/{{ p.id }}" target="_blank" class="text-teal-600 font-black mr-2">보기</a>
                                    <form action="/admin/board/restaurant-request/{{ p.id }}/hide" method="POST" class="inline" onsubmit="return confirm('숨기시겠습니까?');"><button type="submit" class="text-amber-600 font-black">{{ '숨김해제' if p.is_hidden else '숨기기' }}</button></form>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="p-8 text-center text-gray-400">등록된 글이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        {% elif tab == 'partnership' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">제휴문의 관리</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">비밀글 포함. 숨기면 목록에서 비노출. 관리자 메모는 고객에게 보이지 않습니다.</p>
                <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                    <table class="w-full text-left text-[11px]">
                        <thead class="bg-gray-50 border-b border-gray-100"><tr><th class="p-4">ID</th><th class="p-4">제휴종류</th><th class="p-4">작성자</th><th class="p-4">작성일</th><th class="p-4">비밀</th><th class="p-4">관리</th></tr></thead>
                        <tbody>
                            {% for p in admin_partnership_inquiries %}
                            <tr class="border-b border-gray-50 hover:bg-gray-50/50">
                                <td class="p-4">{{ p.id }}</td>
                                <td class="p-4 font-bold">{{ p.partnership_type or '-' }}</td>
                                <td class="p-4">{{ p.user_name or '-' }}</td>
                                <td class="p-4">{{ p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '-' }}</td>
                                <td class="p-4">{{ 'Y' if p.is_secret else '-' }}</td>
                                <td class="p-4">
                                    <a href="/board/partnership/{{ p.id }}" target="_blank" class="text-teal-600 font-black mr-2">보기</a>
                                    <form action="/admin/board/partnership/{{ p.id }}/hide" method="POST" class="inline" onsubmit="return confirm('숨기시겠습니까?');"><button type="submit" class="text-amber-600 font-black">{{ '숨김해제' if p.is_hidden else '숨기기' }}</button></form>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="p-8 text-center text-gray-400">등록된 글이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        {% elif tab == 'member_grade' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">회원 등급 관리 (1·2·3단계)</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">등급은 화면에 노출하지 않으며, 등급별 카테고리 공개·메시지 발송 등에 사용합니다. 직접 설정하거나 구매이력 기준으로 자동 반영할 수 있습니다. 구매금액은 <strong>배송완료</strong>된 품목 금액만 인정됩니다.</p>
                <div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 mb-6">
                    <p class="font-black text-amber-800 text-xs mb-3">자동 등급 기준 (누적 결제액, 원)</p>
                    <form id="mg_config_form" class="flex flex-wrap items-end gap-4">
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">2단계 최소</span><input type="number" name="min_amount_grade2" value="{{ member_grade_min2 }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-32"></label>
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">3단계 최소</span><input type="number" name="min_amount_grade3" value="{{ member_grade_min3 }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-32"></label>
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">4단계 최소</span><input type="number" name="min_amount_grade4" value="{{ member_grade_min4 }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-32"></label>
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">5단계 최소</span><input type="number" name="min_amount_grade5" value="{{ member_grade_min5 }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-32"></label>
                        <button type="submit" class="px-4 py-2 bg-amber-600 text-white rounded-xl font-black text-xs">기준 저장</button>
                    </form>
                    <p class="text-[10px] text-amber-700 mt-2">저장 후 아래 「구매이력으로 자동 반영」 시 위 기준으로 적용됩니다. 직접 설정한 회원은 자동 반영에서 제외됩니다.</p>
                </div>
                <div class="flex gap-3 mb-4">
                    <button type="button" id="mg_auto_apply_btn" class="px-5 py-2.5 bg-teal-600 text-white rounded-xl font-black text-xs">구매이력으로 자동 반영</button>
                    <span id="mg_api_message" class="text-xs font-bold hidden"></span>
                </div>
                <div class="bg-white rounded-2xl border border-gray-200 overflow-x-auto">
                    <table class="w-full text-left min-w-[800px] text-[11px] font-bold border-collapse">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 border border-gray-600">이메일</th>
                                <th class="p-3 border border-gray-600">이름</th>
                                <th class="p-3 border border-gray-600 w-20 text-center">등급</th>
                                <th class="p-3 border border-gray-600 w-24 text-center">직접설정</th>
                                <th class="p-3 border border-gray-600 w-28 text-right">누적결제(원)</th>
                                <th class="p-3 border border-gray-600 w-20 text-center">주문수</th>
                                <th class="p-3 border border-gray-600">설정</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for u in member_grade_users %}
                            <tr class="border-b border-gray-100">
                                <td class="p-3">{{ u.email }}</td>
                                <td class="p-3">{{ u.name }}</td>
                                <td class="p-3 text-center">{{ u.member_grade }}단계</td>
                                <td class="p-3 text-center">{% if u.member_grade_overridden %}Y{% else %}-{% endif %}</td>
                                <td class="p-3 text-right">{{ "{:,}".format(u.total_paid) }}</td>
                                <td class="p-3 text-center">{{ u.order_count }}</td>
                                <td class="p-3">
                                    <select class="mg_grade_select border border-gray-200 rounded-lg px-2 py-1 text-[10px]" data-user-id="{{ u.id }}">
                                        <option value="1" {% if u.member_grade == 1 %}selected{% endif %}>1단계</option>
                                        <option value="2" {% if u.member_grade == 2 %}selected{% endif %}>2단계</option>
                                        <option value="3" {% if u.member_grade == 3 %}selected{% endif %}>3단계</option>
                                        <option value="4" {% if u.member_grade == 4 %}selected{% endif %}>4단계</option>
                                        <option value="5" {% if u.member_grade == 5 %}selected{% endif %}>5단계</option>
                                    </select>
                                    <button type="button" class="mg_set_btn ml-1 px-2 py-1 bg-orange-100 text-orange-700 rounded-lg text-[10px] font-black" data-user-id="{{ u.id }}">직접 설정</button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% if not member_grade_users %}<p class="text-gray-400 text-sm mt-4">등록된 일반 회원이 없습니다.</p>{% endif %}
            </div>
            <script>
            (function(){
                var msgEl = document.getElementById('mg_api_message');
                function showMsg(text, ok) { msgEl.textContent = text; msgEl.classList.remove('hidden'); msgEl.className = 'text-xs font-bold ' + (ok ? 'text-teal-600' : 'text-red-600'); }
                document.getElementById('mg_config_form').addEventListener('submit', function(e) {
                    e.preventDefault();
                    var fd = new FormData(this);
                    fetch('/admin/member_grade/config', { method: 'POST', body: fd }).then(function(r) { return r.json(); }).then(function(d) {
                        showMsg(d.error || '기준 저장되었습니다.', !d.error);
                        if (!d.error) setTimeout(function() { location.reload(); }, 600);
                    }).catch(function() { showMsg('통신 오류', false); });
                });
                document.getElementById('mg_auto_apply_btn').addEventListener('click', function() {
                    fetch('/admin/member_grade/auto_apply', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).then(function(r) { return r.json(); }).then(function(d) {
                        showMsg(d.error || ('자동 반영 완료. ' + (d.updated || 0) + '명 반영됨.'), !d.error);
                        if (!d.error) setTimeout(function() { location.reload(); }, 600);
                    }).catch(function() { showMsg('통신 오류', false); });
                });
                document.querySelectorAll('.mg_set_btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var uid = this.getAttribute('data-user-id');
                        var row = this.closest('tr');
                        var sel = row.querySelector('.mg_grade_select');
                        var grade = sel ? sel.value : 1;
                        fetch('/admin/member_grade/set', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ user_id: parseInt(uid, 10), grade: parseInt(grade, 10), overridden: true })
                        }).then(function(r) { return r.json(); }).then(function(d) {
                            showMsg(d.error || '직접 설정 반영됨.', !d.error);
                            if (!d.error) setTimeout(function() { location.reload(); }, 600);
                        }).catch(function() { showMsg('통신 오류', false); });
                    });
                });
            })();
            </script>

        {% elif tab == 'messages' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">메시지 발송</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">회원 등급을 선택해 가입인사·이벤트·공지·안내 등을 직접 작성해 발송합니다. 아래에서 자동 발송 문구(템플릿)를 수정할 수 있습니다.</p>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="bg-white rounded-2xl border border-gray-200 p-8">
                        <p class="text-[10px] text-teal-600 font-black uppercase mb-3">등급별 직접 발송</p>
                        <form id="admin_message_form" class="space-y-4">
                            <div class="flex flex-wrap gap-4 items-end">
                                <label class="flex flex-col gap-1">
                                    <span class="text-[10px] text-gray-600 font-bold">대상 등급</span>
                                    <select name="target_grade" class="border border-gray-200 rounded-xl px-4 py-2.5 text-xs font-black">
                                        <option value="all">전체 회원</option>
                                        <option value="1">1단계</option>
                                        <option value="2">2단계</option>
                                        <option value="3">3단계</option>
                                        <option value="4">4단계</option>
                                        <option value="5">5단계</option>
                                    </select>
                                </label>
                                <label class="flex flex-col gap-1">
                                    <span class="text-[10px] text-gray-600 font-bold">유형</span>
                                    <select name="msg_type" class="border border-gray-200 rounded-xl px-4 py-2.5 text-xs font-black">
                                        <option value="welcome">가입인사</option>
                                        <option value="event">이벤트</option>
                                        <option value="notice">공지</option>
                                        <option value="guide">안내</option>
                                        <option value="custom">직접작성</option>
                                    </select>
                                </label>
                            </div>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">제목</span>
                                <input type="text" name="title" required placeholder="메시지 제목" class="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm font-black mt-1">
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">내용</span>
                                <textarea name="body" rows="5" placeholder="메시지 내용" class="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm font-black mt-1"></textarea>
                            </label>
                            <button type="submit" class="bg-teal-600 text-white px-8 py-3 rounded-xl font-black text-sm hover:bg-teal-700 transition">발송하기</button>
                        </form>
                        <p id="admin_message_result" class="mt-4 text-sm font-bold hidden"></p>
                    </div>
                    <div class="bg-amber-50/80 rounded-2xl border border-amber-200 p-8">
                        <p class="text-[10px] text-amber-700 font-black uppercase mb-3">자동 발송 템플릿 편집</p>
                        <p class="text-[11px] text-gray-600 mb-4">주문/배송 시 자동 발송되는 문구입니다. <code class="bg-white px-1 rounded text-[10px]">{order_id}</code>는 주문번호로 치환됩니다.</p>
                        <form id="admin_template_form" class="space-y-4">
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">유형</span>
                                <select name="msg_type" id="template_msg_type" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-xs font-black mt-1">
                                    <option value="welcome">가입인사</option>
                                    <option value="order_created">주문접수</option>
                                    <option value="order_cancelled">주문취소</option>
                                    <option value="part_cancelled">일부취소</option>
                                    <option value="out_of_stock">품절취소</option>
                                    <option value="delivery_requested">배송요청</option>
                                    <option value="delivery_in_progress">배송중</option>
                                    <option value="delivery_complete">배송완료</option>
                                    <option value="delivery_delayed">배송지연</option>
                                </select>
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">제목</span>
                                <input type="text" name="title" id="template_title" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1">
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">내용</span>
                                <textarea name="body" id="template_body" rows="4" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1"></textarea>
                            </label>
                            <button type="submit" class="bg-amber-600 text-white px-6 py-2.5 rounded-xl font-black text-xs hover:bg-amber-700 transition">템플릿 저장</button>
                        </form>
                        <p id="admin_template_result" class="mt-3 text-sm font-bold hidden"></p>
                    </div>
                </div>
                <div class="mt-8 p-6 bg-gray-50 rounded-2xl border border-gray-100 text-left text-[11px] text-gray-600">
                    <p class="font-black text-gray-800 mb-2">자동 발송 안내</p>
                    <ul class="list-disc list-inside space-y-1">
                        <li>가입 시: 가입 환영 메시지</li>
                        <li>주문 결제 완료 시: 주문 접수 안내</li>
                        <li>배송 요청/배송중/배송완료/배송지연 시: 배송 상태 알림</li>
                        <li>주문·품목 취소·품절취소 시: 취소·환불 안내</li>
                    </ul>
                </div>
                <div class="mt-8 bg-white rounded-2xl border border-gray-200 overflow-hidden">
                    <p class="p-4 font-black text-gray-800 border-b border-gray-100">발송 이력 (최근 150건)</p>
                    <div class="overflow-x-auto max-h-[400px] overflow-y-auto">
                        <table class="w-full text-left text-[11px] border-collapse">
                            <thead class="bg-gray-100 sticky top-0">
                                <tr>
                                    <th class="p-3 border-b border-gray-200 w-36">발송일시</th>
                                    <th class="p-3 border-b border-gray-200">수신자</th>
                                    <th class="p-3 border-b border-gray-200 w-24">유형</th>
                                    <th class="p-3 border-b border-gray-200">제목</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for row in messages_history %}
                                <tr class="border-b border-gray-50 hover:bg-gray-50/50">
                                    <td class="p-3 text-gray-600">{{ row.msg.created_at.strftime('%Y-%m-%d %H:%M') if row.msg.created_at else '-' }}</td>
                                    <td class="p-3">{{ row.user_email }} ({{ row.user_name }})</td>
                                    <td class="p-3">{{ row.msg.msg_type or 'custom' }}</td>
                                    <td class="p-3 font-bold">{{ (row.msg.title or '')[:50] }}{% if (row.msg.title or '')|length > 50 %}...{% endif %}</td>
                                </tr>
                                {% else %}
                                <tr><td colspan="4" class="p-6 text-center text-gray-400">발송 이력이 없습니다.</td></tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            <script>
            (function(){
                var templateData = {{ message_templates | tojson | safe }};
                var form = document.getElementById('admin_message_form');
                var resultEl = document.getElementById('admin_message_result');
                if (form) form.addEventListener('submit', function(e) {
                    e.preventDefault();
                    var fd = new FormData(form);
                    var obj = { target_grade: fd.get('target_grade') || 'all', msg_type: fd.get('msg_type') || 'custom', title: fd.get('title') || '', body: fd.get('body') || '' };
                    resultEl.classList.add('hidden');
                    fetch('/admin/messages/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj), credentials: 'same-origin' })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            resultEl.textContent = d.success ? (d.message || d.count + '명 발송됨') : (d.message || '발송 실패');
                            resultEl.className = 'mt-4 text-sm font-bold ' + (d.success ? 'text-teal-600' : 'text-red-600');
                            resultEl.classList.remove('hidden');
                            if (d.success) { form.querySelector('[name="title"]').value = ''; form.querySelector('[name="body"]').value = ''; }
                        })
                        .catch(function() { resultEl.textContent = '통신 오류'; resultEl.className = 'mt-4 text-sm font-bold text-red-600'; resultEl.classList.remove('hidden'); });
                });
                var tForm = document.getElementById('admin_template_form');
                var tResult = document.getElementById('admin_template_result');
                var sel = document.getElementById('template_msg_type');
                var tTitle = document.getElementById('template_title');
                var tBody = document.getElementById('template_body');
                function fillTemplate() {
                    var val = sel ? sel.value : '';
                    var t = templateData && templateData.find(function(x) { return x.msg_type === val; });
                    if (t) { if (tTitle) tTitle.value = t.title || ''; if (tBody) tBody.value = t.body || ''; }
                }
                if (sel) sel.addEventListener('change', fillTemplate);
                if (templateData && templateData.length && sel) { fillTemplate(); }
                if (tForm) tForm.addEventListener('submit', function(e) {
                    e.preventDefault();
                    var fd = new FormData(tForm);
                    tResult.classList.add('hidden');
                    fetch('/admin/messages/template', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ msg_type: fd.get('msg_type'), title: fd.get('title'), body: fd.get('body') }), credentials: 'same-origin' })
                        .then(function(r) { return r.json(); })
                        .then(function(d) {
                            tResult.textContent = d.success ? '저장되었습니다.' : (d.message || '저장 실패');
                            tResult.className = 'mt-3 text-sm font-bold ' + (d.success ? 'text-teal-600' : 'text-red-600');
                            tResult.classList.remove('hidden');
                            if (d.success) { var t = templateData && templateData.find(function(x) { return x.msg_type === fd.get('msg_type'); }); if (t) { t.title = fd.get('title'); t.body = fd.get('body'); } }
                        })
                        .catch(function() { tResult.textContent = '통신 오류'; tResult.className = 'mt-3 text-sm font-bold text-red-600'; tResult.classList.remove('hidden'); });
                });
            })();
            </script>

        {% elif tab == 'popup' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">알림 팝업 관리</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">접속 시 노출할 공지·이벤트·알림 팝업. 표시 기간(시작/종료)과 이미지·날짜 문구를 설정할 수 있습니다.</p>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div class="bg-white rounded-2xl border border-gray-200 p-8">
                        <p class="text-[10px] text-teal-600 font-black uppercase mb-4">팝업 등록/수정</p>
                        <form id="popup_form" class="space-y-4 text-left">
                            <input type="hidden" name="id" id="popup_id" value="">
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">유형</span>
                                <select name="popup_type" id="popup_type" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1">
                                    <option value="notice">공지</option>
                                    <option value="event">이벤트</option>
                                    <option value="alert">알림</option>
                                </select>
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">제목</span>
                                <input type="text" name="title" id="popup_title" required class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1" placeholder="팝업 제목">
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">내용</span>
                                <textarea name="body" id="popup_body" rows="4" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1" placeholder="본문 (줄바꿈 가능)"></textarea>
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">노출용 날짜/기간 문구</span>
                                <input type="text" name="display_date" id="popup_display_date" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1" placeholder="예: 2025.02.22 ~ 02.28">
                            </label>
                            <label class="block">
                                <span class="text-[10px] text-gray-600 font-bold">이미지</span>
                                <div class="flex gap-2 mt-1">
                                    <input type="text" name="image_url" id="popup_image_url" class="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black" placeholder="/static/uploads/이미지.jpg 또는 URL">
                                    <input type="file" id="popup_image_file" accept="image/*" class="hidden">
                                    <button type="button" id="popup_image_upload_btn" class="px-4 py-2.5 bg-gray-200 text-gray-700 rounded-xl font-black text-xs whitespace-nowrap">업로드</button>
                                </div>
                            </label>
                            <div class="grid grid-cols-2 gap-4">
                                <label class="block">
                                    <span class="text-[10px] text-gray-600 font-bold">노출 시작일시</span>
                                    <input type="datetime-local" name="start_at" id="popup_start_at" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1">
                                </label>
                                <label class="block">
                                    <span class="text-[10px] text-gray-600 font-bold">노출 종료일시</span>
                                    <input type="datetime-local" name="end_at" id="popup_end_at" class="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm font-black mt-1">
                                </label>
                            </div>
                            <div class="flex flex-wrap items-center gap-4">
                                <label class="flex items-center gap-2">
                                    <input type="checkbox" name="is_active" id="popup_is_active" checked class="rounded">
                                    <span class="text-xs font-bold">활성</span>
                                </label>
                                <label class="flex items-center gap-2">
                                    <span class="text-[10px] text-gray-600 font-bold">순서</span>
                                    <input type="number" name="sort_order" id="popup_sort_order" value="0" class="border border-gray-200 rounded-lg px-2 py-1 w-16 text-xs">
                                </label>
                            </div>
                            <div class="flex gap-3">
                                <button type="submit" class="px-6 py-2.5 bg-teal-600 text-white rounded-xl font-black text-xs">저장</button>
                                <button type="button" id="popup_form_reset" class="px-6 py-2.5 bg-gray-200 text-gray-700 rounded-xl font-black text-xs">초기화</button>
                            </div>
                        </form>
                        <p id="popup_form_result" class="mt-3 text-sm font-bold hidden"></p>
                    </div>
                    <div class="bg-gray-50 rounded-2xl border border-gray-200 p-6">
                        <p class="text-[10px] text-gray-600 font-black uppercase mb-4">등록된 팝업 목록</p>
                        <div class="space-y-3 max-h-[500px] overflow-y-auto">
                            {% for p in popup_list %}
                            <div class="bg-white rounded-xl border border-gray-100 p-4 flex justify-between items-start gap-3">
                                <div class="min-w-0 flex-1">
                                    <span class="text-[10px] px-2 py-0.5 rounded {{ 'bg-amber-100 text-amber-800' if p.popup_type == 'event' else ('bg-blue-100 text-blue-800' if p.popup_type == 'alert' else 'bg-gray-100 text-gray-700') }}">{{ '이벤트' if p.popup_type == 'event' else ('알림' if p.popup_type == 'alert' else '공지') }}</span>
                                    <p class="font-black text-gray-800 mt-1 truncate">{{ p.title or '-' }}</p>
                                    <p class="text-[10px] text-gray-500">{% if p.start_at %}{{ p.start_at.strftime('%Y-%m-%d %H:%M') }}{% else %}시작 미설정{% endif %} ~ {% if p.end_at %}{{ p.end_at.strftime('%Y-%m-%d %H:%M') }}{% else %}종료 미설정{% endif %}</p>
                                </div>
                                <div class="flex gap-2 flex-shrink-0">
                                    <button type="button" class="popup-edit-btn px-3 py-1.5 bg-teal-100 text-teal-700 rounded-lg text-[10px] font-black" data-id="{{ p.id }}" data-title="{{ (p.title or '')|e }}" data-body="{{ (p.body or '')|e }}" data-type="{{ p.popup_type or 'notice' }}" data-display-date="{{ (p.display_date or '')|e }}" data-image-url="{{ (p.image_url or '')|e }}" data-start="{{ p.start_at.strftime('%Y-%m-%dT%H:%M') if p.start_at else '' }}" data-end="{{ p.end_at.strftime('%Y-%m-%dT%H:%M') if p.end_at else '' }}" data-active="{{ '1' if p.is_active else '0' }}" data-sort="{{ p.sort_order or 0 }}">수정</button>
                                    <button type="button" class="popup-del-btn px-3 py-1.5 bg-red-100 text-red-600 rounded-lg text-[10px] font-black" data-id="{{ p.id }}">삭제</button>
                                </div>
                            </div>
                            {% else %}
                            <p class="text-gray-400 text-sm">등록된 팝업이 없습니다.</p>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
            <script>
            (function(){
                var form = document.getElementById('popup_form');
                var resultEl = document.getElementById('popup_form_result');
                function toIsoLocal(d) { if (!d) return ''; var dt = new Date(d); var y=dt.getFullYear(), m=(''+(dt.getMonth()+1)).padStart(2,'0'), day=(''+dt.getDate()).padStart(2,'0'), h=(''+dt.getHours()).padStart(2,'0'), min=(''+dt.getMinutes()).padStart(2,'0'); return y+'-'+m+'-'+day+'T'+h+':'+min; }
                form.addEventListener('submit', function(e){
                    e.preventDefault();
                    var payload = { title: document.getElementById('popup_title').value, body: document.getElementById('popup_body').value, popup_type: document.getElementById('popup_type').value, display_date: document.getElementById('popup_display_date').value || null, image_url: document.getElementById('popup_image_url').value || null, start_at: document.getElementById('popup_start_at').value || null, end_at: document.getElementById('popup_end_at').value || null, is_active: document.getElementById('popup_is_active').checked, sort_order: parseInt(document.getElementById('popup_sort_order').value,10) || 0 };
                    var id = document.getElementById('popup_id').value; if (id) payload.id = parseInt(id,10);
                    resultEl.classList.add('hidden');
                    fetch('/admin/popup/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), credentials: 'same-origin' })
                        .then(function(r){ return r.json(); })
                        .then(function(d){ resultEl.textContent = d.success ? '저장되었습니다.' : (d.message || '실패'); resultEl.className = 'mt-3 text-sm font-bold ' + (d.success ? 'text-teal-600' : 'text-red-600'); resultEl.classList.remove('hidden'); if (d.success) { document.getElementById('popup_form_reset').click(); location.reload(); } })
                        .catch(function(){ resultEl.textContent = '통신 오류'; resultEl.className = 'mt-3 text-sm font-bold text-red-600'; resultEl.classList.remove('hidden'); });
                });
                document.getElementById('popup_form_reset').addEventListener('click', function(){ document.getElementById('popup_id').value = ''; document.getElementById('popup_title').value = ''; document.getElementById('popup_body').value = ''; document.getElementById('popup_type').value = 'notice'; document.getElementById('popup_display_date').value = ''; document.getElementById('popup_image_url').value = ''; document.getElementById('popup_start_at').value = ''; document.getElementById('popup_end_at').value = ''; document.getElementById('popup_is_active').checked = true; document.getElementById('popup_sort_order').value = '0'; });
                document.getElementById('popup_image_upload_btn').addEventListener('click', function(){ document.getElementById('popup_image_file').click(); });
                document.getElementById('popup_image_file').addEventListener('change', function(){
                    var fd = new FormData(); fd.append('image', this.files[0]);
                    fetch('/admin/popup/upload', { method: 'POST', body: fd, credentials: 'same-origin' }).then(function(r){ return r.json(); }).then(function(d){ if (d.success && d.url) document.getElementById('popup_image_url').value = d.url; else if (d.message) alert(d.message); }); this.value = '';
                });
                document.querySelectorAll('.popup-edit-btn').forEach(function(btn){
                    btn.addEventListener('click', function(){ var d=btn.dataset; document.getElementById('popup_id').value = d.id; document.getElementById('popup_title').value = d.title || ''; document.getElementById('popup_body').value = d.body || ''; document.getElementById('popup_type').value = d.type || 'notice'; document.getElementById('popup_display_date').value = d.displayDate || ''; document.getElementById('popup_image_url').value = d.imageUrl || ''; document.getElementById('popup_start_at').value = d.start || ''; document.getElementById('popup_end_at').value = d.end || ''; document.getElementById('popup_is_active').checked = d.active === '1'; document.getElementById('popup_sort_order').value = d.sort || '0'; });
                });
                document.querySelectorAll('.popup-del-btn').forEach(function(btn){
                    btn.addEventListener('click', function(){ if (!confirm('이 팝업을 삭제할까요?')) return; fetch('/admin/popup/delete/' + btn.dataset.id, { method: 'POST', credentials: 'same-origin' }).then(function(){ location.reload(); }); });
                });
            })();
            </script>

        {% elif tab == 'point_manage' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">포인트 정책 및 회원별 관리</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">구매금액의 0.1% 자동 적립, 설정한 금액 이상 구매 시 설정한 한도까지 사용 가능.</p>
                <div class="bg-amber-50 border border-amber-200 rounded-2xl p-6 mb-6">
                    <p class="font-black text-amber-800 text-xs mb-3">포인트 정책 설정</p>
                    <form id="point_config_form" class="flex flex-wrap items-end gap-4">
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">적립률 (1=0.1%)</span><input type="number" name="accumulation_rate" value="{{ point_accumulation_rate }}" min="0" max="100" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-24"></label>
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">사용 가능 최소 주문금액(원)</span><input type="number" name="min_order_to_use" value="{{ point_min_order }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-36"></label>
                        <label class="flex flex-col gap-1"><span class="text-[10px] text-gray-600 font-bold">1회 최대 사용(원)</span><input type="number" name="max_points_per_order" value="{{ point_max_use }}" min="0" class="border border-gray-200 rounded-xl px-3 py-2 text-xs w-32"></label>
                        <button type="submit" class="px-4 py-2 bg-amber-600 text-white rounded-xl font-black text-xs">저장</button>
                    </form>
                    <p class="text-[10px] text-amber-700 mt-2">적립률 1 = 구매금액의 0.1% 자동 적립. 사용 가능 최소 주문금액(원) 이상 구매 시, 1회 최대 사용(원)까지 결제 시 사용 가능.</p>
                </div>
                <div id="point_log_modal" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/50 p-4">
                    <div class="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col">
                        <div class="p-4 border-b border-gray-100 font-black text-gray-800" id="point_log_modal_title">포인트 적립/사용 내역</div>
                        <div class="p-4 overflow-y-auto flex-1 text-[11px]" id="point_log_modal_body"></div>
                        <div class="p-4 border-t border-gray-100"><button type="button" id="point_log_modal_close" class="w-full py-2 bg-gray-200 rounded-xl font-black text-sm">닫기</button></div>
                    </div>
                </div>
                <div class="bg-white rounded-2xl border border-gray-200 overflow-x-auto">
                    <table class="w-full text-left min-w-[700px] text-[11px] font-bold border-collapse">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 border border-gray-600">이메일</th>
                                <th class="p-3 border border-gray-600">이름</th>
                                <th class="p-3 border border-gray-600 w-28 text-right">보유 포인트</th>
                                <th class="p-3 border border-gray-600">지급/차감 · Log</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for u in point_users %}
                            <tr class="border-b border-gray-100">
                                <td class="p-3">{{ u.email }}</td>
                                <td class="p-3">{{ u.name }}</td>
                                <td class="p-3 text-right">{{ "{:,}".format(u.points) }}원</td>
                                <td class="p-3">
                                    <input type="number" class="point_adj_amount border border-gray-200 rounded-lg px-2 py-1 text-[10px] w-20" placeholder="금액" data-user-id="{{ u.id }}">
                                    <select class="point_adj_type border border-gray-200 rounded-lg px-2 py-1 text-[10px] ml-1"><option value="1">지급</option><option value="-1">차감</option></select>
                                    <input type="text" class="point_adj_memo border border-gray-200 rounded-lg px-2 py-1 text-[10px] w-24 ml-1" placeholder="사유" maxlength="50">
                                    <button type="button" class="point_adj_btn ml-1 px-2 py-1 bg-teal-100 text-teal-700 rounded-lg text-[10px] font-black" data-user-id="{{ u.id }}">적용</button>
                                    <button type="button" class="point_log_btn ml-1 px-2 py-1 bg-gray-200 text-gray-700 rounded-lg text-[10px] font-black" data-user-id="{{ u.id }}" data-user-name="{{ u.name or u.email }}">Log</button>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% if not point_users %}<p class="text-gray-400 text-sm mt-4">회원이 없습니다.</p>{% endif %}
            </div>
            <script>
            (function(){
                var msgEl = document.getElementById('pt_api_message');
                function showMsg(text, ok) {
                    var el = document.getElementById('pt_api_message');
                    if (!el) return;
                    el.textContent = text; el.classList.remove('hidden');
                    el.className = 'text-xs font-bold ' + (ok ? 'text-teal-600' : 'text-red-600');
                }
                document.getElementById('point_config_form').addEventListener('submit', function(e) {
                    e.preventDefault();
                    var fd = new FormData(this);
                    fetch('/admin/point/config', { method: 'POST', body: fd }).then(function(r) { return r.json(); }).then(function(d) {
                        showMsg(d.error || '저장되었습니다.', !d.error);
                        if (!d.error) setTimeout(function() { location.reload(); }, 600);
                    }).catch(function() { showMsg('통신 오류', false); });
                });
                document.querySelectorAll('.point_adj_btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var uid = parseInt(this.getAttribute('data-user-id'), 10);
                        var row = this.closest('tr');
                        var amtInput = row.querySelector('.point_adj_amount');
                        var typeSel = row.querySelector('.point_adj_type');
                        var memoInput = row.querySelector('.point_adj_memo');
                        var amt = parseInt(amtInput && amtInput.value, 10) || 0;
                        if (amt <= 0) { alert('금액을 입력하세요.'); return; }
                        var mult = typeSel && typeSel.value === '-1' ? -1 : 1;
                        var body = JSON.stringify({ user_id: uid, amount: amt * mult, memo: memoInput ? memoInput.value : '' });
                        fetch('/admin/point/adjust', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body }).then(function(r) { return r.json(); }).then(function(d) {
                            showMsg(d.error || '적용되었습니다.', !d.error);
                            if (!d.error) setTimeout(function() { location.reload(); }, 600);
                        }).catch(function() { showMsg('통신 오류', false); });
                    });
                });
                var modal = document.getElementById('point_log_modal');
                var modalTitle = document.getElementById('point_log_modal_title');
                var modalBody = document.getElementById('point_log_modal_body');
                document.getElementById('point_log_modal_close').addEventListener('click', function() { modal.classList.add('hidden'); modal.classList.remove('flex'); });
                modal.addEventListener('click', function(e) { if (e.target === modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); } });
                document.querySelectorAll('.point_log_btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var uid = this.getAttribute('data-user-id');
                        var name = this.getAttribute('data-user-name') || '';
                        modalTitle.textContent = '포인트 내역 · ' + name;
                        modalBody.innerHTML = '<p class="text-gray-400">로딩 중...</p>';
                        modal.classList.remove('hidden'); modal.classList.add('flex');
                        fetch('/admin/point/log?user_id=' + uid + '&limit=100').then(function(r) { return r.json(); }).then(function(d) {
                            if (d.error) { modalBody.innerHTML = '<p class="text-red-600">' + d.error + '</p>'; return; }
                            var logs = d.logs || [];
                            if (logs.length === 0) { modalBody.innerHTML = '<p class="text-gray-400">내역이 없습니다.</p>'; return; }
                            var byDate = {};
                            logs.forEach(function(l) {
                                var dk = l.date || '';
                                if (!byDate[dk]) byDate[dk] = { earn: [], use: [] };
                                if (l.amount >= 0) byDate[dk].earn.push(l); else byDate[dk].use.push(l);
                            });
                            var dates = Object.keys(byDate).sort().reverse();
                            var html = '';
                            dates.forEach(function(date) {
                                html += '<div class="mb-6"><p class="text-gray-500 font-black text-[10px] uppercase tracking-wider mb-2 border-b border-gray-100 pb-1">' + date + '</p>';
                                var earn = byDate[date].earn;
                                var use = byDate[date].use;
                                if (earn.length) {
                                    html += '<p class="text-teal-600 font-bold text-[10px] mb-1">적립 내역</p><table class="w-full text-left mb-3"><thead><tr class="border-b border-gray-200 text-gray-500"><th class="py-1 pr-2">일시</th><th class="py-1 pr-2 text-right">금액</th><th class="py-1 pr-2">메모</th><th class="py-1">수정자</th></tr></thead><tbody>';
                                    earn.forEach(function(l) {
                                        html += '<tr class="border-b border-gray-50"><td class="py-1 pr-2 text-gray-500">' + (l.created_at || '') + '</td><td class="py-1 pr-2 text-right text-teal-600">+' + l.amount + '원</td><td class="py-1 pr-2">' + (l.memo || '-') + '</td><td class="py-1 text-gray-500">' + (l.modifier || '시스템') + '</td></tr>';
                                    });
                                    html += '</tbody></table>';
                                }
                                if (use.length) {
                                    html += '<p class="text-red-600 font-bold text-[10px] mb-1">사용 내역</p><table class="w-full text-left"><thead><tr class="border-b border-gray-200 text-gray-500"><th class="py-1 pr-2">일시</th><th class="py-1 pr-2 text-right">금액</th><th class="py-1 pr-2">메모</th><th class="py-1">수정자</th></tr></thead><tbody>';
                                    use.forEach(function(l) {
                                        html += '<tr class="border-b border-gray-50"><td class="py-1 pr-2 text-gray-500">' + (l.created_at || '') + '</td><td class="py-1 pr-2 text-right text-red-600">' + l.amount + '원</td><td class="py-1 pr-2">' + (l.memo || '-') + '</td><td class="py-1 text-gray-500">' + (l.modifier || '시스템') + '</td></tr>';
                                    });
                                    html += '</tbody></table>';
                                }
                                html += '</div>';
                            });
                            modalBody.innerHTML = html;
                        }).catch(function() { modalBody.innerHTML = '<p class="text-red-600">통신 오류</p>'; });
                    });
                });
            })();
            </script>
            <p id="pt_api_message" class="hidden mt-2 text-xs font-bold"></p>

        {% elif tab == 'members' %}
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 italic mb-2">회원관리</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">가입 회원 정보 전체 출력 (비밀번호는 보안상 비표시)</p>
                <div class="bg-white rounded-2xl border border-gray-200 overflow-x-auto">
                    <table class="w-full text-left min-w-[900px] text-[11px] font-bold border-collapse">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 border border-gray-600 w-12 text-center">ID</th>
                                <th class="p-3 border border-gray-600">이메일</th>
                                <th class="p-3 border border-gray-600 w-24">이름</th>
                                <th class="p-3 border border-gray-600 w-28">전화</th>
                                <th class="p-3 border border-gray-600">주소</th>
                                <th class="p-3 border border-gray-600">상세주소</th>
                                <th class="p-3 border border-gray-600 w-20">현관비밀번호</th>
                                <th class="p-3 border border-gray-600">요청메모</th>
                                <th class="p-3 border border-gray-600 w-16 text-center">관리자</th>
                                <th class="p-3 border border-gray-600 w-16 text-center">마케팅</th>
                                <th class="p-3 border border-gray-600 w-14 text-center">등급</th>
                                <th class="p-3 border border-gray-600 w-14 text-center">직접설정</th>
                                <th class="p-3 border border-gray-600 w-20 text-right">포인트</th>
                                <th class="p-3 border border-gray-600 w-32 text-center">관리</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for u in admin_members %}
                            <tr class="border-b border-gray-100 hover:bg-gray-50/50" data-member-id="{{ u.id }}" data-member-name="{{ (u.name or u.email or '')|e }}">
                                <td class="p-3 border border-gray-100 text-center text-gray-500">{{ u.id }}</td>
                                <td class="p-3 border border-gray-100">{{ u.email or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ u.name or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ u.phone or '-' }}</td>
                                <td class="p-3 border border-gray-100 max-w-[180px] truncate" title="{{ u.address or '' }}">{{ u.address or '-' }}</td>
                                <td class="p-3 border border-gray-100 max-w-[120px] truncate" title="{{ u.address_detail or '' }}">{{ u.address_detail or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ u.entrance_pw or '-' }}</td>
                                <td class="p-3 border border-gray-100 max-w-[140px] truncate" title="{{ u.request_memo or '' }}">{{ u.request_memo or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-center">{% if u.is_admin %}Y{% else %}-{% endif %}</td>
                                <td class="p-3 border border-gray-100 text-center">{% if u.consent_marketing %}Y{% else %}-{% endif %}</td>
                                <td class="p-3 border border-gray-100 text-center">{{ u.member_grade or 1 }}</td>
                                <td class="p-3 border border-gray-100 text-center">{% if u.member_grade_overridden|default(false) %}Y{% else %}-{% endif %}</td>
                                <td class="p-3 border border-gray-100 text-right">{{ "{:,}".format(u.points or 0) }}원</td>
                                <td class="p-3 border border-gray-100 text-center">
                                    <button type="button" class="member-msg-btn px-2 py-1.5 rounded-lg bg-teal-600 text-white text-[10px] font-black hover:bg-teal-700 transition" data-uid="{{ u.id }}" data-uname="{{ (u.name or u.email or '')|e }}">메시지</button>
                                    {% if not u.is_admin and u.id != current_user.id %}
                                    <button type="button" class="member-del-btn px-2 py-1.5 rounded-lg bg-red-500 text-white text-[10px] font-black hover:bg-red-600 transition ml-1" data-uid="{{ u.id }}">삭제</button>
                                    {% else %}
                                    <span class="text-gray-300 text-[10px]">-</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="14" class="p-8 text-center text-gray-400 font-bold">등록된 회원이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            <!-- 회원 메시지 발송 모달 (회원관리 탭) -->
            <div id="member-msg-modal" class="fixed inset-0 z-[60] hidden items-center justify-center bg-black/50 p-4">
                <div class="bg-white rounded-2xl shadow-xl max-w-md w-full p-5">
                    <h3 class="text-lg font-black text-gray-800 mb-3">회원에게 메시지 보내기</h3>
                    <p class="text-xs text-gray-500 mb-3" id="member-msg-target">대상: </p>
                    <input type="hidden" id="member-msg-uid" value="">
                    <div class="mb-3">
                        <label class="block text-[10px] font-black text-gray-500 mb-1">제목</label>
                        <input type="text" id="member-msg-title" class="w-full border border-gray-200 p-3 rounded-xl text-sm font-bold" placeholder="제목 입력" maxlength="200">
                    </div>
                    <div class="mb-4">
                        <label class="block text-[10px] font-black text-gray-500 mb-1">내용</label>
                        <textarea id="member-msg-body" class="w-full border border-gray-200 p-3 rounded-xl text-sm font-bold min-h-[100px]" placeholder="내용 입력"></textarea>
                    </div>
                    <div class="flex gap-2">
                        <button type="button" id="member-msg-submit" class="flex-1 py-3 bg-teal-600 text-white rounded-xl font-black text-sm hover:bg-teal-700 transition">발송</button>
                        <button type="button" id="member-msg-cancel" class="px-4 py-3 bg-gray-100 text-gray-600 rounded-xl font-black text-sm hover:bg-gray-200 transition">취소</button>
                    </div>
                    <p id="member-msg-status" class="mt-2 text-xs font-bold hidden"></p>
                </div>
            </div>
            <script>
            (function(){
                var modal = document.getElementById('member-msg-modal');
                var targetEl = document.getElementById('member-msg-target');
                var uidEl = document.getElementById('member-msg-uid');
                var titleEl = document.getElementById('member-msg-title');
                var bodyEl = document.getElementById('member-msg-body');
                var statusEl = document.getElementById('member-msg-status');
                var submitBtn = document.getElementById('member-msg-submit');
                var cancelBtn = document.getElementById('member-msg-cancel');
                if (!modal || !uidEl) return;
                function showModal(uid, uname) {
                    uidEl.value = uid;
                    targetEl.textContent = '대상: ' + (uname || '회원 #' + uid);
                    titleEl.value = '';
                    bodyEl.value = '';
                    statusEl.classList.add('hidden');
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                    if (titleEl) titleEl.focus();
                }
                function hideModal() {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                }
                document.querySelectorAll('.member-msg-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var uid = this.getAttribute('data-uid');
                        var uname = this.getAttribute('data-uname') || '';
                        showModal(uid, uname);
                    });
                });
                if (cancelBtn) cancelBtn.addEventListener('click', hideModal);
                modal.addEventListener('click', function(e) { if (e.target === modal) hideModal(); });
                if (submitBtn) submitBtn.addEventListener('click', function() {
                    var uid = uidEl.value;
                    var title = (titleEl && titleEl.value) ? titleEl.value.trim() : '';
                    if (!title) { statusEl.textContent = '제목을 입력해 주세요.'; statusEl.classList.remove('hidden'); statusEl.className = 'mt-2 text-xs font-bold text-red-600'; return; }
                    statusEl.textContent = '발송 중...';
                    statusEl.classList.remove('hidden');
                    statusEl.className = 'mt-2 text-xs font-bold text-gray-600';
                    submitBtn.disabled = true;
                    fetch('/admin/api/member/' + uid + '/message', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                        body: JSON.stringify({ title: title, body: (bodyEl && bodyEl.value) ? bodyEl.value.trim() : '' }),
                        credentials: 'same-origin'
                    }).then(function(r) { return r.json(); }).then(function(d) {
                        if (d.success) { statusEl.textContent = d.message || '발송되었습니다.'; statusEl.className = 'mt-2 text-xs font-bold text-teal-600'; setTimeout(hideModal, 1200); }
                        else { statusEl.textContent = d.message || '발송 실패'; statusEl.className = 'mt-2 text-xs font-bold text-red-600'; }
                    }).catch(function() { statusEl.textContent = '요청 실패'; statusEl.className = 'mt-2 text-xs font-bold text-red-600'; }).finally(function() { submitBtn.disabled = false; });
                });
                document.querySelectorAll('.member-del-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var uid = this.getAttribute('data-uid');
                        if (!confirm('이 회원을 정말 삭제할까요? 주문 이력이 있으면 삭제되지 않습니다.')) return;
                        fetch('/admin/api/member/' + uid + '/delete', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
                            .then(function(r) { return r.json(); })
                            .then(function(d) {
                                if (d.success) { var row = document.querySelector('tr[data-member-id="' + uid + '"]'); if (row) row.remove(); alert(d.message); }
                                else { alert(d.message || '삭제에 실패했습니다.'); }
                            })
                            .catch(function() { alert('요청 실패'); });
                    });
                });
            })();
            </script>

        {% elif tab == 'sellers' %}
            <div class="mb-12">
                <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
                    <div>
                        <h3 class="text-lg font-black text-gray-800 italic">Seller Business Profile (판매자 정보)</h3>
                        <p class="text-[11px] text-gray-500 font-bold mt-1">엑셀 형식으로 정렬된 판매자별 사업자·정산 정보</p>
                    </div>
                    <a href="/admin/sellers/excel" class="bg-teal-600 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-teal-700">엑셀 다운로드</a>
                </div>
                <div class="flex gap-2 mb-4">
                    <a href="/admin?tab=sellers&seller_tax=전체" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '전체' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">전체</a>
                    <a href="/admin?tab=sellers&seller_tax=과세" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '과세' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">과세</a>
                    <a href="/admin?tab=sellers&seller_tax=면세" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '면세' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">면세</a>
                </div>
                <div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-x-auto">
                    <table class="w-full text-left min-w-[1000px] text-[11px] font-bold border-collapse">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 border border-gray-600 w-12 text-center">순서</th>
                                <th class="p-3 border border-gray-600 w-16 text-center">과세/면세</th>
                                <th class="p-3 border border-gray-600">카테고리</th>
                                <th class="p-3 border border-gray-600">상호</th>
                                <th class="p-3 border border-gray-600">대표자</th>
                                <th class="p-3 border border-gray-600">사업자등록번호</th>
                                <th class="p-3 border border-gray-600">소재지</th>
                                <th class="p-3 border border-gray-600">고객센터</th>
                                <th class="p-3 border border-gray-600">문의링크</th>
                                <th class="p-3 border border-gray-600">은행명</th>
                                <th class="p-3 border border-gray-600">예금주</th>
                                <th class="p-3 border border-gray-600">정산계좌</th>
                                <th class="p-3 border border-gray-600">매니저이메일</th>
                                <th class="p-3 border border-gray-600 w-20 text-center">관리</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for c in sellers_categories %}
                            <tr class="border-b border-gray-100 hover:bg-gray-50/50">
                                <td class="p-3 border border-gray-100 text-center text-gray-500">{{ loop.index }}</td>
                                <td class="p-3 border border-gray-100 text-center"><span class="{% if (c.tax_type or '과세') == '면세' %}text-amber-600{% else %}text-teal-600{% endif %} font-black text-[10px]">{{ c.tax_type or '과세' }}</span></td>
                                <td class="p-3 border border-gray-100 font-black text-teal-700">{{ c.name }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_name or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_representative or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_reg_number or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_address or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_contact or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-teal-600 truncate max-w-[120px]" title="{{ c.seller_inquiry_link or '' }}">{% if c.seller_inquiry_link %}{{ c.seller_inquiry_link[:30] }}{% if c.seller_inquiry_link|length > 30 %}...{% endif %}{% else %}-{% endif %}</td>
                                <td class="p-3 border border-gray-100">{{ c.bank_name or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.account_holder or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.settlement_account or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-gray-500">{{ c.manager_email or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-center"><a href="/admin/category/edit/{{ c.id }}" class="text-blue-600 font-black hover:underline text-[10px]">수정</a></td>
                            </tr>
                            {% else %}
                            <tr><td colspan="14" class="p-8 text-center text-gray-400 font-bold">등록된 카테고리가 없습니다. 카테고리 설정에서 추가해 주세요.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        {% elif tab == 'orders' %}
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 text-left">
                <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm"><p class="text-[9px] text-gray-400 font-black uppercase mb-1">Total Sales</p><p class="text-xl font-black text-teal-600">{{ "{:,}".format(stats.sales) }}원</p></div>
                <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm"><p class="text-[9px] text-gray-400 font-black uppercase mb-1">Orders</p><p class="text-xl font-black text-gray-800">{{ stats.count }}건</p></div>
                <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm"><p class="text-[9px] text-gray-400 font-black uppercase mb-1">Delivery Fees</p><p class="text-xl font-black text-orange-500">{{ "{:,}".format(stats.delivery) }}원</p></div>
                <div class="bg-gray-800 p-6 rounded-[2rem] shadow-xl"><p class="text-[9px] text-gray-400 font-black uppercase mb-1 text-white/50">Grand Total</p><p class="text-xl font-black text-white">{{ "{:,}".format(stats.grand_total) }}원</p></div>
            </div>

            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-sm mb-12">
                <div class="flex gap-2 mb-6">
                    <button type="button" onclick="setDateRange('today')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">오늘</button>
                    <button type="button" onclick="setDateRange('7days')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">최근 7일</button>
                    <button type="button" onclick="setDateRange('month')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">이번 달</button>
                </div>
                <form action="/admin" method="GET" id="date-filter-form" class="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
                    <input type="hidden" name="tab" value="orders">
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">시작 일시</label><input type="datetime-local" name="start_date" id="start_date" value="{{ start_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">종료 일시</label><input type="datetime-local" name="end_date" id="end_date" value="{{ end_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">카테고리</label><select name="order_cat" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체">모든 품목 합산</option>{% for c in selectable_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></div>
                    <button type="submit" class="bg-teal-600 text-white py-4 rounded-2xl font-black shadow-lg">조회하기</button>
                </form>
            </div>

            <div class="mb-8">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-base font-black text-gray-800">판매상품명별 판매수량 총합계</h3>
                    <div class="flex gap-2">
                        <button type="button" onclick="downloadSalesSummaryTableImage()" class="bg-gray-700 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-gray-800">이미지 다운로드</button>
                        <a href="/admin/orders/sales_summary_excel?start_date={{start_date_str}}&end_date={{end_date_str}}&order_ids={{ filtered_orders | map(attribute='order_id') | join(',') }}&order_cat={{ sel_order_cat }}" class="bg-teal-600 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-teal-700">엑셀 다운로드</a>
                    </div>
                </div>
                <div id="sales-summary-table-wrap" class="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto overflow-y-auto max-h-[70rem]" style="max-height: 1300px;">
                    <table id="sales-summary-table" class="w-full text-[11px] font-black min-w-[400px]">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-4 text-left">품목(카테고리)</th>
                                <th class="p-4 text-left">판매상품명</th>
                                <th class="p-4 text-center">판매수량 총합계</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in product_summary_rows %}
                            <tr class="border-b border-gray-100 hover:bg-gray-50/50">
                                <td class="p-4 text-gray-600">{{ row.category }}</td>
                                <td class="p-4 text-gray-800">{{ row.product_name }}</td>
                                <td class="p-4 text-center font-black text-teal-600">{{ row.total_quantity }}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="3" class="p-8 text-center text-gray-400">조회 결과가 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                        <tfoot class="bg-gray-200 border-t-2 border-gray-400">
                            <tr>
                                <td colspan="2" class="p-4 text-right font-black text-gray-800">총합계 수량</td>
                                <td class="p-4 text-center font-black text-teal-600">{{ sales_total_quantity }}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </div>

            <div class="mb-8">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-base font-black text-gray-800">조회 결과 상세 (주문일시 · 판매상품 · 수량 · 결제상태)</h3>
                    <div class="flex gap-2">
                        <button type="button" onclick="downloadSalesTableImage()" class="bg-gray-700 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-gray-800">이미지 다운로드</button>
                        <a href="/admin/orders/sales_excel?start_date={{start_date_str}}&end_date={{end_date_str}}&order_ids={{ filtered_orders | map(attribute='order_id') | join(',') }}&order_cat={{ sel_order_cat }}" class="bg-teal-600 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-teal-700">엑셀 다운로드</a>
                    </div>
                </div>
                <div id="sales-detail-table-wrap" class="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto overflow-y-auto max-h-[70rem]" style="max-height: 1300px;">
                    <table id="sales-detail-table" class="w-full text-[11px] font-black min-w-[600px]">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-4 text-left">주문일시</th>
                                <th class="p-4 text-left">판매상품명</th>
                                <th class="p-4 text-left">카테고리</th>
                                <th class="p-4 text-center">판매수량</th>
                                <th class="p-4 text-center">결제상태</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in sales_table_rows %}
                            <tr class="border-b border-gray-100 hover:bg-gray-50/50">
                                <td class="p-4 text-gray-700">{{ row.order_date }}</td>
                                <td class="p-4 text-gray-800">{{ row.product_name }}</td>
                                <td class="p-4 text-gray-600">{{ row.category | default('') }}</td>
                                <td class="p-4 text-center font-black">{{ row.quantity }}</td>
                                <td class="p-4 text-center {% if row.status in ('결제취소', '취소') %}text-red-500{% else %}text-teal-600{% endif %}">{{ row.status }}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="5" class="p-8 text-center text-gray-400">조회 결과가 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                        <tfoot class="bg-gray-200 border-t-2 border-gray-400">
                            <tr>
                                <td colspan="3" class="p-4 text-right font-black text-gray-800">총합계 수량</td>
                                <td class="p-4 text-center font-black text-teal-600">{{ sales_total_quantity }}</td>
                                <td class="p-4"></td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </div>

            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-sm mb-8">
                <div class="flex gap-2 mb-6">
                    <button type="button" onclick="setDateRange('today')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">오늘</button>
                    <button type="button" onclick="setDateRange('7days')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">최근 7일</button>
                    <button type="button" onclick="setDateRange('month')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">이번 달</button>
                </div>
                <form action="/admin" method="GET" id="date-filter-form-2" class="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
                    <input type="hidden" name="tab" value="orders">
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">시작 일시</label><input type="datetime-local" name="start_date" id="start_date_2" value="{{ start_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">종료 일시</label><input type="datetime-local" name="end_date" id="end_date_2" value="{{ end_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">카테고리</label><select name="order_cat" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체">모든 품목 합산</option>{% for c in selectable_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></div>
                    <button type="submit" class="bg-teal-600 text-white py-4 rounded-2xl font-black shadow-lg">조회하기</button>
                </form>
            </div>

            <div class="flex flex-wrap items-center gap-4 mb-8 bg-gray-50 p-6 rounded-[2.5rem] border border-gray-100">
                <label class="flex items-center gap-2 cursor-pointer bg-white px-6 py-3 rounded-2xl shadow-sm">
                    <input type="checkbox" id="selectAllOrders" class="w-5 h-5 accent-blue-600" onchange="var c=this.checked;document.querySelectorAll('.order-checkbox').forEach(function(b){b.checked=c;});">
                    <span class="text-xs font-black">전체 선택</span>
                </label>
                <button type="button" id="btnBulkDelivery" class="bg-blue-600 text-white px-8 py-3 rounded-2xl font-black text-xs shadow-lg">일괄 배송요청</button>
                <button type="button" id="btnPrintInvoices" class="bg-gray-800 text-white px-8 py-3 rounded-2xl font-black text-xs shadow-lg">송장 출력</button>
                <a href="/admin/orders/excel?start_date={{start_date_str}}&end_date={{end_date_str}}&order_ids={{ filtered_orders | map(attribute='order_id') | join(',') }}" class="bg-teal-100 text-teal-700 px-8 py-3 rounded-2xl font-black text-xs ml-auto">Excel</a>
            </div>

            <div class="bg-white rounded-[2.5rem] shadow-xl border border-gray-50 overflow-x-auto mb-12">
                <table class="w-full text-[10px] font-black min-w-[1200px]">
                    <thead class="bg-gray-800 text-white">
                        <tr><th class="p-6 text-center">선택</th><th class="p-6">오더넘버</th><th class="p-6">주문일 상태</th><th class="p-6">고객정보</th><th class="p-6">배송지</th><th class="p-6">품목</th><th class="p-6 text-center">송장</th></tr>
                    </thead>
                    <tbody>
                        {% for o in filtered_orders %}
                        <tr id="row-{{ o.order_id }}" class="border-b border-gray-100 hover:bg-teal-50/30 transition">
                            <td class="p-6 text-center">
                                {% if o.status == '결제완료' %}
                                <input type="checkbox" class="order-checkbox w-5 h-5 accent-blue-600" value="{{ o.order_id }}">
                                {% endif %}
                            </td>
                            <td class="p-6 text-gray-700 font-mono text-[11px]">{{ o.order_id }}</td>
                            <td class="p-6">
                                <span class="text-gray-400 text-[11px]">{{ o.created_at.strftime('%m/%d %H:%M') }}</span><br>
                                <span id="status-{{ o.order_id }}" class="{% if o.status == '결제취소' %}text-red-500{% else %}text-teal-600{% endif %} font-black">[{{ o.status }}]</span><br>
                                <a href="/admin/order/{{ o.id }}/items" class="text-[10px] text-teal-600 hover:underline font-bold">품목상태</a>
                            </td>
                            <td class="p-6"><b>{{ o.customer_name }}</b><br><span class="text-gray-400">{{ o.customer_phone }}</span></td>
                            <td class="p-6 text-gray-500 text-[11px]">{{ o.delivery_address }}</td>
                            <td class="p-6 text-gray-600 font-medium text-[11px]">{{ (o._manager_items | default([])) | join(', ') }}</td>
                            <td class="p-6 text-center">
                                <button type="button" class="invoice-modal-btn bg-gray-700 text-white px-3 py-2 rounded-xl text-[10px] font-black hover:bg-gray-800" data-order-id="{{ o.order_id }}">송장</button>
                            </td>
                        </tr>
                        {% endfor %}
                        {% if not filtered_orders %}
                        <tr><td colspan="7" class="p-10 text-center text-gray-400 font-bold">조회된 오더가 없습니다.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <div id="invoice-print-modal" class="fixed inset-0 z-[9998] hidden flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
                <div class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 max-h-[90vh] flex flex-col">
                    <div class="flex justify-between items-center mb-4 flex-shrink-0">
                        <h3 class="text-lg font-black text-gray-800" id="invoice-modal-title">송장 출력</h3>
                        <button type="button" id="invoice-modal-close" class="w-8 h-8 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center text-xl">&times;</button>
                    </div>
                    <div id="invoice-step-choice" class="flex flex-col gap-3 flex-shrink-0">
                        <p class="text-xs text-gray-500 mb-1">출력 방식을 선택하세요.</p>
                        <button type="button" id="invoice-print-single" class="w-full bg-teal-600 text-white py-3 rounded-xl font-black text-sm hover:bg-teal-700">개별 (이 주문 1건)</button>
                        <button type="button" id="invoice-print-all-show" class="w-full bg-gray-700 text-white py-3 rounded-xl font-black text-sm hover:bg-gray-800">전체 선택 (오더넘버 선택)</button>
                    </div>
                    <div id="invoice-step-list" class="hidden flex flex-col flex-1 min-h-0">
                        <p class="text-xs text-gray-500 mb-2">출력할 오더넘버를 선택하세요.</p>
                        <label class="flex items-center gap-2 cursor-pointer mb-2 p-2 rounded-lg hover:bg-gray-50">
                            <input type="checkbox" id="invoice-select-all-orders" class="w-4 h-4 accent-teal-600">
                            <span class="text-sm font-black text-gray-700">전체 선택</span>
                        </label>
                        <div id="invoice-order-list" class="border border-gray-200 rounded-xl p-3 overflow-y-auto flex-1 mb-4 space-y-1 max-h-48 text-[11px] font-mono"></div>
                        <div class="flex gap-2 flex-shrink-0">
                            <button type="button" id="invoice-back-from-list" class="flex-1 py-2.5 rounded-xl font-black text-sm bg-gray-100 text-gray-700 hover:bg-gray-200">뒤로</button>
                            <button type="button" id="invoice-do-print-selected" class="flex-1 py-2.5 rounded-xl font-black text-sm bg-teal-600 text-white hover:bg-teal-700">송장 출력</button>
                        </div>
                    </div>
                </div>
            </div>

            <script>
            (function() {
                var invoiceModalOrderId = null;
                function getCheckedOrderIds() {
                    var list = [];
                    document.querySelectorAll('.order-checkbox:checked').forEach(function(cb) { list.push(cb.value); });
                    return list;
                }
                function getAllOrderIds() {
                    var list = [];
                    document.querySelectorAll('.order-checkbox').forEach(function(cb) { list.push(cb.value); });
                    return list;
                }
                function openInvoiceModal(orderId) {
                    invoiceModalOrderId = orderId;
                    showInvoiceStep('choice');
                    var modal = document.getElementById('invoice-print-modal');
                    if (modal) { modal.style.display = 'flex'; modal.classList.remove('hidden'); modal.classList.add('flex'); }
                }
                function closeInvoiceModal() {
                    var modal = document.getElementById('invoice-print-modal');
                    if (modal) { modal.style.display = 'none'; modal.classList.add('hidden'); }
                    invoiceModalOrderId = null;
                    showInvoiceStep('choice');
                }
                function showInvoiceStep(step) {
                    var choiceEl = document.getElementById('invoice-step-choice');
                    var listEl = document.getElementById('invoice-step-list');
                    if (step === 'list') {
                        if (choiceEl) choiceEl.classList.add('hidden');
                        if (listEl) { listEl.classList.remove('hidden'); listEl.classList.add('flex'); fillInvoiceOrderList(); }
                    } else {
                        if (choiceEl) choiceEl.classList.remove('hidden');
                        if (listEl) { listEl.classList.add('hidden'); listEl.classList.remove('flex'); }
                    }
                }
                function fillInvoiceOrderList() {
                    var container = document.getElementById('invoice-order-list');
                    var selectAllCb = document.getElementById('invoice-select-all-orders');
                    if (!container) return;
                    var rows = document.querySelectorAll('tr[id^="row-"]');
                    var orderIds = [];
                    rows.forEach(function(tr) {
                        var id = tr.id.replace('row-', '');
                        if (id) orderIds.push(id);
                    });
                    var checkedInTable = {};
                    document.querySelectorAll('.order-checkbox:checked').forEach(function(cb) { checkedInTable[cb.value] = true; });
                    container.innerHTML = '';
                    orderIds.forEach(function(oid) {
                        var label = document.createElement('label');
                        label.className = 'flex items-center gap-2 cursor-pointer p-1.5 rounded hover:bg-gray-50';
                        var cb = document.createElement('input');
                        cb.type = 'checkbox';
                        cb.className = 'invoice-order-cb w-4 h-4 accent-teal-600';
                        cb.value = oid;
                        cb.checked = !!checkedInTable[oid];
                        label.appendChild(cb);
                        label.appendChild(document.createTextNode(oid));
                        container.appendChild(label);
                    });
                    if (selectAllCb) {
                        selectAllCb.checked = orderIds.length > 0 && orderIds.every(function(id) { return checkedInTable[id]; });
                        selectAllCb.onchange = function() {
                            container.querySelectorAll('.invoice-order-cb').forEach(function(c) { c.checked = selectAllCb.checked; });
                        };
                    }
                }
                function getSelectedInvoiceOrderIds() {
                    var list = [];
                    document.querySelectorAll('#invoice-order-list .invoice-order-cb:checked').forEach(function(cb) { list.push(cb.value); });
                    return list;
                }
                function doPrint(ids) {
                    if (!ids || ids.length === 0) { alert("출력할 주문이 없습니다."); return; }
                    window.open('/admin/order/print?ids=' + ids.join(','), '_blank', 'width=800,height=900');
                    closeInvoiceModal();
                }
                document.querySelectorAll('.invoice-modal-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() { openInvoiceModal(this.getAttribute('data-order-id')); });
                });
                var closeBtn = document.getElementById('invoice-modal-close');
                if (closeBtn) closeBtn.addEventListener('click', closeInvoiceModal);
                var singleBtn = document.getElementById('invoice-print-single');
                if (singleBtn) singleBtn.addEventListener('click', function() {
                    if (invoiceModalOrderId) doPrint([invoiceModalOrderId]);
                    else alert("주문을 지정할 수 없습니다.");
                });
                var allShowBtn = document.getElementById('invoice-print-all-show');
                if (allShowBtn) allShowBtn.addEventListener('click', function() { showInvoiceStep('list'); });
                var backBtn = document.getElementById('invoice-back-from-list');
                if (backBtn) backBtn.addEventListener('click', function() { showInvoiceStep('choice'); });
                var doPrintBtn = document.getElementById('invoice-do-print-selected');
                if (doPrintBtn) doPrintBtn.addEventListener('click', function() {
                    var ids = getSelectedInvoiceOrderIds();
                    if (ids.length === 0) { alert("출력할 오더를 선택하세요."); return; }
                    doPrint(ids);
                });
                document.getElementById('invoice-print-modal').addEventListener('click', function(e) {
                    if (e.target === this) closeInvoiceModal();
                });

                window.printSelectedInvoices = function() {
                    var ids = getCheckedOrderIds();
                    if (ids.length === 0) { alert("출력할 주문을 선택하세요."); return; }
                    window.open('/admin/order/print?ids=' + ids.join(','), '_blank', 'width=800,height=900');
                };
                window.requestBulkDelivery = function() {
                    var ids = getCheckedOrderIds();
                    if (ids.length === 0) { alert("선택된 주문이 없습니다."); return; }
                    if (!confirm(ids.length + "건을 일괄 배송 요청하시겠습니까?")) return;
                    fetch('/admin/order/bulk_request_delivery', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ order_ids: ids }),
                        credentials: 'same-origin'
                    }).then(function(r) { return r.json(); }).then(function(data) {
                        if (data.success) {
                            alert("요청되었습니다.");
                            ids.forEach(function(id) {
                                var el = document.getElementById('status-' + id);
                                if (el) el.innerText = '[배송요청]';
                                var row = document.getElementById('row-' + id);
                                if (row) {
                                    var cb = row.querySelector('.order-checkbox');
                                    if (cb) cb.remove();
                                }
                            });
                        } else { alert(data.message || '처리 실패'); }
                    }).catch(function() { alert("통신 오류"); });
                };
                var sel = document.getElementById('selectAllOrders');
                if (sel) sel.addEventListener('change', function() {
                    var c = this.checked;
                    document.querySelectorAll('.order-checkbox').forEach(function(b) { b.checked = c; });
                });
                var btnPrint = document.getElementById('btnPrintInvoices');
                if (btnPrint) btnPrint.addEventListener('click', window.printSelectedInvoices);
                var btnBulk = document.getElementById('btnBulkDelivery');
                if (btnBulk) btnBulk.addEventListener('click', window.requestBulkDelivery);
            })();
            </script>

        {% elif tab == 'settlement' %}
            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-sm mb-12">
                <div class="flex gap-2 mb-6">
                    <button type="button" onclick="setDateRange('today')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">오늘</button>
                    <button type="button" onclick="setDateRange('7days')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">최근 7일</button>
                    <button type="button" onclick="setDateRange('month')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">이번 달</button>
                </div>
                <form action="/admin" method="GET" id="date-filter-form" class="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
                    <input type="hidden" name="tab" value="settlement">
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">시작 일시</label><input type="datetime-local" name="start_date" id="start_date" value="{{ start_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">종료 일시</label><input type="datetime-local" name="end_date" id="end_date" value="{{ end_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">카테고리 필터</label><select name="order_cat" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체">모든 품목 합산</option>{% for c in selectable_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">입금상태</label><select name="settlement_status" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체" {% if sel_settlement_status == '전체' %}selected{% endif %}>전체</option><option value="입금대기" {% if sel_settlement_status == '입금대기' %}selected{% endif %}>입금대기</option><option value="입금완료" {% if sel_settlement_status == '입금완료' %}selected{% endif %}>입금완료</option><option value="취소" {% if sel_settlement_status == '취소' %}selected{% endif %}>취소</option><option value="보류" {% if sel_settlement_status == '보류' %}selected{% endif %}>보류</option></select></div>
                    <button type="submit" class="bg-teal-600 text-white py-4 rounded-2xl font-black shadow-lg">조회하기</button>
                </form>
            </div>

            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 mb-4 italic">📊 정산 상세 (n넘버 기준)</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">고객 결제 시 품목별 고유 n넘버가 부여되며, 해당 번호를 기준으로 정산합니다.</p>
                <div class="flex items-center gap-4 mb-4 flex-wrap">
                    <span class="text-[11px] font-bold text-gray-600">선택 항목 입금상태 변경:</span>
                    <select id="settlement-bulk-status" class="border border-gray-200 rounded-xl px-3 py-2 text-xs font-black bg-white">
                        <option value="입금대기">입금대기</option>
                        <option value="입금완료">입금완료</option>
                        <option value="취소">취소</option>
                        <option value="보류">보류</option>
                    </select>
                    <button type="button" id="settlement-bulk-status-btn" class="bg-teal-600 text-white px-5 py-2 rounded-xl text-xs font-black shadow">적용</button>
                </div>
                <div id="settlement-detail-table-wrap" class="bg-white rounded-[2rem] border border-gray-100 shadow-sm overflow-x-auto">
                    <table class="w-full text-left min-w-[900px] text-[10px] font-black">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 w-12"><input type="checkbox" id="selectAllSettlement" title="전체선택" class="rounded"></th>
                                <th class="p-3">정산번호(n)</th>
                                <th class="p-3">판매일시</th>
                                <th class="p-3">카테고리</th>
                                <th class="p-3 text-center">면세여부</th>
                                <th class="p-3">품목</th>
                                <th class="p-3 text-right">판매금액</th>
                                <th class="p-3 text-right">수수료</th>
                                <th class="p-3 text-right">배송관리비</th>
                                <th class="p-3 text-right">정산합계</th>
                                <th class="p-3 text-center">입금상태(입금일)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for r in settlement_detail_rows %}
                            <tr class="border-b border-gray-50 hover:bg-teal-50/20">
                                <td class="p-3"><input type="checkbox" class="settlement-row-checkbox rounded" value="{{ r.order_item_id }}" data-order-item-id="{{ r.order_item_id }}"></td>
                                <td class="p-3 font-mono text-gray-700">{{ r.settlement_no or '-' }}</td>
                                <td class="p-3 text-gray-700">{{ r.sale_dt }}</td>
                                <td class="p-3 text-gray-600">{{ r.category }}</td>
                                <td class="p-3 text-center text-[9px]">{{ r.tax_exempt }}</td>
                                <td class="p-3 text-gray-800">{{ r.product_name }}</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.sales_amount) }}원</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.fee) }}원</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.delivery_fee) }}원</td>
                                <td class="p-3 text-right font-black text-blue-600">{{ "{:,}".format(r.settlement_total) }}원</td>
                                <td class="p-3 text-center align-top"><span class="{% if r.settlement_status == '입금완료' %}bg-green-100 text-green-700{% else %}bg-orange-100 text-orange-600{% endif %} px-2 py-1 rounded-full text-[9px]">{{ r.settlement_status }}</span>{% if r.settled_at %}<div class="text-[8px] text-gray-500 mt-1">{{ r.settled_at }}</div>{% endif %}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="11" class="p-10 text-center text-gray-400 font-bold text-sm">해당 기간 정산 내역이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="mt-6 p-6 bg-gray-50 rounded-2xl border border-gray-200">
                    <h4 class="text-sm font-black text-gray-700 mb-4">📌 카테고리별 총합계금액</h4>
                    <ul class="space-y-2 text-[11px] font-black">
                        {% for cat_name, total_amt in settlement_category_totals.items() %}
                        <li class="flex justify-between"><span class="text-gray-600">{{ cat_name }}</span><span class="text-teal-600">{{ "{:,}".format(total_amt) }}원</span></li>
                        {% endfor %}
                        <li class="flex justify-between pt-3 border-t-2 border-gray-300 mt-3"><span class="text-gray-800">총합계</span><span class="text-blue-600 font-black">{{ "{:,}".format(settlement_category_totals.values() | sum) }}원</span></li>
                    </ul>
                </div>
            </div>

            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 mb-6 italic">📋 오더별 정산 현황</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">관리 중인 카테고리 품목만 표시됩니다.</p>
                <div class="bg-white rounded-[2rem] border border-gray-100 shadow-sm overflow-x-auto text-left">
                    <table class="w-full text-left min-w-[800px]">
                        <thead class="bg-gray-50 border-b border-gray-100 text-[10px] text-gray-400 font-black">
                            <tr>
                                <th class="p-5">오더넘버</th>
                                <th class="p-5">판매일</th>
                                <th class="p-5">품목</th>
                                <th class="p-5 text-center">수량</th>
                                <th class="p-5 text-center">배송현황</th>
                                <th class="p-5 text-right">가격(정산대상)</th>
                                <th class="p-5 text-right">합계금액</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for o in filtered_orders %}
                            <tr class="border-b border-gray-50 hover:bg-teal-50/20">
                                <td class="p-5 font-mono text-[11px] text-gray-700">{{ o.order_id[-12:] if o.order_id else '-' }}</td>
                                <td class="p-5 text-gray-700 font-bold">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                                <td class="p-5 text-gray-700 text-[11px] leading-relaxed">{{ (o._manager_items | default([])) | join(', ') }}</td>
                                <td class="p-5 text-center font-black">{{ o._manager_qty | default(0) }}</td>
                                <td class="p-5 text-center"><span class="{% if o.status == '결제취소' %}text-red-500{% else %}text-teal-600{% endif %} font-bold text-[11px]">{{ o.status }}</span></td>
                                <td class="p-5 text-right font-black text-blue-600">{{ "{:,}".format(o._manager_subtotal | default(0)) }}원</td>
                                <td class="p-5 text-right font-black text-gray-800">{{ "{:,}".format(o._manager_subtotal | default(0)) }}원</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="7" class="p-10 text-center text-gray-400 font-bold text-sm">해당 기간 주문이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                        <tfoot class="bg-gray-100 border-t-2 border-gray-200">
                            <tr>
                                <td class="p-5 font-black text-gray-500 text-[11px]" colspan="3">총합계</td>
                                <td class="p-5 text-center font-black text-gray-800">{{ order_total_qty }}</td>
                                <td class="p-5"></td>
                                <td class="p-5 text-right font-black text-blue-600">{{ "{:,}".format(order_total_subtotal) }}원</td>
                                <td class="p-5 text-right font-black text-gray-800">{{ "{:,}".format(order_total_subtotal) }}원</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </div>
            <script>
            function setDateRange(range) {
                const startInput = document.getElementById('start_date');
                const endInput = document.getElementById('end_date');
                if (!startInput || !endInput) return;
                const now = new Date();
                let start = new Date();
                let end = new Date();
                if (range === 'today') { start.setHours(0,0,0,0); end.setHours(23,59,59,999); }
                else if (range === '7days') { start.setDate(now.getDate()-7); start.setHours(0,0,0,0); }
                else if (range === 'month') { start.setDate(1); start.setHours(0,0,0,0); }
                const format = (d) => new Date(d.getTime() - (d.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
                startInput.value = format(start);
                endInput.value = format(end);
                document.getElementById('date-filter-form').submit();
            }
            document.getElementById('selectAllSettlement')?.addEventListener('change', function() {
                document.querySelectorAll('.settlement-row-checkbox').forEach(cb => cb.checked = this.checked);
            });
            document.getElementById('settlement-bulk-status-btn')?.addEventListener('click', async function() {
                const ids = Array.from(document.querySelectorAll('.settlement-row-checkbox:checked')).map(cb => cb.value).filter(Boolean);
                if (!ids.length) { alert('선택한 항목이 없습니다.'); return; }
                const status = document.getElementById('settlement-bulk-status')?.value;
                if (!status) return;
                try {
                    const r = await fetch('/admin/settlement/bulk_item_status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_item_ids: ids, settlement_status: status }), credentials: 'same-origin' });
                    const j = await r.json();
                    if (j.success) { alert(j.message); document.getElementById('date-filter-form')?.submit(); } else { alert(j.message || '변경 실패'); }
                } catch (e) { alert('요청 실패'); }
            });
            </script>

        {% elif tab == 'reviews' %}
            <div class="bg-white rounded-[2.5rem] border border-gray-50 shadow-sm overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 border-b border-gray-100 text-[10px]">
                        <tr><th class="p-6">판매자(카테고리)</th><th class="p-6">상품/작성자</th><th class="p-6">내용</th><th class="p-6 text-center">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for r in reviews %}
                        <tr class="border-b border-gray-100 hover:bg-red-50/30">
                            <td class="p-6 text-gray-500 font-bold">{{ category_names.get(r.category_id, '-') }}</td>
                            <td class="p-6"><span class="text-teal-600">[{{ r.product_name }}]</span><br><b>{{ r.user_name }}</b></td>
                            <td class="p-6 text-gray-600 leading-relaxed">{{ r.content }}</td>
                            <td class="p-6 text-center"><a href="/admin/review/delete/{{ r.id }}" class="text-red-500 underline" onclick="return confirm('삭제?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% endif %}
    </div>

    <script>
    function setDateRange(range) {
        const startInput = document.getElementById('start_date');
        const endInput = document.getElementById('end_date');
        const now = new Date();
        let start = new Date();
        let end = new Date();
        if (range === 'today') { start.setHours(0,0,0,0); end.setHours(23,59,59,999); }
        else if (range === '7days') { start.setDate(now.getDate()-7); start.setHours(0,0,0,0); }
        else if (range === 'month') { start.setDate(1); start.setHours(0,0,0,0); }
        const format = (d) => new Date(d.getTime() - (d.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
        var startStr = format(start);
        var endStr = format(end);
        if(startInput) startInput.value = startStr;
        if(endInput) endInput.value = endStr;
        var start2 = document.getElementById('start_date_2');
        var end2 = document.getElementById('end_date_2');
        if(start2) start2.value = startStr;
        if(end2) end2.value = endStr;
        var form = document.getElementById('date-filter-form') || document.getElementById('date-filter-form-2');
        if(form) form.submit();
    }

    (function() {
        window.printSelectedInvoices = function() {
            var boxes = document.querySelectorAll ? document.querySelectorAll('.order-checkbox:checked') : [];
            var selected = [];
            for (var i = 0; i < boxes.length; i++) selected.push(boxes[i].value);
            if (selected.length === 0) { alert("출력할 주문을 선택하세요."); return; }
            window.open('/admin/order/print?ids=' + selected.join(','), '_blank', 'width=800,height=900');
        };
        window.requestBulkDelivery = function() {
            var boxes = document.querySelectorAll ? document.querySelectorAll('.order-checkbox:checked') : [];
            var selected = [];
            for (var i = 0; i < boxes.length; i++) selected.push(boxes[i].value);
            if (selected.length === 0) { alert("선택된 주문이 없습니다."); return; }
            if (!confirm(selected.length + "건을 일괄 배송 요청하시겠습니까?")) return;
            sendDeliveryRequest(selected);
        };
    })();
    function sendDeliveryRequest(ids) {
        fetch('/admin/order/bulk_request_delivery', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_ids: ids }),
            credentials: 'same-origin'
        }).then(function(res){ return res.json(); }).then(function(data) {
            if (data.success) {
                alert(data.message);
                ids.forEach(function(id) {
                    var statusSpan = document.getElementById('status-' + id);
                    if (statusSpan) statusSpan.innerText = '[배송요청]';
                    var row = document.getElementById('row-' + id);
                    if (row) {
                        var cb = row.querySelector('.order-checkbox');
                        if (cb) cb.remove();
                    }
                });
            } else { alert(data.message || '처리 실패'); }
        }).catch(function() { alert("통신 오류"); });
    }

    function bindOrderCheckboxes() {
        var selectAll = document.getElementById('selectAllOrders');
        if (selectAll) {
            selectAll.addEventListener('change', function() {
                document.querySelectorAll('.order-checkbox').forEach(function(cb) { cb.checked = selectAll.checked; });
            });
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindOrderCheckboxes);
    } else {
        bindOrderCheckboxes();
    }

    async function approveSettlement(catName, amt, email) {
        if(!confirm(catName + "의 " + amt.toLocaleString() + "원 정산을 입금 완료처리하시겠습니까?")) return;
        try {
            const res = await fetch('/admin/settlement/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category_name: catName, amount: amt, manager_email: email })
            });
            const result = await res.json();
            if(result.success) { alert(result.message); location.reload(); }
        } catch(e) { alert("서버 오류"); }
    }
    function downloadSalesTableImage() {
        var el = document.getElementById('sales-detail-table-wrap');
        if (!el) { alert('테이블이 없거나 주문 및 매출 집계 탭에서 조회 후 사용해 주세요.'); return; }
        if (typeof html2canvas === 'undefined') {
            alert('이미지 라이브러리 로딩 중... 잠시 후 다시 클릭해 주세요.');
            var s = document.createElement('script');
            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
            s.onload = function() { runDownload(el); };
            document.head.appendChild(s);
            return;
        }
        runDownload(el);
    }
    function runDownload(el) {
        html2canvas(el, { scale: 2, useCORS: true }).then(function(canvas) {
            var a = document.createElement('a');
            a.href = canvas.toDataURL('image/png');
            a.download = '매출상세_' + new Date().toISOString().slice(0,10) + '.png';
            a.click();
        }).catch(function() { alert('이미지 생성에 실패했습니다.'); });
    }
    function downloadSalesSummaryTableImage() {
        var el = document.getElementById('sales-summary-table-wrap');
        if (!el) { alert('테이블이 없거나 주문 및 매출 집계 탭에서 조회 후 사용해 주세요.'); return; }
        if (typeof html2canvas === 'undefined') {
            alert('이미지 라이브러리 로딩 중... 잠시 후 다시 클릭해 주세요.');
            var s = document.createElement('script');
            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
            s.onload = function() { runDownload(el); };
            document.head.appendChild(s);
            return;
        }
        runDownload(el);
    }
    (function() {
        function syncSelectAllFromRowCbs() {
            var cbs = document.querySelectorAll('.settlement-row-cb');
            var checked = document.querySelectorAll('.settlement-row-cb:checked');
            var allChecked = cbs.length > 0 && checked.length === cbs.length;
            document.querySelectorAll('.select-all-orders-settlement, .select-all-settlement-rows').forEach(function(el) { el.checked = allChecked; });
        }
        document.addEventListener('change', function(e) {
            if (!e.target || !e.target.classList) return;
            if (e.target.classList.contains('select-all-orders-settlement') || e.target.classList.contains('select-all-settlement-rows')) {
                var checked = e.target.checked;
                document.querySelectorAll('.settlement-row-cb').forEach(function(cb) { cb.checked = checked; });
            }
            if (e.target.classList.contains('settlement-row-cb')) {
                syncSelectAllFromRowCbs();
            }
        });
        document.addEventListener('click', function(e) {
            if (!e.target || !e.target.classList) return;
            if (e.target.classList.contains('btn-bulk-settlement-status')) {
                var checked = document.querySelectorAll('.settlement-row-cb:checked');
                var orderIdSet = {};
                checked.forEach(function(cb) {
                    var tr = cb.closest('tr');
                    if (tr) {
                        var orderId = tr.getAttribute('data-order-pk');
                        if (orderId) orderIdSet[orderId] = true;
                    }
                });
                var orderIds = Object.keys(orderIdSet).map(function(k) { return parseInt(k, 10); }).filter(function(id) { return !isNaN(id) && id > 0; });
                var sel = document.getElementById('bulkSettlementStatus') || document.querySelector('.bulk-settlement-status');
                var status = (sel && sel.value) ? sel.value : '입금완료';
                if (orderIds.length === 0) { alert('변경할 품목(행)을 선택해 주세요.'); return; }
                if (!confirm('선택한 ' + orderIds.length + '개 주문(오더)을 모두 "' + status + '"(으)로 변경하시겠습니까?')) return;
                var done = 0, fail = 0, failMsgs = [];
                function onEnd() {
                    if (done + fail === orderIds.length) {
                        var msg = '변경 완료: ' + done + '건' + (fail ? ', 실패: ' + fail + '건' : '');
                        if (fail && failMsgs.length) msg += '\n' + failMsgs.slice(0, 3).join('\n') + (failMsgs.length > 3 ? '\n...' : '');
                        alert(msg);
                        location.reload();
                    }
                }
                orderIds.forEach(function(orderId) {
                    fetch('/admin/settlement/order_status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ order_id: orderId, settlement_status: status })
                    }).then(function(r) {
                        return r.json().then(function(data) {
                            return { ok: r.ok, status: r.status, data: data };
                        }).catch(function() { return { ok: false, status: r.status, data: { success: false, message: '응답 파싱 실패' }; });
                    }).then(function(result) {
                        if (result.ok && result.data && result.data.success) { done++; } else { fail++; if (result.data && result.data.message) failMsgs.push(result.data.message); }
                        onEnd();
                    }).catch(function(err) { fail++; failMsgs.push('요청 실패'); onEnd(); });
                });
                return;
            }
            if (e.target.classList.contains('settlement-log-trigger')) {
                var trigger = e.target;
                var contentEl = trigger.parentElement.querySelector('.settlement-log-content');
                var modal = document.getElementById('settlement-log-modal');
                var bodyEl = document.getElementById('settlement-log-modal-body');
                if (contentEl && modal && bodyEl) {
                    bodyEl.innerHTML = contentEl.innerHTML;
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                    modal.setAttribute('aria-hidden', 'false');
                }
                return;
            }
            if (e.target.id === 'settlement-log-modal-close' || e.target.id === 'settlement-log-modal') {
                var modal = document.getElementById('settlement-log-modal');
                if (modal) {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                    modal.setAttribute('aria-hidden', 'true');
                }
                return;
            }
        });
    })();
    </script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js" async></script>
    """
    return render_template_string(HEADER_HTML + admin_html + FOOTER_HTML, **locals())
    
"""
<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 text-left">
    <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm">
        <p class="text-[9px] text-gray-400 font-black uppercase mb-1">Total Sales</p>
        <p class="text-xl font-black text-teal-600">{{ "{:,}".format(stats.sales) }}원</p>
    </div>
    <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm">
        <p class="text-[9px] text-gray-400 font-black uppercase mb-1">Orders</p>
        <p class="text-xl font-black text-gray-800">{{ stats.count }}건</p>
    </div>
    <div class="bg-white p-6 rounded-[2rem] border border-gray-100 shadow-sm">
        <p class="text-[9px] text-gray-400 font-black uppercase mb-1">Delivery Fees</p>
        <p class="text-xl font-black text-orange-500">{{ "{:,}".format(stats.delivery) }}원</p>
    </div>
    <div class="bg-gray-800 p-6 rounded-[2rem] shadow-xl">
        <p class="text-[9px] text-gray-400 font-black uppercase mb-1 text-white/50">Grand Total</p>
        <p class="text-xl font-black text-white">{{ "{:,}".format(stats.grand_total) }}원</p>
    </div>
</div>
    <div class="max-w-7xl mx-auto py-12 px-4 md:px-6 font-black text-xs md:text-sm text-left">
        <div class="flex justify-between items-center mb-10 text-left">
            <h2 class="text-2xl md:text-3xl font-black text-orange-700 italic text-left">Admin Panel</h2>
            <div class="flex gap-4 text-left"><a href="/logout" class="absolute top-6 right-6 z-[9999] text-[12px] md:text-[10px] bg-gray-100 px-6 py-3 md:px-5 md:py-2 rounded-full text-gray-500 font-black hover:bg-red-50 hover:text-red-500 transition-all shadow-md border border-gray-200 text-center">LOGOUT</a></div>
        </div>
        
        <div class="flex border-b border-gray-100 mb-12 bg-white rounded-t-3xl overflow-x-auto text-left">
            <a href="/admin?tab=products" class="px-8 py-5 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품 관리</a>
            <a href="/admin?tab=orders" class="px-8 py-5 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문 및 배송 집계</a>
            <a href="/admin?tab=settlement" class="px-8 py-5 {% if tab == 'settlement' %}border-b-4 border-orange-500 text-orange-600{% endif %}">정산관리</a>
            {% if is_master %}<a href="/admin?tab=categories" class="px-8 py-5 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리/판매자 설정</a>{% endif %}
            <a href="/admin?tab=reviews" class="px-8 py-5 {% if tab == 'reviews' %}border-b-4 border-orange-500 text-orange-600{% endif %}">리뷰 관리</a>
            {% if is_master %}<a href="/admin?tab=sellers" class="px-8 py-5 {% if tab == 'sellers' %}border-b-4 border-orange-500 text-orange-600{% endif %}">판매자 관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=delivery_zone" class="px-8 py-5 {% if tab == 'delivery_zone' %}border-b-4 border-orange-500 text-orange-600{% endif %}">배송구역관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=member_grade" class="px-8 py-5 {% if tab == 'member_grade' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원 등급</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=point_manage" class="px-8 py-5 {% if tab == 'point_manage' %}border-b-4 border-orange-500 text-orange-600{% endif %}">포인트 관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=members" class="px-8 py-5 {% if tab == 'members' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원관리</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=messages" class="px-8 py-5 {% if tab == 'messages' %}border-b-4 border-orange-500 text-orange-600{% endif %}">메시지 발송</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=popup" class="px-8 py-5 {% if tab == 'popup' %}border-b-4 border-orange-500 text-orange-600{% endif %}">알림팝업</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=restaurant_request" class="px-8 py-5 {% if tab == 'restaurant_request' %}border-b-4 border-orange-500 text-orange-600{% endif %}">전국맛집요청</a>{% endif %}
            {% if is_master %}<a href="/admin?tab=partnership" class="px-8 py-5 {% if tab == 'partnership' %}border-b-4 border-orange-500 text-orange-600{% endif %}">제휴문의</a>{% endif %}
        </div>

        {% if tab == 'products' %}
            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-sm mb-12">
    <form action="/admin" method="GET" class="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
        <input type="hidden" name="tab" value="orders">
        
        <div class="space-y-2">
            <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest ml-2">시작 일시</label>
            <input type="datetime-local" name="start_date" value="{{ start_date_str.replace(' ', 'T') }}" 
                   class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs focus:ring-2 focus:ring-teal-500 transition">
        </div>

        <div class="space-y-2">
            <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest ml-2">종료 일시</label>
            <input type="datetime-local" name="end_date" value="{{ end_date_str.replace(' ', 'T') }}" 
                   class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs focus:ring-2 focus:ring-teal-500 transition">
        </div>

        <div class="space-y-2">
            <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest ml-2">카테고리</label>
            <select name="order_cat" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white focus:ring-2 focus:ring-teal-500 transition">
                <option value="전체">모든 품목 합산</option>
                {% for c in selectable_categories %}
                <option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>
                {% endfor %}
            </select>
        </div>

        <button type="submit" class="bg-teal-600 text-white py-4 rounded-2xl font-black shadow-lg shadow-teal-100 hover:bg-teal-700 transition active:scale-95 text-xs">
            <i class="fas fa-search mr-2"></i> 기간 조회하기
        </button>
    </form>
</div>
                <div class="flex gap-3 text-left">
                    <button onclick="document.getElementById('excel_upload_form').classList.toggle('hidden')" class="bg-blue-600 text-white px-6 py-3 rounded-2xl font-black text-xs shadow-lg hover:bg-blue-700 transition">📦 엑셀 대량 등록</button>
                    <a href="/admin/add" class="bg-teal-600 text-white px-6 py-3 rounded-2xl font-black text-xs shadow-lg hover:bg-teal-700 transition">+ 개별 상품 등록</a>
                </div>
            </div>
            
            <div class="bg-white rounded-[2rem] shadow-sm border border-gray-50 overflow-hidden text-left">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 border-b border-gray-100 text-gray-400 uppercase text-[10px] md:text-xs">
                        <tr><th class="p-6">상품 기본 정보</th><th class="p-6 text-center">재고</th><th class="p-6 text-center">관리</th></tr>
                    </thead>
                    <tbody class="text-left">
                        {% for p in products %}
                        <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition">
                            <td class="p-6 text-left">
                                <b class="text-gray-800 text-sm md:text-base">{{ p.name }}</b> <span class="text-orange-500 text-[9px] md:text-[10px] font-black ml-2">{{ p.badge }}</span><br>
                                <span class="text-teal-600 font-bold text-[10px] md:text-xs">{{ p.description or '설명 없음' }}</span><br>
                                <span class="text-gray-400 text-[10px] md:text-xs">{{ "{:,}".format(p.price) }}원 / {{ p.spec or '일반' }}</span>
                            </td>
                            <td class="p-6 text-center font-black text-gray-500">{{ p.stock }}개</td>
                            <td class="p-6 text-center space-x-3 text-[10px] md:text-xs text-center">
                                <a href="/admin/edit/{{p.id}}" class="text-blue-500 hover:underline">수정</a>
                                <a href="/admin/delete/{{p.id}}" class="text-red-300 hover:text-red-500 transition" onclick="return confirm('이 상품을 영구 삭제하시겠습니까?')">삭제</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

        {% elif tab == 'categories' %}
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-10 text-left">
                <div class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] border border-gray-50 shadow-sm h-fit text-left">
                    <h3 class="text-[11px] md:text-sm text-gray-400 uppercase tracking-widest mb-10 font-black text-left">판매 카테고리 및 사업자 추가</h3>
                    <form action="/admin/category/add" method="POST" class="space-y-5 text-left">
                        <input name="cat_name" placeholder="카테고리명 (예: 산지직송 농산물)" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm text-left" required>
                        <textarea name="description" placeholder="배송기한 정보 등 설명" class="border border-gray-100 p-5 rounded-2xl w-full h-24 font-black text-sm text-left"></textarea>
                        <input name="manager_email" placeholder="관리 매니저 이메일 (ID)" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm text-left">
                        <select name="tax_type" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm text-left bg-white"><option value="과세">일반 과세 상품</option><option value="면세">면세 농축산물</option></select>
                        <p class="text-[10px] text-amber-600 font-bold uppercase mt-2 text-left">노출 회원등급 (몇 등급 이상)</p>
                        <select name="min_member_grade" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left bg-white"><option value="">전체 회원</option><option value="1">1단계 이상</option><option value="2">2단계 이상</option><option value="3">3단계 이상</option><option value="4">4단계 이상</option><option value="5">5단계만</option></select>
                        <div class="border-t border-gray-100 pt-8 space-y-4 text-left">
                            <p class="text-[10px] text-teal-600 font-bold tracking-widest uppercase text-left">Seller Business Profile</p>
                            <input name="biz_name" placeholder="사업자 상호명" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_representative" placeholder="대표자 성함" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_reg_number" placeholder="사업자 등록번호 ( - 포함 )" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_address" placeholder="사업장 소재지" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_contact" placeholder="고객 센터 번호" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="seller_link" placeholder="판매자 문의 (카카오/채팅) 링크" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <p class="text-[10px] text-blue-600 font-bold tracking-widest uppercase pt-2 text-left">정산 계좌</p>
                            <input name="bank_name" placeholder="은행명" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="account_holder" placeholder="예금주" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="settlement_account" placeholder="정산계좌 (계좌번호)" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                        </div>
                        <button class="w-full bg-teal-600 text-white py-5 rounded-3xl font-black text-base md:text-lg shadow-xl hover:bg-teal-700 transition text-center">신규 카테고리 생성</button>
                    </form>
                </div>
                
                <div class="bg-white rounded-[2.5rem] md:rounded-[3.5rem] border border-gray-50 shadow-sm overflow-hidden text-left">
                    <table class="w-full text-left">
                        <thead class="bg-gray-50 border-b border-gray-100 font-bold uppercase text-[10px] md:text-xs">
                            <tr><th class="p-6">전시 순서</th><th class="p-6">카테고리명</th><th class="p-6 text-center">관리</th></tr>
                        </thead>
                        <tbody class="text-left">
                            {% for c in categories %}
                            <tr class="border-b border-gray-50 text-left hover:bg-gray-50/50 transition">
                                <td class="p-6 flex gap-4 text-left">
                                    <a href="/admin/category/move/{{c.id}}/up" class="text-blue-500 p-2"><i class="fas fa-chevron-up"></i></a>
                                    <a href="/admin/category/move/{{c.id}}/down" class="text-red-500 p-2"><i class="fas fa-chevron-down"></i></a>
                                </td>
                                <td class="p-6 text-left"><b class="text-gray-800">{{ c.name }}</b><br><span class="text-gray-400 text-[10px]">매니저: {{ c.manager_email or '미지정' }}</span></td>
                                <td class="p-6 text-center space-x-3 text-[10px] text-center">
                                    <a href="/admin/category/edit/{{c.id}}" class="text-blue-500 hover:underline">수정</a>
                                    <a href="/admin/category/delete/{{c.id}}" class="text-red-200 hover:text-red-500 transition" onclick="return confirm('삭제하시겠습니까?')">삭제</a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        {% elif tab == 'sellers' %}
            <div class="mb-12 text-left">
                <div class="flex flex-wrap items-center justify-between gap-4 mb-6 text-left">
                    <div>
                        <h3 class="text-lg font-black text-gray-800 italic">Seller Business Profile (판매자 정보)</h3>
                        <p class="text-[11px] text-gray-500 font-bold mt-1">엑셀 형식으로 정렬된 판매자별 사업자·정산 정보</p>
                    </div>
                    <a href="/admin/sellers/excel" class="bg-teal-600 text-white px-5 py-2.5 rounded-xl font-black text-xs shadow hover:bg-teal-700">엑셀 다운로드</a>
                </div>
                <div class="flex gap-2 mb-4">
                    <a href="/admin?tab=sellers&seller_tax=전체" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '전체' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">전체</a>
                    <a href="/admin?tab=sellers&seller_tax=과세" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '과세' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">과세</a>
                    <a href="/admin?tab=sellers&seller_tax=면세" class="px-4 py-2 rounded-xl text-[11px] font-black {% if seller_tax == '면세' %}bg-teal-600 text-white{% else %}bg-gray-100 text-gray-600 hover:bg-gray-200{% endif %}">면세</a>
                </div>
                <div class="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-x-auto text-left">
                    <table class="w-full text-left min-w-[1000px] text-[11px] font-bold border-collapse">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 border border-gray-600 w-12 text-center">순서</th>
                                <th class="p-3 border border-gray-600 w-16 text-center">과세/면세</th>
                                <th class="p-3 border border-gray-600">카테고리</th>
                                <th class="p-3 border border-gray-600">상호</th>
                                <th class="p-3 border border-gray-600">대표자</th>
                                <th class="p-3 border border-gray-600">사업자등록번호</th>
                                <th class="p-3 border border-gray-600">소재지</th>
                                <th class="p-3 border border-gray-600">고객센터</th>
                                <th class="p-3 border border-gray-600">문의링크</th>
                                <th class="p-3 border border-gray-600">은행명</th>
                                <th class="p-3 border border-gray-600">예금주</th>
                                <th class="p-3 border border-gray-600">정산계좌</th>
                                <th class="p-3 border border-gray-600">매니저이메일</th>
                                <th class="p-3 border border-gray-600 w-20 text-center">관리</th>
                            </tr>
                        </thead>
                        <tbody class="text-left">
                            {% for c in sellers_categories %}
                            <tr class="border-b border-gray-100 hover:bg-gray-50/50 text-left">
                                <td class="p-3 border border-gray-100 text-center text-gray-500">{{ loop.index }}</td>
                                <td class="p-3 border border-gray-100 text-center"><span class="{% if (c.tax_type or '과세') == '면세' %}text-amber-600{% else %}text-teal-600{% endif %} font-black text-[10px]">{{ c.tax_type or '과세' }}</span></td>
                                <td class="p-3 border border-gray-100 font-black text-teal-700">{{ c.name }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_name or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_representative or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_reg_number or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_address or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.biz_contact or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-teal-600 truncate max-w-[120px]" title="{{ c.seller_inquiry_link or '' }}">{% if c.seller_inquiry_link %}{{ c.seller_inquiry_link[:30] }}{% if c.seller_inquiry_link|length > 30 %}...{% endif %}{% else %}-{% endif %}</td>
                                <td class="p-3 border border-gray-100">{{ c.bank_name or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.account_holder or '-' }}</td>
                                <td class="p-3 border border-gray-100">{{ c.settlement_account or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-gray-500">{{ c.manager_email or '-' }}</td>
                                <td class="p-3 border border-gray-100 text-center"><a href="/admin/category/edit/{{ c.id }}" class="text-blue-600 font-black hover:underline text-[10px]">수정</a></td>
                            </tr>
                            {% else %}
                            <tr><td colspan="14" class="p-8 text-center text-gray-400 font-bold">등록된 카테고리가 없습니다. 카테고리 설정에서 추가해 주세요.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        {% elif tab == 'settlement' %}
            <div class="bg-white p-8 rounded-[2.5rem] border border-gray-100 shadow-sm mb-12">
                <div class="flex gap-2 mb-6">
                    <button type="button" onclick="setDateRange('today')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">오늘</button>
                    <button type="button" onclick="setDateRange('7days')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">최근 7일</button>
                    <button type="button" onclick="setDateRange('month')" class="px-4 py-2 bg-gray-100 rounded-xl text-[10px] font-black hover:bg-teal-100 transition">이번 달</button>
                </div>
                <form action="/admin" method="GET" id="date-filter-form" class="grid grid-cols-1 md:grid-cols-4 gap-6 items-end">
                    <input type="hidden" name="tab" value="settlement">
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">시작 일시</label><input type="datetime-local" name="start_date" id="start_date" value="{{ start_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">종료 일시</label><input type="datetime-local" name="end_date" id="end_date" value="{{ end_date_str.replace(' ', 'T') }}" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs"></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">카테고리 필터</label><select name="order_cat" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체">모든 품목 합산</option>{% for c in selectable_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></div>
                    <div><label class="text-[10px] text-gray-400 font-black ml-2">입금상태</label><select name="settlement_status" class="w-full border-none bg-gray-50 p-4 rounded-2xl font-black text-xs bg-white"><option value="전체" {% if sel_settlement_status == '전체' %}selected{% endif %}>전체</option><option value="입금대기" {% if sel_settlement_status == '입금대기' %}selected{% endif %}>입금대기</option><option value="입금완료" {% if sel_settlement_status == '입금완료' %}selected{% endif %}>입금완료</option><option value="취소" {% if sel_settlement_status == '취소' %}selected{% endif %}>취소</option><option value="보류" {% if sel_settlement_status == '보류' %}selected{% endif %}>보류</option></select></div>
                    <button type="submit" class="bg-teal-600 text-white py-4 rounded-2xl font-black shadow-lg">조회하기</button>
                </form>
            </div>
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 mb-4 italic">📊 정산 상세 (n넘버 기준)</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">고객 결제 시 품목별 고유 n넘버가 부여되며, 해당 번호를 기준으로 정산합니다.</p>
                <div class="flex items-center gap-4 mb-4 flex-wrap">
                    <span class="text-[11px] font-bold text-gray-600">선택 항목 입금상태 변경:</span>
                    <select id="settlement-bulk-status-2" class="border border-gray-200 rounded-xl px-3 py-2 text-xs font-black bg-white">
                        <option value="입금대기">입금대기</option>
                        <option value="입금완료">입금완료</option>
                        <option value="취소">취소</option>
                        <option value="보류">보류</option>
                    </select>
                    <button type="button" id="settlement-bulk-status-btn-2" class="bg-teal-600 text-white px-5 py-2 rounded-xl text-xs font-black shadow">적용</button>
                </div>
                <div id="settlement-detail-table-wrap-2" class="bg-white rounded-[2rem] border border-gray-100 shadow-sm overflow-x-auto">
                    <table class="w-full text-left min-w-[900px] text-[10px] font-black">
                        <thead class="bg-gray-800 text-white">
                            <tr>
                                <th class="p-3 w-12"><input type="checkbox" id="selectAllSettlement2" title="전체선택" class="rounded"></th>
                                <th class="p-3">정산번호(n)</th>
                                <th class="p-3">판매일시</th>
                                <th class="p-3">카테고리</th>
                                <th class="p-3 text-center">면세여부</th>
                                <th class="p-3">품목</th>
                                <th class="p-3 text-right">판매금액</th>
                                <th class="p-3 text-right">수수료</th>
                                <th class="p-3 text-right">배송관리비</th>
                                <th class="p-3 text-right">정산합계</th>
                                <th class="p-3 text-center">입금상태(입금일)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for r in settlement_detail_rows %}
                            <tr class="border-b border-gray-50 hover:bg-teal-50/20">
                                <td class="p-3"><input type="checkbox" class="settlement-row-checkbox-2 rounded" value="{{ r.order_item_id }}" data-order-item-id="{{ r.order_item_id }}"></td>
                                <td class="p-3 font-mono text-gray-700">{{ r.settlement_no or '-' }}</td>
                                <td class="p-3 text-gray-700">{{ r.sale_dt }}</td>
                                <td class="p-3 text-gray-600">{{ r.category }}</td>
                                <td class="p-3 text-center text-[9px]">{{ r.tax_exempt }}</td>
                                <td class="p-3 text-gray-800">{{ r.product_name }}</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.sales_amount) }}원</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.fee) }}원</td>
                                <td class="p-3 text-right">{{ "{:,}".format(r.delivery_fee) }}원</td>
                                <td class="p-3 text-right font-black text-blue-600">{{ "{:,}".format(r.settlement_total) }}원</td>
                                <td class="p-3 text-center align-top"><span class="{% if r.settlement_status == '입금완료' %}bg-green-100 text-green-700{% else %}bg-orange-100 text-orange-600{% endif %} px-2 py-1 rounded-full text-[9px]">{{ r.settlement_status }}</span>{% if r.settled_at %}<div class="text-[8px] text-gray-500 mt-1">{{ r.settled_at }}</div>{% endif %}</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="11" class="p-10 text-center text-gray-400 font-bold text-sm">해당 기간 정산 내역이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="mt-6 p-6 bg-gray-50 rounded-2xl border border-gray-200">
                    <h4 class="text-sm font-black text-gray-700 mb-4">📌 카테고리별 총합계금액</h4>
                    <ul class="space-y-2 text-[11px] font-black">
                        {% for cat_name, total_amt in settlement_category_totals.items() %}
                        <li class="flex justify-between"><span class="text-gray-600">{{ cat_name }}</span><span class="text-teal-600">{{ "{:,}".format(total_amt) }}원</span></li>
                        {% endfor %}
                        <li class="flex justify-between pt-3 border-t-2 border-gray-300 mt-3"><span class="text-gray-800">총합계</span><span class="text-blue-600 font-black">{{ "{:,}".format(settlement_category_totals.values() | sum) }}원</span></li>
                    </ul>
                </div>
            </div>
            <div class="mb-12">
                <h3 class="text-lg font-black text-gray-800 mb-6 italic">📋 오더별 정산 현황</h3>
                <p class="text-[11px] text-gray-500 font-bold mb-4">관리 중인 카테고리 품목만 표시됩니다.</p>
                <div class="bg-white rounded-[2rem] border border-gray-100 shadow-sm overflow-x-auto">
                    <table class="w-full text-left min-w-[800px]">
                        <thead class="bg-gray-50 border-b border-gray-100 text-[10px] text-gray-400 font-black">
                            <tr>
                                <th class="p-5">오더넘버</th>
                                <th class="p-5">판매일</th>
                                <th class="p-5">품목</th>
                                <th class="p-5 text-center">수량</th>
                                <th class="p-5 text-center">배송현황</th>
                                <th class="p-5 text-right">가격(정산대상)</th>
                                <th class="p-5 text-right">합계금액</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for o in filtered_orders %}
                            <tr class="border-b border-gray-50 hover:bg-teal-50/20">
                                <td class="p-5 font-mono text-[11px] text-gray-700">{{ o.order_id[-12:] if o.order_id else '-' }}</td>
                                <td class="p-5 text-gray-700 font-bold">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                                <td class="p-5 text-gray-700 text-[11px] leading-relaxed">{{ (o._manager_items | default([])) | join(', ') }}</td>
                                <td class="p-5 text-center font-black">{{ o._manager_qty | default(0) }}</td>
                                <td class="p-5 text-center"><span class="{% if o.status == '결제취소' %}text-red-500{% else %}text-teal-600{% endif %} font-bold text-[11px]">{{ o.status }}</span></td>
                                <td class="p-5 text-right font-black text-blue-600">{{ "{:,}".format(o._manager_subtotal | default(0)) }}원</td>
                                <td class="p-5 text-right font-black text-gray-800">{{ "{:,}".format(o._manager_subtotal | default(0)) }}원</td>
                            </tr>
                            {% else %}
                            <tr><td colspan="7" class="p-10 text-center text-gray-400 font-bold text-sm">해당 기간 주문이 없습니다.</td></tr>
                            {% endfor %}
                        </tbody>
                        <tfoot class="bg-gray-100 border-t-2 border-gray-200">
                            <tr>
                                <td class="p-5 font-black text-gray-500 text-[11px]" colspan="3">총합계</td>
                                <td class="p-5 text-center font-black text-gray-800">{{ order_total_qty }}</td>
                                <td class="p-5"></td>
                                <td class="p-5 text-right font-black text-blue-600">{{ "{:,}".format(order_total_subtotal) }}원</td>
                                <td class="p-5 text-right font-black text-gray-800">{{ "{:,}".format(order_total_subtotal) }}원</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            </div>
            <script>
            function setDateRange(range) {
                const startInput = document.getElementById('start_date');
                const endInput = document.getElementById('end_date');
                if (!startInput || !endInput) return;
                const now = new Date();
                let start = new Date();
                let end = new Date();
                if (range === 'today') { start.setHours(0,0,0,0); end.setHours(23,59,59,999); }
                else if (range === '7days') { start.setDate(now.getDate()-7); start.setHours(0,0,0,0); }
                else if (range === 'month') { start.setDate(1); start.setHours(0,0,0,0); }
                const format = (d) => new Date(d.getTime() - (d.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
                startInput.value = format(start);
                endInput.value = format(end);
                document.getElementById('date-filter-form').submit();
            }
            document.getElementById('selectAllSettlement2')?.addEventListener('change', function() {
                document.querySelectorAll('.settlement-row-checkbox-2').forEach(cb => cb.checked = this.checked);
            });
            document.getElementById('settlement-bulk-status-btn-2')?.addEventListener('click', async function() {
                const ids = Array.from(document.querySelectorAll('.settlement-row-checkbox-2:checked')).map(cb => cb.value).filter(Boolean);
                if (!ids.length) { alert('선택한 항목이 없습니다.'); return; }
                const status = document.getElementById('settlement-bulk-status-2')?.value;
                if (!status) return;
                try {
                    const r = await fetch('/admin/settlement/bulk_item_status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_item_ids: ids, settlement_status: status }), credentials: 'same-origin' });
                    const j = await r.json();
                    if (j.success) { alert(j.message); document.getElementById('date-filter-form')?.submit(); } else { alert(j.message || '변경 실패'); }
                } catch (e) { alert('요청 실패'); }
            });
            </script>

        {% elif tab == 'reviews' %}
            <div class="bg-white rounded-[2.5rem] shadow-xl border border-gray-50 overflow-hidden">
                <table class="w-full text-[10px] md:text-xs font-black text-left">
                    <thead class="bg-gray-800 text-white">
                        <tr><th class="p-6">판매자(카테고리)</th><th class="p-6">상품/작성자</th><th class="p-6">내용</th><th class="p-6 text-center">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for r in reviews %}
                        <tr class="border-b border-gray-100 hover:bg-red-50/30">
                            <td class="p-6 text-gray-500 font-bold">{{ category_names.get(r.category_id, '-') }}</td>
                            <td class="p-6"><span class="text-teal-600">[{{ r.product_name }}]</span><br>{{ r.user_name }}</td>
                            <td class="p-6">{{ r.content }}</td>
                            <td class="p-6 text-center"><a href="/admin/review/delete/{{ r.id }}" class="bg-red-500 text-white px-4 py-2 rounded-full" onclick="return confirm('삭제하시겠습니까?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% endif %}
    </div>""" 

# --------------------------------------------------------------------------------
# 7. 엑셀 대량 업로드 (사용자 커스텀 양식 대응)
# --------------------------------------------------------------------------------
@app.route('/admin/product/bulk_upload_template')
@login_required
def admin_product_bulk_upload_template():
    """상품 엑셀 업로드용 양식 파일 다운로드 (필수 컬럼: 카테고리, 상품명, 규격, 가격, 이미지파일명)"""
    if not current_user.is_admin:
        return redirect('/')
    df = pd.DataFrame(columns=['카테고리', '상품명', '규격', '가격', '이미지파일명'])
    df.loc[0] = ['(카테고리명)', '(상품명)', '(예: 1박스)', 0, '(파일명.jpg)']
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    out.seek(0)
    return send_file(out, download_name='상품_엑셀_업로드_양식.xlsx', as_attachment=True)


@app.route('/admin/product/bulk_upload', methods=['POST'])
@login_required
def admin_product_bulk_upload():
    """사용자 엑셀 양식(한글 헤더) 기반 대량 업로드 로직"""
    if not current_user.is_admin: return redirect('/')
    file = request.files.get('excel_file')
    if not file: return redirect('/admin')
    try:
        df = pd.read_excel(file)
        # 사용자 요청 헤더: 카테고리, 상품명, 규격, 가격, 이미지파일명
        required_cols = ['카테고리', '상품명', '규격', '가격', '이미지파일명']
        if not all(col in df.columns for col in required_cols): 
            flash("엑셀 헤더 불일치 (필요: 카테고리, 상품명, 규격, 가격, 이미지파일명)"); return redirect('/admin')
        
        count = 0
        for _, row in df.iterrows():
            cat_name = str(row['카테고리']).strip()
            cat_exists = Category.query.filter_by(name=cat_name).first()
            if not cat_exists: continue
            
            # 이미지 경로 매핑 및 상세사진 자동 설정
            raw_img_name = str(row['이미지파일명']).strip()
            img_url = f"/static/uploads/{raw_img_name}" if raw_img_name != 'nan' else ""
            
            new_p = Product(
                category=cat_name, 
                name=str(row['상품명']), 
                price=int(row['가격']), 
                spec=str(row['규격']), 
                origin="국산", 
                farmer="바구니삼촌", 
                stock=50, # 기본 재고 50개 설정
                image_url=img_url, 
                detail_image_url=img_url, # 메인과 상세 동일하게 복사
                is_active=True, 
                tax_type=cat_exists.tax_type
            )
            db.session.add(new_p); count += 1
            
        db.session.commit()
        flash(f"{count}개의 상품이 성공적으로 등록되었습니다."); return redirect('/admin')
    except Exception as e: 
        db.session.rollback()
        flash(f"업로드 실패: {str(e)}"); return redirect('/admin')
        db.session.commit()
        flash(f"{count}개의 상품이 성공적으로 등록되었습니다."); return redirect('/admin')
    except Exception as e: 
        db.session.rollback()
        flash(f"업로드 실패: {str(e)}"); return redirect('/admin')

@app.route('/admin/board/restaurant-request/<int:rid>/hide', methods=['POST'])
@login_required
def admin_restaurant_request_hide(rid):
    if not current_user.is_admin:
        return redirect('/')
    r = RestaurantRequest.query.get_or_404(rid)
    r.is_hidden = not r.is_hidden
    db.session.commit()
    flash("숨김 상태가 변경되었습니다." if r.is_hidden else "다시 노출됩니다.")
    return redirect('/admin?tab=restaurant_request')


@app.route('/admin/board/partnership/<int:pid>/hide', methods=['POST'])
@login_required
def admin_partnership_hide(pid):
    if not current_user.is_admin:
        return redirect('/')
    p = PartnershipInquiry.query.get_or_404(pid)
    p.is_hidden = not p.is_hidden
    db.session.commit()
    flash("숨김 상태가 변경되었습니다." if p.is_hidden else "다시 노출됩니다.")
    return redirect('/admin?tab=partnership')


@app.route('/admin/review/delete/<int:rid>')
@login_required
def admin_review_delete(rid):
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        return redirect('/')
    r = Review.query.get_or_404(rid)
    db.session.delete(r)
    db.session.commit()
    flash("리뷰가 삭제되었습니다.")
    return redirect('/admin?tab=reviews')

# --------------------------------------------------------------------------------
# 7-2. 테스트 카테고리 3개 + 가상 상품 10개씩 시드 (전 기능 테스트용)
# --------------------------------------------------------------------------------
def _seed_test_categories_and_products():
    """테스트 카테고리 3개와 카테고리당 가상 상품 10개 생성. 등록 기능 전 필드 활용."""
    now = datetime.now()
    today_evening = now.replace(hour=20, minute=0, second=0, microsecond=0)
    tomorrow = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    categories_data = [
        {"name": "테스트-채소", "description": "테스트용 채소 카테고리 (상품 등록·수정·배지·마감 테스트)", "order": 900},
        {"name": "테스트-과일", "description": "테스트용 과일 카테고리", "order": 901},
        {"name": "테스트-수산", "description": "테스트용 수산 카테고리", "order": 902},
    ]
    for cdata in categories_data:
        if not Category.query.filter_by(name=cdata["name"]).first():
            db.session.add(Category(name=cdata["name"], description=cdata["description"], order=cdata["order"], tax_type="과세"))
    db.session.commit()

    products_data = []
    # 테스트-채소 10종: description(당일/+1/+2), badge(오늘마감/삼촌추천/없음), deadline(오늘/내일/없음), stock 다양
    veg_names = ["청경채 1단", "상추 2종 모둠", "깻잎 1단", "시금치 1단", "브로콜리 1송이", "당근 1kg", "양파 2kg", "대파 3대", "쪽파 1단", "미나리 1단"]
    for i, name in enumerate(veg_names):
        products_data.append({
            "category": "테스트-채소", "name": name, "description": ["당일배송", "+1일", "+2일", "+3일"][i % 4],
            "price": [3500, 4500, 2800, 3200, 2200, 4000, 3500, 1500, 1800, 2500][i],
            "spec": ["1단", "1팩", "1단", "1단", "1송이", "1kg", "2kg", "3대", "1단", "1단"][i],
            "origin": "국산", "farmer": "바구니삼촌", "stock": [5, 10, 20, 15, 30, 50, 40, 99, 10, 8][i],
            "deadline": today_evening if i % 3 == 0 else (tomorrow if i % 3 == 1 else None),
            "badge": ["오늘마감", "삼촌추천", ""][i % 3], "image_url": f"https://placehold.co/400x400/dcfce7/166534?text=V{i+1}",
            "detail_image_url": f"https://placehold.co/600x400/bbf7d0/166534?text={name[:4]}",
        })
    # 테스트-과일 10종
    fruit_names = ["사과 2kg", "배 1.5kg", "포도 1kg", "귤 2kg", "수박 1통", "참외 2kg", "복숭아 1kg", "블루베리 125g", "딸기 500g", "바나나 1kg"]
    for i, name in enumerate(fruit_names):
        products_data.append({
            "category": "테스트-과일", "name": name, "description": ["+1일", "+2일", "당일배송", "+3일"][i % 4],
            "price": [12000, 15000, 8000, 9000, 18000, 14000, 11000, 6500, 12000, 4500][i],
            "spec": ["2kg", "1.5kg", "1kg", "2kg", "1통", "2kg", "1kg", "125g", "500g", "1kg"][i],
            "origin": "국산", "farmer": "바구니삼촌", "stock": [20, 15, 30, 40, 10, 25, 18, 50, 12, 60][i],
            "deadline": tomorrow if i % 2 == 0 else None, "badge": ["삼촌추천", "", "오늘마감"][i % 3],
            "image_url": f"https://placehold.co/400x400/fef3c7/d97706?text=F{i+1}",
            "detail_image_url": f"https://placehold.co/600x400/fde68a/d97706?text={name[:4]}",
        })
    # 테스트-수산 10종
    fish_names = ["고등어 2마리", "갈치 1kg", "동태 1마리", "새우 300g", "오징어 1마리", "문어 1마리", "연어 200g", "참치캔 3캔", "멸치 100g", "김 10장"]
    for i, name in enumerate(fish_names):
        products_data.append({
            "category": "테스트-수산", "name": name, "description": ["+1일", "+2일", "+3일", "당일배송"][i % 4],
            "price": [8000, 12000, 6500, 15000, 9000, 18000, 7000, 4500, 3500, 4000][i],
            "spec": ["2마리", "1kg", "1마리", "300g", "1마리", "1마리", "200g", "3캔", "100g", "10장"][i],
            "origin": "국산/수입", "farmer": "바구니삼촌", "stock": [10, 8, 25, 15, 12, 5, 30, 50, 40, 20][i],
            "deadline": today_evening if i % 4 == 0 else (tomorrow if i % 4 == 1 else None),
            "badge": ["", "오늘마감", "삼촌추천", ""][i % 4],
            "image_url": f"https://placehold.co/400x400/dbeafe/1d4ed8?text=S{i+1}",
            "detail_image_url": f"https://placehold.co/600x400/bfdbfe/1d4ed8?text={name[:4]}",
        })

    created = 0
    for pdata in products_data:
        exists = Product.query.filter_by(category=pdata["category"], name=pdata["name"]).first()
        if not exists:
            p = Product(
                category=pdata["category"], name=pdata["name"], description=pdata["description"],
                price=pdata["price"], spec=pdata["spec"], origin=pdata["origin"], farmer=pdata["farmer"],
                stock=pdata["stock"], deadline=pdata["deadline"], badge=pdata.get("badge", ""),
                image_url=pdata["image_url"], detail_image_url=pdata.get("detail_image_url", pdata["image_url"]),
                is_active=True, tax_type="과세"
            )
            db.session.add(p)
            created += 1
    db.session.commit()
    return created


def _seed_virtual_reviews_per_product(count_per_product=10):
    """상품별 가상 구매 후기 count_per_product개씩 생성. order_id는 가상 고유값(음수) 사용."""
    reviews_content = [
        "맛있고 신선해요. 다음에도 주문할게요!",
        "배송 빨라서 좋았어요. 품질도 만족합니다.",
        "생각보다 양 많고 가성비 좋아요.",
        "친구 추천으로 처음 주문했는데 대만족입니다.",
        "포장 꼼꼼하고 상태 좋았어요. 추천합니다.",
        "맛이 좋아서 자주 시켜먹을 것 같아요.",
        "당일 받아서 너무 만족스러워요.",
        "가격 대비 퀄리티 좋습니다. 감사해요.",
        "신선하고 맛있어요. 재주문 의사 있습니다.",
        "서비스도 좋고 상품도 만족합니다. 감사합니다.",
    ]
    user_names = ["김**", "이**", "박**", "최**", "정**", "강**", "조**", "윤**", "장**", "한**"]
    products = Product.query.filter_by(is_active=True).all()
    cat_ids = {}
    created = 0
    for p in products:
        if p.category and p.category not in cat_ids:
            c = Category.query.filter_by(name=p.category).first()
            cat_ids[p.category] = c.id if c else None
        category_id = cat_ids.get(p.category)
        existing = Review.query.filter_by(product_id=p.id).count()
        to_add = max(0, count_per_product - existing)
        for j in range(to_add):
            # 가상 order_id: 음수로 실주문과 구분, 상품별·순번별 고유 (기존 후기 수 + j)
            virtual_order_id = -(p.id * 1000 + existing + j)
            if Review.query.filter_by(order_id=virtual_order_id).first():
                continue
            content = reviews_content[j % len(reviews_content)]
            uname = user_names[j % len(user_names)]
            img = f"https://placehold.co/400x400/e0f2fe/1e40af?text=후기"
            r = Review(
                order_id=virtual_order_id,
                user_id=0,
                user_name=uname,
                product_id=p.id,
                product_name=p.name[:100] if p.name else "",
                category_id=category_id,
                content=content,
                image_url=img,
            )
            db.session.add(r)
            created += 1
    if created:
        db.session.commit()
    return created


@app.route('/admin/seed_test_data')
@login_required
def admin_seed_test_data():
    """테스트 카테고리 3개 + 가상 상품 10개씩 생성 (관리자 전용)."""
    if not current_user.is_admin:
        return redirect('/')
    created = _seed_test_categories_and_products()
    flash(f"테스트 데이터 생성 완료. 새로 등록된 상품 {created}건 (카테고리·기존 상품은 중복 생성 안 함).")
    return redirect('/admin')


@app.route('/admin/seed_virtual_reviews')
@login_required
def admin_seed_virtual_reviews():
    """상품별 가상 구매 후기 10개씩 생성 (관리자 전용)."""
    if not current_user.is_admin:
        return redirect('/')
    created = _seed_virtual_reviews_per_product(10)
    flash(f"가상 구매 후기 생성 완료. 새로 등록된 후기 {created}건 (상품당 10개씩, 기존 후기는 건너뜀).")
    return redirect('/admin?tab=reviews')


# --------------------------------------------------------------------------------
# 8. 개별 상품 등록/수정/삭제 및 카테고리 관리
# --------------------------------------------------------------------------------

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    """개별 상품 등록"""
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    is_master = current_user.is_admin
    selectable_categories = [c for c in categories if is_master or c.name in my_categories]
    if request.method == 'POST':
        cat_name = request.form['category']
        if not check_admin_permission(cat_name): return redirect('/admin')
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_files = request.files.getlist('detail_images')
        detail_img_url_str = ",".join(filter(None, [save_uploaded_file(f) for f in detail_files if f.filename != '']))
        deadline_val = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        rt = request.form.get('reset_time', '').strip()[:5] if request.form.get('reset_time') else None
        rq = request.form.get('reset_to_quantity', '').strip()
        reset_to_q = int(rq) if rq.isdigit() else None
        new_p = Product(name=request.form['name'], description=request.form['description'], category=cat_name, price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer="바구니삼촌", stock=int(request.form['stock']), image_url=main_img or "", detail_image_url=detail_img_url_str, deadline=deadline_val, badge=request.form.get('badge', ''), reset_time=rt or None, reset_to_quantity=reset_to_q)
        db.session.add(new_p); db.session.commit(); return redirect('/admin')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-6 font-black text-left"><h2 class="text-3xl font-black mb-12 border-l-8 border-teal-600 pl-6 uppercase italic text-left">Add Product</h2><p class="text-[11px] text-gray-500 font-bold mb-6 bg-gray-50 p-4 rounded-xl border border-gray-100">각 항목이 <strong>목록·상세 페이지 어디에</strong> 나가는지: 상품명→목록 카드·상세 제목 / Short Intro→상품명 옆 / Detailed Intro→상세 사진 위 / Delivery→목록 배지·상세 배송문구 / 가격·규격→목록·상세 / 재고→잔여 N개 / 마감일→카운트다운·오늘마감 / Main Image→목록·대표사진 / Detail Images→상세 본문 여러 장.</p><form method="POST" enctype="multipart/form-data" class="bg-white p-10 rounded-[3rem] shadow-2xl space-y-7 text-left"><select name="category" class="w-full p-5 bg-gray-50 rounded-2xl font-black outline-none focus:ring-4 focus:ring-teal-50 text-left">{% for c in selectable_categories %}<option value="{{c.name}}">{{c.name}}</option>{% endfor %}</select>
   <input name="name" placeholder="상품 명칭 (예: 꿀부사 사과)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" value="{{ p.name if p else '' }}" required>

<div class="space-y-1">
    <label class="text-[10px] text-orange-500 font-black ml-4 uppercase tracking-widest">Short Intro (상품명 옆 한줄소개)</label>
    <input name="badge" placeholder="예: 아삭하고 달콤한, 산지직송" class="w-full p-5 bg-orange-50 border border-orange-100 rounded-2xl font-black text-left text-sm focus:ring-4 focus:ring-orange-100 outline-none transition" value="{{ p.badge if p else '' }}">
</div>

<div class="space-y-1">
    <label class="text-[10px] text-teal-600 font-black ml-4 uppercase tracking-widest">Detailed Intro (사진 위 노출 문구)</label>
    <input name="origin" placeholder="상세페이지 사진 바로 위에 노출될 문구" class="w-full p-5 bg-teal-50 border border-teal-100 rounded-2xl font-black text-left text-sm focus:ring-4 focus:ring-teal-100 outline-none transition" value="{{ p.origin if p else '' }}">
</div>

<div class="space-y-1">
    <label class="text-[10px] text-blue-600 font-black ml-4 uppercase tracking-widest">Delivery (배송 예정일)</label>
    <select name="description" class="w-full p-5 bg-blue-50 text-blue-700 rounded-2xl font-black text-sm outline-none border-none focus:ring-4 focus:ring-blue-100">
        <option value="+1일" {% if p and p.description == '+1일' %}selected{% endif %}>🚚 주문 완료 후 +1일 배송</option>
        <option value="+2일" {% if p and p.description == '+2일' %}selected{% endif %}>🚚 주문 완료 후 +2일 배송</option>
        <option value="+3일" {% if p and p.description == '+3일' %}selected{% endif %}>🚚 주문 완료 후 +3일 배송</option>
        <option value="당일배송" {% if p and p.description == '당일배송' %}selected{% endif %}>⚡ 송도 지역 당일 배송</option>
    </select>
</div>
<div class="grid grid-cols-2 gap-5 text-left"><input name="price" type="number" placeholder="판매 가격(원)" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" required><input name="spec" placeholder="규격 (예: 5kg/1박스)" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"></div>
<div class="grid grid-cols-2 gap-5 text-left"><input name="stock" type="number" placeholder="한정 수량" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" value="50"><input name="deadline" type="datetime-local" id="add-deadline" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"></div>
<div id="add-reset-time-block" class="grid grid-cols-2 gap-5 text-left">
    <div><label class="text-[10px] text-amber-600 font-black ml-4 block mb-1">재고 초기화 시각 (마감일 없을 때)</label><input name="reset_time" type="time" class="w-full p-5 bg-amber-50 rounded-2xl font-black text-left text-sm border border-amber-100" placeholder="09:00"></div>
    <div><label class="text-[10px] text-amber-600 font-black ml-4 block mb-1">초기화 시 복원 수량</label><input name="reset_to_quantity" type="number" min="0" placeholder="예: 50" class="w-full p-5 bg-amber-50 rounded-2xl font-black text-left text-sm border border-amber-100"></div>
</div>
<script>(function(){ var d=document.getElementById('add-deadline'); var b=document.getElementById('add-reset-time-block'); if(d&&b){ function t(){ b.classList.toggle('hidden', !!d.value); } d.addEventListener('change',t); d.addEventListener('input',t); } })();</script>
<select name="badge" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"><option value="">노출 뱃지 없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option></select><div class="p-6 border-2 border-dashed border-gray-100 rounded-3xl text-left"><label class="text-[10px] text-gray-400 uppercase font-black block mb-4 text-left">Main Image (목록·대표 사진)</label><input type="file" name="main_image" class="text-xs text-left"></div><div class="p-6 border-2 border-dashed border-blue-50 rounded-3xl text-left"><label class="text-[10px] text-blue-400 uppercase font-black block mb-4 text-left">Detail Images (상세 본문 여러 장)</label><input type="file" name="detail_images" multiple class="text-xs text-left"></div><button class="w-full bg-teal-600 text-white py-6 rounded-3xl font-black text-xl shadow-xl hover:bg-teal-700 transition active:scale-95 text-center">상품 등록 완료</button></form></div>""", selectable_categories=selectable_categories, p=None)

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_product_edit(pid):
    """개별 상품 수정 (상품 등록폼과 동일한 디자인 및 구성 적용)"""
    p = Product.query.get_or_404(pid)
    if request.method == 'POST':
        # 데이터 업데이트 로직
        p.name = request.form['name']
        p.description = request.form['description']
        p.price = int(request.form['price'])
        p.spec = request.form['spec']
        p.stock = int(request.form['stock'])
        p.origin = request.form['origin']
        p.badge = request.form.get('badge', '')
        p.deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        rt = request.form.get('reset_time', '').strip()
        p.reset_time = rt[:5] if rt else None
        rq = request.form.get('reset_to_quantity', '').strip()
        p.reset_to_quantity = int(rq) if rq.isdigit() else None
        if not p.reset_time:
            p.last_reset_at = None
        
        # 메인 이미지 변경 시 처리
        main_img = save_uploaded_file(request.files.get('main_image'))
        if main_img: p.image_url = main_img
        
        # 상세 이미지 변경 시 처리
        detail_files = request.files.getlist('detail_images')
        if detail_files and detail_files[0].filename != '':
            p.detail_image_url = ",".join(filter(None, [save_uploaded_file(f) for f in detail_files if f.filename != '']))
            
        db.session.commit()
        flash("상품 정보가 성공적으로 수정되었습니다.")
        return redirect('/admin')

    # 수정 폼 렌더링 (등록 폼과 디자인 통일)
    return render_template_string(HEADER_HTML + """
    <div class="max-w-xl mx-auto py-12 md:py-20 px-6 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-10 border-l-8 border-blue-600 pl-5 uppercase italic text-gray-800">
            Edit Product
        </h2>
        <p class="text-[11px] text-gray-500 font-bold mb-6 bg-gray-50 p-4 rounded-xl border border-gray-100">아래 각 항목은 상품 목록·상세 페이지의 <strong>어느 위치에 어떤 글귀</strong>로 노출되는지 적어 두었습니다. 등록 시 참고하세요.</p>
        
        <form method="POST" enctype="multipart/form-data" class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] shadow-2xl space-y-7 text-left">
            <div class="space-y-1">
                <label class="text-[10px] text-gray-400 font-black ml-4 uppercase tracking-widest">Product Name (상품명)</label>
                <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출 위치: 메인·카테고리 목록 카드의 <strong>상품명 한 줄</strong>, 상세 페이지 제목</p>
                <input name="name" placeholder="상품 명칭 (예: 꿀부사 사과)" 
                       class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm focus:ring-4 focus:ring-blue-50 outline-none transition" 
                       value="{{ p.name }}" required>
            </div>

            <div class="space-y-1">
                <label class="text-[10px] text-orange-500 font-black ml-4 uppercase tracking-widest">Short Intro / Badge (한줄소개·뱃지)</label>
                <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출 위치: 목록 카드에서 <strong>상품명 바로 옆</strong> (예: | 산지직송), 상세에서도 상품명 옆. 뱃지 선택 시 오늘마감·삼촌추천 등</p>
                <input name="badge" placeholder="예: 아삭하고 달콤한, 산지직송" 
                       class="w-full p-5 bg-orange-50 border border-orange-100 rounded-2xl font-black text-left text-sm focus:ring-4 focus:ring-orange-100 outline-none transition" 
                       value="{{ p.badge or '' }}">
            </div>

            <div class="space-y-1">
                <label class="text-[10px] text-teal-600 font-black ml-4 uppercase tracking-widest">Detailed Intro / Origin (사진 위 문구)</label>
                <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출 위치: <strong>상세 페이지 메인 이미지 바로 위</strong> 한 줄 문구 (원산지·품질 설명 등)</p>
                <input name="origin" placeholder="상세페이지 사진 바로 위에 노출될 문구" 
                       class="w-full p-5 bg-teal-50 border border-teal-100 rounded-2xl font-black text-left text-sm focus:ring-4 focus:ring-teal-100 outline-none transition" 
                       value="{{ p.origin or '' }}">
            </div>

            <div class="space-y-1">
                <label class="text-[10px] text-blue-600 font-black ml-4 uppercase tracking-widest">Delivery (배송 예정일)</label>
                <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출 위치: 목록 카드 <strong>이미지 좌측 배지</strong> (당일배송/+1일/+2일 등), 상세 페이지 배송 안내 문구</p>
                <select name="description" class="w-full p-5 bg-blue-50 text-blue-700 rounded-2xl font-black text-sm outline-none border-none focus:ring-4 focus:ring-blue-100">
                    <option value="+1일" {% if p.description == '+1일' %}selected{% endif %}>🚚 주문 완료 후 +1일 배송</option>
                    <option value="+2일" {% if p.description == '+2일' %}selected{% endif %}>🚚 주문 완료 후 +2일 배송</option>
                    <option value="+3일" {% if p.description == '+3일' %}selected{% endif %}>🚚 주문 완료 후 +3일 배송</option>
                    <option value="당일배송" {% if p.description == '당일배송' %}selected{% endif %}>⚡ 송도 지역 당일 배송</option>
                </select>
            </div>

            <div class="grid grid-cols-2 gap-5">
                <div class="space-y-1">
                    <label class="text-[10px] text-gray-400 font-black ml-4 uppercase tracking-widest">Price (원)</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출: 목록·상세 <strong>가격</strong></p>
                    <input name="price" type="number" placeholder="판매 가격" 
                           class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm outline-none" 
                           value="{{ p.price }}" required>
                </div>
                <div class="space-y-1">
                    <label class="text-[10px] text-gray-400 font-black ml-4 uppercase tracking-widest">Spec (규격)</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출: 목록 카드 <strong>규격 뱃지</strong> (예: 1박스, 1kg)</p>
                    <input name="spec" placeholder="예: 5kg/1박스" 
                           class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm outline-none" 
                           value="{{ p.spec or '' }}">
                </div>
            </div>

            <div class="grid grid-cols-2 gap-5">
                <div class="space-y-1">
                    <label class="text-[10px] text-gray-400 font-black ml-4 uppercase tracking-widest">Stock (한정 수량)</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출: 상세 페이지 <strong>잔여 N개</strong>, 목록 카드 하단 잔여 수</p>
                    <input name="stock" type="number" placeholder="재고 수량" 
                           class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm outline-none" 
                           value="{{ p.stock }}">
                </div>
                <div class="space-y-1">
                    <label class="text-[10px] text-red-400 font-black ml-4 uppercase tracking-widest">Deadline (마감일)</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">노출: 마감 있으면 상세·목록에 <strong>카운트다운·오늘마감</strong> 등. 비우면 상시 판매</p>
                    <input name="deadline" type="datetime-local" id="edit-deadline"
                           class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm outline-none" 
                           value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}">
                </div>
            </div>

            <div id="edit-reset-time-block" class="grid grid-cols-2 gap-5 {% if p.deadline %}hidden{% endif %}">
                <div class="space-y-1">
                    <label class="text-[10px] text-amber-600 font-black ml-4 uppercase tracking-widest">재고 초기화 시각 (마감일 없을 때)</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">매일 이 시각이 되면 아래 «초기화 수량»으로 재고가 자동 복원됩니다.</p>
                    <input name="reset_time" type="time" placeholder="09:00" 
                           class="w-full p-5 bg-amber-50 rounded-2xl font-black text-left text-sm outline-none border border-amber-100" 
                           value="{{ p.reset_time or '' }}">
                </div>
                <div class="space-y-1">
                    <label class="text-[10px] text-amber-600 font-black ml-4 uppercase tracking-widest">초기화 시 복원 수량</label>
                    <p class="text-[10px] text-gray-500 ml-4 mb-0.5">위 시각에 재고를 이 숫자로 맞춥니다. 비우면 초기화 안 함.</p>
                    <input name="reset_to_quantity" type="number" placeholder="예: 50" min="0"
                           class="w-full p-5 bg-amber-50 rounded-2xl font-black text-left text-sm outline-none border border-amber-100" 
                           value="{{ p.reset_to_quantity if p.reset_to_quantity is not none else '' }}">
                </div>
            </div>
            <script>
            (function(){
                var deadlineInput = document.getElementById('edit-deadline');
                var block = document.getElementById('edit-reset-time-block');
                if (deadlineInput && block) {
                    function toggle() { block.classList.toggle('hidden', !!deadlineInput.value); }
                    deadlineInput.addEventListener('change', toggle);
                    deadlineInput.addEventListener('input', toggle);
                }
            })();
            </script>

            <div class="pt-4 space-y-4">
                <div class="p-6 border-2 border-dashed border-gray-100 rounded-3xl">
                    <label class="text-[10px] text-gray-400 uppercase font-black block mb-3">Main Image (메인 이미지)</label>
                    <p class="text-[10px] text-gray-500 ml-0 mb-2">노출 위치: <strong>메인·카테고리 목록 카드</strong> 및 상세 페이지 대표 사진 (기존 이미지 유지 가능)</p>
                    <input type="file" name="main_image" class="text-[10px] font-bold">
                    {% if p.image_url %}
                    <p class="text-[9px] text-blue-500 mt-2 font-bold italic">현재 등록됨: {{ p.image_url.split('/')[-1] }}</p>
                    {% endif %}
                </div>
                
                <div class="p-6 border-2 border-dashed border-blue-50 rounded-3xl">
                    <label class="text-[10px] text-blue-400 uppercase font-black block mb-3">Detail Images (상세 이미지)</label>
                    <p class="text-[10px] text-gray-500 ml-0 mb-2">노출 위치: <strong>상품 상세 페이지</strong> 본문에 여러 장 노출 (새로 등록 시 기존 대체)</p>
                    <input type="file" name="detail_images" multiple class="text-[10px] font-bold">
                </div>
            </div>

            <button type="submit" class="w-full bg-blue-600 text-white py-6 rounded-3xl font-black text-xl shadow-xl hover:bg-blue-700 transition active:scale-95 text-center">
                상품 정보 수정 완료
            </button>
            
            <div class="text-center mt-4">
                <a href="/admin" class="text-gray-300 text-xs font-bold hover:text-gray-500 transition">수정 취소하고 돌아가기</a>
            </div>
        </form>
    </div>
    """ + FOOTER_HTML, p=p)
@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    """상품 삭제"""
    p = Product.query.get(pid)
    if p and check_admin_permission(p.category): db.session.delete(p); db.session.commit()
    return redirect('/admin')

@app.route('/admin/category/add', methods=['POST'])
@login_required
def admin_category_add():
    """카테고리 추가"""
    if not current_user.is_admin: return redirect('/')
    last_cat = Category.query.order_by(Category.order.desc()).first()
    next_order = (last_cat.order + 1) if last_cat else 0
    mg = request.form.get('min_member_grade', '').strip()
    min_mg = int(mg) if mg and mg.isdigit() and mg in ('1', '2', '3', '4', '5') else None
    db.session.add(Category(name=request.form['cat_name'], description=request.form.get('description'), tax_type=request.form['tax_type'], manager_email=request.form.get('manager_email'), seller_name=request.form.get('biz_name'), seller_inquiry_link=request.form.get('seller_link'), biz_name=request.form.get('biz_name'), biz_representative=request.form.get('biz_representative'), biz_reg_number=request.form.get('biz_reg_number'), biz_address=request.form.get('biz_address'), biz_contact=request.form.get('biz_contact'), bank_name=request.form.get('bank_name'), account_holder=request.form.get('account_holder'), settlement_account=request.form.get('settlement_account'), order=next_order, min_member_grade=min_mg))
    db.session.commit(); return redirect('/admin?tab=categories')

@app.route('/admin/category/edit/<int:cid>', methods=['GET', 'POST'])
@login_required
def admin_category_edit(cid):
    """카테고리 수정"""
    if not current_user.is_admin: return redirect('/')
    cat = Category.query.get_or_404(cid)
    if request.method == 'POST':
        cat.name, cat.description, cat.tax_type, cat.manager_email = request.form['cat_name'], request.form['description'], request.form['tax_type'], request.form.get('manager_email')
        cat.biz_name, cat.biz_representative, cat.biz_reg_number, cat.biz_address, cat.biz_contact, cat.seller_inquiry_link = request.form.get('biz_name'), request.form.get('biz_representative'), request.form.get('biz_reg_number'), request.form.get('biz_address'), request.form.get('biz_contact'), request.form.get('seller_link')
        cat.bank_name, cat.account_holder, cat.settlement_account = request.form.get('bank_name'), request.form.get('account_holder'), request.form.get('settlement_account')
        cat.seller_name = cat.biz_name
        mg = request.form.get('min_member_grade', '').strip()
        cat.min_member_grade = int(mg) if mg and mg.isdigit() and mg in ('1', '2', '3', '4', '5') else None
        db.session.commit(); return redirect('/admin?tab=categories')
    mg_val = getattr(cat, 'min_member_grade', None)
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-6 font-black text-left"><h2 class="text-2xl md:text-3xl font-black mb-12 tracking-tighter uppercase text-teal-600 text-left">Edit Category Profile</h2><form method="POST" class="bg-white p-10 rounded-[3rem] shadow-2xl space-y-8 text-left"><div><label class="text-[10px] text-gray-400 uppercase font-black ml-4 text-left">Settings</label><input name="cat_name" value="{{cat.name}}" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-2 text-sm text-left" required><textarea name="description" class="border border-gray-100 p-5 rounded-2xl w-full h-24 font-black mt-3 text-sm text-left" placeholder="한줄 소개">{{cat.description or ''}}</textarea><input name="manager_email" value="{{cat.manager_email or ''}}" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-3 text-sm text-left" placeholder="매니저 이메일"><select name="tax_type" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-3 text-sm text-left bg-white"><option value="과세" {% if cat.tax_type == '과세' %}selected{% endif %}>과세</option><option value="면세" {% if cat.tax_type == '면세' %}selected{% endif %}>면세</option></select><p class="text-[10px] text-amber-600 font-bold uppercase mt-4 ml-4 text-left">회원 등급별 노출 (비워두면 전체)</p><select name="min_member_grade" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left mt-2 bg-white"><option value="">전체 회원</option><option value="1" {% if mg_val == 1 %}selected{% endif %}>1단계 이상</option><option value="2" {% if mg_val == 2 %}selected{% endif %}>2단계 이상</option><option value="3" {% if mg_val == 3 %}selected{% endif %}>3단계 이상</option><option value="4" {% if mg_val == 4 %}selected{% endif %}>4단계 이상</option><option value="5" {% if mg_val == 5 %}selected{% endif %}>5단계만</option></select></div><div class="border-t border-gray-50 pt-10 space-y-4 text-left"><label class="text-[10px] text-teal-600 uppercase font-black ml-4 text-left">Business Info</label><input name="biz_name" value="{{cat.biz_name or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="상호명"><input name="biz_representative" value="{{cat.biz_representative or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="대표자"><input name="biz_reg_number" value="{{cat.biz_reg_number or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="사업자번호"><input name="biz_address" value="{{cat.biz_address or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="주소"><input name="biz_contact" value="{{cat.biz_contact or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="고객센터"><input name="seller_link" value="{{cat.seller_inquiry_link or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="문의 링크 URL"><p class="text-[10px] text-blue-600 font-bold uppercase mt-4 text-left">정산 계좌</p><input name="bank_name" value="{{cat.bank_name or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left mt-2" placeholder="은행명"><input name="account_holder" value="{{cat.account_holder or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left mt-2" placeholder="예금주"><input name="settlement_account" value="{{cat.settlement_account or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left mt-2" placeholder="정산계좌 (계좌번호)"></div><button class="w-full bg-blue-600 text-white py-6 rounded-3xl font-black shadow-xl hover:bg-blue-700 transition text-center text-center">Save Profile Updates</button></form></div>""", cat=cat, mg_val=mg_val)

@app.route('/admin/category/move/<int:cid>/<string:direction>')
@login_required
def admin_category_move(cid, direction):
    """카테고리 순서 이동"""
    if not current_user.is_admin: return redirect('/')
    curr = Category.query.get_or_404(cid)
    if direction == 'up': target = Category.query.filter(Category.order < curr.order).order_by(Category.order.desc()).first()
    else: target = Category.query.filter(Category.order > curr.order).order_by(Category.order.asc()).first()
    if target: curr.order, target.order = target.order, curr.order; db.session.commit()
    return redirect('/admin?tab=categories')

@app.route('/admin/category/delete/<int:cid>')
@login_required
def admin_category_delete(cid):
    """카테고리 삭제"""
    if not current_user.is_admin: return redirect('/')
    db.session.delete(Category.query.get(cid)); db.session.commit(); return redirect('/admin?tab=categories')


@app.route('/admin/sellers/excel')
@login_required
def admin_sellers_excel():
    """판매자 정보(Seller Business Profile) 엑셀 다운로드"""
    if not current_user.is_admin:
        flash("권한이 없습니다.")
        return redirect('/admin')
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    rows = []
    for i, c in enumerate(categories, 1):
        rows.append({
            '순서': i,
            '카테고리': c.name or '',
            '상호': c.biz_name or '',
            '대표자': c.biz_representative or '',
            '사업자등록번호': c.biz_reg_number or '',
            '소재지': c.biz_address or '',
            '고객센터': c.biz_contact or '',
            '문의링크': c.seller_inquiry_link or '',
            '은행명': c.bank_name or '',
            '예금주': c.account_holder or '',
            '정산계좌': c.settlement_account or '',
            '매니저이메일': c.manager_email or '',
        })
    if not rows:
        flash("다운로드할 판매자 정보가 없습니다.")
        return redirect('/admin?tab=sellers')
    df = pd.DataFrame(rows)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    out.seek(0)
    filename = f"판매자정보_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True)


from urllib.parse import quote


@app.route('/admin/orders/sales_excel')
@login_required
def admin_orders_sales_excel():
    """조회 결과 상세 테이블 엑셀 다운로드 (주문일시, 판매상품명, 판매수량, 결제상태)"""
    categories = Category.query.all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    if not (current_user.is_admin or my_categories):
        flash("권한이 없습니다.")
        return redirect('/admin')
    is_master = current_user.is_admin
    now = datetime.now()
    start_date_str = request.args.get('start_date', now.strftime('%Y-%m-%d 00:00')).replace('T', ' ')
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d 23:59')).replace('T', ' ')
    query = Order.query.filter(Order.status != '결제취소')
    order_ids_param = request.args.get('order_ids', '').strip()
    if order_ids_param:
        allowed_ids = [x.strip() for x in order_ids_param.split(',') if x.strip()]
        if allowed_ids:
            query = query.filter(Order.order_id.in_(allowed_ids))
    else:
        try:
            sd = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M')
            ed = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M')
            query = query.filter(Order.created_at >= sd, Order.created_at <= ed)
        except Exception:
            pass
    sel_order_cat = request.args.get('order_cat', '전체')
    orders = query.order_by(Order.created_at.desc()).all()
    sales_table_rows = []
    for o in orders:
        if is_master:
            order_show = True
        else:
            order_show = False
            parts = (o.product_details or '').split(' | ')
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*)', part)
                if match and match.group(1).strip() in my_categories:
                    order_show = True
                    break
        if not order_show:
            continue
        parts = (o.product_details or '').split(' | ')
        order_date_str = o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else ''
        status_str = o.status or '결제완료'
        items = OrderItem.query.filter_by(order_id=o.id).order_by(OrderItem.id.asc()).all()
        if items:
            for oi in items:
                if (is_master or oi.product_category in my_categories) and (sel_order_cat == '전체' or oi.product_category == sel_order_cat):
                    is_cancelled = getattr(oi, 'cancelled', False) or (getattr(oi, 'item_status', None) in ('부분취소', '품절취소'))
                    sales_table_rows.append({
                        'order_date': order_date_str,
                        'product_name': oi.product_name,
                        'category': oi.product_category,
                        'quantity': 0 if is_cancelled else oi.quantity,
                        'status': '취소' if is_cancelled else (getattr(oi, 'item_status', None) or status_str)
                    })
        else:
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*)', part)
                if match:
                    cat_n, items_str = match.groups()
                    if (is_master or cat_n in my_categories) and (sel_order_cat == '전체' or cat_n == sel_order_cat):
                        for item in items_str.split(', '):
                            it_match = re.search(r'(.*?)\((\d+)\)', item)
                            if it_match:
                                pn, qt = it_match.groups()
                                sales_table_rows.append({'order_date': order_date_str, 'product_name': pn.strip(), 'category': cat_n, 'quantity': int(qt), 'status': status_str})
    if not sales_table_rows:
        flash("다운로드할 데이터가 없습니다.")
        return redirect('/admin?tab=orders')
    df = pd.DataFrame(sales_table_rows, columns=['order_date', 'product_name', 'category', 'quantity', 'status'])
    df.columns = ['주문일시', '판매상품명', '카테고리', '판매수량', '결제상태']
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    out.seek(0)
    filename = f"매출상세_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True)


@app.route('/admin/orders/sales_summary_excel')
@login_required
def admin_orders_sales_summary_excel():
    """판매상품명별 판매수량 총합계 엑셀 다운로드 (품목·판매상품명·총합계)"""
    categories = Category.query.all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    if not (current_user.is_admin or my_categories):
        flash("권한이 없습니다.")
        return redirect('/admin')
    is_master = current_user.is_admin
    now = datetime.now()
    start_date_str = request.args.get('start_date', now.strftime('%Y-%m-%d 00:00')).replace('T', ' ')
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d 23:59')).replace('T', ' ')
    query = Order.query.filter(Order.status != '결제취소')
    order_ids_param = request.args.get('order_ids', '').strip()
    if order_ids_param:
        allowed_ids = [x.strip() for x in order_ids_param.split(',') if x.strip()]
        if allowed_ids:
            query = query.filter(Order.order_id.in_(allowed_ids))
    else:
        try:
            sd = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M')
            ed = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M')
            query = query.filter(Order.created_at >= sd, Order.created_at <= ed)
        except Exception:
            pass
    sel_order_cat = request.args.get('order_cat', '전체')
    orders = query.order_by(Order.created_at.desc()).all()
    sales_table_rows = []
    for o in orders:
        if is_master:
            order_show = True
        else:
            order_show = False
            parts = (o.product_details or '').split(' | ')
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*)', part)
                if match and match.group(1).strip() in my_categories:
                    order_show = True
                    break
        if not order_show:
            continue
        parts = (o.product_details or '').split(' | ')
        order_date_str = o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else ''
        status_str = o.status or '결제완료'
        items = OrderItem.query.filter_by(order_id=o.id).order_by(OrderItem.id.asc()).all()
        if items:
            for oi in items:
                if (is_master or oi.product_category in my_categories) and (sel_order_cat == '전체' or oi.product_category == sel_order_cat):
                    is_cancelled = getattr(oi, 'cancelled', False) or (getattr(oi, 'item_status', None) in ('부분취소', '품절취소'))
                    sales_table_rows.append({
                        'order_date': order_date_str,
                        'product_name': oi.product_name,
                        'category': oi.product_category,
                        'quantity': 0 if is_cancelled else oi.quantity,
                        'status': '취소' if is_cancelled else (getattr(oi, 'item_status', None) or status_str)
                    })
        else:
            for part in parts:
                match = re.search(r'\[(.*?)\] (.*)', part)
                if match:
                    cat_n, items_str = match.groups()
                    if (is_master or cat_n in my_categories) and (sel_order_cat == '전체' or cat_n == sel_order_cat):
                        for item in items_str.split(', '):
                            it_match = re.search(r'(.*?)\((\d+)\)', item)
                            if it_match:
                                pn, qt = it_match.groups()
                                sales_table_rows.append({'order_date': order_date_str, 'product_name': pn.strip(), 'category': cat_n, 'quantity': int(qt), 'status': status_str})
    from collections import defaultdict
    agg = defaultdict(int)
    for r in sales_table_rows:
        key = (r.get('category', ''), r.get('product_name', ''))
        agg[key] += r.get('quantity', 0)
    product_summary_rows = [{'category': k[0], 'product_name': k[1], 'total_quantity': v} for k, v in sorted(agg.items())]
    if not product_summary_rows:
        flash("다운로드할 집계 데이터가 없습니다.")
        return redirect('/admin?tab=orders')
    df = pd.DataFrame(product_summary_rows, columns=['category', 'product_name', 'total_quantity'])
    df.columns = ['품목(카테고리)', '판매상품명', '판매수량 총합계']
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    out.seek(0)
    filename = f"판매상품명별_총합계_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True)


@app.route('/admin/orders/settlement_detail_excel')
@login_required
def admin_orders_settlement_detail_excel():
    """정산 상세 엑셀 다운로드 (Settlement 테이블 n넘버 기준, 날짜·카테고리·입금상태 필터)"""
    categories = Category.query.all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    if not (current_user.is_admin or my_categories):
        flash("권한이 없습니다.")
        return redirect('/admin')
    is_master = current_user.is_admin
    now = datetime.now()
    start_date_str = request.args.get('start_date', now.strftime('%Y-%m-%d 00:00')).replace('T', ' ')
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d 23:59')).replace('T', ' ')
    sel_order_cat = request.args.get('order_cat', '전체')
    sel_settlement_status = request.args.get('settlement_status', '전체')
    if sel_settlement_status == '정산대기': sel_settlement_status = '입금대기'
    if sel_settlement_status == '정산완료': sel_settlement_status = '입금완료'
    try:
        start_dt = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M')
        end_dt = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M')
    except Exception:
        start_dt = now.replace(hour=0, minute=0, second=0)
        end_dt = now.replace(hour=23, minute=59, second=59)
    q = Settlement.query.filter(Settlement.sale_dt >= start_dt, Settlement.sale_dt <= end_dt)
    if not is_master:
        q = q.filter(Settlement.category.in_(my_categories))
    if sel_order_cat != '전체':
        q = q.filter(Settlement.category == sel_order_cat)
    if sel_settlement_status and sel_settlement_status != '전체':
        q = q.filter(Settlement.settlement_status == sel_settlement_status)
    rows = []
    for s in q.order_by(Settlement.sale_dt.desc()).all():
        rows.append({
            'settlement_no': s.settlement_no,
            'sale_dt': s.sale_dt.strftime('%Y-%m-%d %H:%M') if s.sale_dt else '',
            'category': s.category,
            'tax_exempt': '면세' if s.tax_exempt else '과세',
            'product_name': s.product_name,
            'sales_amount': s.sales_amount,
            'fee': s.fee,
            'delivery_fee': s.delivery_fee,
            'settlement_total': s.settlement_total,
            'settlement_status': s.settlement_status,
            'settled_at': s.settled_at.strftime('%Y-%m-%d %H:%M') if s.settled_at else '',
        })
    if not rows:
        flash("다운로드할 정산 상세 데이터가 없습니다.")
        return redirect('/admin?tab=settlement')
    df = pd.DataFrame(rows, columns=['settlement_no', 'sale_dt', 'category', 'tax_exempt', 'product_name', 'sales_amount', 'fee', 'delivery_fee', 'settlement_total', 'settlement_status', 'settled_at'])
    df.columns = ['정산번호(n)', '판매일시', '카테고리', '면세여부', '품목', '판매금액', '수수료', '배송관리비', '정산합계', '입금상태', '입금일']
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    out.seek(0)
    filename = f"정산상세_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True)


@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    """주문 내역 엑셀 다운로드 (정산여부/일시 포함 + 품목 분리 최종 완성본)"""
    categories = Category.query.all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    
    if not (current_user.is_admin or my_categories):
        flash("엑셀 다운로드 권한이 없습니다.")
        return redirect('/admin')



    is_master = current_user.is_admin
    now = datetime.now()
    
    # [기존 로직 유지] 날짜 변수 정의
    start_date_str = request.args.get('start_date', now.strftime('%Y-%m-%d 00:00')).replace('T', ' ')
    end_date_str = request.args.get('end_date', now.strftime('%Y-%m-%d 23:59')).replace('T', ' ')
    
    query = Order.query.filter(Order.status != '결제취소')
    
    # 현재 권한 있는 오더만 사용: order_ids가 있으면 해당 주문만 대상(날짜는 참고용), 없으면 날짜로만 필터
    order_ids_param = request.args.get('order_ids', '').strip()
    if order_ids_param:
        allowed_ids = [x.strip() for x in order_ids_param.split(',') if x.strip()]
        if allowed_ids:
            query = query.filter(Order.order_id.in_(allowed_ids))
    else:
        try:
            sd = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M')
            ed = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M')
            query = query.filter(Order.created_at >= sd, Order.created_at <= ed)
        except:
            pass

    orders = query.order_by(Order.created_at.desc()).all()
    
    data = []
    all_product_columns = set()

    for o in orders:
        # 권한 있는 품목만 합산 (오더별 정산대상금액)
        row_manager_subtotal = 0

        row = {
            "일시": o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else "-",
            "주문번호": o.order_id[-8:] if o.order_id else "-",
            "고객명": o.customer_name or "-",
            "전화번호": o.customer_phone or "-",
            "주소": o.delivery_address or "-",
            "메모": o.request_memo or "-",
            "결제금액": 0,  # 아래에서 권한별로 채움
            "상태": o.status or "-",
            "입금여부": "입금완료" if getattr(o, 'is_settled', False) else "대기",
            "정산일시": o.settled_at.strftime('%Y-%m-%d %H:%M') if (getattr(o, 'is_settled', False) and o.settled_at) else "-"
        }
        
        parts = o.product_details.split(' | ') if o.product_details else []
        row_show_flag = False
        
        for part in parts:
            match = re.search(r'\[(.*?)\] (.*)', part)
            if match:
                cat_n, items_str = match.groups()
                if is_master or cat_n in my_categories:
                    row_show_flag = True
                    items = items_str.split(', ')
                    for item in items:
                        item_match = re.search(r'(.*?)\((\d+)\)', item)
                        if item_match:
                            p_name = item_match.group(1).strip()
                            p_qty = int(item_match.group(2))
                            col_name = f"[{cat_n}] {p_name}"
                            row[col_name] = p_qty
                            all_product_columns.add(col_name)
                            # 권한 있는 품목만 정산대상금액에 합산
                            p_obj = Product.query.filter_by(name=p_name).first()
                            if p_obj:
                                row_manager_subtotal += p_obj.price * p_qty

        if row_show_flag:
            # 마스터는 주문 전체 결제금액, 매니저는 해당 오더의 권한 품목 합계만
            row["결제금액"] = o.total_price if is_master else row_manager_subtotal
            data.append(row)

    if not data:
        flash("다운로드할 데이터가 없습니다.")
        return redirect('/admin?tab=orders')

    # 데이터프레임 생성 및 열 순서 확정
    df = pd.DataFrame(data)
    
    # 헤더 순서 고정 (정보성 열들을 앞으로 배치)
    base_cols = ["일시", "주문번호", "고객명", "전화번호", "주소", "메모", "결제금액", "상태", "정산여부", "정산일시"]
    
    # 실제 생성된 상품 열들만 추출하여 가나다순 정렬
    existing_base_cols = [c for c in base_cols if c in df.columns]
    product_cols = sorted([c for c in df.columns if c not in base_cols])
    
    df = df[existing_base_cols + product_cols]
    df = df.fillna('') # 수량 없는 칸 빈칸 처리

    # 총합계 행 추가 (권한 있는 품목 합계만)
    total_row = {c: "" for c in df.columns}
    total_row["주문번호"] = "총합계"
    if "결제금액" in df.columns:
        total_row["결제금액"] = pd.to_numeric(df["결제금액"], errors="coerce").fillna(0).astype(int).sum()
    df = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    
    out.seek(0)
    filename = f"바구니삼촌_주문정산_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    return send_file(out, download_name=filename, as_attachment=True)
    # 데이터프레임 생성 및 열 순서 정리
    df = pd.DataFrame(data)
    
    # 기본 정보 열 리스트
    base_cols = ["일시", "주문번호", "고객명", "전화번호", "주소", "메모", "결제금액", "상태"]
    # 실제 생성된 상품 열들만 추출하여 가나다순 정렬
    exist_prod_cols = sorted([c for c in all_product_columns if c in df.columns])
    
    # 최종 열 순서 확정 (기본정보 + 상품열)
    df = df[base_cols + exist_prod_cols]
    # 수량이 없는 칸(NaN)은 0 또는 빈칸으로 처리 (수량 집계를 위해 0 추천)
    df = df.fillna('') 

    # 메모리 버퍼에 엑셀 쓰기
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='주문리스트')
        
        # 엑셀 열 너비 자동 최적화
        worksheet = w.sheets['주문리스트']
        for idx, col in enumerate(df.columns):
            column_len = df[col].astype(str).str.len().max()
            column_len = max(column_len, len(col)) + 5
            worksheet.column_dimensions[chr(65 + idx)].width = min(column_len, 60)

    out.seek(0)
    
    # 파일명 한글 깨짐 방지 인코딩
    filename = f"바구니삼촌_주문데이터_{datetime.now().strftime('%m%d_%H%M')}.xlsx"
    encoded_filename = quote(filename)
    
    response = send_file(
        out, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, 
        download_name=filename
    )
    response.headers["Content-Disposition"] = f"attachment; filename={encoded_filename}; filename*=UTF-8''{encoded_filename}"
    
    return response

# --------------------------------------------------------------------------------
# 9. 데이터베이스 초기화 및 서버 실행
# --------------------------------------------------------------------------------

def init_db():
    """데이터베이스 및 기초 데이터 생성"""
    with app.app_context():
        # 모든 테이블(Settlement 포함) 생성
        db.create_all()
        # 누락된 컬럼 수동 추가 (ALTER TABLE 로직)
        cols = [
            ("product", "description", "VARCHAR(200)"), 
            ("product", "detail_image_url", "TEXT"), 
            ("user", "request_memo", "VARCHAR(500)"), 
            ("order", "delivery_fee", "INTEGER DEFAULT 0"), 
            ("product", "badge", "VARCHAR(50)"), 
            ("category", "seller_name", "VARCHAR(100)"), 
            ("category", "seller_inquiry_link", "VARCHAR(500)"), 
            ("category", "order", "INTEGER DEFAULT 0"), 
            ("category", "description", "VARCHAR(200)"), 
            ("category", "biz_name", "VARCHAR(100)"), 
            ("category", "biz_representative", "VARCHAR(50)"), 
            ("category", "biz_reg_number", "VARCHAR(50)"), 
            ("category", "biz_address", "VARCHAR(200)"), 
            ("category", "biz_contact", "VARCHAR(50)"), 
            ("category", "bank_name", "VARCHAR(50)"), 
            ("category", "account_holder", "VARCHAR(100)"), 
            ("category", "settlement_account", "VARCHAR(50)"), 
            ("order", "status", "VARCHAR(20) DEFAULT '결제완료'"), 
            ("review", "user_name", "VARCHAR(50)"), 
            ("review", "product_name", "VARCHAR(100)"),
            ("review", "order_id", "INTEGER"),
            ("review", "category_id", "INTEGER"),
            ("order_item", "item_status", "VARCHAR(30) DEFAULT '결제완료'"),
            ("order_item", "status_message", "TEXT")
        ]
        for t, c, ct in cols:
            try: 
                db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN \"{c}\" {ct}"))
                db.session.commit()
            except: 
                db.session.rollback()

        # 기존 리뷰에 판매자(category_id) 보정: product_id -> 상품의 카테고리 -> category.id
        try:
            for r in Review.query.filter(Review.category_id == None):
                if r.product_id:
                    p = Product.query.get(r.product_id)
                    if p:
                        cat = Category.query.filter_by(name=p.category).first()
                        if cat:
                            r.category_id = cat.id
            db.session.commit()
        except Exception:
            db.session.rollback()
        
        # 관리자 계정 생성 로직 동일 유지
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        db.session.commit()
            
        # 기초 데이터 (관리자 및 샘플 카테고리)
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        if not Category.query.first():
            db.session.add(Category(name="신선 농산물", tax_type="면세", order=0, description="물류 전문가가 엄선한 산지직송 제철 농산물입니다.")); 
            db.session.add(Category(name="프리미엄 공동구매", tax_type="과세", order=1, description="유통 단계를 파격적으로 줄인 송도 전용 공구 상품입니다."));
        db.session.commit()

# [수정 위치: app.py 파일 가장 마지막 부분]

import subprocess

# --- 수정 전 기존 코드 ---
# if __name__ == "__main__":
#     init_db()
#     if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
#         subprocess.Popen(["python", delivery_script])
#     app.run(host="0.0.0.0", port=5000, debug=True)

# --- 수정 후 (이 부분으로 교체하세요) ---
if __name__ == "__main__":
    with app.app_context():
        # 쇼핑몰 테이블과 배송 테이블을 각각의 DB 파일에 생성합니다.
        db.create_all() # BINDS 설정에 따라 자동으로 분리 생성됨
        
        # [복구] 배송 시스템 최초 관리자 생성 로직 추가
        from delivery_system import AdminUser
        if not AdminUser.query.filter_by(username='admin').first():
            db.session.add(AdminUser(username="admin", password="1234"))
            db.session.commit()
# 프로덕션(gunicorn 등) 앱 로드 시 테이블 생성 + 마이그레이션
with app.app_context():
    db.create_all()
    from sqlalchemy import text
    try:
        rp = db.session.execute(text("PRAGMA table_info(settlement)")).fetchall()
        cols = [row[1] for row in rp] if rp else []
        if cols and 'settlement_no' not in cols:
            # 기존 settlement는 구 스키마 → category_settlement로 이름 변경 후 새 settlement 생성
            try:
                db.session.execute(text("ALTER TABLE settlement RENAME TO category_settlement"))
                db.session.commit()
            except Exception:
                db.session.rollback()
                try:
                    db.session.execute(text("DROP TABLE IF EXISTS category_settlement"))
                    db.session.execute(text("ALTER TABLE settlement RENAME TO category_settlement"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text("SELECT 1 FROM settlement LIMIT 1"))
    except Exception:
        db.create_all()
    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN is_settled INTEGER DEFAULT 0'))
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN settled_at DATETIME'))
        db.session.commit()
    except: pass
    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN settlement_status VARCHAR(20) DEFAULT \'입금대기\''))
        db.session.commit()
    except: pass
    try:
        db.session.execute(text('UPDATE "order" SET settlement_status = \'입금대기\' WHERE settlement_status = \'정산대기\''))
        db.session.execute(text('UPDATE "order" SET settlement_status = \'입금완료\' WHERE settlement_status = \'정산완료\''))
        db.session.commit()
    except: pass
    try:
        db.session.execute(text('ALTER TABLE order_item ADD COLUMN settlement_status VARCHAR(20) DEFAULT \'입금대기\''))
        db.session.commit()
    except: pass
    try:
        db.session.execute(text('ALTER TABLE order_item ADD COLUMN settled_at DATETIME'))
        db.session.commit()
    except: pass
    # 회원 등급 컬럼 추가 (기존 DB 호환)
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN member_grade INTEGER DEFAULT 1'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN member_grade_overridden INTEGER DEFAULT 0'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE category ADD COLUMN min_member_grade INTEGER'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN points INTEGER DEFAULT 0'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    # 소셜 로그인 컬럼 (기존 DB 호환)
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN auth_provider VARCHAR(20)'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN auth_provider_id VARCHAR(100)'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN points_used INTEGER DEFAULT 0'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE point_log ADD COLUMN order_item_id INTEGER'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE point_log ADD COLUMN adjusted_by INTEGER'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    # product 재고 초기화 컬럼 (기존 DB 호환)
    try:
        db.session.execute(text('ALTER TABLE product ADD COLUMN reset_time VARCHAR(5)'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE product ADD COLUMN reset_to_quantity INTEGER'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE product ADD COLUMN last_reset_at DATETIME'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    init_db() # 기존 쇼핑몰 초기화 함수 호출
    
    # 로컬 테스트 및 Render 배포 호환 포트 설정 (기본 5000)
    port = int(os.environ.get("PORT", 5000))
    root = os.path.dirname(os.path.abspath(__file__))
    extra_files = [
        os.path.join(root, "app.py"),
        os.path.join(root, "delivery_system.py"),
    ]
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True, extra_files=extra_files)