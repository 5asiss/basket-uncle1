# --------------------------------------------------------------------------------
# 데이터베이스 모델 (DB 구조 변경 금지 규칙 준수)
# --------------------------------------------------------------------------------
from datetime import datetime
from flask_login import UserMixin
from delivery_system import db_delivery

db = db_delivery


class CategorySettlement(db.Model):
    """카테고리별 정산 내역 모델 (요청·완료 처리용)"""
    __tablename__ = "category_settlement"
    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(50), nullable=False)
    manager_email = db.Column(db.String(120), nullable=False)
    total_sales = db.Column(db.Integer, default=0)
    delivery_fee_sum = db.Column(db.Integer, default=0)
    settlement_amount = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='입금대기')
    requested_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)


class User(db.Model, UserMixin):
    """사용자 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=True)
    name = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    address_detail = db.Column(db.String(200))
    entrance_pw = db.Column(db.String(100))
    request_memo = db.Column(db.String(500))
    is_admin = db.Column(db.Boolean, default=False)
    consent_marketing = db.Column(db.Boolean, default=False)
    member_grade = db.Column(db.Integer, default=1)
    member_grade_overridden = db.Column(db.Boolean, default=False)
    points = db.Column(db.Integer, default=0)
    points_accumulated = db.Column(db.Integer, default=0)   # 적립포인트 (구매/배송완료 등)
    points_event = db.Column(db.Integer, default=0)         # 이벤트포인트
    points_cash = db.Column(db.Integer, default=0)          # 캐시충전포인트
    auth_provider = db.Column(db.String(20), nullable=True)
    auth_provider_id = db.Column(db.String(100), nullable=True)
    utm_source = db.Column(db.String(100), nullable=True)
    utm_medium = db.Column(db.String(100), nullable=True)
    utm_campaign = db.Column(db.String(100), nullable=True)
    __table_args__ = (db.UniqueConstraint('auth_provider', 'auth_provider_id', name='uq_user_auth_provider'),)


class Category(db.Model):
    """카테고리 및 판매 사업자 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    category_type = db.Column(db.String(20), default='입점형')
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
    bank_name = db.Column(db.String(50), nullable=True)
    account_holder = db.Column(db.String(100), nullable=True)
    settlement_account = db.Column(db.String(50), nullable=True)
    min_member_grade = db.Column(db.Integer, nullable=True)


class Product(db.Model):
    """상품 정보 모델"""
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50))
    description = db.Column(db.String(200))
    name = db.Column(db.String(200))
    price = db.Column(db.Integer)
    supply_price = db.Column(db.Integer, nullable=True)
    spec = db.Column(db.String(100))
    origin = db.Column(db.String(100))
    farmer = db.Column(db.String(50))
    image_url = db.Column(db.String(500))
    detail_image_url = db.Column(db.Text)
    stock = db.Column(db.Integer, default=10)
    deadline = db.Column(db.DateTime, nullable=True)
    reset_time = db.Column(db.String(5), nullable=True)
    reset_to_quantity = db.Column(db.Integer, nullable=True)
    last_reset_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    tax_type = db.Column(db.String(20), default='과세')
    badge = db.Column(db.String(50), default='')
    view_count = db.Column(db.Integer, default=0)


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
    is_settled = db.Column(db.Boolean, default=False)
    settled_at = db.Column(db.DateTime, nullable=True)
    settlement_status = db.Column(db.String(20), default='입금대기')
    order_id = db.Column(db.String(100))
    payment_key = db.Column(db.String(200))
    delivery_address = db.Column(db.String(500))
    request_memo = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)
    points_used = db.Column(db.Integer, default=0)
    quick_extra_fee = db.Column(db.Integer, default=0)
    utm_source = db.Column(db.String(100), nullable=True)
    utm_medium = db.Column(db.String(100), nullable=True)
    utm_campaign = db.Column(db.String(100), nullable=True)


