import os
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
app.secret_key = "basket_uncle_secure_key_1234"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///basket_uncle.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 이미지 업로드 설정
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

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
    address = db.Column(db.String(200))          # 기본 주소
    address_detail = db.Column(db.String(200))   # 상세 주소
    entrance_pw = db.Column(db.String(100))      # 공동현관 비밀번호
    grade = db.Column(db.String(20), default='RETAIL') 
    is_admin = db.Column(db.Boolean, default=False)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    name = db.Column(db.String(200))
    price_retail = db.Column(db.Integer)    
    price_wholesale = db.Column(db.Integer) 
    original_price = db.Column(db.Integer)  
    spec = db.Column(db.String(100))        
    image_url = db.Column(db.String(500))   
    detail_image_url = db.Column(db.String(500))
    origin_info = db.Column(db.String(200)) 
    is_active = db.Column(db.Boolean, default=True)

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
    phone = db.Column(db.String(20))    
    address = db.Column(db.String(200)) 
    address_detail = db.Column(db.String(200)) 
    entrance_pw = db.Column(db.String(100))    
    product_details = db.Column(db.Text) 
    total_price = db.Column(db.Integer)
    status = db.Column(db.String(20), default='PENDING') 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def save_uploaded_file(file):
    if file and file.filename != '':
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return f"uploads/{filename}"
    return None

# 3. HTML 레이아웃
HEADER_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>바구니삼촌 - 구매대행</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .category-scroll {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        .category-scroll::-webkit-scrollbar { display: none; }
        
        #cart-preview { display: none; }
        #category-bar { transition: all 0.3s ease-in-out; position: sticky; top: 72px; z-index: 40; }
        .shrink { padding-top: 0.5rem; padding-bottom: 0.5rem; font-size: 0.75rem; }
    </style>
</head>
<body class="bg-gray-50 text-gray-800">
    <nav class="bg-white shadow-md p-4 flex justify-between items-center sticky top-0 z-50">
        <a href="/" class="text-xl font-bold text-green-600 flex items-center gap-2">
            <span>🧺</span> 바구니삼촌
        </a>
        <div class="flex items-center gap-4 text-sm">
            {% if current_user.is_authenticated %}
                <div class="relative group">
                    <button onclick="toggleCartPreview()" class="flex items-center gap-1 bg-green-50 px-3 py-1.5 rounded-full text-green-700 font-bold border border-green-200">
                        장바구니 <span class="bg-green-600 text-white px-1.5 rounded-full text-[10px]">+{{ cart_count }}</span>
                    </button>
                    <div id="cart-preview" class="absolute right-0 mt-2 w-64 bg-white shadow-2xl rounded-xl p-4 border border-gray-100 z-[60]">
                        <h4 class="font-bold border-b pb-2 mb-2 text-sm">담은 상품 ({{ cart_count }})</h4>
                        <div class="max-h-40 overflow-y-auto mb-3 text-xs space-y-2">
                            {% for item in cart_items %}
                            <div class="flex justify-between">
                                <span class="truncate w-32">{{ item.product_name }}</span>
                                <span>{{ item.quantity }}개</span>
                            </div>
                            {% endfor %}
                        </div>
                        <div class="border-t pt-2 flex justify-between font-bold text-green-600 mb-3 text-sm">
                            <span>합계</span>
                            <span>{{ cart_total }}원</span>
                        </div>
                        <a href="/cart" class="block text-center bg-green-600 text-white py-2 rounded-lg text-xs">상세보기 및 주문</a>
                    </div>
                </div>
                <a href="/mypage" class="hover:text-green-600">주문내역</a>
                {% if current_user.is_admin %}
                    <a href="/admin/products" class="text-red-600 font-bold underline">관리자</a>
                {% endif %}
                <a href="/logout" class="text-gray-400">로그아웃</a>
            {% else %}
                <a href="/login">로그인</a>
                <a href="/register" class="bg-green-600 text-white px-4 py-2 rounded-full">회원가입</a>
            {% endif %}
        </div>
    </nav>
    <script>
        function toggleCartPreview() {
            const preview = document.getElementById('cart-preview');
            preview.style.display = preview.style.display === 'block' ? 'none' : 'block';
        }
        
        let lastScrollTop = 0;
        window.addEventListener("scroll", function() {
            const catBar = document.getElementById('category-bar');
            if (!catBar) return;
            let st = window.pageYOffset || document.documentElement.scrollTop;
            if (st > lastScrollTop) { catBar.classList.remove('shrink'); } 
            else { catBar.classList.add('shrink'); }
            if (st <= 0) catBar.classList.remove('shrink');
            lastScrollTop = st;
        });

        window.onload = function() {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('registered') === 'true') {
                alert('가입이 완료되었습니다! 반갑습니다.');
            }
        }
    </script>
    <main class="container mx-auto p-4 min-h-screen">
