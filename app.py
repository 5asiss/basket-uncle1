import os
import requests
import base64
from datetime import datetime, timedelta
from io import BytesIO

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
    product_category = db.Column(db.String(50)) # 배송비 계산을 위해 추가
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
    delivery_fee = db.Column(db.Integer, default=0) # 배송비 필드 추가
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
    <title>바구니삼촌몰 - 삼촌이 대신 장봐드립니다</title>
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
        #toast {
            visibility: hidden; min-width: 250px; background-color: #333; color: #fff; text-align: center;
            border-radius: 50px; padding: 16px; position: fixed; z-index: 1000; left: 50%; bottom: 30px;
            transform: translateX(-50%); font-size: 14px; font-weight: bold; transition: 0.5s; opacity: 0;
        }
        #toast.show { visibility: visible; opacity: 1; bottom: 50px; }
    </style>
</head>
<body class="text-left">
    <div id="toast">장바구니에 담겼습니다! 🧺</div>
    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4">
            <div class="flex justify-between h-16 items-center">
                <div class="flex items-center">
                    <a href="/" class="text-xl font-black text-green-600 flex items-center gap-1">
                        <span>🧺</span> <span class="italic tracking-tighter uppercase">Basket Uncle</span>
                    </a>
                </div>
                <div class="flex items-center gap-2">
                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="text-gray-400 relative p-2 hover:text-green-600">
                            <i class="fas fa-shopping-cart text-xl"></i>
                            <span id="cart-count-badge" class="absolute top-0 right-0 bg-red-500 text-white text-[9px] rounded-full px-1.5">{{ cart_count }}</span>
                        </a>
                        <a href="/mypage" class="text-gray-600 font-bold bg-gray-100 px-3 py-1.5 rounded-full text-[11px]">내 정보</a>
                        {% if current_user.is_admin or current_user.email in managers %}<a href="/admin" class="bg-orange-100 text-orange-700 px-3 py-1.5 rounded-full font-bold text-[11px]">관리자</a>{% endif %}
                    {% else %}
                        <a href="/login" class="text-gray-600 font-bold text-xs">로그인</a>
                        <a href="/register" class="bg-green-600 text-white px-4 py-2 rounded-full font-bold text-xs shadow-md">가입</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>
    
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="max-w-7xl mx-auto px-4 mt-4">
          {% for message in messages %}
            <div class="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded relative text-sm font-bold" role="alert">{{ message }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <main class="min-h-screen">
"""

FOOTER_HTML = """
    </main>
    <footer class="bg-gray-800 text-gray-400 py-12 border-t mt-20 text-left">
        <div class="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-10">
            <div>
                <p class="text-green-500 font-black text-2xl italic tracking-tighter mb-4 uppercase">Basket Uncle</p>
                <div class="text-xs space-y-1.5 opacity-80 leading-relaxed">
                    <p>상호: 바구니삼촌 | 성명: 금창권</p>
                    <p>사업장소재지: 인천광역시 연수구 하모니로158, d동3층317호</p>
                    <p>등록번호: 472-93-02262 | 전화번호: 1666-8320</p>
                </div>
            </div>
            <div class="md:text-right text-xs space-y-4">
                <p class="font-bold text-gray-200">고객센터 및 배송문의</p>
                <p>평일 09:00 ~ 18:00 (주말/공휴일 휴무)<br>삼촌이 매일 직접 검수하여 오늘 배달합니다.</p>
                <p class="text-[10px] opacity-40 mt-10">© 2026 Basket Uncle. All Rights Reserved.</p>
            </div>
        </div>
    </footer>
    <script>
        async function addToCart(productId) {
            try {
                const response = await fetch(`/cart/add/${productId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.redirected) {
                    window.location.href = response.url;
                    return;
                }
                const result = await response.json();
                if (result.success) {
                    showToast();
                    document.getElementById('cart-count-badge').innerText = result.cart_count;
                } else { alert(result.message); }
            } catch (error) { console.error('Error:', error); }
        }

        function showToast() {
            const t = document.getElementById("toast");
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
        cart_count = Cart.query.filter_by(user_id=current_user.id).count()
    managers = [c.manager_email for c in Category.query.all() if c.manager_email]
    return dict(cart_count=cart_count, now=datetime.now(), managers=managers)

@app.route('/')
def index():
    categories = Category.query.all()
    grouped_products = {}
    for cat in categories:
        grouped_products[cat] = Product.query.filter_by(category=cat.name, is_active=True).all()
    
    content = """
    <div class="bg-gradient-to-br from-green-600 to-green-900 text-white py-12 md:py-20 px-4 shadow-inner">
        <div class="max-w-7xl mx-auto text-center md:text-left">
            <h2 class="text-3xl md:text-5xl font-black mb-6 leading-tight tracking-tighter">삼촌이 시장에서 <br><span class="text-yellow-300">직접 골라</span> 대신 장봐드려요</h2>
            <p class="text-green-100 text-sm md:text-lg opacity-90 max-w-lg mb-8 mx-auto md:mx-0">매일 새벽, 가장 신선한 상품을 삼촌이 직접 검수하고 문 앞까지 배달해 드립니다.</p>
        </div>
    </div>

    <div class="max-w-7xl mx-auto px-4 py-8">
        {% for cat, products in grouped_products.items() %}
        <section class="mb-12">
            <div class="mb-6 border-b border-gray-100 pb-4 flex justify-between items-end">
                <div>
                    <h2 class="text-xl md:text-2xl font-black text-gray-800 flex items-center gap-2">
                        <span class="w-1.5 h-6 bg-green-500 rounded-full"></span> {{ cat.name }}
                    </h2>
                    <p class="text-[10px] md:text-xs text-orange-500 font-bold mt-1 bg-orange-50 px-3 py-1 rounded-full w-fit">
                        ⏰ 오후 8시 주문마감 / 🚚 다음날 5시 이전 배송
                    </p>
                </div>
                <a href="/category/{{ cat.name }}" class="text-[10px] md:text-xs font-bold text-gray-400 hover:text-green-600 flex items-center gap-1">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            
            <div class="horizontal-scroll no-scrollbar">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-2xl md:rounded-[2.5rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[180px] md:w-[240px] transition-all hover:shadow-md {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[10px] md:text-xs font-black">대행마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-2" onerror="this.src='https://placehold.co/400x400/f0fdf4/166534?text={{ p.name }}'">
                        <div class="absolute bottom-2 left-2"><span class="bg-black/70 text-white text-[9px] px-2 py-1 rounded-md font-bold">잔여: {{ p.stock }}개</span></div>
                        <div class="absolute top-2 left-2">{% if p.badge %}<span class="badge-tag bg-orange-500 text-white text-[9px] px-2 py-0.5 rounded shadow-sm">{{ p.badge }}</span>{% endif %}</div>
                    </a>
                    <div class="p-3 md:p-5 flex flex-col flex-1">
                        <h3 class="font-black text-gray-800 text-xs md:text-sm truncate mb-1">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[10px] text-gray-400 mb-3">{{ p.spec }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-sm md:text-lg font-black text-gray-900">{{ "{:,}".format(p.price) }}원</span>
                            {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-10 md:h-10 rounded-xl text-white shadow hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-xs md:text-base"></i></button>{% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
                <div class="w-4 flex-shrink-0"></div>
            </div>
        </section>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products)

@app.route('/category/<string:cat_name>')
def category_view(cat_name):
    cat = Category.query.filter_by(name=cat_name).first_or_404()
    products = Product.query.filter_by(category=cat_name, is_active=True).all()
    content = """
    <div class="bg-gray-50 py-10 md:py-16 px-4 border-b">
        <div class="max-w-7xl mx-auto text-center">
            <h2 class="text-3xl md:text-4xl font-black text-gray-800 mb-4">{{ cat_name }} 대행 상품</h2>
            <p class="text-gray-400 font-bold text-sm md:text-base">삼촌이 엄선한 신선한 {{ cat_name }} 리스트입니다.</p>
        </div>
    </div>
    <div class="max-w-7xl mx-auto px-4 py-12">
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-8">
            {% for p in products %}
            {% set is_expired = (p.deadline and p.deadline < now) %}
            <div class="product-card bg-white rounded-[2rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col transition-all hover:shadow-xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %}">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-xs font-black">대행마감</div>{% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white">
                    <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4" onerror="this.src='https://placehold.co/400x400/f0fdf4/166534?text={{ p.name }}'">
                    <div class="absolute bottom-4 left-4"><span class="bg-black/70 text-white text-[10px] px-2 py-1 rounded-md font-bold">잔여: {{ p.stock }}개</span></div>
                    <div class="absolute top-4 left-4">{% if p.badge %}<span class="badge-tag bg-orange-500 text-white text-[10px] px-2 py-1 rounded shadow-md">{{ p.badge }}</span>{% endif %}</div>
                </a>
                <div class="p-5 flex flex-col flex-1 text-center md:text-left">
                    <h3 class="font-black text-gray-800 text-sm md:text-base truncate mb-1">{{ p.name }}</h3>
                    <p class="text-[11px] text-gray-400 mb-4">{{ p.spec }} / {{ p.tax_type }}</p>
                    <div class="mt-auto flex justify-between items-center">
                        <span class="text-lg font-black text-green-600">{{ "{:,}".format(p.price) }}원</span>
                        {% if not is_expired and p.stock > 0 %}<button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-10 h-10 rounded-2xl text-white shadow hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus"></i></button>{% endif %}
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
    content = """
    <div class="max-w-4xl mx-auto px-4 py-8 md:py-12">
        <div class="grid md:grid-cols-2 gap-8 md:gap-12 mb-16">
            <div class="aspect-square rounded-[2rem] md:rounded-[3rem] overflow-hidden bg-white border shadow-sm relative">
                <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4" onerror="this.src='https://placehold.co/800x800/f0fdf4/166534?text={{ p.name }}'">
            </div>
            <div class="flex flex-col justify-center">
                <div class="flex items-center gap-2 mb-4"><span class="bg-green-50 text-green-600 px-3 py-1 rounded-full text-[10px] font-black">{{ p.category }} 대행</span><span class="bg-gray-100 text-gray-500 px-2 py-1 rounded text-[9px] font-bold">{{ p.tax_type }}</span></div>
                <h2 class="text-2xl md:text-4xl font-black text-gray-800 mb-4 leading-tight">{{ p.name }}</h2>
                <div class="space-y-1 mb-8 text-xs md:text-sm text-gray-400 font-bold"><p><i class="fas fa-box-open mr-2"></i> 규격: {{ p.spec }}</p><p><i class="fas fa-map-marker-alt mr-2.5"></i> 원산지: {{ p.origin }}</p><p class="text-blue-500 font-black"><i class="fas fa-warehouse mr-2"></i> 현재 잔여수량: {{ p.stock }}개</p></div>
                <div class="bg-gray-50 p-6 md:p-10 rounded-3xl mb-8 border border-gray-100 text-center md:text-left"><span class="text-gray-400 font-bold text-[10px] md:text-xs">구매대행가</span><div class="flex items-baseline justify-center md:justify-start gap-1"><span class="text-3xl md:text-5xl font-black text-green-600">{{ "{:,}".format(p.price) }}원</span></div></div>
                {% if p.stock > 0 and not is_expired %}<button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-5 rounded-2xl font-black text-lg md:text-xl shadow-xl hover:bg-green-700 transition active:scale-95">장바구니 담기</button>
                {% else %}<button class="w-full bg-gray-300 text-white py-5 rounded-2xl font-black text-lg md:text-xl cursor-not-allowed">대행 마감</button>{% endif %}
            </div>
        </div>
        <div class="border-t pt-10"><h3 class="font-black text-xl md:text-2xl mb-8 border-l-4 border-green-600 pl-4">상세 정보</h3><div class="text-center bg-white p-2 md:p-10 rounded-3xl border shadow-sm">{% if p.detail_image_url %}<img src="{{ p.detail_image_url }}" class="max-w-full mx-auto rounded-xl">{% else %}<p class="py-20 text-gray-400 italic text-sm">준비 중입니다.</p>{% endif %}</div></div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user); return redirect('/')
        flash("로그인 정보를 확인해주세요.")
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-10 p-8 bg-white rounded-[2rem] shadow-xl border"><h2 class="text-2xl font-black text-center mb-8 text-green-600 italic uppercase">Basket Uncle</h2><form method="POST" class="space-y-4"><div><input name="email" type="email" placeholder="이메일" class="w-full p-4 bg-gray-50 rounded-xl border-none outline-none focus:ring-2 focus:ring-green-100" required></div><div><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 rounded-xl border-none outline-none focus:ring-2 focus:ring-green-100" required></div><button class="w-full bg-green-600 text-white py-4 rounded-xl font-black shadow-lg hover:bg-green-700 transition">로그인</button></form><div class="text-center mt-6"><a href="/register" class="text-xs text-gray-400 font-bold">회원가입 하기</a></div></div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        if User.query.filter_by(email=email).first(): flash("이미 가입된 이메일입니다."); return redirect('/register')
        db.session.add(User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo))
        db.session.commit()
        # 가입 축하 메시지 요청사항 반영
        flash(f'가입을 축하드립니다. "{name}" 님 로그인 하시면 됩니다.')
        return redirect('/login')
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-10 p-8 bg-white rounded-[2rem] shadow-xl border"><h2 class="text-xl font-black mb-6 text-green-600">회원가입</h2><form method="POST" class="space-y-3 text-xs font-bold"><input name="name" placeholder="성함" class="w-full p-4 bg-gray-50 rounded-xl" required><input name="email" type="email" placeholder="이메일(ID)" class="w-full p-4 bg-gray-50 rounded-xl" required><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 rounded-xl" required><input name="phone" placeholder="연락처 (010-0000-0000)" class="w-full p-4 bg-gray-50 rounded-xl" required><div class="flex gap-2"><input id="address" name="address" placeholder="주소" class="flex-1 p-4 bg-gray-100 rounded-xl" readonly required><button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-4 rounded-xl font-black">검색</button></div><input id="address_detail" name="address_detail" placeholder="상세주소" class="w-full p-4 bg-gray-50 rounded-xl" required><input name="entrance_pw" placeholder="공동현관 비번 (필수)" class="w-full p-4 bg-red-50 rounded-xl" required><input name="request_memo" placeholder="배송 요청사항" class="w-full p-4 bg-white border rounded-xl"><button class="w-full bg-green-600 text-white py-5 rounded-xl font-black text-lg mt-4 shadow-lg">가입 완료</button></form></div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    # 고객센터 정보 추가
    content = """
    <div class="max-w-4xl mx-auto py-10 px-4">
        <h2 class="text-2xl font-black mb-8 border-l-4 border-green-600 pl-4">내 정보</h2>
        <div class="bg-white p-6 rounded-2xl shadow-sm border mb-8 text-xs">
            <p class="text-lg font-black text-gray-800 mb-4">{{ current_user.name }} 고객님</p>
            <div class="space-y-1 text-gray-500"><p>📍 {{ current_user.address }} {{ current_user.address_detail }}</p><p>🔑 비번: {{ current_user.entrance_pw }}</p></div>
            <a href="/logout" class="inline-block mt-6 text-gray-300 underline font-bold">로그아웃</a>
        </div>
        
        <h3 class="text-lg font-black mb-4 flex items-center gap-2"><i class="fas fa-truck text-green-600"></i> 대행 이용 내역</h3>
        <div class="space-y-4 mb-10">
            {% if orders %}
                {% for o in orders %}
                <div class="bg-white p-5 rounded-2xl shadow-sm border">
                    <p class="text-[10px] text-gray-400 mb-1">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                    <p class="font-bold text-sm">{{ o.product_details }}</p>
                    <p class="text-green-600 font-black mt-2">결제액: {{ "{:,}".format(o.total_price) }}원 <span class="text-gray-300 text-[9px]">(배송비: {{ "{:,}".format(o.delivery_fee) }}원 포함)</span></p>
                </div>
                {% endfor %}
            {% else %}
                <div class="bg-white p-10 rounded-2xl border border-dashed text-center text-gray-400 font-bold text-sm">아직 이용 내역이 없습니다.</div>
            {% endif %}
        </div>

        <!-- 고객센터 문의 섹션 추가 -->
        <div class="bg-blue-50 p-8 rounded-[2rem] border border-blue-100">
            <h3 class="font-black text-gray-800 mb-4 flex items-center gap-2">👨‍🏫 도움이 필요하신가요?</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <a href="http://pf.kakao.com/_AIuxkn" target="_blank" class="bg-[#FEE500] text-gray-900 py-4 rounded-2xl font-black text-center shadow-sm flex items-center justify-center gap-2">
                    <i class="fas fa-comment"></i> 카카오톡 채널 문의
                </a>
                <a href="tel:1666-8320" class="bg-gray-800 text-white py-4 rounded-2xl font-black text-center shadow-sm flex items-center justify-center gap-2">
                    <i class="fas fa-phone-alt"></i> 전화 문의 (1666-8320)
                </a>
            </div>
            <p class="text-center text-[10px] text-blue-400 mt-4 font-bold">평일 09:00 ~ 18:00 (주말/공휴일 휴무)</p>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, orders=orders)

@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    if is_expired or p.stock <= 0: return jsonify({"success": False, "message": "마감된 상품입니다."})
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, product_category=p.category, price=p.price, tax_type=p.tax_type))
    db.session.commit()
    return jsonify({"success": True, "cart_count": Cart.query.filter_by(user_id=current_user.id).count()})

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    # 카테고리별 배송비 계산 (카테고리당 1900원)
    unique_cats = set([i.product_category for i in items])
    delivery_fee = len(unique_cats) * 1900
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    
    content = """
    <div class="max-w-3xl mx-auto py-10 px-4"><h2 class="text-2xl font-black mb-8 border-l-4 border-green-600 pl-4">장바구니</h2><div class="bg-white rounded-2xl shadow-xl border overflow-hidden">
    {% if items %}<div class="p-6 space-y-6">{% for i in items %}<div class="flex justify-between items-center border-b border-gray-50 pb-4 last:border-0"><div class="flex-1"><p class="font-black text-sm text-gray-800">{{ i.product_name }}</p><p class="text-green-600 font-bold text-xs mt-1">{{ "{:,}".format(i.price) }}원 × {{ i.quantity }}</p></div><form action="/cart/delete/{{i.product_id}}" method="POST"><button class="text-gray-300 hover:text-red-500"><i class="fas fa-trash-alt"></i></button></form></div>{% endfor %}
    <div class="bg-gray-50 p-6 rounded-xl space-y-2 mt-6">
        <div class="flex justify-between items-center text-xs font-bold text-gray-400"><span>상품 합계</span><span>{{ "{:,}".format(subtotal) }}원</span></div>
        <div class="flex justify-between items-center text-xs font-bold text-orange-400"><span>카테고리별 배송비 ({{ cat_count }}건)</span><span>+ {{ "{:,}".format(delivery_fee) }}원</span></div>
        <div class="flex justify-between items-center pt-2 border-t border-gray-100 font-black"><span class="text-gray-600">최종 대행 결제금액</span><span class="text-2xl text-green-600">{{ "{:,}".format(total) }}원</span></div>
    </div><a href="/order/confirm" class="block text-center bg-green-600 text-white py-5 rounded-xl font-black text-lg shadow-lg mt-6">주문서 확인</a></div>
    {% else %}<div class="py-20 text-center"><p class="text-gray-400 font-bold">비어있습니다.</p><a href="/" class="text-green-600 underline font-black block mt-4 text-sm">쇼핑하러 가기</a></div>{% endif %}</div></div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, subtotal=subtotal, delivery_fee=delivery_fee, total=total, cat_count=len(unique_cats))

@app.route('/cart/delete/<int:pid>', methods=['POST'])
@login_required
def delete_cart(pid):
    Cart.query.filter_by(user_id=current_user.id, product_id=pid).delete(); db.session.commit(); return redirect(url_for('cart'))

@app.route('/order/confirm')
@login_required
def order_confirm():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    unique_cats = set([i.product_category for i in items])
    delivery_fee = len(unique_cats) * 1900
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    
    content = f"""<div class="max-w-md mx-auto py-10 px-4"><h2 class="text-xl font-black mb-6 border-b pb-4 text-gray-800">배송 정보 확인</h2><div class="bg-white p-8 rounded-[2rem] shadow-xl border space-y-6 text-sm"><div><span class="text-gray-400 font-bold block mb-1">받는 분</span><p class="font-black text-lg text-gray-800">{current_user.name}</p></div><div class="p-6 bg-green-50 rounded-2xl border border-green-100 font-black"><span class="text-green-600 text-[10px] block mb-2">배송 주소</span><p>{current_user.address}</p><p class="mt-1">{current_user.address_detail}</p></div><div class="p-6 bg-red-50 rounded-2xl border border-red-100 font-black text-red-500"><span class="text-[10px] block mb-2">출입 및 요청</span><p>🔑 비번: {current_user.entrance_pw}</p><p class="mt-1">📝: {current_user.request_memo or '없음'}</p></div><div class="flex justify-between items-center pt-4 font-black"><span class="text-gray-400 text-sm">최종 결제 금액</span><span class="text-2xl text-green-600">{total:,}원</span></div><a href="/order/payment" class="block w-full bg-green-600 text-white py-5 rounded-2xl font-black text-center text-lg shadow-xl mt-6">지금 결제하기</a></div></div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    unique_cats = set([i.product_category for i in items])
    delivery_fee = len(unique_cats) * 1900
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    tax_free = sum(i.price * i.quantity for i in items if i.tax_type == '면세')
    
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    content = f"""<div class="max-w-md mx-auto py-24 text-center"><div class="w-20 h-20 bg-blue-100 rounded-full flex items-center justify-center text-4xl mx-auto mb-10">🛡️</div><h2 class="text-2xl font-black mb-10 text-gray-800">안전 결제창으로 이동합니다</h2><button id="payment-button" class="w-full bg-blue-600 text-white py-6 rounded-2xl font-black text-xl shadow-xl">결제 진행</button></div>
    <script>
        var tossPayments = TossPayments("{TOSS_CLIENT_KEY}");
        document.getElementById('payment-button').addEventListener('click', function() {{
            tossPayments.requestPayment('카드', {{ amount: {total}, taxFreeAmount: {tax_free}, orderId: '{order_id}', orderName: '{order_name}', customerName: '{current_user.name}', successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail', }});
        }});
    </script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/payment/success')
@login_required
def payment_success():
    pk, oid, amt = request.args.get('paymentKey'), request.args.get('orderId'), request.args.get('amount')
    url, auth_key = "https://api.tosspayments.com/v1/payments/confirm", base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    res = requests.post(url, json={"paymentKey": pk, "amount": amt, "orderId": oid}, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
    if res.status_code == 200:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        # 관리자 요청사항: 카테고리별 상품 분리하여 문자열 생성
        cat_groups = {}
        for i in items:
            if i.product_category not in cat_groups: cat_groups[i.product_category] = []
            cat_groups[i.product_category].append(f"{i.product_name}({i.quantity})")
        
        details = " | ".join([f"[{cat}] {', '.join(prods)}" for cat, prods in cat_groups.items()])
        unique_cats = set([i.product_category for i in items])
        delivery_fee = len(unique_cats) * 1900
        tax_free_total = sum(i.price * i.quantity for i in items if i.tax_type == '면세')
        
        addr = f"({current_user.address}) {current_user.address_detail} (현관:{current_user.entrance_pw})"
        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=int(amt), delivery_fee=delivery_fee, tax_free_amount=tax_free_total, order_id=oid, payment_key=pk, delivery_address=addr, request_memo=current_user.request_memo))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-32 text-center"><h2 class="text-3xl font-black mb-6">주문 완료!</h2><p class="text-gray-400 mb-10 font-bold">삼촌이 출발합니다!</p><a href="/" class="bg-gray-800 text-white px-10 py-4 rounded-xl font-bold">홈으로</a></div>""" + FOOTER_HTML)
    return redirect('/')

# --- 관리자 기능 ---
@app.route('/admin')
@login_required
def admin_dashboard():
    is_master = current_user.is_admin
    my_categories = [c.name for c in Category.query.filter_by(manager_email=current_user.email).all()]
    if not is_master and not my_categories: return redirect('/')

    tab, sel_cat = request.args.get('tab', 'products'), request.args.get('category', '전체')
    users, categories, orders = User.query.all(), Category.query.all(), Order.query.order_by(Order.created_at.desc()).all()
    
    if not is_master:
        if sel_cat == '전체': products = Product.query.filter(Product.category.in_(my_categories)).all()
        else: products = Product.query.filter_by(category=sel_cat).all() if sel_cat in my_categories else []
    else:
        products = Product.query.all() if sel_cat == '전체' else Product.query.filter_by(category=sel_cat).all()

    content = """
    <div class="max-w-7xl mx-auto py-10 px-4">
        <div class="flex justify-between items-center mb-8"><h2 class="text-xl font-black text-orange-700 italic uppercase">Admin Dashboard</h2><p class="text-[10px] text-gray-400 font-bold">{{ current_user.email }}</p></div>
        <div class="flex border-b mb-8 bg-white rounded-t-xl overflow-x-auto no-scrollbar font-black text-[11px]">
            <a href="/admin?tab=products" class="px-6 py-4 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품관리</a>
            {% if current_user.is_admin %}<a href="/admin?tab=categories" class="px-6 py-4 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리/권한</a>{% endif %}
            <a href="/admin?tab=orders" class="px-6 py-4 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문관리(상세)</a>
            {% if current_user.is_admin %}<a href="/admin?tab=users" class="px-6 py-4 {% if tab == 'users' %}border-b-4 border-orange-500 text-orange-600{% endif %}">회원DB(마스터 전용)</a>{% endif %}
        </div>
        {% if tab == 'products' %}
            <div class="flex justify-between items-center mb-6">
                <form action="/admin" class="flex gap-2"><input type="hidden" name="tab" value="products"><select name="category" onchange="this.form.submit()" class="border p-2 rounded-xl text-[11px] font-black bg-white"><option value="전체">전체보기</option>{% for c in categories %}{% if current_user.is_admin or c.name in my_categories %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endif %}{% endfor %}</select></form>
                <a href="/admin/add" class="bg-green-600 text-white px-5 py-3 rounded-xl font-black text-[10px]">+ 상품 등록</a>
            </div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[10px]">
                <table class="w-full text-left"><thead class="bg-gray-50 border-b"><tr><th class="p-4">상품명/세금</th><th class="p-4 text-center">재고</th><th class="p-4">가격</th><th class="p-4 text-center">관리</th></tr></thead>
                <tbody>{% for p in products %}<tr><td class="p-4 font-black text-gray-700">{{ p.name }}<br><span class="text-orange-500">[{{p.tax_type}}] {{ p.badge }}</span></td><td class="p-4 text-center font-bold text-blue-600">{{ p.stock }}개</td><td class="p-4 font-bold">{{ "{:,}".format(p.price) }}원</td><td class="p-4 text-center space-x-2"><a href="/admin/edit/{{p.id}}" class="text-blue-500 font-bold">수정</a><a href="/admin/delete/{{p.id}}" class="text-red-300 font-bold">삭제</a></td></tr>{% endfor %}</tbody></table>
            </div>
        {% elif tab == 'orders' %}
            <div class="flex justify-end mb-6"><a href="/admin/orders/excel" class="bg-orange-600 text-white px-5 py-3 rounded-xl font-black text-[10px]">엑셀 다운로드</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-x-auto text-[10px]">
                <table class="w-full text-left min-w-[1100px]">
                    <thead class="bg-gray-50 border-b text-gray-400"><tr><th class="p-4">일시/주문번호</th><th class="p-4">고객(ID)/연락처</th><th class="p-4">배송주소/요청사항</th><th class="p-4">상품상세 (카테고리별 분리)</th><th class="p-4 text-right">금액(배송비)</th></tr></thead>
                    <tbody>{% for o in orders %}<tr class="border-b"><td class="p-4"><b>{{ o.created_at.strftime('%m/%d %H:%M') }}</b><br><span class="text-gray-300 text-[9px]">{{ o.order_id }}</span></td><td class="p-4"><b>{{ o.customer_name }}</b><br>{{ o.customer_email }}<br>{{ o.customer_phone }}</td><td class="p-4 leading-relaxed"><span class="text-blue-600 font-bold">{{ o.delivery_address }}</span><br><span class="text-orange-500 font-bold">📝{{ o.request_memo }}</span></td><td class="p-4 font-bold text-gray-600">{{ o.product_details }}</td><td class="p-4 text-right font-black"><b>{{ "{:,}".format(o.total_price) }}원</b><br><span class="text-[9px] text-gray-300">(배송비:{{ "{:,}".format(o.delivery_fee) }})</span></td></tr>{% endfor %}</tbody>
                </table>
            </div>
        {% elif tab == 'users' and current_user.is_admin %}
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-[10px]">
                <table class="w-full text-left"><thead class="bg-gray-50 border-b"><tr><th class="p-4">고객명</th><th class="p-4">아이디(이메일)</th><th class="p-4">연락처</th><th class="p-4">가입배송지</th><th class="p-4 text-center">관리</th></tr></thead>
                <tbody>{% for u in users %}<tr><td class="p-4 font-black">{{ u.name }}</td><td class="p-4 font-bold">{{ u.email }}</td><td class="p-4">{{ u.phone }}</td><td class="p-4 truncate max-w-[250px]">{{ u.address }} {{ u.address_detail }}</td><td class="p-4 text-center"><a href="/admin/user/delete/{{u.id}}" class="text-red-400 font-bold" onclick="return confirm('정말 탈퇴처리 하시겠습니까?')">강제탈퇴</a></td></tr>{% endfor %}</tbody></table>
            </div>
        {% elif tab == 'categories' and current_user.is_admin %}
            <div class="max-w-2xl space-y-4 text-xs font-black"><form action="/admin/category/add" method="POST" class="bg-white p-6 rounded-2xl border flex flex-col gap-3"><p class="text-gray-400">새 카테고리 추가</p><div class="flex gap-2"><input name="cat_name" placeholder="카테고리명" class="border p-3 rounded-xl flex-1" required><select name="tax_type" class="border p-3 rounded-xl"><option value="과세">과세</option><option value="면세">면세</option></select></div><input name="manager_email" placeholder="담당자 이메일 (해당 ID 로그인 시 이 카테고리만 관리 가능)" class="border p-3 rounded-xl w-full"><button class="bg-green-600 text-white py-3 rounded-xl">생성하기</button></form>
            <div class="bg-white rounded-2xl border overflow-hidden"><table class="w-full text-left"><thead class="bg-gray-50 border-b"><tr><th class="p-4">이름</th><th class="p-4">세금</th><th class="p-4">담당자</th><th class="p-4 text-center">삭제</th></tr></thead>
            <tbody>{% for c in categories %}<tr class="border-b"><td class="p-4">{{ c.name }}</td><td class="p-4">{{ c.tax_type }}</td><td class="p-4 text-gray-400">{{ c.manager_email or '마스터 전용' }}</td><td class="p-4 text-center"><a href="/admin/category/delete/{{c.id}}" class="text-red-300">삭제</a></td></tr>{% endfor %}</tbody></table></div></div>
        {% endif %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, orders=orders, users=users, categories=categories, tab=tab, sel_cat=sel_cat, my_categories=my_categories)

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
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-10 px-4"><h2 class="text-xl font-black mb-8 text-orange-600 font-black">새 상품 대행 등록</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-8 rounded-3xl shadow-lg space-y-5 text-xs font-bold"><div><label>배치 카테고리</label><select name="category" class="w-full border p-4 rounded-xl">{% for c in cats %}{% if current_user.is_admin or c.manager_email == current_user.email %}<option value="{{c.name}}">{{c.name}}</option>{% endif %}{% endfor %}</select></div><input name="name" placeholder="상품명" class="w-full border p-4 rounded-xl" required><div class="grid grid-cols-2 gap-4"><input name="price" type="number" placeholder="가격" class="w-full border p-4 rounded-xl" required><input name="spec" placeholder="규격 (예: 1kg)" class="w-full border p-4 rounded-xl"></div><div class="grid grid-cols-2 gap-4"><input name="stock" type="number" placeholder="한정수량" class="w-full border p-4 rounded-xl" value="50" required><input name="deadline" type="datetime-local" class="w-full border p-4 rounded-xl"></div><input name="origin" placeholder="원산지" class="w-full border p-4 rounded-xl" value="국산"><select name="badge" class="w-full border p-4 rounded-xl"><option value="">뱃지없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option><option value="강력추천">💎 강력추천</option><option value="최저가">📉 최저가</option></select><div><label>목록 사진</label><input type="file" name="main_image" class="text-[9px]"></div><div><label>상세 설명 사진</label><input type="file" name="detail_image" class="text-[9px]"></div><button class="w-full bg-green-600 text-white py-5 rounded-xl font-black text-base shadow-lg">상품 등록 완료</button></form></div>""", cats=cats)

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
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-10 px-4"><h2 class="text-xl font-black mb-8 text-blue-600">상품 수정</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-8 rounded-3xl shadow-lg space-y-5 text-xs font-bold"><div><label>카테고리</label><select name="category" class="w-full border p-4 rounded-xl">{% for c in cats %}{% if current_user.is_admin or c.manager_email == current_user.email %}<option value="{{c.name}}" {% if p.category == c.name %}selected{% endif %}>{{c.name}}</option>{% endif %}{% endfor %}</select></div><input name="name" value="{{p.name}}" class="w-full border p-4 rounded-xl" required><div class="grid grid-cols-2 gap-4"><input name="price" type="number" value="{{p.price}}" class="w-full border p-4 rounded-xl" required><input name="spec" value="{{p.spec}}" class="w-full border p-4 rounded-xl"></div><div class="grid grid-cols-2 gap-4"><input name="stock" type="number" value="{{p.stock}}" class="w-full border p-4 rounded-xl"><input name="deadline" type="datetime-local" value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}" class="w-full border p-4 rounded-xl"></div><input name="origin" value="{{p.origin}}" class="w-full border p-4 rounded-xl"><button class="w-full bg-blue-600 text-white py-5 rounded-xl font-black text-base shadow-lg">수정 완료</button></form></div>""", p=p, cats=cats)

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
    data = [{"일시": o.created_at.strftime('%Y-%m-%d %H:%M'), "고객": o.customer_name, "전화": o.customer_phone, "이메일": o.customer_email, "주소": o.delivery_address, "요청사항": o.request_memo, "상품정보": o.product_details, "총액": o.total_price, "배송비": o.delivery_fee} for o in Order.query.all()]
    df = pd.DataFrame(data); out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, download_name=f"UncleOrders_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

def init_db():
    with app.app_context():
        db.create_all()
        # 컬럼 자동 보수 및 배송비 필드 추가
        cols = [
            ("user", "request_memo", "VARCHAR(500)"), 
            ("category", "tax_type", "VARCHAR(20) DEFAULT '과세'"), 
            ("category", "manager_email", "VARCHAR(120)"), 
            ("product", "badge", "VARCHAR(50)"), 
            ("product", "tax_type", "VARCHAR(20) DEFAULT '과세'"), 
            ("cart", "product_category", "VARCHAR(50)"),
            ("order", "customer_email", "VARCHAR(120)"), 
            ("order", "request_memo", "VARCHAR(500)"), 
            ("order", "tax_free_amount", "INTEGER DEFAULT 0"),
            ("order", "delivery_fee", "INTEGER DEFAULT 0")
        ]
        for t, c, ct in cols:
            try: db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN {c} {ct}")); db.session.commit()
            except: db.session.rollback()
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        if not Category.query.first():
            db.session.add(Category(name="농산물", tax_type="면세")); db.session.add(Category(name="공동구매", tax_type="과세")); db.session.add(Category(name="반찬", tax_type="과세"))
        if not Product.query.first():
            items = [("농산물", "산지직송 꿀부사 사과", 12000, "2kg", "청송", "삼촌추천", "면세", 20), ("농산물", "제주 당도타이벡 감귤", 8500, "3kg", "제주", "오늘마감", "면세", 15), ("공동구매", "대용량 베이킹소다 세제", 15900, "4L x 2", "국산", "강력추천", "과세", 50), ("반찬", "고소한 견과류 멸치볶음", 6500, "150g", "국산", "삼촌추천", "과세", 10)]
            for cat, name, price, spec, origin, badge, tax, stock in items:
                db.session.add(Product(category=cat, name=name, price=price, spec=spec, origin=origin, badge=badge, tax_type=tax, farmer="바구니농가", stock=stock, deadline=datetime.now()+timedelta(hours=12), is_active=True))
        db.session.commit()

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=5000, debug=True)