class OrderItem(db.Model):
    """주문 품목"""
    __tablename__ = "order_item"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    product_category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    tax_type = db.Column(db.String(20), default='과세')
    cancelled = db.Column(db.Boolean, default=False)
    item_status = db.Column(db.String(30), default='결제완료')
    status_message = db.Column(db.Text, nullable=True)
    delivery_proof_image_url = db.Column(db.String(500), nullable=True)
    settlement_status = db.Column(db.String(20), default='입금대기')
    settled_at = db.Column(db.DateTime, nullable=True)


class OrderItemLog(db.Model):
    __tablename__ = "order_item_log"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    order_item_id = db.Column(db.Integer, nullable=True)
    log_type = db.Column(db.String(30), nullable=False)
    old_value = db.Column(db.String(50), nullable=True)
    new_value = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class UserMessage(db.Model):
    __tablename__ = "user_message"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    msg_type = db.Column(db.String(30), default='custom')
    related_order_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    read_at = db.Column(db.DateTime, nullable=True)


class MessageTemplate(db.Model):
    __tablename__ = "message_template"
    id = db.Column(db.Integer, primary_key=True)
    msg_type = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class PushSubscription(db.Model):
    __tablename__ = "push_subscription"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint = db.Column(db.String(512), nullable=False)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'endpoint', name='uq_push_user_endpoint'),)


class RestaurantRequest(db.Model):
    __tablename__ = "restaurant_request"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    store_name = db.Column(db.String(200), nullable=False)
    store_info = db.Column(db.Text, nullable=True)
    menu = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_hidden = db.Column(db.Boolean, default=False)
    is_notice = db.Column(db.Boolean, default=False)


