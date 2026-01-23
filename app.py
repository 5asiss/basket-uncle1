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

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    tax_type = db.Column(db.String(20), default='과세') 
    manager_email = db.Column(db.String(120), nullable=True) 

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50)) 
    name = db.Column(db.String(200))
    price = db.Column(db.Integer)
    spec = db.Column(db.String(100))     
    origin = db.Column(db.String(100))   
    farmer = db.Column(db.String(50))    
    image_url = db.Column(db.String(500)) 
    detail_image_url = db.Column(db.String(500)) 
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
            <a href="/" class="block text-gray-800 hover:text-green-600 transition">전체 대행 리스트</a>
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
    <footer class="bg-gray-800 text-gray-400 py-12 border-t mt-20 text-left">
        <div class="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-10">
            <div>
                <p class="text-green-500 font-black text-2xl italic tracking-tighter mb-4 uppercase">바구니삼촌 구매대행</p>
                <div class="text-xs space-y-1.5 opacity-80 leading-relaxed font-black">
                    <p>상호: 바구니삼촌 | 성명: 금창권</p>
                    <p>사업장소재지: 인천광역시 연수구 하모니로158, d동3층317호</p>
                    <p>등록번호: 472-93-02262 | 전화번호: 1666-8320</p>
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
    
    if query:
        for cat in categories:
            products = Product.query.filter(Product.category == cat.name, Product.name.contains(query), Product.is_active == True).all()
            if products: grouped_products[cat] = products
    else:
        for cat in categories:
            grouped_products[cat] = Product.query.filter_by(category=cat.name, is_active=True).all()
    
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
        
        {% if not grouped_products %}
            <div class="py-40 text-center text-gray-400">
                <p class="text-5xl mb-6">🔍</p>
                <p class="font-black text-xl">대행 가능한 상품을 찾지 못했습니다.</p>
                <a href="/" class="text-green-600 underline font-bold mt-4 inline-block">전체 리스트 보기</a>
            </div>
        {% endif %}

        {% for cat, products in grouped_products.items() %}
        <section class="mb-20">
            <div class="mb-10 flex justify-between items-end border-b border-gray-100 pb-4">
                <div>
                    <h2 class="text-2xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                        <span class="w-2 h-10 bg-green-500 rounded-full"></span> {{ cat.name }} 리스트
                    </h2>
                    <p class="text-[10px] md:text-sm text-orange-500 font-bold mt-2 bg-orange-50 px-4 py-1.5 rounded-full w-fit">
                        ⏰ 오후 8시 주문마감 / 🚚 다음날 5시 이전 배송
                    </p>
                </div>
                <a href="/category/{{ cat.name }}" class="text-[11px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1 transition-colors">
                    전체보기 <i class="fas fa-chevron-right text-[10px]"></i>
                </a>
            </div>
            
            <div class="horizontal-scroll no-scrollbar">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[200px] md:w-[280px] transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-xs">대행마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4" onerror="this.src='https://placehold.co/400x400/f0fdf4/166534?text={{ p.name }}'">
                        <div class="absolute bottom-4 left-4"><span class="bg-black/70 text-white text-[10px] px-3 py-1 rounded-lg backdrop-blur-sm font-black">잔여: {{ p.stock }}개</span></div>
                        <div class="absolute top-4 left-4">{% if p.badge %}<span class="badge-tag bg-orange-500 text-white text-[10px] px-3 py-1 rounded-lg shadow-xl uppercase">{{ p.badge }}</span>{% endif %}</div>
                    </a>
                    <div class="p-6 flex flex-col flex-1">
                        <p class="countdown-timer text-[9px] font-bold text-red-500 mb-2" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-sm md:text-base truncate mb-1">{{ p.name }}</h3>
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
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, query=query, grouped_products=grouped_products)

