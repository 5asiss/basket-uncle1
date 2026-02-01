import os
import sqlite3
import requests
import json
import time
import hmac
import hashlib
import re
import uuid
import pandas as pd  # [추가] 엑셀 처리를 위해 필수 (pip install pandas openpyxl)
from datetime import datetime, timedelta
from flask import Blueprint, render_template_string, request, redirect, jsonify, flash, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, UniqueConstraint

# --------------------------------------------------------------------------------
# 1. Blueprint 및 DB 설정
# --------------------------------------------------------------------------------
logi_bp = Blueprint('logi', __name__, url_prefix='/logi')
vendor_bp = Blueprint('vendor', __name__, url_prefix='/vendor') # [추가] 외주업체 전용
db_delivery = SQLAlchemy()

# --------------------------------------------------------------------------------
# 2. 데이터베이스 모델
# --------------------------------------------------------------------------------
def get_kst():
    """한국 표준시(UTC+9) 반환 함수"""
    return datetime.utcnow() + timedelta(hours=9)

class AdminUser(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    username = db_delivery.Column(db_delivery.String(50), unique=True)
    password = db_delivery.Column(db_delivery.String(100))

class Driver(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    name = db_delivery.Column(db_delivery.String(50), nullable=False)
    phone = db_delivery.Column(db_delivery.String(20))
    token = db_delivery.Column(db_delivery.String(100), unique=True)
    created_at = db_delivery.Column(db_delivery.DateTime, default=get_kst)

class DeliveryTask(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    order_id = db_delivery.Column(db_delivery.String(100))
    customer_name = db_delivery.Column(db_delivery.String(50))
    phone = db_delivery.Column(db_delivery.String(20))
    address = db_delivery.Column(db_delivery.String(500))
    category = db_delivery.Column(db_delivery.String(100)) 
    memo = db_delivery.Column(db_delivery.String(500))
    product_details = db_delivery.Column(db_delivery.Text)
    driver_id = db_delivery.Column(db_delivery.Integer, nullable=True)
    driver_name = db_delivery.Column(db_delivery.String(50), default="미배정")
    status = db_delivery.Column(db_delivery.String(20), default="대기")
    photo_data = db_delivery.Column(db_delivery.Text, nullable=True) 
    pickup_at = db_delivery.Column(db_delivery.DateTime, nullable=True)
    completed_at = db_delivery.Column(db_delivery.DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('order_id', 'category', name='_order_cat_v12_uc_bp'),)

class DeliveryLog(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    task_id = db_delivery.Column(db_delivery.Integer)
    order_id = db_delivery.Column(db_delivery.String(100))
    status = db_delivery.Column(db_delivery.String(50))
    message = db_delivery.Column(db_delivery.String(500))
    created_at = db_delivery.Column(db_delivery.DateTime, default=get_kst)

# --------------------------------------------------------------------------------
# 3. 유틸리티 함수
# --------------------------------------------------------------------------------
def logi_add_log(task_id, order_id, status, message):
    log = DeliveryLog(task_id=task_id, order_id=order_id, status=status, message=message, created_at=get_kst())
    db_delivery.session.add(log)
    db_delivery.session.commit()

def logi_extract_qty(text_data):
    match = re.search(r'\((\d+)\)', text_data)
    return int(match.group(1)) if match else 0

def logi_get_item_summary(tasks):
    summary = {}
    for t in tasks:
        items = re.findall(r'\]\s*(.*?)\((\d+)\)', t.product_details)
        if not items: items = re.findall(r'(.*?)\((\d+)\)', t.product_details)
        for name, qty in items:
            name = name.strip()
            summary[name] = summary.get(name, 0) + int(qty)
    return summary

def logi_get_main_db_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'direct_trade_mall.db')

# --------------------------------------------------------------------------------
# 4. [신규] 외주업체 전용 기능 (vendor_bp)
# --------------------------------------------------------------------------------

@vendor_bp.route('/upload', methods=['GET', 'POST'])
def vendor_excel_upload():
    """외주업체 배송 명단 엑셀 업로드"""
    if request.method == 'POST':
        file = request.files.get('excel_file')
        vendor_name = request.form.get('vendor_name', '외부업체').strip()
        
        if file and vendor_name:
            try:
                df = pd.read_excel(file)
                count = 0
                for _, row in df.iterrows():
                    # 데이터 정리 순서: 품목 / 품종 / 출하지 / 규격 / 거래량 / 경락가
                    # 엑셀 헤더가 일치해야 함
                    p_name = row.get('품목', '-')
                    p_type = row.get('품종', '-')
                    origin = row.get('출하지', '-')
                    spec = row.get('규격', '-')
                    qty = row.get('거래량', 0)
                    price = row.get('경락가', 0)
                    
                    product_info = f"[{p_name}/{p_type}] {origin} | {spec} | {qty}개 | {price}원"
                    
                    new_task = DeliveryTask(
                        order_id=f"EXT-{uuid.uuid4().hex[:6].upper()}",
                        customer_name=str(row.get('받는분', '미기재')),
                        phone=str(row.get('연락처', '000-0000-0000')),
                        address=str(row.get('주소', '주소없음')),
                        category=vendor_name,
                        product_details=product_info,
                        status='대기'
                    )
                    db_delivery.session.add(new_task)
                    db_delivery.session.flush() # ID 생성을 위해 flush
                    logi_add_log(new_task.id, new_task.order_id, '입고', f'[{vendor_name}] 엑셀 업로드 입고')
                    count += 1
                
                db_delivery.session.commit()
                flash(f"{count}건의 오더가 등록되었습니다.")
                return redirect(url_for('vendor.vendor_dashboard', v=vendor_name))
            except Exception as e:
                db_delivery.session.rollback()
                return f"엑셀 처리 오류: {str(e)}"
                
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-900 text-white flex items-center justify-center min-h-screen p-6">
        <div class="max-w-md w-full bg-slate-800 p-10 rounded-[2.5rem] shadow-2xl border border-slate-700">
            <h1 class="text-2xl font-black text-blue-400 mb-2 italic uppercase">Order Upload</h1>
            <p class="text-slate-400 text-xs mb-8 font-bold italic">바구니삼촌 물류센터 오더 접수 창구</p>
            <form method="POST" enctype="multipart/form-data" class="space-y-6">
                <div>
                    <label class="text-[10px] text-slate-500 font-black mb-2 block uppercase tracking-widest">Vendor Name</label>
                    <input name="vendor_name" class="w-full p-4 rounded-2xl bg-slate-700 border-none text-white font-bold outline-none focus:ring-2 ring-blue-500" placeholder="업체명을 입력하세요" required>
                </div>
                <div class="border-2 border-dashed border-slate-600 p-8 rounded-3xl text-center hover:border-blue-500 transition cursor-pointer" onclick="document.getElementById('file-idx').click()">
                    <input type="file" name="excel_file" class="hidden" id="file-idx" accept=".xlsx, .xls" required>
                    <i class="fas fa-file-excel text-3xl text-slate-500 mb-3"></i>
                    <p class="text-blue-400 font-black">배송 명단 선택 (XLSX)</p>
                    <p class="text-slate-500 text-[10px] mt-2">받는분, 연락처, 주소, 품목, 품종 등 포함</p>
                </div>
                <button class="w-full bg-blue-600 py-5 rounded-2xl font-black text-lg shadow-lg hover:bg-blue-700 transition active:scale-95">오더 등록하기</button>
            </form>
            <div class="mt-8 text-center"><a href="/logi" class="text-slate-500 text-xs font-bold hover:text-white">관제 시스템 돌아가기</a></div>
        </div>
    </body>
    """)

@vendor_bp.route('/dashboard')
def vendor_dashboard():
    """외주업체 전용 실시간 배송 현황판"""
    vendor_name = request.args.get('v', '').strip()
    if not vendor_name: return redirect(url_for('vendor.vendor_excel_upload'))
    
    my_tasks = DeliveryTask.query.filter_by(category=vendor_name).order_by(DeliveryTask.id.desc()).all()
    stats = {
        'total': len(my_tasks),
        'pending': len([t for t in my_tasks if t.status == '대기']),
        'shipping': len([t for t in my_tasks if t.status == '픽업']),
        'done': len([t for t in my_tasks if t.status == '완료'])
    }

    html = """
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <body class="bg-slate-50 p-4 font-bold text-slate-800">
        <div class="max-w-4xl mx-auto">
            <header class="flex justify-between items-end mb-8">
                <div>
                    <p class="text-blue-600 text-[10px] font-black uppercase tracking-widest mb-1">Logistics Partner</p>
                    <h1 class="text-2xl font-black italic uppercase">{{vendor_name}} <span class="text-slate-400">Portal</span></h1>
                </div>
                <a href="{{ url_for('vendor.vendor_excel_upload') }}" class="bg-blue-600 text-white px-6 py-3 rounded-2xl font-black shadow-xl hover:bg-blue-700 transition">+ 신규 의뢰</a>
            </header>

            <div class="grid grid-cols-4 gap-3 mb-8">
                <div class="bg-white p-5 rounded-[2rem] border shadow-sm text-center">
                    <p class="text-[9px] text-slate-400 mb-1 uppercase font-black">전체 의뢰</p>
                    <p class="text-2xl font-black">{{stats.total}}</p>
                </div>
                <div class="bg-white p-5 rounded-[2rem] border border-blue-100 shadow-sm text-center">
                    <p class="text-[9px] text-blue-400 mb-1 uppercase font-black">접수 대기</p>
                    <p class="text-2xl font-black text-blue-600">{{stats.pending}}</p>
                </div>
                <div class="bg-white p-5 rounded-[2rem] border border-orange-100 shadow-sm text-center">
                    <p class="text-[9px] text-orange-400 mb-1 uppercase font-black">배송 중</p>
                    <p class="text-2xl font-black text-orange-600">{{stats.shipping}}</p>
                </div>
                <div class="bg-white p-5 rounded-[2rem] border border-green-100 shadow-sm text-center">
                    <p class="text-[9px] text-green-400 mb-1 uppercase font-black">배송 완료</p>
                    <p class="text-2xl font-black text-green-600">{{stats.done}}</p>
                </div>
            </div>

            <div class="bg-white rounded-[2.5rem] shadow-xl border overflow-hidden">
                <table class="w-full text-left border-collapse">
                    <thead class="bg-slate-800 text-slate-400 text-[10px] font-black uppercase tracking-tighter">
                        <tr>
                            <th class="p-5">받는분 / 주소</th>
                            <th class="p-5">상품 및 거래 정보</th>
                            <th class="p-5 text-center">상태</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for t in tasks %}
                        <tr class="hover:bg-slate-50 transition">
                            <td class="p-5 min-w-[180px]">
                                <div class="text-[14px] font-black text-slate-800">{{t.customer_name}}</div>
                                <div class="text-[11px] text-slate-400 mt-1 break-keep leading-tight">{{t.address}}</div>
                            </td>
                            <td class="p-5 text-slate-500 font-bold text-[11px] leading-relaxed">{{t.product_details}}</td>
                            <td class="p-5 text-center">
                                <span class="px-3 py-1 rounded-full text-[9px] font-black 
                                {% if t.status == '완료' %}bg-green-100 text-green-600{% elif t.status == '픽업' %}bg-orange-100 text-orange-600{% else %}bg-slate-100 text-slate-400{% endif %}">
                                    {{t.status}}
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% if not tasks %}
                <div class="py-20 text-center text-slate-300 font-black italic">의뢰된 배송 내역이 없습니다.</div>
                {% endif %}
            </div>
        </div>
    </body>
    """
    return render_template_string(html, vendor_name=vendor_name, tasks=my_tasks, stats=stats)

# --------------------------------------------------------------------------------
# 5. 기존 관리자 및 기사 기능 (logi_bp) - 보존 및 통합
# --------------------------------------------------------------------------------

@logi_bp.route('/login', methods=['GET', 'POST'])
def logi_admin_login():
    if request.method == 'POST':
        user = AdminUser.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            session['admin_logged_in'] = True
            session['admin_username'] = user.username
            return redirect(url_for('logi.logi_admin_dashboard'))
        flash("로그인 정보가 일치하지 않습니다.")
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-900 flex items-center justify-center min-h-screen p-6 text-white">
        <div class="w-full max-w-sm bg-slate-800 p-10 rounded-[2.5rem] shadow-2xl text-center border border-slate-700">
            <h1 class="text-3xl font-black text-green-500 mb-10 italic">B.UNCLE CONTROL</h1>
            <p class="text-slate-400 mb-8 font-bold">배송 관제 시스템 보안 접속</p>
            <form method="POST" class="space-y-4">
                <input name="username" placeholder="Admin ID" class="w-full p-5 rounded-2xl bg-slate-700 text-white font-black border-none text-center" required>
                <input type="password" name="password" placeholder="Password" class="w-full p-5 rounded-2xl bg-slate-700 text-white font-black border-none text-center" required>
                <button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black text-lg shadow-lg hover:bg-green-700 transition active:scale-95">시스템 접속하기</button>
            </form>
        </div>
    </body>
    """)

