import os
import sqlite3
import requests
import json
import time
import hmac
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, jsonify, flash, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, UniqueConstraint

# 1. 초기 설정
app = Flask(__name__)
app.secret_key = "delivery_safe_key_v12_summary_secure_path_99"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DB_PATH = os.path.join(BASE_DIR, 'instance', 'direct_trade_mall.db')
DELIVERY_DB_PATH = os.path.join(BASE_DIR, 'delivery.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DELIVERY_DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db_delivery = SQLAlchemy(app)

# 3. 데이터베이스 모델
class AdminUser(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    username = db_delivery.Column(db_delivery.String(50), unique=True)
    password = db_delivery.Column(db_delivery.String(100))

class Driver(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    name = db_delivery.Column(db_delivery.String(50), nullable=False)
    phone = db_delivery.Column(db_delivery.String(20))
    token = db_delivery.Column(db_delivery.String(100), unique=True)
    created_at = db_delivery.Column(db_delivery.DateTime, default=datetime.now)

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
    __table_args__ = (UniqueConstraint('order_id', 'category', name='_order_cat_v12_uc'),)

class DeliveryLog(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    task_id = db_delivery.Column(db_delivery.Integer)
    order_id = db_delivery.Column(db_delivery.String(100))
    status = db_delivery.Column(db_delivery.String(50))
    message = db_delivery.Column(db_delivery.String(500))
    created_at = db_delivery.Column(db_delivery.DateTime, default=datetime.now)

# 4. 유틸리티 함수
def add_log(task_id, order_id, status, message):
    log = DeliveryLog(task_id=task_id, order_id=order_id, status=status, message=message)
    db_delivery.session.add(log)
    db_delivery.session.commit()

def extract_qty(text_data):
    match = re.search(r'\((\d+)\)', text_data)
    return int(match.group(1)) if match else 0

def get_item_summary(tasks):
    summary = {}
    for t in tasks:
        items = re.findall(r'\]\s*(.*?)\((\d+)\)', t.product_details)
        if not items: items = re.findall(r'(.*?)\((\d+)\)', t.product_details)
        for name, qty in items:
            name = name.strip()
            summary[name] = summary.get(name, 0) + int(qty)
    return summary

def get_main_db_categories():
    if not os.path.exists(MAIN_DB_PATH): return []
    try:
        conn = sqlite3.connect(MAIN_DB_PATH); cursor = conn.cursor()
        cursor.execute("SELECT product_details FROM \"order\"")
        rows = cursor.fetchall(); conn.close()
        cats = set()
        for r in rows:
            if r[0]:
                for c in re.findall(r'\[(.*?)\]', r[0]): cats.add(c.strip())
        return sorted(list(cats))
    except: return []

# 5. 관리자 보안 및 메인
@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = AdminUser.query.filter_by(username=request.form['username']).first()
        if user and user.password == request.form['password']:
            session['admin_logged_in'] = True
            session['admin_username'] = user.username
            return redirect('/')
        flash("로그인 정보 오류")
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-900 flex items-center justify-center min-h-screen">
        <div class="w-full max-w-sm bg-slate-800 p-10 rounded-[2.5rem] shadow-2xl text-center border border-slate-700 text-white">
            <h1 class="text-3xl font-black text-green-500 mb-10 italic">B.UNCLE CONTROL</h1>
            <form method="POST" class="space-y-4">
                <input name="username" placeholder="ID" class="w-full p-4 rounded-2xl bg-slate-700 border-none font-bold text-white" required>
                <input type="password" name="password" placeholder="PW" class="w-full p-4 rounded-2xl bg-slate-700 border-none font-bold text-white" required>
                <button class="w-full bg-green-600 text-white py-4 rounded-2xl font-black text-lg shadow-lg hover:bg-green-700 transition">접속</button>
            </form>
        </div>
    </body>
    """)

@app.route('/logout')
def admin_logout():
    session.clear()
    return redirect('/login')

@app.route('/')
def admin_dashboard():
    if not session.get('admin_logged_in'): return redirect('/login')
    
    st_filter = request.args.get('status', 'all')
    cat_filter = request.args.get('category', '전체')
    q = request.args.get('q', '')

    query = DeliveryTask.query
    # [복구] 상태 필터 로직
    if st_filter == '미배정': query = query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None)
    elif st_filter == '배정완료': query = query.filter(DeliveryTask.status == '배정완료')
    elif st_filter != 'all': query = query.filter_by(status=st_filter)
    
    # [복구] 카테고리 필터 로직
    if cat_filter != '전체': query = query.filter_by(category=cat_filter)
    
    # 검색어 필터
    if q: query = query.filter((DeliveryTask.address.contains(q)) | (DeliveryTask.customer_name.contains(q)))
    
    tasks = query.all()
    tasks.sort(key=lambda x: (x.address or "", extract_qty(x.product_details)), reverse=True)
    
    # 숫자 현황판용 전체 데이터
    unassigned_count = DeliveryTask.query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None).count()
    assigned_count = DeliveryTask.query.filter_by(status='배정완료').count()
    picking_count = DeliveryTask.query.filter_by(status='픽업').count()
    complete_today = DeliveryTask.query.filter_by(status='완료').filter(DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).count()

    item_sum = get_item_summary(tasks)
    drivers = Driver.query.all()
    main_cats = get_main_db_categories()
    saved_cats = sorted(list(set([t.category for t in DeliveryTask.query.all() if t.category])))

    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>바구니삼촌 LOGI - 관제</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8fafc; transition: font-size 0.2s; }
        .tab-active { border-bottom: 3px solid #16a34a; color: #16a34a; font-weight: 900; }
        .btn-size { background: #1e293b; color: white; width: 40px; height: 40px; border-radius: 50%; display: flex; items-center; justify-center; font-bold; opacity: 0.8; position: fixed; bottom: 20px; right: 20px; z-index: 1000; }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        </style>
    </head>
    <body class="text-[12px]" id="app-body">
        <div class="flex gap-2 btn-size shadow-xl">
            <button onclick="changeFontSize(-1)">A-</button>
            <button onclick="changeFontSize(1)">A+</button>
        </div>
        <nav class="bg-white border-b h-14 flex items-center justify-between px-4 sticky top-0 z-50">
            <div class="flex items-center gap-6">
                <h1 class="text-lg font-black text-green-600 italic">B.UNCLE</h1>
                <div class="flex gap-4 font-bold text-slate-400 text-[11px]">
                    <a href="/" class="text-green-600 border-b-2 border-green-600">배송통제</a>
                    <a href="/drivers">기사관리</a>
                    <a href="/admin/map">지도</a>
                    {% if session['admin_username'] == 'admin' %}<a href="/admin/users">운영진설정</a>{% endif %}
                </div>
            </div>
            <button onclick="syncNow()" class="bg-green-600 text-white px-3 py-1.5 rounded-lg font-black text-[10px] shadow-md">주문 가져오기</button>
        </nav>

        <main class="p-2 lg:p-4 max-w-[1400px] mx-auto">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
                <div class="bg-white p-4 rounded-2xl shadow-sm border-b-4 border-slate-300 text-center">
                    <p class="text-[9px] font-bold text-slate-400 uppercase">Unassigned</p><p class="text-xl font-black text-slate-700">{{unassigned_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border-b-4 border-blue-500 text-center">
                    <p class="text-[9px] font-bold text-blue-400 uppercase">Assigned</p><p class="text-xl font-black text-blue-600">{{assigned_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border-b-4 border-orange-500 text-center">
                    <p class="text-[9px] font-bold text-orange-400 uppercase">Picking</p><p class="text-xl font-black text-orange-600">{{picking_count}}</p>
                </div>
                <div class="bg-white p-4 rounded-2xl shadow-sm border-b-4 border-green-500 text-center">
                    <p class="text-[9px] font-bold text-green-400 uppercase">Today Done</p><p class="text-xl font-black text-green-600">{{complete_today}}</p>
                </div>
            </div>

            <div class="bg-white p-3 rounded-2xl border border-blue-100 shadow-sm mb-4">
                <h3 class="text-[10px] font-black text-blue-600 mb-2 italic">ITEM SUMMARY</h3>
                <div class="flex flex-wrap gap-2">
                    {% for name, total in item_sum.items() %}
                    <span class="bg-blue-50 text-blue-700 px-2 py-0.5 rounded border border-blue-100 font-bold">{{ name }}: {{ total }}</span>
                    {% endfor %}
                </div>
            </div>

            <div class="bg-white p-3 rounded-2xl border border-slate-200 shadow-sm mb-4">
                <div class="flex flex-wrap justify-between items-center gap-4">
                    <div class="flex gap-4 border-b overflow-x-auto no-scrollbar whitespace-nowrap text-[11px] font-black">
                        <a href="/?status=all" class="{% if current_status=='all' %}tab-active{% endif %} pb-2">전체</a>
                        <a href="/?status=미배정" class="{% if current_status=='미배정' %}tab-active{% endif %} pb-2 text-slate-400">미배정</a>
                        <a href="/?status=배정완료" class="{% if current_status=='배정완료' %}tab-active{% endif %} pb-2 text-blue-500">배정됨</a>
                        <a href="/?status=픽업" class="{% if current_status=='픽업' %}tab-active{% endif %} pb-2 text-orange-500">배송중</a>
                        <a href="/?status=완료" class="{% if current_status=='완료' %}tab-active{% endif %} pb-2 text-green-600">완료</a>
                        <a href="/?status=보류" class="{% if current_status=='보류' %}tab-active{% endif %} pb-2 text-yellow-600">보류/재배정</a>
                    </div>
                    <div class="flex items-center gap-2 flex-wrap">
                        <select onchange="location.href='/?status={{current_status}}&category='+encodeURIComponent(this.value)" class="border rounded-lg px-2 py-1.5 font-bold text-slate-500 bg-slate-50 text-[10px]">
                            <option value="전체">카테고리 전체보기</option>
                            {% for sc in saved_cats %}<option value="{{sc}}" {% if current_cat == sc %}selected{% endif %}>{{sc}}</option>{% endfor %}
                        </select>
                        <div class="bg-blue-50 p-1.5 rounded-xl flex items-center gap-1 border border-blue-100 shadow-inner">
                            <select id="bulk-driver" class="border rounded px-1 py-1 font-black text-blue-600 text-[10px] bg-white">
                                <option value="">기사 배정</option>
                                {% for d in drivers %}<option value="{{d.id}}">{{d.name}}</option>{% endfor %}
                            </select>
                            <button onclick="bulkAction('assign')" class="bg-blue-600 text-white px-2 py-1 rounded font-black text-[10px]">배정</button>
                            <button onclick="bulkAction('hold')" class="bg-yellow-500 text-white px-2 py-1 rounded font-black text-[10px]">보류</button>
                            <button onclick="bulkAction('delete')" class="bg-slate-800 text-white px-2 py-1 rounded font-black text-[10px]">삭제</button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden">
                <table class="w-full text-left">
                    <thead class="bg-slate-50 border-b text-slate-400 font-black text-[10px] uppercase">
                        <tr>
                            <th class="p-3 w-10 text-center"><input type="checkbox" id="check-all" onclick="toggleAll()"></th>
                            <th class="p-3 w-16 text-center">상태</th>
                            <th class="p-3">배송지 정보 및 히스토리</th>
                            <th class="p-3 w-20 text-center">조치</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for t in tasks %}
                        <tr>
                            <td class="p-3 text-center"><input type="checkbox" class="task-check" value="{{t.id}}"></td>
                            <td class="p-3 text-center">
                                <span class="px-2 py-0.5 rounded-full text-[9px] font-black 
                                {% if t.status == '픽업' %}bg-orange-100 text-orange-600
                                {% elif t.status == '완료' %}bg-green-100 text-green-600
                                {% elif t.status == '배정완료' %}bg-blue-100 text-blue-600
                                {% else %}bg-slate-100 text-slate-400{% endif %}">{{ t.status }}</span>
                            </td>
                            <td class="p-3">
                                <div class="font-black text-slate-800 text-[14px] leading-tight mb-1">{{ t.address }}</div>
                                <div class="text-[11px] text-slate-400 font-bold mb-1">{{ t.product_details }} | {{ t.customer_name }}</div>
                                <div class="flex gap-2">
                                    <span class="text-[9px] bg-slate-100 px-2 py-0.5 rounded text-slate-600 font-black"><i class="fas fa-truck mr-1"></i>{{ t.driver_name }}</span>
                                    <button onclick="viewTaskLog('{{t.id}}')" class="text-[9px] text-blue-500 font-black hover:underline">Log 확인</button>
                                </div>
                                <div id="log-view-{{t.id}}" class="hidden mt-2 p-2 bg-slate-50 rounded-lg text-[9px] text-slate-400 border border-dashed"></div>
                            </td>
                            <td class="p-3 text-center">
                                <a href="/cancel/{{t.id}}" class="text-[10px] bg-slate-200 px-2 py-1 rounded font-black hover:bg-slate-300 transition" title="기사 배정 해제">재배정</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </main>
        <script>
            let currentSize = 12;
            function changeFontSize(delta) {
                currentSize += delta;
                if(currentSize < 10) currentSize = 10;
                if(currentSize > 18) currentSize = 18;
                document.getElementById('app-body').style.fontSize = currentSize + 'px';
            }
            async function viewTaskLog(tid) {
                const box = document.getElementById('log-view-'+tid);
                box.classList.toggle('hidden');
                if(!box.classList.contains('hidden')) {
                    const res = await fetch('/api/logs/'+tid);
                    const logs = await res.json();
                    box.innerHTML = logs.map(l => `<div>[${l.time}] ${l.msg}</div>`).join('');
                }
            }
            async function syncNow() {
                const res = await fetch('/sync');
                const data = await res.json();
                if(data.success) { alert(data.synced_count + "건 입고 완료"); location.reload(); }
                else { alert(data.error); }
            }
            function toggleAll() {
                const isChecked = document.getElementById('check-all').checked;
                document.querySelectorAll('.task-check').forEach(i => i.checked = isChecked);
            }
            async function bulkAction(type) {
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("항목 선택 필요");
                let payload = { task_ids: selected, action: type };
                if(type === 'assign') {
                    const dId = document.getElementById('bulk-driver').value;
                    if(!dId) return alert("기사를 선택하세요.");
                    payload.driver_id = dId;
                }
                await fetch('/bulk/execute', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                location.reload();
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, **locals(), current_status=st_filter, current_cat=cat_filter)

# 8. 기사 업무 페이지 (보안 및 PC 편의성 통합)
@app.route('/work/<string:token>')
def driver_work_secure(token):
    driver = Driver.query.filter_by(token=token).first_or_404()
    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(m in user_agent for m in ['mobile', 'android', 'iphone', 'ipad'])
    auth_phone = request.args.get('auth_phone', '')
    
    # [PC 접속 시 인증 생략]
    if is_mobile and auth_phone.replace('-', '') != driver.phone.replace('-', ''):
        return render_template_string("""
        <script src="https://cdn.tailwindcss.com"></script>
        <body class="bg-[#0f172a] text-white flex items-center justify-center min-h-screen p-8 text-center">
            <div class="w-full max-w-sm bg-[#1e293b] p-10 rounded-[2.5rem] shadow-2xl border border-slate-700">
                <h1 class="text-2xl font-black text-green-500 italic mb-8">DRIVER VERIFY</h1>
                <p class="text-slate-400 mb-8 font-bold text-sm">기사님 본인 확인을 위해<br>등록된 전화번호를 입력해주세요.</p>
                <form method="GET" class="space-y-6">
                    <input type="tel" name="auth_phone" placeholder="010-0000-0000" class="w-full p-5 rounded-2xl bg-slate-900 border-none text-center text-xl font-black text-white" required>
                    <button class="w-full bg-green-600 py-5 rounded-2xl font-black text-lg shadow-lg">인증 및 접속</button>
                </form>
            </div>
        </body>
        """)

    view_status = request.args.get('view', 'assigned') 
    query = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id)
    if view_status == 'assigned': tasks = query.filter(DeliveryTask.status.in_(['배정완료', '대기'])).all()
    elif view_status == 'pickup': tasks = query.filter_by(status='픽업').all()
    elif view_status == 'complete': tasks = query.filter_by(status='완료').all()
    else: tasks = query.filter(DeliveryTask.status != '완료').all()

    tasks.sort(key=lambda x: (x.address or "", extract_qty(x.product_details)), reverse=True)
    item_sum = get_item_summary(tasks) if view_status != 'complete' else {}

    html = """
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body { transition: font-size 0.2s; font-family: 'Noto Sans KR', sans-serif; }</style>
    <body class="bg-[#0f172a] p-2 text-white pb-24" id="driver-body">
        <div class="fixed bottom-24 right-4 z-50 flex flex-col gap-3">
            <button onclick="changeFontSize(2)" class="w-12 h-12 bg-green-500 rounded-full font-black shadow-lg">A+</button>
            <button onclick="changeFontSize(-2)" class="w-12 h-12 bg-green-500 rounded-full font-black shadow-lg">A-</button>
        </div>
        <header class="flex justify-between items-center p-3 mb-2">
            <h1 class="text-xl font-black text-green-500 italic">B.UNCLE</h1>
            <button onclick="location.reload()" class="bg-slate-800 p-2 rounded shadow-lg"><i class="fas fa-sync-alt"></i></button>
        </header>

        <div class="flex mb-4 bg-[#1e293b] rounded-t-xl overflow-hidden shadow-xl border-b border-slate-700">
            <a href="?auth_phone={{auth_phone}}&view=assigned" class="flex-1 text-center py-5 font-black {% if view_status=='assigned' %}text-green-500 border-b-4 border-green-500{% else %}text-slate-500{% endif %}">배정</a>
            <a href="?auth_phone={{auth_phone}}&view=pickup" class="flex-1 text-center py-5 font-black {% if view_status=='pickup' %}text-green-500 border-b-4 border-green-500{% else %}text-slate-500{% endif %}">픽업</a>
            <a href="?auth_phone={{auth_phone}}&view=complete" class="flex-1 text-center py-5 font-black {% if view_status=='complete' %}text-green-500 border-b-4 border-green-500{% else %}text-slate-500{% endif %}">완료</a>
        </div>

        <div class="space-y-4 px-2">
            <div class="bg-slate-800 p-3 rounded-xl flex gap-2 mb-4 border border-slate-700 shadow-inner">
                <input type="checkbox" id="check-all" onclick="toggleAll()" class="w-6 h-6 ml-1 bg-slate-900 border-slate-600 rounded">
                <button onclick="bulkActionDriver('hold')" class="bg-yellow-600 text-white px-3 py-2 rounded-lg font-black text-[11px] flex-1 shadow-md">일괄 재배정 요청</button>
                {% if view_status == 'assigned' %}
                <button onclick="bulkPickup()" class="bg-blue-600 text-white px-3 py-2 rounded-lg font-black text-[11px] flex-1 shadow-md">일괄 픽업</button>
                {% endif %}
            </div>
            {% for t in tasks %}
            <div class="bg-[#1e293b] p-5 rounded-2xl shadow-2xl border border-slate-800">
                <div class="flex gap-4 mb-4">
                    <input type="checkbox" class="task-check w-7 h-7 mt-1 rounded bg-slate-900" value="{{t.id}}">
                    <div class="flex-1">
                        <div class="font-black text-white text-[19px] leading-tight mb-2">{{ t.address }}</div>
                        <div class="text-green-400 font-black text-[16px] mb-1 italic">{{ t.product_details }}</div>
                        <div class="text-[13px] text-slate-500 font-bold uppercase">{{ t.customer_name }} | <a href="tel:{{t.phone}}" class="text-blue-400 underline font-black">{{t.phone}}</a></div>
                    </div>
                </div>
                <div class="flex gap-2">
                    {% if t.status in ['배정완료', '대기'] %}
                    <button onclick="secureStatus('{{t.id}}', '픽업')" class="flex-1 bg-orange-600 py-5 rounded-xl font-black text-lg shadow-lg">상차 완료(픽업)</button>
                    {% elif t.status == '픽업' %}
                    <button onclick="openCameraUI('{{t.id}}')" class="flex-1 bg-green-600 py-5 rounded-xl font-black text-lg shadow-lg">배송 완료(사진)</button>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        <div id="camera-layer" class="fixed inset-0 bg-black z-[100] hidden flex flex-col items-center justify-center p-4">
            <video id="video" class="w-full rounded-2xl mb-6 shadow-2xl" autoplay playsinline></video>
            <canvas id="canvas" class="hidden"></canvas>
            <div id="preview-box" class="hidden w-full mb-6 text-center"><img id="photo-preview" class="w-full rounded-2xl border-4 border-green-600 max-h-[70vh] object-contain mx-auto"></div>
            <div class="flex gap-4 w-full">
                <button id="capture-btn" class="flex-1 bg-white text-black py-5 rounded-2xl font-black text-lg shadow-xl">촬영</button>
                <button id="confirm-btn" class="hidden flex-1 bg-green-600 text-white py-5 rounded-2xl font-black text-lg shadow-xl">완료 확정</button>
                <button id="cancel-camera" class="flex-1 bg-slate-800 text-white py-5 rounded-2xl font-bold shadow-lg">취소</button>
            </div>
        </div>

        <script>
            let currentSize = 14;
            function changeFontSize(d) { 
                currentSize += d; 
                if(currentSize < 12) currentSize = 12;
                if(currentSize > 24) currentSize = 24;
                document.getElementById('driver-body').style.fontSize = currentSize+'px'; 
            }
            function toggleAll() { const isChecked = document.getElementById('check-all').checked; document.querySelectorAll('.task-check').forEach(i => i.checked = isChecked); }
            async function secureStatus(tid, status) {
                if(confirm("["+status+"] 처리하시겠습니까?")) {
                    if(confirm("배송 업무 중 오작동 방지: 최종 확인합니다.")) {
                        await fetch('/update_status/'+tid+'/'+status);
                        location.reload();
                    }
                }
            }
            async function bulkActionDriver(action) {
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("항목 선택 필요");
                if(confirm("재배정 요청을 일괄 진행하시겠습니까?")) {
                    await fetch('/bulk/execute', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ task_ids: selected, action: action }) });
                    location.reload();
                }
            }
            async function bulkPickup(){
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("항목 선택 필요");
                if(confirm("일괄 픽업(상차) 하시겠습니까?")) {
                    await fetch('/bulk/pickup', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ task_ids: selected }) });
                    location.reload();
                }
            }
            async function openCameraUI(tid){
                currentTaskId = tid; document.getElementById('camera-layer').classList.remove('hidden');
                try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); document.getElementById('video').srcObject = stream; } 
                catch (e) { alert("카메라 권한 거부됨"); }
            }
            document.getElementById('capture-btn').onclick = () => {
                const v = document.getElementById('video'); const c = document.getElementById('canvas');
                c.width = v.videoWidth; c.height = v.videoHeight; c.getContext('2d').drawImage(v, 0, 0);
                document.getElementById('photo-preview').src = c.toDataURL('image/jpeg', 0.6);
                v.classList.add('hidden'); document.getElementById('preview-box').classList.remove('hidden');
                document.getElementById('capture-btn').classList.add('hidden'); document.getElementById('confirm-btn').classList.remove('hidden');
            };
            document.getElementById('confirm-btn').onclick = async () => {
                const photo = document.getElementById('photo-preview').src;
                const res = await fetch('/complete_action/' + currentTaskId, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ photo: photo }) });
                const data = await res.json();
                if(data.success) {
                    const msg = `[바구니삼촌] 안녕하세요, ${data.customer}님! 주문하신 상품이 배송 완료되었습니다. 🧺`;
                    const smsUrl = `sms:${data.phone}${navigator.userAgent.match(/iPhone/i) ? '&' : '?'}body=${encodeURIComponent(msg)}`;
                    location.href = smsUrl;
                    if(stream) stream.getTracks().forEach(t => t.stop());
                    setTimeout(() => location.reload(), 1500);
                }
            };
            document.getElementById('cancel-camera').onclick = () => { if(stream) stream.getTracks().forEach(t => t.stop()); document.getElementById('camera-layer').classList.add('hidden'); };
        </script>
    </body>
    """
    return render_template_string(html, **locals(), driver_name=driver.name, auth_phone=auth_phone)

# 9. 관리 및 API 라우트
@app.route('/api/logs/<int:tid>')
def get_task_logs(tid):
    logs = DeliveryLog.query.filter_by(task_id=tid).order_by(DeliveryLog.created_at.desc()).all()
    return jsonify([{"time": l.created_at.strftime('%m-%d %H:%M'), "msg": l.message} for l in logs])

@app.route('/sync')
def sync_orders():
    if not os.path.exists(MAIN_DB_PATH): return jsonify({"success": False, "error": "메인 DB 못찾음"})
    try:
        conn = sqlite3.connect(MAIN_DB_PATH); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        cursor.execute("SELECT order_id FROM \"order\" WHERE status = '결제취소'")
        canceled_ids = [r['order_id'] for r in cursor.fetchall()]
        if canceled_ids: DeliveryTask.query.filter(DeliveryTask.order_id.in_(canceled_ids)).update({DeliveryTask.status: '결제취소'}, synchronize_session=False)
        
        cursor.execute("SELECT * FROM \"order\" WHERE status = '배송요청'")
        count = 0
        for row in cursor.fetchall():
            for block in row['product_details'].split(' | '):
                match = re.search(r'\[(.*?)\]', block)
                if match:
                    cat = match.group(1).strip()
                    exists = DeliveryTask.query.filter_by(order_id=row['order_id'], category=cat).first()
                    if not exists:
                        nt = DeliveryTask(order_id=row['order_id'], customer_name=row['customer_name'], phone=row['customer_phone'], address=row['delivery_address'], memo=row['request_memo'], category=cat, product_details=block.strip(), status='대기')
                        db_delivery.session.add(nt); db_delivery.session.commit()
                        add_log(nt.id, nt.order_id, '입고', '배송시스템에 신규 주문 입고됨')
                        count += 1
        db_delivery.session.commit(); conn.close(); return jsonify({"success": True, "synced_count": count})
    except Exception as e: return jsonify({"success": False, "error": str(e)})

@app.route('/bulk/execute', methods=['POST'])
def bulk_execute():
    data = request.json; ids, action = data.get('task_ids', []), data.get('action')
    tasks = DeliveryTask.query.filter(DeliveryTask.id.in_(ids)).all()
    for t in tasks:
        if action == 'assign':
            d = Driver.query.get(data.get('driver_id'))
            if d:
                t.driver_id, t.driver_name, t.status = d.id, d.name, '배정완료'
                add_log(t.id, t.order_id, '배정', f'관리자가 기사[{d.name}] 배정')
        elif action == 'hold':
            t.status = '보류'
            add_log(t.id, t.order_id, '보류', '재배정 요청(보류) 처리')
        elif action == 'delete':
            db_delivery.session.delete(t)
    db_delivery.session.commit(); return jsonify({"success": True})

@app.route('/update_status/<int:tid>/<string:new_status>')
def update_task_status(tid, new_status):
    t = DeliveryTask.query.get(tid)
    if t:
        if t.status == '완료': return "수정불가", 403
        old = t.status; t.status = new_status
        if new_status == '픽업': t.pickup_at = datetime.now()
        add_log(t.id, t.order_id, new_status, f'{old} -> {new_status} 상태 변경')
        db_delivery.session.commit()
    return redirect(request.referrer or '/')

@app.route('/complete_action/<int:tid>', methods=['POST'])
def complete_action(tid):
    t = DeliveryTask.query.get(tid); d = request.json
    if t:
        t.status, t.completed_at, t.photo_data = '완료', datetime.now(), d.get('photo')
        add_log(t.id, t.order_id, '완료', f'기사[{t.driver_name}] 배송 사진 촬영 및 완료 확정')
        db_delivery.session.commit()
        return jsonify({"success": True, "customer": t.customer_name, "phone": t.phone})
    return jsonify({"success": False})

@app.route('/admin/users')
def admin_users_mgmt():
    if not session.get('admin_logged_in') or session.get('admin_username') != 'admin':
        return "<script>alert('최고 관리자 전용'); history.back();</script>"
    users = AdminUser.query.all()
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <div class="max-w-md mx-auto">
            <h2 class="font-black mb-6 text-xl text-red-600">운영 관리자 계정 설정</h2>
            <form action="/admin/users/add" method="POST" class="bg-white p-6 rounded-3xl border mb-6 space-y-4 shadow-xl">
                <input name="username" placeholder="관리자 ID" class="w-full border p-3 rounded-xl font-black" required>
                <input name="password" placeholder="비밀번호" class="w-full border p-3 rounded-xl font-black" required>
                <button class="w-full bg-slate-800 text-white py-4 rounded-xl font-black shadow-lg">계정 생성</button>
            </form>
            {% for u in users %}
            <div class="bg-white p-4 border rounded-2xl mb-2 flex justify-between items-center shadow-sm">
                <b class="text-slate-700">{{u.username}}</b>
                {% if u.username != 'admin' %}<a href="/admin/users/delete/{{u.id}}" class="text-red-500 font-bold text-xs hover:underline">삭제</a>{% endif %}
            </div>
            {% endfor %}
        </div>
    </body>
    """, users=users)

