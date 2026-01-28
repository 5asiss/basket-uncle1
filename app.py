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

# --------------------------------------------------------------------------------
# 1. 초기 설정 및 Flask 인스턴스 생성
# --------------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = "basket_uncle_direct_trade_key_999_secure"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///direct_trade_mall.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 결제 연동 키 (Toss Payments)
TOSS_CLIENT_KEY = "test_ck_DpexMgkW36zB9qm5m4yd3GbR5ozO"
TOSS_SECRET_KEY = "test_sk_0RnYX2w532E5k7JYaJye8NeyqApQ"

# 파일 업로드 경로 설정
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>바구니삼촌 - 신개념 6PL 생활서비스 </title>
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
        <div class="max-w-7xl mx-auto px-4 md:px-6">
            <div class="flex justify-between h-16 md:h-20 items-center">
                <div class="flex items-center gap-3 md:gap-6">
                    <button onclick="toggleSidebar()" class="text-gray-400 text-xl md:text-2xl hover:text-green-600 transition p-2">
                        <i class="fas fa-bars"></i>
                    </button>
                    <a href="/" class="flex items-center gap-2.5">
                        <img src="/static/logo/side1.jpg" alt="바구니삼촌" class="h-8 md:h-10 w-auto rounded-lg" onerror="this.src='https://placehold.co/100x40?text=Uncle'">
                        <span class="italic tracking-tighter uppercase font-black text-green-600 text-lg md:text-xl hidden sm:block">바구니삼촌</span>
                    </a>
                </div>

                <div class="flex items-center gap-3 md:gap-5 flex-1 justify-end">
                    <form action="/" method="GET" class="relative hidden md:block max-w-xs flex-1">
                        <input name="q" placeholder="상품검색" class="w-full bg-gray-100 py-2.5 px-6 rounded-full text-xs font-black outline-none focus:ring-4 focus:ring-green-50 transition border border-transparent focus:border-green-100">
                        <button class="absolute right-4 top-2.5 text-gray-400 hover:text-green-600 transition"><i class="fas fa-search"></i></button>
                    </form>
                    
                    <button onclick="document.getElementById('mobile-search-nav').classList.toggle('hidden')" class="md:hidden text-gray-400 p-2 text-xl"><i class="fas fa-search"></i></button>

                    {% if current_user.is_authenticated %}
                        <a href="/cart" class="text-gray-400 relative p-2 hover:text-green-600 transition">
                            <i class="fas fa-shopping-cart text-2xl md:text-3xl"></i>
                            <span id="cart-count-badge" class="absolute top-0 right-0 bg-red-500 text-white text-[9px] md:text-[10px] rounded-full px-1.5 py-0.5 font-black border-2 border-white shadow-sm">{{ cart_count }}</span>
                        </a>
                        <a href="/mypage" class="text-gray-600 font-black bg-gray-100 px-4 py-2 rounded-full text-[10px] md:text-xs hover:bg-gray-200 transition">MY</a>
                    {% else %}
                        <a href="/login" class="text-gray-400 font-black text-xs md:text-sm hover:text-green-600 transition">로그인</a>
                        <a href="/register" class="bg-green-600 text-white px-5 py-2.5 rounded-full text-xs font-black shadow-lg hover:bg-green-700 transition hidden sm:block">시작하기</a>
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

    <div id="term-modal">
        <div id="term-modal-content">
            <div class="p-8 border-b border-gray-100 flex justify-between items-center">
                <h3 id="term-title" class="text-xl font-black text-gray-800"></h3>
                <button onclick="closeUncleModal()" class="text-gray-400 text-2xl"><i class="fas fa-times"></i></button>
            </div>
            <div id="term-modal-body"></div>
            <div class="p-8 bg-gray-50 text-center">
                <button onclick="closeUncleModal()" class="bg-gray-800 text-white px-10 py-4 rounded-full font-black text-sm">닫기</button>
            </div>
        </div>
    </div>

    <footer class="bg-gray-900 text-gray-400 py-16 md:py-24 border-t border-white/5 mt-20 text-left">
        <div class="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 md:gap-20 text-left">
            <div class="text-left">
                <p class="text-green-500 font-black text-3xl italic tracking-tighter mb-6 uppercase text-left">바구니삼촌</p>
                <div class="text-xs md:text-sm space-y-2 opacity-70 leading-loose font-black text-left">
                    <p>상호: 바구니삼촌 | 성명: 금창권</p>
                    <p>사업장소재지: 인천광역시 연수구 하모니로158, d동3층317호 (송도동, 송도 타임스페이스)</p>
                    <p>사업자등록번호: 472-93-02262 | 통신판매업신고: 제 2025-인천연수-3388호</p>
                    <p>전화번호: 1666-8320 | 이메일: basamsongdo@gmail.com</p>
                    <div class="pt-8 flex flex-wrap gap-6 opacity-60 underline text-left">
                        <a href="javascript:void(0)" onclick="openUncleModal('terms')" class="hover:text-white transition">이용약관</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('privacy')" class="hover:text-white transition">개인정보처리방침</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('agency')" class="hover:text-white transition">이용 안내</a>
                        <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="hover:text-white transition">전자상거래 유의사항</a>
                    </div>
                </div>
            </div>
            
            <div class="md:text-right text-left flex flex-col md:items-end justify-between">
                <div class="text-left md:text-right space-y-4">
                    <p class="font-bold text-gray-200 text-lg mb-4 font-black">Customer Center</p>
                    <div class="flex flex-col md:items-end gap-3 text-left md:text-right">
                    
                        <a href="http://pf.kakao.com/_AIuxkn" target="_blank" class="bg-[#FEE500] text-gray-900 px-6 py-3 rounded-2xl font-black text-xs flex items-center gap-2 w-fit shadow-lg transition hover:brightness-105">
                            <i class="fas fa-comment"></i> 카카오톡 문의하기
                        </a>
                        <p class="text-sm font-black text-gray-300">평일 09:00 ~ 18:00 (점심 12~13시)</p>
                        <p class="text-xs text-orange-500 font-bold italic text-left md:text-right">인천 연수구 송도동 전용 서비스</p>
                    </div>
                </div>
                <p class="text-[11px] opacity-30 mt-16 font-bold uppercase tracking-[0.4em] text-left md:text-right">© 2026바구니삼촌. All Rights Reserved.</p>
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
    
    # 최신 상품 20개 중 랜덤
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

        <h1 class="hero-title text-3xl md:text-7xl font-black mb-8 leading-tight tracking-tighter text-center">
            우리는 상품을 판매하지 않습니다.<br>
            <span class="text-green-500 uppercase">Premium Service</span>
        </h1>

        <div class="w-12 h-1 bg-white/20 mx-auto mb-8"></div>

        <p class="hero-desc text-gray-400 text-sm md:text-2xl font-bold max-w-2xl mx-auto mb-12 text-center">
            판매가 아닌,
            <span class="text-white underline decoration-green-500 decoration-4 underline-offset-8">
                배송 서비스
            </span>
            입니다.
        </p>

        <div class="flex flex-col md:flex-row justify-center items-center gap-6">
            <a href="#products"
               class="bg-green-600 text-white px-10 py-4 md:px-12 md:py-5 rounded-full font-black shadow-2xl hover:bg-green-700 transition active:scale-95 text-center">
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
                <div class="bg-white rounded-[2rem] p-4 shadow-sm border border-gray-50 flex flex-col gap-3 transition hover:shadow-xl hover:-translate-y-1 text-left">
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
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-gray-100 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] transition-all hover:shadow-2xl text-left">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden text-left">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1.5 md:p-5" onerror="this.src='https://placehold.co/400x400?text={{ p.name }}'">
                        <div class="absolute top-2 left-2 md:top-4 md:left-4"><span class="bg-blue-500 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg uppercase font-black">NEW</span></div>
                    </a>
                    <div class="p-3 md:p-7 flex flex-col flex-1 text-left">
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5 text-left">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-green-600 mb-2 font-medium truncate text-left">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end text-left">
                            <span class="text-[13px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90 text-center"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
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
                <div class="product-card bg-white rounded-3xl md:rounded-[3rem] shadow-sm border border-red-50 overflow-hidden relative flex flex-col w-[calc((100%-24px)/3)] md:w-[calc((100%-48px)/5)] transition-all hover:shadow-2xl text-left">
                    <a href="/product/{{p.id}}" class="relative aspect-square block bg-white overflow-hidden text-left">
                        <img src="{{ p.image_url }}" class="w-full h-full object-contain p-1.5 md:p-5">
                        <div class="absolute bottom-2 left-2 md:bottom-5 md:left-5"><span class="bg-red-600 text-white text-[7px] md:text-[10px] px-1.5 py-0.5 md:px-3 md:py-1 rounded md:rounded-lg font-black animate-pulse uppercase">CLOSING</span></div>
                    </a>
                    <div class="p-3 md:p-7 flex flex-col flex-1 text-left">
                        <p class="countdown-timer text-[8px] md:text-[10px] font-bold text-red-500 mb-1.5 text-left" data-deadline="{{ p.deadline.strftime('%Y-%m-%dT%H:%M:%S') if p.deadline else '' }}"></p>
                        <h3 class="font-black text-gray-800 text-[11px] md:text-base truncate mb-0.5 text-left">{{ p.name }}</h3>
                        <p class="text-[9px] md:text-[11px] text-green-600 mb-2 font-medium truncate text-left">{{ p.description or '' }}</p>
                        <div class="mt-auto flex justify-between items-end text-left">
                            <span class="text-[13px] md:text-2xl text-gray-900 font-black tracking-tighter">{{ "{:,}".format(p.price) }}원</span>
                            <button onclick="addToCart('{{p.id}}')" class="bg-green-600 w-8 h-8 md:w-14 md:h-14 rounded-xl md:rounded-[1.5rem] text-white shadow-xl hover:bg-green-700 flex items-center justify-center transition active:scale-90 text-center"><i class="fas fa-plus text-[10px] md:text-xl"></i></button>
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
    """브랜드 소개 페이지"""
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
                    <p class="text-slate-900 text-2xl md:text-4xl font-black tracking-tighter leading-tight text-left">
                        바구니 삼촌몰은 단순한 판매 플랫폼이 아닌,<br class="hidden md:block"> 
                        물류 전문가가 설계한 <b>신개념 유통·배송 서비스</b>입니다.
                    </p>
                    <p class="opacity-90 text-left">기존 유통 구조에서 분리되어 있던 상품 소싱, 물류 운영, 플랫폼 개발을 하나의 체계로 통합하여, 불필요한 유통 단계를 대폭 축소했습니다.</p>
                </div>
            </header>
            <div class="pb-16 text-center">
                <a href="/" class="group inline-flex items-center gap-6 bg-emerald-600 text-white px-16 py-8 md:px-24 md:py-10 rounded-[32px] font-black text-2xl md:text-4xl shadow-2xl hover:bg-emerald-500 transition-all active:scale-95 duration-300">
                    지금 상품 확인하기
                    <i class="fas fa-arrow-right text-lg md:text-2xl group-hover:translate-x-2 transition-transform"></i>
                </a>
            </div>
        </div>
    </div>
    """
    return render_template_string(HEADER_HTML + content + FOOTER_HTML)

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
                        <span class="bg-black/70 text-white text-[8px] md:text-[11px] px-2.5 py-1.5 rounded-lg font-black backdrop-blur-sm">잔여: {{ p.stock }}</span>
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
    keyword = p.name.split()[0] if p.name else ""
    keyword_recommends = Product.query.filter(Product.name.contains(keyword), Product.id != pid, Product.is_active == True, Product.stock > 0).limit(10).all()
    latest_all = Product.query.filter(Product.is_active == True, Product.id != pid).order_by(Product.id.desc()).limit(10).all()
    product_reviews = Review.query.filter_by(product_id=pid).order_by(Review.created_at.desc()).all()

    content = """
    <div class="max-w-4xl mx-auto px-4 md:px-6 py-16 md:py-24 font-black text-left">
        <div class="grid md:grid-cols-2 gap-10 md:gap-16 mb-24 text-left">
            <div class="relative text-left">
                <img src="{{ p.image_url }}" class="w-full aspect-square object-contain border border-gray-100 rounded-[3rem] bg-white p-8 md:p-12 shadow-sm text-left">
                {% if is_expired or p.stock <= 0 %}<div class="sold-out-badge text-lg">판매마감</div>{% endif %}
            </div>
            <div class="flex flex-col justify-center text-left">
                <h2 class="text-3xl md:text-5xl text-gray-800 mb-6 leading-tight tracking-tighter text-left">{{ p.name }}</h2>
                <p class="text-green-600 text-lg md:text-2xl mb-8 font-bold text-left">{{ p.description or '' }}</p>
                <div class="bg-gray-50 p-8 md:p-12 rounded-[2.5rem] mb-12 border border-gray-100 text-4xl md:text-6xl font-black text-green-600 text-left shadow-inner">
                    {{ "{:,}".format(p.price) }}원
                </div>
                {% if p.stock > 0 and not is_expired %}
                <button onclick="addToCart('{{p.id}}')" class="w-full bg-green-600 text-white py-6 md:py-8 rounded-[2rem] font-black text-xl md:text-2xl shadow-2xl active:scale-95 transition-all text-center">장바구니 담기</button>
                {% else %}
                <button class="w-full bg-gray-300 text-white py-6 md:py-8 rounded-[2rem] font-black text-xl cursor-not-allowed italic shadow-none text-center">판매가 마감되었습니다</button>
                {% endif %}
            </div>
        </div>
    </div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, p=p, is_expired=is_expired, detail_images=detail_images, cat_info=cat_info, latest_all=latest_all, keyword_recommends=keyword_recommends, product_reviews=product_reviews)

