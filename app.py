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
from delivery_system import logi_bp # 배송 시스템 파일에서 Blueprint 가져오기

# --------------------------------------------------------------------------------
# 1. 초기 설정 및 Flask 인스턴스 생성
# --------------------------------------------------------------------------------
# --- 수정 전 기존 코드 ---
# app = Flask(__name__)
# app.register_blueprint(logi_bp) 
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db'
# db = SQLAlchemy(app)

# --- 수정 후 (이 부분으로 교체하세요) ---
from delivery_system import logi_bp, db_delivery  # 배송 시스템 파일에서 객체 가져오기

app = Flask(__name__)
app.secret_key = "basket_uncle_direct_trade_key_999_secure"

# 1. 모든 DB 경로를 설정에 먼저 등록합니다.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db' # 쇼핑몰 DB
app.config['SQLALCHEMY_BINDS'] = {
    'delivery': 'sqlite:///delivery.db' # 배송 시스템 DB
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. [핵심] 쇼핑몰 주방장(db)을 배송팀(db_delivery)과 공유합니다.
# 새로 만들지 않고 기존에 정의된 배송팀 주방장 객체를 가져와서 쇼핑몰 앱에 연결합니다.
db = db_delivery  
db.init_app(app)

# 3. 배송 관리 시스템 Blueprint 등록 (주소 접두어 /logi 적용됨)
app.register_blueprint(logi_bp)

# 결제 연동 키 (Toss Payments)
TOSS_CLIENT_KEY = "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"

# 파일 업로드 경로 설정
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --------------------------------------------------------------------------------
# 2. 데이터베이스 모델 설계 (DB 구조 변경 금지 규칙 준수)
# --------------------------------------------------------------------------------

class User(db.Model, UserMixin):
    """사용자 정보 모델"""
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
    order_id = db.Column(db.String(100)) 
    payment_key = db.Column(db.String(200)) 
    delivery_address = db.Column(db.String(500))
    request_memo = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)

class Review(db.Model):
    """사진 리뷰 모델"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    user_name = db.Column(db.String(50))
    product_id = db.Column(db.Integer) 
    product_name = db.Column(db.String(100))
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

def save_uploaded_file(file):
    """파일 업로드 저장 및 경로 반환"""
    if file and file.filename != '':
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        new_filename = f"uncle_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        return f"/static/uploads/{new_filename}"
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="description" content="바구니 삼촌은 농산물·식자재를 중간 유통 없이 직접 연결하고 최소 배송비만 받는 신개념 물류·구매대행 서비스입니다.">
<title>바구니 삼촌 |  basam</title>

    <title>바구니삼촌 - 농산물·식자재 배송 신개념 6PL 생활서비스 basam </title>
    <script src="https://js.tosspayments.com/v1/payment"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8f9fa; color: #333; -webkit-tap-highlight-color: transparent; overflow-x: hidden; }
        
        /* 유틸리티 스타일 */
        .sold-out { filter: grayscale(100%); opacity: 0.6; }
        .sold-out-badge { 
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8); color: white; padding: 10px 20px; 
            border-radius: 12px; font-weight: 800; z-index: 10; border: 2px solid white;
        }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        
        /* 가로 스크롤 레이아웃 */
        .horizontal-scroll {
            display: flex; overflow-x: auto; scroll-snap-type: x mandatory; 
            gap: 12px; padding-bottom: 20px; -webkit-overflow-scrolling: touch;
        }
        .horizontal-scroll > div { scroll-snap-align: start; flex-shrink: 0; }
        
        /* 사이드바 메뉴 */
        #sidebar {
            position: fixed; top: 0; left: -300px; width: 300px; height: 100%;
            background: white; z-index: 1000; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 15px 0 40px rgba(0,0,0,0.15); overflow-y: auto;
        }
        #sidebar.open { left: 0; }
        #sidebar-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); z-index: 999; display: none; backdrop-filter: blur(2px);
        }
        #sidebar-overlay.show { display: block; }

        /* 알림 토스트 */
        #toast {
            visibility: hidden; min-width: 280px; background-color: #1a1a1a; color: #fff; text-align: center;
            border-radius: 50px; padding: 18px; position: fixed; z-index: 5000; left: 50%; bottom: 30px;
            transform: translateX(-50%); font-size: 14px; font-weight: bold; transition: 0.5s; opacity: 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        #toast.show { visibility: visible; opacity: 1; bottom: 60px; }

        /* 모달 공통 */
        #term-modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:4000; align-items:center; justify-content:center; padding:20px; }
        #term-modal-content { background:white; width:100%; max-width:600px; max-height:85vh; border-radius:2.5rem; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 30px 60px rgba(0,0,0,0.4); }
        #term-modal-body { overflow-y:auto; padding:2.5rem; font-size:0.95rem; line-height:1.8; color:#444; }

        /* 반응형 타이틀 및 텍스트 최적화 */
        @media (max-width: 640px) {
            .hero-title { font-size: 1.75rem !important; line-height: 1.3 !important; }
            .hero-desc { font-size: 0.875rem !important; }
        }
    </style>
</head>
<body class="text-left font-black">
    <div id="toast">메시지가 표시됩니다. 🧺</div>
    
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
    <div id="sidebar" class="p-10 flex flex-col h-full">
        <div class="flex justify-between items-center mb-12">
            <div class="flex items-center gap-2">
                <img src="/static/logo/side1.jpg" class="h-6 w-auto rounded" onerror="this.style.display='none'">
                <h3 class="text-xl text-green-600 italic font-black uppercase tracking-tighter">Categories</h3>
            </div>
            <button onclick="toggleSidebar()" class="text-gray-300 text-2xl hover:text-red-500 transition"><i class="fas fa-times"></i></button>
        </div>
        
        <nav class="space-y-7 text-base flex-1">
            <a href="/" class="group flex items-center gap-3 text-gray-800 hover:text-green-600 transition font-black">
                <i class="fas fa-th-large opacity-20 group-hover:opacity-100 transition"></i> 전체 상품 리스트
            </a>
            <div class="h-px bg-gray-100 w-full my-4"></div>
            
            {% for c in nav_categories %}
            <a href="/category/{{ c.name }}" class="flex items-center justify-between text-gray-500 hover:text-green-600 transition">
                <span>{{ c.name }}</span>
                <i class="fas fa-chevron-right text-[10px] opacity-30"></i>
            </a>
            {% endfor %}
            
            <div class="h-px bg-gray-100 w-full my-4"></div>
            <a href="/about" class="block font-bold text-blue-500 hover:underline">바구니삼촌이란?</a>
            
            {% if current_user.is_authenticated and (current_user.is_admin or current_user.email in managers) %}
            <div class="pt-6">
                <a href="/admin" class="block p-5 bg-orange-50 text-orange-600 rounded-3xl text-center text-xs border border-orange-100 font-black shadow-sm hover:bg-orange-100 transition">
                    <i class="fas fa-user-shield mr-2"></i> 관리자 대시보드
                </a>
            </div>
            {% endif %}
        </nav>
        
        <div class="mt-auto pt-10 border-t border-gray-100">
            <p class="text-[10px] text-gray-300 uppercase tracking-[0.2em] font-black mb-2">Service Center</p>
            <p class="text-lg font-black text-gray-400">1666-8320</p>
            <p class="text-[9px] text-gray-300 mt-1 font-bold">인천 연수구 송도동 전용</p>
        </div>
    </div>

    <nav class="bg-white/95 backdrop-blur-md shadow-sm sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-3 md:px-6">
            <div class="flex justify-between h-16 md:h-20 items-center">
                <div class="flex items-center gap-2 md:gap-6">
                    <button onclick="toggleSidebar()" class="text-gray-400 text-xl md:text-2xl hover:text-green-600 transition p-1">
                        <i class="fas fa-bars"></i>
                    </button>
                    <a href="/" class="flex items-center gap-1.5">
                        <img src="/static/logo/side1.jpg" alt="바구니삼촌" class="h-7 md:h-10 w-auto rounded-lg" onerror="this.style.display='none'">
                        <span class="italic tracking-tighter uppercase font-black text-green-600 text-base md:text-xl">바구니삼촌</span>
                    </a>
                </div>

                <div class="flex items-center gap-2 md:gap-5 flex-1 justify-end">
                    <form action="/" method="GET" class="relative hidden md:block max-w-xs flex-1">
                        <input name="q" placeholder="상품검색" class="w-full bg-gray-100 py-2.5 px-6 rounded-full text-xs font-black outline-none focus:ring-4 focus:ring-green-50 transition border border-transparent focus:border-green-100">
                        <button class="absolute right-4 top-2.5 text-gray-400 hover:text-green-600 transition"><i class="fas fa-search"></i></button>
                    </form>
                    
                    <button onclick="document.getElementById('mobile-search-nav').classList.toggle('hidden')" class="md:hidden text-gray-400 p-2 text-lg"><i class="fas fa-search"></i></button>

                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="text-gray-400 relative p-1.5 hover:text-green-600 transition">
                            <i class="fas fa-shopping-cart text-xl md:text-3xl"></i>
                            <span id="cart-count-badge" class="absolute top-0 right-0 bg-red-500 text-white text-[8px] md:text-[10px] rounded-full px-1 py-0.5 font-black border border-white shadow-sm">{{ cart_count }}</span>
                        </a>
                        <a href="/mypage" class="text-gray-600 font-black bg-gray-100 px-3 py-1.5 rounded-full text-[9px] md:text-xs hover:bg-gray-200 transition">MY</a>
                    {% else %}
                        <a href="/login" class="text-gray-400 font-black text-[10px] md:text-sm hover:text-green-600 transition">로그인</a>
                    {% endif %}
                </div>
            </div>
            
            <div id="mobile-search-nav" class="hidden md:hidden pb-4">
                <form action="/" method="GET" class="relative">
                    <input name="q" placeholder="상품 검색..." class="w-full bg-gray-100 py-3.5 px-7 rounded-full text-sm font-bold outline-none border-2 border-green-50 focus:border-green-200 transition">
                    <button class="absolute right-6 top-4 text-green-600"><i class="fas fa-search"></i></button>
                </form>
            </div>
        </div>
    </nav>
    <main class="min-h-screen">
"""

