import os
import sqlite3
import requests
import json
import time
import hmac
import hashlib
import re
import uuid
import base64
from datetime import datetime, timedelta
from flask import Blueprint, render_template_string, request, redirect, jsonify, flash, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, UniqueConstraint

# [핵심] Blueprint 정의
logi_bp = Blueprint('logi', __name__, url_prefix='/logi')
db_delivery = SQLAlchemy()

PROOF_FOLDER = os.path.join('static', 'proof_photos')
if not os.path.exists(PROOF_FOLDER):
    os.makedirs(PROOF_FOLDER, exist_ok=True)

# --------------------------------------------------------------------------------
# 3. 데이터베이스 모델 (기존 기능 100% 보존)
# --------------------------------------------------------------------------------

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
    __table_args__ = (UniqueConstraint('order_id', 'category', name='_order_cat_v12_uc_bp'),)

# 통합 로그 및 메시지 이력 테이블
# 통합 로그 및 메시지 이력 테이블 (기존 DeliveryLog 역할을 대신함)
class MessageLog(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    task_id = db_delivery.Column(db_delivery.Integer, nullable=True)
    order_id = db_delivery.Column(db_delivery.String(100), nullable=True)
    message_type = db_delivery.Column(db_delivery.String(50)) # 가입, 픽업, 완료, 로그
    phone = db_delivery.Column(db_delivery.String(20), nullable=True)
    status = db_delivery.Column(db_delivery.String(50))
    message = db_delivery.Column(db_delivery.String(500))
    created_at = db_delivery.Column(db_delivery.DateTime, default=datetime.now)
# --------------------------------------------------------------------------------
# 4. 유틸리티 함수 (함수명 겹침 방지 접두어 사용)
# --------------------------------------------------------------------------------

def logi_add_log(task_id, order_id, status, message):
    # 정의되지 않은 DeliveryLog 대신 MessageLog를 사용하여 기록
    log = MessageLog(task_id=task_id, order_id=order_id, status=status, message=message, message_type='시스템로그')
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
    # app.py와 같은 레벨의 instance 폴더 내 DB 경로를 정확히 반환
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'direct_trade_mall.db')

