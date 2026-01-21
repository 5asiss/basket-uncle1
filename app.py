import os
import requests
import base64
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from flask import Flask, render_template_string, request, redirect, url_for, session, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text

# 1. 초기 설정
app = Flask(__name__)
app.secret_key = "basket_uncle_direct_trade_key_999"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 토스 페이먼츠 API 키 설정
TOSS_CLIENT_KEY = "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"

# 이미지 업로드 설정
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
    is_admin = db.Column(db.Boolean, default=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

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
    deadline = db.Column(db.DateTime)          
    is_active = db.Column(db.Boolean, default=True)
    tax_type = db.Column(db.String(20), default='과세') 

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer)
    product_name = db.Column(db.String(100))
    price = db.Column(db.Integer)
    quantity = db.Column(db.Integer, default=1)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    customer_name = db.Column(db.String(50))
    customer_phone = db.Column(db.String(20))
    product_details = db.Column(db.Text) 
    total_price = db.Column(db.Integer)
    status = db.Column(db.String(20), default='결제완료') 
    order_id = db.Column(db.String(100)) 
    payment_key = db.Column(db.String(200)) 
    delivery_address = db.Column(db.String(500)) # ⚠️ 에러 원인이었던 컬럼
    created_at = db.Column(db.DateTime, default=datetime.now)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def save_uploaded_file(file):
    if file and file.filename != '':
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"/static/uploads/{filename}"
    return None