FOOTER_HTML = """
    </main>

    <footer class="bg-gray-900 text-gray-400 py-12 md:py-20 border-t border-white/5 mt-20">
        <div class="max-w-7xl mx-auto px-6">
            
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-white/5 pb-10 mb-10 gap-8">
                <div class="text-left">
                    <p class="text-green-500 font-black text-2xl italic tracking-tighter mb-2 uppercase">바구니삼촌</p>
                    <p class="text-xs text-orange-500 font-bold italic">인천 연수구 송도동 전용 구매대행 및 배송 서비스</p>
                </div>
                
                <div class="flex flex-col md:items-end gap-3 w-full md:w-auto">
                    <p class="font-bold text-gray-200 text-sm md:text-base font-black">Customer Center</p>
                    <div class="flex flex-wrap md:justify-end gap-3 items-center">
                        <a href="http://pf.kakao.com/_AIuxkn" target="_blank" class="bg-[#FEE500] text-gray-900 px-5 py-2.5 rounded-xl font-black text-[11px] flex items-center gap-2 shadow-lg transition hover:brightness-105">
                            <i class="fas fa-comment"></i> 카카오톡 문의
                        </a>
                        <p class="text-lg font-black text-white ml-2">1666-8320</p>
                    </div>
                    <p class="text-[10px] font-bold text-gray-500">평일 09:00 ~ 18:00 (점심 12:00 ~ 13:00)</p>
                </div>
            </div>

            <div class="flex flex-wrap gap-x-6 gap-y-3 mb-8 text-[11px] font-bold opacity-60 underline">
                <a href="javascript:void(0)" onclick="openUncleModal('terms')" class="hover:text-white transition">이용약관</a>
                <a href="javascript:void(0)" onclick="openUncleModal('privacy')" class="hover:text-white transition">개인정보처리방침</a>
                <a href="javascript:void(0)" onclick="openUncleModal('agency')" class="hover:text-white transition">이용 안내</a>
                <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="hover:text-white transition">전자상거래 유의사항</a>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-8 items-end">
                <div class="text-[10px] md:text-[11px] space-y-1.5 opacity-40 leading-relaxed font-medium text-left">
                    <p>상호: 바구니삼촌 | 대표: 금창권 | 개인정보관리책임자: 금창권</p>
                    <p>주소: 인천광역시 연수구 하모니로158, D동 317호 (송도동, 송도 타임스페이스)</p>
                    <p>사업자등록번호: 472-93-02262 | 통신판매업신고: 제 2025-인천연수-3388호</p>
                    <p>이메일: basamsongdo@gmail.com</p>
                    <p class="pt-4 opacity-100 font-bold uppercase tracking-[0.2em]">© 2026 BASAM. All Rights Reserved.</p>
                </div>
                
                <div class="hidden md:block text-right opacity-20">
                    <i class="fas fa-truck-fast text-5xl"></i>
                </div>
            </div>
        </div>
    </footer>


<!-- ✅ 여기부터 붙여넣기 -->
<div id="uncleModal" class="fixed inset-0 bg-black bg-opacity-70 hidden items-center justify-center z-50">
  <div class="bg-white text-black max-w-3xl w-full mx-4 rounded-xl shadow-lg overflow-y-auto max-h-[80vh]">
    <div class="flex justify-between items-center p-6 border-b">
      <h2 id="uncleModalTitle" class="text-lg font-bold"></h2>
      <button onclick="closeUncleModal()" class="text-gray-500 hover:text-black text-xl">✕</button>
    </div>
    <div id="uncleModalContent" class="p-6 text-sm leading-relaxed space-y-4"></div>
  </div>
</div>
<!-- ✅ 여기까지 -->

    <script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebar-overlay');
            sidebar.classList.toggle('open');
            overlay.classList.toggle('show');
        }

        const UNCLE_TERMS = {
            'terms': {
                'title': '바구니삼촌 이용약관',
                'content': `<b>제1조 (목적)</b><br>본 약관은 바구니삼촌이 제공하는 통합 유통 및 배송 서비스의 이용 조건을 규정합니다.<br><br><b>제2조 (서비스 정의)</b><br>바구니삼촌은 물류 기획, 상품 소싱, 배송 인프라를 통합하여 제공하는 6PL 지향 물류 전문 서비스입니다.<br><br><b>제3조 (가격 정책)</b><br>상품 가격은 실제 구매 원가를 기준으로 투명하게 운영되며, 별도의 불투명한 중개 수수료를 소비자에게 부과하지 않습니다.`
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
            new daum.Postcode({
                oncomplete: function(data) {
                    document.getElementById('address').value = data.address;
                    document.getElementById('address_detail').focus();
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

</body>

</html>
"""

# --------------------------------------------------------------------------------
# 5. 비즈니스 로직 및 라우팅
# --------------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    """전역 템플릿 변수 주입"""
    cart_count = 0
    if current_user.is_authenticated:
        total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar()
        cart_count = total_qty if total_qty else 0
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    managers = [c.manager_email for c in categories if c.manager_email]
    return dict(cart_count=cart_count, now=datetime.now(), managers=managers, nav_categories=categories)

@app.route('/')
def index():
    """메인 페이지"""
    query = request.args.get('q', '').strip()
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    grouped_products = {}
    
    order_logic = (Product.stock <= 0) | (Product.deadline < datetime.now())
    
    # 최신 상품 20개 중 8개 랜덤
    latest_all = Product.query.filter_by(is_active=True).order_by(Product.id.desc()).limit(20).all()
    random_latest = random.sample(latest_all, min(len(latest_all), 30)) if latest_all else []
    
    # 오늘 마감 상품
    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    closing_today = Product.query.filter(
        Product.is_active == True,
        Product.deadline > datetime.now(),
        Product.deadline <= today_end
    ).order_by(Product.deadline.asc()).all()

    # 최신 리뷰 4개 (메인 노출)
    latest_reviews = Review.query.order_by(Review.created_at.desc()).limit(4).all()

    for cat in categories:
        q_obj = Product.query.filter_by(category=cat.name, is_active=True)
        if query: q_obj = q_obj.filter(Product.name.contains(query))
        products = q_obj.order_by(order_logic, Product.id.desc(), Product.deadline.asc()).all()
        if products: grouped_products[cat] = products
    
    content = """
   <div class="bg-gray-900 text-white py-20 md:py-32 px-4 shadow-inner relative overflow-hidden text-center">
    <div class="max-w-7xl mx-auto relative z-10 font-black text-center">
        
        <span class="text-green-400 text-[10px] md:text-sm font-black mb-6 inline-block uppercase tracking-[0.3em]">
            Direct Delivery Service
        </span>

        <h1 class="hero-title text-3xl md:text-7xl font-black mb-8 leading-tight tracking-tighter">
            우리는 상품을 판매하지 않습니다.<br>
            <span class="text-green-500 uppercase">Premium Service</span>
        </h1>

        <div class="w-12 h-1 bg-white/20 mx-auto mb-8"></div>

        <p class="hero-desc text-gray-400 text-sm md:text-2xl font-bold max-w-2xl mx-auto mb-12">
            판매가 아닌,
            <span class="text-white underline decoration-green-500 decoration-4 underline-offset-8">
                배송 서비스
            </span>
            입니다.
        </p>

        <div class="flex flex-col md:flex-row justify-center items-center gap-6">
            <a href="#products"
               class="bg-green-600 text-white px-10 py-4 md:px-12 md:py-5 rounded-full font-black shadow-2xl hover:bg-green-700 transition active:scale-95">
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

    <div id="products" class="max-w-7xl mx-auto px-4 py-16 text-left">
        {% if query %}
            <p class="mb-8 font-black text-gray-400 text-lg md:text-xl border-b border-gray-100 pb-4 text-left">
                <span class="text-green-600">"{{ query }}"</span>에 대한 상품 검색 결과입니다.
            </p>
        {% endif %}

        {% if latest_reviews and not query %}
        <section class="mb-12 text-left">
            <div class="mb-6 flex justify-between items-end border-b border-gray-100 pb-4 text-left">
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
        <section class="mb-12 text-left">
            <div class="mb-6 flex justify-between items-end border-b border-gray-100 pb-4 text-left">
                <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                    <span class="w-1.5 h-8 bg-blue-500 rounded-full"></span> ✨ 최신 상품
                </h2>
                <a href="/category/최신상품" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar">
                {% for p in random_latest %}
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] transition-all hover:shadow-2xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1.5 md:p-5" onerror="this.src='https://placehold.co/400x400?text={{ p.name }}'">
                        <div class="absolute top-2 left-2 md:top-4 md:left-4"><span class="bg-blue-500 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg uppercase font-black">NEW</span></div>
                    </a>
                    <div class="p-3 md:p-7 flex flex-col flex-1 text-left">
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-green-600 mb-2 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[13px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}

        {% if closing_today and not query %}
        <section class="mb-12 text-left">
            <div class="mb-6 flex justify-between items-end border-b border-gray-100 pb-4 text-left">
                <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter">
                    <span class="w-1.5 h-8 bg-red-500 rounded-full"></span> 🔥 오늘 마감 임박!
                </h2>
                <a href="/category/오늘마감" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar">
                {% for p in closing_today %}
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-red-50 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] transition-all hover:shadow-2xl">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1.5 md:p-5">
                        <div class="absolute bottom-2 left-2 md:bottom-5 md:left-5"><span class="bg-red-600 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg font-black animate-pulse uppercase">CLOSING</span></div>
                    </a>
                    <div class="p-3 md:p-7 flex flex-col flex-1 text-left">
                        <p class="countdown-timer text-[8px] md:text-[10px] font-bold text-red-500 mb-1.5" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-green-600 mb-2 font-medium truncate">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end">
                            <span class="text-[13px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </section>
        {% endif %}
        
        {% for cat, products in grouped_products.items() %}
        <section class="mb-12 text-left">
            <div class="mb-6 flex justify-between items-end border-b border-gray-100 pb-4 text-left">
                <div class="text-left">
                    <h2 class="text-xl md:text-3xl font-black text-gray-800 flex items-center gap-3 tracking-tighter text-left">
                        <span class="w-1.5 h-8 bg-green-500 rounded-full"></span> {{ cat.name }} 리스트
                    </h2>
                    {% if cat.description %}<p class="text-[11px] md:text-sm text-gray-400 mt-2 font-bold text-left">{{ cat.description }}</p>{% endif %}
                </div>
                <a href="/category/{{ cat.name }}" class="text-[10px] md:text-sm font-bold text-gray-400 hover:text-green-600 flex items-center gap-1 transition">
                    전체보기 <i class="fas fa-chevron-right text-[8px]"></i>
                </a>
            </div>
            <div class="horizontal-scroll no-scrollbar text-left">
                {% for p in products %}
                {% set is_expired = (p.deadline and p.deadline < now) %}
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] transition-all hover:shadow-2xl {% if is_expired or p.stock <= 0 %}sold-out{% endif %} text-left">
                    {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[9px] md:text-xs text-center">판매마감</div>{% endif %}
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden text-left">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-2 md:p-6 text-left">
                        <div class="absolute bottom-2 left-2 md:bottom-5 md:left-5 text-left">
                            <span class="bg-black/70 text-white text-[7px] md:text-[11px] px-2 py-1 rounded-md font-black backdrop-blur-sm">잔여: {{ p.stock }}</span>
                        </div>
                    </a>
                    <div class="p-3 md:p-8 flex flex-col flex-1 text-left">
                        <p class="countdown-timer text-[8px] md:text-[10px] font-bold text-red-500 mb-1.5 text-left" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5 text-left">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-green-600 mb-2 font-medium truncate text-left">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end text-left">
                            <span class="text-[13px] md:text-2xl font-black text-green-600 text-left">{{ "{:,}".format(p.price) }}원</span>
                            {% if not is_expired and p.stock > 0 %}
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90 text-center">
                                <i class="fas fa-plus text-[10px] md:text-xl"></i>
                            </button>
                            {% endif %}
                        </div>
                    </div>
                </div>
                {% endfor %}
                <div class="w-4 md:w-10 flex-shrink-0"></div>
            </div>
        </section>
        {% endfor %}
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, grouped_products=grouped_products, random_latest=random_latest, closing_today=closing_today, latest_reviews=latest_reviews)

@app.route('/about')
def about_page():
    """브랜드 소개 페이지 (디자인 스타일 통합 버전)"""
    content = """
    <div class="bg-[#fcfcfc] py-24 md:py-40 px-6 tracking-tight font-medium">
        <div class="max-w-4xl mx-auto">
            
            <nav class="mb-24 flex justify-start">
                <a href="/" class="group flex items-center gap-2 text-slate-400 hover:text-emerald-600 transition-all duration-300 font-bold">
                    <span class="w-10 h-10 flex items-center justify-center rounded-full bg-white shadow-sm group-hover:bg-emerald-50 transition-colors">
                        <i class="fas fa-arrow-left text-xs"></i>
                    </span>
                    <span class="text-sm uppercase tracking-widest ml-2">Back to Store</span>
                </a>
            </nav>
            
            <header class="mb-32 text-left">
               
               
                <div class="space-y-12 text-slate-600 text-xl md:text-3xl leading-relaxed font-semibold">
                    <p class="text-slate-900 text-2xl md:text-4xl font-black tracking-tighter leading-tight">
                        바구니 삼촌몰은 단순한 판매 플랫폼이 아닌,<br class="hidden md:block"> 
                        물류 전문가가 설계한 <b>신개념 유통·배송 서비스</b>입니다.
                    </p>
                    <p class="opacity-90">
                        기존 유통 구조에서 분리되어 있던 상품 소싱, 물류 운영, 플랫폼 개발을 하나의 체계로 통합하여, 불필요한 유통 단계를 대폭 축소했습니다.
                    </p>
                    <p class="opacity-90">
                        우리는 기존 4PL(제4자 물류)의 개념을 확장해, 물류 기획·운영을 기반으로 상품 소싱과 자체 플랫폼 개발까지 포함한 <b>‘확장형 물류 서비스(일명 6PL)’</b>에 가까운 새로운 형태의 유통 모델을 지향합니다.
                    </p>
                    <p class="opacity-90">
                        직접 구축한 물류 인프라와 배송 네트워크를 기반으로 중간 유통 마진, 광고비, 플랫폼 수수료를 최소화하고, 그 절감된 비용을 상품 원가와 배송비에 그대로 반영하여 소비자에게는 합리적인 가격을, 판매자에게는 수수료 부담 없는 유통 환경을 제공합니다.
                    </p>
                </div>
            </header>
            
            <section class="mb-40">
                <div class="bg-emerald-50/50 rounded-[48px] p-10 md:p-20 border-none shadow-inner text-left">
                    <p class="text-emerald-800 font-black text-3xl md:text-4xl mb-16 italic">우리의 핵심 가치는 명확합니다.</p>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-12 md:gap-20 mb-20">
                        <div class="flex flex-col gap-4">
                            <p class="text-emerald-600 text-sm font-black uppercase tracking-[0.2em] opacity-50">Value 01</p>
                            <p class="text-3xl md:text-4xl font-black text-slate-800 leading-tight">
                                중간 유통 수수료<br><span class="text-emerald-600 underline decoration-4 underline-offset-8">0원</span>
                            </p>
                        </div>
                        <div class="flex flex-col gap-4">
                            <p class="text-emerald-600 text-sm font-black uppercase tracking-[0.2em] opacity-50">Value 02</p>
                            <p class="text-3xl md:text-4xl font-black text-slate-800 leading-tight">
                                플랫폼 입점 비용<br><span class="text-emerald-600 underline decoration-4 underline-offset-8">0원</span>
                            </p>
                        </div>
                    </div>

                    <div class="border-t border-emerald-100 pt-16">
                        <p class="text-slate-500 font-bold text-xl md:text-2xl leading-relaxed">
                            바구니 삼촌몰은 <span class="text-slate-800 font-black">‘상품을 파는 플랫폼’</span>이 아니라, <br class="hidden md:block">
                            <span class="text-emerald-600 font-black">‘유통 구조를 설계하고 배송을 완성하는 물류 중심 서비스’</span>입니다.
                        </p>
                    </div>
                </div>
            </section>

            <section class="mb-40 bg-slate-900 p-12 md:p-24 rounded-[64px] text-white shadow-2xl relative overflow-hidden text-left">
                <div class="relative z-10">
                    <h3 class="text-3xl md:text-5xl font-black mb-20 tracking-tighter uppercase italic text-emerald-400">송도에 최적화된 6PL 모델</h3>
                    
                    <ul class="grid grid-cols-1 md:grid-cols-2 gap-12 text-lg md:text-2xl font-bold opacity-90">
                        <li class="flex items-start gap-5">
                            <i class="fas fa-check-circle text-emerald-500 mt-1"></i>
                            <span>송도 생활권 중심의<br>직영 배송 네트워크</span>
                        </li>
                        <li class="flex items-start gap-5">
                            <i class="fas fa-check-circle text-emerald-500 mt-1"></i>
                            <span>산지 소싱부터 문 앞 배송까지<br>직접 관리</span>
                        </li>
                        <li class="flex items-start gap-5">
                            <i class="fas fa-check-circle text-emerald-500 mt-1"></i>
                            <span>자체 기술(IT) 인프라를 통한<br>비용 절감</span>
                        </li>
                        <li class="flex items-start gap-5">
                            <i class="fas fa-check-circle text-emerald-500 mt-1"></i>
                            <span>불필요한 마케팅비를 뺀<br>원가 중심 유통</span>
                        </li>
                    </ul>

                    <div class="mt-24 pt-20 border-t border-white/10">
                        <p class="text-3xl md:text-6xl font-black tracking-tight text-emerald-400 italic leading-[1.1]">
                            가장 합리적인 유통 구조를<br>
                            송도에서 바구니 삼촌이 실현합니다.
                        </p>
                    </div>
                </div>
                <div class="absolute -right-32 -bottom-32 w-[600px] h-[600px] bg-emerald-500/10 rounded-full blur-[120px]"></div>
            </section>

            <div class="pb-16 text-center">
                <a href="/" class="group inline-flex items-center gap-6 bg-emerald-600 text-white px-16 py-8 md:px-24 md:py-10 rounded-[32px] font-black text-2xl md:text-4xl shadow-2xl shadow-emerald-600/30 hover:bg-emerald-500 transition-all active:scale-95 duration-300">
                    지금 상품 확인하기
                    <i class="fas fa-arrow-right text-lg md:text-2xl group-hover:translate-x-2 transition-transform"></i>
                </a>
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)
# [추가] 무한 스크롤을 위한 상품 데이터 제공 API
@app.route('/api/category_products/<string:cat_name>')
def api_category_products(cat_name):
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
    """카테고리별 상품 목록 뷰"""
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
    <div class="max-w-7xl mx-auto px-4 md:px-6 py-20 text-left">
        <div class="mb-16 text-left">
            <h2 class="text-3xl md:text-5xl text-gray-800 font-black text-left">{{ display_name }}</h2>
            {% if cat and cat.description %}<p class="text-gray-400 font-bold mt-4 text-base md:text-xl text-left">{{ cat.description }}</p>{% endif %}
        </div>
        
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 md:gap-10 text-left">
            {% for p in products %}
            {% set is_expired = (p.deadline and p.deadline < now) %}
            <div class="product-card bg-white rounded-[2rem] md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden flex flex-col transition-all hover:shadow-2xl hover:-translate-y-2 {% if is_expired or p.stock <= 0 %}sold-out{% endif %} text-left">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-[10px] md:text-sm text-center">판매마감</div>{% endif %}
                <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden text-left">
                    <img src="{{ p.image_url }}" class="w-full h-full object-contain p-4 md:p-8 text-left">
                    <div class="absolute bottom-4 left-4 text-left">
                        <span class="bg-black/70 text-white text-[8px] md:text-[11px] px-2.5 py-1.5 rounded-lg font-black backdrop-blur-sm text-left">잔여: {{ p.stock }}</span>
                    </div>
                </a>
                <div class="p-5 md:p-10 flex flex-col flex-1 text-left">
                    <p class="countdown-timer text-[8px] md:text-[11px] font-bold text-red-500 mb-2 text-left" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                    <h3 class="font-black text-gray-800 text-sm md:text-lg truncate mb-1 md:mb-2 leading-tight text-left">{{ p.name }}</h3>
                    <p class="text-[10px] md:text-sm text-green-600 mb-3 md:mb-5 font-medium truncate text-left">{{ p.description or '' }}</p>
                    <div class="mt-auto flex justify-between items-center text-left">
                        <span class="text-base md:text-2xl font-black text-green-600 text-left">{{ "{:,}".format(p.price) }}원</span>
                        {% if not is_expired and p.stock > 0 %}
                        <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-12 md:h-12 rounded-full text-white shadow-lg active:scale-90 transition-transform text-center flex items-center justify-center">
                            <i class="fas fa-plus text-[10px] md:text-base"></i>
                        </button>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products, display_name=display_name, cat=cat)