# [수정] 회원가입 라우트 기능 보강
@app.route('/register', methods=['GET', 'POST'])
def register():
    """회원가입 라우트 (전자상거래 동의 포함)"""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        pw = request.form.get('password')
        phone = request.form.get('phone')
        addr = request.form.get('address')
        addr_d = request.form.get('address_detail')
        ent_pw = request.form.get('entrance_pw')
        memo = request.form.get('request_memo')
        
        # 송도동 체크
        if "송도동" not in (addr or ""):
            flash("바구니삼촌은 현재 송도동 지역 전용 서비스입니다. 배송지 주소를 확인해주세요."); 
            return redirect('/register')

        if not request.form.get('consent_e_commerce'):
            flash("전자상거래 이용 약관 및 유의사항에 동의해야 합니다."); 
            return redirect('/register')

        if User.query.filter_by(email=email).first(): 
            flash("이미 가입된 이메일입니다."); 
            return redirect('/register')

        new_user = User(
            email=email, 
            password=generate_password_hash(pw), 
            name=name, 
            phone=phone, 
            address=addr, 
            address_detail=addr_d, 
            entrance_pw=ent_pw, 
            request_memo=memo
        )
        db.session.add(new_user)
        db.session.commit()
        flash("회원가입이 완료되었습니다! 로그인해 주세요.");
        return redirect('/login')

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
                <div class="flex gap-2 text-left">
                    <input id="address" name="address" placeholder="인천광역시 연수구 송도동..." class="flex-1 p-5 bg-gray-100 rounded-2xl font-black text-xs md:text-sm text-left" readonly onclick="execDaumPostcode()">
                    <button type="button" onclick="execDaumPostcode()" class="bg-gray-800 text-white px-6 rounded-2xl font-black text-xs text-center">검색</button>
                </div>
                <input id="address_detail" name="address_detail" placeholder="상세주소 (동/호수)" class="w-full p-5 bg-gray-50 rounded-2xl font-black text-sm text-left" required>
                <input name="entrance_pw" placeholder="공동현관 비밀번호 (필수)" class="w-full p-5 bg-red-50 rounded-2xl font-black border border-red-100 text-sm text-left" required>
                <textarea name="request_memo" placeholder="배송 시 요청사항을 남겨주세요" class="w-full p-5 bg-white border border-gray-100 rounded-2xl font-black h-28 text-sm text-left"></textarea>
            </div>
            
            <div class="p-5 bg-gray-50 rounded-2xl border border-gray-100 text-[10px] space-y-3 mt-6 text-left">
                <label class="flex items-start gap-3 cursor-pointer group text-left">
                    <input type="checkbox" name="consent_e_commerce" class="mt-0.5 w-4 h-4 rounded-full border-gray-300 text-green-600 focus:ring-green-500 text-left" required>
                    <span class="group-hover:text-gray-800 transition leading-tight text-left text-left">[필수] <a href="javascript:void(0)" onclick="openUncleModal('e_commerce')" class="underline decoration-green-300 text-left">전자상거래 이용자 유의사항</a> 및 서비스 이용 약관에 동의합니다.</span>
                </label>
            </div>

            <button class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-lg shadow-xl mt-6 hover:bg-green-700 transition active:scale-95 text-center text-center">가입 완료</button>
        </form>
    </div>""" + FOOTER_HTML)

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
            <input name="email" type="email" placeholder="이메일 주소" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-green-100 outline-none text-sm text-left" required>
            <input name="password" type="password" placeholder="비밀번호" class="w-full p-6 bg-gray-50 rounded-3xl font-black focus:ring-4 focus:ring-green-100 outline-none text-sm text-left" required>
            <button class="w-full bg-green-600 text-white py-6 rounded-3xl font-black text-lg md:text-xl shadow-xl hover:bg-green-700 transition text-center">로그인</button>
        </form>
        <div class="text-center mt-10"><a href="/register" class="text-gray-400 text-xs font-black hover:text-green-600 transition text-center">회원가입 하러가기</a></div>
    </div>""" + FOOTER_HTML)