# --- HTML 템플릿 ---
HEADER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>바구니삼촌몰 - 시장가 당일배송</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://js.tosspayments.com/v1/payment"></script>
    <script src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8f9fa; }
        .sold-out { filter: grayscale(100%); opacity: 0.7; pointer-events: none; }
        .sold-out-badge { 
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8); color: white; padding: 10px 20px; 
            border-radius: 8px; font-weight: 800; z-index: 10; border: 2px solid white;
            pointer-events: none;
        }
        .countdown-timer { color: #e11d48; font-weight: bold; font-size: 0.7rem; }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .horizontal-slider { -ms-overflow-style: none; scrollbar-width: none; scroll-behavior: smooth; }
    </style>
</head>
<body>
    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16 items-center">
                <div class="flex items-center">
                    <a href="/" class="text-2xl font-bold text-green-600 flex items-center gap-2">
                        <span>🧺</span> <span class="hidden md:block">바구니삼촌</span>
                    </a>
                </div>
                <div class="flex items-center gap-4 text-sm">
                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="text-gray-600 font-medium relative p-2">
                            <i class="fas fa-shopping-cart text-xl text-gray-400"></i>
                            <span class="absolute top-0 right-0 bg-red-500 text-white text-[10px] rounded-full px-1.5">{{ cart_count }}</span>
                        </a>
                        {% if current_user.is_admin %}
                            <a href="/admin" class="bg-orange-100 text-orange-700 px-3 py-1 rounded-full font-bold text-xs">관리자</a>
                        {% endif %}
                        <a href="/logout" class="text-gray-400">로그아웃</a>
                    {% else %}
                        <a href="/login" class="text-gray-600">로그인</a>
                        <a href="/register" class="bg-green-600 text-white px-4 py-2 rounded-full font-bold text-xs">회원가입</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>
    
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="max-w-7xl mx-auto px-4 mt-4">
          {% for message in messages %}
            <div class="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded relative text-sm" role="alert">
              {{ message }}
            </div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <main class="min-h-screen">
"""

FOOTER_HTML = """
    </main>
    <footer class="bg-white py-12 border-t mt-20">
        <div class="max-w-7xl mx-auto px-4 text-center">
            <p class="text-green-600 font-bold mb-2 italic text-lg text-center">BASKET UNCLE</p>
            <p class="text-gray-400 text-xs text-center">배송 전문가가 직접 챙기는 신선 배송 시스템</p>
            <p class="text-gray-400 text-[10px] mt-4 text-center">© 2026 Basket Uncle. All Rights Reserved.</p>
        </div>
    </footer>
    <script>
        function updateCountdowns() {
            const timers = document.querySelectorAll('.countdown-timer');
            const now = new Date().getTime();
            timers.forEach(timer => {
                if(!timer.dataset.deadline) return;
                const deadline = new Date(timer.dataset.deadline).getTime();
                const diff = deadline - now;
                if (diff <= 0) {
                    timer.innerText = "마감됨";
                    const card = timer.closest('.product-card');
                    if (card && !card.classList.contains('sold-out')) {
                        location.reload();
                    }
                } else {
                    const h = Math.floor(diff / (1000 * 60 * 60));
                    const m = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                    const s = Math.floor((diff % (1000 * 60)) / 1000);
                    timer.innerText = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')} 남음`;
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

@app.context_processor
def inject_globals():
    cart_count = 0
    if current_user.is_authenticated:
        cart_count = Cart.query.filter_by(user_id=current_user.id).count()
    return dict(cart_count=cart_count, now=datetime.now())

# --- 메인 화면 ---
@app.route('/')
def index():
    all_categories = Category.query.all()
    grouped_products = {}
    for cat in all_categories:
        grouped_products[cat.name] = Product.query.filter_by(category=cat.name, is_active=True).all()
    
    content = """
    <div class="bg-gradient-to-r from-green-600 to-green-700 text-white py-12 px-4 shadow-inner">
        <div class="max-w-7xl mx-auto">
            <h2 class="text-2xl font-black mb-1 leading-tight text-center md:text-left">바구니삼촌이 고른 오늘의 신선함 🥦</h2>
            <p class="text-green-100 text-xs text-center md:text-left opacity-90">시장의 가격 그대로, 사장님이 직접 문 앞까지 배달합니다.</p>
        </div>
    </div>

    <div class="max-w-7xl mx-auto px-4 py-8">
        {% if not all_categories %}
            <div class="py-20 text-center text-gray-400 text-sm italic">관리자 페이지에서 카테고리를 먼저 설정해주세요.</div>
        {% endif %}

        {% for cat in all_categories %}
        <section class="mb-14">
            <div class="flex justify-between items-center mb-5 px-1 border-b border-gray-100 pb-2">
                <h2 class="text-xl font-black text-gray-800 flex items-center gap-2">
                    <span class="w-1.5 h-6 bg-green-500 rounded-full"></span> {{ cat.name }}
                </h2>
                <a href="{{ 'http://localhost:5001' if cat.name == '농산물' else '#' }}" 
                   class="text-[11px] text-green-600 font-bold bg-green-50 px-3 py-1 rounded-full hover:bg-green-600 hover:text-white transition-colors">
                   전체보기 <i class="fas fa-chevron-right ml-1"></i>
                </a>
            </div>
            
            <div class="flex gap-4 overflow-x-auto horizontal-slider pb-6 no-scrollbar">
                {% if grouped_products[cat.name] %}
                    {% for p in grouped_products[cat.name] %}
                    {% set is_expired = p.deadline < now if p.deadline else False %}
                    {% set is_out_of_stock = p.stock <= 0 %}
                    <div class="product-card flex-none w-[170px] md:w-[240px] bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col hover:shadow-lg transition-shadow {% if is_expired or is_out_of_stock %}sold-out{% endif %}">
                        {% if is_expired or is_out_of_stock %}
                            <div class="sold-out-badge text-xs">판매종료</div>
                        {% endif %}
                        
                        <a href="/product/{{p.id}}" class="relative aspect-square block bg-gray-50 overflow-hidden">
                            <img src="{{ p.image_url }}" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/400x400?text=이미지준비중'">
                            <div class="absolute bottom-2 left-2 flex flex-col gap-1">
                                <span class="bg-black/70 text-white text-[9px] px-2 py-0.5 rounded-full font-bold">남은수량 {{ p.stock }}</span>
                            </div>
                        </a>
                        
                        <div class="p-4 flex flex-col flex-1">
                            <h3 class="font-bold text-gray-800 text-sm mb-1 truncate">{{ p.name }}</h3>
                            <p class="text-[11px] text-gray-400 mb-3 truncate">{{ p.spec }}</p>
                            
                            <div class="mt-auto text-left">
                                <div class="flex justify-between items-end">
                                    <span class="text-base font-black text-gray-900 text-left">{{ "{:,}".format(p.price) }}원</span>
                                    <form action="/cart/add/{{p.id}}" method="POST">
                                        <button class="bg-green-600 p-2 rounded-xl text-white hover:bg-green-700 shadow-md transition transform active:scale-90">
                                            <i class="fas fa-cart-plus text-xs"></i>
                                        </button>
                                    </form>
                                </div>
                                <div class="mt-3 pt-2 border-t border-gray-50 flex justify-between items-center">
                                    <span class="countdown-timer text-[10px] text-red-500 font-bold" data-deadline="{{ p.deadline.isoformat() if p.deadline else '' }}">
                                        --:--:--
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                    <div class="py-16 text-center w-full bg-gray-50 rounded-3xl text-gray-400 text-xs italic">
                        상품 준비 중
                    </div>
                {% endif %}
            </div>
        </section>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products, all_categories=all_categories)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    is_expired = p.deadline < datetime.now() if p.deadline else False
    is_out_of_stock = p.stock <= 0
    content = """
    <div class="max-w-4xl mx-auto px-4 py-10">
        <div class="grid md:grid-cols-2 gap-10 mb-16">
            <div class="aspect-square rounded-3xl overflow-hidden border-2 border-gray-50 bg-gray-50 shadow-sm">
                <img src="{{ p.image_url }}" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/600x600?text=상품준비중'">
            </div>
            <div class="flex flex-col justify-center py-4">
                <div class="flex items-center gap-2 mb-3">
                    <span class="text-green-600 font-black text-xs px-3 py-1 bg-green-50 rounded-full">{{ p.category }}</span>
                    <span class="text-[11px] text-gray-400">{{ p.tax_type }}</span>
                </div>
                <h2 class="text-3xl font-black text-gray-800 mb-4 leading-tight text-left">{{ p.name }}</h2>
                <p class="text-gray-500 text-base mb-8 text-left">{{ p.spec }} / {{ p.origin }}</p>
                <div class="bg-gray-50 p-8 rounded-3xl mb-10 border border-gray-100">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400 font-medium">판매가</span>
                        <span class="text-3xl font-black text-green-600">{{ "{:,}".format(p.price) }}원</span>
                    </div>
                </div>
                {% if not is_expired and not is_out_of_stock %}
                <form action="/cart/add/{{p.id}}" method="POST">
                    <button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black text-xl shadow-xl hover:bg-green-700 transition transform active:scale-95 text-center">장바구니 담기</button>
                </form>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-5 rounded-2xl font-black text-xl cursor-not-allowed text-center">판매 종료되었습니다</button>
                {% endif %}
            </div>
        </div>
        <div class="border-t pt-14 text-center">
            <h3 class="font-black text-xl mb-8 border-l-4 border-green-600 pl-5 text-left text-gray-800 tracking-tighter text-left">상품 상세 안내</h3>
            {% if p.detail_image_url %}
                <img src="{{ p.detail_image_url }}" class="max-w-full mx-auto rounded-2xl shadow-md border">
            {% else %}
                <div class="py-24 bg-gray-50 rounded-3xl text-gray-400 text-sm italic border-2 border-dashed text-center">"상세 정보 준비 중"</div>
            {% endif %}
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, is_out_of_stock=is_out_of_stock)

# --- 회원가입 및 로그인 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email', '')).first()
        if user and check_password_hash(user.password, request.form.get('password', '')):
            login_user(user)
            return redirect('/')
        flash("로그인 정보가 올바르지 않습니다.")
    return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto mt-20 p-10 bg-white rounded-[2.5rem] shadow-2xl border"><h2 class="text-3xl font-black text-center mb-12 text-gray-800 italic text-green-600 text-xl text-center">바구니삼촌 로그인</h2><form method="POST" class="space-y-6"><div class="space-y-2"><label class="text-xs font-bold text-gray-400 ml-1 text-left block">이메일(아이디)</label><input name="email" type="email" placeholder="이메일 주소" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required></div><div class="space-y-2"><label class="text-xs font-bold text-gray-400 ml-1 text-left block">비밀번호</label><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required></div><button class="w-full bg-green-600 text-white p-5 rounded-3xl font-black text-lg shadow-xl hover:bg-green-700 transition text-center">로그인</button></form><div class="mt-8 text-center text-xs text-gray-400 text-center">계정이 없으신가요? <a href="/register" class="text-green-600 font-bold ml-2 underline text-center">회원가입</a></div></div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        pw = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()
        addr = request.form.get('address', '').strip()
        addr_detail = request.form.get('address_detail', '').strip()
        entrance_pw = request.form.get('entrance_pw', '').strip()
        
        if not all([name, email, pw, phone, addr, addr_detail, entrance_pw]):
            flash("모든 항목을 정확히 입력해주세요. 배송에 꼭 필요합니다.")
            return redirect('/register')
        if User.query.filter_by(email=email).first():
            flash("이미 사용 중인 이메일입니다.")
            return redirect('/register')
            
        db.session.add(User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_detail, entrance_pw=entrance_pw))
        db.session.commit()
        flash("환영합니다! 회원가입이 완료되었습니다.")
        return redirect('/login')
        
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-10 p-10 bg-white rounded-[2.5rem] shadow-2xl border">
        <h2 class="text-2xl font-black text-center mb-8 text-green-600 text-center">바구니삼촌 회원가입</h2>
        <form method="POST" class="space-y-4 text-xs text-left">
            <div><label class="font-bold text-gray-400 block text-left">성함</label><input name="name" class="w-full p-3 bg-gray-50 rounded-xl border-none outline-none" required></div>
            <div><label class="font-bold text-gray-400 block text-left">이메일(아이디)</label><input name="email" type="email" placeholder="abc@mail.com" class="w-full p-3 bg-gray-50 rounded-xl border-none outline-none" required></div>
            <div><label class="font-bold text-gray-400 block text-left">비밀번호 (4자 이상)</label><input name="password" type="password" class="w-full p-3 bg-gray-50 rounded-xl border-none outline-none" required></div>
            <div><label class="font-bold text-gray-400 block text-left">휴대폰 번호</label><input name="phone" placeholder="010-0000-0000" class="w-full p-3 bg-gray-50 rounded-xl border-none outline-none" required></div>
            
            <div class="pt-4 border-t text-left">
                <label class="font-bold text-green-600 block text-left">배송지 주소 (다음 API 연동)</label>
                <div class="flex gap-2 mt-2">
                    <input id="address" name="address" placeholder="주소 찾기를 클릭하세요" class="flex-1 p-3 bg-gray-100 rounded-xl border-none outline-none" readonly required>
                    <button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-4 rounded-xl font-bold">주소 찾기</button>
                </div>
                <input id="address_detail" name="address_detail" placeholder="상세주소 (호수 등)" class="w-full p-3 bg-gray-50 rounded-xl border-none outline-none mt-2" required>
            </div>
            
            <div class="p-4 bg-red-50 rounded-2xl border border-red-100 text-left">
                <label class="font-bold text-red-500 block text-left">공동현관 비밀번호 (필수)</label>
                <input name="entrance_pw" placeholder="예: #1234# 또는 없음" class="w-full p-3 bg-white rounded-xl border-none outline-none mt-2" required>
                <p class="text-[9px] text-red-400 mt-1 text-left">* 새벽 배송 및 당일 배송 시 꼭 필요합니다.</p>
            </div>

            <button class="w-full bg-green-600 text-white py-5 rounded-3xl font-black text-lg shadow-xl hover:bg-green-700 transition mt-6 text-center">가입 완료하기</button>
        </form>
    </div>
    """ + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

# --- 🌟 장바구니 관리 기능 보강 ---
@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get(pid)
    if (p.deadline and p.deadline < datetime.now()) or p.stock <= 0:
        flash("해당 상품은 현재 판매 기간이 아니거나 품절되었습니다.")
        return redirect('/')
    
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item:
        if item.quantity < p.stock:
            item.quantity += 1
        else:
            flash(f"죄송합니다. 현재 남은 재고는 {p.stock}개입니다.")
    else:
        db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, price=p.price))
    db.session.commit()
    return redirect(request.referrer or '/')

@app.route('/cart/minus/<int:pid>', methods=['POST'])
@login_required
def minus_cart(pid):
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item:
        if item.quantity > 1:
            item.quantity -= 1
        else:
            db.session.delete(item)
    db.session.commit()
    return redirect(url_for('cart'))

@app.route('/cart/delete/<int:pid>', methods=['POST'])
@login_required
def delete_cart(pid):
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item:
        db.session.delete(item)
    db.session.commit()
    return redirect(url_for('cart'))

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all(); total = sum(i.price * i.quantity for i in items)
    content = """
    <div class="max-w-3xl mx-auto py-12 px-4">
        <h2 class="text-2xl font-black mb-8 border-l-4 border-green-600 pl-4 text-left">내 장바구니</h2>
        <div class="bg-white rounded-3xl shadow-xl border overflow-hidden">
            {% if items %}
                <div class="p-8 space-y-5">
                    {% for i in items %}
                    <div class="flex justify-between items-center border-b pb-5 last:border-0 last:pb-0 text-left">
                        <div class="flex-1 text-left">
                            <p class="font-black text-gray-800 text-base mb-1 text-left">{{ i.product_name }}</p>
                            <p class="text-xs text-green-600 font-bold text-left">{{ "{:,}".format(i.price) }}원</p>
                        </div>
                        <div class="flex items-center gap-4">
                            <!-- 🌟 수량 조절 버튼 -->
                            <div class="flex items-center bg-gray-100 rounded-lg overflow-hidden">
                                <form action="/cart/minus/{{i.product_id}}" method="POST">
                                    <button class="px-3 py-1 hover:bg-gray-200 text-gray-500 font-bold">-</button>
                                </form>
                                <span class="px-2 text-sm font-black w-8 text-center">{{ i.quantity }}</span>
                                <form action="/cart/add/{{i.product_id}}" method="POST">
                                    <button class="px-3 py-1 hover:bg-gray-200 text-gray-500 font-bold">+</button>
                                </form>
                            </div>
                            <span class="font-black text-gray-900 text-lg min-w-[80px] text-right">{{ "{:,}".format(i.price * i.quantity) }}원</span>
                            <!-- 🌟 삭제 버튼 -->
                            <form action="/cart/delete/{{i.product_id}}" method="POST">
                                <button class="text-gray-300 hover:text-red-500 transition ml-2"><i class="fas fa-trash-alt"></i></button>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                <div class="bg-gray-50 p-8 flex justify-between items-center border-t">
                    <span class="font-bold text-gray-500">최종 결제 예정 금액</span>
                    <span class="text-3xl font-black text-green-600 text-right">{{ "{:,}".format(total) }}원</span>
                </div>
                <div class="p-8">
                    <a href="/order/confirm" class="block text-center bg-green-600 text-white py-5 rounded-2xl font-black text-xl shadow-lg hover:bg-green-700 transition text-center">주소 확인 및 결제하기</a>
                </div>
            {% else %}
                <div class="p-24 text-center text-gray-400 text-sm text-center">장바구니가 비어있습니다.</div>
            {% endif %}
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, total=total)

# --- 결제 전 주소 확인 페이지 ---
@app.route('/order/confirm')
@login_required
def order_confirm():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    # 배송 정보가 누락된 회원(예전 가입자) 체크
    if not current_user.address or not current_user.address_detail or not current_user.entrance_pw:
        flash("배송지 정보가 부족합니다. 회원가입 양식대로 정보를 업데이트 해주세요.")
        return redirect('/')
        
    total = sum(i.price * i.quantity for i in items)
    content = f"""
    <div class="max-w-md mx-auto py-16 px-4">
        <h2 class="text-2xl font-black mb-6 border-b pb-4 text-left">배송지 정보를 확인해 주세요</h2>
        <div class="bg-white p-8 rounded-3xl shadow-xl border space-y-6 text-sm text-left">
            <div class="space-y-4 text-left">
                <div class="text-left"><span class="text-gray-400 block mb-1 text-left">받는 분</span><span class="font-bold text-lg text-left">{current_user.name}</span></div>
                <div class="text-left"><span class="text-gray-400 block mb-1 text-left">연락처</span><span class="font-bold text-left">{current_user.phone}</span></div>
                <div class="p-4 bg-green-50 rounded-2xl border border-green-100 text-left">
                    <span class="text-green-600 font-bold block mb-1 text-left"><i class="fas fa-truck mr-1"></i> 배송지 주소</span>
                    <p class="font-black text-gray-800 text-left">{current_user.address}</p>
                    <p class="font-black text-gray-800 mt-1 text-left">{current_user.address_detail}</p>
                </div>
                <div class="p-4 bg-red-50 rounded-2xl border border-red-100 text-left">
                    <span class="text-red-500 font-bold block mb-1 text-left"><i class="fas fa-key mr-1"></i> 공동현관 비밀번호</span>
                    <p class="font-black text-gray-800 text-left">{current_user.entrance_pw}</p>
                </div>
            </div>
            <hr>
            <div class="flex justify-between items-center py-2 text-left">
                <span class="text-gray-400 font-bold text-left">총 결제금액</span>
                <span class="text-2xl font-black text-green-600 text-right">{total:,}원</span>
            </div>
            <div class="flex gap-2 pt-4">
                <a href="/order/payment" class="flex-1 bg-green-600 text-white py-5 rounded-2xl font-black text-center text-lg shadow-xl text-center">주소가 맞습니다 (결제)</a>
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    total = sum(i.price * i.quantity for i in items)
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    content = f"""<div class="max-w-md mx-auto py-24 px-4 text-center"><h2 class="text-2xl font-black mb-6 text-center">결제를 진행합니다</h2><div class="bg-white p-8 rounded-3xl shadow-xl border mb-10 text-left text-sm space-y-4"><div><span class="text-gray-400 block mb-1 text-left">주문명</span><span class="font-black text-gray-800 text-lg text-left">{order_name}</span></div><hr><div><span class="text-gray-400 block mb-1 text-left">최종 결제금액</span><span class="font-black text-3xl text-green-600 text-left">{total:,}원</span></div></div><button id="payment-button" class="w-full bg-blue-600 text-white py-5 rounded-3xl font-black text-xl shadow-2xl hover:bg-blue-700 transform active:scale-95 transition text-center">카드/페이 결제하기</button></div><script>var tossPayments = TossPayments("{TOSS_CLIENT_KEY}"); document.getElementById('payment-button').addEventListener('click', function() {{ tossPayments.requestPayment('카드', {{ amount: {total}, orderId: '{order_id}', orderName: '{order_name}', customerName: '{current_user.name}', successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail', }}); }});</script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/payment/success')
@login_required
def payment_success():
    payment_key, order_id, amount = request.args.get('paymentKey'), request.args.get('orderId'), request.args.get('amount')
    url = "https://api.tosspayments.com/v1/payments/confirm"
    encoded_auth = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    res = requests.post(url, json={"paymentKey": payment_key, "amount": amount, "orderId": order_id}, headers={"Authorization": f"Basic {encoded_auth}", "Content-Type": "application/json"})
    if res.status_code == 200:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        details = ", ".join([f"{i.product_name}({i.quantity}개)" for i in items])
        # ⚠️ 배송 정보 기록 (에러 방지용으로 빈값일 경우 방어 로직 추가)
        full_addr = f"({current_user.address or '주소미입력'}) {current_user.address_detail or ''} / 비번: {current_user.entrance_pw or '없음'}"
        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, product_details=details, total_price=int(amount), order_id=order_id, payment_key=payment_key, delivery_address=full_addr, status='결제완료'))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-32 px-4 text-center"><div class="text-green-600 text-7xl mb-8"><i class="fas fa-check-circle"></i></div><h2 class="text-3xl font-black mb-4 text-center">결제 완료!</h2><p class="text-gray-500 mb-12 text-sm text-center">삼촌이 정성껏 준비해 배달해 드릴게요.</p><a href="/" class="inline-block bg-gray-800 text-white px-10 py-4 rounded-2xl font-black shadow-lg text-center">홈으로 돌아가기</a></div>""" + FOOTER_HTML)
    return redirect(url_for('payment_fail', message=res.json().get('message')))

@app.route('/payment/fail')
def payment_fail():
    content = f"""<div class="max-w-md mx-auto py-32 px-4 text-center"><h2 class="text-2xl font-black mb-4 text-red-500 text-center">결제 실패</h2><p class="mb-10 text-gray-500 text-center">{request.args.get('message', '오류')}</p><a href="/cart" class="bg-gray-100 px-8 py-3 rounded-xl font-bold text-center">장바구니로</a></div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

# --- 관리자 기능 ---
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: return redirect('/')
    active_tab = request.args.get('tab', 'products')
    products, orders, users, categories = Product.query.all(), Order.query.order_by(Order.created_at.desc()).all(), User.query.all(), Category.query.all()
    
    content = """
    <div class="max-w-7xl mx-auto py-10 px-4 text-sm text-left">
        <h2 class="text-xl font-black text-orange-700 mb-8 text-left">바구니삼촌 통합 관리자</h2>
        <div class="flex border-b mb-10 overflow-x-auto whitespace-nowrap bg-white rounded-t-2xl shadow-sm text-left">
            <a href="/admin?tab=products" class="px-8 py-4 {% if active_tab == 'products' %}border-b-4 border-orange-500 font-bold text-orange-600{% else %}text-gray-400{% endif %}">상품 관리</a>
            <a href="/admin?tab=categories" class="px-8 py-4 {% if active_tab == 'categories' %}border-b-4 border-orange-500 font-bold text-orange-600{% else %}text-gray-400{% endif %}">카테고리 설정</a>
            <a href="/admin?tab=orders" class="px-8 py-4 {% if active_tab == 'orders' %}border-b-4 border-orange-500 font-bold text-orange-600{% else %}text-gray-400{% endif %}">주문/배송 정보</a>
        </div>

        {% if active_tab == 'products' %}
            <div class="flex justify-between items-center mb-6 text-left"><a href="/admin/add" class="bg-green-600 text-white px-6 py-3 rounded-2xl font-black text-sm shadow-xl">+ 상품 직접 등록</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-left"><table class="w-full text-left text-xs">
                <thead class="bg-gray-50 border-b text-gray-500 text-left"><tr><th class="p-5 text-left">분류</th><th class="p-5 text-left">상품명</th><th class="p-5 text-left">판매가</th><th class="p-5 text-left">재고</th><th class="p-5 text-center">동작</th></tr></thead>
                <tbody class="text-left">{% for p in products %}<tr class="border-b hover:bg-gray-50 transition text-left"><td class="p-5 text-gray-400 font-bold text-left">{{ p.category }}</td><td class="p-5 font-black text-gray-700 text-left">{{ p.name }}</td><td class="p-5 font-bold text-left">{{ "{:,}".format(p.price) }}원</td><td class="p-5 text-blue-600 font-black text-left">{{ p.stock }}개</td><td class="p-5 text-center"><a href="/admin/delete/{{p.id}}" class="text-red-400 hover:underline">삭제</a></td></tr>{% endfor %}</tbody>
            </table></div>
        {% elif active_tab == 'orders' %}
            <div class="flex justify-end mb-6 text-left"><a href="/admin/orders/excel" class="bg-orange-600 text-white px-6 py-3 rounded-2xl font-black text-sm shadow-xl">주문 엑셀 다운로드</a></div>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden text-left"><table class="w-full text-left text-xs text-left">
                <thead class="bg-gray-50 border-b text-left"><tr><th class="p-5 text-left">일시</th><th class="p-5 text-left">고객/배송지</th><th class="p-5 text-left">주문내용</th><th class="p-5 text-right text-right">금액</th></tr></thead>
                <tbody class="text-left">{% for o in orders %}<tr class="border-b hover:bg-gray-50 transition text-left"><td class="p-5 text-gray-400 text-left">{{ o.created_at.strftime('%m/%d %H:%M') }}</td><td class="p-5 text-left"><b>{{ o.customer_name }}</b> ({{ o.customer_phone }})<br><span class="text-[10px] text-blue-600">{{ o.delivery_address }}</span></td><td class="p-5 truncate max-w-[200px] text-left">{{ o.product_details }}</td><td class="p-5 text-right text-green-600 font-black text-base text-right">{{ "{:,}".format(o.total_price) }}원</td></tr>{% endfor %}</tbody>
            </table></div>
        {% endif %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, orders=orders, users=users, categories=categories, active_tab=active_tab)

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    if not current_user.is_admin: return redirect('/')
    cats = Category.query.all()
    if request.method == 'POST':
        dl = datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form['deadline'] else None
        p = Product(name=request.form['name'], category=request.form['category'], tax_type=request.form['tax_type'], price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer=request.form['farmer'], image_url=save_uploaded_file(request.files.get('main_image')) or "", detail_image_url=save_uploaded_file(request.files.get('detail_image')), stock=int(request.form['stock']), deadline=dl, is_active=True)
        db.session.add(p); db.session.commit(); return redirect('/admin')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-12 px-4 text-left"><h2 class="text-3xl font-black mb-10 text-orange-700 italic text-left">ADD PRODUCT</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-10 rounded-[2.5rem] shadow-2xl border space-y-6 text-sm text-left"><div><label class="block font-black text-gray-600 ml-1 text-left">카테고리</label><select name="category" class="w-full bg-gray-100 p-4 rounded-2xl outline-none">{% for c in cats %}<option value="{{c.name}}">{{c.name}}</option>{% endfor %}</select></div><div class="space-y-2"><label class="block font-black text-gray-600 ml-1 text-left">과세/면세</label><select name="tax_type" class="w-full border-none bg-gray-100 p-4 rounded-2xl"><option value="과세">과세</option><option value="면세">면세</option></select></div><div class="space-y-2"><label class="block font-black text-gray-600 ml-1 text-left">상품명</label><input name="name" class="w-full border-none bg-gray-100 p-4 rounded-2xl" required></div><div class="grid grid-cols-2 gap-4 text-left"><div class="space-y-2 text-left"><label class="block font-black text-gray-600 ml-1 text-left">판매가격</label><input name="price" type="number" class="w-full border-none bg-gray-100 p-4 rounded-2xl text-left" required></div><div class="space-y-2 text-left"><label class="block font-black text-gray-600 ml-1 text-left">규격</label><input name="spec" class="w-full border-none bg-gray-100 p-4 rounded-2xl text-left"></div></div><div class="grid grid-cols-2 gap-4 text-left"><div class="space-y-2 text-left"><label class="block font-black text-gray-600 ml-1 text-left">한정재고</label><input name="stock" type="number" class="w-full border-none bg-gray-100 p-4 rounded-2xl text-left" value="50"></div><div class="space-y-2 text-left"><label class="block font-black text-gray-600 ml-1 text-left">마감시간</label><input name="deadline" type="datetime-local" class="w-full border-none bg-gray-100 p-4 rounded-2xl text-left" required></div></div><div><label class="block font-black text-green-700 ml-1 text-left">메인 사진</label><input type="file" name="main_image" class="w-full text-xs text-left"></div><div><label class="block font-black text-blue-700 ml-1 text-left">상세 사진</label><input type="file" name="detail_image" class="w-full text-xs text-left"></div><button class="w-full bg-green-600 text-white py-5 rounded-[2rem] font-black text-xl shadow-xl text-center">상품 등록 완료</button></form></div>""", cats=cats)

@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    if not current_user.is_admin: return redirect('/')
    db.session.delete(Product.query.get(pid)); db.session.commit(); return redirect('/admin')

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    if not current_user.is_admin: return redirect('/')
    data = [{"결제일시": o.created_at.strftime('%Y-%m-%d %H:%M'), "주문번호": o.order_id, "고객명": o.customer_name, "연락처": o.customer_phone, "주문내용": o.product_details, "금액": o.total_price, "배송지정보": o.delivery_address} for o in Order.query.all()]
    df = pd.DataFrame(data); out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, download_name=f"Uncle_Orders_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

# --- 초기 데이터베이스 구축 및 테스트용 상품 9개 ---
def init_db():
    with app.app_context():
        db.create_all()
        # ⚠️ DB가 이미 존재할 경우, 누락된 칸(delivery_address 등)을 자동으로 추가하는 안전 로직
        cols = [
            ("user", "is_admin", "BOOLEAN DEFAULT FALSE"), 
            ("user", "address_detail", "VARCHAR(200)"),
            ("user", "entrance_pw", "VARCHAR(100)"),
            ("product", "stock", "INTEGER DEFAULT 10"), 
            ("product", "deadline", "DATETIME"), 
            ("product", "detail_image_url", "VARCHAR(500)"), 
            ("product", "tax_type", "VARCHAR(20) DEFAULT '과세'"), 
            ("order", "customer_phone", "VARCHAR(20)"), 
            ("order", "order_id", "VARCHAR(100)"), 
            ("order", "payment_key", "VARCHAR(200)"),
            ("order", "delivery_address", "VARCHAR(500)")
        ]
        for t, c, ct in cols:
            try: db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN {c} {ct}")); db.session.commit()
            except: db.session.rollback() 

        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True, address="서울시 강남구", address_detail="101호", entrance_pw="0000"))
        
        if not Category.query.first():
            for name in ['농산물', '공동구매', '반찬']:
                db.session.add(Category(name=name))
        
        if not Product.query.first():
            test_items = [
                ("농산물", "산지직송 싱싱 흙당근", 4500, "1kg", "제주"),
                ("농산물", "고당도 꿀부사 사과", 12000, "3kg", "청송"),
                ("농산물", "강원도 햇 감자", 5500, "2kg", "강원"),
                ("공동구매", "대용량 액체 세제 4L", 15000, "1통", "국산"),
                ("공동구매", "무선 미니 청소기", 49000, "1개", "중국"),
                ("공동구매", "프리미엄 캠핑 의자", 32000, "1세트", "베트남"),
                ("반찬", "고소한 멸치볶음", 6500, "200g", "본사"),
                ("반찬", "양념 깻잎 장아찌", 5000, "300g", "본사"),
                ("반찬", "매콤 진미채 볶음", 7200, "150g", "본사")
            ]
            for cat, name, price, spec, origin in test_items:
                db.session.add(Product(category=cat, name=name, price=price, spec=spec, origin=origin, farmer="바구니농가", stock=30, deadline=datetime.now() + timedelta(days=2), is_active=True))
        db.session.commit()

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=5000, debug=True)