# --------------------------------------------------------------------------------
# 5. 관리자 보안 라우트 (로그인/로그아웃)
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
            <div class="mt-8 pt-8 border-t border-slate-700">
                <a href="/" class="text-slate-500 font-bold hover:text-white transition">쇼핑몰 메인으로 돌아가기</a>
            </div>
        </div>
    </body>
    """)

@logi_bp.route('/logout')
def logi_admin_logout():
    session.clear()
    return redirect(url_for('logi.logi_admin_login'))

# --------------------------------------------------------------------------------
# 6. 관리자 메인 대시보드 (복구된 모든 필터링 및 숫자 현황판)
# --------------------------------------------------------------------------------

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
    tasks.sort(key=lambda x: (x.address or "", logi_extract_qty(x.product_details)), reverse=True)

    # 현황판 수치 계산
    pending_sync_count = 0
    try:
        conn = sqlite3.connect(logi_get_main_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM \"order\" WHERE status = '배송요청'")
        pending_sync_count = cursor.fetchone()[0]
        conn.close()
    except: pass

    unassigned_count = DeliveryTask.query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None).count()
    assigned_count = DeliveryTask.query.filter_by(status='배정완료').count()
    picking_count = DeliveryTask.query.filter_by(status='픽업').count()
    complete_today = DeliveryTask.query.filter_by(status='완료').filter(DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).count()

    item_sum = logi_get_item_summary(tasks)
    drivers = Driver.query.all()
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
        .btn-control { background: #1e293b; color: white; width: 45px; height: 45px; border-radius: 50%; display: flex; items-center; justify-center; font-bold; opacity: 0.8; position: fixed; bottom: 25px; right: 25px; z-index: 1000; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .no-scrollbar::-webkit-scrollbar { display: none; }
        </style>
    </head>
    <body class="text-[12px]" id="app-body">
        <div class="btn-control flex gap-2">
            <button onclick="changeFontSize(-1)" class="w-full h-full text-xs text-center">A-</button>
            <button onclick="changeFontSize(1)" class="w-full h-full text-xs text-center">A+</button>
        </div>
        <nav class="bg-white border-b h-16 flex items-center justify-between px-6 sticky top-0 z-50 shadow-sm">
            <div class="flex items-center gap-8">
                <h1 class="text-xl font-black text-green-600 italic">B.UNCLE</h1>
                <div class="flex gap-6 font-bold text-slate-400 text-[11px]">
                    <a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 border-b-2 border-green-600 pb-1">배송관제</a>
                    <a href="{{ url_for('logi.logi_driver_mgmt') }}" class="hover:text-green-600 transition">기사관리</a>
                    <a href="{{ url_for('logi.logi_driver_path_map') }}" class="hover:text-blue-500 transition">배송지도</a>
                    {% if session['admin_username'] == 'admin' %}<a href="{{ url_for('logi.logi_admin_users_mgmt') }}" class="hover:text-red-500 transition">설정</a>{% endif %}
                </div>
            </div>
            <div class="flex items-center gap-4">
                <button onclick="syncNow()" id="sync-btn" class="bg-red-600 text-white px-5 py-2 rounded-xl font-black text-[11px] shadow-lg hover:bg-red-700 transition ring-2 ring-red-300 ring-offset-2">신규 주문 가져오기</button>
                <a href="{{ url_for('logi.logi_admin_logout') }}" class="text-slate-300 font-bold hover:text-red-500"><i class="fas fa-sign-out-alt"></i></a>
            </div>
        </nav>

        <main class="p-4 max-w-[1400px] mx-auto">
            <div class="grid grid-cols-3 md:grid-cols-5 gap-2 mb-4">
                <div class="bg-white p-3 rounded-2xl shadow-sm border border-red-100 text-center">
                    <p class="text-[9px] font-black text-red-400 mb-0.5 uppercase">신규 주문</p>
                    <p class="text-xl font-black text-red-600" id="sync-count-val">{{pending_sync_count}}</p>
                </div>
                <div class="bg-white p-3 rounded-2xl shadow-sm border border-slate-100 text-center">
                    <p class="text-[9px] font-black text-slate-400 mb-0.5 uppercase">배정 대기</p>
                    <p class="text-xl font-black text-slate-700">{{unassigned_count}}</p>
                </div>
                <div class="bg-white p-3 rounded-2xl shadow-sm border border-blue-100 text-center">
                    <p class="text-[9px] font-black text-blue-400 mb-0.5 uppercase">배정 완료</p>
                    <p class="text-xl font-black text-blue-600">{{assigned_count}}</p>
                </div>
                <div class="bg-white p-3 rounded-2xl shadow-sm border border-orange-100 text-center">
                    <p class="text-[9px] font-black text-orange-400 mb-0.5 uppercase">배송 중</p>
                    <p class="text-xl font-black text-orange-600">{{picking_count}}</p>
                </div>
                <div class="bg-white p-3 rounded-2xl shadow-sm border border-green-100 text-center">
                    <p class="text-[9px] font-black text-green-400 mb-0.5 uppercase">배송 완료</p>
                    <p class="text-xl font-black text-green-600">{{complete_today}}</p>
                </div>
            </div> 

            <div class="bg-white p-5 rounded-[2rem] border border-blue-50 shadow-sm mb-6">
                <h3 class="text-[11px] font-black text-blue-500 mb-4 italic flex items-center gap-2"><span class="w-1.5 h-4 bg-blue-500 rounded-full"></span> 카테고리별 품목 합계 및 전체선택</h3>
                <div class="space-y-4">
                    {% for cat_n, items in item_sum_grouped.items() %}
                    <div class="border-b border-slate-50 pb-3 last:border-0">
                        <div class="flex items-center gap-3 mb-2">
                            <input type="checkbox" class="w-4 h-4 rounded border-slate-300 accent-blue-600" onclick="toggleCategoryAll(this, '{{ cat_n }}')">
                            <span class="font-black text-slate-700 text-[13px]">{{ cat_n }}</span>
                            <span class="text-[10px] text-slate-400 font-bold">합계: {{ items.values()|sum }}개</span>
                        </div>
                        <div class="flex flex-wrap gap-2 pl-7">
                            {% for pn, qt in items.items() %}
                            <span class="bg-slate-50 text-slate-600 px-2 py-1 rounded-md border border-slate-100 text-[10px] font-bold">{{ pn }}: {{ qt }}</span>
                            {% endfor %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>

            <div class="bg-white p-3 rounded-xl border border-slate-100 shadow-sm mb-4 flex flex-wrap justify-between items-center gap-4">
                <div class="flex gap-4 border-b w-full md:w-auto overflow-x-auto no-scrollbar whitespace-nowrap text-[11px] font-black tracking-tighter">
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='all') }}" class="{% if current_status=='all' %}tab-active{% endif %} pb-1.5 px-1">전체</a>
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='미배정') }}" class="{% if current_status=='미배정' %}tab-active{% endif %} pb-1.5 px-1 text-slate-300">미배정</a>
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='배정완료') }}" class="{% if current_status=='배정완료' %}tab-active{% endif %} pb-1.5 px-1 text-blue-500">배정됨</a>
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='픽업') }}" class="{% if current_status=='픽업' %}tab-active{% endif %} pb-1.5 px-1 text-orange-500">배송중</a>
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='완료') }}" class="{% if current_status=='완료' %}tab-active{% endif %} pb-1.5 px-1 text-green-600">완료</a>
                    <a href="{{ url_for('logi.logi_admin_dashboard', status='보류') }}" class="{% if current_status=='보류' %}tab-active{% endif %} pb-1.5 px-1 text-yellow-600">보류</a>
                </div>
                <div class="flex items-center gap-3 flex-wrap">
                    <select onchange="location.href='{{ url_for('logi.logi_admin_dashboard') }}?status={{current_status}}&category='+encodeURIComponent(this.value)" class="border border-slate-100 rounded-xl px-3 py-2 font-black text-slate-400 bg-slate-50 text-[11px] outline-none">
                        <option value="전체">카테고리 전체</option>
                        {% for sc in saved_cats %}<option value="{{sc}}" {% if current_cat == sc %}selected{% endif %}>{{sc}}</option>{% endfor %}
                    </select>
                    <div class="bg-blue-50 p-2 rounded-2xl flex items-center gap-2 border border-blue-100">
                        <select id="bulk-driver-select" class="border rounded-xl px-3 py-1.5 font-black text-blue-600 text-[11px] bg-white outline-none">
                            <option value="">기사 일괄 배정</option>
                            {% for d in drivers %}<option value="{{d.id}}">{{d.name}}</option>{% endfor %}
                        </select>
                        <button onclick="executeBulk('assign')" class="bg-blue-600 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition hover:bg-blue-700">배정</button>
                        <button onclick="executeBulk('hold')" class="bg-yellow-500 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition">보류</button>
                        <button onclick="executeBulk('delete')" class="bg-slate-800 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition">삭제</button>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-[2rem] shadow-xl border border-slate-50 overflow-hidden mb-12">
                <table class="w-full text-left">
                    <thead class="bg-slate-800 border-b text-slate-400 font-black text-[10px] uppercase tracking-widest">
                        <tr>
                            <th class="p-4 w-12 text-center"><input type="checkbox" id="check-all" onclick="toggleAll()" class="w-4 h-4 rounded border-none"></th>
                            <th class="p-4 w-20 text-center">Status</th>
                            <th class="p-4">Address & Product & History</th>
                            <th class="p-4 w-24 text-center">Action</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 bg-white">
                        {% for t in tasks %}
                        <tr class="{% if t.status == '결제취소' %}bg-red-50{% endif %} hover:bg-slate-50 transition">
                            <td class="py-3 px-2 text-center w-8">
                                <input type="checkbox" class="task-check w-4 h-4 rounded border-slate-300 accent-green-600" value="{{t.id}}" data-category="{{ t.category }}">
                            </td>
                            <td class="py-3 px-1 text-center w-16 text-center">
                                <span class="inline-block px-2 py-0.5 rounded-full text-[8px] font-black shadow-sm transform scale-95
                                {% if t.status == '픽업' %}bg-orange-500 text-white
                                {% elif t.status == '완료' %}bg-green-600 text-white
                                {% elif t.status == '배정완료' %}bg-blue-500 text-white
                                {% else %}bg-slate-200 text-slate-500{% endif %}">
                                    {{ t.status }}
                                </span>
                            </td>
                            <td class="py-3 px-2">
                                <div class="font-black text-slate-800 text-[14px] leading-tight mb-0.5 break-keep">{{ t.address }}</div>
                                <div class="text-[10px] text-slate-400 font-bold mb-1 line-clamp-1">
                                    {{ t.product_details }} | <span class="text-orange-400">{{ t.customer_name }}</span>
                                </div>
                                <div class="flex gap-2 items-center">
                                    <span class="text-[9px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-500 font-black border border-slate-200">
                                        <i class="fas fa-truck mr-0.5 text-slate-300"></i>{{ t.driver_name }}
                                    </span>
                                    <button onclick="viewTaskLog('{{t.id}}')" class="text-[9px] text-blue-500 font-black flex items-center gap-0.5">
                                        <i class="fas fa-history"></i> Log보기
                                    </button>
                                </div>
                                <div id="log-view-{{t.id}}" class="hidden mt-2 p-3 bg-slate-50 rounded-xl text-[9px] text-slate-500 border border-dashed border-slate-200 leading-normal"></div>
                            </td>
                         <td class="py-3 px-2 text-right">
    {% if t.status == '완료' %}
        {% if t.photo_data %}
        <button onclick="viewAdminPhoto('{{ t.photo_data }}')" class="inline-block text-[10px] bg-green-600 text-white px-2.5 py-1.5 rounded-lg font-black shadow-sm active:scale-90 transition-transform whitespace-nowrap">
            <i class="fas fa-image mr-1"></i>사진확인
        </button>
        {% else %}
        <span class="text-[10px] text-slate-300 italic">사진없음</span>
        {% endif %}
    {% else %}
        <a href="{{ url_for('logi.logi_cancel_assignment', tid=t.id) }}" 
           class="inline-block text-[10px] bg-slate-800 text-white px-2.5 py-1.5 rounded-lg font-black shadow-sm active:scale-90 transition-transform whitespace-nowrap" 
           onclick="return confirm('배정을 해제하고 대기목록으로 보낼까요?')">
            재배정
        </a>
    {% endif %}
</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </main>
        <div id="admin-photo-modal" class="fixed inset-0 bg-black/80 z-[9999] hidden flex flex-col items-center justify-center p-4" onclick="this.classList.add('hidden')">
    <div class="bg-white p-2 rounded-[2rem] max-w-lg w-full relative overflow-hidden shadow-2xl" onclick="event.stopPropagation()">
        <img id="admin-modal-img" src="" class="w-full h-auto rounded-2xl">
        <button onclick="document.getElementById('admin-photo-modal').classList.add('hidden')" class="absolute top-4 right-4 bg-black/50 text-white w-10 h-10 rounded-full flex items-center justify-center">✕</button>
        <div class="p-6 text-center">
            <p class="text-slate-800 font-black text-lg">배송 완료 증빙 사진</p>
            <p class="text-slate-400 text-xs mt-1">기사님이 직접 촬영하여 등록한 사진입니다.</p>
        </div>
    </div>
</div>

<script>
function viewAdminPhoto(data) {
    const modal = document.getElementById('admin-photo-modal');
    document.getElementById('admin-modal-img').src = data;
    modal.classList.remove('hidden');
}
</script>

        <script>
            let currentSize = 12;
            function changeFontSize(delta) {
                currentSize += delta;
                if(currentSize < 10) currentSize = 10;
                if(currentSize > 20) currentSize = 20;
                document.getElementById('app-body').style.fontSize = currentSize + 'px';
            }

            // [추가] 카테고리별 전체 선택 기능
            function toggleCategoryAll(master, catName) {
                const checkboxes = document.querySelectorAll(`.task-check[data-category="${catName}"]`);
                checkboxes.forEach(cb => { cb.checked = master.checked; });
            }

            function toggleAll() {
                const masterChecked = document.getElementById('check-all').checked;
                const checkboxes = document.querySelectorAll('.task-check');
                checkboxes.forEach(cb => { cb.checked = masterChecked; });
            }

            async function viewTaskLog(tid) {
                const box = document.getElementById('log-view-'+tid);
                box.classList.toggle('hidden');
                if(!box.classList.contains('hidden')) {
                    const res = await fetch('{{ url_for("logi.logi_get_task_logs", tid=0) }}'.replace('0', tid));
                    const logs = await res.json();
                    box.innerHTML = logs.map(l => `<div><span class="text-slate-300 font-black mr-2">${l.time}</span> <span class="text-slate-500 font-bold">${l.msg}</span></div>`).join('');
                }
            }

            async function syncNow() {
                const syncBtn = document.getElementById('sync-btn');
                if(syncBtn.disabled) return;
                if(!confirm("신규 주문 데이터를 동기화하시겠습니까?")) return;
                
                syncBtn.innerText = "데이터 연결 중...";
                syncBtn.disabled = true;
                syncBtn.classList.add('bg-slate-400', 'cursor-not-allowed');

                try {
                    const res = await fetch('{{ url_for("logi.logi_sync") }}');
                    const data = await res.json();
                    if(data.success) { 
                        document.getElementById('sync-count-val').innerText = "0";
                        alert(data.synced_count + "건의 신규 배송건이 입고되었습니다."); 
                        location.reload(); 
                    } else { alert("동기화 실패: " + data.error); location.reload(); }
                } catch(e) { alert("네트워크 오류"); location.reload(); }
            }

            async function executeBulk(actionType) {
                const selectedIds = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if (selectedIds.length === 0) return alert("항목을 먼저 선택해 주세요.");

                let payload = { task_ids: selectedIds, action: actionType };
                if (actionType === 'assign') {
                    const driverSelector = document.getElementById('bulk-driver-select');
                    if (!driverSelector.value) return alert("기사님을 선택해 주세요.");
                    payload.driver_id = driverSelector.value;
                } else {
                    if (!confirm("선택한 항목들을 일괄 처리하시겠습니까?")) return;
                }

                const res = await fetch('{{ url_for("logi.logi_bulk_execute") }}', { 
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'}, 
                    body: JSON.stringify(payload) 
                });
                const result = await res.json();
                if(result.success) { alert("처리가 완료되었습니다."); location.reload(); }
                else { alert("오류 발생: " + result.error); }
            }
        </script>
    </body>
    </html>
    """

    # [핵심] 카테고리별 요약을 위해 데이터 가공 추가
    item_sum_grouped = {}
    for t in tasks:
        cat = t.category or "기타"
        if cat not in item_sum_grouped: item_sum_grouped[cat] = {}
        items = re.findall(r'\]\s*(.*?)\((\d+)\)', t.product_details)
        if not items: items = re.findall(r'(.*?)\((\d+)\)', t.product_details)
        for name, qty in items:
            name = name.strip()
            item_sum_grouped[cat][name] = item_sum_grouped[cat].get(name, 0) + int(qty)

   # 함수 내에서 정의된 모든 변수(tasks, item_sum_grouped 등)가 자동으로 전달됩니다.
    return render_template_string(html, 
                            tasks=tasks,
                            pending_sync_count=pending_sync_count,
                            unassigned_count=unassigned_count,
                            assigned_count=assigned_count,
                            picking_count=picking_count,
                            complete_today=complete_today,
                            drivers=drivers,
                            saved_cats=saved_cats,
                            item_sum_grouped=item_sum_grouped,
                            current_status=st_filter, 
                            current_cat=cat_filter)