@app.route('/product/<int:pid>')
def product_detail(pid):
    """상품 상세 정보 페이지"""
    p = Product.query.get_or_404(pid)
    is_expired = (p.deadline and p.deadline < datetime.now())
    detail_images = p.detail_image_url.split(',') if p.detail_image_url else []
    cat_info = Category.query.filter_by(name=p.category).first()
    
    # 추천 상품: 키워드(상품명 첫 단어) 기반
    keyword = p.name.split()[0] if p.name else ""
    keyword_recommends = Product.query.filter(
        Product.name.contains(keyword),
        Product.id != pid,
        Product.is_active == True,
        Product.stock > 0
    ).limit(10).all()

    # 최신 상품 10개
    latest_all = Product.query.filter(Product.is_active == True, Product.id != pid).order_by(Product.id.desc()).limit(10).all()
    
    # 리뷰 리스트
    product_reviews = Review.query.filter_by(product_id=pid).order_by(Review.created_at.desc()).all()

    content = """
    <div class="max-w-4xl mx-auto px-4 md:px-6 py-16 md:py-24 font-black text-left">
        <div class="grid md:grid-cols-2 gap-10 md:gap-16 mb-24 text-left">
            <div class="relative text-left">
                <img src="{{ p.image_url }}" class="w-full aspect-square object-contain border border-gray-100 rounded-[3rem] bg-white p-8 md:p-12 shadow-sm text-left">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-lg">판매마감</div>{% endif %}
            </div>
            
            <div class="flex flex-col justify-center text-left">
                <div class="flex flex-wrap items-center gap-3 mb-6 text-left">
                    <span class="bg-green-50 text-green-600 px-5 py-1.5 rounded-full text-[10px] md:text-xs font-black text-left shadow-sm">{{ p.category }}</span>
                    {% if cat_info and cat_info.description %}
                    <span class="text-gray-400 text-[10px] md:text-xs font-bold text-left opacity-60">| {{ cat_info.description }}</span>
                    {% endif %}
                </div>
                <h2 class="text-3xl md:text-5xl text-gray-800 mb-6 leading-tight tracking-tighter text-left">{{ p.name }}</h2>
                <p class="text-green-600 text-lg md:text-2xl mb-8 font-bold text-left">{{ p.description or '' }}</p>
                
                <div class="space-y-3 mb-10 text-xs md:text-sm text-gray-400 text-left border-l-4 border-gray-100 pl-6 py-2">
                    <p class="text-blue-600 font-bold text-left flex items-center gap-2"><i class="fas fa-warehouse opacity-30"></i> 잔여수량: {{ p.stock }}개 한정</p>
                    <p class="countdown-timer text-red-500 font-bold text-left flex items-center gap-2" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                 
                    <p class="text-left flex items-center gap-2"><i class="fas fa-box-open opacity-30"></i> 규격: {{ p.spec or '일반' }}</p>
                </div>
                
                <div class="bg-gray-50 p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] mb-12 border border-gray-100 text-4xl md:text-6xl font-black text-green-600 text-left shadow-inner">
                    {{ "{:,}".format(p.price) }}<span class="text-xl md:text-2xl ml-1">원</span>
                </div>
                
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-6 md:py-8 rounded-[2rem] md:rounded-[2.5rem] font-black text-xl md:text-2xl shadow-2xl active:scale-95 transition-all mb-6 hover:bg-green-700 hover:shadow-green-100">장바구니 담기</button>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-6 md:py-8 rounded-[2rem] font-black text-xl cursor-not-allowed italic mb-6 shadow-none">판매가 마감되었습니다</button>
                {% endif %}
            </div>
        </div>
        
        <div class="border-t border-gray-100 pt-20 text-left">
            <h3 class="font-black text-2xl md:text-3xl mb-16 border-l-8 border-green-600 pl-6 text-gray-800 text-left">상세 정보</h3>
            <div class="flex flex-col gap-10 bg-white p-4 md:p-10 rounded-3xl md:rounded-[4rem] border border-gray-50 shadow-sm text-left">
                {% if detail_images %}
                    {% for img in detail_images %}<img src="{{ img.strip() }}" class="w-full rounded-2xl md:rounded-[3rem] shadow-sm text-left" onerror="this.style.display='none'">{% endfor %}
                {% else %}
                    <img src="{{ p.image_url }}" class="w-full rounded-2xl md:rounded-[3rem] text-left">
                {% endif %}
                <div class="text-lg text-gray-600 leading-loose p-6 font-bold text-left">
                    {{ p.description or '상세 설명이 준비 중입니다.' }}
                </div>
            </div>

            {% if product_reviews %}
            <div class="mt-24 bg-white p-8 md:p-16 rounded-[3rem] md:rounded-[4rem] border border-gray-100 shadow-sm text-left">
                <h3 class="text-2xl md:text-4xl font-black mb-12 flex items-center gap-4 text-left">
                    <span class="bg-orange-100 p-3 rounded-2xl text-orange-500"><i class="fas fa-camera"></i></span>
                    구매 후기 ({{ product_reviews|length }}건)
                </h3>
                <div class="space-y-10 text-left">
                    {% for r in product_reviews %}
                    <div class="border-b border-gray-100 pb-10 flex flex-col md:flex-row gap-8 text-left group">
                        <img src="{{ r.image_url }}" class="w-full md:w-48 aspect-square object-cover rounded-3xl flex-shrink-0 shadow-sm transition group-hover:scale-105">
                        <div class="flex-1 text-left">
                            <div class="flex justify-between items-center mb-3">
                                <p class="text-sm text-gray-400 font-bold text-left">{{ r.user_name[:1] }}**님 | {{ r.created_at.strftime('%Y-%m-%d') }}</p>
                                <div class="text-orange-400 text-xs"><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i></div>
                            </div>
                            <p class="text-base md:text-xl font-bold text-gray-700 leading-relaxed text-left whitespace-pre-line">{{ r.content }}</p>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
            
            <div class="mt-20 p-8 md:p-16 bg-gray-50 rounded-[2.5rem] md:rounded-[4rem] text-[10px] md:text-sm text-gray-400 leading-relaxed border border-gray-100 font-black text-left">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-12 md:gap-20 text-left">
                    <div class="text-left">
                        <h4 class="text-gray-700 mb-6 border-b border-gray-200 pb-2 font-black text-xs md:text-base uppercase tracking-widest text-left">배송정보 안내</h4>
                        <p class="mb-2 text-left"><span class="inline-block w-20 md:w-28 font-black text-gray-500">배송방법</span>신선/냉장/냉동 최적화 배송</p>
                        <p class="mb-2 text-left text-orange-500"><span class="inline-block w-20 md:w-28 font-black">배송비 정책</span>카테고리별 1,900원 (5만원 초과 시 5만원당 1,900원 추가)</p>
                        <p class="mb-2 text-left"><span class="inline-block w-20 md:w-28 font-black text-gray-500">묶음배송</span>카테고리별 묶음 배송 가능</p>
                        <p class="text-left"><span class="inline-block w-20 md:w-28 font-black text-gray-500">배송지역</span>인천광역시 연수구 송도동 전 지역 전용 서비스</p>
                    </div>
                    <div class="text-left">
                        <h4 class="text-gray-700 mb-6 border-b border-gray-200 pb-2 font-black text-xs md:text-base uppercase tracking-widest text-left">교환/반품 상세규정</h4>
                        <p class="mb-2 text-left"><span class="inline-block w-20 md:w-28 font-black text-gray-500">반품비용</span>상품 및 배송 상황에 따라 다름</p>
                        <p class="mb-6 text-left"><span class="inline-block w-20 md:w-28 font-black text-gray-500">접수방법</span>고객센터(1666-8320) 접수 후 처리</p>
                        <div class="mt-6 border-t border-gray-200 pt-6 text-left text-[9px] md:text-xs">
                            <p class="text-gray-700 font-black mb-4 text-xs md:text-sm text-left">🚫 교환/반품 제한사항 (원상복구)</p>
                            <ul class="list-disc pl-5 space-y-2 opacity-80 font-bold text-left">
                                <li class="text-left">주문/제작 상품의 경우, 상품의 제작이 이미 진행된 경우</li>
                                <li class="text-left">상품 포장을 개봉하여 사용 또는 설치 완료되어 상품의 가치가 훼손된 경우</li>
                                <li class="text-left">고객의 사용, 시간경과, 일부 소비에 의하여 상품의 가치가 현저히 감소한 경우</li>
                                <li class="text-left">세트상품 일부 사용, 구성품을 분실하였거나 취급 부주의로 인한 파손/고장/오염</li>
                                <li class="text-left">모니터 해상도의 차이로 인해 색상이나 이미지가 실제와 달라 변심 무료 반품 요청 시</li>
                                <li class="text-left">제조사의 사정 및 부품 가격 변동 등에 의해 무료 교환/반품으로 요청하는 경우</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        {% if keyword_recommends %}
        <div class="mt-24 border-t border-gray-100 pt-20 text-left">
            <h3 class="font-black text-2xl md:text-3xl mb-12 flex items-center gap-4 tracking-tighter text-left text-left">
                <span class="w-2 h-10 bg-green-500 rounded-full text-left"></span> ⭐ 연관 추천 상품
            </h3>
            <div class="horizontal-scroll no-scrollbar text-left text-left">
                {% for rp in keyword_recommends %}
                <a href="/product/{{rp.id}}" class="group flex-shrink-0 w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] text-left text-left">
                    <div class="bg-white rounded-[2rem] border border-gray-100 p-3 shadow-sm transition hover:shadow-xl hover:-translate-y-1 text-left text-left">
                        <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-4 rounded-2xl bg-gray-50 text-left text-left">
                        <p class="text-[10px] md:text-sm font-black text-gray-800 truncate text-left text-left">{{ rp.name }}</p>
                        <p class="text-[11px] md:text-base font-black text-green-600 mt-2 text-left text-left">{{ "{:,}".format(rp.price) }}원</p>
                    </div>
                </a>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="mt-16 border-t border-gray-100 pt-20 text-left text-left">
            <h3 class="font-black text-2xl md:text-3xl mb-12 flex items-center gap-4 tracking-tighter text-left text-left">
                <span class="w-2 h-10 bg-blue-500 rounded-full text-left"></span> ✨ 최근 등록 상품
            </h3>
            <div class="horizontal-scroll no-scrollbar text-left text-left">
                {% for rp in latest_all %}
                <a href="/product/{{rp.id}}" class="group flex-shrink-0 w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] text-left text-left">
                    <div class="bg-white rounded-[2rem] border border-gray-100 p-3 shadow-sm transition hover:shadow-xl hover:-translate-y-1 text-left text-left">
                        <img src="{{ rp.image_url }}" class="w-full aspect-square object-contain mb-4 rounded-2xl bg-gray-50 text-left">
                        <p class="text-[10px] md:text-sm font-black text-gray-800 truncate text-left">{{ rp.name }}</p>
                        <p class="text-[11px] md:text-base font-black text-green-600 mt-2 text-left">{{ "{:,}".format(rp.price) }}원</p>
                    </div>
                </a>
                {% endfor %}
            </div>
        </div>

        <div class="mt-24 border-t border-gray-100 pt-20 space-y-10 text-left">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-left text-left">
                <a href="/category/최신상품" class="bg-gray-800 text-white py-6 md:py-8 rounded-[2rem] text-center text-sm md:text-base font-black shadow-xl hover:bg-gray-700 transition flex items-center justify-center gap-3">
                    <i class="fas fa-sparkles"></i> 최신상품 전체보기
                </a>
                <a href="/category/{{ p.category }}" class="bg-white border-2 border-green-600 text-green-600 py-6 md:py-8 rounded-[2rem] text-center text-sm md:text-base font-black shadow-sm hover:bg-green-50 transition flex items-center justify-center gap-3">
                    <i class="fas fa-store"></i> 이 판매자 상품 전체보기
                </a>
            </div>
            
            <div class="bg-gray-100 p-10 md:p-16 rounded-[3.5rem] md:rounded-[5rem] text-left text-left">
                <div class="max-w-2xl mx-auto text-center text-left">
                    <p class="text-xs md:text-sm font-black text-gray-400 mb-6 uppercase tracking-[0.3em] text-center text-left">Looking for something else?</p>
                    <form action="/" method="GET" class="relative text-left text-left">
                        <input name="q" placeholder="찾으시는 다른 상품명을 입력해보세요" class="w-full bg-white py-5 px-10 rounded-full text-sm md:text-lg font-black outline-none shadow-xl focus:ring-4 focus:ring-green-100 transition text-left text-left">
                        <button class="absolute right-8 top-5 text-green-600 text-right"><i class="fas fa-search text-xl md:text-2xl"></i></button>
                    </form>
                </div>
            </div>
        </div>

        {% if cat_info and cat_info.biz_name %}
        <div class="mt-24 border-t border-gray-100 pt-20 text-left">
            <div class="bg-gray-50 p-10 md:p-20 rounded-[3.5rem] md:rounded-[5rem] border border-gray-100 shadow-sm text-left">
                <div class="flex items-center gap-5 mb-10 text-left text-left text-left">
                    <div class="w-12 h-12 md:w-16 md:h-16 bg-green-600 text-white rounded-full flex items-center justify-center text-xl md:text-2xl shadow-xl text-center"><i class="fas fa-info-circle"></i></div>
                    <h4 class="text-2xl md:text-4xl font-black text-gray-800 text-left text-left">서비스 이용 및 판매자 정보</h4>
                </div>
                <p class="text-gray-500 leading-loose mb-12 font-bold text-sm md:text-xl text-left text-left">본 상품은 바구니삼촌이 실제 상품 판매자의 제품을 송도 지역 고객님께 배송해 드리는 통합 유통 모델입니다. 실제 판매자 정보는 아래 버튼을 통해 확인 가능합니다.</p>
                
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 text-left">
                    <a href="/category/seller/{{ cat_info.id }}" class="bg-white border-2 border-gray-200 text-gray-800 px-8 py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-xs md:text-sm hover:bg-gray-100 transition shadow-sm flex items-center justify-center gap-4 text-center">
                        <i class="fas fa-address-card text-xl text-gray-400"></i> 사업자정보보기
                    </a>
                    {% if cat_info.biz_contact %}
                    <a href="tel:{{ cat_info.biz_contact }}" class="bg-white border-2 border-blue-100 text-blue-600 px-8 py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-xs md:text-sm hover:bg-blue-50 transition shadow-sm flex items-center justify-center gap-4 text-center">
                        <i class="fas fa-phone-alt text-xl"></i> 고객센터 연결
                    </a>
                    {% endif %}
                    {% if cat_info.seller_inquiry_link %}
                    <a href="{{ cat_info.seller_inquiry_link }}" target="_blank" class="bg-green-600 text-white px-8 py-6 rounded-[1.5rem] md:rounded-[2rem] font-black text-xs md:text-sm hover:bg-green-700 transition shadow-lg flex items-center justify-center gap-4 text-center">
                        <i class="fas fa-comment-dots text-xl"></i> 판매자 1:1 문의
                    </a>
                    {% endif %}
                </div>
                <p class="mt-12 text-[10px] md:text-sm text-gray-400 font-bold italic text-left text-left">※ 바구니삼촌은 물류 전문가가 송도 지역 거주민을 위해 구축한 프리미엄 배송 인프라입니다.</p>
            </div>
        </div>
        {% endif %}
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, detail_images=detail_images, cat_info=cat_info, latest_all=latest_all, keyword_recommends=keyword_recommends, product_reviews=product_reviews)

@app.route('/category/seller/<int:cid>')
def seller_info_page(cid):
    """판매 사업자 정보 상세 페이지"""
    cat = Category.query.get_or_404(cid)
    content = """
    <div class="max-w-xl mx-auto py-24 md:py-32 px-6 font-black text-left">
        <nav class="mb-12 text-left"><a href="javascript:history.back()" class="text-green-600 font-black hover:underline flex items-center gap-2"><i class="fas fa-arrow-left"></i> 이전으로 돌아가기</a></nav>
        <div class="bg-white rounded-[3rem] md:rounded-[5rem] shadow-2xl border border-gray-100 overflow-hidden text-left">
            <div class="bg-green-600 p-12 md:p-16 text-white text-center">
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
                <div class="p-8 md:p-12 bg-gray-50 rounded-[2rem] md:rounded-[3rem] border border-dashed border-gray-200 text-left"><p class="text-[10px] text-gray-400 uppercase tracking-[0.3em] mb-3 font-black text-left">Inquiry Center</p><p class="text-green-600 text-2xl md:text-4xl font-black italic text-left">{{ cat.biz_contact or '-' }}</p></div>
            </div>
            
            <div class="bg-gray-50 p-8 text-center border-t border-gray-100 text-[11px] text-gray-400 font-black uppercase tracking-[0.5em] text-center">
                바구니 삼촌 Premium Service
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, cat=cat)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """로그인 라우트"""
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user); return redirect('/')
        flash("로그인 정보를 다시 한 번 확인해주세요.")
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-24 p-10 md:p-16 bg-white rounded-[3rem] md:rounded-[4rem] shadow-2xl border text-left">
        <h2 class="text-3xl font-black text-center mb-16 text-green-600 uppercase italic tracking-tighter text-center">Login</h2>
        <form method="POST" class="space-y-8 text-left">
            <div class="space-y-2 text-left">
                <label class="text-[10px] text-gray-300 font-black uppercase tracking-widest ml-4 text-left">ID (Email)</label>
                <input name="email" type="email" placeholder="email@example.com" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-green-100 outline-none text-sm text-left" required>
            </div>
            <div class="space-y-2 text-left">
                <label class="text-[10px] text-gray-300 font-black uppercase tracking-widest ml-4 text-left">Password</label>
                <input name="password" type="password" placeholder="••••••••" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-green-100 outline-none text-sm text-left" required>
            </div>
            <button class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-lg md:text-xl shadow-xl hover:bg-green-700 transition active:scale-95 text-center">로그인</button>
        </form>
        <div class="text-center mt-10 text-center"><a href="/register" class="text-gray-400 text-xs font-black hover:text-green-600 transition text-center text-center">아직 회원이 아니신가요? 회원가입</a></div>
    </div>""" + FOOTER_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """회원가입 라우트 (전자상거래 동의 포함)"""
    if request.method == 'POST':
        name, email, pw, phone = request.form['name'], request.form['email'], request.form['password'], request.form['phone']
        addr, addr_d, ent_pw, memo = request.form['address'], request.form['address_detail'], request.form['entrance_pw'], request.form['request_memo']
        
        # 송도동 체크
        if "송도동" not in (addr or ""):
            flash("바구니삼촌은 현재 송도동 지역 전용 서비스입니다. 배송지 주소를 확인해주세요."); return redirect('/register')

        if not request.form.get('consent_e_commerce'):
            flash("전자상거래 이용 약관 및 유의사항에 동의해야 합니다."); return redirect('/register')

        if User.query.filter_by(email=email).first(): flash("이미 가입된 이메일입니다."); return redirect('/register')
        new_user = User(email=email, password=generate_password_hash(pw), name=name, phone=phone, address=addr, address_detail=addr_d, entrance_pw=ent_pw, request_memo=memo)
        db.session.add(new_user); db.session.commit(); return redirect('/login')
    return render_template_string(HEADER_HTML + """
    <div class="max-w-md mx-auto mt-12 mb-24 p-10 md:p-16 bg-white rounded-[3rem] md:rounded-[4rem] shadow-2xl border text-left">
        <h2 class="text-2xl md:text-3xl font-black mb-12 tracking-tighter uppercase text-green-600 text-left">Join Us</h2>
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
                <input name="address_detail" placeholder="상세주소 (동/호수)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="entrance_pw" placeholder="공동현관 비밀번호 (필수)" class="w-full p-5 bg-red-50 rounded-2xl font-black border border-red-100 text-sm text-left" required>
                <textarea name="request_memo" placeholder="배송 시 요청사항을 남겨주세요" class="w-full p-5 bg-white border border-gray-100 rounded-2xl font-black h-28 text-sm text-left"></textarea>
            </div>
            
            <div class="p-5 bg-gray-50 rounded-2xl border border-gray-100 text-[10px] space-y-3 mt-6 text-left">
                <label class="flex items-start gap-3 cursor-pointer group text-left text-left">
                    <input type="checkbox" name="consent_e_commerce" class="mt-0.5 w-4 h-4 rounded-full border-gray-300 text-green-600 focus:ring-green-500 text-left" required>
                    <span class="group-hover:text-gray-800 transition leading-tight text-left text-left">[필수] <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="underline decoration-green-300 text-left">전자상거래 이용자 유의사항</a> 및 서비스 이용 약관에 동의합니다.</span>
                </label>
            </div>

            <button class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-lg shadow-xl mt-6 hover:bg-green-700 transition active:scale-95 text-center text-center">가입 완료</button>
        </form>
    </div>""" + FOOTER_HTML)

@app.route('/logout')
def logout(): 
    """로그아웃"""
    logout_user(); return redirect('/')

@app.route('/mypage')
@login_required
def mypage():
    """마이페이지 (주문 취소 및 리뷰 작성 포함)"""
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """
    <div class="max-w-4xl mx-auto py-16 md:py-24 px-4 font-black text-left">
        <h2 class="text-3xl md:text-5xl font-black mb-16 border-l-8 border-green-600 pl-8 tracking-tighter uppercase italic text-left">My Center</h2>
        
        <div class="bg-white p-10 md:p-16 rounded-[3rem] md:rounded-[4rem] shadow-xl border border-gray-50 mb-20 relative overflow-hidden text-left text-left">
            <div class="relative z-10 text-left">
                <p class="text-2xl md:text-4xl font-black mb-3 text-gray-800 text-left">{{ current_user.name }} 고객님</p>
                <p class="text-gray-400 font-bold mb-12 text-sm md:text-lg text-left">{{ current_user.email }}</p>
                
                <div class="grid md:grid-cols-2 gap-12 pt-12 border-t border-gray-50 text-left">
                    <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-widest mb-4 font-black text-left">Shipping Address</p><p class="text-gray-700 font-bold text-base md:text-xl leading-relaxed text-left">{{ current_user.address }}<br>{{ current_user.address_detail }}</p></div>
                    <div class="text-left"><p class="text-[10px] text-gray-400 uppercase tracking-widest mb-4 font-black text-left">Gate Access</p><p class="text-red-500 font-black text-xl md:text-2xl text-left">🔑 {{ current_user.entrance_pw }}</p></div>
                </div>
            </div>
            <a href="/logout" class="absolute top-10 right-10 text-[10px] bg-gray-100 px-5 py-2 rounded-full text-gray-400 font-black hover:bg-gray-200 transition text-center">LOGOUT</a>
        </div>
        
        <h3 class="text-2xl md:text-3xl font-black mb-12 flex items-center gap-4 italic text-left text-left"><i class="fas fa-truck text-green-600 text-left"></i> History</h3>
        <div class="space-y-8 text-left">
            {% if orders %}
                {% for o in orders %}
                <div class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] shadow-sm border border-gray-100 hover:shadow-md transition-shadow text-left text-left">
                    <div class="flex justify-between items-start mb-6 text-left">
                        <p class="text-[10px] md:text-xs text-gray-300 font-black uppercase tracking-widest text-left">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }} | <span class="{% if o.status == '결제취소' %}text-red-400{% else %}text-green-600{% endif %}">{{ o.status }}</span></p>
                        {% if o.status == '결제완료' %}
                        <form action="/order/cancel/{{ o.id }}" method="POST" onsubmit="return confirm('정말 결제를 취소하시겠습니까? (신선식품은 준비가 시작된 경우 취소가 불가능할 수 있습니다)')" class="text-right">
                            <button class="text-[10px] bg-red-50 text-red-500 px-4 py-2 rounded-full font-black border border-red-100 hover:bg-red-500 hover:text-white transition text-center">결제취소</button>
                        </form>
                        {% endif %}
                    </div>
                    <p class="font-black text-gray-800 text-lg md:text-2xl leading-tight mb-8 text-left">{{ o.product_details }}</p>
                    <div class="flex justify-between items-center pt-8 border-t border-gray-50 font-black text-left">
                        <div class="flex gap-3 text-left">
                             {% if o.status != '결제취소' %}
                             <button onclick="openReviewModal('{{ o.id }}', '{{ o.product_details }}')" class="text-[11px] md:text-sm bg-green-50 text-green-600 px-5 py-2 rounded-full font-black border border-green-100 shadow-sm hover:bg-green-600 hover:text-white transition text-center">📸 사진리뷰 작성</button>
                             {% endif %}
                        </div>
                        <span class="text-2xl md:text-4xl text-green-600 italic text-right">{{ "{:,}".format(o.total_price) }}<span class="text-sm ml-1">원</span></span>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="bg-white py-40 text-center text-gray-300 rounded-[4rem] border-2 border-dashed font-black text-base md:text-xl text-center">서비스 이용 내역이 아직 없습니다.</div>
            {% endif %}
        </div>
    </div>

    <div id="review-modal" class="hidden fixed inset-0 bg-black/70 z-[3000] flex items-center justify-center p-6 text-left">
        <div class="bg-white w-full max-w-md rounded-[3rem] overflow-hidden shadow-2xl text-left text-left">
            <div class="bg-green-600 p-10 text-white text-left text-left">
                <h3 class="text-2xl font-black italic text-left">PHOTO REVIEW</h3>
                <p id="review-product-name" class="text-xs opacity-80 mt-2 truncate text-left"></p>
            </div>
            <form action="/review/add" method="POST" enctype="multipart/form-data" class="p-10 space-y-8 text-left">
                <input type="hidden" name="order_id" id="review-order-id">
                <div class="space-y-3 text-left">
                    <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-left">Photo upload</label>
                    <div class="p-6 border-2 border-dashed border-gray-100 rounded-3xl text-center relative hover:bg-gray-50 transition text-left">
                        <input type="file" name="review_image" class="absolute inset-0 opacity-0 cursor-pointer text-left" accept="image/*" required onchange="this.nextElementSibling.innerText=this.files[0].name">
                        <p class="text-xs text-gray-300 font-bold">터치하여 사진을 업로드하세요</p>
                    </div>
                </div>
                <div class="space-y-3 text-left">
                    <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-left">Your Comment</label>
                    <textarea name="content" placeholder="배송 상태나 품질에 대한 소중한 후기를 남겨주세요! (5자 이상)" class="w-full h-40 p-6 bg-gray-50 rounded-3xl text-sm font-bold outline-none focus:ring-4 focus:ring-green-50 border-none text-left" required minlength="5"></textarea>
                </div>
                <div class="flex gap-4 text-left">
                    <button type="button" onclick="closeReviewModal()" class="flex-1 py-5 bg-gray-100 text-gray-400 rounded-3xl font-black text-center">취소</button>
                    <button class="flex-2 px-10 py-5 bg-green-600 text-white rounded-3xl font-black shadow-xl hover:bg-green-700 transition text-center text-center">후기 등록하기</button>
                </div>
            </form>
        </div>
    </div>
    <script>
        function openReviewModal(oid, details) {
            document.getElementById('review-order-id').value = oid;
            document.getElementById('review-product-name').innerText = details;
            document.getElementById('review-modal').classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        }
        function closeReviewModal() {
            document.getElementById('review-modal').classList.add('hidden');
            document.body.style.overflow = 'auto';
        }
    </script>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, orders=orders)

