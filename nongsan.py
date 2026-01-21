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

# 토스 페이먼츠 API 키 설정 (제공해주신 테스트 키)
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
    is_admin = db.Column(db.Boolean, default=False)

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
    order_id = db.Column(db.String(100)) # 토스 주문번호
    payment_key = db.Column(db.String(200)) # 토스 결제키
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
        .countdown { color: #e11d48; font-weight: bold; font-size: 0.7rem; }
        .no-scrollbar::-webkit-scrollbar { display: none; }
    </style>
</head>
<body>
    <nav class="bg-white shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16 items-center">
                <div class="flex items-center">
                    <a href="/" class="text-2xl font-bold text-green-600">🧺 바구니삼촌</a>
                    <span class="ml-4 text-gray-400 hidden md:block text-xs">| 시장가격 당일배송</span>
                </div>
                <div class="flex items-center gap-4 text-sm">
                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="text-gray-600 font-medium relative">
                            <i class="fas fa-shopping-cart text-xl text-gray-400"></i>
                            <span class="absolute -top-2 -right-2 bg-red-500 text-white text-[10px] rounded-full px-1.5">{{ cart_count }}</span>
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
    <main class="min-h-screen">
"""

FOOTER_HTML = """
    </main>
    <footer class="bg-white py-12 border-t mt-20">
        <div class="max-w-7xl mx-auto px-4 text-center">
            <p class="text-green-600 font-bold mb-2 italic">BASKET UNCLE</p>
            <p class="text-gray-400 text-xs">매일 아침 시장 가격 그대로, 당일 배송해 드립니다.</p>
            <p class="text-gray-400 text-[10px] mt-4">© 2026 Basket Uncle. All Rights Reserved.</p>
        </div>
    </footer>
    <script>
        function updateCountdowns() {
            const timers = document.querySelectorAll('.countdown-timer');
            const now = new Date().getTime();
            
            timers.forEach(timer => {
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

@app.route('/')
def index():
    cat = request.args.get('category', '전체')
    if cat == '전체':
        products = Product.query.filter_by(is_active=True).all()
    else:
        products = Product.query.filter_by(category=cat, is_active=True).all()
    
    content = """
    <div class="bg-gradient-to-r from-green-600 to-green-700 text-white py-10 px-4">
        <div class="max-w-7xl mx-auto">
            <h2 class="text-2xl font-black mb-2 leading-tight">오늘 아침 시장가격 그대로<br>문 앞까지 당일 배송 🚀</h2>
            <p class="text-green-100 text-xs">중간 유통 마진 없이 신선함을 직접 배달합니다.</p>
        </div>
    </div>

    <div class="max-w-7xl mx-auto px-4 py-8">
        <div class="flex gap-2 overflow-x-auto pb-6 no-scrollbar">
            {% for c in ['전체', '과일', '채소', '쌀/잡곡', '기타'] %}
            <a href="/?category={{c}}" class="px-5 py-2 rounded-full border text-xs font-bold {% if request.args.get('category','전체') == c %}bg-green-600 text-white border-green-600{% else %}bg-white text-gray-500{% endif %}">
                {{c}}
            </a>
            {% endfor %}
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            {% for p in products %}
            {% set is_expired = p.deadline < now if p.deadline else False %}
            {% set is_out_of_stock = p.stock <= 0 %}
            <div class="product-card bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden relative flex flex-col {% if is_expired or is_out_of_stock %}sold-out{% endif %}">
                {% if is_expired or is_out_of_stock %}
                    <div class="sold-out-badge text-xs">판매종료</div>
                {% endif %}
                
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-gray-50 overflow-hidden">
                    <img src="{{ p.image_url }}" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/400x400?text=이미지준비중'">
                    <div class="absolute bottom-2 left-2 flex flex-col gap-1">
                        <span class="bg-black/60 text-white text-[9px] px-2 py-0.5 rounded-full">잔여 {{ p.stock }}개</span>
                    </div>
                </a>
                
                <div class="p-3 flex flex-col flex-1">
                    <p class="text-[9px] text-green-600 font-bold">{{ p.origin }}</p>
                    <a href="/product/{{p.id}}"><h3 class="font-bold text-gray-800 text-xs mb-1 truncate">{{ p.name }}</h3></a>
                    <p class="text-[10px] text-gray-400 mb-2">{{ p.spec }}</p>
                    
                    <div class="mt-auto">
                        <div class="flex justify-between items-end">
                            <span class="text-sm font-black text-gray-900">{{ "{:,}".format(p.price) }}원</span>
                            <form action="/cart/add/{{p.id}}" method="POST">
                                <button class="bg-green-50 p-2 rounded-xl text-green-600 hover:bg-green-600 hover:text-white transition">
                                    <i class="fas fa-cart-plus"></i>
                                </button>
                            </form>
                        </div>
                        <div class="mt-2 pt-2 border-t border-gray-50 flex justify-between items-center">
                            <span class="text-[9px] text-gray-400">마감: {{ p.deadline.strftime('%H:%M') if p.deadline else '미정' }}</span>
                            <span class="countdown-timer text-[9px] text-red-500 font-bold" data-deadline="{{ p.deadline.isoformat() if p.deadline else '' }}">
                                --:--:--
                            </span>
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    is_expired = p.deadline < datetime.now() if p.deadline else False
    is_out_of_stock = p.stock <= 0
    content = """
    <div class="max-w-4xl mx-auto px-4 py-10">
        <div class="grid md:grid-cols-2 gap-8 mb-12">
            <div class="aspect-square rounded-2xl overflow-hidden border">
                <img src="{{ p.image_url }}" class="w-full h-full object-cover" onerror="this.src='https://placehold.co/600x600?text=이미지준비중'">
            </div>
            <div class="flex flex-col justify-center">
                <span class="text-green-600 font-bold text-xs mb-2">{{ p.origin }} | {{ p.farmer }}</span>
                <h2 class="text-2xl font-black text-gray-800 mb-4">{{ p.name }}</h2>
                <p class="text-gray-400 text-sm mb-6">{{ p.spec }}</p>
                <div class="bg-gray-50 p-6 rounded-2xl mb-8">
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-gray-500 text-sm">판매가</span>
                        <span class="text-2xl font-black text-gray-900">{{ "{:,}".format(p.price) }}원</span>
                    </div>
                    <div class="flex justify-between items-center text-xs text-gray-400">
                        <span>배송정보</span>
                        <span>당일 수확 / 오후 6시 이전 배송</span>
                    </div>
                </div>
                {% if not is_expired and not is_out_of_stock %}
                <form action="/cart/add/{{p.id}}" method="POST">
                    <button class="w-full bg-green-600 text-white py-4 rounded-xl font-bold text-lg shadow-lg hover:bg-green-700 transition transform active:scale-95">장바구니 담기</button>
                </form>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-4 rounded-xl font-bold text-lg cursor-not-allowed">판매 종료된 상품입니다</button>
                {% endif %}
            </div>
        </div>

        <div class="border-t pt-10">
            <h3 class="font-bold text-lg mb-6 border-l-4 border-green-600 pl-4">상세 설명</h3>
            <div class="text-center">
                {% if p.detail_image_url %}
                <img src="{{ p.detail_image_url }}" class="max-w-full mx-auto rounded-lg shadow-sm">
                {% else %}
                <div class="py-20 bg-gray-50 rounded-xl text-gray-400 text-sm italic">"가장 신선한 상태로 삼촌이 직접 골라 보내드립니다."</div>
                {% endif %}
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, is_out_of_stock=is_out_of_stock)

# --- 회원가입 / 로그인 / 로그아웃 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect('/')
        flash("이메일 또는 비밀번호를 확인하세요.")
    content = """<div class="max-w-md mx-auto mt-20 p-8 bg-white rounded-3xl shadow-xl border border-gray-50"><h2 class="text-2xl font-black text-center mb-10 text-gray-800">로그인</h2><form method="POST" class="space-y-6"><input name="email" type="email" placeholder="이메일" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><button class="w-full bg-green-600 text-white p-5 rounded-2xl font-black text-lg shadow-lg hover:bg-green-700 transition">시작하기</button></form></div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form['password'])
        new_user = User(email=request.form['email'], password=hashed_pw, name=request.form['name'], phone=request.form['phone'])
        db.session.add(new_user); db.session.commit()
        return redirect('/login')
    content = """<div class="max-w-md mx-auto mt-10 p-8 bg-white rounded-3xl shadow-xl border border-gray-50"><h2 class="text-2xl font-black text-center mb-8 text-gray-800">회원가입</h2><form method="POST" class="space-y-4"><input name="name" placeholder="이름" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><input name="email" type="email" placeholder="이메일" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><input name="password" type="password" placeholder="비밀번호" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><input name="phone" placeholder="연락처" class="w-full p-4 bg-gray-50 border-none rounded-2xl outline-none" required><button class="w-full bg-green-600 text-white p-5 rounded-2xl font-black text-lg shadow-lg hover:bg-green-700 transition mt-4">가입하기</button></form></div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/logout')
def logout(): logout_user(); return redirect('/')

@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get(pid)
    if (p.deadline and p.deadline < datetime.now()) or p.stock <= 0:
        flash("이미 마감되었거나 품절된 상품입니다.")
        return redirect('/')
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, price=p.price))
    db.session.commit()
    return redirect('/')

@app.route('/cart')
@login_required
def cart():
    items = Cart.query.filter_by(user_id=current_user.id).all(); total = sum(i.price * i.quantity for i in items)
    content = """
    <div class="max-w-3xl mx-auto py-12 px-4">
        <h2 class="text-2xl font-black mb-8">내 장바구니</h2>
        <div class="bg-white rounded-3xl shadow-sm border overflow-hidden">
            {% if items %}
                <div class="p-6 space-y-4">
                    {% for i in items %}
                    <div class="flex justify-between items-center border-b pb-4">
                        <div>
                            <p class="font-bold text-gray-800 text-sm">{{ i.product_name }}</p>
                            <p class="text-xs text-gray-400">{{ i.price }}원 x {{ i.quantity }}개</p>
                        </div>
                        <span class="font-bold text-green-600">{{ i.price * i.quantity }}원</span>
                    </div>
                    {% endfor %}
                </div>
                <div class="bg-gray-50 p-6 flex justify-between items-center">
                    <span class="font-bold text-sm">최종 결제 예정 금액</span>
                    <span class="text-2xl font-black text-green-600">{{ total }}원</span>
                </div>
                <div class="p-6">
                    <a href="/order/payment" class="block text-center bg-green-600 text-white py-4 rounded-2xl font-black shadow-lg hover:bg-green-700">지금 결제하기</a>
                </div>
            {% else %}
                <div class="p-20 text-center text-gray-400 text-sm">장바구니가 비어있습니다.</div>
            {% endif %}
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, total=total)

# --- 토스 결제 요청 페이지 ---
@app.route('/order/payment')
@login_required
def order_payment():
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    total = sum(i.price * i.quantity for i in items)
    order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}"
    order_name = f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    
    content = f"""
    <div class="max-w-md mx-auto py-20 px-4 text-center">
        <h2 class="text-xl font-black mb-4">결제를 진행합니다</h2>
        <p class="text-gray-500 mb-8 text-sm">토스 페이먼츠 안전 결제창으로 연결됩니다.</p>
        <div class="bg-white p-6 rounded-2xl shadow-sm border mb-8 text-left">
            <div class="flex justify-between mb-2"><span class="text-gray-400 text-xs">주문상품</span><span class="text-xs font-bold">{order_name}</span></div>
            <div class="flex justify-between"><span class="text-gray-400 text-xs">결제금액</span><span class="text-sm font-black text-green-600">{total:,}원</span></div>
        </div>
        <button id="payment-button" class="w-full bg-blue-600 text-white py-4 rounded-2xl font-bold shadow-lg">결제하기</button>
    </div>
    <script>
        var tossPayments = TossPayments("{TOSS_CLIENT_KEY}");
        document.getElementById('payment-button').addEventListener('click', function() {{
            tossPayments.requestPayment('카드', {{
                amount: {total},
                orderId: '{order_id}',
                orderName: '{order_name}',
                customerName: '{current_user.name}',
                successUrl: window.location.origin + '/payment/success',
                failUrl: window.location.origin + '/payment/fail',
            }});
        }});
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

# --- 결제 성공 핸들러 (서버 승인 로직) ---
@app.route('/payment/success')
@login_required
def payment_success():
    payment_key = request.args.get('paymentKey')
    order_id = request.args.get('orderId')
    amount = request.args.get('amount')

    # 1. 토스 서버에 최종 결제 승인 요청 (Security Check)
    url = "https://api.tosspayments.com/v1/payments/confirm"
    # 시크릿 키를 Base64 인코딩하여 인증 헤더 생성
    secret = TOSS_SECRET_KEY + ":"
    encoded_secret = base64.b64encode(secret.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_secret}",
        "Content-Type": "application/json"
    }
    payload = {
        "paymentKey": payment_key,
        "amount": amount,
        "orderId": order_id
    }
    
    res = requests.post(url, json=payload, headers=headers)
    
    if res.status_code == 200:
        # 2. 결제 승인 성공 시 DB 주문 기록 생성
        items = Cart.query.filter_by(user_id=current_user.id).all()
        details = ", ".join([f"{i.product_name}({i.quantity}개)" for i in items])
        
        # 주문 생성
        order = Order(
            user_id=current_user.id,
            customer_name=current_user.name,
            customer_phone=current_user.phone,
            product_details=details,
            total_price=int(amount),
            order_id=order_id,
            payment_key=payment_key,
            status='결제완료'
        )
        db.session.add(order)
        
        # 3. 실제 재고 차감 (장바구니에 담을 때 가차감했으므로 확정)
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
            
        # 4. 장바구니 비우기
        Cart.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        
        content = """
        <div class="max-w-md mx-auto py-32 px-4 text-center">
            <div class="text-green-600 text-6xl mb-6"><i class="fas fa-check-circle"></i></div>
            <h2 class="text-2xl font-black mb-2">결제가 완료되었습니다!</h2>
            <p class="text-gray-500 mb-10 text-sm">신선한 상품으로 삼촌이 곧 달려갈게요.</p>
            <a href="/" class="inline-block bg-gray-800 text-white px-8 py-3 rounded-xl font-bold">홈으로 이동</a>
        </div>
        """
        return render_template_string(HEADER_HTML + content + FOOTER_HTML)
    else:
        # 승인 실패 시
        return redirect(url_for('payment_fail', message=res.json().get('message')))