# --------------------------------------------------------------------------------
# 7. 기사용 업무 페이지 (보안 강화 및 PC 자동인증 로직 100% 복구)
# --------------------------------------------------------------------------------

# [delivery_system.py 내 logi_driver_work 함수 부분 수정]

@logi_bp.route('/work', methods=['GET', 'POST'])
def logi_driver_work():
    # 1. 입력값 정제
    driver_name = request.args.get('driver_name', '').strip()
    auth_phone = request.args.get('auth_phone', '').strip().replace('-', '')
    
    # 2. 기사 정보 매칭 확인 (이름과 전화번호 동시 만족)
    driver = None
    if driver_name and auth_phone:
        # DB의 전화번호에서도 하이픈을 제거하고 비교하여 검색
        driver = Driver.query.filter(
            Driver.name == driver_name,
            db_delivery.func.replace(Driver.phone, '-', '') == auth_phone
        ).first()

    # 3. 인증 실패 또는 최초 접속 시 로그인 화면 표시
    if not driver:
        return render_template_string("""
        <script src="https://cdn.tailwindcss.com"></script>
        <body class="bg-[#0f172a] text-white flex items-center justify-center min-h-screen p-8 text-center">
            <div class="w-full max-w-sm bg-[#1e293b] p-12 rounded-[3.5rem] shadow-2xl border border-slate-700">
                <h1 class="text-2xl font-black text-green-500 mb-8 italic uppercase tracking-widest">Driver Login</h1>
                <p class="text-slate-400 mb-10 font-bold leading-relaxed text-sm">등록된 성함과 전화번호를<br>입력하여 접속하세요.</p>
                <form action="{{ url_for('logi.logi_driver_work') }}" method="GET" class="space-y-6">
                    <input type="text" name="driver_name" placeholder="성함 입력" class="w-full p-6 rounded-3xl bg-slate-900 border-none text-center text-xl font-black text-white outline-none" required>
                    <input type="tel" name="auth_phone" placeholder="전화번호 (01000000000)" class="w-full p-6 rounded-3xl bg-slate-900 border-none text-center text-xl font-black text-white outline-none" required>
                    <button class="w-full bg-green-600 py-6 rounded-3xl font-black text-xl shadow-xl active:scale-95 transition-all">업무 시작하기</button>
                </form>
            </div>
        </body>
        """)

    # --- 이후 배송 목록 출력 로직은 기존과 동일함 ---

    # 1. 탭 상태 및 날짜 설정
    view_status = request.args.get('view', 'assigned')
    selected_days = int(request.args.get('days', 1)) # 기본값 오늘(1일)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_date = datetime.now() - timedelta(days=selected_days)

    # 2. [핵심] 상단 현황판용 숫자 계산 (탭 이동과 상관없이 항상 전체 통계 유지)
    # 배정됨: 대기 또는 배정완료 상태인 전체 건수
    assigned_count = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status.in_(['배정완료', '대기'])).count()
    # 진행중: 현재 상차(픽업)한 건수
    picking_count = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status == '픽업').count()
    # 오늘완료: 오늘 00시 이후 완료된 건수
    complete_today = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status == '완료', DeliveryTask.completed_at >= today_start).count()

    # 3. 실제 리스트에 보여줄 데이터 필터링
    base_query = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id)
    
    # 1. 현황판용 수치 계산 (탭 클릭과 관계없이 항상 전체 요약 유지)
    assigned_count = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status.in_(['배정완료', '대기'])).count()
    picking_count = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status == '픽업').count()
    complete_today = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id, DeliveryTask.status == '완료', DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).count()

    # 2. 완료 내역 조회용 기간 설정 (기본 1일)
    selected_days = int(request.args.get('days', 1))
    since_date = datetime.now().replace(hour=0, minute=0, second=0) - timedelta(days=selected_days-1)

    # 3. 탭별 데이터 필터링
    base_query = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id)
    if view_status == 'assigned': 
        tasks = base_query.filter(DeliveryTask.status.in_(['배정완료', '대기'])).all()
    elif view_status == 'pickup': 
        tasks = base_query.filter(DeliveryTask.status == '픽업').all()
    elif view_status == 'complete':
        # 기사가 직접 지정한 시작일과 종료일 가져오기 (기본값은 오늘)
        today_str = datetime.now().strftime('%Y-%m-%d')
        start_date_str = request.args.get('start_date', today_str)
        end_date_str = request.args.get('end_date', today_str)
        
        # 조회 범위 설정 (시작일 00:00:00 ~ 종료일 23:59:59)
        start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        
        tasks = base_query.filter(
            DeliveryTask.status == '완료', 
            DeliveryTask.completed_at >= start_dt,
            DeliveryTask.completed_at <= end_dt
        ).all()
        
        # 기간 내 날짜별 합계 계산
        date_summary = {}
        for t in tasks:
            d_str = t.completed_at.strftime('%Y-%m-%d')
            date_summary[d_str] = date_summary.get(d_str, 0) + 1
        sorted_date_summary = sorted(date_summary.items(), reverse=True)
    # 4. [신규] 배송완료 탭을 위한 날짜별 합계 계산
    date_summary = {}
    if view_status == 'complete':
        for t in tasks:
            d_str = t.completed_at.strftime('%Y-%m-%d')
            date_summary[d_str] = date_summary.get(d_str, 0) + 1
    
    sorted_date_summary = sorted(date_summary.items(), reverse=True)
    tasks.sort(key=lambda x: (x.address or "", logi_extract_qty(x.product_details)), reverse=True)
    item_sum = logi_get_item_summary(tasks) if view_status != 'complete' else {}

   # [delivery_system.py 내 logi_driver_work 함수 안의 html 변수 부분 수정]

    html = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>B.Uncle Logi - {{ driver_name }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;700;900&display=swap');
    
    body { 
        font-family: 'Pretendard', sans-serif; 
        background-color: #0f172a; color: #f8fafc; 
        letter-spacing: -0.03em; word-break: keep-all;
    }

    /* 기사님 가독성을 위한 큼직한 카드 스타일 */
    .task-card {
        background: #1e293b; border-radius: 1.5rem;
        padding: 1.5rem; border: 1px solid #334155;
        margin-bottom: 1.25rem; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
    }

    /* 주소: 가독성을 위해 크기 유지 및 줄간격 확보 */
    .address-highlight { 
        color: #ffffff; 
        font-weight: 900; 
        line-height: 1.3; 
        font-size: 24px; 
        margin-bottom: 8px;
    }

    /* [수정 핵심] 품목 배지: 두 줄이 되어도 글자가 겹치지 않도록 line-height와 padding 조정 */
.product-badge { 
    /* 1. 줄바꿈 시 배경 겹침 방지의 핵심 */
    display: inline-block;      
    line-height: 1.6;           /* 줄 간격을 글자 크기의 1.6배로 벌림 */
    
    /* 2. 디자인 및 색상 */
    background: #064e3b; 
    color: #34d399; 
    border: 1px solid #065f46;
    border-radius: 8px; 
    
    /* 3. 여백 조절 (글자가 배경 끝에 붙지 않게 함) */
    padding: 2px 10px;          /* 위아래(2px), 좌우(10px) */
    margin-top: 4px;            /* 배지 위쪽 간격 */
    margin-bottom: 4px;         /* 배지 아래쪽 간격 */
    
    /* 4. 가독성 */
    font-weight: 800; 
    font-size: 15px; 
    word-break: keep-all;       /* 단어 중간에서 끊기지 않게 함 */
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);

    /* 하단 조작바 */
    .bottom-ctrl { 
        position: fixed; 
        bottom: 20px; 
        left: 50%; 
        transform: translateX(-50%); 
        width: 92%; 
        z-index: 1000; 
    }

    .no-scrollbar::-webkit-scrollbar { display: none; }
</style>
</head>
<body class="pb-32 px-3">
    <div class="grid grid-cols-3 bg-slate-900 text-white rounded-b-[2.5rem] shadow-2xl mb-6 border-b border-slate-800 py-6 sticky top-0 z-50 backdrop-blur-md bg-opacity-95">
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=assigned" class="text-center border-r border-slate-800">
            <div class="text-[10px] text-slate-500 font-black uppercase mb-1">배정대기</div>
            <div class="text-2xl font-black {% if view_status=='assigned' %}text-blue-400{% else %}text-slate-600{% endif %}">{{ assigned_count }}</div>
        </a>
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=pickup" class="text-center border-r border-slate-800">
            <div class="text-[10px] text-slate-500 font-black uppercase mb-1">배송중</div>
            <div class="text-2xl font-black {% if view_status=='pickup' %}text-orange-400{% else %}text-slate-600{% endif %}">{{ picking_count }}</div>
        </a>
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=complete" class="text-center">
            <div class="text-[10px] text-slate-500 font-black uppercase mb-1">오늘완료</div>
            <div class="text-2xl font-black {% if view_status=='complete' %}text-green-400{% else %}text-slate-600{% endif %}">{{ complete_today }}</div>
        </a>
    </div>

    {% if view_status == 'complete' %}
    <div class="bg-slate-800/50 p-5 rounded-3xl mb-6 border border-slate-700">
        {% if view_status == 'complete' %}
<div class="bg-slate-800/50 p-5 rounded-3xl mb-6 border border-slate-700 mx-2">
    <p class="text-slate-400 text-[10px] font-black mb-3 uppercase tracking-widest text-left">배송 실적 직접 조회</p>
    
    <form action="" method="GET" class="space-y-3">
        <input type="hidden" name="driver_name" value="{{ driver_name }}">
        <input type="hidden" name="auth_phone" value="{{ auth_phone }}">
        <input type="hidden" name="view" value="complete">
        
        <div class="grid grid-cols-2 gap-2">
            <div>
                <span class="text-[9px] text-slate-500 ml-1">시작일</span>
                <input type="date" name="start_date" value="{{ start_date_str }}" class="w-full bg-slate-900 border border-slate-700 p-3 rounded-xl text-white font-bold text-sm outline-none focus:border-green-500">
            </div>
            <div>
                <span class="text-[9px] text-slate-500 ml-1">종료일</span>
                <input type="date" name="end_date" value="{{ end_date_str }}" class="w-full bg-slate-900 border border-slate-700 p-3 rounded-xl text-white font-bold text-sm outline-none focus:border-green-500">
            </div>
        </div>
        <button type="submit" class="w-full bg-green-600 text-white py-4 rounded-2xl font-black text-sm shadow-xl active:scale-95 transition-transform">실적 조회하기</button>
    </form>

    <div class="mt-6 pt-5 border-t border-slate-700/50">
        <div class="flex justify-between items-end mb-4">
            <span class="text-slate-400 font-bold text-xs">조회 기간 총 합계</span>
            <span class="text-2xl font-black text-green-400">{{ tasks|length }}건</span>
        </div>
        
        <div class="space-y-2">
            {% for date, count in sorted_date_summary %}
            <div class="flex justify-between items-center bg-slate-900/40 p-3 rounded-xl border border-slate-800/50">
                <span class="text-slate-400 font-bold text-xs">{{ date }}</span>
                <span class="text-white font-black text-sm">{{ count }}건</span>
            </div>
            {% endfor %}
        </div>
    </div>
</div>
{% endif %}
        <div class="space-y-2">
            {% for date, count in sorted_date_summary %}
            <div class="flex justify-between items-center bg-slate-900/50 p-4 rounded-xl border border-slate-800">
                <span class="text-slate-400 font-bold text-sm">{{ date }}</span>
                <span class="text-green-400 font-black">{{ count }}건 완료</span>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <div class="space-y-4">
        {% if view_status != 'complete' %}
        <div class="flex items-center justify-between px-2 mb-2">
            <label class="flex items-center gap-3 font-black text-slate-500 text-base cursor-pointer">
                <input type="checkbox" id="driver-check-all" onclick="toggleDriverAll(this)" class="w-7 h-7 rounded-lg border-slate-700 bg-slate-800 accent-green-500 shadow-sm"> 전체선택
            </label>
            {% if view_status == 'assigned' %}
            <button onclick="bulkPickup()" class="bg-blue-600 text-white px-5 py-2.5 rounded-xl font-black text-sm shadow-xl active:scale-95 transition-transform">일괄 상차 완료</button>
            {% endif %}
        </div>
        {% endif %}

        {% for t in tasks %}
        <div class="task-card border-l-[10px] {% if view_status=='complete' %}border-green-900{% elif view_status=='pickup' %}border-orange-600{% else %}border-blue-600{% endif %}">
            {% if view_status == 'complete' %}
                <div class="flex justify-between items-center">
                    <div class="min-w-0">
                        <div class="text-xl font-black text-white truncate">{{ t.address.split(' ')[2:]|join(' ') }}</div>
                        <div class="text-[11px] text-slate-500 mt-1 font-bold">{{ t.customer_name }}님 | {{ t.category }}</div>
                    </div>
                    <div class="text-right ml-4">
                        <div class="text-lg font-black text-green-500">{{ t.completed_at.strftime('%H:%M') }}</div>
                        <div class="text-[10px] text-slate-600 font-bold">배송완료</div>
                    </div>
                </div>
            {% else %}
                <div class="flex items-start gap-4">
                    <input type="checkbox" class="task-check w-8 h-8 rounded-lg bg-slate-900 border-slate-700 accent-green-500 mt-1 shadow-inner" value="{{t.id}}">
                    <div class="flex-1 min-w-0">
                        <div class="address-highlight mb-3">{{ t.address }}</div>
                        <div class="mb-4"><span class="product-badge italic">{{ t.product_details }}</span></div>
                        
                        <div class="grid grid-cols-2 gap-3 text-sm font-bold text-slate-400 border-t border-slate-700/50 pt-4">
                            <div class="flex items-center gap-2"><i class="fas fa-user text-slate-600"></i>{{ t.customer_name }}</div>
                            <a href="tel:{{t.phone}}" class="flex items-center gap-2 text-blue-400"><i class="fas fa-phone-alt"></i> 전화하기</a>
                        </div>
                        
                        {% if t.memo %}
                        <div class="mt-3 text-[13px] bg-slate-900/50 p-3 rounded-xl text-orange-300 font-medium border border-orange-900/20">
                            <i class="fas fa-comment-dots mr-1"></i> {{t.memo}}
                        </div>
                        {% endif %}

                        <div class="mt-5">
                            {% if t.status in ['배정완료', '대기'] %}
                                <button onclick="secureStatus('{{t.id}}', '픽업')" class="w-full bg-orange-600 text-white py-4 rounded-2xl font-black text-lg shadow-xl active:scale-95 transition-all">상차 완료</button>
                            {% elif t.status == '픽업' %}
                                <button onclick="openCameraUI('{{t.id}}')" class="w-full bg-green-600 text-white py-4 rounded-2xl font-black text-lg shadow-xl active:scale-95 transition-all">배송 완료 처리</button>
                            {% endif %}
                        </div>
                    </div>
                </div>
            {% endif %}
        </div>
        {% endfor %}

        {% if not tasks %}
        <div class="py-32 text-center text-slate-600 font-black italic">해당 내역이 없습니다.</div>
        {% endif %}
    </div>

    <div class="bottom-ctrl">
        <div class="bg-slate-800/90 backdrop-blur-xl p-3 rounded-[2rem] border border-slate-700 flex justify-around shadow-2xl">
            <button onclick="location.reload()" class="flex flex-col items-center gap-1 px-4 py-2">
                <i class="fas fa-sync-alt text-slate-400 text-lg"></i>
                <span class="text-[10px] font-bold text-slate-400">새로고침</span>
            </button>
            <div class="flex gap-2">
                <button onclick="changeFontSize(2)" class="bg-slate-700 text-white w-12 h-10 rounded-xl font-black">A+</button>
                <button onclick="changeFontSize(-2)" class="bg-slate-700 text-white w-12 h-10 rounded-xl font-black">A-</button>
            </div>
        </div>
    </div>

<input type="file" id="emergency-file-input" accept="image/*" capture="environment" class="hidden">

<div id="camera-layer" class="fixed inset-0 bg-black z-[5000] hidden flex flex-col items-center justify-center p-4">
    ...
</div>
        <div class="relative w-full max-w-md aspect-[3/4] overflow-hidden rounded-[2.5rem] shadow-2xl bg-slate-900 mb-8 border-4 border-slate-800">
            <video id="video" class="w-full h-full object-cover" autoplay playsinline></video>
            <img id="photo-preview" class="hidden w-full h-full object-cover">
            <canvas id="canvas" class="hidden"></canvas>
        </div>
        <div class="flex gap-4 w-full max-w-md px-2">
            <button id="capture-btn" type="button" class="flex-1 bg-white text-slate-900 py-6 rounded-2xl font-black text-xl shadow-2xl active:scale-95 transition-transform"><i class="fas fa-camera mr-2"></i>사진 촬영</button>
            <button id="confirm-btn" type="button" class="hidden flex-1 bg-green-600 text-white py-6 rounded-2xl font-black text-xl shadow-2xl active:scale-95 transition-transform"><i class="fas fa-check-circle mr-2"></i>배송 완료 확정</button>
            <button id="cancel-camera" type="button" class="w-24 bg-slate-800 text-slate-400 py-6 rounded-2xl font-bold">취소</button>
        </div>
    </div>

    <script>
        let currentSize = 15;
        let currentTaskId = null; 
        let stream = null;

       let currentBaseSize = 15; 

function changeFontSize(delta) {
    const body = document.getElementById('driver-body');
    if (!body) return;

    // 1. 크기 계산 (최소 12px ~ 최대 35px 제한)
    currentBaseSize += delta;
    if (currentBaseSize < 12) currentBaseSize = 12;
    if (currentBaseSize > 35) currentBaseSize = 35;

    // 2. 전체 본문 크기 변경
    body.style.fontSize = currentBaseSize + 'px';

    // 3. [추가] 주소나 품목 텍스트처럼 중요한 부분은 비례해서 더 커지도록 처리
    document.querySelectorAll('.address-highlight').forEach(el => {
        el.style.fontSize = (currentBaseSize + 7) + 'px';
    });
    document.querySelectorAll('.product-badge').forEach(el => {
        el.style.fontSize = (currentBaseSize + 1) + 'px';
    });
}

        function toggleDriverAll(master) {
            document.querySelectorAll('.task-check').forEach(cb => cb.checked = master.checked);
        }

        async function bulkPickup() {
            const ids = Array.from(document.querySelectorAll('.task-check:checked')).map(cb => cb.value);
            if(ids.length === 0) return alert("항목을 선택해주세요.");
            if(!confirm(ids.length + "건을 일괄 상차 처리할까요?")) return;
            const res = await fetch('{{ url_for("logi.logi_bulk_pickup") }}', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ task_ids: ids })
            });
            const result = await res.json();
            if(result.success) location.reload();
        }

        async function secureStatus(tid, status) {
            if(confirm("["+status+"] 처리를 진행할까요?")) {
                await fetch('{{ url_for("logi.logi_update_task_status", tid=0, new_status="X") }}'.replace('0', tid).replace('X', status));
                location.reload();
            }
        }

        // 통합된 배송 완료 처리 함수