"""

FOOTER_HTML = """
    </main>
    <footer class="bg-white p-8 mt-10 border-t text-center text-gray-500 text-xs">
        <p>© 2026 바구니삼촌 - 마트 가격 그대로 집까지</p>
        <p class="mt-1">가입 시 입력된 주소로 배송되며, 결제는 주문 확정 후 안내됩니다.</p>
    </footer>
</body>
</html>
"""

@app.context_processor
def inject_cart_info():
    if current_user.is_authenticated:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        count = sum(i.quantity for i in items)
        total = sum(i.price * i.quantity for i in items)
        return dict(cart_count=count, cart_items=items, cart_total=total)
    return dict(cart_count=0, cart_items=[], cart_total=0)

# 4. 라우팅 로직
@app.route('/')
def index():
    cat_id = request.args.get('category', type=int)
    search_q = request.args.get('q', '') 
    categories = Category.query.all()
    
    query = Product.query.filter_by(is_active=True)
    if cat_id: query = query.filter_by(category_id=cat_id)
    if search_q: query = query.filter(Product.name.contains(search_q)) 
    products = query.all()
        
    content = """
    <section class="mb-4 text-center py-8 bg-gradient-to-r from-green-50 to-green-100 rounded-3xl">
        <h2 class="text-3xl font-black text-green-800 mb-2">바구니삼촌 장보기</h2>
        <p class="text-green-600 font-medium text-sm">신선함을 직접 고르고 배달합니다.</p>
    </section>

    <div id="category-bar" class="bg-white shadow-sm rounded-full flex overflow-x-auto gap-2 mb-4 p-3 category-scroll border border-gray-100">
        <a href="/" class="whitespace-nowrap px-5 py-1.5 rounded-full border shadow-sm {% if not request.args.get('category') %}bg-green-600 text-white border-green-600{% else %}bg-white text-gray-600{% endif %} font-bold text-sm">전체보기</a>
        {% for cat in categories %}
        <a href="/?category={{cat.id}}" class="whitespace-nowrap px-5 py-1.5 rounded-full border shadow-sm {% if request.args.get('category')|int == cat.id %}bg-green-600 text-white border-green-600{% else %}bg-white text-gray-600{% endif %} font-bold text-sm">
            {{ cat.name }}
        </a>
        {% endfor %}
    </div>

    <div class="mb-8 max-w-md mx-auto">
        <form action="/" method="GET" class="relative">
            <input name="q" value="{{ request.args.get('q','') }}" placeholder="찾으시는 상품명을 입력하세요" class="w-full p-4 pl-6 pr-12 rounded-full border-2 border-green-100 focus:border-green-400 outline-none shadow-sm">
            <button class="absolute right-4 top-1/2 -translate-y-1/2 text-green-600 font-bold">🔍</button>
        </form>
    </div>
    
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-6">
        {% for p in products %}
        <div class="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden group">
            <a href="/product/{{p.id}}" class="block relative aspect-square bg-gray-50">
                {% if p.image_url %}
                    <img src="/static/{{ p.image_url }}" class="w-full h-full object-cover group-hover:scale-105 transition" onerror="this.src='https://placehold.co/400x400?text=이미지준비중'">
                {% else %}<div class="w-full h-full flex items-center justify-center text-gray-300">사진 준비중</div>{% endif %}
            </a>
            <div class="p-4">
                <a href="/product/{{p.id}}"><h3 class="font-bold text-gray-800 mb-1 truncate text-sm">{{ p.name }}</h3></a>
                <p class="text-[10px] text-gray-400 mb-2">{{ p.spec or '규격없음' }}</p>
                <div class="flex flex-col gap-2">
                    <span class="text-green-600 font-black text-base">
                        {% if current_user.is_authenticated and current_user.grade == 'WHOLESALE' %}{{ p.price_wholesale }}원
                        {% else %}{{ p.price_retail }}원{% endif %}
                    </span>
                    <form action="/cart/add/{{p.id}}" method="POST">
                        <button class="w-full bg-gray-100 text-gray-700 py-2 rounded-xl text-xs font-bold hover:bg-green-600 hover:text-white">담기</button>
                    </form>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, categories=categories)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    content = """
    <div class="max-w-5xl mx-auto bg-white p-6 md:p-12 rounded-[2rem] shadow-xl border border-gray-50 mt-6 text-sm">
        <div class="grid md:grid-cols-2 gap-12">
            <div class="aspect-square bg-gray-50 rounded-3xl overflow-hidden">
                {% if p.image_url %}<img src="/static/{{ p.image_url }}" class="w-full h-full object-cover">
                {% else %}<div class="w-full h-full flex items-center justify-center text-gray-300 font-bold text-2xl">사진 준비중</div>{% endif %}
            </div>
            <div class="flex flex-col py-2">
                <span class="text-green-600 font-bold text-xs bg-green-50 w-fit px-3 py-1 rounded-full mb-4">바구니삼촌 추천</span>
                <h2 class="text-3xl font-black text-gray-900 mb-2">{{ p.name }}</h2>
                <p class="text-gray-400 mb-6">{{ p.spec or '' }}</p>
                <div class="bg-gray-50 p-6 rounded-2xl space-y-4 mb-8">
                    <div class="flex justify-between items-center"><span class="text-gray-500">판매가</span><span class="text-2xl font-black text-green-600">{{ p.price_retail }}원</span></div>
                </div>
                <form action="/cart/add/{{p.id}}" method="POST" class="mt-auto">
                    <button class="w-full bg-green-600 text-white py-5 rounded-2xl font-bold text-xl hover:bg-green-700">🧺 장바구니에 담기</button>
                </form>
            </div>
        </div>
        <div class="mt-16 pt-16 border-t border-gray-100">
            <h3 class="text-xl font-black mb-8 border-l-4 border-green-600 pl-4 text-gray-800">상품 상세 정보</h3>
            <div class="text-center">
                {% if p.detail_image_url %}<img src="/static/{{ p.detail_image_url }}" class="w-full max-w-3xl mx-auto rounded-xl shadow-sm">
                {% else %}<div class="bg-green-50 p-10 rounded-3xl text-green-700 italic">"매일 아침 마트에서 가장 신선한 녀석으로 골라옵니다."</div>{% endif %}
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p)

# --- 회원 관리 ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        if User.query.filter_by(email=email).first(): return "이미 가입된 이메일입니다."
        user = User(
            email=email, password=generate_password_hash(request.form['password']),
            name=request.form['name'], phone=request.form['phone'],
            address=request.form['address'], address_detail=request.form['address_detail'], 
            entrance_pw=request.form['entrance_pw']        
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login', registered='true'))
    
    content = """
    <script src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
    <script>
        function execDaumPostcode() {
            new daum.Postcode({
                oncomplete: function(data) {
                    document.getElementById('address').value = data.address;
                    document.getElementById('address_detail').focus();
                }
            }).open();
        }
    </script>
    <div class="max-w-md mx-auto bg-white p-10 rounded-[2.5rem] shadow-2xl mt-10">
        <h2 class="text-2xl font-black mb-8 text-center text-green-700">반가워요! 바구니삼촌</h2>
        <form method="POST" class="space-y-4 text-xs">
            <div><label class="font-bold text-gray-400">이름</label><input name="name" placeholder="실명 입력" class="w-full p-4 bg-gray-50 rounded-2xl border-none outline-none" required></div>
            <div><label class="font-bold text-gray-400">연락처</label><input name="phone" placeholder="010-0000-0000" class="w-full p-4 bg-gray-50 rounded-2xl border-none outline-none" required></div>
            <div><label class="font-bold text-gray-400">배송지 (클릭하여 검색)</label><input id="address" name="address" placeholder="주소 검색을 위해 클릭" readonly onclick="execDaumPostcode()" class="w-full p-4 bg-green-50 rounded-2xl border-none outline-none cursor-pointer" required></div>
            <div><label class="font-bold text-gray-400">상세 주소</label><input id="address_detail" name="address_detail" placeholder="상세 주소 입력" class="w-full p-4 bg-gray-50 rounded-2xl border-none outline-none" required></div>
            <div><label class="font-bold text-red-500">공동현관 비밀번호 (필수)</label><input name="entrance_pw" placeholder="현관 비번 또는 출입방법" class="w-full p-4 bg-red-50 rounded-2xl border-none outline-none" required></div>
            <div class="pt-4 border-t mt-4 space-y-4">
                <div><label class="font-bold text-gray-400">이메일(아이디)</label><input name="email" type="email" placeholder="abc@mail.com" class="w-full p-4 bg-gray-50 rounded-2xl border-none outline-none" required></div>
                <div><label class="font-bold text-gray-400">비밀번호</label><input name="password" type="password" placeholder="••••••••" class="w-full p-4 bg-gray-50 rounded-2xl border-none outline-none" required></div>
            </div>
            <button class="w-full bg-green-600 text-white p-5 rounded-3xl font-black text-xl hover:bg-green-700 shadow-lg transition mt-6">회원가입 완료</button>
        </form>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect('/')
        return "아이디 또는 비밀번호가 틀렸습니다."
    
    content = """
    <div class="max-w-md mx-auto bg-white p-10 rounded-[2.5rem] shadow-2xl mt-10">
        <h2 class="text-2xl font-black mb-10 text-center text-gray-800">로그인</h2>
        <form method="POST" class="space-y-6">
            <input name="email" type="email" placeholder="이메일 주소" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required>
            <input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required>
            <button class="w-full bg-green-600 text-white p-5 rounded-3xl font-black text-xl hover:bg-green-700 transition shadow-lg">로그인하기</button>
        </form>
        <div class="mt-8 text-center text-xs">처음이신가요? <a href="/register" class="text-green-600 font-bold ml-2">회원가입</a></div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/logout')
def logout():
    logout_user(); return redirect('/')

# --- 장바구니 및 주문 ---
@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get(pid)
    price = p.price_wholesale if current_user.grade == 'WHOLESALE' else p.price_retail
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, price=price))
    db.session.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    total = sum(i.price * i.quantity for i in items)
    content = """
    <h2 class="text-2xl font-black mb-8 text-gray-800">장바구니 확인</h2>
    <div class="bg-white rounded-3xl shadow-xl overflow-hidden border border-gray-100">
        {% if items %}
            <div class="p-8 space-y-6">
                {% for i in items %}
                <div class="flex justify-between items-center bg-gray-50 p-4 rounded-2xl text-sm">
                    <div class="flex-1"><p class="font-black text-gray-800">{{ i.product_name }}</p><p class="text-green-600 font-bold">{{ i.price }}원 x {{ i.quantity }}개</p></div>
                    <span class="text-lg font-black text-gray-900">{{ i.price * i.quantity }}원</span>
                    <a href="/cart/delete/{{ i.id }}" class="text-[10px] text-red-400 ml-4">삭제</a>
                </div>
                {% endfor %}
            </div>
            <div class="bg-green-600 p-8 flex justify-between items-center text-white">
                <div><span class="text-green-200 text-xs">최종 합계</span><p class="text-3xl font-black">{{ total }}원</p></div>
                <a href="/order/confirm" class="bg-white text-green-700 px-10 py-4 rounded-2xl font-black text-lg">주문하기</a>
            </div>
        {% else %}<div class="py-20 text-center font-bold text-gray-400 text-sm">장바구니가 텅 비어있어요.</div>{% endif %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, total=total)

