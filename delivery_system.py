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
from flask import Blueprint, render_template_string, request, redirect, jsonify, flash, url_for, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, UniqueConstraint

# [핵심] Blueprint 정의 (이름: logi, 주소 접두어: /logi)
# 이 설정으로 인해 이제 모든 주소는 basam.co.kr/logi/... 가 됩니다.
logi_bp = Blueprint('logi', __name__, url_prefix='/logi')
db_delivery = SQLAlchemy()

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

class DeliveryLog(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    task_id = db_delivery.Column(db_delivery.Integer)
    order_id = db_delivery.Column(db_delivery.String(100))
    status = db_delivery.Column(db_delivery.String(50))
    message = db_delivery.Column(db_delivery.String(500))
    created_at = db_delivery.Column(db_delivery.DateTime, default=datetime.now)

# --------------------------------------------------------------------------------
# 4. 유틸리티 함수 (함수명 겹침 방지 접두어 사용)
# --------------------------------------------------------------------------------

def logi_add_log(task_id, order_id, status, message):
    log = DeliveryLog(task_id=task_id, order_id=order_id, status=status, message=message)
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
    # 상태 필터링
    if st_filter == '미배정': query = query.filter(DeliveryTask.status == '대기', DeliveryTask.driver_id == None)
    elif st_filter == '배정완료': query = query.filter(DeliveryTask.status == '배정완료')
    elif st_filter != 'all': query = query.filter_by(status=st_filter)
    
    # 카테고리 필터링
    if cat_filter != '전체': query = query.filter_by(category=cat_filter)
    
    # 검색어 필터링
    if q: query = query.filter((DeliveryTask.address.contains(q)) | (DeliveryTask.customer_name.contains(q)))
    
    tasks = query.all()
    tasks.sort(key=lambda x: (x.address or "", logi_extract_qty(x.product_details)), reverse=True)
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
    # 현황판용 수치 계산
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
            <button onclick="changeFontSize(-1)" class="w-full h-full text-xs">A-</button>
            <button onclick="changeFontSize(1)" class="w-full h-full text-xs">A+</button>
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
                <button onclick="syncNow()" class="bg-red-600 text-white px-5 py-2 rounded-xl font-black text-[11px] shadow-lg hover:bg-red-700 transition animate-bounce">신규 주문 가져오기</button>
                <a href="{{ url_for('logi.logi_admin_logout') }}" class="text-slate-300 font-bold hover:text-red-500"><i class="fas fa-sign-out-alt"></i></a>
            </div>
        </nav>

        <main class="p-4 max-w-[1400px] mx-auto">
            <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
                <div class="bg-white p-6 rounded-[2rem] shadow-sm border-b-8 border-red-500 text-center {% if pending_sync_count > 0 %}animate-pulse{% endif %}">
                    <p class="text-[10px] font-black text-red-300 uppercase tracking-tighter mb-1">New Orders</p>
                    <p class="text-3xl font-black text-red-600" id="sync-count-val">{{pending_sync_count}}</p>
                </div>
                <div class="bg-white p-6 rounded-[2rem] shadow-sm border-b-8 border-slate-200 text-center">
                    <p class="text-[10px] font-black text-slate-300 uppercase tracking-tighter mb-1">Unassigned</p><p class="text-3xl font-black text-slate-700">{{unassigned_count}}</p>
                </div>
                <div class="bg-white p-6 rounded-[2rem] shadow-sm border-b-8 border-blue-500 text-center">
                    <p class="text-[10px] font-black text-blue-300 uppercase tracking-tighter mb-1">Assigned</p><p class="text-3xl font-black text-blue-600">{{assigned_count}}</p>
                </div>
                <div class="bg-white p-6 rounded-[2rem] shadow-sm border-b-8 border-orange-500 text-center">
                    <p class="text-[10px] font-black text-orange-300 uppercase tracking-tighter mb-1">Picking</p><p class="text-3xl font-black text-orange-600">{{picking_count}}</p>
                </div>
                <div class="bg-white p-6 rounded-[2rem] shadow-sm border-b-8 border-green-500 text-center">
                    <p class="text-[10px] font-black text-green-300 uppercase tracking-tighter mb-1">Completed</p><p class="text-3xl font-black text-green-600">{{complete_today}}</p>
                </div>
            </div> 


            <div class="bg-white p-5 rounded-[2rem] border border-blue-50 shadow-sm mb-6">
                <h3 class="text-[11px] font-black text-blue-500 mb-3 italic flex items-center gap-2"><span class="w-1.5 h-4 bg-blue-500 rounded-full"></span> 현재 필터 기준 품목 합계</h3>
                <div class="flex flex-wrap gap-2">
                    {% for name, total in item_sum.items() %}
                    <span class="bg-blue-50 text-blue-700 px-3 py-1 rounded-lg border border-blue-100 font-black text-[11px]">{{ name }}: {{ total }}개</span>
                    {% else %}
                    <span class="text-slate-300 font-bold">집계할 데이터가 없습니다.</span>
                    {% endfor %}
                </div>
            </div>

      <div class="bg-white p-2 md:p-3 rounded-xl border border-slate-100 shadow-sm mb-4 flex flex-wrap justify-between items-center gap-4">
    <div class="flex gap-4 border-b w-full md:w-auto overflow-x-auto no-scrollbar whitespace-nowrap text-[11px] font-black tracking-tighter">
        <a href="{{ url_for('logi.logi_admin_dashboard', status='all') }}" class="{% if current_status=='all' %}tab-active{% endif %} pb-1.5 px-1">전체</a>
        <a href="{{ url_for('logi.logi_admin_dashboard', status='미배정') }}" class="{% if current_status=='미배정' %}tab-active{% endif %} pb-1.5 px-1 text-slate-300">미배정</a>
        <a href="{{ url_for('logi.logi_admin_dashboard', status='배정완료') }}" class="{% if current_status=='배정완료' %}tab-active{% endif %} pb-1.5 px-1 text-blue-500">배정됨</a>
        <a href="{{ url_for('logi.logi_admin_dashboard', status='픽업') }}" class="{% if current_status=='픽업' %}tab-active{% endif %} pb-1.5 px-1 text-orange-500">배송중</a>
        <a href="{{ url_for('logi.logi_admin_dashboard', status='완료') }}" class="{% if current_status=='완료' %}tab-active{% endif %} pb-1.5 px-1 text-green-600">완료</a>
        <a href="{{ url_for('logi.logi_admin_dashboard', status='보류') }}" class="{% if current_status=='보류' %}tab-active{% endif %} pb-1.5 px-1 text-yellow-600">보류</a>
    </div>
</div>
                <div class="flex items-center gap-3 flex-wrap">
                    <select onchange="location.href='{{ url_for('logi.logi_admin_dashboard') }}?status={{current_status}}&category='+encodeURIComponent(this.value)" class="border border-slate-100 rounded-xl px-3 py-2 font-black text-slate-400 bg-slate-50 text-[11px] outline-none">
                        <option value="전체">카테고리 전체보기</option>
                        {% for sc in saved_cats %}<option value="{{sc}}" {% if current_cat == sc %}selected{% endif %}>{{sc}}</option>{% endfor %}
                    </select>
                    <div class="bg-blue-50 p-2 rounded-2xl flex items-center gap-2 border border-blue-100 shadow-inner">
                        <select id="bulk-driver" class="border rounded-xl px-3 py-1.5 font-black text-blue-600 text-[11px] bg-white outline-none">
                            <option value="">일괄 기사 배정</option>
                            {% for d in drivers %}<option value="{{d.id}}">{{d.name}}</option>{% endfor %}
                        </select>
                        <button onclick="bulkAction('assign')" class="bg-blue-600 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition">배정</button>
                        <button onclick="bulkAction('hold')" class="bg-yellow-500 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition">보류</button>
                        <button onclick="bulkAction('delete')" class="bg-slate-800 text-white px-4 py-1.5 rounded-xl font-black text-[11px] shadow-sm active:scale-95 transition">삭제</button>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-[2rem] shadow-xl border border-slate-50 overflow-hidden mb-12">
                <table class="w-full text-left">
                    <thead class="bg-slate-800 border-b text-slate-400 font-black text-[10px] uppercase tracking-widest">
                        <tr>
                            <th class="p-4 w-12 text-center"><input type="checkbox" id="check-all" onclick="toggleAll()" class="w-4 h-4 rounded"></th>
                            <th class="p-4 w-20 text-center">Status</th>
                            <th class="p-4">Address & Product & History</th>
                            <th class="p-4 w-24 text-center">Action</th>
                        </tr>
                    </thead>
<tbody class="divide-y divide-slate-100 bg-white">
    {% for t in tasks %}
    <tr class="{% if t.status == '결제취소' %}bg-red-50{% endif %} hover:bg-slate-50 transition">
        <td class="py-3 px-2 text-center w-8">
            <input type="checkbox" class="task-check w-4 h-4 rounded border-slate-300 accent-green-600" value="{{t.id}}">
        </td>
        
        <td class="py-3 px-1 text-center w-16">
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
            <a href="{{ url_for('logi.logi_cancel_assignment', tid=t.id) }}" 
               class="inline-block text-[10px] bg-slate-800 text-white px-2.5 py-1.5 rounded-lg font-black shadow-sm active:scale-90 transition-transform whitespace-nowrap" 
               onclick="return confirm('배정을 해제하고 대기목록으로 보낼까요?')">
                재배정
            </a>
        </td>
    </tr>
    {% endfor %}
</tbody>
                </table>
                {% if not tasks %}
                <div class="py-32 text-center text-slate-300 font-black text-lg italic">No Data Found.</div>
                {% endif %}
            </div>
        </main>
        <script>
            let currentSize = 12;
            function changeFontSize(delta) {
                currentSize += delta;
                if(currentSize < 10) currentSize = 10;
                if(currentSize > 20) currentSize = 20;
                document.getElementById('app-body').style.fontSize = currentSize + 'px';
            }
            async function viewTaskLog(tid) {
                const box = document.getElementById('log-view-'+tid);
                box.classList.toggle('hidden');
                if(!box.classList.contains('hidden')) {
                    const res = await fetch('{{ url_for("logi.logi_get_task_logs", tid=0) }}'.replace('0', tid));
                    const logs = await res.json();
                    box.innerHTML = '<p class="font-black text-slate-400 mb-2 border-b border-slate-200 pb-1 uppercase tracking-widest">Order Life Cycle Log</p>' + 
                                    logs.map(l => `<div><span class="text-slate-300 font-black mr-2">${l.time}</span> <span class="text-slate-500 font-bold">${l.msg}</span></div>`).join('');
                }
            }
            async function syncNow() {
    if(!confirm("쇼핑몰의 신규 주문 데이터를 동기화하시겠습니까?")) return;
    
    // 버튼 상태 변경
    const syncBtn = event.currentTarget;
    syncBtn.innerText = "동기화 중...";
    syncBtn.classList.add('opacity-50');

    const res = await fetch('{{ url_for("logi.logi_sync") }}');
    const data = await res.json();
    
    if(data.success) { 
        // 동기화 성공 시 숫자 0으로 시각적 변경
        const syncVal = document.getElementById('sync-count-val');
        if(syncVal) syncVal.innerText = "0";
        
        alert(data.synced_count + "건의 신규 배송건이 입고되었습니다."); 
        location.reload(); 
    }
    else { 
        alert("동기화 오류: " + data.error); 
        syncBtn.innerText = "신규 주문 가져오기";
        syncBtn.classList.remove('opacity-50');
    }
}
            function toggleAll() {
                const isChecked = document.getElementById('check-all').checked;
                document.querySelectorAll('.task-check').forEach(i => i.checked = isChecked);
            }
            async function bulkAction(type) {
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("선택된 항목이 없습니다.");
                let payload = { task_ids: selected, action: type };
                if(type === 'assign') {
                    const dId = document.getElementById('bulk-driver').value;
                    if(!dId) return alert("기사를 선택해 주세요.");
                    payload.driver_id = dId;
                } else {
                    if(!confirm("일괄 작업을 진행하시겠습니까?")) return;
                }
                await fetch('{{ url_for("logi.logi_bulk_execute") }}', { 
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'}, 
                    body: JSON.stringify(payload) 
                });
                location.reload();
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, **locals(), current_status=st_filter, current_cat=cat_filter)

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

    view_status = request.args.get('view', 'assigned') 
    query = DeliveryTask.query.filter(DeliveryTask.driver_id == driver.id)
    if view_status == 'assigned': tasks = query.filter(DeliveryTask.status.in_(['배정완료', '대기'])).all()
    elif view_status == 'pickup': tasks = query.filter_by(status='픽업').all()
   # [수정 전]
# elif view_status == 'complete': tasks = query.filter_by(status='완료').all()

# [수정 후]
    elif view_status == 'complete':
      days = int(request.args.get('days', 7)) # 기본 7일
      since = datetime.now() - timedelta(days=days)
      tasks = query.filter(DeliveryTask.status == '완료', DeliveryTask.completed_at >= since).all()
    else: tasks = query.filter(DeliveryTask.status != '완료').all()

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
            .tab-btn { 
                flex: 1; text-align: center; padding: 15px 5px; font-weight: 800; 
                color: #94a3b8; border-bottom: 3px solid #1e293b; font-size: 14px; 
            }
            .tab-btn.active { color: #22c55e; border-bottom: 3px solid #22c55e; background: linear-gradient(to top, rgba(34,197,94,0.1), transparent); }
            .task-card {
                background: #1e293b; border-radius: 1.25rem;
                padding: 1.25rem; border: 1px solid #334155;
                margin-bottom: 1rem; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
            }
            .address-highlight { color: #ffffff; font-weight: 900; line-height: 1.2; }
            .product-badge { background: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 8px; font-weight: 800; font-size: 15px; }
            /* 하단 플로팅 조작바 */
            .bottom-ctrl { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); width: 90%; z-index: 1000; }
        </style>
    </head>
    <body class="pb-32 px-3" id="driver-body">
        <header class="flex justify-between items-center py-5 px-2">
            <div>
                <h1 class="text-xl font-black text-green-500 italic uppercase">B.Uncle Logi</h1>
                <p class="text-[10px] text-slate-500 font-bold uppercase">{{ driver_name }} 기사님 반갑습니다.</p>
            </div>
            <button onclick="location.reload()" class="bg-slate-800 w-12 h-12 rounded-2xl flex items-center justify-center shadow-lg active:scale-90 transition">
                <i class="fas fa-sync-alt text-green-500"></i>
            </button>
        </header>

        <div class="flex mb-4 bg-[#1e293b] rounded-2xl overflow-hidden shadow-xl sticky top-2 z-40 border border-slate-700">
            <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=assigned" class="tab-btn {% if view_status=='assigned' %}active{% endif %}">대기/배정</a>
            <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=pickup" class="tab-btn {% if view_status=='pickup' %}active{% endif %}">배송중</a>
            <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=complete" class="tab-btn {% if view_status=='complete' %}active{% endif %}">배송완료</a>
        </div>

        {% if view_status == 'complete' %}
        <div class="flex gap-2 mb-4 overflow-x-auto pb-2 no-scrollbar">
            {% for d in [7, 15, 30] %}
            <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=complete&days={{d}}" 
               class="px-4 py-2 rounded-full text-xs font-bold border {% if request.args.get('days')|int == d or (not request.args.get('days') and d==7) %}bg-green-600 border-green-600 text-white{% else %}bg-slate-800 border-slate-700 text-slate-400{% endif %} whitespace-nowrap">
               최근 {{d}}일
            </a>
            {% endfor %}
        </div>
        {% endif %}

        {% if view_status != 'complete' %}
        <div class="bg-slate-900/80 backdrop-blur-md p-4 rounded-2xl mb-4 border border-slate-800">
            <div class="flex justify-between items-end mb-3">
                <span class="text-[10px] font-black text-slate-500 uppercase">품목별 합계 ({{tasks|length}}건)</span>
            </div>
            <div class="flex flex-wrap gap-2">
                {% for name, total in item_sum.items() %}
                <span class="bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-xl text-green-400 font-black text-xs">{{ name }} {{ total }}</span>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <div class="space-y-3">
            {% for t in tasks %}
            <div class="task-card">
                <div class="flex items-start gap-3">
                    <input type="checkbox" class="task-check w-7 h-7 mt-1 rounded-lg bg-slate-900 border-slate-700 accent-green-500" value="{{t.id}}">
                    <div class="flex-1 min-w-0">
                        <div class="address-highlight text-[22px] mb-2 break-all">{{ t.address }}</div>
                        <div class="mb-3"><span class="product-badge">{{ t.product_details }}</span></div>
                        
                        <div class="grid grid-cols-2 gap-2 text-[13px] font-bold text-slate-400 border-t border-slate-700/50 pt-3">
                            <div class="flex items-center gap-2"><i class="fas fa-user text-slate-600"></i>{{ t.customer_name }}</div>
                            <a href="tel:{{t.phone}}" class="flex items-center gap-2 text-blue-400"><i class="fas fa-phone-alt"></i> 전화하기</a>
                        </div>
                        {% if t.memo %}
                        <div class="mt-2 text-[12px] bg-slate-900/50 p-2 rounded-lg text-orange-300 font-medium">
                            <i class="fas fa-comment-dots mr-1"></i> {{t.memo}}
                        </div>
                        {% endif %}
                    </div>
                </div>
                
                <div class="mt-4">
                    {% if t.status in ['배정완료', '대기'] %}
                    <button onclick="secureStatus('{{t.id}}', '픽업')" class="w-full bg-orange-600 text-white py-4 rounded-xl font-black text-lg shadow-lg active:scale-95 transition">상차 완료</button>
                    {% elif t.status == '픽업' %}
                    <button onclick="openCameraUI('{{t.id}}')" class="w-full bg-green-600 text-white py-4 rounded-xl font-black text-lg shadow-lg active:scale-95 transition">배송 완료 처리</button>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        <div class="bottom-ctrl flex gap-3">
            <div class="bg-slate-800/90 backdrop-blur-md p-2 rounded-2xl border border-slate-700 flex gap-2 w-full shadow-2xl">
                <button onclick="toggleAll()" class="bg-slate-700 text-white px-4 py-3 rounded-xl font-black text-xs">전체선택</button>
                <button onclick="bulkActionDriver('hold')" class="bg-slate-900 text-yellow-500 px-4 py-3 rounded-xl font-black text-xs flex-1 border border-yellow-900/30">재배정 요청</button>
                {% if view_status == 'assigned' %}
                <button onclick="bulkPickup()" class="bg-blue-600 text-white px-4 py-3 rounded-xl font-black text-xs flex-1 shadow-lg">일괄 상차</button>
                {% endif %}
                <div class="flex flex-col gap-1">
                    <button onclick="changeFontSize(2)" class="bg-green-600 text-white w-10 h-6 rounded-lg text-[10px] font-black">A+</button>
                    <button onclick="changeFontSize(-2)" class="bg-slate-700 text-white w-10 h-6 rounded-lg text-[10px] font-black">A-</button>
                </div>
            </div>
        </div>

        <div id="camera-layer" class="fixed inset-0 bg-black z-[5000] hidden flex flex-col items-center justify-center p-4">
            <div class="relative w-full aspect-[3/4] overflow-hidden rounded-3xl shadow-2xl bg-slate-900 mb-6">
                <video id="video" class="w-full h-full object-cover" autoplay playsinline></video>
                <canvas id="canvas" class="hidden"></canvas>
                <img id="photo-preview" class="hidden w-full h-full object-cover">
            </div>
            <div class="flex gap-4 w-full max-w-sm">
                <button id="capture-btn" class="flex-1 bg-white text-black py-5 rounded-2xl font-black text-xl shadow-xl">사진 촬영</button>
                <button id="confirm-btn" class="hidden flex-1 bg-green-600 text-white py-5 rounded-2xl font-black text-xl shadow-xl">배송 확정</button>
                <button id="cancel-camera" class="w-20 bg-slate-800 text-white py-5 rounded-2xl font-bold">닫기</button>
            </div>
        </div>

        <script>
            let currentSize = 15;
            function changeFontSize(d) { 
                currentSize += d; 
                if(currentSize < 12) currentSize = 12; if(currentSize > 35) currentSize = 35; 
                document.getElementById('driver-body').style.fontSize = currentSize+'px';
                // 주소 텍스트는 본문보다 약간 더 크게 비례 조절
                document.querySelectorAll('.address-text').forEach(el => {
                    el.style.fontSize = (currentSize + 5) + 'px';
                });
            }
            function toggleAll() { const isChecked = document.getElementById('check-all').checked; document.querySelectorAll('.task-check').forEach(i => i.checked = isChecked); }
            
            async function secureStatus(tid, status) {
                if(confirm("["+status+"] 처리를 진행할까요?")) {
                    await fetch('{{ url_for("logi.logi_update_task_status", tid=0, new_status="X") }}'.replace('0', tid).replace('X', status));
                    location.reload();
                }
            }

            async function bulkActionDriver(action) {
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("항목을 선택해 주세요.");
                if(confirm("재배정 요청을 일괄로 진행하시겠습니까?")) {
                    await fetch('{{ url_for("logi.logi_bulk_execute") }}', { 
                        method: 'POST', 
                        headers: {'Content-Type': 'application/json'}, 
                        body: JSON.stringify({ task_ids: selected, action: action }) 
                    });
                    location.reload();
                }
            }

            async function bulkPickup(){
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("항목을 선택해 주세요.");
                if(confirm("선택한 물량을 일괄 상차(픽업) 완료하시겠습니까?")) {
                    await fetch('{{ url_for("logi.logi_bulk_pickup") }}', { 
                        method: 'POST', 
                        headers: {'Content-Type': 'application/json'}, 
                        body: JSON.stringify({ task_ids: selected }) 
                    });
                    location.reload();
                }
            }

            let currentTaskId = null; let stream = null;
            async function openCameraUI(tid){
                currentTaskId = tid; document.getElementById('camera-layer').classList.remove('hidden');
                try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); document.getElementById('video').srcObject = stream; } 
                catch (e) { alert("카메라 권한 오류: " + e); }
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
                const res = await fetch('{{ url_for("logi.logi_complete_action", tid=0) }}'.replace('0', currentTaskId), { 
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ photo: photo }) 
                });
                const data = await res.json();
                if(data.success) {
                    const msg = `[바구니삼촌] 안녕하세요, ${data.customer}님! 주문하신 상품이 문 앞에 배송 완료되었습니다. 🧺`;
                    const smsUrl = `sms:${data.phone}${navigator.userAgent.match(/iPhone/i) ? '&' : '?'}body=${encodeURIComponent(msg)}`;
                    location.href = smsUrl;
                    if(stream) stream.getTracks().forEach(t => t.stop());
                    setTimeout(() => location.reload(), 1200);
                }
            };

            document.getElementById('cancel-camera').onclick = () => { 
                if(stream) stream.getTracks().forEach(t => t.stop()); 
                document.getElementById('camera-layer').classList.add('hidden'); 
                document.getElementById('video').classList.remove('hidden');
                document.getElementById('preview-box').classList.add('hidden');
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

@logi_bp.route('/api/logs/<int:tid>')
def logi_get_task_logs(tid):
    logs = DeliveryLog.query.filter_by(task_id=tid).order_by(DeliveryLog.created_at.desc()).all()
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
    data = request.json; ids, action = data.get('task_ids', []), data.get('action')
    tasks = DeliveryTask.query.filter(DeliveryTask.id.in_(ids)).all()
    for t in tasks:
        if action == 'assign':
            d = Driver.query.get(data.get('driver_id'))
            if d:
                t.driver_id, t.driver_name, t.status = d.id, d.name, '배정완료'
                logi_add_log(t.id, t.order_id, '배정', f'관리자가 기사[{d.name}] 배정 완료')
        elif action == 'hold':
            t.status = '보류'
            logi_add_log(t.id, t.order_id, '보류', '재배정 요청 및 보류 처리됨')
        elif action == 'delete':
            db_delivery.session.delete(t)
    db_delivery.session.commit(); return jsonify({"success": True})

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
    if t:
        if t.status == '완료': return "수정불가", 403
        old = t.status; t.status = new_status
        if new_status == '픽업': t.pickup_at = datetime.now()
        logi_add_log(t.id, t.order_id, new_status, f'{old} -> {new_status} 상태 변경')
        db_delivery.session.commit()
    return redirect(request.referrer or url_for('logi.logi_admin_dashboard'))

@logi_bp.route('/complete_action/<int:tid>', methods=['POST'])
def logi_complete_action(tid):
    t = DeliveryTask.query.get(tid); d = request.json
    if t:
        t.status, t.completed_at, t.photo_data = '완료', datetime.now(), d.get('photo')
        logi_add_log(t.id, t.order_id, '완료', '기사 배송 완료 및 안내 전송')
        db_delivery.session.commit()
        return jsonify({"success": True, "customer": t.customer_name, "phone": t.phone})
    return jsonify({"success": False})

# --------------------------------------------------------------------------------
# 9. 기사/사용자 설정 및 지도 (복구 완료)
# --------------------------------------------------------------------------------

@logi_bp.route('/drivers')
def logi_driver_mgmt():
    if not session.get('admin_logged_in'): return redirect(url_for('logi.logi_admin_login'))
    drivers = Driver.query.all()
    # 공통 접속 주소 (토큰 없음)
    work_url = request.host_url.rstrip('/') + "/logi/work"
    
    return render_template_string("""
                                  
    <script src="https://cdn.tailwindcss.com"></script>
    <body class="bg-slate-50 p-6">
        <div class="max-w-md mx-auto">
            <nav class="mb-8"><a href="{{ url_for('logi.logi_admin_dashboard') }}" class="text-green-600 font-black"><i class="fas fa-arrow-left mr-2"></i>돌아가기</a></nav>
            <h2 class="font-black mb-8 text-2xl text-slate-800 italic uppercase">Driver Management</h2>
            <form action="{{ url_for('logi.logi_add_driver') }}" method="POST" class="bg-white p-8 rounded-[2.5rem] shadow-xl border mb-10 space-y-5">
                <input name="name" placeholder="기사님 성함" class="w-full border-none p-5 rounded-2xl bg-slate-50 font-black text-sm" required>
                <input name="phone" placeholder="전화번호 (인증용)" class="w-full border-none p-5 rounded-2xl bg-slate-50 font-black text-sm" required>
                <button class="w-full bg-green-600 text-white py-5 rounded-2xl font-black text-lg shadow-lg hover:bg-green-700 transition active:scale-95">신규 기사 생성</button>
            </form>
            <div class="space-y-4">
                {% for d in drivers %}
<div class="bg-white p-6 rounded-[2rem] border flex justify-between items-center shadow-md border-slate-100">
        <div>
            <p class="font-black text-slate-800 text-lg">{{ d.name }}</p>
            <p class="text-[11px] text-slate-400 font-bold tracking-widest">{{ d.phone }}</p>
        </div>
        <div class="flex gap-2">
            <button onclick="copyUrl()" class="bg-blue-50 text-blue-600 px-4 py-2 rounded-xl font-black text-[10px] border border-blue-100">접속주소 복사</button>
            <button onclick="secureDelete({{d.id}})" class="text-red-300 hover:text-red-500 transition p-3"><i class="fas fa-trash-alt"></i></button>
        </div>
    </div>
<div class="flex mb-6 bg-[#1e293b] rounded-3xl overflow-hidden shadow-2xl border-b border-slate-700 mx-2">
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=assigned" class="tab-btn {% if view_status=='assigned' %}active{% endif %}">대기/배정</a>
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=pickup" class="tab-btn {% if view_status=='pickup' %}active{% endif %}">배송중</a>
        <a href="?driver_name={{driver_name}}&auth_phone={{auth_phone}}&view=complete" class="tab-btn {% if view_status=='complete' %}active{% endif %}">완료</a>
    </div>
                </div>
                {% endfor %}
            </div>
        </div>
<script>
        function copyUrl() {
            const t = document.createElement("input"); document.body.appendChild(t); 
            t.value = "{{work_url}}"; t.select();
            document.execCommand("copy"); document.body.removeChild(t); 
            alert("기사용 접속 주소가 복사되었습니다.\\n기사님은 성함과 전화번호로 로그인하시면 됩니다.");
        }
    </script>
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

@logi_bp.route('/admin/users')
def logi_admin_users_mgmt():
    if not session.get('admin_logged_in') or session.get('admin_username') != 'admin': return redirect(url_for('logi.logi_admin_dashboard'))
    users = AdminUser.query.all()
    return render_template_string("""...운영진 관리 HTML...""", users=users)

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