async function openCameraUI(tid) {
    currentTaskId = tid;
    
    try {
        // 1. 카메라 스트림 시도 (후면 카메라 우선)
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: { ideal: "environment" } } 
        });

        const video = document.getElementById('video');
        video.srcObject = stream;
        
        // 카메라 레이어 표시
        document.getElementById('camera-layer').classList.remove('hidden');
        video.classList.remove('hidden');
        document.getElementById('photo-preview').classList.add('hidden');
        document.getElementById('capture-btn').classList.remove('hidden');
        document.getElementById('confirm-btn').classList.add('hidden');
        
    } catch (e) {
        console.error("카메라 실행 실패:", e);
        
        // 2. 카메라 실패 시 갤러리/파일 선택창 실행 (비상 로직)
        if (confirm("카메라를 켤 수 없습니다. 갤러리에서 사진을 선택하여 배송 완료하시겠습니까?")) {
            const fileInput = document.getElementById('emergency-file-input');
            if(!fileInput) {
                alert("시스템 오류: emergency-file-input 요소가 없습니다.");
                return;
            }
            fileInput.click(); 

            fileInput.onchange = async (event) => {
                const file = event.target.files[0];
                if (file) {
                    const reader = new FileReader();
                    reader.onload = async (e) => {
                        const base64Photo = e.target.result;
                        // 선택 시 즉시 업로드 함수 호출
                        await uploadPhotoDirectly(currentTaskId, base64Photo);
                    };
                    reader.readAsDataURL(file);
                }
            };
        }
    }
}