# (이후 장바구니, 주문, 관리자 대시보드 등의 기존 기능 코드 전체 유지...)
@app.route('/cart/add/<int:pid>', methods=['POST'])
@login_required
def add_cart(pid):
    p = Product.query.get_or_404(pid)
    if (p.deadline and p.deadline < datetime.now()) or p.stock <= 0: 
        return jsonify({"success": False, "message": "판매가 마감된 상품입니다."})
    item = Cart.query.filter_by(user_id=current_user.id, product_id=pid).first()
    if item: item.quantity += 1
    else: db.session.add(Cart(user_id=current_user.id, product_id=pid, product_name=p.name, product_category=p.category, price=p.price, tax_type=p.tax_type))
    db.session.commit()
    total_qty = db.session.query(db.func.sum(Cart.quantity)).filter(Cart.user_id == current_user.id).scalar() or 0
    return jsonify({"success": True, "cart_count": total_qty})

@app.route('/mypage')
@login_required
def mypage():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    content = """<div class="max-w-4xl mx-auto py-16 px-4 font-black text-left"><h2 class="text-3xl font-black mb-16 border-l-8 border-green-600 pl-8 text-left italic uppercase">My Center</h2><div class="bg-white p-10 rounded-[3rem] shadow-xl border mb-20 text-left"><p class="text-2xl font-black mb-3 text-left">{{ current_user.name }} 고객님</p><p class="text-gray-400 text-left">{{ current_user.email }}</p></div><h3 class="text-2xl font-black mb-12 text-left italic"><i class="fas fa-truck text-green-600"></i> History</h3><div class="space-y-8 text-left">{% if orders %}{% for o in orders %}<div class="bg-white p-8 rounded-[2.5rem] border text-left"><p class="text-xs text-gray-300 text-left">{{ o.created_at.strftime('%Y-%m-%d %H:%M') }} | {{ o.status }}</p><p class="font-black text-gray-800 text-lg mt-4 text-left">{{ o.product_details }}</p><p class="text-2xl text-green-600 text-right mt-6 italic">{{ "{:,}".format(o.total_price) }}원</p></div>{% endfor %}{% else %}<div class="py-20 text-center text-gray-300 font-black">내역이 없습니다.</div>{% endif %}</div></div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, orders=orders)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not (current_user.is_admin or Category.query.filter_by(manager_email=current_user.email).first()): return redirect('/')
    is_master = current_user.is_admin
    tab = request.args.get('tab', 'products')
    categories = Category.query.order_by(Category.order.asc()).all()
    my_cats = [c.name for c in categories if c.manager_email == current_user.email]
    
    if tab == 'products':
        q = Product.query
        products = [p for p in q.order_by(Product.id.desc()).all() if is_master or p.category in my_cats]
        content = """<div class="max-w-7xl mx-auto py-12 px-6 font-black text-left"><h2 class="text-2xl font-black text-orange-700 italic text-left">Admin Panel</h2><div class="bg-white rounded-[2rem] shadow-sm border mt-10 overflow-hidden text-left"><table class="w-full text-left"><thead class="bg-gray-50 border-b text-left text-xs uppercase text-gray-400"><tr><th class="p-6">상품정보</th><th class="p-6 text-center">재고</th></tr></thead><tbody class="text-left">{% for p in products %}<tr class="border-b text-left"><td class="p-6 text-left"><b class="text-gray-800">{{ p.name }}</b><br><span class="text-green-600 text-xs">{{ p.category }}</span></td><td class="p-6 text-center font-black">{{ p.stock }}</td></tr>{% endfor %}</tbody></table></div></div>"""
    else:
        content = """<div class="max-w-7xl mx-auto py-12 px-6 font-black text-left">주문 집계 탭 (준비중)</div>"""
    return render_template_string(HEADER_HTML + content + FOOTER_HTML, products=products if tab=='products' else [], tab=tab, categories=categories)

<<<<<<< HEAD
        {% elif tab == 'categories' %}
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-10 text-left">
                <div class="bg-white p-8 md:p-12 rounded-[2.5rem] md:rounded-[3.5rem] border border-gray-50 shadow-sm h-fit text-left">
                    <h3 class="text-[11px] md:text-sm text-gray-400 uppercase tracking-widest mb-10 font-black text-left">판매 카테고리 및 사업자 추가</h3>
                    <form action="/admin/category/add" method="POST" class="space-y-5 text-left">
                        <input name="cat_name" placeholder="카테고리명 (예: 산지직송 농산물)" class="border border-gray-100 p-5 rounded-2xl w-full font-black text-sm text-left" required>
                        <textarea name="description" placeholder="배송기한 예)+1일배송 ,마감후 일괄배송" class="border border-gray-100 p-5 rounded-2xl w-full h-24 font-black text-sm text-left"></textarea>
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
                                    <a href="/admin/category/delete/{{c.id}}" class="text-red-200 hover:text-red-500 transition">삭제</a>
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
                    <div class="flex items-end text-left"><button class="w-full bg-orange-600 text-white py-4 rounded-2xl font-black shadow-lg text-xs md:text-sm text-center">집계 및 리스트 업데이트</button></div>
                </form>
            </div>
            
            <h3 class="text-xl md:text-2xl font-black mb-8 italic text-left underline underline-offset-8 decoration-green-300">📊 품목별 배송 수량 합계</h3>
            {% for cat_n, items in summary.items() %}
            <div class="bg-white rounded-[2rem] border border-gray-50 overflow-hidden mb-10 shadow-sm text-left">
                <div class="bg-gray-50 px-8 py-5 border-b border-gray-100 font-black text-green-700 flex justify-between text-left">
                    <span>{{ cat_n }}</span><span class="text-gray-400 font-bold text-right">총계: {{ items.values()|sum }}건</span>
                </div>
                <table class="w-full text-left">
                    <tbody class="text-left">
                        {% for pn, qt in items.items() %}
                        <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition text-left">
                            <td class="p-5 font-bold text-gray-700 text-left text-sm md:text-base">{{ pn }}</td>
                            <td class="p-5 text-right font-black text-blue-600 text-sm md:text-base text-right">{{ qt }}개</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endfor %}
            
            <h3 class="text-xl md:text-2xl font-black mt-24 mb-8 italic text-left underline underline-offset-8 decoration-orange-300 text-left">📑 상세 배송 명단</h3>
            <div class="bg-white rounded-[2.5rem] shadow-xl border border-gray-50 overflow-x-auto text-left">
                <table class="w-full text-[10px] md:text-xs font-black min-w-[1200px] text-left">
                    <thead class="bg-gray-800 text-white text-left">
                        <tr>
                            <th class="p-6 uppercase tracking-widest text-left">Info</th>
                            <th class="p-6 uppercase tracking-widest text-left">Customer</th>
                            <th class="p-6 uppercase tracking-widest text-left">Address & Access</th>
                            <th class="p-6 uppercase tracking-widest text-left">Order Details</th>
                            <th class="p-6 text-right uppercase tracking-widest text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody class="text-left">
                        {% for o in filtered_orders %}
                        <tr class="border-b border-gray-100 hover:bg-green-50/30 transition text-left">
                            <td class="p-6 text-gray-400 font-bold text-left">
                                {{ o.created_at.strftime('%m/%d %H:%M') }}<br><span class="text-[8px] opacity-40 text-left">{{ o.order_id }}</span><br>
                                <span class="{% if o.status == '결제취소' %}text-red-500{% else %}text-green-600{% endif %}">[{{ o.status }}]</span>
                            </td>
                            <td class="p-6 text-left"><b class="text-gray-900 text-sm md:text-base text-left">{{ o.customer_name }}</b><br><span class="text-blue-600 text-left">{{ o.customer_phone }}</span></td>
                            <td class="p-6 text-left">
                                <span class="font-bold text-gray-700 block mb-2 text-left leading-relaxed">{{ o.delivery_address }}</span>
                                <span class="text-orange-500 font-black italic block text-left">📝 {{ o.request_memo or '메모 없음' }}</span>
                            </td>
                            <td class="p-6 text-gray-600 leading-relaxed font-bold text-left text-xs md:text-sm">{{ o.product_details }}</td>
                            <td class="p-6 text-right font-black text-green-600 text-sm md:text-lg text-right">{{ "{:,}".format(o.total_price) }}원</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="flex justify-end mt-12 text-right">
                <a href="/admin/orders/excel" class="bg-gray-800 text-white px-10 py-5 rounded-2xl font-black text-xs md:text-sm shadow-2xl hover:scale-105 transition text-center">Excel Download (전체 내역)</a>
            </div>
        {% endif %}
    </div>""" + FOOTER_HTML, **locals())