@app.route('/order/cancel/<int:oid>', methods=['POST'])
@login_required
def order_cancel(oid):
    """결제 취소 로직 (재고 복구 포함)"""
    order = Order.query.get_or_404(oid)
    if order.user_id != current_user.id: return redirect('/mypage')
    if order.status != '결제완료': 
        flash("취소 가능한 상태가 아닙니다. 이미 배송이 시작되었을 수 있습니다."); return redirect('/mypage')
    
    # 1. 상태 변경
    order.status = '결제취소'
    
    # 2. 재고 복구 (주문 상세 텍스트 파싱)
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
    flash("결제가 성공적으로 취소되었습니다. 환불은 카드사 정책에 따라 3~7일 소요될 수 있습니다."); 
    return redirect('/mypage')

@app.route('/review/add', methods=['POST'])
@login_required
def review_add():
    """사진 리뷰 등록"""
    oid, content = request.form.get('order_id'), request.form.get('content')
    order = Order.query.get(oid)
    if not order or order.user_id != current_user.id: return redirect('/mypage')
    
    img_path = save_uploaded_file(request.files.get('review_image'))
    if not img_path: 
        flash("후기 사진 등록은 필수입니다."); return redirect('/mypage')
    
    # 리뷰 대상 상품 ID 추출 (첫 번째 상품 기준)
    p_name = order.product_details.split('(')[0].split(']')[-1].strip()
    match = re.search(r'\[(.*?)\] (.*?)\(', order.product_details)
    p_id = 0
    if match:
        first_p = Product.query.filter_by(name=match.group(2).strip()).first()
        if first_p: p_id = first_p.id

    new_review = Review(user_id=current_user.id, user_name=current_user.name, product_id=p_id, product_name=p_name, content=content, image_url=img_path)
    db.session.add(new_review)
    db.session.commit()
    flash("작성해주신 소중한 후기가 등록되었습니다. 감사합니다!"); 
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
    """장바구니 화면 (카테고리/금액별 배송비 계산)"""
    items = Cart.query.filter_by(user_id=current_user.id).all()
    
    # 배송비 계산: 카테고리별 합계 금액 50,000원당 1,900원 추가
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()]) if items else 0
    subtotal = sum(i.price * i.quantity for i in items)
    total = subtotal + delivery_fee
    
    content = f"""<div class="max-w-4xl mx-auto py-16 md:py-24 px-6 font-black text-left"><h2 class="text-2xl md:text-4xl font-black mb-16 border-l-8 border-green-600 pl-6 tracking-tighter uppercase italic text-left">Shopping Basket</h2><div class="bg-white rounded-[2.5rem] md:rounded-[4rem] shadow-2xl border border-gray-50 overflow-hidden text-left">
    {'<div class="p-8 md:p-16 space-y-10 text-left">' if items else '<div class="py-48 text-center text-gray-300 font-black text-center"><p class="text-7xl md:text-9xl mb-10 opacity-20 text-center">🧺</p><p class="text-xl md:text-3xl mb-12 text-center text-center">장바구니가 비어있습니다.</p><a href="/" class="inline-block bg-green-600 text-white px-12 py-5 rounded-full shadow-2xl font-black text-lg md:text-xl text-center">상품 보러가기</a></div>'}
    """
    if items:
        for i in items: content += f'<div class="flex justify-between items-center border-b border-gray-50 pb-10 text-left"><div class="flex-1 mr-6 text-left"><p class="font-black text-lg md:text-2xl text-gray-800 leading-tight text-left">{ i.product_name }</p><p class="text-green-600 font-black text-sm md:text-base mt-2 italic text-left">{ "{:,}".format(i.price) }원</p></div><div class="flex items-center gap-4 md:gap-8 bg-gray-100 px-5 py-3 md:px-8 md:py-4 rounded-2xl md:rounded-3xl text-left"><button onclick="minusFromCart({i.product_id})" class="text-gray-400 font-black text-2xl md:text-3xl hover:text-red-500 transition text-center">-</button><span class="font-black text-lg md:text-2xl w-8 md:w-12 text-center">{ i.quantity }</span><button onclick="addToCart({i.product_id})" class="text-gray-400 font-black text-2xl md:text-3xl hover:text-green-600 transition text-center">+</button></div><form action="/cart/delete/{i.product_id}" method="POST" class="ml-6 text-left"><button class="text-gray-200 hover:text-red-500 transition text-2xl md:text-3xl text-center"><i class="fas fa-trash-alt text-center"></i></button></form></div>'
        content += f'<div class="bg-gray-50 p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] space-y-6 mt-16 border border-gray-100 text-left"><div class="flex justify-between text-xs md:text-base text-gray-400 font-bold text-left"><span>Subtotal (상품 합계)</span><span>{ "{:,}".format(subtotal) }원</span></div><div class="flex justify-between text-xs md:text-base text-orange-400 font-bold text-left"><span>Delivery (카테고리별 배송료)</span><span>+ { "{:,}".format(delivery_fee) }원</span></div><div class="flex justify-between items-center pt-8 border-t border-gray-200 font-black text-left"><span class="text-xl md:text-3xl text-gray-700 uppercase italic text-left">Total Payment</span><span class="text-3xl md:text-6xl text-green-600 italic underline underline-offset-8 text-right">{ "{:,}".format(total) }원</span></div><p class="text-[10px] md:text-xs text-gray-400 mt-4 italic font-bold text-left">※ 배송비 안내: 카테고리별 기본 1,900원이며, 합계 금액 50,000원 초과 시 50,000원 단위로 1,900원이 추가 가산됩니다.</p></div><a href="/order/confirm" class="block text-center bg-green-600 text-white py-7 md:py-10 rounded-[2.5rem] md:rounded-[3rem] font-black text-xl md:text-3xl shadow-2xl mt-16 hover:bg-green-700 transition active:scale-95 italic uppercase tracking-tighter text-center">Checkout & Order</a></div>'
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, items=items, subtotal=subtotal, delivery_fee=delivery_fee, total=total)