// 갤러리 사진 전용 업로드 함수
async function uploadPhotoDirectly(tid, photoData) {
    const res = await fetch('{{ url_for("logi.logi_complete_action", tid=0) }}'.replace('0', tid), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo: photoData })
    });
    const data = await res.json();
    if (data.success) {
        alert("배송 완료 처리되었습니다.");
        location.reload();
    } else {
        alert("업로드 실패: " + data.error);
    }
}
    
    try {
        // 1. 카메라 스트림 시도
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: { ideal: "environment" } } 
        });
        
        document.getElementById('video').srcObject = stream;
        document.getElementById('camera-layer').classList.remove('hidden');
        
    } catch (e) {
        console.error("카메라 권한 없음:", e);
        
        // 2. 카메라 실패 시 비상용 갤러리/파일 선택창 실행
        if (confirm("카메라 권한이 거부되었거나 지원하지 않는 브라우저입니다.\n갤러리에서 직접 사진을 선택하시겠습니까?")) {
            const fileInput = document.getElementById('emergency-file-input');
            fileInput.click(); // 파일 선택창 강제 실행

            // 파일 선택 시 바로 배송 완료 처리로 연결
            fileInput.onchange = async (event) => {
                const file = event.target.files[0];
                if (file) {
                    const reader = new FileReader();
                    reader.onload = async (e) => {
                        const base64Photo = e.target.result;
                        // 선택한 사진으로 바로 완료 API 호출
                        await uploadPhotoDirectly(currentTaskId, base64Photo);
                    };
                    reader.readAsDataURL(file);
                }
            };
        }
    }
}