# --------------------------------------------------------------------------------
# 7. 엑셀 대량 업로드 (사용자 커스텀 양식 대응)
# --------------------------------------------------------------------------------

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
=======
@app.route('/logout')
def logout(): 
    logout_user(); return redirect('/')
>>>>>>> 5d361e43b0e3aa8cbdda2eb5e3af9701810179f4

def init_db():
    with app.app_context():
        db.create_all()
        # 누락 컬럼 자동 추가
        cols = [("product", "description", "VARCHAR(200)"), ("product", "detail_image_url", "TEXT"), ("user", "request_memo", "VARCHAR(500)"), ("order", "delivery_fee", "INTEGER DEFAULT 0"), ("product", "badge", "VARCHAR(50)"), ("category", "biz_name", "VARCHAR(100)"), ("order", "status", "VARCHAR(20) DEFAULT '결제완료'")]
        for t, c, ct in cols:
            try: db.session.execute(text(f'ALTER TABLE "{t}" ADD COLUMN "{c}" {ct}')); db.session.commit()
            except: db.session.rollback()
        if not User.query.filter_by(email="admin@uncle.com").first():
            db.session.add(User(email="admin@uncle.com", password=generate_password_hash("1234"), name="바구니삼촌", is_admin=True))
        db.session.commit()

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=5000, debug=True)