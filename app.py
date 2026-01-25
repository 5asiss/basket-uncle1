import os
import requests
import base64
from datetime import datetime, timedelta
from io import BytesIO
import re
import random # 최신상품 랜덤 노출을 위해 추가

import pandas as pd
from flask import Flask, render_template_string, request, redirect, url_for, session, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text

# 1. 초기 설정
app = Flask(__name__)
app.secret_key = "basket_uncle_direct_trade_key_999_secure"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 테스트용 API 키 (실제 운영 시 환경변수 권장)
TOSS_CLIENT_KEY = "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# 2. 데이터베이스 모델 설계
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False) 
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))          
    address_detail = db.Column(db.String(200)) 
    entrance_pw = db.Column(db.String(100))    
    request_memo = db.Column(db.String(500))
    is_admin = db.Column(db.Boolean, default=False)
    consent_marketing = db.Column(db.Boolean, default=False)

class Category(db.Model):
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

class Product(db.Model):
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
    is_active = db.Column(db.Boolean, default=True)
    tax_type = db.Column(db.String(20), default='과세') 
    badge = db.Column(db.String(50), default='')

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    product_category = db.Column(db.String(50)) 
    price = db.Column(db.Integer)
    quantity = db.Column(db.Integer, default=1)
    tax_type = db.Column(db.String(20), default='과세')

class Order(db.Model):
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
    order_id = db.Column(db.String(100)) 
    payment_key = db.Column(db.String(200)) 
    delivery_address = db.Column(db.String(500))
    request_memo = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)

class UserConsent(db.Model):
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

def save_uploaded_file(file):
    if file and file.filename != '':
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        new_filename = f"uncle_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        return f"/static/uploads/{new_filename}"
    return None

def check_admin_permission(category_name=None):
    if not current_user.is_authenticated: return False
    if current_user.is_admin: return True 
    if category_name:
        cat = Category.query.filter_by(name=category_name).first()
        if cat and cat.manager_email == current_user.email: return True
    return False

# --- HTML 공통 디자인 ---
HEADER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>바구니삼촌 구매대행 - 배송 서비스의 혁신</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://js.tosspayments.com/v1/payment"></script>
    <script src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8f9fa; color: #333; -webkit-tap-highlight-color: transparent; overflow-x: hidden; }
        .sold-out { filter: grayscale(100%); opacity: 0.6; }
        .sold-out-badge { 
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8); color: white; padding: 10px 20px; 
            border-radius: 8px; font-weight: 800; z-index: 10; border: 2px solid white;
        }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .badge-tag { font-size: 10px; padding: 2px 8px; border-radius: 4px; font-weight: bold; margin-bottom: 4px; display: inline-block; }
        .horizontal-scroll {
            display: flex; overflow-x: auto; scroll-snap-type: x mandatory; 
            gap: 12px; padding-bottom: 15px; -webkit-overflow-scrolling: touch;
        }
        .horizontal-scroll > div { scroll-snap-align: start; flex-shrink: 0; }
        
        #sidebar {
            position: fixed; top: 0; left: -280px; width: 280px; height: 100%;
            background: white; z-index: 1000; transition: 0.3s; box-shadow: 10px 0 30px rgba(0,0,0,0.1);
            overflow-y: auto;
        }
        #sidebar.open { left: 0; }
        #sidebar-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); z-index: 999; display: none;
        }
        #sidebar-overlay.show { display: block; }

        #toast {
            visibility: hidden; min-width: 250px; background-color: #333; color: #fff; text-align: center;
            border-radius: 50px; padding: 16px; position: fixed; z-index: 1000; left: 50%; bottom: 30px;
            transform: translateX(-50%); font-size: 14px; font-weight: bold; transition: 0.5s; opacity: 0;
        }
        #toast.show { visibility: visible; opacity: 1; bottom: 50px; }

        #term-modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:2000; align-items:center; justify-content:center; padding:20px; }
        #term-modal-content { background:white; width:100%; max-width:600px; max-height:80vh; border-radius:2rem; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 20px 50px rgba(0,0,0,0.2); }
        #term-modal-body { overflow-y:auto; padding:2rem; font-size:0.85rem; line-height:1.6; color:#555; }
    </style>
</head>
<body class="text-left font-black">
    <div id="toast">장바구니에 담겼습니다! 🧺</div>
    
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
    <div id="sidebar" class="p-8">
        <div class="flex justify-between items-center mb-10">
            <h3 class="text-xl text-green-600 italic font-black">CATEGORIES</h3>
            <button onclick="toggleSidebar()" class="text-gray-300 text-2xl"><i class="fas fa-times"></i></button>
        </div>
        <nav class="space-y-6 text-sm">
            <a href="/" class="block text-gray-800 hover:text-green-600 transition font-black">전체 상품 리스트</a>
            <div class="h-px bg-gray-100 w-full"></div>
            {% for c in nav_categories %}
            <a href="/category/{{ c.name }}" class="block text-gray-500 hover:text-green-600 transition flex items-center justify-between">
                {{ c.name }} <i class="fas fa-chevron-right text-[10px] opacity-30"></i>
            </a>
            {% endfor %}
            <div class="h-px bg-gray-100 w-full"></div>
            <a href="/about" class="block font-bold text-blue-500 hover:underline">바구니삼촌이란?</a>
            
            {% if current_user.is_authenticated and (current_user.is_admin or current_user.email in managers) %}
            <div class="pt-4">
                <a href="/admin" class="block p-4 bg-orange-50 text-orange-600 rounded-2xl text-center text-xs border border-orange-100">
                    <i class="fas fa-cog mr-2"></i> 관리자 설정
                </a>
            </div>
            {% endif %}
        </nav>
        <div class="mt-20 pt-10 border-t border-gray-50">
            <p class="text-[10px] text-gray-300 uppercase tracking-widest font-black">Customer Center</p>
            <p class="text-sm font-black text-gray-400 mt-2 font-black">1666-8320</p>
        </div>
    </div>

    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4">
            <div class="flex justify-between h-16 items-center">
                <div class="flex items-center gap-4">
                    <button onclick="toggleSidebar()" class="text-gray-400 text-xl hover:text-green-600 transition">
                        <i class="fas fa-bars"></i>
                    </button>
                    <a href="/" class="text-lg font-black text-green-600 flex items-center gap-1">
                        <span>🧺</span> <span class="italic tracking-tighter uppercase hidden sm:block">바구니삼촌</span>
                    </a>
                </div>

                <div class="flex items-center gap-2 md:gap-4 flex-1 justify-end max-sm:max-w-[150px] max-w-sm">
                    <form action="/" method="GET" class="relative hidden md:block flex-1">
                        <input name="q" placeholder="필요한 상품을 검색하세요" class="w-full bg-gray-100 py-2 px-5 rounded-full text-[11px] font-black outline-none focus:ring-2 focus:ring-green-200 transition">
                        <button class="absolute right-4 top-2 text-gray-400"><i class="fas fa-search"></i></button>
                    </form>
                    
                    <button onclick="document.getElementById('mobile-search').classList.toggle('hidden')" class="md:hidden text-gray-400 p-2"><i class="fas fa-search"></i></button>

                    {% if current_user.is_authenticated %}
                        {% if current_user.is_admin or current_user.email in managers %}
                        <a href="/admin" class="hidden sm:block bg-orange-100 text-orange-700 px-3 py-1.5 rounded-full font-black text-[10px] hover:bg-orange-200 transition">관리자</a>
                        {% endif %}
                        
                        <a href="/cart" class="text-gray-400 relative p-2 hover:text-green-600 transition">
                            <i class="fas fa-shopping-cart text-xl"></i>
                            <span id="cart-count-badge" class="absolute top-0 right-0 bg-red-500 text-white text-[9px] rounded-full px-1.5 font-black border-2 border-white">{{ cart_count }}</span>
                        </a>
                        <a href="/mypage" class="text-gray-600 font-black bg-gray-100 px-3 py-1.5 rounded-full text-[10px] hover:bg-gray-200 transition font-black">MY</a>
                    {% else %}
                        <a href="/login" class="text-gray-400 font-black text-[11px] hover:text-green-600 transition">로그인</a>
                    {% endif %}
                </div>
            </div>
            
            <div id="mobile-search" class="hidden md:hidden pb-4">
                <form action="/" method="GET" class="relative">
                    <input name="q" placeholder="상품 검색..." class="w-full bg-gray-100 py-3 px-6 rounded-full text-sm font-bold outline-none border-2 border-green-50">
                    <button class="absolute right-5 top-3.5 text-green-600"><i class="fas fa-search"></i></button>
                </form>
            </div>
        </div>
    </nav>
    <main class="min-h-screen">