@app.route('/order/confirm')
@login_required
def order_confirm():
    """결제 전 최종 확인 (송도동 배송지 제한 로직 포함)"""
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items: return redirect('/')
    
    cat_price_sums = {}
    for i in items: cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()])
    total = sum(i.price * i.quantity for i in items) + delivery_fee
    
    # [수정] Null-safe 송도동 배송지 체크
    is_songdo = "송도동" in (current_user.address or "")

    content = f"""<div class="max-w-md mx-auto py-24 md:py-32 px-4 font-black text-left"><h2 class="text-3xl font-black mb-12 border-b-4 border-green-600 pb-4 text-center uppercase italic text-center">Confirm Order</h2><div class="bg-white p-10 md:p-12 rounded-[3.5rem] md:rounded-[4.5rem] shadow-2xl border border-gray-50 space-y-12 text-left"><div class="p-8 md:p-10 {'bg-green-50 border-green-100' if is_songdo else 'bg-red-50 border-red-100'} rounded-[2.5rem] md:rounded-[3.5rem] border text-left relative overflow-hidden text-left text-left"><span class="{'text-green-600' if is_songdo else 'text-red-600'} text-[10px] block uppercase font-black mb-4 text-left">Delivery Point</span><p class="text-xl md:text-2xl text-gray-800 text-left font-black leading-snug">{ current_user.address or '정보 없음' }<br>{ current_user.address_detail or '' }</p><p class="mt-6 font-black text-base text-left">{'<span class="text-green-600 flex items-center gap-2"><i class="fas fa-check-circle"></i> 송도동 배송 가능 지역</span>' if is_songdo else '<span class="text-red-600 flex items-center gap-2"><i class="fas fa-exclamation-triangle"></i> 배송 불가 지역 (송도동 전용)</span>'}</p></div>{'<div class="p-8 bg-red-100 rounded-3xl text-red-700 text-xs md:text-sm font-bold text-left leading-relaxed">⚠️ 바구니삼촌은 인천 연수구 **송도동** 지역만 집중 배송하는 특화 서비스입니다. 주소를 송도동으로 수정해 주세요.</div>' if not is_songdo else ''}<div class="flex justify-between items-end pt-4 font-black text-left"><span class="text-gray-400 text-xs uppercase tracking-widest text-left">Grand Total</span><span class="text-4xl md:text-5xl text-green-600 italic underline underline-offset-8 text-right">{ "{:,}".format(total) }원</span></div><div class="bg-orange-50 p-6 rounded-3xl border border-orange-100 text-[10px] md:text-xs text-orange-700 font-bold text-left leading-relaxed">📢 배송비 안내: 카테고리별 5만원 단위 1,900원 가산 (현재 배송비: { "{:,}".format(delivery_fee) }원)</div><div class="p-8 bg-gray-50 rounded-[2.5rem] text-[10px] md:text-xs text-gray-500 space-y-5 font-black border border-gray-100 text-left text-left"><label class="flex items-start gap-4 cursor-pointer group text-left"><input type="checkbox" id="consent_agency" class="mt-1.5 w-4 h-4 rounded-full border-gray-300 text-green-600 text-left" required><span class="group-hover:text-gray-800 transition leading-relaxed text-left text-left text-left text-left">본인은 바구니삼촌이 상품 판매자가 아니며, 요청에 따라 대신 구매/배송하는 대행 기반 서비스임에 인지하고 동의합니다.</span></label><label class="flex items-start gap-4 pt-5 border-t border-gray-200 cursor-pointer group text-left text-left"><input type="checkbox" id="consent_third_party_order" class="mt-1.5 w-4 h-4 rounded-full border-gray-300 text-green-600 text-left" required><span class="group-hover:text-gray-800 transition leading-relaxed text-left text-left text-left text-left text-left">[필수] 개인정보 제3자 제공 동의 : 원활한 배송 처리를 위해 구매처 및 배송자에게 정보가 제공됨을 확인했습니다.</span></label></div>{f'<button onclick="startPayment()" class="w-full bg-green-600 text-white py-7 rounded-[2rem] md:rounded-[2.5rem] font-black text-xl md:text-2xl shadow-2xl active:scale-95 transition-all uppercase italic tracking-tighter hover:bg-green-700 text-center">Secure Payment</button>' if is_songdo else '<button class="w-full bg-gray-300 text-white py-7 rounded-[2rem] font-black text-xl cursor-not-allowed uppercase italic tracking-tighter text-center" disabled>Check Address</button>'}</div></div><script>function startPayment() {{ if(!document.getElementById('consent_agency').checked) {{ alert("이용 동의가 필요합니다."); return; }} if(!document.getElementById('consent_third_party_order').checked) {{ alert("개인정보 제공 동의가 필요합니다."); return; }} window.location.href = "/order/payment"; }}</script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, total=total, delivery_fee=delivery_fee, is_songdo=is_songdo)

@app.route('/order/payment')
@login_required
def order_payment():
    """토스페이먼츠 결제창 호출 라우트"""
    items = Cart.query.filter_by(user_id=current_user.id).all()
    if not items or "송도동" not in (current_user.address or ""): return redirect('/order/confirm')
    
    subtotal = sum(i.price * i.quantity for i in items)
    cat_price_sums = {}
    for i in items: 
        cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
    delivery_fee = sum([( (amt // 50001) + 1) * 1900 for amt in cat_price_sums.values()])
    
    total, tax_free = int(subtotal + delivery_fee), int(sum(i.price * i.quantity for i in items if i.tax_type == '면세'))
    order_id, order_name = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{current_user.id}", f"{items[0].product_name} 외 {len(items)-1}건" if len(items) > 1 else items[0].product_name
    
    content = f"""<div class="max-w-md mx-auto py-40 text-center font-black text-center text-center text-center"><div class="w-24 h-24 bg-blue-100 rounded-full flex items-center justify-center text-5xl mx-auto mb-12 text-blue-600 shadow-2xl animate-pulse text-center">🛡️</div><h2 class="text-3xl font-black mb-12 text-gray-800 uppercase italic text-center">Secure Gateway</h2><button id="payment-button" class="w-full bg-blue-600 text-white py-7 rounded-[2.5rem] font-black text-xl shadow-xl hover:bg-blue-700 transition active:scale-95 text-center">결제창 열기</button></div><script>var tossPayments = TossPayments("{TOSS_CLIENT_KEY}"); document.getElementById('payment-button').addEventListener('click', function() {{ tossPayments.requestPayment('카드', {{ amount: { total }, taxFreeAmount: { tax_free }, orderId: '{ order_id }', orderName: '{ order_name }', customerName: '{ current_user.name }', successUrl: window.location.origin + '/payment/success', failUrl: window.location.origin + '/payment/fail' }}); }});</script>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

