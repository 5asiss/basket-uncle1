import os
import sqlite3
import requests
import json
import time
import hmac
import hashlib
import re
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, jsonify, flash, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, UniqueConstraint

# 1. 초기 설정
app = Flask(__name__)
app.secret_key = "delivery_safe_key_v12_summary"

# 경로 설정 (로컬 환경 최적화)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DB_PATH = os.path.join(BASE_DIR, 'instance', 'direct_trade_mall.db')
DELIVERY_DB_PATH = os.path.join(BASE_DIR, 'delivery.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DELIVERY_DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db_delivery = SQLAlchemy(app)

# 2. 알림톡 API 설정 (미입력 시 시뮬레이션)
API_KEY = ""
API_SECRET = ""
PFID = ""
TEMPLATE_ID = ""

# 3. 데이터베이스 모델
class Driver(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    name = db_delivery.Column(db_delivery.String(50), nullable=False)
    phone = db_delivery.Column(db_delivery.String(20))
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
    status = db_delivery.Column(db_delivery.String(20), default="대기") # 대기 -> 픽업 -> 완료
    
    photo_data = db_delivery.Column(db_delivery.Text, nullable=True) 
    pickup_at = db_delivery.Column(db_delivery.DateTime, nullable=True)
    completed_at = db_delivery.Column(db_delivery.DateTime, nullable=True)

    __table_args__ = (UniqueConstraint('order_id', 'category', name='_order_cat_v12_uc'),)

# 4. 유틸리티 함수
def extract_qty(text_data):
    """문자열에서 (숫자)를 찾아 숫자로 반환"""
    match = re.search(r'\((\d+)\)', text_data)
    return int(match.group(1)) if match else 0

def get_item_summary(tasks):
    """리스트에 있는 품목별 수량 합계를 계산합니다."""
    summary = {}
    for t in tasks:
        # "[카테고리] 품목명(수량)" 형태에서 품목명과 수량 추출
        items = re.findall(r'\]\s*(.*?)\((\d+)\)', t.product_details)
        if not items:
            items = re.findall(r'(.*?)\((\d+)\)', t.product_details)
            
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

def send_delivery_complete_msg(task):
    print(f"[알림전송 시뮬레이션] {task.customer_name}님께 배송사진과 함께 완료 메시지 전송됨")
    return True

# 5. UI: 관리자 화면
@app.route('/')
def admin_dashboard():
    st_filter = request.args.get('status', 'all')
    cat_filter = request.args.get('category', '전체')
    q = request.args.get('q', '')

    query = DeliveryTask.query
    if st_filter != 'all': query = query.filter_by(status=st_filter)
    if cat_filter != '전체': query = query.filter_by(category=cat_filter)
    if q: query = query.filter((DeliveryTask.address.contains(q)) | (DeliveryTask.customer_name.contains(q)))
    
    tasks = query.all()
    tasks.sort(key=lambda x: (x.address or "", extract_qty(x.product_details)), reverse=True)
    
    # [추가] 품목별 합계 계산
    item_sum = get_item_summary(tasks)
    
    drivers = Driver.query.all()
    main_cats = get_main_db_categories()
    saved_cats = sorted(list(set([t.category for t in DeliveryTask.query.all() if t.category])))

    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>바구니삼촌 LOGI - 관리자</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #f8fafc; }
        .tab-active { border-bottom: 3px solid #16a34a; color: #16a34a; font-weight: 900; }
        .excel-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; white-space: normal; word-break: keep-all; }
        .excel-table th { padding: 10px 12px; background: #f8fafc; position: sticky; top: 0; z-index: 5; }
        .summary-badge { background: #e0f2fe; color: #0369a1; padding: 4px 10px; rounded: 8px; font-weight: 900; margin-right: 8px; border: 1px solid #bae6fd; }
        </style>
    </head>
    <body class="text-[11px]">
        <nav class="bg-white border-b h-14 flex items-center justify-between px-6 sticky top-0 z-50">
            <div class="flex items-center gap-10">
                <h1 class="text-xl font-black text-green-600 italic">B.UNCLE LOGI</h1>
                <div class="flex gap-6 font-bold text-slate-400"><a href="/" class="text-green-600 border-b-2 border-green-600">배송통제</a><a href="/drivers">기사관리</a></div>
            </div>
            <div class="flex gap-2">
                <select id="sync-cat" class="border rounded px-2 py-1 font-bold text-[10px]">
                    <option value="전체">전체 카테고리</option>
                    {% for mc in main_cats %}<option value="{{mc}}">{{mc}}</option>{% endfor %}
                </select>
                <button onclick="syncNow()" class="bg-green-600 text-white px-4 py-1.5 rounded-lg font-black shadow-md">주문 동기화</button>
            </div>
        </nav>

        <main class="max-w-[1900px] mx-auto p-4">
            <!-- 품목별 합계 요약 섹션 -->
            <div class="bg-white p-4 rounded-xl border border-blue-200 shadow-sm mb-4">
                <h3 class="text-[12px] font-black text-blue-600 mb-3"><i class="fas fa-calculator mr-2"></i>현재 필터 결과 - 품목별 총 수량</h3>
                <div class="flex flex-wrap gap-2">
                    {% for name, total in item_sum.items() %}
                    <span class="summary-badge">{{ name }}: {{ total }}개</span>
                    {% else %}
                    <span class="text-slate-400 font-bold">집계할 데이터가 없습니다.</span>
                    {% endfor %}
                </div>
            </div>

            <div class="flex items-center justify-between mb-4 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
                <div class="flex gap-6">
                    <a href="/?status=all" class="{% if current_status=='all' %}tab-active{% endif %} pb-1">전체({{tasks|length}})</a>
                    <a href="/?status=대기" class="{% if current_status=='대기' %}tab-active{% endif %} pb-1 text-slate-400">대기/배정</a>
                    <a href="/?status=픽업" class="{% if current_status=='픽업' %}tab-active{% endif %} pb-1 text-orange-400">배송중</a>
                    <a href="/?status=완료" class="{% if current_status=='완료' %}tab-active{% endif %} pb-1 text-green-600">완료</a>
                </div>
                <div class="flex items-center gap-3">
                    <select onchange="location.href='/?category='+encodeURIComponent(this.value)" class="border rounded px-2 py-1 font-bold text-slate-500">
                        <option value="전체">카테고리 필터</option>
                        {% for sc in saved_cats %}<option value="{{sc}}" {% if current_cat == sc %}selected{% endif %}>{{sc}}</option>{% endfor %}
                    </select>
                    <div class="bg-blue-50 p-1 rounded-lg flex items-center gap-2 border border-blue-100">
                        <select id="bulk-driver" class="border rounded px-2 py-1 font-bold text-blue-600 bg-white">
                            <option value="">일괄배정 기사</option>
                            {% for d in drivers %}<option value="{{d.id}}">{{d.name}}</option>{% endfor %}
                        </select>
                        <button onclick="bulkAssign()" class="bg-blue-600 text-white px-4 py-1 rounded-lg font-black shadow-md">배정실행</button>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm overflow-auto border border-slate-200 max-h-[70vh]">
                <table class="w-full text-left excel-table">
                    <thead class="text-slate-400 font-black uppercase border-b bg-slate-50">
                        <tr>
                            <th class="w-10 text-center"><input type="checkbox" onclick="toggleAll()"></th>
                            <th class="w-20 text-center">상태</th>
                            <th class="w-28 text-center">카테고리</th>
                            <th class="w-80 text-blue-600 italic">배송지 주소</th>
                            <th class="w-32">고객명</th>
                            <th>상세 주문 내역</th>
                            <th class="w-40 text-center">배정기사</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        {% for t in tasks %}
                        <tr>
                            <td class="text-center"><input type="checkbox" class="task-check" value="{{t.id}}"></td>
                            <td class="text-center"><span class="px-1.5 py-0.5 rounded text-[9px] font-black {% if t.status == '픽업' %}bg-orange-100 text-orange-600{% elif t.status == '완료' %}bg-green-100 text-green-600{% else %}bg-slate-100 text-slate-400{% endif %}">{{ t.status }}</span></td>
                            <td class="text-center"><span class="bg-green-50 text-green-600 px-2 py-0.5 rounded-full font-black">{{ t.category }}</span></td>
                            <td class="font-black text-slate-800">{{ t.address }}</td>
                            <td class="font-black text-slate-900">{{ t.customer_name }}</td>
                            <td class="text-slate-500 font-medium">{{ t.product_details }}</td>
                           <td class="text-center font-black text-slate-600">
    {{ t.driver_name }}
    <div class="flex gap-1 justify-center mt-1">
        <a href="/cancel/{{t.id}}" class="text-[9px] bg-slate-200 px-1 rounded" title="재배정">재배정</a>
        <a href="/update_status/{{t.id}}/보류" class="text-[9px] bg-yellow-100 text-yellow-700 px-1 rounded">보류</a>
        <a href="/update_status/{{t.id}}/취소" class="text-[9px] bg-red-100 text-red-700 px-1 rounded">취소</a>
    </div>
</td>
                            
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </main>
        <script>
            async function syncNow() {
                const cat = document.getElementById('sync-cat').value;
                const res = await fetch('/sync?category=' + encodeURIComponent(cat));
                const data = await res.json();
                if(data.success) { alert(data.synced_count + "건 동기화 성공!"); location.reload(); }
                else { alert("오류: " + data.error); }
            }
            function toggleAll() { document.querySelectorAll('.task-check').forEach(i => i.checked = event.target.checked); }
            async function bulkAssign() {
                const driverId = document.getElementById('bulk-driver').value;
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(!driverId || selected.length === 0) return alert("기사와 항목을 선택하세요.");
                await fetch('/bulk/assign', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ task_ids: selected, driver_id: driverId })
                });
                location.reload();
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, tasks=tasks, drivers=drivers, main_cats=main_cats, saved_cats=saved_cats, current_status=st_filter, current_cat=cat_filter, item_sum=item_sum)

# 6. UI: 기사 전용 업무 페이지
@app.route('/work/<int:driver_id>')
def driver_work_page(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    tasks = DeliveryTask.query.filter(DeliveryTask.driver_id == driver_id, DeliveryTask.status != '완료').all()
    tasks.sort(key=lambda x: (x.address or "", extract_qty(x.product_details)), reverse=True)
    
    # [추가] 기사 본인의 품목별 합계 계산
    item_sum = get_item_summary(tasks)

    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>B.UNCLE 기사 - {{ driver_name }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
        body { font-family: 'Noto Sans KR', sans-serif; background-color: #0f172a; color: #e2e8f0; }
        .excel-table td { padding: 12px 10px; border-bottom: 1px solid #1e293b; word-break: keep-all; white-space: normal; }
        .excel-table th { padding: 12px 10px; background: #1e293b; position: sticky; top: 0; z-index: 10; }
        .summary-box { background: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 12px; margin-bottom: 16px; }
        </style>
    </head>
    <body class="p-2">
        <header class="flex justify-between items-center mb-4 px-2">
            <div>
                <h1 class="text-lg font-black text-green-500 italic">B.UNCLE DRIVER</h1>
                <p class="text-[10px] text-slate-500 font-bold">{{ driver_name }} 기사님 업무 현황</p>
            </div>
            <div class="flex gap-2">
                <button onclick="bulkPickup()" class="bg-blue-600 text-white px-4 py-2 rounded-lg font-black text-xs">일괄 픽업</button>
                <button onclick="location.reload()" class="bg-slate-800 text-slate-400 p-2 rounded-lg"><i class="fas fa-sync-alt"></i></button>
            </div>
        </header>

        <!-- 기사용 품목 합계 집계표 -->
        <div class="summary-box">
            <h3 class="text-xs font-black text-green-400 mb-2"><i class="fas fa-truck-loading mr-2"></i>오늘 상차/배송 총 수량</h3>
            <div class="flex flex-wrap gap-2">
                {% for name, total in item_sum.items() %}
                <span class="text-[11px] font-black bg-slate-900 border border-slate-700 px-3 py-1 rounded-full text-white">{{ name }}: {{ total }}개</span>
                {% else %}
                <span class="text-slate-500 text-[11px]">배정된 물량이 없습니다.</span>
                {% endfor %}
            </div>
        </div>

        <div class="bg-[#1e293b] rounded-xl overflow-hidden shadow-2xl border border-slate-800">
            <table class="w-full text-left excel-table text-[12px]">
                <thead>
                    <tr class="text-slate-400 text-[11px]">
                        <th class="w-10 text-center"><input type="checkbox" onclick="toggleAll()"></th>
                        <th class="w-16 text-center">상태</th>
                        <th class="w-56 text-green-400">배송지</th>
                        <th>품목/연락처</th>
                        <th class="w-20 text-center">완료</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800">
                    {% for t in tasks %}
                    <tr class="{% if t.status == '픽업' %}bg-blue-900/10{% endif %}">
                        <td class="text-center">{% if t.status == '대기' %}<input type="checkbox" class="task-check w-5 h-5" value="{{t.id}}">{% endif %}</td>
                        <td class="text-center"><span class="px-1.5 py-0.5 rounded text-[10px] font-black {% if t.status == '픽업' %}bg-orange-500 text-white{% else %}bg-slate-700 text-slate-400{% endif %}">{{ t.status }}</span></td>
                        <td class="font-black text-white text-[13px]">{{ t.address }}</td>
                        <td>
                            <p class="text-slate-400 mb-1">{{ t.product_details }}</p>
                            <div class="flex items-center gap-2"><span class="text-green-500 font-bold">{{ t.customer_name }}</span><a href="tel:{{t.phone}}" class="text-blue-400 underline">{{ t.phone }}</a></div>
                        </td>
                        <td class="text-center">
                            {% if t.status == '픽업' %}<button onclick="openCameraUI('{{t.id}}')" class="bg-green-600 text-white w-full py-3 rounded-lg font-black">완료</button>
                            {% else %}<span class="text-slate-600 font-bold">픽업전</span>{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <!-- 카메라 레이어 (기존과 동일) -->
        <div id="camera-layer" class="fixed inset-0 bg-black z-[100] hidden flex flex-col items-center justify-center p-6">
            <h3 class="text-green-500 font-black mb-4">현관 앞 사진 촬영</h3>
            <video id="video" class="w-full rounded-2xl bg-slate-900 mb-6" autoplay playsinline></video>
            <canvas id="canvas" class="hidden"></canvas>
            <div id="preview-box" class="hidden w-full mb-6"><img id="photo-preview" class="w-full rounded-2xl border-4 border-green-600 max-h-[60vh] object-contain mx-auto"></div>
            <div class="flex gap-4 w-full">
                <button id="capture-btn" class="flex-1 bg-white text-black py-4 rounded-2xl font-black text-lg">사진 촬영</button>
                <button id="confirm-btn" class="hidden flex-1 bg-green-600 text-white py-4 rounded-2xl font-black text-lg">완료 확정</button>
                <button id="cancel-camera" class="flex-1 bg-slate-800 text-white py-4 rounded-2xl font-bold">닫기</button>
            </div>
        </div>

        <script>
            let currentTaskId = null; let stream = null;
            function toggleAll(){ document.querySelectorAll('.task-check').forEach(i => i.checked = event.target.checked); }
            async function bulkPickup(){
                const selected = Array.from(document.querySelectorAll('.task-check:checked')).map(c => c.value);
                if(selected.length === 0) return alert("선택된 항목이 없습니다.");
                await fetch('/bulk/pickup', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ task_ids: selected }) });
                location.reload();
            }
            async function openCameraUI(tid){
                currentTaskId = tid; document.getElementById('camera-layer').classList.remove('hidden');
                try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); document.getElementById('video').srcObject = stream; } 
                catch (e) { alert("카메라 권한이 필요합니다."); }
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
                await fetch('/complete_action/' + currentTaskId, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ photo: photo }) });
                if(stream) stream.getTracks().forEach(t => t.stop()); location.reload();
            };
            document.getElementById('cancel-camera').onclick = () => { if(stream) stream.getTracks().forEach(t => t.stop()); document.getElementById('camera-layer').classList.add('hidden'); };
        </script>
    </body>
    </html>
    """
    return render_template_string(html, tasks=tasks, driver_name=driver.name, driver_id=driver_id, item_sum=item_sum)

# 7. 기사 관리 UI
@app.route('/drivers')
def driver_mgmt():
    drivers = Driver.query.all(); base_url = request.host_url.rstrip('/')
    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head><meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script><link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet"></head>
    <body class="bg-slate-50 text-sm">
        <nav class="bg-white border-b h-14 flex items-center px-6 gap-6">
            <h1 class="text-lg font-black text-green-600">B.UNCLE LOGI</h1>
            <a href="/" class="font-bold text-gray-400">배송통제</a><a href="/drivers" class="font-bold text-green-600 border-b-2 border-green-600 h-full flex items-center">기사관리</a>
        </nav>
        <div class="max-w-2xl mx-auto p-6">
            <div class="bg-white p-8 rounded-3xl shadow-sm border mb-8">
                <h2 class="font-black mb-4">신규 기사님 등록</h2>
                <form action="/driver/add" method="POST" class="flex gap-2">
                    <input name="name" placeholder="이름" class="flex-1 border p-3 rounded-xl font-bold" required>
                    <input name="phone" placeholder="연락처" class="flex-1 border p-3 rounded-xl font-bold" required>
                    <button class="bg-green-600 text-white px-8 py-3 rounded-xl font-black">등록</button>
                </form>
            </div>
            <div class="grid gap-3">
                {% for d in drivers %}
                <div class="bg-white p-5 rounded-2xl border flex justify-between items-center">
                    <span class="font-black text-lg text-slate-700">{{ d.name }} <span class="text-slate-300 text-xs ml-2">{{ d.phone }}</span></span>
                    <div class="flex gap-2"><button onclick="copyLink('{{base_url}}/work/{{d.id}}')" class="bg-blue-50 text-blue-600 px-3 py-1.5 rounded-lg font-black text-[10px]">링크복사</button>
                    <a href="/driver/delete/{{d.id}}" class="text-red-300 p-2"><i class="fas fa-trash-alt"></i></a></div>
                </div>
                {% endfor %}
            </div>
        </div>
        <script>function copyLink(url){ const t = document.createElement("input"); t.value=url; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t); alert("업무 링크 복사완료!"); }</script>
    </body>
    </html>
    """
    return render_template_string(html, drivers=drivers, base_url=base_url)