// 갤러리 사진 선택 시 바로 서버로 쏘는 함수
async function uploadPhotoDirectly(tid, photoData) {
    const res = await fetch('{{ url_for("logi.logi_complete_action", tid=0) }}'.replace('0', tid), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo: photoData })
    });
    const data = await res.json();
    if (data.success) {
        alert("갤러리 사진으로 배송 완료 처리되었습니다.");
        location.reload();
    } else {
        alert("업로드 실패: " + data.error);
    }
}
    } catch (e) { 
        console.error("카메라 에러:", e);
        alert("카메라 권한이 거부되었습니다.\n\n[해결방법]\n1. 브라우저 주소창 왼쪽/오른쪽의 설정 아이콘 클릭\n2. 카메라 권한을 '허용'으로 변경\n3. 페이지 새로고침 후 다시 시도해주세요.");
    }
}

// 사진 촬영 버튼 클릭 시
document.getElementById('capture-btn').onclick = () => {
    const v = document.getElementById('video');
    const c = document.getElementById('canvas');
    const p = document.getElementById('photo-preview');

    // 캔버스 크기 최적화 (가로 800px)
    c.width = 800;
    c.height = v.videoHeight * (800 / v.videoWidth);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    
    // 미리보기 이미지 생성
    p.src = c.toDataURL('image/jpeg', 0.7);

    // 카메라 즉시 종료하여 자원 해제
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }

    // UI 전환: 비디오 숨기고 사진 표시
    v.style.display = 'none'; 
    v.classList.add('hidden');
    p.classList.remove('hidden');
    
    document.getElementById('capture-btn').classList.add('hidden');
    document.getElementById('confirm-btn').classList.remove('hidden');
};
// 확정 버튼 클릭 시 서버 전송
// 통합 로직: 서버 저장 + 기사폰 문자 발송 연동
document.getElementById('confirm-btn').onclick = async () => {
    const confirmBtn = document.getElementById('confirm-btn');
    if(confirmBtn.disabled) return;
    confirmBtn.disabled = true; // 중복 클릭 방지
    confirmBtn.innerText = "전송 중...";

    const photoData = document.getElementById('photo-preview').src;
    
    try {
        const res = await fetch('{{ url_for("logi.logi_complete_action", tid=0) }}'.replace('0', currentTaskId), { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ photo: photoData }) 
        });
        const data = await res.json();

        if(data.success) {
            // 1. 문자 메시지 내용 구성 (서버에서 받은 고객명과 폰번호 사용)
            const msg = `[바구니삼촌] 안녕하세요, ${data.customer}님! 주문하신 상품이 문 앞에 배송 완료되었습니다. 🧺\n배송사진 확인: https://basam.co.kr${data.photo_url || ''}`;
            
            // 2. 기사 폰 문자 앱 연동 (iOS/Android 대응)
            const isIphone = navigator.userAgent.match(/iPhone/i);
            const smsUrl = `sms:${data.phone}${isIphone ? '&' : '?'}body=${encodeURIComponent(msg)}`;
            
            alert("서버 저장 완료! 확인을 누르면 문자 발송 화면으로 이동합니다.");
            
            // 3. 문자 앱 실행 및 페이지 새로고침
            location.href = smsUrl;
            setTimeout(() => { location.reload(); }, 1000);
        } else {
            alert("오류: " + data.error);
            confirmBtn.disabled = false;
            confirmBtn.innerText = "배송 완료 확정";
        }
    } catch (e) {
        alert("네트워크 오류가 발생했습니다.");
        confirmBtn.disabled = false;
    }
};
};

        document.getElementById('confirm-btn').onclick = async () => {
            const photo = document.getElementById('photo-preview').src;
            const res = await fetch('{{ url_for("logi.logi_complete_action", tid=0) }}'.replace('0', currentTaskId), { 
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ photo: photo }) 
            });
            const data = await res.json();
            if(data.success) {
                const msg = `[바구니삼촌] 안녕하세요, ${data.customer}님! 주문하신 상품이 문 앞에 배송 완료되었습니다. 🧺`;
                const smsUrl = `sms:${data.phone}${navigator.userAgent.match(/iPhone/i) ? '&' : '?'}body=${encodeURIComponent(msg)}`;
                location.href = smsUrl;
                if(stream) stream.getTracks().forEach(t => t.stop());
                setTimeout(() => location.reload(), 500);
            }
        };

        document.getElementById('cancel-camera').onclick = () => { 
            if(stream) stream.getTracks().forEach(t => t.stop()); 
            document.getElementById('camera-layer').classList.add('hidden'); 
            document.getElementById('video').style.display = 'block';
            document.getElementById('photo-preview').classList.add('hidden');
            document.getElementById('capture-btn').classList.remove('hidden');
            document.getElementById('confirm-btn').classList.add('hidden');
        };
    </script>