"""

FOOTER_HTML = """
    </main>

    <!-- 약관 팝업 모달 -->
    <div id="term-modal">
        <div id="term-modal-content">
            <div class="p-6 border-b flex justify-between items-center bg-gray-50">
                <h3 id="term-title" class="font-black text-gray-800">약관 상세 보기</h3>
                <button onclick="closeUncleModal()" class="text-gray-400 hover:text-red-500 text-2xl"><i class="fas fa-times"></i></button>
            </div>
            <div id="term-modal-body">
                <!-- 내용이 여기에 주입됨 -->
            </div>
            <div class="p-6 border-t bg-gray-50 text-center">
                <button onclick="closeUncleModal()" class="bg-gray-800 text-white px-10 py-3 rounded-full font-black">닫기</button>
            </div>
        </div>
    </div>

    <footer class="bg-gray-800 text-gray-400 py-12 border-t mt-20 text-left">
        <div class="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-10">
            <div>
                <p class="text-green-500 font-black text-2xl italic tracking-tighter mb-4 uppercase">바구니삼촌</p>
                <div class="text-xs space-y-1.5 opacity-80 leading-relaxed font-black">
                    <p>상호: 바구니삼촌 | 성명: 금창권</p>
                    <p>사업장소재지: 인천광역시 연수구 하모니로158, d동3층317호</p>
                    <p>등록번호: 472-93-02262 | 전화번호: 1666-8320</p>
                    <div class="pt-4 flex gap-4 opacity-50 underline">
                        <a href="javascript:void(0)" onclick="openUncleModal('terms')">이용약관</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('privacy')">개인정보처리방침</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('agency')">이용 안내</a>
                    </div>
                </div>
            </div>
            <div class="md:text-right space-y-6">
                <div>
                    <p class="font-bold text-gray-200 text-sm mb-3 font-black">고객센터 및 문의</p>
                    <div class="flex flex-col md:items-end gap-2">
                        <a href="http://pf.kakao.com/_AIuxkn" target="_blank" class="bg-[#FEE500] text-gray-900 px-4 py-2 rounded-xl font-black text-xs flex items-center gap-2 w-fit shadow-lg transition hover:brightness-105">
                            <i class="fas fa-comment"></i> 카카오톡 친구추가
                        </a>
                        <p class="text-xs font-black">평일 09:00 ~ 18:00 (1666-8320)</p>
                    </div>
                </div>
                <p class="text-[10px] opacity-40 mt-10 font-bold uppercase tracking-widest font-black">© 2026 Basket Uncle. All Rights Reserved.</p>
            </div>
        </div>
    </footer>
    <script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            sidebar.classList.toggle('open');
            overlay.classList.toggle('show');
        }

        const UNCLE_TERMS = {
            'terms': {
                'title': '바구니삼촌몰 이용약관',
                'content': `
                    <b>제1조 (목적)</b><br>본 약관은 바구니삼촌몰(이하 “회사”)이 제공하는 구매대행 및 배송대행 서비스의 이용과 관련하여 회사와 이용자의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.<br><br>
                    <b>제2조 (서비스의 성격)</b><br>① 회사는 상품을 직접 판매하지 않습니다.<br>② 회사는 이용자의 요청에 따라 상품을 대신 구매하고 배송하는 서비스를 제공합니다.<br>③ 상품의 가격은 회사가 임의로 정하는 판매가가 아닌, 구매처의 실제 구매 원가를 기준으로 합니다.<br><br>
                    <b>제3조 (가격 구조)</b><br>① 상품 금액: 구매처의 실제 구매 원가<br>② 회사 마진: 없음 (0원)<br>③ 배송비: 카테고리별 정액 배송비 (1,900원)<br>④ 추가 수수료: 없음<br>※ 회사는 가격 구조를 투명하게 공개하며, 별도의 숨겨진 비용을 부과하지 않습니다.`
            },
            'third_party': {
                'title': '개인정보 제3자 제공 동의 (필수)',
                'content': '원활한 주문 처리를 위해 배송지 및 연락처 정보가 구매처와 배송 수행자에게 제공됨을 확인하였습니다.'
            },
            'privacy': {
                'title': '개인정보처리방침',
                'content': '고객님의 정보를 안전하게 보호하고 관련 법령을 준수합니다.'
            },
            'agency': {
                'title': '이용 안내',
                'content': '바구니삼촌은 배송 전문 서비스로, 고객님의 요청에 따라 상품을 대신 구매하고 배송해 드립니다.'
            },
            'e_commerce': {
                'title': '전자상거래 이용자 유의사항',
                'content': '본 서비스는 통신판매중개업이 아닌 구매대행/배송 서비스입니다. 이용자는 전자상거래법에 따른 청약철회 권리를 행사할 수 있으나, 구매대행의 특성상 단순 변심에 의한 반품 시 현지 배송비 및 비용이 발생할 수 있음을 확인합니다.'
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

        // 통합 장바구니 추가 함수 (헤더 정의)
        async function addToCart(productId) {
            try {
                const response = await fetch(`/cart/add/${productId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.redirected) { window.location.href = response.url; return; }
                const result = await response.json();
                if (result.success) {
                    showToast("장바구니에 담겼습니다! 🧺");
                    const badge = document.getElementById('cart-count-badge');
                    if(badge) badge.innerText = result.cart_count;
                    if(window.location.pathname === '/cart') location.reload();
                } else { 
                    showToast(result.message || "추가 실패");
                }
            } catch (error) { 
                console.error('Error:', error); 
                showToast("오류가 발생했습니다.");
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
                if(!timer.dataset.deadline) { timer.innerText = "📅 상시"; return; }
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
            new daum.Postcode({
                oncomplete: function(data) {
                    document.getElementById('address').value = data.address;
                    document.getElementById('address_detail').focus();
                }
            }).open();
        }
    </script>
</body>
</html>
"""

# --- 라우팅 ---

@app.context_processor
def inject_globals():
    cart_count = 0
    if current_user.is_authenticated:
        total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar()
        cart_count = total_qty if total_qty else 0
    # 노출 순서에 따른 카테고리 로드
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    managers = [c.manager_email for c in categories if c.manager_email]
    return dict(cart_count=cart_count, now=datetime.now(), managers=managers, nav_categories=categories)

@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    grouped_products = {}
    
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    
    # [특수 카테고리 1] 최신상품 랜덤 추출 (최근 등록된 20개 중 8개 무작위 선택)
    latest_all = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).limit(20).all()
    random_latest = random.sample(latest_all, min(len(latest_all), 8)) if latest_all else []
    
    # [특수 카테고리 2] 오늘마감 (오늘 23:59 이전에 마감되는 상품)
    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    closing_today = Product.query.filter(
        Product.is_active == True,
        Product.deadline > datetime.now(),
        Product.deadline <= today_end
    ).order_by(Product.deadline.asc()).all()

    for cat in categories:
        q_obj = Product.query.filter_by(category=cat.name, is_active=True)
        if query: q_obj = q_obj.filter(Product.name.contains(query))
        products = q_obj.order_by(order_logic, Product.id.desc(), Product.deadline.asc()).all()
        if products: grouped_products[cat] = products
    
    content = """
    <div class="bg-gray-900 text-white py-20 md:py-32 px-4 shadow-inner relative overflow-hidden text-center">
        <div class="max-w-7xl mx-auto relative z-10 font-black">
            <span class="text-green-400 text-[10px] md:text-sm font-black mb-6 inline-block uppercase tracking-[0.3em]">Direct Delivery Service</span>
            <h2 class="text-2xl md:text-7xl font-black mb-8 leading-tight tracking-tighter">
                우리는 상품을 판매하지 않습니다.<br>
                <span class="text-green-500 uppercase">Premium Service</span>
            </h2>
            <div class="w-12 h-1 bg-white/20 mx-auto mb-8"></div>
            <p class="text-gray-400 text-sm md:text-2xl font-bold max-w-2xl mx-auto mb-12">
                판매가 아닌 <span class="text-white underline decoration-green-500 decoration-4 underline-offset-8">배송 서비스</span> 입니다.
            </p>
            <div class="flex flex-col md:flex-row justify-center items-center gap-6">
                <a href="#products" class="bg-green-600 text-white px-10 py-4 md:px-12 md:py-5 rounded-full font-black shadow-2xl hover:bg-green-700 transition active:scale-95 text-base md:text-lg">쇼핑하러 가기</a>
                <a href="/about" class="text-white/60 hover:text-white font-bold border-b border-white/20 pb-1 transition text-xs md:text-base">바구니삼촌이란? <i class="fas fa-arrow-right ml-2"></i></a>
            </div>
        </div>
        <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/dark-matter.png')] opacity-30"></div>
    </div>

    <div id="products" class="max-w-7xl mx-auto px-4 py-16">
        {% if query %}
            <p class="mb-10 font-black text-gray-400 text-lg md:text-xl border-b pb-4">
                <span class="text-green-600">"{{ query }}"</span>에 대한 상품 검색 결과입니다.
            </p>
        {% endif %}

        <!-- [특수 섹션 1] ✨ 최신 상품 -->
        {% if random_latest and not query %}
        <section class="mb-20">
            <div class="mb-10 flex justify-between items-end border-b border-gray-100 pb-4">
                <div>
                    <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                        <span class="w-1.5 h-8 bg-blue-500 rounded-full"></span> ✨ 최신 상품
                    </h2>
                </div>
                <a href="/category/최신상품" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar">
                {% for p in random_latest %}
                <div class="product-card bg-white rounded-2xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] transition-all hover:shadow-2xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1 md:p-4" onerror="this.src='https://placehold.co/400x400?text={{ p.name }}'">
                        <div class="absolute top-2 left-2 md:top-4 md:left-4"><span class="bg-blue-500 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg uppercase">NEW</span></div>
                    </a>
                    <div class="p-2 md:p-6 flex flex-col flex-1">
                        <h3 class="font-black text-gray-800 text-[10px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[8px] md:text-[11px] text-green-600 mb-1 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[12px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-7 h-7 md:w-12 md:h-12 rounded-lg md:rounded-2xl text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-base"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}

        <!-- [특수 섹션 2] 🔥 오늘 마감 상품 -->
        {% if closing_today and not query %}
        <section class="mb-20">
            <div class="mb-10 flex justify-between items-end border-b border-gray-100 pb-4">
                <div>
                    <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                        <span class="w-1.5 h-8 bg-red-500 rounded-full"></span> 🔥 오늘 마감 임박!
                    </h2>
                </div>
                <a href="/category/오늘마감" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar">
                {% for p in closing_today %}
                <div class="product-card bg-white rounded-2xl md:rounded-[3rem] shadow-sm border border-red-50 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] transition-all hover:shadow-2xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1 md:p-4">
                        <div class="absolute bottom-2 left-2 md:bottom-4 md:left-4"><span class="bg-red-600 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg font-black animate-pulse">오늘마감</span></div>
                    </a>
                    <div class="p-2 md:p-6 flex flex-col flex-1">
                        <p class="countdown-timer text-[7px] md:text-[9px] font-bold text-red-500 mb-1" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[10px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[8px] md:text-[11px] text-green-600 mb-1 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[12px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-7 h-7 md:w-12 md:h-12 rounded-lg md:rounded-2xl text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-base"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}
        
        <!-- [일반 카테고리 리스트] -->
        {% for cat, products in grouped_products.items() %}
        <section class="mb-20">
            <div class="mb-10 flex justify-between items-end border-b border-gray-100 pb-4">
                <div>
                    <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                        <span class="w-1.5 h-8 bg-green-500 rounded-full"></span> {{ cat.name }} 리스트
                    </h2>
                    {% if cat.description %}<p class="text-[10px] text-gray-400 mt-2 font-bold">{{ cat.description }}</p>{% endif %}
                </div>
                <a href="/category/{{ cat.name }}" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-2xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[8px] md:text-xs">판매마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1 md:p-4">
                        <div class="absolute bottom-2 left-2 md:bottom-4 md:left-4"><span class="bg-black/70 text-white text-[7px] md:text-[10px] px-1 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg font-black">잔여: {{ p.stock }}</span></div>
                    </a>
                    <div class="p-2 md:p-6 flex flex-col flex-1">
                        <p class="countdown-timer text-[7px] md:text-[9px] font-bold text-red-500 mb-1" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[10px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[8px] md:text-[11px] text-green-600 mb-1 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[12px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-7 h-7 md:w-12 md:h-12 rounded-2xl text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-base"></i></button>{% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
                <div class="w-4 md:w-8 flex-shrink-0"></div>
            </div>
        </section>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products, random_latest=random_latest, closing_today=closing_today)

@app.route('/about')
def about_page():
    content = """
    <div class="bg-white py-20 px-6 font-black">
        <div class="max-w-4xl mx-auto">
            <nav class="mb-10 text-left"><a href="/" class="text-green-600 font-black text-sm md:text-base"><i class="fas fa-arrow-left mr-2"></i> 홈으로 돌아가기</a></nav>
            
            <!-- 섹션 1: 가치 안내 -->
            <section class="mb-20 text-left">
                <h2 class="text-3xl md:text-5xl font-black text-gray-800 mb-8 tracking-tighter leading-tight uppercase italic">바구니 삼촌</h2>
                <div class="space-y-6 text-gray-600 text-base md:text-lg leading-loose">
                    <p>바구니 삼촌은 외부 플랫폼에 의존하지 않고 직접 개발한 시스템으로 운영되어 수수료·중개비 등 불필요한 운영 비용을 최소화한 지역 기반 물류 서비스입니다.</p>
                    <p>송도 지역에 자체 배송 인력과 인프라를 직접 보유하고 있으며, 효율적인 로직을 적용해 배송비 부담을 구조적으로 낮췄습니다.</p>
                </div>
                <div class="mt-10 p-6 md:p-10 bg-green-50 rounded-[2.5rem] md:rounded-[3rem] border border-green-100 shadow-inner">
                    <p class="text-green-800 font-black text-xl md:text-2xl mb-6 italic">또한 판매자에게는</p>
                    <div class="space-y-4">
                        <p class="text-2xl md:text-3xl font-black text-gray-800 flex items-center gap-3">
                            <span class="w-2.5 h-2.5 bg-green-600 rounded-full"></span> 중개 수수료 <span class="text-green-600 underline decoration-4 underline-offset-4 font-black">0원</span>
                        </p>
                        <p class="text-2xl md:text-3xl font-black text-gray-800 flex items-center gap-3">
                            <span class="w-2.5 h-2.5 bg-green-600 rounded-full"></span> 플랫폼 사용료 <span class="text-green-600 underline decoration-4 underline-offset-4 font-black">0원</span>
                        </p>
                    </div>
                    <p class="mt-8 text-gray-500 font-bold text-sm md:text-base leading-relaxed">을 적용하여 유통 단계에서 발생하는 비용을 최소 수준으로 설계하였습니다.</p>
                </div>
                <p class="mt-12 text-gray-800 font-black text-lg md:text-xl leading-relaxed text-left border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6">
                    바구니 삼촌은 이렇게 절감된 비용을 모두 소비자에게 직접 환원하는 구조를 지향합니다.
                </p>
            </section>

            <!-- 섹션 2: 송도 최적화 모델 -->
            <section class="mb-20 bg-gray-900 p-8 md:p-20 rounded-[2.5rem] md:rounded-[4rem] text-white text-left relative overflow-hidden shadow-2xl">
                <div class="relative z-10">
                    <h3 class="text-3xl md:text-5xl font-black mb-12 tracking-tighter uppercase italic text-green-400">송도에 맞는 이유</h3>
                    <ul class="space-y-6 md:space-y-8 text-lg md:text-2xl font-bold opacity-90">
                        <li class="flex items-start gap-4 md:gap-5">
                            <span class="text-green-500 mt-1"><i class="fas fa-check-circle"></i></span>
                            <span>송도 생활권 중심의 근거리 배송 구조</span>
                        </li>
                        <li class="flex items-start gap-4 md:gap-5">
                            <span class="text-green-500 mt-1"><i class="fas fa-check-circle"></i></span>
                            <span>대단지·오피스텔 밀집 환경에 최적화된 운영</span>
                        </li>
                        <li class="flex items-start gap-4 md:gap-5">
                            <span class="text-green-500 mt-1"><i class="fas fa-check-circle"></i></span>
                            <span>자체 물류 시스템 운영</span>
                        </li>
                        <li class="flex items-start gap-4 md:gap-5">
                            <span class="text-green-500 mt-1"><i class="fas fa-check-circle"></i></span>
                            <span>관리사무소 운영 부담 없는 협업 구조</span>
                        </li>
                    </ul>
                    <div class="mt-16 pt-12 border-t border-white/10">
                        <p class="text-xl md:text-4xl font-black tracking-tight text-green-400 italic leading-tight">
                            송도에서 시작한,<br>송도에 가장 적합한 생활 물류 모델입니다.
                        </p>
                    </div>
                </div>
                <div class="absolute -right-20 -bottom-20 w-80 h-80 bg-green-500/10 rounded-full blur-3xl"></div>
            </section>

            <!-- 섹션 3: 동네 물류 선언 -->
            <section class="text-center md:text-left">
                <h3 class="text-2xl md:text-4xl font-black text-gray-800 mb-8 tracking-tighter leading-tight italic">바구니 삼촌은 송도에서 시작한 동네 물류입니다</h3>
                <div class="space-y-8 text-gray-500 text-base md:text-lg leading-relaxed">
                    <p>바구니 삼촌은 송도에서 직접 운영되는 지역 기반 배송 서비스입니다. 송도 생활 패턴과 동선에 맞춰 불필요한 비용을 줄이고 합리적으로 전달합니다.</p>
                    <div class="p-6 md:p-10 bg-orange-50 rounded-[2rem] md:rounded-[3rem] border border-orange-100 shadow-sm">
                        <p class="text-gray-900 font-black text-lg md:text-2xl leading-relaxed">
                            농산물·식자재·생활필수품을 원가 기준으로 대신 구매하고,<br>
                            카테고리별 배송료 <span class="text-orange-600 underline decoration-4 underline-offset-4">1,900원</span>으로 송도 전 지역에 배송합니다.
                        </p>
                    </div>
                </div>
            </section>

            <div class="mt-20 text-center">
                <a href="/" class="inline-block bg-green-600 text-white px-16 py-5 md:px-20 md:py-6 rounded-full font-black text-xl md:text-2xl shadow-2xl hover:bg-green-700 transition active:scale-95">쇼핑하러 가기</a>
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/category/<string:cat_name>')
def category_view(cat_name):
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    cat = None
    if cat_name == '최신상품':
        products = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).all()
        display_name = "✨ 최신 상품"
    elif cat_name == '오늘마감':
        today_end = datetime.now().replace(hour=23, minute=59, second=59)
        products = Product.query.filter(Product.is_active == True, Product.deadline > datetime.now(), Product.deadline <= today_end).order_by(Product.deadline.asc()).all()
        display_name = "🔥 오늘 마감 임박!"
    else:
        cat = Category.query.filter_by(name=cat_name).first_or_404()
        products = Product.query.filter_by(category=cat_name, is_active=True).order_by(order_logic, Product.id.desc(), Product.deadline.asc()).all()
        display_name = f"{cat_name} 상품 리스트"

    content = """
    <div class="max-w-7xl mx-auto px-4 py-16">
        <h2 class="text-2xl md:text-4xl text-gray-800 mb-4 font-black">{{ display_name }}</h2>
        {% if cat and cat.description %}<p class="text-gray-400 font-bold mb-10 text-sm md:text-lg">{{ cat.description }}</p>{% endif %}
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-6">
            {% for p in products %}
            {% set is_expired = (p.deadline and p.deadline < now) %}
            <div class="product-card bg-white rounded-[1.5rem] md:rounded-[2.5rem] shadow-sm border border-gray-100 overflow-hidden flex flex-col transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[8px] md:text-[10px]">판매마감</div>{% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                    <img src="{{ p.image_url }}" class="w-full h-full object-contain p-2 md:p-4">
                    <div class="absolute bottom-2 left-2 md:bottom-3 md:left-3"><span class="bg-black/70 text-white text-[7px] md:text-[9px] px-1.5 py-0.5 md:px-2 md:py-1 rounded md:rounded-md font-black backdrop-blur-sm">잔여: {{ p.stock }}</span></div>
                </a>
                <div class="p-3 md:p-6 flex flex-col flex-1">
                    <p class="countdown-timer text-[7px] md:text-[8px] font-bold text-red-500 mb-1" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                    <h3 class="font-black text-gray-800 text-[11px] md:text-sm truncate mb-0.5 md:mb-1 leading-tight">{{ p.name }}</h3>
                    <p class="text-[9px] md:text-[10px] text-green-600 mb-1 md:mb-2 font-medium truncate">{{ p.description or '' }}</p>
                    <div class="mt-auto flex justify-between items-center">
                        <span class="text-sm md:text-lg font-black text-green-600">{{ "{:,}".format(p.price) }}원</span>
                        {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-6 h-6 md:w-8 md:h-8 rounded-full text-white shadow-lg active:scale-90 transition-transform"><i class="fas fa-plus text-[8px] md:text-xs"></i></button>{% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, display_name=display_name, cat=cat)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    detail_images = p.detail_image_url.split(',') if p.detail_image_url else []
    cat_info = Category.query.filter_by(name=p.category).first()
    
    # [신규] 추천 상품 로직: 현재 상품명의 키워드 기반 검색
    keyword = p.name.split()[0] if p.name else ""
    keyword_recommends = Product.query.filter(
        Product.name.contains(keyword),
        Product.id != pid,
        Product.is_active == True,
        Product.stock > 0
    ).limit(5).all()

    # [기존] 최신 상품 5개 랜덤 노출
    latest_all = Product.query.filter(Product.is_active == True, Product.id != pid).order_by(Product.id.desc()).limit(20).all()
    random_recommends = random.sample(latest_all, min(len(latest_all), 5)) if latest_all else []

    content = """
    <div class="max-w-4xl mx-auto px-4 py-16 font-black">
        <div class="grid md:grid-cols-2 gap-8 md:gap-10 mb-20">
            <img src="{{ p.image_url }}" class="w-full aspect-square object-contain border rounded-[2rem] md:rounded-[3rem] bg-white p-4 md:p-8">
            <div class="flex flex-col justify-center">
                <div class="flex flex-wrap items-center gap-2 mb-4">
                    <span class="bg-green-50 text-green-600 px-4 py-1 rounded-full text-[10px] md:text-[11px] w-fit font-black">{{ p.category }}</span>
                    {% if cat_info and cat_info.description %}
                    <span class="text-gray-400 text-[10px] font-bold">| {{ cat_info.description }}</span>
                    {% endif %}
                </div>
                <h2 class="text-2xl md:text-5xl text-gray-800 mb-4 leading-tight tracking-tighter">{{ p.name }}</h2>
                <p class="text-green-600 text-base md:text-lg mb-4 font-bold">{{ p.description or '' }}</p>
                <div class="space-y-2 mb-8 text-[10px] md:text-xs text-gray-400">
                    <p class="text-blue-500 font-bold"><i class="fas fa-warehouse mr-2"></i> 잔여수량: {{ p.stock }}개</p>
                    <p class="countdown-timer text-red-500 font-bold" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                </div>
                <div class="bg-gray-50 p-6 md:p-8 rounded-[1.5rem] md:rounded-[2.5rem] mb-10 border border-gray-100 text-3xl md:text-6xl font-black text-green-600">{{ "{:,}".format(p.price) }}원</div>
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-5 md:py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-lg md:text-xl shadow-2xl active:scale-95 transition-transform mb-4">장바구니 담기</button>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-5 md:py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-lg md:text-xl cursor-not-allowed italic mb-4">판매마감</button>
                {% endif %}
                
                <div class="grid grid-cols-2 gap-3">
                    <a href="/category/{{ p.category }}" class="bg-white border-2 border-green-600 text-green-600 py-3 rounded-xl text-center text-xs font-black hover:bg-green-50 transition">판매자 상품 전체보기</a>
                    <a href="/category/최신상품" class="bg-gray-800 text-white py-3 rounded-xl text-center text-xs font-black hover:bg-gray-700 transition">최신 상품 전체보기</a>
                </div>
            </div>
        </div>
        
        <div class="border-t pt-16">
            <h3 class="font-black text-xl md:text-2xl mb-12 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 text-gray-800">상세 정보</h3>
            <div class="flex flex-col gap-6 bg-white p-2 md:p-4 rounded-2xl md:rounded-3xl border">
                {% for img in detail_images %}<img src="{{ img }}" class="w-full rounded-xl md:rounded-2xl shadow-sm">{% endfor %}
            </div>
            
            <div class="mt-12 p-6 md:p-10 bg-gray-50 rounded-[1.5rem] md:rounded-[2.5rem] text-[9px] md:text-[10px] text-gray-400 leading-relaxed border border-gray-100 font-black">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-8 md:gap-10 text-left">
                    <div>
                        <h4 class="text-gray-700 mb-4 border-b pb-1 font-black text-[11px] uppercase tracking-widest">배송정보</h4>
                        <p class="mb-1"><span class="inline-block w-16 md:w-20 font-black">배송방법</span>신선/냉장/냉동</p>
                        <p class="mb-1"><span class="inline-block w-16 md:w-20 font-black text-orange-500">배송비</span>카테고리별 1,900원(5만원 초과시 1,900원 추가)</p>
                        <p class="mb-1"><span class="inline-block w-16 md:w-20 font-black">묶음배송</span>가능</p>
                    </div>
                    <div>
                        <h4 class="text-gray-700 mb-4 border-b pb-1 font-black text-[11px] uppercase tracking-widest">교환/반품안내</h4>
                        <p class="mb-1"><span class="inline-block w-16 md:w-20 font-black">비용</span>상품에 따라 다름</p>
                        <p class="mb-4"><span class="inline-block w-16 md:w-20 font-black">방법</span>전화 문의 후 상태 설정</p>
                        <div class="mt-4 border-t pt-4">
                            <p class="text-gray-700 font-black mb-2 text-[11px]">교환/반품 제한사항</p>
                            <ul class="list-disc pl-5 space-y-1 opacity-80 font-bold">
                                <li>주문/제작 상품의 경우, 상품의 제작이 이미 진행된 경우</li>
                                <li>상품 포장을 개봉하여 사용 또는 설치 완료되어 상품의 가치가 훼손된 경우</li>
                                <li>고객의 사용, 시간경과, 일부 소비에 의하여 상품의 가치가 현저히 감소한 경우</li>
                                <li>세트상품 일부 사용, 구성품을 분실하였거나 취급 부주의로 인한 파손/고장/오염</li>
                                <li>모니터 해상도의 차이로 인해 색상이나 이미지가 실제와 달라 변심 무료 반품 요청 시</li>
                                <li>제조사의 사정 및 부품 가격 변동 등에 의해 무료 교환/반품으로 요청하는 경우</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- [신규] 추천 상품 (키워드 기반) -->
        {% if keyword_recommends %}
        <div class="mt-20 border-t pt-16">
            <h3 class="font-black text-xl md:text-2xl mb-10 flex items-center gap-3 tracking-tighter">⭐ 연관 추천 상품</h3>
            <div class="grid grid-cols-2 sm:grid-cols-5 gap-4">
                {% for rp in keyword_recommends %}
                <a href="/product/{{rp.id}}" class="group">
                    <div class="bg-white rounded-2xl border border-gray-100 p-2 overflow-hidden shadow-sm transition group-hover:shadow-md">
                        <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-3 rounded-xl bg-gray-50">
                        <p class="text-[10px] md:text-[11px] font-black text-gray-800 truncate">{{ rp.name }}</p>
                        <p class="text-[10px] md:text-[12px] font-black text-green-600 mt-1">{{ "{:,}".format(rp.price) }}원</p>
                    </div>
                </a>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <!-- [기존] 최신 상품 5개 랜덤 노출 -->
        <div class="mt-10 border-t pt-16">
            <h3 class="font-black text-xl md:text-2xl mb-10 flex items-center gap-3 tracking-tighter">✨ 최신 상품</h3>
            <div class="grid grid-cols-2 sm:grid-cols-5 gap-4">
                {% for rp in random_recommends %}
                <a href="/product/{{rp.id}}" class="group">
                    <div class="bg-white rounded-2xl border border-gray-100 p-2 overflow-hidden shadow-sm transition group-hover:shadow-md">
                        <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-3 rounded-xl bg-gray-50">
                        <p class="text-[10px] md:text-[11px] font-black text-gray-800 truncate">{{ rp.name }}</p>
                        <p class="text-[10px] md:text-[12px] font-black text-green-600 mt-1">{{ "{:,}".format(rp.price) }}원</p>
                    </div>
                </a>
                {% endfor %}
            </div>
        </div>

        {% if cat_info and cat_info.biz_name %}
        <div class="mt-20 border-t pt-16">
            <div class="bg-gray-50 p-8 md:p-12 rounded-[2rem] md:rounded-[3.5rem] border border-gray-100 shadow-sm">
                <div class="flex items-center gap-4 mb-8 text-left">
                    <div class="w-10 h-10 md:w-12 md:h-12 bg-green-600 text-white rounded-full flex items-center justify-center text-base md:text-lg shadow-lg"><i class="fas fa-info"></i></div>
                    <h4 class="text-xl md:text-2xl font-black text-gray-800">서비스 이용 안내</h4>
                </div>
                <p class="text-gray-500 leading-relaxed mb-10 font-bold text-sm md:text-lg text-left">본 상품은 바구니삼촌이 고객님의 요청에 따라 구매를 대행하는 상품입니다. 실제 판매자 정보는 아래 버튼을 통해 확인 및 문의 가능합니다.</p>
                
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
                    <a href="/category/seller/{{ cat_info.id }}" class="bg-white border-2 border-gray-200 text-gray-800 px-6 py-4 md:px-8 md:py-5 rounded-[1.2rem] md:rounded-[1.5rem] font-black text-xs md:text-sm hover:bg-gray-100 transition shadow-sm flex items-center justify-center gap-3">
                        <i class="fas fa-address-card text-lg text-gray-400"></i> 사업자정보보기
                    </a>
                    
                    {% if cat_info.biz_contact %}
                    <a href="tel:{{ cat_info.biz_contact }}" class="bg-white border-2 border-blue-100 text-blue-600 px-6 py-4 md:px-8 md:py-5 rounded-[1.2rem] md:rounded-[1.5rem] font-black text-xs md:text-sm hover:bg-blue-50 transition shadow-sm flex items-center justify-center gap-3">
                        <i class="fas fa-phone-alt text-lg"></i> 고객센터 연결
                    </a>
                    {% endif %}

                    {% if cat_info.seller_inquiry_link %}
                    <a href="{{ cat_info.seller_inquiry_link }}" target="_blank" class="bg-green-600 text-white px-6 py-4 md:px-8 md:py-5 rounded-[1.2rem] md:rounded-[1.5rem] font-black text-xs md:text-sm hover:bg-green-700 transition shadow-lg flex items-center justify-center gap-3">
                        <i class="fas fa-comment-dots text-lg"></i> 판매자 문의
                    </a>
                    {% endif %}
                </div>
                
                <p class="mt-10 text-[10px] md:text-xs text-gray-400 font-bold italic text-left">※ 본 상품은 바구니삼촌 송도 전용 상품입니다.</p>
            </div>
        </div>
        {% endif %}
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, detail_images=detail_images, cat_info=cat_info, random_recommends=random_recommends, keyword_recommends=keyword_recommends)

@app.route('/category/seller/<int:cid>')
def seller_info_page(cid):
    cat = Category.query.get_or_404(cid)
    content = """
    <div class="max-w-xl mx-auto py-20 px-6 font-black text-sm md:text-base">
        <nav class="mb-10"><a href="javascript:history.back()" class="text-green-600 font-black hover:underline"><i class="fas fa-arrow-left mr-2"></i> 이전으로 돌아가기</a></nav>
        <div class="bg-white rounded-[2.5rem] md:rounded-[4rem] shadow-2xl border border-gray-100 overflow-hidden">
            <div class="bg-green-600 p-8 md:p-12 text-white text-center">
                <div class="w-16 h-16 md:w-20 md:h-20 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-6 text-2xl md:text-3xl"><i class="fas fa-store"></i></div>
                <h2 class="text-2xl md:text-3xl font-black tracking-tight mb-2 italic uppercase">Business Info</h2>
                <p class="opacity-80 font-bold text-xs md:text-base">본 상품의 실제 판매 사업자 정보입니다.</p>
            </div>
            
            <div class="p-8 md:p-12 space-y-8 md:space-y-10 text-left">
                <div><p class="text-[10px] text-gray-400 uppercase tracking-[0.2em] mb-2 font-black">Company Name</p><p class="text-xl md:text-2xl text-gray-800 font-black">상호명 : {{ cat.biz_name }}</p></div>
                <div class="grid grid-cols-2 gap-6 md:gap-8">
                    <div><p class="text-[10px] text-gray-400 uppercase tracking-[0.2em] mb-2 font-black">Representative</p><p class="text-gray-800 font-black text-base md:text-lg">대표자 : {{ cat.biz_representative }}</p></div>
                    <div><p class="text-[10px] text-gray-400 uppercase tracking-[0.2em] mb-2 font-black">Tax Number</p><p class="text-gray-800 font-black text-base md:text-lg">{{ cat.biz_reg_number }}</p></div>
                </div>
                <div><p class="text-[10px] text-gray-400 uppercase tracking-[0.2em] mb-2 font-black">Location</p><p class="text-gray-700 font-bold leading-relaxed text-sm md:text-base">{{ cat.biz_address }}</p></div>
                <div class="p-6 md:p-8 bg-gray-50 rounded-[1.5rem] md:rounded-[2.5rem] border border-dashed border-gray-200"><p class="text-[10px] text-gray-400 uppercase tracking-[0.2em] mb-2 font-black">Inquiry Center</p><p class="text-green-600 text-xl md:text-2xl font-black italic">{{ cat.biz_contact }}</p></div>
            </div>
            
            <div class="bg-gray-50 p-6 text-center border-t text-[10px] text-gray-400 font-black uppercase tracking-widest">
                Basket Uncle Service
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, cat=cat)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user); return redirect('/')
        flash("로그인 정보를 다시 확인해주세요.")
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-20 p-8 md:p-12 bg-white rounded-[2.5rem] md:rounded-[4rem] shadow-2xl border">
        <h2 class="text-2xl md:text-3xl font-black text-center mb-12 text-green-600 uppercase italic tracking-tighter">Login</h2>
        <form method="POST" class="space-y-6">
            <input name="email" type="email" placeholder="이메일 주소" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black focus:ring-2 focus:ring-green-100 outline-none text-sm md:text-base" required>
            <input name="password" type="password" placeholder="비밀번호" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black focus:ring-2 focus:ring-green-100 outline-none text-sm md:text-base" required>
            <button class="w-full bg-green-600 text-white py-5 md:py-6 rounded-2xl font-black text-lg md:text-xl shadow-xl hover:bg-green-700 transition">로그인</button>
        </form>
        <div class="text-center mt-8"><a href="/register" class="text-gray-400 text-[10px] md:text-xs font-black hover:text-green-600">아직 회원이 아니신가요? 회원가입</a></div>
    </div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        
        # [수정] 필수 동의 체크 확인
        if not request.form.get('consent_e_commerce'):
            flash("전자상거래 이용 약관에 동의해야 합니다."); return redirect('/register')

        if User.query.filter_by(email=email).first(): flash("이미 존재하는 계정입니다."); return redirect('/register')
        new_user = User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo)
        db.session.add(new_user); db.session.commit(); return redirect('/login')
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-10 p-8 md:p-10 bg-white rounded-[2rem] md:rounded-[3.5rem] shadow-2xl border">
        <h2 class="text-xl md:text-2xl font-black mb-10 tracking-tighter uppercase italic text-green-600">Join Us</h2>
        <form method="POST" class="space-y-4">
            <input name="name" placeholder="실명 성함" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required>
            <input name="email" type="email" placeholder="이메일(ID)" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required>
            <input name="password" type="password" placeholder="비밀번호" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required>
            <input name="phone" placeholder="휴대폰 번호" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required>
            <div class="flex gap-2"><input id="address" name="address" placeholder="주소" class="flex-1 p-4 md:p-5 bg-gray-100 rounded-2xl font-black text-sm md:text-base" readonly onclick="execDaumPostcode()"><button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-4 md:px-5 rounded-2xl font-black text-xs">검색</button></div>
            <input name="address_detail" placeholder="상세주소 (동/호수)" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required>
            <input name="entrance_pw" placeholder="공동현관 비번 (필수)" class="w-full p-4 md:p-5 bg-red-50 rounded-2xl font-black border border-red-100 text-sm md:text-base" required>
            <textarea name="request_memo" placeholder="배송 요청사항" class="w-full p-4 md:p-5 bg-white border border-gray-100 rounded-2xl font-black h-24 text-sm md:text-base"></textarea>
            
            <div class="p-4 bg-gray-50 rounded-2xl border border-gray-100 text-[10px] space-y-2 mt-4">
                <label class="flex items-start gap-2 cursor-pointer group">
                    <input type="checkbox" name="consent_e_commerce" class="mt-0.5 w-3 h-3 rounded-full border-gray-300 text-green-600 focus:ring-green-500" required>
                    <span class="group-hover:text-gray-800 transition leading-tight">[필수] <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="underline decoration-green-300">전자상거래 이용자 유의사항</a> 및 서비스 이용에 동의합니다.</span>
                </label>
            </div>

            <button class="w-full bg-green-600 text-white py-5 md:py-6 rounded-2xl font-black text-lg md:text-xl shadow-xl mt-6 hover:bg-green-700 transition">가입 완료</button>
        </form>
    </div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """
    <div class="max-w-4xl mx-auto py-12 px-4 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-12 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 tracking-tighter uppercase italic">My Center</h2>
        <div class="bg-white p-8 md:p-12 rounded-[2rem] md:rounded-[4rem] shadow-xl border mb-12 relative overflow-hidden">
            <div class="relative z-10">
                <p class="text-2xl md:text-3xl font-black mb-2 text-gray-800">{{ current_user.name }} 고객님</p>
                <p class="text-gray-400 font-bold mb-10 text-xs md:text-sm">{{ current_user.email }}</p>
                <div class="grid md:grid-cols-2 gap-8 md:gap-10 pt-10 border-t border-gray-50">
                    <div><p class="text-[9px] md:text-[10px] text-gray-400 uppercase tracking-widest mb-3 font-black">Shipping Address</p><p class="text-gray-700 font-bold text-base md:text-lg leading-relaxed">{{ current_user.address }}<br>{{ current_user.address_detail }}</p></div>
                    <div><p class="text-[9px] md:text-[10px] text-gray-400 uppercase tracking-widest mb-3 font-black">Gate Access</p><p class="text-red-500 font-black text-lg md:text-xl">🔑 {{ current_user.entrance_pw }}</p></div>
                </div>
            </div>
            <a href="/logout" class="absolute top-6 right-6 md:top-10 md:right-10 text-[9px] md:text-[10px] bg-gray-100 px-3 py-1.5 rounded-full text-gray-400 font-black hover:bg-gray-200 transition">LOGOUT</a>
        </div>
        <h3 class="text-xl md:text-2xl font-black mb-8 flex items-center gap-3 italic"><i class="fas fa-truck text-green-600"></i> History</h3>
        <div class="space-y-6">
            {% if orders %}
                {% for o in orders %}
                <div class="bg-white p-6 md:p-10 rounded-[2rem] md:rounded-[3rem] shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
                    <p class="text-[9px] md:text-[10px] text-gray-300 font-black mb-4 uppercase tracking-widest">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                    <p class="font-black text-gray-800 text-lg md:text-xl leading-tight mb-6">{{ o.product_details }}</p>
                    <div class="flex justify-between items-center pt-6 border-t border-gray-50 font-black">
                        <span class="text-gray-400 text-[10px] md:text-xs">Total Payment</span>
                        <span class="text-xl md:text-2xl text-green-600 italic">{{ "{:,}".format(o.total_price) }}원</span>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="bg-white py-32 text-center text-gray-300 rounded-[2.5rem] md:rounded-[4rem] border border-dashed font-black text-sm md:text-base">이용 내역이 없습니다.</div>
            {% endif %}
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, orders=orders)

@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get_or_404(pid)
    if (p.deadline and p.deadline < datetime.now()) or p.stock <= 0: return jsonify({"success": False, "message": "마감된 상품입니다."})
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, product_category=p.category, price=p.price, tax_type=p.tax_type))
    db.session.commit()
    total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar() or 0
    return jsonify({"success": True, "cart_count": total_qty})

@app.route('/cart/minus/<int:pid>', methods=['POST'])
@login_required
def minus_cart(pid):
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
    Cart.query.filter_by(user_id=current_user.id, product_id=pid).delete()
    db.session.commit()
    return redirect('/cart')

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    
    # [수정] 배송비 계산 로직 변경: 카테고리별 합계 금액 기반
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()]) if items else 0
    
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    content = """
    <div class="max-w-4xl mx-auto py-16 px-6 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-12 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 tracking-tighter uppercase italic">Shopping Basket</h2>
        <div class="bg-white rounded-[2rem] md:rounded-[4rem] shadow-2xl border overflow-hidden">
            {% if items %}
            <div class="p-6 md:p-10 space-y-8">
                {% for i in items %}
                <div class="flex justify-between items-center border-b border-gray-50 pb-8 last:border-0 last:pb-0">
                    <div class="flex-1 mr-4">
                        <p class="font-black text-base md:text-xl text-gray-800 leading-tight">{{ i.product_name }}</p>
                        <p class="text-green-600 font-black text-xs md:text-sm mt-1 italic">{{ "{:,}".format(i.price) }}원</p>
                    </div>
                    <div class="flex items-center gap-3 md:gap-6 bg-gray-100 px-4 py-2 md:px-6 md:py-3 rounded-xl md:rounded-2xl">
                        <button onclick="minusFromCart('{{i.product_id}}')" class="text-gray-400 font-black text-xl md:text-2xl hover:text-red-500 transition">-</button>
                        <span class="font-black text-base md:text-xl w-6 md:w-8 text-center">{{ i.quantity }}</span>
                        <button onclick="addToCart('{{i.product_id}}')" class="text-gray-400 font-black text-xl md:text-2xl hover:text-green-600 transition">+</button>
                    </div>
                    <form action="/cart/delete/{{i.product_id}}" method="POST" class="ml-4 md:ml-8">
                        <button class="text-gray-300 hover:text-red-500 transition text-xl md:text-2xl"><i class="fas fa-trash-alt"></i></button>
                    </form>
                </div>
                {% endfor %}
                <div class="bg-gray-50 p-6 md:p-10 rounded-[1.5rem] md:rounded-[3rem] space-y-4 mt-12 border border-gray-100">
                    <div class="flex justify-between items-center text-gray-400 font-bold uppercase tracking-widest text-[9px] md:text-xs"><span>Subtotal</span><span>{{ "{:,}".format(subtotal) }}원</span></div>
                    <div class="flex justify-between items-center text-orange-400 font-bold uppercase tracking-widest text-[9px] md:text-xs"><span>Delivery (카테고리별 합산)</span><span>+ {{ "{:,}".format(delivery_fee) }}원</span></div>
                    <div class="flex justify-between items-center pt-6 border-t border-gray-200 font-black">
                        <span class="text-lg md:text-xl text-gray-700 uppercase italic">Total</span>
                        <span class="text-2xl md:text-4xl text-green-600 italic underline underline-offset-8">{{ "{:,}".format(total) }}원</span>
                    </div>
                    <p class="text-[9px] text-gray-400 mt-2 italic font-bold">※ 배송비는 카테고리별 1,900원이며, 카테고리별 합계 50,000원 초과 시 50,000원당 1,900원이 추가됩니다.</p>
                </div>
                <a href="/order/confirm" class="block text-center bg-green-600 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2.5rem] font-black text-lg md:text-2xl shadow-2xl mt-12 hover:bg-green-700 transition active:scale-95 italic uppercase tracking-tighter">Order & Payment</a>
            </div>
            {% else %}
            <div class="py-40 text-center text-gray-300 font-black">
                <p class="text-6xl md:text-8xl mb-8 opacity-20">🧺</p><p class="text-xl md:text-2xl mb-12">장바구니가 비어있습니다.</p>
                <a href="/" class="inline-block bg-green-600 text-white px-10 py-4 md:px-12 md:py-5 rounded-full shadow-2xl font-black text-base md:text-lg">상품 보러가기</a>
            </div>
            {% endif %}
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, subtotal=subtotal, delivery_fee=delivery_fee, total=total)

@app.route('/order/confirm')
@login_required
def order_confirm():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()])
    
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    content = """
    <div class="max-w-md mx-auto py-20 px-4 font-black text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-10 border-b-4 border-green-600 pb-4 text-center uppercase italic">Checkout</h2>
        <div class="bg-white p-8 md:p-12 rounded-[2rem] md:rounded-[4rem] shadow-2xl border space-y-10">
            <div class="p-6 md:p-8 bg-green-50 rounded-[1.5rem] md:rounded-[3rem] border border-green-100 text-left relative overflow-hidden">
                <span class="text-green-600 text-[9px] md:text-[10px] block uppercase font-black tracking-widest mb-3">Delivery To</span>
                <p class="text-lg md:text-xl leading-relaxed text-gray-800">{{ current_user.address }}<br>{{ current_user.address_detail }}</p>
                <p class="text-red-500 mt-4 font-black text-base md:text-lg flex items-center gap-2">🔑 GATE: {{ current_user.entrance_pw }}</p>
            </div>
            <div class="flex justify-between items-end pt-4 font-black">
                <span class="text-gray-400 uppercase italic text-[10px] md:text-sm">Grand Total</span>
                <span class="text-3xl md:text-4xl text-green-600 italic underline underline-offset-4">{{ "{:,}".format(total) }}원</span>
            </div>
            
            <div class="bg-orange-50 p-4 rounded-2xl border border-orange-100 text-[9px] text-orange-700 font-bold leading-relaxed">
                📢 배송비 안내: 카테고리별 기본 1,900원이며, 개별 카테고리 합계 금액이 50,000원을 초과할 경우 50,000원 단위로 1,900원이 추가 과금됩니다. (현재 배송비: {{ "{:,}".format(delivery_fee) }}원)
            </div>

            <div class="p-6 md:p-8 bg-gray-50 rounded-[1.5rem] md:rounded-[2.5rem] text-[9px] md:text-[10px] text-gray-500 space-y-4 font-black border border-gray-100">
                <label class="flex items-start gap-3 mb-2 cursor-pointer group">
                    <input type="checkbox" id="consent_agency" class="mt-1 w-4 h-4 rounded-full border-gray-300 text-green-600 focus:ring-green-500" required>
                    <span class="group-hover:text-gray-800 transition">본인은 바구니삼촌이 상품 판매자가 아니며, 본인의 요청에 따라 상품을 대신 구매하고 배송하는 대행 서비스임을 인지하고 이에 동의합니다.</span>
                </label>
                <label class="flex items-start gap-3 pt-4 border-t border-gray-200 cursor-pointer group">
                    <input type="checkbox" id="consent_third_party_order" class="mt-1 w-4 h-4 rounded-full border-gray-300 text-green-600 focus:ring-green-500" required>
                    <span class="group-hover:text-gray-800 transition">[필수] 개인정보 제3자 제공 동의 : 원활한 배송 및 주문 처리를 위해 정보가 구매처와 배송 수행자에게 제공됨을 확인하였습니다.</span>
                </label>
            </div>
            <button onclick="startPayment()" class="w-full bg-green-600 text-white py-6 md:py-7 rounded-[1.5rem] md:rounded-[2.5rem] font-black text-xl md:text-2xl shadow-2xl active:scale-95 transition-transform uppercase italic tracking-tighter">Secure Payment</button>
        </div>
    </div>
    <script>
        function startPayment() { 
            if(!document.getElementById('consent_agency').checked) { alert("이용 동의가 필요합니다."); return; } 
            if(!document.getElementById('consent_third_party_order').checked) { alert("개인정보 제3자 제공 동의가 필요합니다."); return; } 
            window.location.href = "/order/payment"; 
        }
    </script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, total=total, delivery_fee=delivery_fee)

@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    subtotal = sum(i.price * i.quantity for i in items)
    
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()])
    
    total, tax_free = int(subtotal + delivery_fee), int(sum(i.price * i.quantity for i in items if i.tax_type == '면세'))
    order_id, order_name = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}", f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    content = """<div class="max-w-md mx-auto py-32 text-center font-black"><div class="w-20 h-20 md:w-24 md:h-24 bg-blue-100 rounded-full flex items-center justify-center text-4xl md:text-5xl mx-auto mb-10 text-blue-600 shadow-2xl animate-pulse">🛡️</div><h2 class="text-2xl md:text-3xl font-black mb-10 text-gray-800 tracking-tighter uppercase italic">Secure Gateway</h2><button id="payment-button" class="w-full bg-blue-600 text-white py-5 md:py-6 rounded-[1.5rem] md:rounded-[2.5rem] font-black text-lg md:text-xl shadow-xl hover:bg-blue-700 transition">결제창 열기</button></div><script>var tossPayments = TossPayments("{{ client_key }}"); document.getElementById('payment-button').addEventListener('click', function() { tossPayments.requestPayment('카드', { amount: {{ total }}, taxFreeAmount: {{ tax_free }}, orderId: '{{ order_id }}', orderName: '{{ order_name }}', customerName: '{{ user_name }}', successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail' }).catch(function (error) { if (error.code !== 'USER_CANCEL') alert(error.message); }); });</script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, client_key=TOSS_CLIENT_KEY, total=total, tax_free=tax_free, order_id=order_id, order_name=order_name, user_name=current_user.name)

@app.route('/payment/success')
@login_required
def payment_success():
    pk, oid, amt = request.args.get('paymentKey'), request.args.get('orderId'), request.args.get('amount')
    url, auth_key = "https://api.tosspayments.com/v1/payments/confirm", base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    res = requests.post(url, json={"paymentKey": pk, "amount": amt, "orderId": oid}, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
    if res.status_code == 200:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        cat_groups = {i.product_category: [] for i in items}
        for i in items: cat_groups[i.product_category].append(f"{i.product_name}({i.quantity})")
        details = " | ".join([f"[{cat}] {', '.join(prods)}" for cat, prods in cat_groups.items()])
        tax_free_total = sum(i.price * i.quantity for i in items if i.tax_type == '면세')
        
        cat_price_sums = {}
        for i in items: cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
        delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()])

        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=int(amt), delivery_fee=delivery_fee, tax_free_amount=tax_free_total, order_id=oid, payment_key=pk, delivery_address=f"({current_user.address}) {current_user.address_detail} (현관:{current_user.entrance_pw})", request_memo=current_user.request_memo))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-40 text-center font-black"><div class="w-20 h-20 md:w-24 md:h-24 bg-green-500 rounded-full flex items-center justify-center text-white text-4xl md:text-5xl mx-auto mb-10 shadow-2xl animate-bounce"><i class="fas fa-check"></i></div><h2 class="text-2xl md:text-3xl font-black mb-6">주문 성공!</h2><p class="text-gray-400 font-bold mb-16 text-sm md:text-base">배송 일정에 맞춰 찾아뵙겠습니다.</p><a href="/" class="bg-gray-800 text-white px-12 py-4 md:px-16 md:py-5 rounded-full font-black text-lg md:text-xl shadow-xl">홈으로</a></div>""" + FOOTER_HTML)
    return redirect('/')

# --- 관리자 기능 ---
@app.route('/admin')
@login_required
def admin_dashboard():
    is_master = current_user.is_admin
    tab = request.args.get('tab', 'products')
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    
    if tab == 'products':
        sel_cat = request.args.get('category', '전체')
        q = Product.query
        if sel_cat != '전체': q = q.filter_by(category=sel_cat)
        products = q.order_by(Product.id.desc()).all()
        if not is_master: products = [p for p in products if p.category in my_categories]
    elif tab == 'orders':
        start_date_str = request.args.get('start_date', datetime.now().strftime('%Y-%m-%dT00:00'))
        end_date_str = request.args.get('end_date', datetime.now().strftime('%Y-%m-%dT23:59'))
        sel_order_cat = request.args.get('order_cat', '전체')
        start_dt = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
        end_dt = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        all_orders_in_range = Order.query.filter(Order.created_at >= start_dt, Order.created_at <= end_dt).order_by(Order.created_at.desc()).all()
        filtered_orders, summary = [], {}
        for o in all_orders_in_range:
            show_order = False
            parts = o.product_details.split(' | ')
            for p_info in parts:
                match = re.match(r'\[(.*?)\] (.*)', p_info)
                if match:
                    cat_n, items_str = match.groups()
                    if not is_master and cat_n not in my_categories: continue
                    if sel_order_cat != '전체' and cat_n != sel_order_cat: continue
                    show_order = True
                    if cat_n not in summary: summary[cat_n] = {}
                    item_parts = items_str.split(', ')
                    for item_part in item_parts:
                        it_match = re.match(r'(.*?)\((\d+)\)', item_part)
                        if it_match: pn, qt = it_match.groups(); qt = int(qt); summary[cat_n][pn] = summary[cat_n].get(pn, 0) + qt
            if show_order: filtered_orders.append(o)
    
    content = """
    <div class="max-w-7xl mx-auto py-10 px-4 font-black text-xs md:text-sm">
        <div class="flex justify-between items-center mb-8"><h2 class="text-base md:text-xl font-black text-orange-700 italic">Admin Dashboard</h2><div class="flex gap-4"><a href="/logout" class="text-[10px] text-gray-400">로그아웃</a></div></div>
        <div class="flex border-b mb-8 bg-white rounded-t-xl overflow-x-auto text-[10px] md:text-[11px]"><a href="/admin?tab=products" class="px-5 py-4 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품관리</a>{% if current_user.is_admin %}<a href="/admin?tab=categories" class="px-5 py-4 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리 설정</a>{% endif %}<a href="/admin?tab=orders" class="px-5 py-4 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문집계</a></div>
        {% if tab == 'products' %}
            <div class="flex flex-col sm:flex-row justify-between items-center mb-6 gap-4"><form action="/admin" class="flex gap-2"><input type="hidden" name="tab" value="products"><select name="category" onchange="this.form.submit()" class="border p-2 rounded-xl text-[10px] font-black bg-white"><option value="전체">전체보기</option>{% for c in categories %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></form><div class="flex gap-2"><button onclick="document.getElementById('excel_upload_form').classList.toggle('hidden')" class="bg-blue-600 text-white px-4 py-2.5 rounded-xl font-black text-[9px] md:text-[10px]">엑셀 등록</button><a href="/admin/add" class="bg-green-600 text-white px-4 py-2.5 rounded-xl font-black text-[9px] md:text-[10px]">+ 상품 등록</a></div></div>
            <div id="excel_upload_form" class="hidden bg-blue-50 p-6 rounded-2xl mb-8 border border-blue-100"><h3 class="text-blue-700 font-black mb-2 text-xs">엑셀 상품 대량 등록</h3><form action="/admin/product/bulk_upload" method="POST" enctype="multipart/form-data" class="flex gap-2 items-end"><div class="flex-1"><label class="text-[9px] text-blue-400 font-bold mb-1 block">파일 (.xlsx)</label><input type="file" name="excel_file" class="w-full p-2 bg-white rounded-lg text-[10px]" required></div><button class="bg-blue-600 text-white px-5 py-2.5 rounded-xl font-black text-[10px]">업로드</button></form></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[9px] md:text-[10px] text-left"><table class="w-full"><thead class="bg-gray-50 border-b text-gray-400 uppercase"><tr><th class="p-3 md:p-4">상품 정보</th><th class="p-3 md:p-4 text-center">재고</th><th class="p-3 md:p-4 text-center">관리</th></tr></thead><tbody>{% for p in products %}<tr class="border-b"><td class="p-3 md:p-4"><b>{{ p.name }}</b> <span class="text-orange-500 text-[8px]">{{ p.badge }}</span><br><span class="text-green-600 font-bold">{{ p.description or '' }}</span><br><span class="text-gray-400">{{ "{:,}".format(p.price) }}원 ({{ p.spec }})</span></td><td class="p-3 md:p-4 text-center">{{ p.stock }}개</td><td class="p-3 md:p-4 text-center space-x-2"><a href="/admin/edit/{{p.id}}" class="text-blue-500">수정</a><a href="/admin/delete/{{p.id}}" class="text-red-300" onclick="return confirm('정말 삭제하시겠습니까?')">삭제</a></td></tr>{% endfor %}</tbody></table></div>
        {% elif tab == 'categories' %}
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 md:gap-10 text-left"><div class="bg-white p-6 md:p-8 rounded-2xl md:rounded-3xl border shadow-sm h-fit"><h3 class="text-[10px] text-gray-400 uppercase tracking-widest mb-6 font-black">카테고리 및 판매자 추가</h3><form action="/admin/category/add" method="POST" class="space-y-4"><input name="cat_name" placeholder="카테고리명" class="border p-4 rounded-xl w-full font-bold text-sm" required><textarea name="description" placeholder="카테고리 한줄 소개" class="border p-4 rounded-xl w-full h-20 font-bold text-sm"></textarea><input name="manager_email" placeholder="매니저 이메일" class="border p-4 rounded-xl w-full font-bold text-sm"><select name="tax_type" class="border p-4 rounded-xl w-full font-bold text-sm"><option value="과세">과세</option><option value="면세">면세</option></select><div class="border-t pt-4 space-y-2"><p class="text-[9px] text-green-600 font-bold tracking-widest uppercase">Seller Business Info</p><input name="biz_name" placeholder="상호명" class="border p-3 rounded-xl w-full font-bold text-sm"><input name="biz_representative" placeholder="대표자" class="border p-3 rounded-xl w-full font-bold text-sm"><input name="biz_reg_number" placeholder="사업자번호" class="border p-3 rounded-xl w-full font-bold text-sm"><input name="biz_address" placeholder="주소" class="border p-3 rounded-xl w-full font-bold text-sm"><input name="biz_contact" placeholder="연락처" class="border p-3 rounded-xl w-full font-bold text-sm"><input name="seller_link" placeholder="문의 링크" class="border p-3 rounded-xl w-full font-bold text-sm"></div><button class="w-full bg-green-600 text-white py-4 rounded-xl font-black text-sm md:text-base">생성</button></form></div><div class="bg-white rounded-2xl md:rounded-3xl border shadow-sm overflow-hidden"><table class="w-full text-left text-[10px] md:text-[11px]"><thead class="bg-gray-50 border-b font-bold uppercase"><tr><th class="p-3 md:p-4">순서</th><th class="p-3 md:p-4">카테고리명</th><th class="p-3 md:p-4 text-center">관리</th></tr></thead><tbody>{% for c in categories %}<tr class="border-b"><td class="p-3 md:p-4 flex gap-2"><a href="/admin/category/move/{{c.id}}/up" class="text-blue-500"><i class="fas fa-chevron-up"></i></a><a href="/admin/category/move/{{c.id}}/down" class="text-red-500"><i class="fas fa-chevron-down"></i></a></td><td class="p-3 md:p-4"><b>{{ c.name }}</b><br><span class="text-gray-400">매니저: {{ c.manager_email or '미지정' }}</span></td><td class="p-3 md:p-4 text-center space-x-2"><a href="/admin/category/edit/{{c.id}}" class="text-blue-500">수정</a><a href="/admin/category/delete/{{c.id}}" class="text-red-300">삭제</a></td></tr>{% endfor %}</tbody></table></div></div>
        {% elif tab == 'orders' %}
            <div class="bg-white p-6 md:p-8 rounded-2xl md:rounded-3xl border shadow-sm mb-10 text-left"><form action="/admin" method="GET" class="grid grid-cols-1 md:grid-cols-4 gap-4"><input type="hidden" name="tab" value="orders"><div><label class="text-[9px] text-gray-400 font-bold uppercase tracking-widest">Start Date</label><input type="datetime-local" name="start_date" value="{{ start_date_str }}" class="w-full border p-3 rounded-xl font-black mt-1 text-xs"></div><div><label class="text-[9px] text-gray-400 font-bold uppercase tracking-widest">End Date</label><input type="datetime-local" name="end_date" value="{{ end_date_str }}" class="w-full border p-3 rounded-xl font-black mt-1 text-xs"></div><div><label class="text-[9px] text-gray-400 font-bold uppercase tracking-widest">Category</label><select name="order_cat" class="w-full border p-3 rounded-xl font-black bg-white mt-1 text-xs"><option value="전체">전체보기</option>{% for c in nav_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}</select></div><div class="flex items-end"><button class="w-full bg-orange-600 text-white py-3 rounded-xl font-black shadow-lg text-xs md:text-sm">조회하기</button></div></form></div>
            <h3 class="text-lg md:text-xl font-black mb-6 italic text-left underline underline-offset-8">📊 품목별 수량 합계</h3>{% for cat_n, items in summary.items() %}<div class="bg-white rounded-[1.5rem] md:rounded-[2rem] border overflow-hidden mb-8 shadow-sm text-left text-xs md:text-sm"><div class="bg-gray-50 px-6 py-3 border-b font-black text-green-700 flex justify-between"><span>{{ cat_n }}</span><span class="text-gray-400 font-bold">Total: {{ items.values()|sum }}</span></div><table class="w-full text-left text-[10px] md:text-[11px]"><tbody>{% for pn, qt in items.items() %}<tr class="border-b hover:bg-gray-50 transition"><td class="p-3 md:p-4 font-bold text-gray-700">{{ pn }}</td><td class="p-3 md:p-4 text-right font-black text-blue-600 text-xs md:text-sm">{{ qt }}개</td></tr>{% endfor %}</tbody></table></div>{% endfor %}
            <h3 class="text-lg md:text-xl font-black mt-20 mb-6 italic text-left underline underline-offset-8">📑 상세 주문 명단</h3><div class="bg-white rounded-[1.5rem] md:rounded-[2.5rem] shadow-xl border overflow-x-auto text-left"><table class="w-full text-[9px] md:text-[10px] font-black min-w-[1000px] md:min-w-[1200px]"><thead class="bg-gray-800 text-white"><tr><th class="p-4 md:p-5 uppercase tracking-widest">Info</th><th class="p-4 md:p-5 uppercase tracking-widest">Customer</th><th class="p-4 md:p-5 uppercase tracking-widest">Shipping</th><th class="p-4 md:p-5 uppercase tracking-widest">Details</th><th class="p-4 md:p-5 text-right uppercase tracking-widest">Amount</th></tr></thead><tbody>{% for o in filtered_orders %}<tr class="border-b hover:bg-green-50 transition"><td class="p-4 md:p-5 text-gray-400 font-bold">{{ o.created_at.strftime('%m/%d %H:%M') }}<br><span class="text-[8px] opacity-50">{{ o.order_id }}</span></td><td class="p-4 md:p-5"><b class="text-gray-900 text-xs md:text-sm">{{ o.customer_name }}</b><br><span class="text-blue-600">{{ o.customer_phone }}</span></td><td class="p-4 md:p-5"><span class="font-bold text-gray-700 block mb-1 text-[10px]">{{ o.delivery_address }}</span><span class="text-orange-500 font-black italic block">📝 {{ o.request_memo or '없음' }}</span></td><td class="p-4 md:p-5 text-gray-600 leading-relaxed font-bold">{{ o.product_details }}</td><td class="p-4 md:p-5 text-right font-black text-green-600 text-xs md:text-sm">{{ "{:,}".format(o.total_price) }}원</td></tr>{% endfor %}</tbody></table></div>
            <div class="flex justify-end mt-10"><a href="/admin/orders/excel" class="bg-gray-800 text-white px-8 py-3.5 md:px-10 md:py-4 rounded-xl md:rounded-2xl font-black text-[10px] shadow-2xl hover:scale-105 transition">EXCEL DOWNLOAD</a></div>
        {% endif %}
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, **locals())

# [복구] 엑셀 대량 등록 라우트
@app.route('/admin/product/bulk_upload', methods=['POST'])
@login_required
def admin_product_bulk_upload():
    if not current_user.is_admin: return redirect('/')
    file = request.files.get('excel_file')
    if not file: return redirect('/admin')
    try:
        df = pd.read_excel(file)
        required_cols = ['category', 'name', 'price', 'stock']
        if not all(col in df.columns for col in required_cols):
            flash("엑셀 양식이 잘못되었습니다. (필수: category, name, price, stock)"); return redirect('/admin')
        count = 0
        for _, row in df.iterrows():
            cat_name = str(row['category']).strip()
            cat_exists = Category.query.filter_by(name=cat_name).first()
            if not cat_exists: continue
            new_p = Product(category=cat_name, name=str(row['name']), description=str(row.get('description', '')), price=int(row['price']), spec=str(row.get('spec', '')), origin=str(row.get('origin', '국산')), farmer="바구니삼촌", stock=int(row['stock']), deadline=pd.to_datetime(row['deadline']) if pd.notnull(row.get('deadline')) else None, badge=str(row.get('badge', '')), tax_type=cat_exists.tax_type)
            db.session.add(new_p); count += 1
        db.session.commit(); flash(f"{count}개의 상품이 대량 등록되었습니다.")
    except Exception as e: db.session.rollback(); flash(f"업로드 실패: {str(e)}")
    return redirect('/admin')

@app.route('/admin/category/add', methods=['POST'])
@login_required
def admin_category_add():
    if not current_user.is_admin: return redirect('/')
    last_cat = Category.query.order_by(Category.order.desc()).first()
    next_order = (last_cat.order + 1) if last_cat else 0
    db.session.add(Category(name=request.form['cat_name'], description=request.form.get('description'), tax_type=request.form['tax_type'], manager_email=request.form.get('manager_email'), seller_name=request.form.get('biz_name'), seller_inquiry_link=request.form.get('seller_link'), biz_name=request.form.get('biz_name'), biz_representative=request.form.get('biz_representative'), biz_reg_number=request.form.get('biz_reg_number'), biz_address=request.form.get('biz_address'), biz_contact=request.form.get('biz_contact'), order=next_order))
    db.session.commit(); return redirect('/admin?tab=categories')

@app.route('/admin/category/edit/<int:cid>', methods=['GET', 'POST'])
@login_required
def admin_category_edit(cid):
    if not current_user.is_admin: return redirect('/')
    cat = Category.query.get_or_404(cid)
    if request.method == 'POST':
        cat.name, cat.description, cat.tax_type, cat.manager_email = request.form['cat_name'], request.form['description'], request.form['tax_type'], request.form.get('manager_email')
        cat.biz_name, cat.biz_representative, cat.biz_reg_number, cat.biz_address, cat.biz_contact, cat.seller_inquiry_link = request.form.get('biz_name'), request.form.get('biz_representative'), request.form.get('biz_reg_number'), request.form.get('biz_address'), request.form.get('biz_contact'), request.form.get('seller_link')
        cat.seller_name = cat.biz_name
        db.session.commit(); return redirect('/admin?tab=categories')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-4 font-black text-left"><h2 class="text-2xl md:text-3xl font-black mb-10 tracking-tighter uppercase italic text-green-600">Edit Category</h2><form method="POST" class="bg-white p-8 md:p-10 rounded-[2.5rem] md:rounded-[3.5rem] shadow-2xl space-y-6"><div><label class="text-[9px] md:text-[10px] text-gray-400 uppercase font-black tracking-widest">Base Setting</label><input name="cat_name" value="{{cat.name}}" class="border p-4 md:p-5 rounded-2xl w-full font-black mt-1 text-sm md:text-base" required><textarea name="description" class="border p-4 md:p-5 rounded-2xl w-full h-24 font-black mt-2 text-sm md:text-base" placeholder="한줄 소개">{{cat.description or ''}}</textarea><input name="manager_email" value="{{cat.manager_email or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black mt-2 text-sm md:text-base" placeholder="매니저 이메일"><select name="tax_type" class="border p-4 md:p-5 rounded-2xl w-full font-black mt-2 text-sm md:text-base"><option value="과세" {% if cat.tax_type == '과세' %}selected{% endif %}>과세</option><option value="면세" {% if cat.tax_type == '면세' %}selected{% endif %}>면세</option></select></div><div class="border-t pt-6 space-y-4"><label class="text-[9px] md:text-[10px] text-green-600 uppercase font-black tracking-widest">Seller Business Info</label><input name="biz_name" value="{{cat.biz_name or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="상호명"><input name="biz_representative" value="{{cat.biz_representative or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="대표자"><input name="biz_reg_number" value="{{cat.biz_reg_number or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="사업자번호"><input name="biz_address" value="{{cat.biz_address or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="주소"><input name="biz_contact" value="{{cat.biz_contact or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="고객센터"><input name="seller_link" value="{{cat.seller_inquiry_link or ''}}" class="border p-4 md:p-5 rounded-2xl w-full font-black text-sm md:text-base" placeholder="문의 링크 URL"></div><button class="w-full bg-blue-600 text-white py-5 md:py-6 rounded-2xl font-black shadow-xl hover:bg-blue-700 transition italic uppercase text-sm md:text-base">Save Changes</button></form></div>""", cat=cat)

@app.route('/admin/category/move/<int:cid>/<string:direction>')
@login_required
def admin_category_move(cid, direction):
    if not current_user.is_admin: return redirect('/')
    curr = Category.query.get_or_404(cid)
    if direction == 'up': target = Category.query.filter(Category.order < curr.order).order_by(Category.order.desc()).first()
    else: target = Category.query.filter(Category.order > curr.order).order_by(Category.order.asc()).first()
    if target: curr.order, target.order = target.order, curr.order; db.session.commit()
    return redirect('/admin?tab=categories')

@app.route('/admin/category/delete/<int:cid>')
@login_required
def admin_category_delete(cid):
    if not current_user.is_admin: return redirect('/')
    db.session.delete(Category.query.get(cid)); db.session.commit(); return redirect('/admin?tab=categories')

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    if request.method == 'POST':
        cat_name = request.form['category']
        if not check_admin_permission(cat_name): return redirect('/admin')
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_files = request.files.getlist('detail_images')
        detail_img_url_str = ",".join(filter(None, [save_uploaded_file(f) for f in detail_files if f.filename != '']))
        new_p = Product(name=request.form['name'], description=request.form['description'], category=cat_name, price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer="바구니삼촌", stock=int(request.form['stock']), image_url=main_img or "", detail_image_url=detail_img_url_str, deadline=datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None, badge=request.form['badge'])
        db.session.add(new_p); db.session.commit(); return redirect('/admin')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-10 px-4 font-black text-left"><h2 class="text-2xl md:text-3xl font-black mb-10 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 uppercase italic">Add Product</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-8 md:p-10 rounded-[2rem] md:rounded-[3rem] shadow-2xl space-y-6"><select name="category" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black focus:ring-2 focus:ring-green-100 outline-none text-sm md:text-base">{% for c in nav_categories %}<option value="{{c.name}}">{{c.name}}</option>{% endfor %}</select><input name="name" placeholder="상품 정식 명칭" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required><input name="description" placeholder="한줄 소개" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><div class="grid grid-cols-2 gap-4"><input name="price" type="number" placeholder="가격(원)" class="p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" required><input name="spec" placeholder="규격" class="p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base"></div><div class="grid grid-cols-2 gap-4"><input name="stock" type="number" placeholder="수량" class="p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" value="50"><input name="deadline" type="datetime-local" class="p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base"></div><input name="origin" placeholder="원산지" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base" value="국산"><select name="badge" class="w-full p-4 md:p-5 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><option value="">뱃지없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option></select><div class="p-4 md:p-6 border-2 border-dashed border-gray-100 rounded-3xl"><label class="text-[9px] md:text-[10px] text-gray-400 uppercase font-black block mb-3">Main Image</label><input type="file" name="main_image" class="text-[10px]"></div><div class="p-4 md:p-6 border-2 border-dashed border-blue-50 rounded-3xl"><label class="text-[9px] md:text-[10px] text-blue-400 uppercase font-black block mb-3">Detail Images</label><input type="file" name="detail_images" multiple class="text-[10px]"></div><button class="w-full bg-green-600 text-white py-5 md:py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-lg md:text-2xl shadow-xl hover:bg-green-700 transition active:scale-95 italic uppercase text-sm md:text-base">Register Product</button></form></div>""")

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_product_edit(pid):
    p = Product.query.get_or_404(pid)
    if request.method == 'POST':
        p.name, p.description, p.price, p.spec, p.stock, p.origin, p.badge = request.form['name'], request.form['description'], int(request.form['price']), request.form['spec'], int(request.form['stock']), request.form['origin'], request.form['badge']
        p.deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        main_img = save_uploaded_file(request.files.get('main_image'))
        if main_img: p.image_url = main_img
        detail_files = request.files.getlist('detail_images')
        if detail_files and detail_files[0].filename != '':
            p.detail_image_url = ",".join(filter(None, [save_uploaded_file(f) for f in detail_files if f.filename != '']))
        db.session.commit(); return redirect('/admin')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-10 px-4 font-black text-left"><h2 class="text-2xl md:text-3xl font-black mb-10 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 uppercase italic text-gray-800">Edit Product</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[4rem] shadow-2xl space-y-6"><input name="name" value="{{p.name}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><input name="description" value="{{p.description or ''}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><input name="price" type="number" value="{{p.price}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><input name="stock" type="number" value="{{p.stock}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><input name="deadline" type="datetime-local" value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base"><div class="p-6 border-2 border-dashed border-gray-100 rounded-3xl"><label class="text-[9px] md:text-[10px] text-blue-600 font-black block mb-2 uppercase">Update Detail Images</label><input type="file" name="detail_images" multiple class="text-[10px]"></div><button class="w-full bg-blue-600 text-white py-5 md:py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-lg md:text-2xl shadow-xl hover:bg-blue-700 transition italic uppercase text-sm md:text-base">Apply Changes</button></form></div>""", p=p)

@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    p = Product.query.get(pid)
    if p and check_admin_permission(p.category): db.session.delete(p); db.session.commit()
    return redirect('/admin')

@app.route('/admin/user/delete/<int:uid>')
@login_required
def admin_user_delete(uid):
    if not current_user.is_admin: return redirect('/')
    db.session.delete(User.query.get(uid)); db.session.commit(); return redirect('/admin?tab=users')

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    if not current_user.is_admin: return redirect('/admin')
    all_categories, orders = [c.name for c in Category.query.all()], Order.query.all()
    data = []
    for o in orders:
        row = {"일시": o.created_at.strftime('%Y-%m-%d %H:%M'), "고객": o.customer_name, "전화": o.customer_phone, "이메일": o.customer_email, "주소": o.delivery_address, "요청사항": o.request_memo, "총액": o.total_price, "배송비": o.delivery_fee}
        parts = o.product_details.split(' | ')
        for cat in all_categories: row[f"[{cat}] 품명"] = ""; row[f"[{cat}] 수량"] = ""
        for part in parts:
            match = re.match(r'\[(.*?)\] (.*)', part)
            if match:
                cat_name, items_str = match.groups()
                if cat_name in all_categories:
                    item_list = items_str.split(', ')
                    names, qtys = [], []
                    for item in item_list:
                        it_match = re.match(r'(.*?)\((\d+)\)', item)
                        if it_match: n, q = it_match.groups(); names.append(n); qtys.append(q)
                    row[f"[{cat_name}] 품명"], row[f"[{cat_name}] 수량"] = ", ".join(names), ", ".join(qtys)
        data.append(row)
    df = pd.DataFrame(data); out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, download_name=f"UncleOrders_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

# --- DB 초기화 ---
def init_db():
    with app.app_context():
        db.create_all()
        # SQLite 예약어 "order" 충돌 방지를 위해 컬럼명에 쌍따옴표 추가
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
            ("category", "biz_contact", "VARCHAR(50)")
        ]
        for t, c, ct in cols:
            try: 
                db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN \"{c}\" {ct}"))
                db.session.commit()
            except: 
                db.session.rollback()
        
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        if not Category.query.first():
            db.session.add(Category(name="농산물", tax_type="면세", order=0)); db.session.add(Category(name="공동구매", tax_type="과세", order=1)); db.session.add(Category(name="반찬", tax_type="과세", order=2))
        db.session.commit()

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=5000, debug=True)