@app.route('/about')
def about_page():
    content = """
    <div class="bg-white py-20 px-4 font-black">
        <div class="max-w-4xl mx-auto">
            <nav class="mb-10"><a href="/" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i> 홈으로 돌아가기</a></nav>
            <h2 class="text-4xl md:text-5xl font-black text-gray-800 mb-12 tracking-tighter leading-tight text-center md:text-left">바구니삼촌 구매대행 몰이란?</h2>
            
            <section class="mb-20">
                <span class="text-green-600 font-black text-xs uppercase tracking-widest mb-4 block">Trust & Experience</span>
                <h3 class="text-2xl md:text-3xl font-black text-gray-800 mb-8">이 구조를 만든 사람들</h3>
                <div class="space-y-6 text-gray-500 text-lg leading-loose font-black">
                    <p>바구니삼촌은 <span class="text-gray-800 font-black">송도에서 오랫동안 물류와 배송을 직접 해온 전문가들</span>이 현장에서 느낀 근본적인 문제를 해결하기 위해 만든 서비스입니다.</p>
                    <div class="w-12 h-1 bg-green-100 my-8"></div>
                    <p>우리는 단순히 온라인 쇼핑몰을 운영하는 것이 아닙니다. <span class="bg-green-50 text-green-700 px-2 py-1 rounded">수만 번의 배송 현장에서 검증된 효율적인 구조</span>를 통해, 가장 신선하고 합리적인 방식으로 물류를 재정의합니다.</p>
                    
                    <div class="p-8 bg-orange-50 rounded-[2rem] border border-orange-100 mt-10 font-black">
                        <p class="text-orange-700 text-base md:text-lg font-black leading-relaxed">
                            우리는 대행 서비스의 질을 높이기 위해 <span class="underline decoration-2">카테고리당 1,900원</span>의 정직한 배송료를 적용합니다.<br class="hidden md:block">
                            배송 효율을 극대화하기 위해 한 카테고리에 4개 이상의 상품 구매 시, 4개마다 1,900원의 배송료가 추가되는 '수량 계단형 배송비' 시스템을 운영하고 있습니다.
                        </p>
                    </div>
                </div>
            </section>

            <section class="bg-gray-900 p-10 md:p-16 rounded-[3rem] text-white font-black">
                <span class="text-yellow-400 font-black text-xs uppercase tracking-widest mb-4 block">Innovation Declaration</span>
                <h3 class="text-3xl md:text-4xl font-black mb-10 tracking-tighter">우리는 다르게 만들었습니다</h3>
                <div class="space-y-8 opacity-90 leading-relaxed text-base md:text-lg">
                    <p>바구니삼촌은 <span class="text-yellow-300">“얼마나 더 싸게 팔까”</span>를 고민하는 대신,</p>
                    <p class="text-xl md:text-2xl text-white font-black leading-tight italic">유통의 과정에서 어디서, 어떻게, 왜 가격이 비싸지는지를 철저히 분석하여 <span class="text-green-400 underline decoration-2 underline-offset-4">판매 마진을 없앤 혁신적인 물류 대행 모델</span>을 만들었습니다.</p>
                    <p class="text-gray-400">이것은 단순한 가격 경쟁을 넘어선, 물류 구조 자체를 바꾸는 방식의 <span class="text-white uppercase tracking-wider">Innovation</span>입니다.</p>
                </div>
            </section>

            <div class="mt-20 text-center">
                <a href="/" class="inline-block bg-green-600 text-white px-16 py-5 rounded-full font-black text-xl shadow-xl hover:bg-green-700 transition">쇼핑하러 가기</a>
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/category/<string:cat_name>')
def category_view(cat_name):
    cat = Category.query.filter_by(name=cat_name).first_or_404()
    products = Product.query.filter_by(category=cat_name, is_active=True).all()
    content = """
    <div class="bg-gray-50 py-16 px-4 border-b text-center">
        <div class="max-w-7xl mx-auto">
            <h2 class="text-4xl md:text-5xl text-gray-800 mb-4 tracking-tighter">{{ cat_name }} 대행 상품</h2>
        </div>
    </div>
    <div class="max-w-7xl mx-auto px-4 py-16">
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-10">
            {% for p in products %}
            {% set is_expired = (p.deadline and p.deadline < now) %}
            <div class="product-card bg-white rounded-[2.5rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-xs">대행마감</div>{% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                    <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4" onerror="this.src='https://placehold.co/400x400/f0fdf4/166534?text={{ p.name }}'">
                    <div class="absolute bottom-4 left-4"><span class="bg-black/70 text-white text-[10px] px-2 py-1 rounded-md font-black">잔여: {{ p.stock }}개</span></div>
                </a>
                <div class="p-6 flex flex-col flex-1">
                    <p class="countdown-timer text-[9px] font-bold text-red-500 mb-2" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                    <h3 class="font-black text-gray-800 text-sm md:text-base truncate mb-1 leading-tight">{{ p.name }}</h3>
                    <p class="text-[11px] text-gray-400 mb-4 font-bold">{{ p.spec }} / {{ p.tax_type }}</p>
                    <div class="mt-auto flex justify-between items-center">
                        <span class="text-xl font-black text-green-600">{{ "{:,}".format(p.price) }}원</span>
                        {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-10 h-10 rounded-2xl text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus"></i></button>{% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, cat_name=cat_name)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    is_taxable = (p.tax_type == '과세')
    total_price = p.price
    if is_taxable:
        supply_price = int(total_price / 1.1)
        vat = total_price - supply_price
    else:
        supply_price = total_price
        vat = 0
        
    content = """
    <div class="max-w-4xl mx-auto px-4 py-8 md:py-16">
        <div class="grid md:grid-cols-2 gap-10 md:gap-16 mb-20 text-center md:text-left">
            <div class="aspect-square rounded-[3rem] overflow-hidden bg-white border shadow-sm relative group">
                <img src="{{ p.image_url }}" class="w-full h-full object-contain p-8 transition-transform duration-700 group-hover:scale-110" onerror="this.src='https://placehold.co/800x800/f0fdf4/166534?text={{ p.name }}'">
            </div>
            <div class="flex flex-col justify-center">
                <div class="flex items-center justify-center md:justify-start gap-3 mb-6">
                    <span class="bg-green-50 text-green-600 px-4 py-1.5 rounded-full text-[11px] tracking-widest uppercase font-black">{{ p.category }}</span>
                    <span class="bg-blue-50 text-blue-600 px-3 py-1.5 rounded-lg text-[10px] font-black">{{ p.tax_type }} 상품</span>
                </div>
                <h2 class="text-3xl md:text-5xl text-gray-800 mb-6 leading-tight tracking-tighter">{{ p.name }}</h2>
                <div class="space-y-3 mb-10 text-xs md:text-base text-gray-400">
                    <p><i class="fas fa-box-open mr-2 text-green-500 w-6"></i> 규격: {{ p.spec }}</p>
                    <p class="text-blue-500"><i class="fas fa-warehouse mr-2 w-6"></i> 잔여수량: {{ p.stock }}개</p>
                    <p class="countdown-timer text-red-500 font-bold" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                </div>
                
                <div class="bg-gray-50 p-8 md:p-10 rounded-[2.5rem] mb-10 border border-gray-100">
                    <span class="text-gray-400 text-xs mb-1 block">최종 장보기 대행가(VAT 포함)</span>
                    <div class="flex items-baseline justify-center md:justify-start gap-1">
                        <span class="text-4xl md:text-6xl font-black text-green-600">{{ "{:,}".format(total_price) }}</span>
                        <span class="text-xl font-black text-green-600">원</span>
                    </div>
                </div>
                
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-6 rounded-[2rem] font-black text-xl md:text-2xl shadow-2xl hover:bg-green-700 transition active:scale-95 flex items-center justify-center gap-3">
                    <i class="fas fa-shopping-basket"></i> 장바구니 담기
                </button>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-6 rounded-[2rem] font-black text-xl md:text-2xl cursor-not-allowed italic">대행이 마감되었습니다</button>
                {% endif %}
            </div>
        </div>
        <div class="border-t pt-16 text-center">
            <h3 class="font-black text-2xl md:text-3xl mb-12 border-l-8 border-green-600 pl-6 text-gray-800 tracking-tighter text-left">삼촌의 상세 정보</h3>
            <div class="bg-white p-4 md:p-12 rounded-[3.5rem] border shadow-sm">
                {% if p.detail_image_url %}<img src="{{ p.detail_image_url }}" class="max-w-full mx-auto rounded-2xl shadow-lg">
                {% else %}<div class="py-32 text-gray-400 italic font-bold">상세 정보가 준비 중입니다.</div>{% endif %}
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, supply_price=supply_price, vat=vat, total_price=total_price)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user); return redirect('/')
        flash("로그인 정보를 확인해주세요.")
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-10 p-10 bg-white rounded-[3rem] shadow-2xl border font-black"><h2 class="text-3xl font-black text-center mb-10 text-green-600 italic uppercase tracking-tighter text-lg">바구니삼촌 구매대행</h2><form method="POST" class="space-y-6"><div><input name="email" type="email" placeholder="이메일" class="w-full p-5 bg-gray-50 rounded-2xl border-none outline-none focus:ring-2 focus:ring-green-100 font-bold" required></div><div><input name="password" type="password" placeholder="비밀번호" class="w-full p-5 bg-gray-50 rounded-2xl border-none outline-none focus:ring-2 focus:ring-green-100 font-bold" required></div><button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black shadow-xl hover:bg-green-700 transition">로그인</button></form><div class="text-center mt-8 font-bold text-xs"><a href="/register" class="text-gray-400 hover:text-green-600 transition">아직 회원이 아니신가요? 회원가입</a></div></div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        if User.query.filter_by(email=email).first(): flash("이미 가입된 이메일입니다."); return redirect('/register')
        db.session.add(User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo))
        db.session.commit()
        flash(f'가입을 축하드립니다. "{name}" 님! 로그인 하시면 됩니다.')
        return redirect('/login')
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-10 p-10 bg-white rounded-[3rem] shadow-2xl border font-black"><h2 class="text-2xl font-black mb-8 text-green-600 tracking-tighter">회원가입</h2><form method="POST" class="space-y-4 text-xs font-black text-gray-800"><input name="name" placeholder="성함" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="email" type="email" placeholder="이메일(ID)" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="phone" placeholder="연락처 (010-0000-0000)" class="w-full p-4 bg-gray-50 rounded-2xl" required><div class="flex gap-2"><input id="address" name="address" placeholder="주소" class="flex-1 p-4 bg-gray-100 rounded-2xl" readonly required><button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-4 rounded-2xl">검색</button></div><input id="address_detail" name="address_detail" placeholder="상세주소" class="w-full p-4 bg-gray-50 rounded-2xl" required><input name="entrance_pw" placeholder="공동현관 비번 (필수)" class="w-full p-4 bg-red-50 rounded-2xl" required><input name="request_memo" placeholder="배송 요청사항" class="w-full p-4 bg-white border-2 border-gray-100 rounded-2xl"><button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black text-lg mt-6 shadow-xl active:scale-95 transition-transform">쇼핑하러 가기</button></form></div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """
    <div class="max-w-4xl mx-auto py-12 px-4 font-black">
        <h2 class="text-3xl font-black mb-10 border-l-8 border-green-600 pl-6 tracking-tighter text-gray-800">내 정보 센터</h2>
        <div class="bg-white p-8 md:p-12 rounded-[3rem] shadow-xl border mb-12 relative overflow-hidden text-xs font-black">
            <div class="relative z-10">
                <p class="text-2xl font-black text-gray-800 mb-2">{{ current_user.name }} 고객님</p>
                <p class="text-gray-400 font-bold text-sm mb-8">{{ current_user.email }}</p>
                <div class="grid md:grid-cols-2 gap-8 pt-8 border-t border-gray-100 text-sm text-center md:text-left">
                    <div><p class="text-[10px] text-gray-400 uppercase tracking-widest mb-2">My Address</p><p class="text-gray-700 leading-relaxed">{{ current_user.address }} {{ current_user.address_detail }}</p></div>
                    <div><p class="text-[10px] text-gray-400 uppercase tracking-widest mb-2">Access Info</p><p class="text-red-500 font-black">🔑 공동현관: {{ current_user.entrance_pw }}</p></div>
                </div>
            </div>
            <a href="/logout" class="absolute top-8 right-8 text-[10px] bg-gray-100 px-3 py-1 rounded-full font-black text-gray-400 hover:bg-gray-200 transition">LOGOUT</a>
        </div>
        <h3 class="text-xl font-black mb-6 flex items-center gap-2 text-gray-800"><i class="fas fa-truck text-green-600"></i> 대행 이용 내역</h3>
        <div class="space-y-4 mb-16 text-xs font-black">
            {% if orders %}
                {% for o in orders %}
                <div class="bg-white p-8 rounded-[2.5rem] shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
                    <p class="text-[10px] text-gray-300 font-black mb-2">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                    <p class="font-black text-gray-800 text-lg leading-tight mb-4">{{ o.product_details }}</p>
                    <div class="flex justify-between items-center pt-4 border-t border-gray-50">
                        <span class="text-gray-400 text-xs">최종 결제액</span>
                        <span class="text-xl text-green-600 font-black">{{ "{:,}".format(o.total_price) }}원</span>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="bg-white p-20 rounded-[3rem] border border-dashed text-center text-gray-400 text-sm">이용 내역이 없습니다.</div>
            {% endif %}
        </div>
    </div>
    """
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

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    cat_counts = {}
    for i in items: cat_counts[i.product_category] = cat_counts.get(i.product_category, 0) + i.quantity
    delivery_fee = sum([((count // 4) + 1) * 1900 for count in cat_counts.values()])
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    content = """
    <div class="max-w-3xl mx-auto py-16 px-4 font-black"><h2 class="text-3xl font-black mb-10 border-l-8 border-green-600 pl-6 tracking-tighter">내 장바구니</h2><div class="bg-white rounded-[3rem] shadow-2xl border overflow-hidden">
    {% if items %}<div class="p-10 space-y-6">{% for i in items %}<div class="flex justify-between items-center border-b border-gray-50 pb-6 last:border-0"><div class="flex-1"><p class="font-black text-lg text-gray-800">{{ i.product_name }}</p><p class="text-green-600 font-black text-sm mt-1">{{ "{:,}".format(i.price) }}원</p></div>
    <div class="flex items-center gap-4 bg-gray-100 px-4 py-2 rounded-2xl">
        <button onclick="minusFromCart('{{i.product_id}}')" class="text-gray-400 hover:text-red-500 font-black text-xl">-</button>
        <span class="font-black text-lg w-6 text-center">{{ i.quantity }}</span>
        <button onclick="addToCart('{{i.product_id}}')" class="text-gray-400 hover:text-green-600 font-black text-xl">+</button>
    </div>
    <form action="/cart/delete/{{i.product_id}}" method="POST" class="ml-4"><button class="text-gray-300 hover:text-red-500 transition"><i class="fas fa-trash-alt text-xl"></i></button></form></div>{% endfor %}
    <div class="bg-gray-50 p-8 rounded-[2rem] space-y-3 mt-10 text-xs"><div class="flex justify-between items-center text-gray-400 uppercase tracking-widest"><span>Items Total</span><span>{{ "{:,}".format(subtotal) }}원</span></div><div class="flex justify-between items-center text-orange-400 uppercase tracking-widest"><span>Delivery Fee (Quantity Tier)</span><span>+ {{ "{:,}".format(delivery_fee) }}원</span></div><div class="flex justify-between items-center pt-4 border-t border-gray-100"><span class="text-gray-600 text-lg font-black">Total Amount</span><span class="text-3xl text-green-600 font-black">{{ "{:,}".format(total) }}원</span></div></div><a href="/order/confirm" class="block text-center bg-green-600 text-white py-6 rounded-[2rem] font-black text-xl shadow-xl mt-8 hover:bg-green-700 transition">주문 확인 및 결제하기</a></div>
    {% else %}<div class="py-32 text-center text-gray-400"><p class="text-6xl mb-6">🧺</p><p class="font-black text-xl mb-10">장바구니가 비어있습니다.</p><a href="/" class="bg-green-600 text-white px-10 py-4 rounded-full font-black shadow-lg">쇼핑하러 가기</a></div>{% endif %}</div></div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, subtotal=subtotal, delivery_fee=delivery_fee, total=total)

@app.route('/order/confirm')
@login_required
def order_confirm():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    cat_counts = {i.product_category: 0 for i in items}
    for i in items: cat_counts[i.product_category] += i.quantity
    delivery_fee = sum([((count // 4) + 1) * 1900 for count in cat_counts.values()])
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    content = """
    <div class="max-w-md mx-auto py-20 px-4 font-black"><h2 class="text-2xl font-black mb-8 border-b pb-4 text-center uppercase">Confirm</h2><div class="bg-white p-10 rounded-[3rem] shadow-2xl border space-y-8 text-sm font-bold">
        <div><span class="text-gray-400 font-black block mb-2 uppercase text-[10px]">Recipient</span><p class="font-black text-2xl text-gray-800">{{ current_user.name }}</p></div>
        <div class="p-8 bg-green-50 rounded-[2.5rem] border border-green-100 font-black"><span class="text-green-600 text-[10px] block mb-2 uppercase">Destination</span><p class="text-lg leading-relaxed">{{ current_user.address }}</p><p class="mt-1 leading-relaxed">{{ current_user.address_detail }}</p></div>
        <div class="p-6 bg-red-50 rounded-[2rem] border border-red-100 text-red-500 font-black"><span class="text-[10px] block mb-2 uppercase">Note</span><p class="font-black text-lg">🔑 {{ current_user.entrance_pw }}</p><p class="mt-2 text-xs opacity-70">📝 {{ current_user.request_memo or '없음' }}</p></div>
        <div class="flex justify-between items-center pt-4 font-black"><span class="text-gray-400 text-base">Final Total</span><span class="text-3xl text-green-600">{{ "{:,}".format(total) }}원</span></div>
        <a href="/order/payment" class="block w-full bg-green-600 text-white py-6 rounded-3xl font-black text-center text-xl shadow-xl mt-6">안전 결제 시작</a>
    </div></div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, total=total)

@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    subtotal = sum(i.price * i.quantity for i in items)
    cat_counts = {i.product_category: 0 for i in items}
    for i in items: cat_counts[i.product_category] += i.quantity
    delivery_fee = sum([((count // 4) + 1) * 1900 for count in cat_counts.values()])
    total = int(subtotal + delivery_fee)
    tax_free = int(sum(i.price * i.quantity for i in items if i.tax_type == '면세'))
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    content = """
    <div class="max-w-md mx-auto py-32 text-center font-black"><div class="w-24 h-24 bg-blue-100 rounded-full flex items-center justify-center text-5xl mx-auto mb-10 text-blue-600 shadow-2xl animate-pulse font-black">🛡️</div><h2 class="text-3xl font-black mb-10 text-gray-800 tracking-tighter">안전 결제창으로<br>이동합니다</h2><button id="payment-button" class="w-full bg-blue-600 text-white py-6 rounded-[2rem] font-black text-xl shadow-xl hover:bg-blue-700 transition">결제 진행</button></div>
    <script>
        var clientKey = "{{ client_key }}";
        var tossPayments = TossPayments(clientKey);
        document.getElementById('payment-button').addEventListener('click', function() {
            tossPayments.requestPayment('카드', { 
                amount: {{ total }}, taxFreeAmount: {{ tax_free }}, orderId: '{{ order_id }}', orderName: '{{ order_name }}', customerName: '{{ user_name }}', 
                successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail', 
            }).catch(function (error) { if (error.code !== 'USER_CANCEL') alert(error.message); });
        });
    </script>
    """
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
        delivery_fee = sum([((count // 4) + 1) * 1900 for count in cat_counts.values()])
        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=int(amt), delivery_fee=delivery_fee, tax_free_amount=tax_free_total, order_id=oid, payment_key=pk, delivery_address=f"({current_user.address}) {current_user.address_detail} (현관:{current_user.entrance_pw})", request_memo=current_user.request_memo))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-40 text-center font-black"><div class="w-24 h-24 bg-green-500 rounded-full flex items-center justify-center text-white text-5xl mx-auto mb-10 shadow-2xl animate-bounce font-black"><i class="fas fa-check"></i></div><h2 class="text-3xl font-black mb-6 text-gray-800 tracking-tighter">Success!</h2><p class="text-gray-400 font-bold mb-16 text-lg font-black">주문이 완료되었습니다.<br>배송일정에 맞춰서 배송됩니다.</p><a href="/" class="inline-block bg-gray-800 text-white px-16 py-5 rounded-full font-black text-xl shadow-xl hover:bg-black transition">홈으로</a></div>""" + FOOTER_HTML)
    return redirect('/')

# --- 관리자 기능 ---
@app.route('/admin')
@login_required
def admin_dashboard():
    is_master = current_user.is_admin
    my_categories = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
    if not is_master and not my_categories: return redirect('/')
    tab, sel_cat = request.args.get('tab', 'products'), request.args.get('category', '전체')
    sel_order_cat = request.args.get('order_cat', '전체')
    start_date_str, end_date_str = request.args.get('start_date', datetime.now().strftime('%Y-%m-%dT00:00')), request.args.get('end_date', (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%dT00:00'))
    start_dt, end_dt = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M'), datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
    users, categories = User.query.all(), Category.query.all()
    all_orders = Order.query.order_by(Order.created_at.desc()).all()
    filtered_orders = Order.query.filter(Order.created_at >= start_dt, Order.created_at <= end_dt).all()
    
    # 통계 집계 로직
    summary = {}
    for o in filtered_orders:
        parts = o.product_details.split(' | ')
        for p_info in parts:
            match = re.match(r'\[(.*?)\] (.*)', p_info)
            if match:
                cat_n, items_str = match.groups()
                if not is_master and cat_n not in my_categories: continue
                if cat_n not in summary: summary[cat_n] = {}
                
                # 상세 아이템 분리: "사과(2), 배(1)"
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

    products = Product.query.all() if sel_cat == '전체' else Product.query.filter_by(category=sel_cat).all()
    if not is_master: products = [p for p in products if p.category in my_categories]
    
    content = """
    <div class="max-w-7xl mx-auto py-10 px-4 font-black">
        <div class="flex justify-between items-center mb-8"><h2 class="text-xl font-black text-orange-700 italic">Admin Dashboard</h2><p class="text-[10px] text-gray-400 font-bold">{{ current_user.email }}</p></div>
        <div class="flex border-b mb-8 bg-white rounded-t-xl overflow-x-auto no-scrollbar text-[11px] font-black">
            <a href="/admin?tab=products" class="px-6 py-4 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품관리</a>
            {% if current_user.is_admin %}<a href="/admin?tab=categories" class="px-6 py-4 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리/권한</a>{% endif %}
            <a href="/admin?tab=orders" class="px-6 py-4 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문관리(통계)</a>
            {% if current_user.is_admin %}<a href="/admin?tab=users" class="px-6 py-4 {% if tab == 'users' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원DB(마스터)</a>{% endif %}
        </div>
        {% if tab == 'products' %}
            <div class="flex justify-between items-center mb-6"><form action="/admin" class="flex gap-2"><input type="hidden" name="tab" value="products"><select name="category" onchange="this.form.submit()" class="border p-2 rounded-xl text-[11px] font-black bg-white"><option value="전체">전체보기</option>{% for c in categories %}{% if current_user.is_admin or c.manager_email == current_user.email %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endif %}{% endfor %}</select></form><a href="/admin/add" class="bg-green-600 text-white px-5 py-3 rounded-xl font-black text-[10px]">+ 상품 등록</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[10px] font-black">
                <table class="w-full text-left font-black">
                    <thead class="bg-gray-50 border-b text-gray-400">
                        <tr>
                            <th class="p-4">상품명/규격/가격</th>
                            <th class="p-4 text-center">재고</th>
                            <th class="p-4 text-center">관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for p in products %}
                        <tr>
                            <td class="p-4 text-gray-700">
                                <b>{{ p.name }}</b> <span class="text-gray-400">({{ p.spec }})</span><br>
                                <span class="text-green-600 font-bold">{{ "{:,}".format(p.price) }}원</span> 
                                <span class="text-orange-500 text-[8px]">[{{p.tax_type}}] {{ p.badge }}</span>
                            </td>
                            <td class="p-4 text-center font-bold">{{ p.stock }}개</td>
                            <td class="p-4 text-center space-x-2"><a href="/admin/edit/{{p.id}}" class="text-blue-500 font-bold">수정</a><a href="/admin/delete/{{p.id}}" class="text-red-300 font-bold">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif tab == 'orders' %}
            <div class="bg-white p-6 rounded-3xl border border-green-100 mb-8 shadow-sm text-xs font-black"><h3 class="font-black text-green-700 mb-4"><i class="fas fa-calculator"></i> 장보기 품목 집계</h3><form action="/admin" method="GET" class="grid grid-cols-1 md:grid-cols-3 gap-4 font-black"><input type="hidden" name="tab" value="orders"><div class="font-black"><label class="text-[10px] font-bold text-gray-400">시작</label><input type="datetime-local" name="start_date" value="{{ start_date_str }}" class="w-full border p-3 rounded-xl"></div><div class=""><label class="text-[10px] font-bold text-gray-400">종료</label><input type="datetime-local" name="end_date" value="{{ end_date_str }}" class="w-full border p-3 rounded-xl"></div><div class="flex items-end"><button class="w-full bg-green-600 text-white py-3 rounded-xl font-black text-xs">집계</button></div></form></div>
            
            {% if summary %}
            <div class="mb-6 font-black">
                <p class="text-[10px] text-gray-400 mb-3 uppercase tracking-widest">Category Tabs (분류별 보기)</p>
                <div class="flex gap-2 overflow-x-auto no-scrollbar pb-2">
                    <a href="/admin?tab=orders&start_date={{start_date_str}}&end_date={{end_date_str}}&order_cat=전체" 
                       class="px-4 py-2 rounded-full text-[10px] font-black {% if sel_order_cat == '전체' %}bg-green-600 text-white shadow-lg{% else %}bg-gray-100 text-gray-400{% endif %}">전체</a>
                    {% for cat_name in summary.keys() %}
                    <a href="/admin?tab=orders&start_date={{start_date_str}}&end_date={{end_date_str}}&order_cat={{cat_name}}" 
                       class="px-4 py-2 rounded-full text-[10px] font-black {% if sel_order_cat == cat_name %}bg-green-600 text-white shadow-lg{% else %}bg-gray-100 text-gray-400{% endif %}">{{ cat_name }}</a>
                    {% endfor %}
                </div>
            </div>

            <div class="space-y-6 mb-12 font-black">
                {% for cat_n, items in summary.items() %}
                {% if sel_order_cat == '전체' or sel_order_cat == cat_n %}
                <div class="bg-white rounded-3xl border overflow-hidden">
                    <div class="bg-gray-50 px-6 py-3 border-b text-sm text-gray-800 font-black flex justify-between items-center">
                        <span>{{ cat_n }} 상세 통계</span>
                        <div class="flex gap-4">
                            <span class="text-[10px] text-blue-600 font-black">총 품목: {{ items|length }}종</span>
                            {% set cat_total_qty = items.values()|sum(attribute='qty') %}
                            <span class="text-[10px] text-orange-600 font-black">총 수량: {{ cat_total_qty }}개</span>
                        </div>
                    </div>
                    <table class="w-full text-left text-[11px] font-black">
                        <thead><tr class="bg-white border-b text-gray-400"> <th class="p-4">품명</th><th class="p-4 text-center">합계수량</th><th class="p-4 text-right">합계금액</th></tr></thead>
                        <tbody>
                            {% for p_n, data in items.items() %}
                            <tr class="border-b font-black"><td class="p-4">{{ p_n }}</td><td class="p-4 text-center text-blue-600 font-bold">{{ data.qty }}개</td><td class="p-4 text-right text-gray-900 font-bold">{{ "{:,}".format(data.price_sum) }}원</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% endif %}
                {% endfor %}
            </div>
            {% endif %}

            <div class="flex justify-between items-center mb-6 font-black"><h3 class="font-black text-gray-800 text-sm">전체 주문 상세 내역</h3><a href="/admin/orders/excel" class="bg-orange-600 text-white px-5 py-3 rounded-xl font-black text-[10px] shadow-sm">엑셀 다운로드</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-x-auto text-[10px] font-medium font-black"><table class="w-full text-left min-w-[1100px]"><thead class="bg-gray-50 border-b text-gray-400 font-bold uppercase"><tr><th class="p-4">일시/고객(ID)</th><th class="p-4">배송주소/메모</th><th class="p-4">상품상세정보</th><th class="p-4 text-right">총금액</th></tr></thead><tbody>{% for o in all_orders %}<tr class="border-b"><td class="p-4"><b>{{ o.created_at.strftime('%m/%d %H:%M') }}</b><br>{{ o.customer_name }}<br>{{ o.customer_email }}</td><td class="p-4 leading-relaxed"><span class="text-blue-600 font-bold">{{ o.delivery_address }}</span><br><span class="text-orange-500 font-bold">📝{{ o.request_memo }}</span></td><td class="p-4 text-gray-500">{{ o.product_details }}</td><td class="p-4 text-right"><b>{{ "{:,}".format(o.total_price) }}원</b></td></tr>{% endfor %}</tbody></table></div>
        {% elif tab == 'users' and current_user.is_admin %}
            <div class="flex justify-between items-center mb-6"><h3 class="font-black text-gray-800 text-sm">회원 목록</h3><a href="/admin/users/excel" class="bg-blue-600 text-white px-5 py-3 rounded-xl font-black text-[10px] shadow-sm">회원 엑셀</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-x-auto text-[10px] font-black">
                <table class="w-full text-left min-w-[1000px]">
                    <thead class="bg-gray-50 border-b text-gray-400 font-bold uppercase">
                        <tr>
                            <th class="p-4">고객명/이메일</th>
                            <th class="p-4">전화번호</th>
                            <th class="p-4">배송지 정보</th>
                            <th class="p-4 text-center">관리</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for u in users %}
                        <tr>
                            <td class="p-4"><b>{{ u.name }}</b><br>{{ u.email }}</td>
                            <td class="p-4">{{ u.phone }}</td>
                            <td class="p-4"><span class="text-blue-600">{{ u.address }}</span><br>{{ u.address_detail }}</td>
                            <td class="p-4 text-center"><a href="/admin/user/delete/{{u.id}}" class="text-red-400 font-bold" onclick="return confirm('정말 탈퇴처리 하시겠습니까?')">탈퇴</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% elif tab == 'categories' and current_user.is_admin %}
            <div class="max-w-2xl space-y-4 text-xs font-black"><form action="/admin/category/add" method="POST" class="bg-white p-6 rounded-2xl border border-gray-100 flex flex-col gap-3 font-black"><p class="text-gray-400 uppercase tracking-widest text-[10px]">Create Category</p><div class="flex gap-2"><input name="cat_name" placeholder="카테고리명" class="border p-4 rounded-xl flex-1 font-bold" required><select name="tax_type" class="border p-4 rounded-xl font-bold"><option value="과세">과세</option><option value="면세">면세</option></select></div><input name="manager_email" placeholder="담당자 이메일 (마스터는 비워두세요)" class="border p-4 rounded-xl w-full font-bold"><button class="bg-green-600 text-white py-4 rounded-xl font-black shadow-lg">생성</button></form>
            <div class="bg-white rounded-2xl border overflow-hidden font-black text-xs"><table class="w-full text-left font-black"><thead class="bg-gray-50 border-b text-gray-400 font-bold uppercase"><tr><th class="p-4">이름</th><th class="p-4">세금</th><th class="p-4 text-center">삭제</th></tr></thead><tbody>{% for c in categories %}<tr class="border-b"><td class="p-4">{{ c.name }}</td><td class="p-4 font-bold">{{ c.tax_type }}</td><td class="p-4 text-center"><a href="/admin/category/delete/{{c.id}}" class="text-red-300">삭제</a></td></tr>{% endfor %}</tbody></table></div></div>
        {% endif %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, start_date_str=start_date_str, end_date_str=end_date_str, summary=summary, all_orders=all_orders, products=products, users=users, categories=categories, tab=tab, sel_cat=sel_cat, my_categories=my_categories, sel_order_cat=sel_order_cat)

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    cats = Category.query.all()
    if request.method == 'POST':
        category_name = request.form['category']
        if not check_admin_permission(category_name): flash("권한이 없습니다."); return redirect('/admin')
        cat_info = Category.query.filter_by(name=category_name).first()
        dl = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        db.session.add(Product(name=request.form['name'], category=category_name, price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer="바구니삼촌", stock=int(request.form['stock']), deadline=dl, badge=request.form['badge'], tax_type=cat_info.tax_type if cat_info else '과세', image_url=save_uploaded_file(request.files.get('main_image')) or "", detail_image_url=save_uploaded_file(request.files.get('detail_image')) or ""))
        db.session.commit(); return redirect('/admin')
    
    return render_template_string(HEADER_HTML + """
    <div class="max-w-xl mx-auto py-10 px-4 font-black text-xs">
        <h2 class="text-xl font-black mb-8 text-orange-600 uppercase tracking-tighter">Add Product</h2>
        <form method="POST" enctype="multipart/form-data" class="bg-white p-8 rounded-3xl shadow-lg space-y-5">
            <div><label>배치 카테고리</label><select name="category" class="w-full border p-4 rounded-xl font-bold">{% for c in cats %}{% if current_user.is_admin or c.manager_email == current_user.email %}<option value="{{c.name}}">{{c.name}}</option>{% endif %}{% endfor %}</select></div>
            <input name="name" placeholder="상품명" class="w-full border p-4 rounded-xl font-bold" required>
            <div class="grid grid-cols-2 gap-4"><input name="price" type="number" placeholder="가격" class="w-full border p-4 rounded-xl font-bold" required><input name="spec" placeholder="규격" class="w-full border p-4 rounded-xl font-bold"></div>
            <div class="grid grid-cols-2 gap-4"><input name="stock" type="number" placeholder="한정수량" class="w-full border p-4 rounded-xl font-bold" value="50" required><input name="deadline" type="datetime-local" class="w-full border p-4 rounded-xl font-bold"></div>
            <input name="origin" placeholder="원산지" class="w-full border p-4 rounded-xl font-bold" value="국산">
            <select name="badge" class="w-full border p-4 rounded-xl font-bold"><option value="">뱃지없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option><option value="강력추천">💎 강력추천</option><option value="최저가">📉 최저가</option></select>
            <div class="space-y-4 border-t pt-4">
                <div><label class="text-[9px] text-gray-400">목록 사진 (메인 이미지)</label><input type="file" name="main_image" class="text-[9px] w-full mt-1"></div>
                <div><label class="text-[9px] text-blue-600 font-bold">상세페이지 이미지 (상세 설명용)</label><input type="file" name="detail_image" class="text-[9px] w-full mt-1"></div>
            </div>
            <button class="w-full bg-green-600 text-white py-5 rounded-xl font-black text-base shadow-lg transition hover:bg-green-700">상품 등록 완료</button>
        </form>
    </div>""", cats=cats)

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_product_edit(pid):
    p = Product.query.get_or_404(pid)
    if not check_admin_permission(p.category): flash("권한이 없습니다."); return redirect('/admin')
    cats = Category.query.all()
    if request.method == 'POST':
        p.name, p.category, p.price, p.spec, p.stock, p.origin, p.badge = request.form['name'], request.form['category'], int(request.form['price']), request.form['spec'], int(request.form['stock']), request.form['origin'], request.form['badge']
        p.deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None
        m_img, d_img = save_uploaded_file(request.files.get('main_image')), save_uploaded_file(request.files.get('detail_image'))
        if m_img: p.image_url = m_img
        if d_img: p.detail_image_url = d_img
        db.session.commit(); return redirect('/admin')
    
    return render_template_string(HEADER_HTML + """
    <div class="max-w-xl mx-auto py-10 px-4 font-black text-xs">
        <h2 class="text-xl font-black mb-8 text-blue-600 uppercase tracking-tighter">Edit Product</h2>
        <form method="POST" enctype="multipart/form-data" class="bg-white p-8 rounded-3xl shadow-lg space-y-5">
            <div><label>카테고리</label><select name="category" class="w-full border p-4 rounded-xl font-bold">{% for c in cats %}{% if current_user.is_admin or c.manager_email == current_user.email %}<option value="{{c.name}}" {% if p.category == c.name %}selected{% endif %}>{{c.name}}</option>{% endif %}{% endfor %}</select></div>
            <input name="name" value="{{p.name}}" class="w-full border p-4 rounded-xl font-bold" required>
            <div class="grid grid-cols-2 gap-4"><input name="price" type="number" value="{{p.price}}" class="w-full border p-4 rounded-xl font-bold" required><input name="spec" value="{{p.spec}}" class="w-full border p-4 rounded-xl font-bold"></div>
            <div class="grid grid-cols-2 gap-4"><input name="stock" type="number" value="{{p.stock}}" class="w-full border p-4 rounded-xl font-bold" required><input name="deadline" type="datetime-local" value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}" class="w-full border p-4 rounded-xl font-bold"></div>
            <input name="origin" value="{{p.origin}}" class="w-full border p-4 rounded-xl font-bold">
            <select name="badge" class="w-full border p-4 rounded-xl font-bold"><option value="" {% if p.badge == '' %}selected{% endif %}>뱃지없음</option><option value="오늘마감" {% if p.badge == '오늘마감' %}selected{% endif %}>🔥 오늘마감</option><option value="삼촌추천" {% if p.badge == '삼촌추천' %}selected{% endif %}>⭐ 삼촌추천</option><option value="강력추천" {% if p.badge == '강력추천' %}selected{% endif %}>💎 강력추천</option><option value="최저가" {% if p.badge == '최저가' %}selected{% endif %}>📉 최저가</option></select>
            <div class="space-y-4 border-t pt-4">
                <div><label class="text-[9px] text-gray-400">목록 사진 업데이트</label><input type="file" name="main_image" class="text-[9px] w-full mt-1"></div>
                <div><label class="text-[9px] text-blue-600 font-bold">상세페이지 이미지 업데이트</label><input type="file" name="detail_image" class="text-[9px] w-full mt-1"></div>
            </div>
            <button class="w-full bg-blue-600 text-white py-5 rounded-xl font-black text-base shadow-lg transition hover:bg-blue-700">수정 완료</button>
        </form>
    </div>""", p=p, cats=cats)

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

@app.route('/admin/category/delete/<int:cid>')
@login_required
def admin_category_delete(cid):
    if not current_user.is_admin: return redirect('/')
    db.session.delete(Category.query.get(cid)); db.session.commit()
    return redirect('/admin?tab=categories')

@app.route('/admin/user/delete/<int:uid>')
@login_required
def admin_user_delete(uid):
    if not current_user.is_admin: return redirect('/')
    db.session.delete(User.query.get(uid)); db.session.commit()
    return redirect('/admin?tab=users')

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    if not current_user.is_admin: return redirect('/admin')
    
    all_categories = [c.name for c in Category.query.all()]
    orders = Order.query.all()
    data = []
    
    for o in orders:
        # 기본 정보
        row = {
            "일시": o.created_at.strftime('%Y-%m-%d %H:%M'),
            "고객": o.customer_name,
            "전화": o.customer_phone,
            "이메일": o.customer_email,
            "주소": o.delivery_address,
            "요청사항": o.request_memo,
            "총액": o.total_price,
            "배송비": o.delivery_fee
        }
        
        # 카테고리별 품명/수량 데이터 초기화
        cat_row_data = {}
        for cat in all_categories:
            cat_row_data[f"[{cat}] 품명"] = ""
            cat_row_data[f"[{cat}] 수량"] = ""
            
        # 상품 상세 정보 파싱
        # o.product_details 예시: "[농산물] 사과(2), 배(1) | [반찬] 콩자반(1)"
        parts = o.product_details.split(' | ')
        for part in parts:
            match = re.match(r'\[(.*?)\] (.*)', part)
            if match:
                cat_name, items_str = match.groups()
                if cat_name in all_categories:
                    # 개별 아이템 분리 (사과(2), 배(1))
                    item_list = items_str.split(', ')
                    names = []
                    qtys = []
                    for item in item_list:
                        it_match = re.match(r'(.*?)\((\d+)\)', item)
                        if it_match:
                            n, q = it_match.groups()
                            names.append(n)
                            qtys.append(q)
                    
                    cat_row_data[f"[{cat_name}] 품명"] = ", ".join(names)
                    cat_row_data[f"[{cat_name}] 수량"] = ", ".join(qtys)
        
        row.update(cat_row_data)
        row["전체상품정보(원본)"] = o.product_details
        data.append(row)
        
    df = pd.DataFrame(data)
    
    # 열 순서 정의
    base_cols = ["일시", "고객", "전화", "이메일", "주소", "요청사항", "총액", "배송비"]
    cat_cols = []
    for cat in all_categories:
        cat_cols.append(f"[{cat}] 품명")
        cat_cols.append(f"[{cat}] 수량")
    
    final_cols = base_cols + cat_cols + ["전체상품정보(원본)"]
    df = df[final_cols]
    
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: 
        df.to_excel(w, index=False)
    out.seek(0)
    
    return send_file(out, download_name=f"UncleOrders_Detailed_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

@app.route('/admin/users/excel')
@login_required
def admin_users_excel():
    if not current_user.is_admin: return redirect('/admin')
    data = [{"성함": u.name, "이메일": u.email, "전화번호": u.phone, "주소": u.address, "상세주소": u.address_detail, "공동현관": u.entrance_pw, "관리자여부": "Y" if u.is_admin else "N"} for u in User.query.all()]
    df = pd.DataFrame(data); out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, download_name=f"UncleUsers_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

def init_db():
    with app.app_context():
        db.create_all()
        cols = [
            ("user", "request_memo", "VARCHAR(500)"), ("category", "tax_type", "VARCHAR(20) DEFAULT '과세'"), ("category", "manager_email", "VARCHAR(120)"), 
            ("product", "badge", "VARCHAR(50)"), ("product", "tax_type", "VARCHAR(20) DEFAULT '과세'"), ("cart", "product_category", "VARCHAR(50)"),
            ("order", "customer_email", "VARCHAR(120)"), ("order", "request_memo", "VARCHAR(500)"), ("order", "tax_free_amount", "INTEGER DEFAULT 0"),
            ("order", "delivery_fee", "INTEGER DEFAULT 0")
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