</body>
</html>
    """
    return render_template_string(html, **locals())

# --------------------------------------------------------------------------------
# 8. 핵심 비즈니스 로직 & API (모든 기능 통합 복구)
# --------------------------------------------------------------------------------
# 솔라피 설정 (관리자 페이지에서 환경변수화 권장)
SOLAPI_API_KEY = 'NCSFMENLMWQDMAVG'
SOLAPI_API_SECRET = 'WFCUQXKPU8YUTHWE4QKKXLWMBVZMK8ON'
SOLAPI_SENDER = '01066681661' # 하이픈 제거

def get_solapi_header():
    date = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    salt = str(uuid.uuid4().hex)
    combined = date + salt
    signature = hmac.new(SOLAPI_API_SECRET.encode('utf-8'), combined.encode('utf-8'), hashlib.sha256).hexdigest()
    return {
        'Authorization': f'HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={date}, salt={salt}, signature={signature}',
        'Content-Type': 'application/json; charset=utf-8'
    }

def send_solapi_message(to_phone, text, order_id=None, msg_type="알림"):
    url = "https://api.solapi.com/messages/v4/send"
    payload = {
        "message": {
            "to": to_phone.replace('-', ''),
            "from": SOLAPI_SENDER,
            "text": text
        }
    }
    try:
        res = requests.post(url, json=payload, headers=get_solapi_header())
        # 발송 이력 기록 (MessageLog 활용)
        new_msg = MessageLog(order_id=order_id, message_type=msg_type, phone=to_phone, message=text, status="발송완료")
        db_delivery.session.add(new_msg)
        db_delivery.session.commit()
        return res.json()
    except Exception as e:
        print(f"SMS 발송 에러: {e}")
        return None




@logi_bp.route('/api/logs/<int:tid>')
def logi_get_task_logs(tid):
    # MessageLog를 사용하여 통합 로그(시스템로그 + 메시지로그) 반환
    logs = MessageLog.query.filter_by(task_id=tid).order_by(MessageLog.created_at.desc()).all()
    return jsonify([{"time": l.created_at.strftime('%m-%d %H:%M'), "msg": l.message} for l in logs])

@logi_bp.route('/sync')
def logi_sync():
    path = logi_get_main_db_path()
    try:
        conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        # [복구] 결제취소 상태 동기화
        cursor.execute("SELECT order_id FROM \"order\" WHERE status = '결제취소'")
        canceled_ids = [r['order_id'] for r in cursor.fetchall()]
        if canceled_ids: DeliveryTask.query.filter(DeliveryTask.order_id.in_(canceled_ids)).update({DeliveryTask.status: '결제취소'}, synchronize_session=False)
        
        # [복구] 배송요청 신규 입고
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
                        logi_add_log(nt.id, nt.order_id, '입고', '배송시스템에 신규 주문 입고됨')
                        count += 1
        db_delivery.session.commit(); conn.close(); return jsonify({"success": True, "synced_count": count})
    except Exception as e: return jsonify({"success": False, "error": str(e)})

@logi_bp.route('/bulk/execute', methods=['POST'])
def logi_bulk_execute():
    try:
        data = request.json
        ids = data.get('task_ids', []) # JS에서 보낸 [10, 11, 12...] 리스트를 받음
        action = data.get('action')
        
        if not ids:
            return jsonify({"success": False, "error": "선택된 주문이 없습니다."})

        # DB에서 선택된 모든 Task를 한 번에 가져옵니다.
        tasks = DeliveryTask.query.filter(DeliveryTask.id.in_(ids)).all()
        
        for t in tasks:
            if action == 'assign':
                d_id = data.get('driver_id')
                driver = Driver.query.get(d_id)
                if driver:
                    # 보류/대기 상관없이 모두 강제 배정
                    t.driver_id, t.driver_name, t.status = driver.id, driver.name, '배정완료'
                    logi_add_log(t.id, t.order_id, '배정', f'관리자가 [{driver.name}] 기사 일괄 배정')
            
            elif action == 'hold':
                t.status = '보류'
                logi_add_log(t.id, t.order_id, '보류', '관리자 일괄 보류 처리')
                
            elif action == 'delete':
                db_delivery.session.delete(t)
        
        # ⚠️ 루프가 다 끝난 후 '한 번에' 저장(Commit) 합니다.
        db_delivery.session.commit()
        return jsonify({"success": True})

    except Exception as e:
        db_delivery.session.rollback()
        return jsonify({"success": False, "error": str(e)})

@logi_bp.route('/bulk/pickup', methods=['POST'])
def logi_bulk_pickup():
    data = request.json
    for tid in data.get('task_ids'):
        t = DeliveryTask.query.get(tid)
        if t and t.status in ['배정완료', '대기']: 
            t.status, t.pickup_at = '픽업', datetime.now()
            logi_add_log(t.id, t.order_id, '픽업', '일괄 상차 완료 처리')
    db_delivery.session.commit(); return jsonify({"success": True})

@logi_bp.route('/update_status/<int:tid>/<string:new_status>')
def logi_update_task_status(tid, new_status):
    t = DeliveryTask.query.get(tid)
    if not t: return redirect(url_for('logi.logi_admin_dashboard'))
    
    if t.status == '완료': return "수정불가", 403
    old_status = t.status
    t.status = new_status
    
    if new_status == '픽업':
        t.pickup_at = datetime.now()
        # [솔라피 추가] 배송 시작 알림
        pickup_msg = f"[바구니삼촌] {t.customer_name}님, 기사가 배송을 시작했습니다. 순차적으로 배송됩니다."
        send_solapi_message(t.phone, pickup_msg, t.order_id, "기사픽업")
            
    logi_add_log(t.id, t.order_id, new_status, f'{old_status} -> {new_status} 상태 변경')
    db_delivery.session.commit()
    return redirect(request.referrer or url_for('logi.logi_admin_dashboard'))

@logi_bp.route('/complete_action/<int:tid>', methods=['POST'])
def logi_complete_action(tid):
    t = DeliveryTask.query.get(tid)
    d = request.json
    photo_b64 = d.get('photo') 

    if t and photo_b64:
        try:
            # 1. 이미지 저장
            header, encoded = photo_b64.split(",", 1)
            img_data = base64.b64decode(encoded)
            filename = f"proof_{t.order_id}_{datetime.now().strftime('%H%M%S')}.jpg"
            filepath = os.path.join(PROOF_FOLDER, filename)
            with open(filepath, "wb") as f:
                f.write(img_data)

            # 2. 데이터 업데이트
            t.photo_data = f"/static/proof_photos/{filename}"
            t.status = '완료'
            t.completed_at = datetime.now()

            # 3. [솔라피 추가] 배송 완료 문자 (사진 링크 포함)
            full_photo_url = f"https://basam.co.kr{t.photo_data}" 
            complete_msg = (f"[바구니삼촌] 배송이 완료되었습니다. 지정된 장소를 확인해주세요!\n"
                            f"아래 링크에서 배송사진을 확인하세요.\n{full_photo_url}")
            send_solapi_message(t.phone, complete_msg, t.order_id, "배송완료")

            db_delivery.session.commit()
            return jsonify({
        "success": True, 
        "customer": t.customer_name, 
        "phone": t.phone, 
        "photo_url": t.photo_data
    })
        except Exception as e:
            db_delivery.session.rollback()
            return jsonify({"success": False, "error": str(e)})
            
    return jsonify({"success": False, "error": "데이터가 유효하지 않습니다."})

# --------------------------------------------------------------------------------
# 9. 기사/사용자 설정 및 지도 (복구 완료)
# --------------------------------------------------------------------------------

@logi_bp.route('/drivers')
def logi_driver_mgmt():
    if not session.get('admin_logged_in'): return redirect(url_for('logi.logi_admin_login'))
    drivers = Driver.query.all()
    # 공통 접속 주소
    work_url = request.host_url.rstrip('/') + "/logi/work"
    
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <body class="bg-slate-50 p-6 font-bold">
        <div class="max-w-md mx-auto">
            <nav class="mb-8 flex justify-between items-center">
                <a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i>관제로 돌아가기</a>
            </nav>

            <h2 class="font-black mb-8 text-2xl text-slate-800 italic uppercase tracking-tighter">Driver Management</h2>
            
            <form action="{{ url_for('logi.logi_add_driver') }}" method="POST" class="bg-white p-8 rounded-[2.5rem] shadow-xl border border-slate-100 mb-10 space-y-5">
                <p class="text-[10px] text-slate-400 font-black uppercase tracking-widest px-1">기사 신규 등록</p>
                <input name="name" placeholder="기사님 성함" class="w-full border-none p-5 rounded-2xl bg-slate-50 font-black text-sm outline-none focus:ring-2 focus:ring-green-500" required>
                <input name="phone" placeholder="전화번호 (010-0000-0000)" class="w-full border-none p-5 rounded-2xl bg-slate-50 font-black text-sm outline-none focus:ring-2 focus:ring-green-500" required>
                <button class="w-full bg-slate-900 text-white py-5 rounded-2xl font-black text-lg shadow-lg hover:bg-black transition active:scale-95">기사님 등록하기</button>
            </form>

            <p class="text-[10px] text-slate-400 font-black uppercase tracking-widest px-2 mb-4">등록된 기사 목록 ({{ drivers|length }}명)</p>
            
            <div class="space-y-4">
                {% for d in drivers %}
                <div class="bg-white p-6 rounded-[2rem] border border-slate-100 flex justify-between items-center shadow-md">
                    <div>
                        <p class="font-black text-slate-800 text-lg">{{ d.name }}</p>
                        <p class="text-[11px] text-slate-400 font-bold tracking-widest">{{ d.phone }}</p>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="copyDriverUrl()" class="bg-green-50 text-green-600 px-4 py-2 rounded-xl font-black text-[10px] border border-green-100 active:scale-90 transition">주소복사</button>
                        <a href="{{ url_for('logi.logi_delete_driver', did=d.id) }}" onclick="return confirm('정말 삭제할까요?')" class="text-slate-300 hover:text-red-500 transition p-2 text-sm"><i class="fas fa-trash-alt"></i></a>
                    </div>
                </div>
                {% endfor %}
            </div>
            
            {% if not drivers %}
            <div class="py-20 text-center text-slate-300 font-bold italic text-sm">등록된 기사님이 없습니다.</div>
            {% endif %}
        </div>

        <script>
            function copyDriverUrl() {
                const t = document.createElement("input");
                document.body.appendChild(t);
                t.value = "{{ work_url }}";
                t.select();
                document.execCommand("copy");
                document.body.removeChild(t);
                alert("기사용 접속 주소가 복사되었습니다.\\n기사님께 이 주소를 보내주시면 성함과 번호로 로그인이 가능합니다.");
            }
        </script>
    </body>
    """, drivers=drivers, work_url=work_url)