@app.route('/cart/delete/<int:id>')
@login_required
def cart_delete(id):
    item = Cart.query.filter_by(id=id, user_id=current_user.id).first()
    if item: db.session.delete(item); db.session.commit()
    return redirect('/cart')

@app.route('/order/confirm')
@login_required
def order_confirm():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    content = """
    <div class="max-w-2xl mx-auto bg-white p-10 rounded-[2.5rem] shadow-2xl mt-6 border-4 border-green-50 text-sm">
        <h2 class="text-2xl font-black mb-8 text-green-800">주문 정보 확인</h2>
        <div class="mb-10 space-y-4">
            <h4 class="font-bold text-gray-400 border-b pb-2">배송지 및 출입정보</h4>
            <p class="text-lg font-black">{{ current_user.name }}님 / {{ current_user.phone }}</p>
            <p class="bg-yellow-50 p-4 rounded-xl font-bold">🏠 {{ current_user.address }}<br>{{ current_user.address_detail }}</p>
            <p class="bg-red-50 p-4 rounded-xl text-red-800 font-bold">🔑 공동현관: {{ current_user.entrance_pw }}</p>
        </div>
        <form action="/order/submit" method="POST"><button class="w-full bg-green-600 text-white py-5 rounded-3xl font-black text-xl">주문 최종 전송</button></form>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/order/submit', methods=['POST'])
@login_required
def submit_order():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    details = ", ".join([f"{i.product_name}({i.quantity})" for i in items])
    total = sum(i.price * i.quantity for i in items)
    order = Order(
        user_id=current_user.id, customer_name=current_user.name, phone=current_user.phone,
        address=current_user.address, address_detail=current_user.address_detail, 
        entrance_pw=current_user.entrance_pw, product_details=details, total_price=total
    )
    db.session.add(order)
    for i in items: db.session.delete(i)
    db.session.commit()
    return redirect('/mypage')

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """<h2 class="text-2xl font-black mb-8">내 주문 내역</h2><div class="space-y-6">{% for o in orders %}<div class="bg-white p-8 rounded-3xl shadow-sm border text-sm"><div><span class="text-[10px] text-gray-400 font-bold">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }}</span><p class="font-black text-gray-800 mt-1">{{ o.product_details }}</p><p class="text-gray-500 text-[10px] mt-2">배송지: {{ o.address }} {{ o.address_detail }}</p></div><div class="flex justify-between items-center mt-4"><span class="text-xl font-black text-green-600">{{ o.total_price }}원</span><span class="bg-gray-100 px-3 py-1 rounded-full text-[10px] font-bold">{{ o.status }}</span></div></div>{% endfor %}</div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, orders=orders)