# [수정] 결제 성공 화면 내 '바로가기 추가' 버튼 포함
@app.route('/payment/success')
@login_required
def payment_success():
    """결제 성공 및 주문 생성"""
    pk, oid, amt = request.args.get('paymentKey'), request.args.get('orderId'), request.args.get('amount')
    url, auth_key = "https://api.tosspayments.com/v1/payments/confirm", base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    res = requests.post(url, json={"paymentKey": pk, "amount": amt, "orderId": oid}, headers={"Authorization": f"Basic {auth_key}", "Content-Type": "application/json"})
    
    if res.status_code == 200:
        items = Cart.query.filter_by(user_id=current_user.id).all()
        cat_groups = {i.product_category: [] for i in items}
        for i in items: cat_groups[i.product_category].append(f"{i.product_name}({i.quantity})")
        details = " | ".join([f"[{cat}] {', '.join(prods)}" for cat, prods in cat_groups.items()])
        
        cat_price_sums = {}
        for i in items: cat_price_sums[i.product_category] = cat_price_sums.get(i.product_category, 0) + (i.price * i.quantity)
        delivery_fee = sum([( (amt_ // 50001) + 1) * 1900 for amt_ in cat_price_sums.values()])

        db.session.add(Order(user_id=current_user.id, customer_name=current_user.name, customer_phone=current_user.phone, customer_email=current_user.email, product_details=details, total_price=int(amt), delivery_fee=delivery_fee, tax_free_amount=sum(i.price * i.quantity for i in items if i.tax_type == '면세'), order_id=oid, payment_key=pk, delivery_address=f"({current_user.address}) {current_user.address_detail} (현관:{current_user.entrance_pw})", request_memo=current_user.request_memo, status='결제완료'))
        for i in items:
            p = Product.query.get(i.product_id)
            if p: p.stock -= i.quantity
        Cart.query.filter_by(user_id=current_user.id).delete(); db.session.commit()
        
        return render_template_string(HEADER_HTML + """<div class="max-w-md mx-auto py-48 text-center font-black text-center text-center">
                                      <div class="w-28 h-28 bg-green-500 rounded-full flex items-center justify-center text-white text-5xl mx-auto mb-12 shadow-2xl animate-bounce text-center">
                                      <i class="fas fa-check"></i></div><h2 class="text-3xl md:text-4xl font-black mb-8 text-center">주문 성공!</h2><p class="text-gray-400 font-bold mb-16 text-sm md:text-base text-center">
                                      최적의 경로로 배송해 드리겠습니다.</p><div class="flex flex-col gap-5 text-center"><a href="/" class="bg-gray-800 text-white py-5 rounded-full font-black text-lg shadow-xl hover:scale-105 transition text-center">
                                      홈으로 돌아가기</a>)" </div></div>""" + FOOTER_HTML)
    return redirect('/')

# --------------------------------------------------------------------------------
# 6. 관리자 전용 기능 (Dashboard / Bulk Upload / Excel)
# --------------------------------------------------------------------------------
# --- [신규 추가] 카테고리 관리자의 배송 요청 기능 ---
@app.route('/admin/order/request_delivery/<string:order_id>', methods=['POST'])
@login_required
def admin_request_delivery(order_id):
    # 권한 체크 (어드민이거나 해당 카테고리 매니저인지)
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()):
        return redirect('/')
    
    order = Order.query.filter_by(order_id=order_id).first()
    if order and order.status == '결제완료':
        order.status = '배송요청'  # 상태를 '배송요청'으로 변경
        db.session.commit()
        flash(f"주문 {order_id} 건이 배송 시스템으로 요청되었습니다.")
    
    return redirect('/admin?tab=orders')
@app.route('/admin')
@login_required
def admin_dashboard():
    """관리자 대시보드 - 카테고리 관리 기능 및 주문 탭 오류 수정 완료본"""
    # 1. 권한 체크 (마스터 관리자이거나 등록된 매니저인 경우 접근 허용)
    categories = Category.query.order_by(Category.order.asc(), Category.id.asc()).all()
    managers = [c.manager_email for c in categories if c.manager_email]
    
    if not (current_user.is_admin or current_user.email in managers):
        flash("관리자 권한이 없습니다.")
        return redirect('/')
    
    is_master = current_user.is_admin
    tab = request.args.get('tab', 'products')
    my_categories = [c.name for c in categories if c.manager_email == current_user.email]
    
    # [안정성] 모든 탭에서 공용으로 사용하는 변수 초기화
    sel_cat = request.args.get('category', '전체')
    sel_order_cat = request.args.get('order_cat', '전체')
    start_date_str = request.args.get('start_date', datetime.now().strftime('%Y-%m-%dT00:00'))
    end_date_str = request.args.get('end_date', datetime.now().strftime('%Y-%m-%dT23:59'))
    products, filtered_orders, summary, reviews = [], [], {}, []

    if tab == 'products':
        q = Product.query
        if sel_cat != '전체': q = q.filter_by(category=sel_cat)
        products = [p for p in q.order_by(Product.id.desc()).all() if is_master or p.category in my_categories]
    
    elif tab == 'orders':
        try:
            start_dt = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
            end_dt = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
        except:
            start_dt = datetime.now().replace(hour=0, minute=0)
            end_dt = datetime.now().replace(hour=23, minute=59)

        all_orders = Order.query.filter(Order.created_at >= start_dt, Order.created_at <= end_dt).order_by(Order.created_at.desc()).all()
        for o in all_orders:
            show = False
            for p_info in o.product_details.split(' | '):
                match = re.match(r'\[(.*?)\] (.*)', p_info)
                if match:
                    cat_n, items_str = match.groups()
                    if (is_master or cat_n in my_categories) and (sel_order_cat == '전체' or cat_n == sel_order_cat):
                        show = True
                        if cat_n not in summary: summary[cat_n] = {}
                        for item in items_str.split(', '):
                            it_match = re.match(r'(.*?)\((\d+)\)', item)
                            if it_match: pn, qt = it_match.groups(); summary[cat_n][pn] = summary[cat_n].get(pn, 0) + int(qt)
            if show: filtered_orders.append(o)
            
    elif tab == 'reviews':
        reviews = Review.query.order_by(Review.created_at.desc()).all()

    # 렌더링 시 **locals()를 통해 모든 변수 안전하게 전달
    return render_template_string(HEADER_HTML + """
    <div class="max-w-7xl mx-auto py-12 px-4 md:px-6 font-black text-xs md:text-sm text-left">
        <div class="flex justify-between items-center mb-10 text-left">
            <h2 class="text-2xl md:text-3xl font-black text-orange-700 italic text-left">Admin Panel</h2>
            <div class="flex gap-4 text-left"><a href="/logout" class="text-xs text-gray-400 hover:text-red-500 text-left">로그아웃</a></div>
        </div>
        
        <div class="flex border-b border-gray-100 mb-12 bg-white rounded-t-3xl overflow-x-auto text-left">
            <a href="/admin?tab=products" class="px-8 py-5 {% if tab == 'products' %}border-b-4 border-orange-500 text-orange-600{% endif %}">상품 관리</a>
            {% if is_master %}<a href="/admin?tab=categories" class="px-8 py-5 {% if tab == 'categories' %}border-b-4 border-orange-500 text-orange-600{% endif %}">카테고리/판매자 설정</a>{% endif %}
            <a href="/admin?tab=orders" class="px-8 py-5 {% if tab == 'orders' %}border-b-4 border-orange-500 text-orange-600{% endif %}">주문 및 배송 집계</a>
            <a href="/admin?tab=reviews" class="px-8 py-5 {% if tab == 'reviews' %}border-b-4 border-orange-500 text-orange-600{% endif %}">리뷰 관리</a>
        </div>

        {% if tab == 'products' %}
            <div class="flex flex-col sm:flex-row justify-between items-center mb-8 gap-6 text-left">
                <form action="/admin" class="flex gap-3 text-left">
                    <input type="hidden" name="tab" value="products">
                    <select name="category" onchange="this.form.submit()" class="border border-gray-100 p-3 rounded-2xl text-[11px] font-black bg-white shadow-sm text-left">
                        <option value="전체">전체 카테고리</option>
                        {% for c in categories %}<option value="{{c.name}}" {% if sel_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}
                    </select>
                </form>
                <div class="flex gap-3 text-left">
                    <button onclick="document.getElementById('excel_upload_form').classList.toggle('hidden')" class="bg-blue-600 text-white px-6 py-3 rounded-2xl font-black text-xs shadow-lg hover:bg-blue-700 transition">📦 엑셀 대량 등록</button>
                    <a href="/admin/add" class="bg-green-600 text-white px-6 py-3 rounded-2xl font-black text-xs shadow-lg hover:bg-green-700 transition">+ 개별 상품 등록</a>
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
                                <span class="text-green-600 font-bold text-[10px] md:text-xs">{{ p.description or '설명 없음' }}</span><br>
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
                        <div class="border-t border-gray-100 pt-8 space-y-4 text-left">
                            <p class="text-[10px] text-green-600 font-bold tracking-widest uppercase text-left">Seller Business Profile</p>
                            <input name="biz_name" placeholder="사업자 상호명" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_representative" placeholder="대표자 성함" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_reg_number" placeholder="사업자 등록번호 ( - 포함 )" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_address" placeholder="사업장 소재지" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="biz_contact" placeholder="고객 센터 번호" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                            <input name="seller_link" placeholder="판매자 문의 (카카오/채팅) 링크" class="border border-gray-100 p-4 rounded-xl w-full font-bold text-xs md:text-sm text-left">
                        </div>
                        <button class="w-full bg-green-600 text-white py-5 rounded-3xl font-black text-base md:text-lg shadow-xl hover:bg-green-700 transition text-center">신규 카테고리 생성</button>
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

        {% elif tab == 'orders' %}
            <div class="bg-white p-8 md:p-12 rounded-[2.5rem] border border-gray-50 shadow-sm mb-12 text-left">
                <form action="/admin" method="GET" class="grid grid-cols-1 md:grid-cols-4 gap-6 text-left">
                    <input type="hidden" name="tab" value="orders">
                    <div>
                        <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-left">조회 시작일</label>
                        <input type="datetime-local" name="start_date" value="{{ start_date_str }}" class="w-full border border-gray-100 p-4 rounded-2xl font-black mt-2 text-xs text-left">
                    </div>
                    <div>
                        <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-left">조회 종료일</label>
                        <input type="datetime-local" name="end_date" value="{{ end_date_str }}" class="w-full border border-gray-100 p-4 rounded-2xl font-black mt-2 text-xs text-left">
                    </div>
                    <div>
                        <label class="text-[10px] text-gray-400 font-black uppercase tracking-widest text-left">필터링</label>
                        <select name="order_cat" class="w-full border border-gray-100 p-4 rounded-2xl font-black bg-white mt-2 text-xs text-left">
                            <option value="전체">모든 카테고리</option>
                            {% for c in nav_categories %}<option value="{{c.name}}" {% if sel_order_cat == c.name %}selected{% endif %}>{{c.name}}</option>{% endfor %}
                        </select>
                    </div>
                    <div class="flex items-end text-left"><button class="w-full bg-orange-600 text-white py-4 rounded-2xl font-black shadow-lg text-xs md:text-sm text-center">집계 업데이트</button></div>
                </form>
            </div>

            {% for cat_n, items in summary.items() %}
            <div class="bg-white rounded-[2rem] border border-gray-50 overflow-hidden mb-10 shadow-sm">
             <div class="bg-gray-50 px-8 py-5 border-b border-gray-100 font-black text-green-700 flex justify-between items-center">
    <div class="flex items-center gap-3">
        <input type="checkbox" class="task-check w-4 h-4 rounded border-slate-300 accent-green-600" 
       value="{{t.id}}" data-category="{{ t.category }}">
        <span>{{ cat_n }}</span>
    </div>
    <span class="text-gray-400 font-bold">총계: {{ items.values()|sum }}개</span>
</div>

<script>
function toggleCategoryAll(master, catName) {
    // 1. 해당 카테고리 섹션 내의 체크박스들만 찾습니다.
    // 데이터 속성을 활용하여 특정 카테고리의 오더만 타겟팅합니다.
    const checkboxes = document.querySelectorAll(`.task-check[data-category="${catName}"]`);
    checkboxes.forEach(cb => {
        cb.checked = master.checked;
    });
}
</script>
                <table class="w-full">
                    {% for pn, qt in items.items() %}
                    <tr class="border-b border-gray-50"><td class="p-5 font-bold text-gray-700">{{ pn }}</td><td class="p-5 text-right font-black text-blue-600">{{ qt }}개</td></tr>
                    {% endfor %}
                </table>
            </div>
            {% endfor %}

            <div class="bg-white rounded-[2.5rem] shadow-xl border border-gray-50 overflow-x-auto">
                <table class="w-full text-[10px] md:text-xs font-black min-w-[1200px]">
                    <thead class="bg-gray-800 text-white">
                        <tr><th class="p-6">Info</th><th class="p-6">Customer</th><th class="p-6">Address</th><th class="p-6">Details</th><th class="p-6 text-right">Action</th></tr>
                    </thead>
                    <tbody>
                        {% for o in filtered_orders %}
                        <tr class="border-b border-gray-100 hover:bg-green-50/30 transition">
                            <td class="p-6 text-gray-400">
                                {{ o.created_at.strftime('%m/%d %H:%M') }}<br>
                                <span class="{% if o.status == '결제취소' %}text-red-500{% else %}text-green-600{% endif %}">[{{ o.status }}]</span>
                            </td>
                            <td class="p-6"><b>{{ o.customer_name }}</b><br>{{ o.customer_phone }}</td>
                            <td class="p-6">{{ o.delivery_address }}<br><span class="text-orange-500 italic">📝 {{ o.request_memo or '' }}</span></td>
                            <td class="p-6 text-gray-600 leading-relaxed">{{ o.product_details }}</td>
                            <td class="p-6 text-right font-black text-green-600 text-sm md:text-lg">
                                {{ "{:,}".format(o.total_price) }}원<br>
                                {% if o.status == '결제완료' %}
                                <form action="/admin/order/request_delivery/{{ o.order_id }}" method="POST" class="mt-2">
                                    <button class="bg-blue-600 text-white px-3 py-1 rounded-lg text-[10px] font-black hover:bg-blue-700 transition">배송요청</button>
                                </form>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="flex justify-end mt-12"><a href="/admin/orders/excel" class="bg-gray-800 text-white px-10 py-5 rounded-2xl font-black text-xs md:text-sm shadow-2xl transition text-center">Excel Download</a></div>

        {% elif tab == 'reviews' %}
            <div class="bg-white rounded-[2.5rem] shadow-xl border border-gray-50 overflow-hidden">
                <table class="w-full text-[10px] md:text-xs font-black text-left">
                    <thead class="bg-gray-800 text-white">
                        <tr><th class="p-6">상품/작성자</th><th class="p-6">내용</th><th class="p-6 text-center">관리</th></tr>
                    </thead>
                    <tbody>
                        {% for r in reviews %}
                        <tr class="border-b border-gray-100 hover:bg-red-50/30">
                            <td class="p-6"><span class="text-green-600">[{{ r.product_name }}]</span><br>{{ r.user_name }}</td>
                            <td class="p-6">{{ r.content }}</td>
                            <td class="p-6 text-center"><a href="/admin/review/delete/{{ r.id }}" class="bg-red-500 text-white px-4 py-2 rounded-full" onclick="return confirm('삭제하시겠습니까?')">삭제</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% endif %}
    </div>""" + FOOTER_HTML, **locals())

# --------------------------------------------------------------------------------
# 7. 엑셀 대량 업로드 (사용자 커스텀 양식 대응)
# --------------------------------------------------------------------------------
# 관리자 주문 탭에서 개별 건에 대해 배송요청 상태로 변경하는 라우트
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
# 8. 개별 상품 등록/수정/삭제 및 카테고리 관리
# --------------------------------------------------------------------------------

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def admin_product_add():
    """개별 상품 등록"""
    if request.method == 'POST':
        cat_name = request.form['category']
        if not check_admin_permission(cat_name): return redirect('/admin')
        main_img = save_uploaded_file(request.files.get('main_image'))
        detail_files = request.files.getlist('detail_images')
        detail_img_url_str = ",".join(filter(None, [save_uploaded_file(f) for f in detail_files if f.filename != '']))
        new_p = Product(name=request.form['name'], description=request.form['description'], category=cat_name, price=int(request.form['price']), spec=request.form['spec'], origin=request.form['origin'], farmer="바구니삼촌", stock=int(request.form['stock']), image_url=main_img or "", detail_image_url=detail_img_url_str, deadline=datetime.strptime(request.form['deadline'], '%Y-%m-%dT%H:%M') if request.form.get('deadline') else None, badge=request.form['badge'])
        db.session.add(new_p); db.session.commit(); return redirect('/admin')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-6 font-black text-left"><h2 class="text-3xl font-black mb-12 border-l-8 border-green-600 pl-6 uppercase italic text-left">Add Product</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-10 rounded-[3rem] shadow-2xl space-y-7 text-left"><select name="category" class="w-full p-5 bg-gray-50 rounded-2xl font-black outline-none focus:ring-4 focus:ring-green-50 text-left">{% for c in nav_categories %}<option value="{{c.name}}">{{c.name}}</option>{% endfor %}</select><input name="name" placeholder="상품 정식 명칭" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" required><input name="description" placeholder="배송기한(예 오늘주문 내일배송)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"><div class="grid grid-cols-2 gap-5 text-left"><input name="price" type="number" placeholder="판매 가격(원)" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" required><input name="spec" placeholder="규격 (예: 5kg/1박스)" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"></div><div class="grid grid-cols-2 gap-5 text-left"><input name="stock" type="number" placeholder="재고 수량" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" value="50"><input name="deadline" type="datetime-local" class="p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"></div><input name="origin" placeholder="원산지 정보" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm" value="국산"><select name="badge" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-left text-sm"><option value="">노출 뱃지 없음</option><option value="오늘마감">🔥 오늘마감</option><option value="삼촌추천">⭐ 삼촌추천</option></select><div class="p-6 border-2 border-dashed border-gray-100 rounded-3xl text-left"><label class="text-[10px] text-gray-400 uppercase font-black block mb-4 text-left">Main Image (목록 노출)</label><input type="file" name="main_image" class="text-xs text-left"></div><div class="p-6 border-2 border-dashed border-blue-50 rounded-3xl text-left"><label class="text-[10px] text-blue-400 uppercase font-black block mb-4 text-left">Detail Images (상세 내 노출)</label><input type="file" name="detail_images" multiple class="text-xs text-left"></div><button class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-xl shadow-xl hover:bg-green-700 transition active:scale-95 text-center">상품 등록 완료</button></form></div>""")

@app.route('/admin/edit/<int:pid>', methods=['GET', 'POST'])
@login_required
def admin_product_edit(pid):
    """개별 상품 수정"""
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
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-6 font-black text-left"><h2 class="text-3xl font-black mb-12 border-l-4 md:border-l-8 border-green-600 pl-4 md:pl-6 uppercase italic text-gray-800 text-left text-left">Edit Product</h2><form method="POST" enctype="multipart/form-data" class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[4rem] shadow-2xl space-y-7 text-left text-left"><input name="name" value="{{p.name}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base text-left text-left text-left"><input name="description" value="{{p.description or ''}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base text-left text-left text-left"><input name="price" type="number" value="{{p.price}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base text-left text-left text-left"><input name="stock" type="number" value="{{p.stock}}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base text-left text-left text-left"><input name="deadline" type="datetime-local" value="{{ p.deadline.strftime('%Y-%m-%dT%H:%M') if p.deadline else '' }}" class="w-full p-5 md:p-6 bg-gray-50 rounded-2xl font-black text-sm md:text-base text-left text-left text-left text-left"><div class="p-8 border-2 border-dashed border-gray-100 rounded-3xl text-left text-left text-left text-left"><label class="text-[10px] text-blue-600 font-black block mb-4 uppercase text-left text-left">Update Detail Images (Multi)</label><input type="file" name="detail_images" multiple class="text-[10px] text-left text-left text-left"></div><button class="w-full bg-blue-600 text-white py-6 md:py-8 rounded-[1.5rem] md:rounded-[2rem] font-black text-lg md:text-2xl shadow-xl hover:bg-blue-700 transition italic uppercase text-center text-center">Apply Changes</button></form></div>""", p=p)

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
    db.session.add(Category(name=request.form['cat_name'], description=request.form.get('description'), tax_type=request.form['tax_type'], manager_email=request.form.get('manager_email'), seller_name=request.form.get('biz_name'), seller_inquiry_link=request.form.get('seller_link'), biz_name=request.form.get('biz_name'), biz_representative=request.form.get('biz_representative'), biz_reg_number=request.form.get('biz_reg_number'), biz_address=request.form.get('biz_address'), biz_contact=request.form.get('biz_contact'), order=next_order))
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
        cat.seller_name = cat.biz_name
        db.session.commit(); return redirect('/admin?tab=categories')
    return render_template_string(HEADER_HTML + """<div class="max-w-xl mx-auto py-20 px-6 font-black text-left"><h2 class="text-2xl md:text-3xl font-black mb-12 tracking-tighter uppercase text-green-600 text-left">Edit Category Profile</h2><form method="POST" class="bg-white p-10 rounded-[3rem] shadow-2xl space-y-8 text-left"><div><label class="text-[10px] text-gray-400 uppercase font-black ml-4 text-left">Settings</label><input name="cat_name" value="{{cat.name}}" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-2 text-sm text-left" required><textarea name="description" class="border border-gray-100 p-5 rounded-2xl w-full h-24 font-black mt-3 text-sm text-left" placeholder="한줄 소개">{{cat.description or ''}}</textarea><input name="manager_email" value="{{cat.manager_email or ''}}" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-3 text-sm text-left" placeholder="매니저 이메일"><select name="tax_type" class="border border-gray-100 p-5 rounded-2xl w-full font-black mt-3 text-sm text-left bg-white"><option value="과세" {% if cat.tax_type == '과세' %}selected{% endif %}>과세</option><option value="면세" {% if cat.tax_type == '면세' %}selected{% endif %}>면세</option></select></div><div class="border-t border-gray-50 pt-10 space-y-4 text-left"><label class="text-[10px] text-green-600 uppercase font-black ml-4 text-left">Business Info</label><input name="biz_name" value="{{cat.biz_name or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="상호명"><input name="biz_representative" value="{{cat.biz_representative or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="대표자"><input name="biz_reg_number" value="{{cat.biz_reg_number or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="사업자번호"><input name="biz_address" value="{{cat.biz_address or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="주소"><input name="biz_contact" value="{{cat.biz_contact or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="고객센터"><input name="seller_link" value="{{cat.seller_inquiry_link or ''}}" class="border border-gray-100 p-4 rounded-xl w-full font-black text-xs text-left" placeholder="문의 링크 URL"></div><button class="w-full bg-blue-600 text-white py-6 rounded-3xl font-black shadow-xl hover:bg-blue-700 transition text-center text-center">Save Profile Updates</button></form></div>""", cat=cat)

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

@app.route('/admin/orders/excel')
@login_required
def admin_orders_excel():
    """주문 내역 전체 엑셀 다운로드"""
    if not current_user.is_admin: return redirect('/admin')
    all_categories = [c.name for c in Category.query.all()]
    orders = Order.query.order_by(Order.created_at.desc()).all()
    data = []
    for o in orders:
        row = {"일시": o.created_at.strftime('%Y-%m-%d %H:%M'), "고객명": o.customer_name, "전화번호": o.customer_phone, "이메일": o.customer_email, "주소": o.delivery_address, "메모": o.request_memo, "상태": o.status, "총액": o.total_price, "배송비": o.delivery_fee}
        parts = o.product_details.split(' | ')
        for cat in all_categories: row[f"[{cat}] 품명"], row[f"[{cat}] 수량"] = "", ""
        for part in parts:
            match = re.match(r'\[(.*?)\] (.*)', part)
            if match:
                cat_n, items_str = match.groups()
                if cat_n in all_categories:
                    row[f"[{cat_n}] 품명"] = items_str
        data.append(row)
    df = pd.DataFrame(data); out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w: df.to_excel(w, index=False)
    out.seek(0); return send_file(out, download_name=f"BasketUncle_Orders_{datetime.now().strftime('%m%d_%H%M')}.xlsx", as_attachment=True)

# --------------------------------------------------------------------------------
# 9. 데이터베이스 초기화 및 서버 실행
# --------------------------------------------------------------------------------

def init_db():
    """데이터베이스 및 기초 데이터 생성"""
    with app.app_context():
        db.create_all()
        # 누락된 컬럼 수동 추가 (ALTER TABLE 로직)
        cols = [
            ("product", "description", "VARCHAR(200)"), ("product", "detail_image_url", "TEXT"), ("user", "request_memo", "VARCHAR(500)"), ("order", "delivery_fee", "INTEGER DEFAULT 0"), ("product", "badge", "VARCHAR(50)"), ("category", "seller_name", "VARCHAR(100)"), ("category", "seller_inquiry_link", "VARCHAR(500)"), ("category", "order", "INTEGER DEFAULT 0"), ("category", "description", "VARCHAR(200)"), ("category", "biz_name", "VARCHAR(100)"), ("category", "biz_representative", "VARCHAR(50)"), ("category", "biz_reg_number", "VARCHAR(50)"), ("category", "biz_address", "VARCHAR(200)"), ("category", "biz_contact", "VARCHAR(50)"), ("order", "status", "VARCHAR(20) DEFAULT '결제완료'"), ("review", "user_name", "VARCHAR(50)"), ("review", "product_name", "VARCHAR(100)")
        ]
        for t, c, ct in cols:
            try: db.session.execute(text(f"ALTER TABLE \"{t}\" ADD COLUMN \"{c}\" {ct}")); db.session.commit()
            except: db.session.rollback()
            
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
            
    init_db() # 기존 쇼핑몰 초기화 함수 호출
    
    # 로컬 테스트 및 Render 배포 호환 포트 설정
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)