@logi_bp.route('/driver/add', methods=['POST'])
def logi_add_driver():
    db_delivery.session.add(Driver(name=request.form['name'], phone=request.form['phone'], token=str(uuid.uuid4())[:12]))
    db_delivery.session.commit(); return redirect(url_for('logi.logi_driver_mgmt'))

@logi_bp.route('/driver/delete/<int:did>')
def logi_delete_driver(did):
    Driver.query.filter_by(id=did).delete(); db_delivery.session.commit(); return redirect(url_for('logi.logi_driver_mgmt'))

@logi_bp.route('/cancel/<int:tid>')
def logi_cancel_assignment(tid):
    t = DeliveryTask.query.get(tid)
    if t: 
        t.driver_id, t.driver_name, t.status, t.pickup_at = None, '미배정', '대기', None
        logi_add_log(t.id, t.order_id, '재배정', '관리자가 기사 배정을 취소하고 대기 상태로 초기화함')
    db_delivery.session.commit(); return redirect(request.referrer or url_for('logi.logi_admin_dashboard'))

@logi_bp.route('/admin/users', methods=['GET', 'POST'])
def logi_admin_users_mgmt():
    if not session.get('admin_logged_in') or session.get('admin_username') != 'admin':
        return redirect(url_for('logi.logi_admin_dashboard'))
    
    if request.method == 'POST':
        new_un = request.form.get('new_username')
        new_pw = request.form.get('new_password')
        if new_un and new_pw:
            db_delivery.session.add(AdminUser(username=new_un, password=new_pw))
            db_delivery.session.commit()
            flash("새 관리자가 등록되었습니다.")
            return redirect(url_for('logi.logi_admin_users_mgmt'))

    users = AdminUser.query.all()
    html = """
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6 font-bold text-slate-800">
        <div class="max-w-md mx-auto">
            <nav class="mb-8"><a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600"><i class="fas fa-arrow-left mr-2"></i>돌아가기</a></nav>
            <h2 class="text-2xl font-black mb-8 italic">ADMIN SETTINGS</h2>
            
            <form method="POST" class="bg-white p-6 rounded-[2rem] shadow-xl border mb-10 space-y-4">
                <p class="text-xs text-slate-400 uppercase tracking-widest mb-2">신규 관리자 추가</p>
                <input name="new_username" placeholder="아이디" class="w-full p-4 rounded-2xl bg-slate-50 border-none text-sm" required>
                <input name="new_password" placeholder="비밀번호" class="w-full p-4 rounded-2xl bg-slate-50 border-none text-sm" required>
                <button class="w-full bg-slate-800 text-white py-4 rounded-2xl font-black shadow-lg">관리자 등록</button>
            </form>

            <div class="space-y-3">
                <p class="text-xs text-slate-400 uppercase tracking-widest px-2">현재 관리자 목록</p>
                {% for u in users %}
                <div class="bg-white p-5 rounded-2xl border flex justify-between items-center shadow-sm">
                    <span>{{ u.username }}</span>
                    {% if u.username != 'admin' %}
                    <a href="{{ url_for('logi.logi_delete_admin', uid=u.id) }}" class="text-red-300 hover:text-red-500 text-xs">삭제</a>
                    {% else %}
                    <span class="text-slate-300 text-[10px]">MASTER</span>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
    </body>
    """
    return render_template_string(html, users=users)

# 삭제 라우트 추가
@logi_bp.route('/admin/delete_user/<int:uid>')
def logi_delete_admin(uid):
    if session.get('admin_username') == 'admin':
        AdminUser.query.filter_by(id=uid).delete()
        db_delivery.session.commit()
    return redirect(url_for('logi.logi_admin_users_mgmt'))

@logi_bp.route('/admin/map')
def logi_driver_path_map():
    if not session.get('admin_logged_in'): return redirect(url_for('logi.logi_admin_login'))
    tasks = DeliveryTask.query.filter(DeliveryTask.status == '완료', DeliveryTask.completed_at >= datetime.now().replace(hour=0,minute=0,second=0)).all()
    return render_template_string("""
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <nav class="mb-6"><a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i>돌아가기</a></nav>
        <h2 class="text-2xl font-black mb-6 italic uppercase tracking-tighter">Delivery Path Map</h2>
        <div id="map" style="width:100%;height:500px;" class="rounded-[3rem] border shadow-2xl bg-white flex items-center justify-center text-slate-300 font-black">
            📍 Kakao Maps API 연동 준비 완료. <br> 등록된 주소 좌표 분석 중...
        </div>
        <div class="mt-8 space-y-3">
            {% for t in tasks %}<div class="text-[11px] bg-white p-4 rounded-[1.5rem] border font-black shadow-sm flex items-center gap-3">📍 {{t.address}} <span class="text-slate-300">({{t.driver_name}})</span></div>{% endfor %}
        </div>
    </body>
    """, tasks=tasks)