@app.route('/payment/fail')
def payment_fail():
    message = request.args.get('message', '결제 중 오류가 발생했습니다.')
    content = f"""
    <div class="max-w-md mx-auto py-32 px-4 text-center">
        <div class="text-red-500 text-6xl mb-6"><i class="fas fa-exclamation-triangle"></i></div>
        <h2 class="text-2xl font-black mb-2">결제에 실패했습니다</h2>
        <p class="text-gray-500 mb-10 text-sm">{message}</p>
        <a href="/cart" class="inline-block bg-gray-100 text-gray-600 px-8 py-3 rounded-xl font-bold">장바구니로 돌아가기</a>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

# --- 관리자 기능 ---
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: return redirect('/')
    products = Product.query.all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    content = """
    <div class="max-w-7xl mx-auto py-10 px-4">
        <div class="flex flex-col md:flex-row justify-between items-center mb-8 gap-4">
            <h2 class="text-xl font-black text-orange-700">바구니삼촌 직거래 관리자</h2>
            <div class="flex gap-2">
                <a href="/admin/orders/excel" class="bg-blue-600 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-md"><i class="fas fa-file-excel mr-1"></i> 주문 엑셀 다운로드</a>
                <a href="/admin/add" class="bg-green-600 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-md">+ 상품 등록</a>
            </div>
        </div>

        <div class="mb-12">
            <h3 class="font-bold text-gray-800 mb-4">📦 상품 관리</h3>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden">
                <table class="w-full text-left text-xs">
                    <thead class="bg-gray-50 border-b">
                        <tr><th class="p-4">상품명</th><th class="p-4">판매가</th><th class="p-4">잔여수량</th><th class="p-4">마감시간</th><th class="p-4">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for p in products %}
                        <tr class="border-b">
                            <td class="p-4 font-bold">{{ p.name }}</td>
                            <td class="p-4">{{ p.price }}원</td>
                            <td class="p-4 font-bold text-blue-600">{{ p.stock }}개</td>
                            <td class="p-4 text-red-500 font-bold">{{ p.deadline.strftime('%H:%M') if p.deadline else '미정' }}</td>
                            <td class="p-4"><a href="/admin/delete/{{p.id}}" class="text-red-400" onclick="return confirm('삭제?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <div>
            <h3 class="font-bold text-gray-800 mb-4">🛒 결제 완료 주문 내역</h3>
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden">
                <table class="w-full text-left text-xs">
                    <thead class="bg-gray-50 border-b">
                        <tr><th class="p-4">일시</th><th class="p-4">고객명</th><th class="p-4">주문내용</th><th class="p-4">총금액</th><th class="p-4">결제ID</th></tr>
                    </thead>
                    <tbody>
                        {% for o in orders %}
                        <tr class="border-b">
                            <td class="p-4 text-gray-400">{{ o.created_at.strftime('%m/%d %H:%M') }}</td>
                            <td class="p-4 font-bold">{{ o.customer_name }}<br><span class="text-[10px] text-gray-400">{{ o.customer_phone }}</span></td>
                            <td class="p-4 truncate max-w-[200px]">{{ o.product_details }}</td>
                            <td class="p-4 font-bold text-green-600">{{ "{:,}".format(o.total_price) }}원</td>
                            <td class="p-4"><span class="text-[10px] text-gray-300">{{ o.order_id }}</span></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, orders=orders)

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    if not current_user.is_admin: return redirect('/')
    orders = Order.query.order_by(Order.created_at.desc()).all()
    data = [{
        "주문일시": o.created_at.strftime('%Y-%m-%d %H:%M'),
        "주문번호": o.order_id,
        "고객명": o.customer_name,
        "연락처": o.customer_phone,
        "주문내역": o.product_details,
        "결제금액": o.total_price,
        "상태": o.status
    } for o in orders]
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Orders')
    output.seek(0)
    return send_file(output, download_name=f"orders_{datetime.now().strftime('%Y%m%d')}.xlsx", as_attachment=True)

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    if not current_user.is_admin: return redirect('/')
    if request.method == 'POST':
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_img = save_uploaded_file(request.files.get('detail_image'))
        dl_str = request.form['deadline']
        deadline_obj = datetime.strptime(dl_str, '%Y-%m-%dT%H:%M') if dl_str else None
        p = Product(name=request.form['name'], category=request.form['category'], price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer=request.form['farmer'], image_url=main_img or "https://placehold.co/400x400?text=이미지없음", detail_image_url=detail_img, stock=int(request.form['stock']), deadline=deadline_obj, is_active=True)
        db.session.add(p); db.session.commit()
        return redirect('/admin')
    content = """
    <div class="max-w-xl mx-auto py-12 px-4">
        <h2 class="text-2xl font-black mb-8 text-orange-700">시장가 당일배송 상품 등록</h2>
        <form method="POST" enctype="multipart/form-data" class="bg-white p-8 rounded-3xl shadow-sm border space-y-4 text-sm">
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block mb-1 font-bold">카테고리</label><select name="category" class="w-full border p-3 rounded-xl"><option>과일</option><option>채소</option><option>쌀/잡곡</option><option>기타</option></select></div>
                <div><label class="block mb-1 font-bold">상품명</label><input name="name" class="w-full border p-3 rounded-xl" required></div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block mb-1 font-bold">판매가격</label><input name="price" type="number" class="w-full border p-3 rounded-xl" required></div>
                <div><label class="block mb-1 font-bold">규격</label><input name="spec" class="w-full border p-3 rounded-xl" placeholder="예: 3kg"></div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="block mb-1 font-bold">한정 수량</label><input name="stock" type="number" class="w-full border p-3 rounded-xl" value="10" required></div>
                <div><label class="block mb-1 font-bold">마감 일시</label><input name="deadline" type="datetime-local" class="w-full border p-3 rounded-xl" required></div>
            </div>
            <div><label class="block mb-1 font-bold">산지/농가</label><input name="origin" placeholder="산지" class="w-full border p-3 rounded-xl mb-2"><input name="farmer" placeholder="농가명" class="w-full border p-3 rounded-xl"></div>
            <div class="bg-green-50 p-4 rounded-xl border border-dashed border-green-200"><label class="block mb-1 font-bold text-green-700">메인 사진</label><input type="file" name="main_image" accept="image/*" class="w-full text-xs"></div>
            <div class="bg-blue-50 p-4 rounded-xl border border-dashed border-blue-200"><label class="block mb-1 font-bold text-blue-700">상세 사진</label><input type="file" name="detail_image" accept="image/*" class="w-full text-xs"></div>
            <button class="w-full bg-green-600 text-white py-4 rounded-2xl font-black text-lg shadow-lg">등록 완료</button>
        </form>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

@app.route('/admin/delete/<int:pid>')
@login_required
def admin_delete(pid):
    if not current_user.is_admin: return redirect('/')
    p = Product.query.get(pid); db.session.delete(p); db.session.commit()
    return redirect('/admin')

def init_db():
    with app.app_context():
        db.create_all()
        cols = [
            ("product", "stock", "INTEGER DEFAULT 10"), 
            ("product", "deadline", "DATETIME"),
            ("product", "detail_image_url", "VARCHAR(500)"),
            ("order", "customer_phone", "VARCHAR(20)"),
            ("order", "order_id", "VARCHAR(100)"),
            ("order", "payment_key", "VARCHAR(200)")
        ]
        for t, c, ct in cols:
            try:
                db.session.execute(text(f"ALTER TABLE {t} ADD COLUMN {c} {ct}"))
                db.session.commit()
            except: db.session.rollback() 
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        db.session.commit()

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)