# --- 관리자 기능 ---
@app.route('/admin/products')
@login_required
def admin_products():
    if not current_user.is_admin: return redirect('/')
    cat_id = request.args.get('category', type=int)
    categories = Category.query.all()
    query = Product.query
    if cat_id: query = query.filter_by(category_id=cat_id)
    products = query.all()
    content = """
    <div class="flex flex-col gap-6 mb-6">
        <div class="flex justify-between items-center bg-white p-6 rounded-3xl shadow-sm">
            <h2 class="text-xl font-bold">상품 관리</h2>
            <div class="flex gap-2"><a href="/admin/users" class="bg-gray-100 text-gray-700 px-4 py-2 rounded-xl text-xs font-bold">회원 관리</a><a href="/admin/add" class="bg-green-600 text-white px-4 py-2 rounded-xl font-bold text-xs">+ 개별 등록</a></div>
        </div>
        <div class="bg-white p-6 rounded-3xl shadow-sm border text-xs">
            <h4 class="font-bold mb-4">카테고리 필터 및 관리</h4>
            <div class="flex flex-wrap gap-2 mb-4">
                <a href="/admin/products" class="px-4 py-2 bg-gray-100 rounded-full font-bold">전체보기</a>
                {% for c in categories %}
                <div class="flex items-center gap-1 bg-green-50 px-3 py-1.5 rounded-full">
                    <a href="/admin/products?category={{c.id}}" class="text-green-700 font-bold">{{c.name}}</a>
                    <a href="/admin/category/delete_all/{{c.id}}" class="text-red-400 font-black ml-1" onclick="return confirm('해당 카테고리 모든 상품을 삭제할까요?')">×</a>
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="bg-white rounded-3xl shadow-sm border overflow-hidden text-xs">
            <table class="w-full text-left">
                <thead class="bg-gray-50 border-b"><tr><th class="p-5">상품명</th><th class="p-5">상태</th><th class="p-5">관리</th></tr></thead>
                <tbody>{% for p in products %}<tr class="border-b">
                    <td class="p-5 font-bold">{{ p.name }}</td>
                    <td class="p-5">{{ '🟢' if p.is_active else '🔴' }}</td>
                    <td class="p-5 space-x-3"><a href="/admin/toggle/{{p.id}}" class="text-blue-500">상태변경</a><a href="/admin/edit/{{p.id}}" class="text-green-600 font-bold">수정</a><a href="/admin/delete/{{p.id}}" class="text-red-400">삭제</a></td>
                </tr>{% endfor %}</tbody>
            </table>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, categories=categories)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin: return redirect('/')
    users = User.query.all()
    content = """
    <div class="flex flex-col gap-6">
        <div class="flex justify-between items-center bg-white p-6 rounded-3xl shadow-sm">
            <h2 class="text-xl font-bold text-gray-800">회원 관리 센터</h2>
            <a href="/admin/users/excel" class="bg-blue-600 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-md hover:bg-blue-700 transition">회원 정보 엑셀 다운로드</a>
        </div>
        <div class="bg-white rounded-3xl shadow-sm border overflow-hidden">
            <table class="w-full text-left">
                <thead class="bg-gray-50 border-b text-[11px] text-gray-400 uppercase tracking-wider">
                    <tr><th class="p-5">이름/아이디</th><th class="p-5">연락처</th><th class="p-5">주소 및 상세</th><th class="p-5">공동현관</th></tr>
                </thead>
                <tbody class="text-[12px]">
                    {% for u in users %}
                    <tr class="border-b hover:bg-gray-50 transition">
                        <td class="p-5"><b>{{ u.name }}</b><br><span class="text-gray-400">{{ u.email }}</span></td>
                        <td class="p-5">{{ u.phone }}</td>
                        <td class="p-5">{{ u.address }}<br><span class="text-green-600 font-bold">{{ u.address_detail }}</span></td>
                        <td class="p-5"><span class="bg-red-50 text-red-700 px-2 py-1 rounded">🔑 {{ u.entrance_pw }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, users=users)