# 8. 핵심 로직 처리
@app.route('/sync')
def sync_orders():
    if not os.path.exists(MAIN_DB_PATH): return jsonify({"success": False, "error": "DB 못찾음"})
    sel_cat = request.args.get('category', '전체')
    try:
        conn = sqlite3.connect(MAIN_DB_PATH); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
        cursor.execute("SELECT * FROM \"order\" WHERE status = '결제완료'")
        count = 0
        for row in cursor.fetchall():
            for block in row['product_details'].split(' | '):
                match = re.search(r'\[(.*?)\]', block)
                if match:
                    cat = match.group(1).strip()
                    if sel_cat != '전체' and sel_cat != cat: continue
                    exists = DeliveryTask.query.filter_by(order_id=row['order_id'], category=cat).first()
                    if not exists:
                        db_delivery.session.add(DeliveryTask(order_id=row['order_id'], customer_name=row['customer_name'], phone=row['customer_phone'], address=row['delivery_address'], memo=row['request_memo'], category=cat, product_details=block.strip()))
                        count += 1
        db_delivery.session.commit(); conn.close()
        return jsonify({"success": True, "synced_count": count})
    except Exception as e: return jsonify({"success": False, "error": str(e)})

@app.route('/bulk/assign', methods=['POST'])
def bulk_assign():
    data = request.json; d = Driver.query.get(data.get('driver_id'))
    if d:
        for tid in data.get('task_ids'):
            t = DeliveryTask.query.get(tid)
            if t and t.status == '대기': t.driver_id, t.driver_name = d.id, d.name
        db_delivery.session.commit()
    return jsonify({"success": True})