@app.route('/admin/users/add', methods=['POST'])
def add_admin():
    db_delivery.session.add(AdminUser(username=request.form['username'], password=request.form['password']))
    db_delivery.session.commit(); return redirect('/admin/users')

@app.route('/admin/users/delete/<int:uid>')
def delete_admin(uid):
    AdminUser.query.filter_by(id=uid).delete(); db_delivery.session.commit(); return redirect('/admin/users')

@app.route('/drivers')
def driver_mgmt():
    if not session.get('admin_logged_in'): return redirect('/login')
    drivers = Driver.query.all(); base_url = request.host_url.rstrip('/')
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <div class="max-w-md mx-auto">
            <h2 class="font-black mb-6 text-xl text-green-600">배송 기사 보안 관리</h2>
            <form action="/driver/add" method="POST" class="bg-white p-6 rounded-3xl border mb-8 space-y-4 shadow-xl">
                <input name="name" placeholder="기사님 실명" class="w-full border p-3 rounded-xl font-bold" required>
                <input name="phone" placeholder="전화번호" class="w-full border p-3 rounded-xl font-bold" required>
                <button class="w-full bg-green-600 text-white py-4 rounded-xl font-black shadow-lg">신규 기사 생성 및 보안토큰 발급</button>
            </form>
            <div class="space-y-3">
                {% for d in drivers %}
                <div class="bg-white p-5 rounded-3xl border flex justify-between items-center shadow-md">
                    <div><p class="font-black text-slate-700">{{ d.name }}</p><p class="text-[10px] text-slate-400">{{ d.phone }}</p></div>
                    <div class="flex gap-2">
                        <button onclick="copyToken('{{base_url}}/work/{{d.token}}')" class="bg-blue-50 text-blue-600 px-3 py-1.5 rounded-lg font-black text-[10px] border border-blue-200">URL 복사</button>
                        <button onclick="secureDelete({{d.id}})" class="text-red-300 hover:text-red-600 transition p-2"><i class="fas fa-trash-alt"></i></button>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        <script>
            function copyToken(url) {
                const t = document.createElement("input"); document.body.appendChild(t); t.value = url; t.select();
                document.execCommand("copy"); document.body.removeChild(t); alert("보안 접속 URL이 복사되었습니다.");
            }
            function secureDelete(id) {
                if(confirm("1/3 정말 삭제하시겠습니까?"))
                    if(confirm("2/3 업무 데이터가 모두 유실됩니다. 계속하시겠습니까?"))
                        if(confirm("3/3 마지막입니다. 기사를 영구 삭제합니다."))
                            location.href = '/driver/delete/' + id;
            }
        </script>
    </body>
    """, drivers=drivers, base_url=base_url)

@app.route('/driver/add', methods=['POST'])
def add_driver():
    db_delivery.session.add(Driver(name=request.form['name'], phone=request.form['phone'], token=str(uuid.uuid4())[:12]))
    db_delivery.session.commit(); return redirect('/drivers')

@app.route('/driver/delete/<int:did>')
def delete_driver(did):
    Driver.query.filter_by(id=did).delete(); db_delivery.session.commit(); return redirect('/drivers')

@app.route('/cancel/<int:tid>')
def cancel_assignment(tid):
    t = DeliveryTask.query.get(tid)
    if t: 
        t.driver_id, t.driver_name, t.status, t.pickup_at = None, '미배정', '대기', None
        add_log(t.id, t.order_id, '재배정', '관리자가 기사 배정을 취소하고 대기 상태로 초기화함')
    db_delivery.session.commit(); return redirect(request.referrer or '/')

@app.route('/bulk/pickup', methods=['POST'])
def bulk_pickup():
    data = request.json
    for tid in data.get('task_ids'):
        t = DeliveryTask.query.get(tid)
        if t and t.status in ['배정완료', '대기']: t.status, t.pickup_at = '픽업', datetime.now()
    db_delivery.session.commit(); return jsonify({"success": True})

@app.route('/admin/map')
def driver_path_map():
    if not session.get('admin_logged_in'): return redirect('/login')
    # 오늘 배송지 리스트 시각화용 데이터
    tasks = DeliveryTask.query.filter(DeliveryTask.status == '완료', DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).all()
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <nav class="mb-6"><a href="/" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i>돌아가기</a></nav>
        <h2 class="text-xl font-black mb-4">오늘의 배송 완료 경로 지도</h2>
        <div id="map" style="width:100%;height:500px;" class="rounded-[2rem] border shadow-2xl bg-white flex items-center justify-center text-slate-300 font-bold">
            Kakao Maps API 연동 준비 완료. <br> 등록된 주소 좌표값 분석 중...
        </div>
        <div class="mt-6 space-y-2">
            {% for t in tasks %}<div class="text-[11px] bg-white p-3 rounded-2xl border font-black shadow-sm flex items-center gap-3"><span class="w-2 h-2 bg-green-500 rounded-full"></span> 📍 {{t.address}} <span class="text-slate-300 font-bold">({{t.driver_name}})</span></div>{% endfor %}
        </div>
    </body>
    """, tasks=tasks)

def patch_db():
    with app.app_context():
        db_delivery.create_all()
        # 기초 관리자 생성
        if not AdminUser.query.filter_by(username='admin').first():
            db_delivery.session.add(AdminUser(username="admin", password="1234"))
            db_delivery.session.commit()

if __name__ == "__main__":
    patch_db()
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)