class RestaurantRecommend(db.Model):
    __tablename__ = "restaurant_recommend"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    restaurant_request_id = db.Column(db.Integer, db.ForeignKey('restaurant_request.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'restaurant_request_id', name='uq_restaurant_recommend_user_post'),)


class RestaurantVote(db.Model):
    __tablename__ = "restaurant_vote"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    restaurant_request_id = db.Column(db.Integer, db.ForeignKey('restaurant_request.id', ondelete='CASCADE'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'restaurant_request_id', name='uq_restaurant_vote_user_post'),)


class PartnershipInquiry(db.Model):
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
    is_notice = db.Column(db.Boolean, default=False)


class FreeBoard(db.Model):
    __tablename__ = "free_board"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_hidden = db.Column(db.Boolean, default=False)
    is_notice = db.Column(db.Boolean, default=False)


class DeliveryRequest(db.Model):
    __tablename__ = "delivery_request"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    region_name = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_hidden = db.Column(db.Boolean, default=False)
    is_notice = db.Column(db.Boolean, default=False)


class DeliveryRequestVote(db.Model):
    __tablename__ = "delivery_request_vote"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    delivery_request_id = db.Column(db.Integer, db.ForeignKey('delivery_request.id', ondelete='CASCADE'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('user_id', 'delivery_request_id', name='uq_delivery_request_vote_user_post'),)


class BoardComment(db.Model):
    """게시판 공통 댓글 (전국맛집요청·배송요청·제휴문의·자유게시판)"""
    __tablename__ = "board_comment"
    id = db.Column(db.Integer, primary_key=True)
    board_type = db.Column(db.String(30), nullable=False)  # restaurant, delivery, partnership, free
    post_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user_name = db.Column(db.String(50), nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


class DailyStat(db.Model):
    __tablename__ = "daily_stat"
    id = db.Column(db.Integer, primary_key=True)
    stat_date = db.Column(db.Date, unique=True, nullable=False)
    main_views = db.Column(db.Integer, default=0)
    category_views = db.Column(db.Integer, default=0)
    product_views = db.Column(db.Integer, default=0)
    cart_views = db.Column(db.Integer, default=0)


class SellerOrderConfirmation(db.Model):
    __tablename__ = "seller_order_confirmation"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    category_name = db.Column(db.String(50), nullable=False)
    confirmation_code = db.Column(db.String(10), unique=True, nullable=False)
    order_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    recipient_email = db.Column(db.String(120), nullable=True)


class EmailOrderLineStatus(db.Model):
    __tablename__ = "email_order_line_status"
    id = db.Column(db.Integer, primary_key=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_item.id'), unique=True, nullable=False)
    status = db.Column(db.String(20), default='대기')
    confirmation_id = db.Column(db.Integer, db.ForeignKey('seller_order_confirmation.id'), nullable=True)


class SitePopup(db.Model):
    __tablename__ = "site_popup"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=True)
    popup_type = db.Column(db.String(30), default='notice')
    image_url = db.Column(db.String(500), nullable=True)
    display_date = db.Column(db.String(100), nullable=True)
    start_at = db.Column(db.DateTime, nullable=True)
    end_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class DeliveryZone(db.Model):
    __tablename__ = "delivery_zone"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default="기본 구역")
    polygon_json = db.Column(db.Text, nullable=True)
    quick_region_polygon_json = db.Column(db.Text, nullable=True)
    quick_region_names = db.Column(db.Text, nullable=True)
    use_quick_region_only = db.Column(db.Boolean, default=False)
    quick_extra_fee = db.Column(db.Integer, default=10000)
    quick_extra_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class MemberGradeConfig(db.Model):
    __tablename__ = "member_grade_config"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(50), nullable=True)


class PointConfig(db.Model):
    __tablename__ = "point_config"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(50), nullable=True)


# 포인트 유형: accumulated(적립), event(이벤트), cash(캐시충전)
POINT_TYPE_ACCUMULATED = "accumulated"
POINT_TYPE_EVENT = "event"
POINT_TYPE_CASH = "cash"


class PointLog(db.Model):
    __tablename__ = "point_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    point_type = db.Column(db.String(20), default=POINT_TYPE_ACCUMULATED, nullable=True)  # accumulated / event / cash
    order_id = db.Column(db.Integer, nullable=True)
    order_item_id = db.Column(db.Integer, nullable=True)
    memo = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    adjusted_by = db.Column(db.Integer, nullable=True)


class MarketingCost(db.Model):
    __tablename__ = "marketing_cost"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    amount = db.Column(db.Integer, nullable=False)
    memo = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Review(db.Model):
    """사진 리뷰 모델"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, unique=True)
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(50))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    content = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)


class ReviewVote(db.Model):
    """리뷰 추천/비추천 (회원별 1회, 1=추천 -1=비추천)"""
    __tablename__ = "review_vote"
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('review.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    vote = db.Column(db.Integer, nullable=False)  # 1=추천, -1=비추천
    created_at = db.Column(db.DateTime, default=datetime.now)
    __table_args__ = (db.UniqueConstraint('review_id', 'user_id', name='uq_review_vote_review_user'),)


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


class Settlement(db.Model):
    """정산 전용 테이블"""
    __tablename__ = "settlement"
    id = db.Column(db.Integer, primary_key=True)
    settlement_no = db.Column(db.String(32), unique=True, nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)
    order_item_id = db.Column(db.Integer, nullable=True)
    sale_dt = db.Column(db.DateTime, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    category_type = db.Column(db.String(20), default='입점형')
    tax_exempt = db.Column(db.Boolean, default=False)
    product_name = db.Column(db.String(200), nullable=False)
    sales_amount = db.Column(db.Integer, default=0)
    fee = db.Column(db.Integer, default=0)
    delivery_fee = db.Column(db.Integer, default=0)
    settlement_total = db.Column(db.Integer, default=0)
    settlement_status = db.Column(db.String(20), default='입금대기')
    settled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class MarketingAlimtalkLog(db.Model):
    """마케팅 알림톡 발송 로그 (재방문 유도 등, ROAS 검증용)"""
    __tablename__ = "marketing_alimtalk_log"
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    customer_name = db.Column(db.String(50), nullable=True)
    template_code = db.Column(db.String(50), nullable=True)
    coupon_code = db.Column(db.String(50), nullable=True)
    success = db.Column(db.Boolean, default=False)
    memo = db.Column(db.String(500), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.now)