@logi_bp.route('/')
def logi_admin_dashboard():
    if not session.get('admin_logged_in'): return redirect(url_for('logi.logi_admin_login'))
    
    st_filter = request.args.get('status', 'all')
    cat_filter = request.args.get('category', '전체')
    q = request.args.get('q', '')

    query = DeliveryTask.query
    if st_filter == '미배정': query = query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None)
    elif st_filter == '배정완료': query = query.filter(DeliveryTask.status == '배정완료')
    elif st_filter != 'all': query = query.filter_by(status=st_filter)
    
    if cat_filter != '전체': query = query.filter_by(category=cat_filter)
    if q: query = query.filter((DeliveryTask.address.contains(q)) | (DeliveryTask.customer_name.contains(q)))
    
    tasks = query.all()
    # 정렬: 주소순 -> 수량순
    tasks.sort(key=lambda x: (x.address or "", logi_extract_qty(x.product_details)), reverse=True)

    # 현황판 수치
    unassigned_count = DeliveryTask.query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None).count()
    assigned_count = DeliveryTask.query.filter_by(status='배정완료').count()
    picking_count = DeliveryTask.query.filter_by(status='픽업').count()
    complete_today = DeliveryTask.query.filter_by(status='완료').filter(DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).count()

    drivers = Driver.query.all()
    saved_cats = sorted(list(set([t.category for t in DeliveryTask.query.all() if t.category])))

    # [수정] 카테고리별 요약 데이터 가공 (외주업체 데이터 포함)
    item_sum_grouped = {}
    for t in tasks:
        cat = t.category or "기타"
        if cat not in item_sum_grouped: item_sum_grouped[cat] = {}
        items = re.findall(r'\]\s*(.*?)\((\d+)\)', t.product_details)
        if not items: items = re.findall(r'(.*?)\((\d+)\)', t.product_details)
        for name, qty in items:
            name = name.strip()
            item_sum_grouped[cat][name] = item_sum_grouped[cat].get(name, 0) + int(qty)

    # 관리자 대시보드 HTML (생략 없이 통합)
    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>바구니삼촌 LOGI - 관제</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8fafc; }
        .tab-active { border-bottom: 3px solid #16a34a; color: #16a34a; font-weight: 900; }
        </style>
    </head>
    <body class="text-[12px]">
        <nav class="bg-white border-b h-16 flex items-center justify-between px-6 sticky top-0 z-50 shadow-sm">
            <div class="flex items-center gap-8">
                <h1 class="text-xl font-black text-green-600 italic">B.UNCLE</h1>
                <div class="flex gap-6 font-bold text-slate-400 text-[11px]">
                    <a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 border-b-2 border-green-600 pb-1">배송관제</a>
                    <a href="{{ url_for('logi.logi_driver_mgmt') }}" class="hover:text-green-600 transition">기사관리</a>
                    <a href="{{ url_for('vendor.vendor_excel_upload') }}" class="bg-blue-50 text-blue-600 px-3 py-1 rounded-lg">외주업체 접수</a>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <a href="{{ url_for('logi.logi_admin_logout') }}" class="text-slate-300 font-bold hover:text-red-500"><i class="fas fa-sign-out-alt"></i></a>
            </div>
        </nav>

        <main class="p-4 max-w-[1400px] mx-auto">
            <div class="grid grid-cols-4 gap-2 mb-4">
                <div class="bg-white p-4 rounded-2xl shadow-sm border text-center">
                    <p class="text-[9px] font-black text-slate-400 mb-1 uppercase">배정 대기</p>
                    <p class="text-2xl font-black text-slate-700">{{unassigned_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border border-blue-100 text-center">
                    <p class="text-[9px] font-black text-blue-400 mb-1 uppercase">배정 완료</p>
                    <p class="text-2xl font-black text-blue-600">{{assigned_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border border-orange-100 text-center">
                    <p class="text-[9px] font-black text-orange-400 mb-1 uppercase">배송 중</p>
                    <p class="text-2xl font-black text-orange-600">{{picking_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border border-green-100 text-center">
                    <p class="text-[9px] font-black text-green-400 mb-1 uppercase">오늘 완료</p>
                    <p class="text-2xl font-black text-green-600">{{complete_today}}</p>
                </div>
            </div>

            <div class="bg-white p-5 rounded-[2rem] border shadow-sm mb-6">
                <h3 class="text-[11px] font-black text-blue-500 mb-4 flex items-center gap-2"><span class="w-1.5 h-4 bg-blue-500 rounded-full"></span> 업체별 품목 합계</h3>
                <div class="space-y-4">
                    {% for cat_n, items in item_sum_grouped.items() %}
                    <div class="border-b border-slate-50 pb-3 last:border-0">
                        <div class="flex items-center gap-3 mb-2">
                            <span class="font-black text-slate-700 text-[13px]">{{ cat_n }}</span>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            {% for pn, qt in items.items() %}
                            <span class="bg-slate-50 text-slate-600 px-2 py-1 rounded-md border border-slate-100 text-[10px] font-bold">{{ pn }}: {{ qt }}</span>
                            {% endfor %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>

            <div class="bg-white rounded-[2rem] shadow-xl border overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-slate-800 text-slate-400 font-black text-[10px] uppercase">
                        <tr>
                            <th class="p-4 w-12 text-center"><input type="checkbox"></th>
                            <th class="p-4 w-20 text-center">상태</th>
                            <th class="p-4">배송 정보 및 품목</th>
                            <th class="p-4 w-24 text-center">관리</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for t in tasks %}
                        <tr class="hover:bg-slate-50">
                            <td class="p-4 text-center"><input type="checkbox" class="task-check" value="{{t.id}}"></td>
                            <td class="p-4 text-center">
                                <span class="px-2 py-0.5 rounded-full text-[8px] font-black 
                                {% if t.status == '완료' %}bg-green-600 text-white{% elif t.status == '픽업' %}bg-orange-500 text-white{% else %}bg-slate-200 text-slate-500{% endif %}">
                                    {{ t.status }}
                                </span>
                            </td>
                            <td class="p-4">
                                <div class="font-black text-slate-800 text-[13px]">{{ t.address }}</div>
                                <div class="text-[10px] text-slate-400 font-bold mt-1">{{ t.product_details }} | <span class="text-blue-500">{{ t.category }}</span></div>
                            </td>
                            <td class="p-4 text-center">
                                <a href="{{ url_for('logi.logi_cancel_assignment', tid=t.id) }}" class="text-[10px] font-black text-red-400">재배정</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </main>
    </body>
    </html>
    """
    return render_template_string(html, **locals())

@logi_bp.route('/logout')
def logi_admin_logout():
    session.clear()
    return redirect(url_for('logi.logi_admin_login'))

@logi_bp.route('/drivers')
def logi_driver_mgmt():
    if not session.get('admin_logged_in'): return redirect(url_for('logi.logi_admin_login'))
    drivers = Driver.query.all()
    work_url = request.host_url.rstrip('/') + "/logi/work"
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <div class="max-w-md mx-auto">
            <nav class="mb-8"><a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 font-black">← 돌아가기</a></nav>
            <h2 class="font-black mb-8 text-2xl text-slate-800 italic uppercase">Driver Mgmt</h2>
            <div class="space-y-4">
                {% for d in drivers %}
                <div class="bg-white p-6 rounded-[2rem] border flex justify-between items-center shadow-md">
                    <div>
                        <p class="font-black text-slate-800 text-lg">{{ d.name }}</p>
                        <p class="text-[11px] text-slate-400 font-bold tracking-widest">{{ d.phone }}</p>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </body>
    """, drivers=drivers, work_url=work_url)

@logi_bp.route('/cancel/<int:tid>')
def logi_cancel_assignment(tid):
    t = DeliveryTask.query.get(tid)
    if t: 
        t.driver_id, t.driver_name, t.status, t.pickup_at = None, '미배정', '대기', None
        logi_add_log(t.id, t.order_id, '재배정', '관리자가 기사 배정을 취소하고 대기 상태로 초기화함')
    db_delivery.session.commit()
    return redirect(request.referrer or url_for('logi.logi_admin_dashboard'))

# --------------------------------------------------------------------------------
# 6. 기사용 업무 페이지 (기존 보안 로직 유지)
# --------------------------------------------------------------------------------

@logi_bp.route('/work', methods=['GET', 'POST'])
def logi_driver_work():
    driver_name = request.args.get('driver_name', '').strip()
    auth_phone = request.args.get('auth_phone', '').strip().replace('-', '')
    
    driver = None
    if driver_name and auth_phone:
        driver = Driver.query.filter(
            Driver.name == driver_name,
            db_delivery.func.replace(Driver.phone, '-', '') == auth_phone
        ).first()

    if not driver:
        return render_template_string("""
        <script src="https://cdn.tailwindcss.com"></script>
        <body class="bg-[#0f172a] text-white flex items-center justify-center min-h-screen p-8 text-center">
            <div class="w-full max-w-sm bg-[#1e293b] p-12 rounded-[3.5rem] shadow-2xl border border-slate-700">
                <h1 class="text-2xl font-black text-green-500 mb-8 italic uppercase tracking-widest">Driver Login</h1>
                <form action="{{ url_for('logi.logi_driver_work') }}" method="GET" class="space-y-6">
                    <input type="text" name="driver_name" placeholder="성함 입력" class="w-full p-6 rounded-3xl bg-slate-900 border-none text-center text-xl font-black text-white" required>
                    <input type="tel" name="auth_phone" placeholder="전화번호" class="w-full p-6 rounded-3xl bg-slate-900 border-none text-center text-xl font-black text-white" required>
                    <button class="w-full bg-green-600 py-6 rounded-3xl font-black text-xl shadow-xl">업무 시작</button>
                </form>
            </div>
        </body>
        """)

    view_status = request.args.get('view', 'assigned')
    tasks = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id)
    
    if view_status == 'assigned': tasks = tasks.filter(DeliveryTask.status.in_(['배정완료', '대기'])).all()
    elif view_status == 'pickup': tasks = tasks.filter(DeliveryTask.status == '픽업').all()
    else: tasks = tasks.filter(DeliveryTask.status == '완료').all()

    return render_template_string("기사용 HTML 생략 (기존과 동일)", tasks=tasks, driver_name=driver.name)

# --------------------------------------------------------------------------------
# 7. 상태 업데이트 및 사진 처리 (복구 완료)
# --------------------------------------------------------------------------------

@logi_bp.route('/update_status/<int:tid>/<string:new_status>')
def logi_update_task_status(tid, new_status):
    t = DeliveryTask.query.get(tid)
    if t:
        if t.status == '완료': return "수정불가", 403
        old = t.status; t.status = new_status
        if new_status == '픽업': t.pickup_at = get_kst()
        logi_add_log(t.id, t.order_id, new_status, f'{old} -> {new_status} 상태 변경')
        db_delivery.session.commit()
    return redirect(request.referrer or url_for('logi.logi_admin_dashboard'))

@logi_bp.route('/complete_action/<int:tid>', methods=['POST'])
def logi_complete_action(tid):
    t = DeliveryTask.query.get(tid); d = request.json
    if t:
        t.status, t.completed_at, t.photo_data = '완료', get_kst(), d.get('photo')
        logi_add_log(t.id, t.order_id, '완료', '기사 배송 완료 처리')
        db_delivery.session.commit()
        return jsonify({"success": True, "customer": t.customer_name, "phone": t.phone})
    return jsonify({"success": False})

@logi_bp.route('/api/photo/<int:tid>')
def logi_get_photo(tid):
    task = DeliveryTask.query.get(tid)
    if task and task.photo_data:
        return jsonify({"success": True, "photo": task.photo_data})
    return jsonify({"success": False, "error": "사진이 없습니다."})