@app.route('/bulk/pickup', methods=['POST'])
def bulk_pickup():
    data = request.json
    for tid in data.get('task_ids'):
        t = DeliveryTask.query.get(tid)
        if t and t.status == '대기': t.status, t.pickup_at = '픽업', datetime.now()
    db_delivery.session.commit()
    return jsonify({"success": True})

@app.route('/complete_action/<int:tid>', methods=['POST'])
def complete_action(tid):
    t = DeliveryTask.query.get(tid); d = request.json
    if t:
        t.status, t.completed_at, t.photo_data = '완료', datetime.now(), d.get('photo')
        db_delivery.session.commit(); send_delivery_complete_msg(t)
    return jsonify({"success": True})

@app.route('/driver/add', methods=['POST'])
def add_driver():
    db_delivery.session.add(Driver(name=request.form['name'], phone=request.form['phone']))
    db_delivery.session.commit(); return redirect('/drivers')

@app.route('/driver/delete/<int:did>')
def delete_driver(did):
    Driver.query.filter_by(id=did).delete(); db_delivery.session.commit(); return redirect('/drivers')

# [8. 핵심 로직 처리 구역 - cancel_assignment 수정 및 상태 변경 추가]

@app.route('/cancel/<int:tid>')
def cancel_assignment(tid):
    t = DeliveryTask.query.get(tid)
    # 기존: 미배정/대기로 복구 (픽업 후에도 재배정 가능하도록 수정 금지 규칙 하에 로직만 확장)
    if t:
        t.driver_id, t.driver_name, t.status = None, '미배정', '대기'
        t.pickup_at = None # 픽업 시간 초기화
        db_delivery.session.commit()
    return redirect(request.referrer or '/')

@app.route('/update_status/<int:tid>/<string:new_status>')
def update_task_status(tid, new_status):
    # 보류, 취소 등 상태 강제 변경 기능
    t = DeliveryTask.query.get(tid)
    if t:
        t.status = new_status
        db_delivery.session.commit()
    return redirect(request.referrer or '/')

def patch_db():
    with app.app_context():
        db_delivery.create_all()
        cols = [("delivery_task", "category", "VARCHAR(100)"), ("delivery_task", "driver_name", "VARCHAR(50)"), ("delivery_task", "completed_at", "DATETIME"), ("delivery_task", "photo_data", "TEXT"), ("delivery_task", "pickup_at", "DATETIME")]
        for table, col, ctype in cols:
            try: db_delivery.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")); db_delivery.session.commit()
            except: db_delivery.session.rollback()

if __name__ == "__main__":
    patch_db()
    print("--- 바구니삼촌 고밀도 엑셀형 배송시스템 가동 (포트 5001) ---")
    app.run(host="0.0.0.0", port=5001, debug=True)