@app.route('/admin/users/excel')
@login_required
def admin_users_excel():
    if not current_user.is_admin: return redirect('/')
    users = User.query.all()
    data = [{
        "이름": u.name, "이메일(아이디)": u.email, "연락처": u.phone, 
        "기본주소": u.address, "상세주소": u.address_detail, "공동현관비번": u.entrance_pw, "회원등급": u.grade
    } for u in users]
    df = pd.DataFrame(data)
    out = BytesIO()
    df.to_excel(out, index=False)
    out.seek(0)
    return send_file(out, download_name=f"members_{datetime.now().strftime('%m%d')}.xlsx", as_attachment=True)

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_add():
    if not current_user.is_admin: return redirect('/')
    categories = Category.query.all()
    if request.method == 'POST':
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_img = save_uploaded_file(request.files.get('detail_image'))
        p = Product(
            name=request.form['name'], category_id=int(request.form['category_id']),
            price_retail=int(request.form['price_retail']), price_wholesale=int(request.form['price_wholesale']),
            spec=request.form['spec'], image_url=main_img if main_img else '',
            detail_image_url=detail_img, is_active=True
        )
        db.session.add(p); db.session.commit()
        return redirect('/admin/products')
    
    content = """
    <div class="max-w-xl mx-auto bg-white p-10 rounded-3xl shadow-xl mt-6 text-xs">
        <h3 class="text-xl font-black mb-8 border-b pb-4">🍎 새 상품 개별 등록</h3>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <div><label class="font-bold">상품명</label><input name="name" class="w-full border p-3 rounded-xl" required></div>
            <div><label class="font-bold">카테고리</label><select name="category_id" class="w-full border p-3 rounded-xl">{% for c in categories %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select></div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="font-bold">소매가</label><input name="price_retail" type="number" class="w-full border p-3 rounded-xl" required></div>
                <div><label class="font-bold">도매가</label><input name="price_wholesale" type="number" class="w-full border p-3 rounded-xl" required></div>
            </div>
            <div><label class="font-bold">규격</label><input name="spec" class="w-full border p-3 rounded-xl" placeholder="예: 500g"></div>
            <div class="bg-green-50 p-6 rounded-2xl space-y-4">
                <p class="font-bold text-green-700">📸 이미지 업로드</p>
                <div>메인 사진: <input type="file" name="main_image"></div>
                <div>상세 내용 사진: <input type="file" name="detail_image"></div>
            </div>
            <button class="w-full bg-green-600 text-white p-5 rounded-2xl font-black text-lg">상품 등록하기</button>
        </form>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, categories=categories)

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_edit(pid):
    if not current_user.is_admin: return redirect('/')
    p = Product.query.get_or_404(pid)
    categories = Category.query.all()
    if request.method == 'POST':
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_img = save_uploaded_file(request.files.get('detail_image'))
        p.name, p.category_id = request.form['name'], int(request.form['category_id'])
        p.price_retail, p.price_wholesale = int(request.form['price_retail']), int(request.form['price_wholesale'])
        p.spec = request.form['spec']
        if main_img: p.image_url = main_img
        if detail_img: p.detail_image_url = detail_img
        db.session.commit(); return redirect('/admin/products')
    
    content = """
    <div class="max-w-xl mx-auto bg-white p-10 rounded-3xl shadow-xl mt-6 text-xs">
        <h3 class="text-xl font-black mb-8 border-b pb-4">✏️ 상품 정보 수정</h3>
        <form method="POST" enctype="multipart/form-data" class="space-y-4">
            <div><label class="font-bold text-gray-500">상품명</label><input name="name" value="{{ p.name }}" class="w-full border p-3 rounded-xl font-bold" required></div>
            <div><label class="font-bold text-gray-500">카테고리</label>
                <select name="category_id" class="w-full border p-3 rounded-xl">
                    {% for c in categories %}
                    <option value="{{ c.id }}" {% if c.id == p.category_id %}selected{% endif %}>{{ c.name }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="font-bold text-gray-500">소매가</label><input name="price_retail" type="number" value="{{ p.price_retail }}" class="w-full border p-3 rounded-xl" required></div>
                <div><label class="font-bold text-gray-500">도매가</label><input name="price_wholesale" type="number" value="{{ p.price_wholesale }}" class="w-full border p-3 rounded-xl" required></div>
            </div>
            <div><label class="font-bold text-gray-500">규격</label><input name="spec" value="{{ p.spec or '' }}" class="w-full border p-3 rounded-xl"></div>
            <div class="bg-blue-50 p-6 rounded-2xl space-y-4 border border-blue-100 mt-4">
                <p class="font-bold text-blue-700">📸 사진 관리 (선택 시 교체됨)</p>
                <div class="flex flex-col gap-2">
                    <label class="text-[10px] text-blue-400">메인 사진 업로드</label>
                    <input type="file" name="main_image" class="text-[10px]">
                </div>
                <div class="flex flex-col gap-2">
                    <label class="text-[10px] text-blue-400">상세내용 사진 업로드</label>
                    <input type="file" name="detail_image" class="text-[10px]">
                </div>
            </div>
            <button class="w-full bg-black text-white p-5 rounded-2xl font-black text-lg shadow-lg hover:bg-gray-800 transition mt-6">정보 수정 완료</button>
        </form>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, categories=categories)

