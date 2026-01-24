import os
import requests
import base64
from datetime import datetime, timedelta
from io import BytesIO
import re

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

# 테스트용 API 키
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

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50)) 
    description = db.Column(db.String(200)) # 상품 한줄 소개
    name = db.Column(db.String(200))
    price = db.Column(db.Integer)
    spec = db.Column(db.String(100))     
    origin = db.Column(db.String(100))   
    farmer = db.Column(db.String(50))    
    image_url = db.Column(db.String(500)) 
    detail_image_url = db.Column(db.Text) # 여러 장의 경로를 쉼표(,)로 구분하여 저장
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
            <a href="/" class="block text-gray-800 hover:text-green-600 transition font-black">전체 대행 리스트</a>
            <div class="h-px bg-gray-100 w-full"></div>
            {% for c in nav_categories %}
            <a href="/category/{{ c.name }}" class="block text-gray-500 hover:text-green-600 transition flex items-center justify-between">
                {{ c.name }} <i class="fas fa-chevron-right text-[10px] opacity-30"></i>
            </a>
            {% endfor %}
            <div class="h-px bg-gray-100 w-full"></div>
            <a href="/about" class="block font-bold text-blue-500 hover:underline">바구니삼촌 구매대행 몰이란?</a>
            
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
                        <span>🧺</span> <span class="italic tracking-tighter uppercase hidden sm:block">바구니삼촌 구매대행</span>
                    </a>
                </div>

                <div class="flex items-center gap-2 md:gap-4 flex-1 justify-end max-w-sm">
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
                <p class="text-green-500 font-black text-2xl italic tracking-tighter mb-4 uppercase">바구니삼촌 구매대행</p>
                <div class="text-xs space-y-1.5 opacity-80 leading-relaxed font-black">
                    <p>상호: 바구니삼촌 | 성명: 금창권</p>
                    <p>사업장소재지: 인천광역시 연수구 하모니로158, d동3층317호</p>
                    <p>등록번호: 472-93-02262 | 전화번호: 1666-8320</p>
                    <div class="pt-4 flex gap-4 opacity-50 underline">
                        <a href="javascript:void(0)" onclick="openUncleModal('terms')">이용약관</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('privacy')">개인정보처리방침</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('agency')">구매대행 안내</a>
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
                'title': '바구니삼촌몰 이용약관 (구매대행·배송대행)',
                'content': `
                    <b>제1조 (목적)</b><br>본 약관은 바구니삼촌몰(이하 “회사”)이 제공하는 구매대행 및 배송대행 서비스의 이용과 관련하여 회사와 이용자의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.<br><br>
                    <b>제2조 (서비스의 성격)</b><br>① 회사는 상품을 직접 판매하지 않습니다.<br>② 회사는 이용자의 요청에 따라 상품을 대신 구매하고 배송하는 구매대행·배송대행 서비스를 제공합니다.<br>③ 상품의 가격은 회사가 임의로 정하는 판매가가 아닌, 구매처의 실제 구매 원가를 기준으로 합니다.<br><br>
                    <b>제3조 (가격 구조)</b><br>① 상품 금액: 구매처의 실제 구매 원가<br>② 회사 마진: 없음 (0원)<br>③ 배송비: 카테고리별 정액 배송비 (1,900원)<br>④ 추가 수수료: 없음<br>※ 회사는 가격 구조를 투명하게 공개하며, 별도의 숨겨진 비용을 부과하지 않습니다.<br><br>
                    <b>제4조 (주문 및 결제)</b><br>① 이용자는 회사가 제공하는 방식에 따라 구매대행을 신청하고 결제할 수 있습니다.<br>② 결제 금액에는 상품 구매 원가와 배송비가 포함됩니다.<br>③ 구매대행 특성상 주문 완료 후 즉시 구매가 진행되므로, 단순 변심에 의한 취소가 제한될 수 있습니다.`
            },
            'third_party': {
                'title': '개인정보 제3자 제공 동의 (필수)',
                'content': '주문 처리를 위해 이름, 연락처, 주소가 구매처 및 배송사에 제공됩니다.'
            },
            'privacy': {
                'title': '개인정보처리방침',
                'content': '고객님의 정보를 안전하게 보호합니다.'
            },
            'agency': {
                'title': '구매대행 안내',
                'content': '우리는 물건을 파는 마트가 아니라 구매와 배송을 대신 해드리는 대행 서비스입니다.'
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
                    showToast("장바구니에 담겼습니다! 🧺");
                    document.getElementById('cart-count-badge').innerText = result.cart_count;
                    if(window.location.pathname === '/cart') location.reload();
                } else { alert(result.message); }
            } catch (error) { console.error('Error:', error); }
        }

        async function minusFromCart(productId) {
            try {
                const response = await fetch(`/cart/minus/${productId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const result = await response.json();
                if (result.success) {
                    document.getElementById('cart-count-badge').innerText = result.cart_count;
                    location.reload(); 
                } else { alert(result.message); }
            } catch (error) { console.error('Error:', error); }
        }

        function showToast(msg) {
            const t = document.getElementById("toast");
            t.innerText = msg;
            t.className = "show";
            setTimeout(() => { t.className = t.className.replace("show", ""); }, 2500);
        }

        function updateCountdowns() {
            const timers = document.querySelectorAll('.countdown-timer');
            const now = new Date().getTime();
            timers.forEach(timer => {
                if(!timer.dataset.deadline) { timer.innerText = "📅 상시 대행"; return; }
                const deadline = new Date(timer.dataset.deadline).getTime();
                const diff = deadline - now;
                if (diff <= 0) {
                    timer.innerText = "대행마감";
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
    categories = Category.query.all()
    managers = [c.manager_email for c in categories if c.manager_email]
    return dict(cart_count=cart_count, now=datetime.now(), managers=managers, nav_categories=categories)

@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    categories = Category.query.all()
    grouped_products = {}
    
    # 정렬 기준 설정:
    # 1. 마감안됨/재고있음(0) -> 마감됨/품절(1) 순서 (판매 가능 상품을 먼저 배치)
    # 2. 마지막 등록 상품이 가장 앞 (id DESC)
    # 3. 마감 시간 임박순 (deadline ASC)
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    
    for cat in categories:
        q_obj = Product.query.filter_by(category=cat.name, is_active=True)
        if query: q_obj = q_obj.filter(Product.name.contains(query))
        # 요청사항 반영: 최신 등록(id DESC)을 우선하고 그다음 마감시간(deadline ASC) 순
        products = q_obj.order_by(order_logic, Product.id.desc(), Product.deadline.asc()).all()
        if products: grouped_products[cat] = products
    
    content = """
    <div class="bg-gray-900 text-white py-20 md:py-32 px-4 shadow-inner relative overflow-hidden text-center">
        <div class="max-w-7xl mx-auto relative z-10 font-black">
            <span class="text-green-400 text-xs md:text-sm font-black mb-6 inline-block uppercase tracking-[0.3em]">Direct Delivery Service</span>
            <h2 class="text-4xl md:text-7xl font-black mb-8 leading-tight tracking-tighter">
                우리는 상품을 판매하지 않습니다.<br>
                <span class="text-green-500 uppercase">Innovation Buying Agent</span>
            </h2>
            <div class="w-20 h-1 bg-white/20 mx-auto mb-8"></div>
            <p class="text-gray-400 text-lg md:text-2xl font-bold max-w-2xl mx-auto mb-12">
                판매가 아닌 <span class="text-white underline decoration-green-500 decoration-4 underline-offset-8">배송 서비스</span> 입니다.
            </p>
            <div class="flex flex-col md:flex-row justify-center items-center gap-6">
                <a href="#products" class="bg-green-600 text-white px-12 py-5 rounded-full font-black shadow-2xl hover:bg-green-700 transition active:scale-95 text-lg">쇼핑하러 가기</a>
                <a href="/about" class="text-white/60 hover:text-white font-bold border-b border-white/20 pb-1 transition">바구니삼촌 구매대행 몰이란? <i class="fas fa-arrow-right ml-2"></i></a>
            </div>
        </div>
        <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/dark-matter.png')] opacity-30"></div>
    </div>

    <div id="products" class="max-w-7xl mx-auto px-4 py-16">
        {% if query %}
            <p class="mb-10 font-black text-gray-400 text-xl border-b pb-4">
                <span class="text-green-600">"{{ query }}"</span>에 대한 대행 검색 결과입니다.
            </p>
        {% endif %}
        
        {% for cat, products in grouped_products.items() %}
        <section class="mb-20">
            <div class="mb-10 flex justify-between items-end border-b border-gray-100 pb-4">
                <div>
                    <h2 class="text-2xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                        <span class="w-2 h-10 bg-green-500 rounded-full"></span> {{ cat.name }} 리스트
                    </h2>
                </div>
                <a href="/category/{{ cat.name }}" class="text-[11px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1">
                    전체보기 <i class="fas fa-chevron-right text-[10px]"></i>
                </a>
            </div>
            
            <div class="horizontal-scroll no-scrollbar">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[200px] md:w-[280px] transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-xs">대행마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4" onerror="this.src='https://placehold.co/400x400?text={{ p.name }}'">
                        <div class="absolute bottom-4 left-4"><span class="bg-black/70 text-white text-[10px] px-3 py-1 rounded-lg font-black">잔여: {{ p.stock }}개</span></div>
                        <div class="absolute top-4 left-4">{% if p.badge %}<span class="badge-tag bg-orange-500 text-white text-[10px] px-3 py-1 rounded-lg uppercase">{{ p.badge }}</span>{% endif %}</div>
                    </a>
                    <div class="p-6 flex flex-col flex-1">
                        <p class="countdown-timer text-[9px] font-bold text-red-500 mb-2" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-sm md:text-base truncate mb-1">{{ p.name }}</h3>
                        <p class="text-[11px] text-green-600 mb-1 font-medium">{{ p.description or '' }}</p>
                        <p class="text-[11px] md:text-xs text-gray-400 mb-4 font-bold">{{ p.spec }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <div class="flex flex-col">
                                <span class="text-xs text-gray-300 mb-1">대행가</span>
                                <span class="text-lg md:text-2xl text-gray-900 font-black">{{ "{:,}".format(p.price) }}원</span>
                            </div>
                            {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-10 h-10 md:w-12 md:h-12 rounded-2xl text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus"></i></button>{% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
                <div class="w-8 flex-shrink-0"></div>
            </div>
        </section>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products)

@app.route('/about')
def about_page():
    content = """
    <div class="bg-white py-20 px-4 font-black">
        <div class="max-w-4xl mx-auto">
            <nav class="mb-10"><a href="/" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i> 홈으로 돌아가기</a></nav>
            <h2 class="text-4xl md:text-5xl font-black text-gray-800 mb-12 tracking-tighter text-center md:text-left">바구니삼촌 구매대행 몰이란?</h2>
            <section class="mb-20">
                <h3 class="text-2xl md:text-3xl font-black text-gray-800 mb-8">혁신적인 물류 구조</h3>
                <div class="space-y-6 text-gray-500 text-lg leading-loose font-black text-left">
                    <p>우리는 상품을 직접 파는 마트가 아닙니다. 현장의 물류 전문가들이 가장 신선한 상품을 대신 구매하여 문 앞까지 전달하는 배송 전문 서비스입니다.</p>
                </div>
            </section>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/category/<string:cat_name>')
def category_view(cat_name):
    cat = Category.query.filter_by(name=cat_name).first_or_404()
    # 요청사항 반영: 최신 등록(id DESC)을 우선하고 그다음 마감시간 임박(deadline ASC) 순
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    products = Product.query.filter_by(category=cat_name, is_active=True).order_by(order_logic, Product.id.desc(), Product.deadline.asc()).all()
    content = """
    <div class="max-w-7xl mx-auto px-4 py-16">
        <h2 class="text-4xl text-gray-800 mb-10 font-black">{{ cat_name }} 대행 상품</h2>
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
            {% for p in products %}
            {% set is_expired = (p.deadline and p.deadline < now) %}
            <div class="product-card bg-white rounded-[2.5rem] shadow-sm border border-gray-100 overflow-hidden flex flex-col transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[10px]">대행마감</div>{% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                    <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4">
                    <!-- 잔여수량 표시 추가 -->
                    <div class="absolute bottom-3 left-3"><span class="bg-black/70 text-white text-[9px] px-2 py-1 rounded-md font-black backdrop-blur-sm">잔여: {{ p.stock }}개</span></div>
                </a>
                <div class="p-6 flex flex-col flex-1">
                    <!-- 마감시간 타이머 추가 -->
                    <p class="countdown-timer text-[8px] font-bold text-red-500 mb-1" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                    <h3 class="font-black text-gray-800 text-sm truncate mb-1 leading-tight">{{ p.name }}</h3>
                    <p class="text-[10px] text-green-600 mb-2 font-medium">{{ p.description or '' }}</p>
                    <div class="mt-auto flex justify-between items-center">
                        <span class="text-lg font-black text-green-600">{{ "{:,}".format(p.price) }}원</span>
                        {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 rounded-full text-white shadow-lg active:scale-90 transition-transform"><i class="fas fa-plus text-xs"></i></button>{% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, cat_name=cat_name)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    # 상세 이미지는 쉼표로 구분되어 저장됨
    detail_images = p.detail_image_url.split(',') if p.detail_image_url else []
    
    content = """
    <div class="max-w-4xl mx-auto px-4 py-16 font-black">
        <div class="grid md:grid-cols-2 gap-10 mb-20">
            <img src="{{ p.image_url }}" class="w-full aspect-square object-contain border rounded-[3rem] bg-white p-8">
            <div class="flex flex-col justify-center">
                <span class="bg-green-50 text-green-600 px-4 py-1.5 rounded-full text-[11px] w-fit mb-4">{{ p.category }}</span>
                <h2 class="text-3xl md:text-5xl text-gray-800 mb-4 leading-tight tracking-tighter">{{ p.name }}</h2>
                <p class="text-green-600 text-lg mb-4 font-bold">{{ p.description or '' }}</p>
                <div class="space-y-2 mb-8 text-xs text-gray-400">
                    <p class="text-blue-500 font-bold"><i class="fas fa-warehouse mr-2"></i> 잔여수량: {{ p.stock }}개</p>
                    <p class="countdown-timer text-red-500 font-bold" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                </div>
                <div class="bg-gray-50 p-8 rounded-[2.5rem] mb-10 border border-gray-100">
                    <span class="text-gray-400 text-xs mb-1 block">대행가(VAT 포함)</span>
                    <p class="text-4xl md:text-6xl font-black text-green-600">{{ "{:,}".format(p.price) }}원</p>
                </div>
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-6 rounded-[2rem] font-black text-xl shadow-2xl active:scale-95 transition-transform">장바구니 담기</button>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-6 rounded-[2rem] font-black text-xl cursor-not-allowed italic">대행마감</button>
                {% endif %}
            </div>
        </div>
        <div class="border-t pt-16">
            <h3 class="font-black text-2xl mb-12 border-l-8 border-green-600 pl-6">상세 이미지</h3>
            <div class="flex flex-col gap-6 bg-white p-4 rounded-3xl border">
                {% for img in detail_images %}
                <img src="{{ img }}" class="w-full rounded-2xl shadow-sm">
                {% endfor %}
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, detail_images=detail_images)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user); return redirect('/')
        flash("로그인 정보를 확인해주세요.")
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-20 p-10 bg-white rounded-[3rem] shadow-2xl border">
        <h2 class="text-2xl font-black text-center mb-10 text-green-600">바구니삼촌 로그인</h2>
        <form method="POST" class="space-y-6">
            <input name="email" type="email" placeholder="이메일" class="w-full p-5 bg-gray-50 rounded-2xl" required>
            <input name="password" type="password" placeholder="비밀번호" class="w-full p-5 bg-gray-50 rounded-2xl" required>
            <button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black shadow-xl">로그인</button>
        </form>
    </div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        if User.query.filter_by(email=email).first(): flash("이미 가입된 이메일입니다."); return redirect('/register')
        new_user = User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo)
        db.session.add(new_user); db.session.commit()
        return redirect('/login')
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-10 p-10 bg-white rounded-[3rem] shadow-2xl border"><h2 class="text-2xl font-black mb-8">회원가입</h2><form method="POST" class="space-y-4"><input name="name" placeholder="성함" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="email" type="email" placeholder="이메일" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="phone" placeholder="연락처" class="w-full p-4 bg-gray-50 rounded-2xl" required><input id="address" name="address" placeholder="주소" class="w-full p-4 bg-gray-100 rounded-2xl" readonly onclick="execDaumPostcode()"><input name="address_detail" placeholder="상세주소" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="entrance_pw" placeholder="공동현관 비번 (필수)" class="w-full p-4 bg-red-50 rounded-2xl" required><input name="request_memo" placeholder="배송 요청사항" class="w-full p-4 bg-white border rounded-2xl"><button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black shadow-xl mt-6">가입하기</button></form></div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """
    <div class="max-w-4xl mx-auto py-12 px-4 font-black">
        <h2 class="text-3xl font-black mb-10 border-l-8 border-green-600 pl-6">내 정보 센터</h2>
        <div class="bg-white p-12 rounded-[3rem] shadow-xl border mb-12 relative overflow-hidden">
            <p class="text-2xl font-black mb-2">{{ current_user.name }} 고객님</p>
            <p class="text-gray-400 font-bold mb-8">{{ current_user.email }}</p>
            <div class="grid md:grid-cols-2 gap-8 pt-8 border-t">
                <div><p class="text-xs text-gray-400 uppercase mb-2 tracking-widest">배송지</p><p class="text-gray-700 leading-relaxed">{{ current_user.address }} {{ current_user.address_detail }}</p></div>
                <div><p class="text-xs text-gray-400 uppercase mb-2 tracking-widest">현관비번</p><p class="text-red-500">🔑 {{ current_user.entrance_pw }}</p></div>
            </div>
            <a href="/logout" class="absolute top-8 right-8 text-[10px] bg-gray-100 px-3 py-1 rounded-full text-gray-400 hover:bg-gray-200 transition">LOGOUT</a>
        </div>
        <h3 class="text-xl font-black mb-6"><i class="fas fa-truck text-green-600"></i> 대행 이용 내역</h3>
        <div class="space-y-4">
            {% for o in orders %}
            <div class="bg-white p-8 rounded-[2.5rem] shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
                <p class="text-[10px] text-gray-300 mb-2">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                <p class="font-black text-gray-800 text-lg mb-4">{{ o.product_details }}</p>
                <div class="flex justify-between items-center pt-4 border-t border-gray-50">
                    <span class="text-gray-400 text-xs">최종 결제액</span>
                    <span class="text-xl text-green-600">{{ "{:,}".format(o.total_price) }}원</span>
                </div>
            </div>
            {% endfor %}
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
    cat_counts = {}
    for i in items: cat_counts[i.product_category] = cat_counts.get(i.product_category, 0) + i.quantity
    # 수량 계단형 배송비: 4개마다 1900원 추가
    delivery_fee = sum([((count-1) // 4 + 1) * 1900 for count in cat_counts.values()]) if items else 0
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    content = """
    <div class="max-w-3xl mx-auto py-16 px-4 font-black">
        <h2 class="text-3xl font-black mb-10 border-l-8 border-green-600 pl-6">장바구니</h2>
        <div class="bg-white rounded-[3rem] shadow-2xl border overflow-hidden">
            {% if items %}
            <div class="p-10 space-y-6">
                {% for i in items %}
                <div class="flex justify-between items-center border-b pb-6 last:border-0">
                    <div class="flex-1"><p class="font-black text-lg">{{ i.product_name }}</p><p class="text-green-600 font-black text-sm">{{ "{:,}".format(i.price) }}원</p></div>
                    <div class="flex items-center gap-4 bg-gray-100 px-4 py-2 rounded-2xl">
                        <button onclick="minusFromCart('{{i.product_id}}')" class="text-gray-400 font-black text-xl">-</button>
                        <span class="font-black text-lg w-6 text-center">{{ i.quantity }}</span>
                        <button onclick="addToCart('{{i.product_id}}')" class="text-gray-400 font-black text-xl">+</button>
                    </div>
                    <form action="/cart/delete/{{i.product_id}}" method="POST" class="ml-4">
                        <button class="text-gray-300 hover:text-red-500 transition"><i class="fas fa-trash-alt text-xl"></i></button>
                    </form>
                </div>
                {% endfor %}
                <div class="bg-gray-50 p-8 rounded-[2rem] space-y-3 mt-10 text-xs">
                    <div class="flex justify-between"><span>상품 합계</span><span>{{ "{:,}".format(subtotal) }}원</span></div>
                    <div class="flex justify-between text-orange-400"><span>배송비 (수량 계단형)</span><span>+ {{ "{:,}".format(delivery_fee) }}원</span></div>
                    <div class="flex justify-between pt-4 border-t font-black">
                        <span class="text-lg">최종 결제 금액</span>
                        <span class="text-3xl text-green-600">{{ "{:,}".format(total) }}원</span>
                    </div>
                </div>
                <a href="/order/confirm" class="block text-center bg-green-600 text-white py-6 rounded-[2rem] font-black text-xl shadow-xl mt-8">주문 확인 및 결제하기</a>
            </div>
            {% else %}
            <div class="py-32 text-center text-gray-400 font-black">
                <p class="text-6xl mb-6">🧺</p><p class="font-black text-xl mb-10">장바구니가 비어있습니다.</p>
                <a href="/" class="bg-green-600 text-white px-10 py-4 rounded-full shadow-lg">쇼핑하러 가기</a>
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
    cat_counts = {}
    for i in items: cat_counts[i.product_category] = cat_counts.get(i.product_category, 0) + i.quantity
    delivery_fee = sum([((count-1) // 4 + 1) * 1900 for count in cat_counts.values()])
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    content = """
    <div class="max-w-md mx-auto py-20 px-4 font-black">
        <h2 class="text-2xl font-black mb-8 border-b pb-4 text-center uppercase">주문 확인</h2>
        <div class="bg-white p-10 rounded-[3rem] shadow-2xl border space-y-8">
            <div class="p-8 bg-green-50 rounded-[2.5rem] border font-black text-left">
                <span class="text-green-600 text-[10px] block uppercase mb-2">배송지</span>
                <p class="text-lg leading-relaxed">{{ current_user.address }} {{ current_user.address_detail }}</p>
                <p class="text-red-500 mt-2 font-black">현관: {{ current_user.entrance_pw }}</p>
            </div>
            <div class="flex justify-between items-center pt-4 font-black">
                <span class="text-gray-400">최종 결제액</span>
                <span class="text-3xl text-green-600">{{ "{:,}".format(total) }}원</span>
            </div>
            <div class="p-6 bg-gray-50 rounded-2xl text-[10px] text-gray-500 space-y-3 font-black text-left">
                <label class="flex items-start gap-2">
                    <input type="checkbox" id="consent_agency" class="mt-1" required>
                    <span>본인은 바구니삼촌이 상품 판매자가 아니며, 본인의 요청에 따라 상품을 대신 구매하고 배송하는 대행 서비스임을 인지하고 이에 동의합니다.</span>
                </label>
            </div>
            <button onclick="startPayment()" class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-xl shadow-xl active:scale-95 transition-transform">안전 결제 시작</button>
        </div>
    </div>
    <script>
        function startPayment() {
            if(!document.getElementById('consent_agency').checked) { alert("구매대행 이용 동의가 필요합니다."); return; }
            window.location.href = "/order/payment";
        }
    </script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, total=total)

@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    subtotal = sum(i.price * i.quantity for i in items)
    cat_counts = {i.product_category: 0 for i in items}
    for i in items: cat_counts[i.product_category] += i.quantity
    delivery_fee = sum([((count-1) // 4 + 1) * 1900 for count in cat_counts.values()])
    total = int(subtotal + delivery_fee)
    tax_free = int(sum(i.price * i.quantity for i in items if i.tax_type == '면세'))
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    content = """
    <div class="max-w-md mx-auto py-32 text-center font-black">
        <div class="w-24 h-24 bg-blue-100 rounded-full flex items-center justify-center text-5xl mx-auto mb-10 text-blue-600 shadow-2xl animate-pulse">🛡️</div>
        <h2 class="text-3xl font-black mb-10 text-gray-800 tracking-tighter">안전 결제창으로 이동합니다</h2>
        <button id="payment-button" class="w-full bg-blue-600 text-white py-6 rounded-[2rem] font-black text-xl shadow-xl">결제 진행</button>
    </div>
    <script>
        var tossPayments = TossPayments("{{ client_key }}");
        document.getElementById('payment-button').addEventListener('click', function() {
            tossPayments.requestPayment('카드', { 
                amount: {{ total }}, taxFreeAmount: {{ tax_free }}, orderId: '{{ order_id }}', orderName: '{{ order_name }}', 
                customerName: '{{ user_name }}', successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail', 
            }).catch(function (error) { if (error.code !== 'USER_CANCEL') alert(error.message); });
        });
    </script>"""
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
        cat_counts = {i.product_category: 0 for i in items}
        for i in items: cat_counts[i.product_category] += i.quantity
        delivery_fee = sum([((count-1) // 4 + 1) * 1900 for count in cat_counts.values()])
        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=int(amt), delivery_fee=delivery_fee, tax_free_amount=tax_free_total, order_id=oid, payment_key=pk, delivery_address=f"({current_user.address}) {current_user.address_detail} (현관:{current_user.entrance_pw})", request_memo=current_user.request_memo))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-40 text-center font-black"><div class="w-24 h-24 bg-green-500 rounded-full flex items-center justify-center text-white text-5xl mx-auto mb-10 shadow-2xl animate-bounce"><i class="fas fa-check"></i></div><h2 class="text-3xl font-black mb-6">주문 성공!</h2><p class="text-gray-400 font-bold mb-16">배송 일정에 맞춰 찾아뵙겠습니다.</p><a href="/" class="bg-gray-800 text-white px-16 py-5 rounded-full font-black text-xl shadow-xl">홈으로</a></div>""" + FOOTER_HTML)
    return redirect('/')

# --- 관리자 기능 (기존 1306줄 분량의 모든 기능을 다시 채움) ---
@app.route('/admin')
@login_required
def admin_dashboard():
    is_master = current_user.is_admin
    my_categories = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
    if not is_master and not my_categories: return redirect('/')
    
    tab = request.args.get('tab', 'products')
    sel_cat = request.args.get('category', '전체')
    sel_order_cat = request.args.get('order_cat', '전체')
    start_date_str = request.args.get('start_date', datetime.now().strftime('%Y-%m-%dT00:00'))
    end_date_str = request.args.get('end_date', (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%dT00:00'))
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
    end_dt = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
    
    users, categories = User.query.all(), Category.query.all()
    all_orders = Order.query.order_by(Order.created_at.desc()).all()
    filtered_orders = Order.query.filter(Order.created_at >= start_dt, Order.created_at <= end_dt).all()
    
    summary = {}
    for o in filtered_orders:
        parts = o.product_details.split(' | ')
        for p_info in parts:
            match = re.match(r'\[(.*?)\] (.*)', p_info)
            if match:
                cat_n, items_str = match.groups()
                if not is_master and cat_n not in my_categories: continue
                if cat_n not in summary: summary[cat_n] = {}
                item_parts = items_str.split(', ')
                for item_part in item_parts:
                    it_match = re.match(r'(.*?)\((\d+)\)', item_part)
                    if it_match:
                        prod_n, qty = it_match.groups()
                        qty = int(qty)
                        if prod_n not in summary[cat_n]: summary[cat_n][prod_n] = {'qty': 0, 'price_sum': 0}
                        summary[cat_n][prod_n]['qty'] += qty
                        db_p = Product.query.filter_by(name=prod_n).first()
                        if db_p: summary[cat_n][prod_n]['price_sum'] += (db_p.price * qty)

    products_query = Product.query
    if sel_cat != '전체': products_query = products_query.filter_by(category=sel_cat)
    products = products_query.all()
    if not is_master: products = [p for p in products if p.category in my_categories]
    
    content = """
    <div class="max-w-7xl mx-auto py-10 px-4 font-black">
        <div class="flex justify-between items-center mb-8">
            <h2 class="text-xl font-black text-orange-700 italic">Admin Dashboard</h2>
            <p class="text-[10px] text-gray-400">{{ current_user.email }}</p>
        </div>
        <div class="flex border-b mb-8 bg-white rounded-t-xl overflow-x-auto text-[11px]">
            <a href="/admin?tab=products" class="px-6 py-4 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품관리</a>
            {% if current_user.is_admin %}<a href="/admin?tab=categories" class="px-6 py-4 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리/권한</a>{% endif %}
            <a href="/admin?tab=orders" class="px-6 py-4 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문관리(통계)</a>
            {% if current_user.is_admin %}<a href="/admin?tab=users" class="px-6 py-4 {% if tab == 'users' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원DB</a>{% endif %}
        </div>

        {% if tab == 'products' %}
            <div class="flex justify-between items-center mb-6">
                <form action="/admin" class="flex gap-2">
                    <input type="hidden" name="tab" value="products">
                    <select name="category" onchange="this.form.submit()" class="border p-2 rounded-xl text-[11px] font-black bg-white">
                        <option value="전체">전체보기</option>
                        {% for c in categories %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}
                    </select>
                </form>
                <a href="/admin/add" class="bg-green-600 text-white px-5 py-3 rounded-xl font-black text-[10px]">+ 상품 등록</a>
            </div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[10px]">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 border-b text-gray-400">
                        <tr><th class="p-4">상품명/한줄소개/가격</th><th class="p-4 text-center">재고</th><th class="p-4 text-center">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for p in products %}
                        <tr class="border-b">
                            <td class="p-4">
                                <b>{{ p.name }}</b> <span class="text-orange-500 text-[8px]">{{ p.badge }}</span><br>
                                <span class="text-green-600 font-bold">{{ p.description or '' }}</span><br>
                                <span class="text-gray-400">{{ "{:,}".format(p.price) }}원 ({{ p.spec }})</span>
                            </td>
                            <td class="p-4 text-center">{{ p.stock }}개</td>
                            <td class="p-4 text-center space-x-2">
                                <a href="/admin/edit/{{p.id}}" class="text-blue-500">수정</a>
                                <a href="/admin/delete/{{p.id}}" class="text-red-300" onclick="return confirm('정말 삭제하시겠습니까?')">삭제</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif tab == 'orders' %}
            <div class="bg-white p-6 rounded-3xl border border-green-100 mb-8 shadow-sm text-xs">
                <h3 class="font-black text-green-700 mb-4">장보기 품목 집계 (날짜별)</h3>
                <form action="/admin" method="GET" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <input type="hidden" name="tab" value="orders">
                    <div><label class="text-[10px] text-gray-400 font-bold">시작</label><input type="datetime-local" name="start_date" value="{{ start_date_str }}" class="w-full border p-3 rounded-xl font-black"></div>
                    <div><label class="text-[10px] text-gray-400 font-bold">종료</label><input type="datetime-local" name="end_date" value="{{ end_date_str }}" class="w-full border p-3 rounded-xl font-black"></div>
                    <div class="flex items-end"><button class="w-full bg-green-600 text-white py-3 rounded-xl font-black">데이터 추출</button></div>
                </form>
            </div>
            {% for cat_n, items in summary.items() %}
            <div class="bg-white rounded-3xl border overflow-hidden mb-6">
                <div class="bg-gray-50 px-6 py-3 border-b text-sm font-black flex justify-between">{{ cat_n }} 상세 통계</div>
                <table class="w-full text-left text-[11px]">
                    <thead><tr class="border-b text-gray-400"><th class="p-4">품명</th><th class="p-4 text-center">합계수량</th><th class="p-4 text-right">금액합계</th></tr></thead>
                    <tbody>
                        {% for p_n, data in items.items() %}
                        <tr class="border-b"><td class="p-4">{{ p_n }}</td><td class="p-4 text-center text-blue-600">{{ data.qty }}개</td><td class="p-4 text-right">{{ "{:,}".format(data.price_sum) }}원</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endfor %}
            <div class="flex justify-end"><a href="/admin/orders/excel" class="bg-orange-600 text-white px-5 py-3 rounded-xl font-black text-[10px]">전체 주문 엑셀 다운로드</a></div>
        {% elif tab == 'users' %}
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[10px]">
                <table class="w-full text-left">
                    <thead class="bg-gray-50 border-b text-gray-400"><tr><th class="p-4">고객명/이메일</th><th class="p-4">전화번호</th><th class="p-4">주소/현관정보</th><th class="p-4 text-center">관리</th></tr></thead>
                    <tbody>
                        {% for u in users %}
                        <tr class="border-b">
                            <td class="p-4"><b>{{ u.name }}</b><br>{{ u.email }}</td>
                            <td class="p-4">{{ u.phone }}</td>
                            <td class="p-4">{{ u.address }} {{ u.address_detail }}<br><span class="text-red-500">🔑 {{ u.entrance_pw }}</span></td>
                            <td class="p-4 text-center"><a href="/admin/user/delete/{{u.id}}" class="text-red-400" onclick="return confirm('탈퇴처리 하시겠습니까?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif tab == 'categories' %}
            <div class="max-w-2xl bg-white p-8 rounded-3xl border shadow-sm">
                <h3 class="text-gray-400 uppercase tracking-widest text-[10px] mb-4">카테고리 생성</h3>
                <form action="/admin/category/add" method="POST" class="space-y-4">
                    <div class="flex gap-2">
                        <input name="cat_name" placeholder="카테고리명" class="border p-4 rounded-xl flex-1" required>
                        <select name="tax_type" class="border p-4 rounded-xl"><option value="과세">과세</option><option value="면세">면세</option></select>
                    </div>
                    <input name="manager_email" placeholder="담당자 이메일 (마스터는 비워두세요)" class="border p-4 rounded-xl w-full">
                    <button class="w-full bg-green-600 text-white py-4 rounded-xl font-black">생성</button>
                </form>
            </div>
        {% endif %}
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, **locals())

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    cats = Category.query.all()
    if request.method == 'POST':
        cat_name = request.form['category']
        if not check_admin_permission(cat_name): return redirect('/admin')
        
        # 대표 사진 1장
        main_img = save_uploaded_file(request.files.get('main_image'))
        
        # 상세 사진 여러 장
        detail_files = request.files.getlist('detail_images')
        detail_paths = []
        for f in detail_files:
            p_path = save_uploaded_file(f)
            if p_path: detail_paths.append(p_path)
        detail_img_url_str = ",".join(detail_paths)

        new_p = Product(
            name=request.form['name'],
            description=request.form['description'],
            category=cat_name,
            price=int(request.form['price']),
            spec=request.form['spec'],
            origin=request.form['origin'],
            farmer="바구니삼촌",
            stock=int(request.form['stock']),
            image_url=main_img or "",
            detail_image_url=detail_img_url_str,
            deadline=datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None,
            badge=request.form['badge']
        )
        db.session.add(new_p); db.session.commit()
        return redirect('/admin')
    
    return render_template_string(HEADER_HTML + """
    <div class="max-w-xl mx-auto py-10 px-4 font-black">
        <h2 class="text-2xl font-black mb-8 tracking-tighter">상품 등록</h2>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <select name="category" class="w-full border p-4 rounded-xl font-bold">
                {% for c in cats %}<option value="{{c.name}}">{{c.name}}</option>{% endfor %}
            </select>
            <input name="name" placeholder="상품명" class="w-full border p-4 rounded-xl font-bold" required>
            <input name="description" placeholder="한줄 소개 (예: 산지직송 당일수확 아삭한 배)" class="w-full border p-4 rounded-xl font-bold">
            <div class="grid grid-cols-2 gap-4">
                <input name="price" type="number" placeholder="가격" class="border p-4 rounded-xl font-bold" required>
                <input name="spec" placeholder="규격" class="border p-4 rounded-xl font-bold">
            </div>
            <div class="grid grid-cols-2 gap-4">
                <input name="stock" type="number" placeholder="재고" class="border p-4 rounded-xl font-bold" value="50">
                <input name="deadline" type="datetime-local" class="border p-4 rounded-xl font-bold">
            </div>
            <input name="origin" placeholder="원산지" class="w-full border p-4 rounded-xl font-bold" value="국산">
            <select name="badge" class="w-full border p-4 rounded-xl font-bold">
                <option value="">뱃지없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option>
            </select>
            <div class="p-4 border rounded-xl">
                <label class="text-xs text-gray-400 block mb-2">대표 사진 (1장)</label>
                <input type="file" name="main_image">
            </div>
            <div class="p-4 border rounded-xl">
                <label class="text-xs text-blue-600 font-bold block mb-2">상세 사진 (다중 선택 가능)</label>
                <input type="file" name="detail_images" multiple>
            </div>
            <button class="w-full bg-green-600 text-white py-5 rounded-xl font-black text-lg shadow-lg">상품 등록 완료</button>
        </form>
    </div>""", cats=cats)

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_product_edit(pid):
    p = Product.query.get_or_404(pid)
    cats = Category.query.all()
    if request.method == 'POST':
        p.name = request.form['name']
        p.description = request.form['description']
        p.price = int(request.form['price'])
        p.spec = request.form['spec']
        p.stock = int(request.form['stock'])
        p.origin = request.form['origin']
        p.badge = request.form['badge']
        p.deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        
        main_img = save_uploaded_file(request.files.get('main_image'))
        if main_img: p.image_url = main_img
        
        detail_files = request.files.getlist('detail_images')
        if detail_files and detail_files[0].filename != '':
            detail_paths = [save_uploaded_file(f) for f in detail_files if f.filename != '']
            p.detail_image_url = ",".join(filter(None, detail_paths))
            
        db.session.commit(); return redirect('/admin')
    
    return render_template_string(HEADER_HTML + """
    <div class="max-w-xl mx-auto py-10 px-4 font-black">
        <h2 class="text-2xl font-black mb-8 tracking-tighter">상품 수정</h2>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <input name="name" value="{{p.name}}" class="w-full border p-4 rounded-xl font-bold">
            <input name="description" value="{{p.description or ''}}" class="w-full border p-4 rounded-xl font-bold">
            <input name="price" type="number" value="{{p.price}}" class="w-full border p-4 rounded-xl font-bold">
            <input name="stock" type="number" value="{{p.stock}}" class="w-full border p-4 rounded-xl font-bold">
            <input name="deadline" type="datetime-local" value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}" class="w-full border p-4 rounded-xl font-bold">
            <div class="p-4 border rounded-xl">
                <label class="text-xs text-blue-600 font-bold block mb-2">상세 사진 재등록 (다중 선택)</label>
                <input type="file" name="detail_images" multiple>
            </div>
            <button class="w-full bg-blue-600 text-white py-5 rounded-xl font-black">수정 완료</button>
        </form>
    </div>""", p=p)

@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    p = Product.query.get(pid)
    if p and check_admin_permission(p.category): db.session.delete(p); db.session.commit()
    return redirect('/admin')

@app.route('/admin/category/add', methods=['POST'])
@login_required
def admin_category_add():
    if not current_user.is_admin: return redirect('/')
    db.session.add(Category(name=request.form['cat_name'], tax_type=request.form['tax_type'], manager_email=request.form.get('manager_email', '').strip() or None))
    db.session.commit(); return redirect('/admin?tab=categories')

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    if not current_user.is_admin: return redirect('/admin')
    all_categories = [c.name for c in Category.query.all()]
    orders = Order.query.all()
    data = []
    for o in orders:
        row = {"일시": o.created_at.strftime('%Y-%m-%d %H:%M'), "고객": o.customer_name, "전화": o.customer_phone, "이메일": o.customer_email, "주소": o.delivery_address, "요청사항": o.request_memo, "총액": o.total_price, "배송비": o.delivery_fee}
        cat_row_data = {}
        for cat in all_categories:
            cat_row_data[f"[{cat}] 품명"] = ""
            cat_row_data[f"[{cat}] 수량"] = ""
        parts = o.product_details.split(' | ')
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
                    cat_row_data[f"[{cat_name}] 품명"] = ", ".join(names)
                    cat_row_data[f"[{cat_name}] 수량"] = ", ".join(qtys)
        row.update(cat_row_data)
        data.append(row)
    df = pd.DataFrame(data)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0)
    return send_file(out, download_name=f"UncleOrders_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

# --- DB 초기화 ---
def init_db():
    with app.app_context():
        db.create_all()
        # 누락된 컬럼 추가 (기존 사용자 대응)
        cols = [
            ("product", "description", "VARCHAR(200)"),
            ("product", "detail_image_url", "TEXT"),
            ("user", "request_memo", "VARCHAR(500)"),
            ("order", "delivery_fee", "INTEGER DEFAULT 0"),
            ("product", "badge", "VARCHAR(50)")
        ]
        for t, c, ct in cols:
            try: db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN {c} {ct}")); db.session.commit()
            except: db.session.rollback()
        
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        if not Category.query.first():
            db.session.add(Category(name="농산물", tax_type="면세")); db.session.add(Category(name="공동구매", tax_type="과세")); db.session.add(Category(name="반찬", tax_type="과세"))
        db.session.commit()

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=5000, debug=True)