@app.route('/admin/category/delete_all/<int:cat_id>')
@login_required
def admin_cat_delete(cat_id):
    if not current_user.is_admin: return redirect('/')
    Product.query.filter_by(category_id=cat_id).delete(); db.session.commit()
    return redirect('/admin/products')

@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    if not current_user.is_admin: return redirect('/')
    p = Product.query.get(pid)
    if p: Cart.query.filter_by(product_id=pid).delete(); db.session.delete(p); db.session.commit()
    return redirect('/admin/products')

@app.route('/admin/toggle/<int:pid>')
@login_required
def admin_toggle(pid):
    if not current_user.is_admin: return redirect('/')
    p = Product.query.get(pid); p.is_active = not p.is_active; db.session.commit()
    return redirect('/admin/products')

@app.route('/admin/upload', methods=['POST'])
@login_required
def admin_upload():
    if not current_user.is_admin: return redirect('/')
    file = request.files.get('excel_file')
    if not file: return "파일 없음"
    try:
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            name = str(row['상품명'])
            product = Product.query.filter_by(name=name).first()
            if not product:
                product = Product(name=name)
                db.session.add(product)
            product.category_id = int(row['카테고리'])
            product.price_retail = int(row['가격'])
            product.price_wholesale = int(product.price_retail * 0.9)
            product.spec = str(row['규격'])
            product.image_url = str(row['이미지파일명'])
            product.is_active = True
        db.session.commit()
    except Exception as e: return f"오류 발생: {e}"
    return redirect('/admin/products')

def init_db():
    with app.app_context():
        db.create_all()
        new_cols = [
            ("user", "address_detail", "VARCHAR(200)"), ("user", "entrance_pw", "VARCHAR(100)"),
            ("order", "address_detail", "VARCHAR(200)"), ("order", "entrance_pw", "VARCHAR(100)")
        ]
        for table, col, col_type in new_cols:
            try: db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")); db.session.commit()
            except: db.session.rollback()
        cat_list = ["과일", "채소", "양곡/견과류", "정육/계란", "수산/건해산물", "양념/가루/오일", "반찬/냉장/냉동/즉석식품", "면류/통조림/간편식품", "유제품/베이커리", "생수/음료/커피/차", "과자/시리얼/빙과", "바디케어/베이비", "주방/세제/세탁/청소", "생활/잡화", "대용량/식자재", "세트상품"]
        for i, name in enumerate(cat_list, 1):
            if not Category.query.get(i): db.session.add(Category(id=i, name=name))
        if not User.query.filter_by(email="admin@test.com").first():
            db.session.add(User(email="admin@test.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True, grade='WHOLESALE'))
        db.session.commit()

if __name__ == "__main__":
    init_db()
    # 🌟 Render 배포 환경을 위한 설정 (포트 자동 인식)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)