import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sdk_python_v4.sdk import SolapiMsgV4 # 알림톡 라이브러리

# 1. 초기 설정
app = Flask(__name__)
app.secret_key = "delivery_secret_key_1234"

# 데이터베이스 경로 설정 (내 컴퓨터 폴더 내에서 실행하기 위해 절대경로 확보)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 메인 쇼핑몰 DB (반드시 같은 폴더에 이 파일이 있어야 합니다)
MAIN_DB_PATH = os.path.join(BASE_DIR, 'direct_trade_mall.db')
# 배송 전용 DB (자동 생성됨)
DELIVERY_DB_PATH = os.path.join(BASE_DIR, 'delivery.db')

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DELIVERY_DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db_delivery = SQLAlchemy(app)

# 2. 알림톡 API 설정 (사장님 계정 정보 입력)
SOLAPI_API_KEY = "여기에_API_KEY_입력"
SOLAPI_API_SECRET = "여기에_API_SECRET_입력"
PFID = "여기에_발신프로필ID_입력"
TEMPLATE_ID = "여기에_템플릿ID_입력"

# 3. 배송 관리 DB 모델
class DeliveryTask(db_delivery.Model):
    id = db_delivery.Column(db_delivery.Integer, primary_key=True)
    order_id = db_delivery.Column(db_delivery.String(100), unique=True)
    customer_name = db_delivery.Column(db_delivery.String(50))
    phone = db_delivery.Column(db_delivery.String(20))
    address = db_delivery.Column(db_delivery.String(500))
    memo = db_delivery.Column(db_delivery.String(500))
    product_details = db_delivery.Column(db_delivery.Text)
    
    # 관리용 컬럼
    driver_name = db_delivery.Column(db_delivery.String(50), default="미배정")
    status = db_delivery.Column(db_delivery.String(20), default="대기") # 대기 -> 배송중 -> 완료
    alimtalk_sent = db_delivery.Column(db_delivery.Boolean, default=False)
    created_at = db_delivery.Column(db_delivery.DateTime, default=datetime.now)

# 4. 알림톡 발송 함수
def send_alimtalk(task):
    """솔라피를 이용한 알림톡 발송"""
    # API 키가 입력되지 않았으면 테스트 모드로 시뮬레이션
    if "입력" in SOLAPI_API_KEY:
        print(f"[알림톡 시뮬레이션] {task.customer_name}님 ({task.phone})")
        print(f"내용: {task.address}로 배송 예정입니다.")
        return True

    solapi = SolapiMsgV4(SOLAPI_API_KEY, SOLAPI_API_SECRET)
    message = {
        'to': task.phone.replace('-', ''),
        'from': '16668320', # 등록된 발신번호
        'kakaoOptions': {
            'pfId': PFID,
            'templateId': TEMPLATE_ID,
            'variables': {
                '#{이름}': task.customer_name,
                '#{주소}': task.address,
                '#{상품}': task.product_details[:20] + "..."
            }
        }
    }
    try:
        solapi.send_one(message)
        return True
    except Exception as e:
        print(f"알림톡 발송 에러: {e}")
        return False

# 5. DB 동기화 엔진 (메인 DB -> 배송 DB)
@app.route('/sync')
def sync_orders():
    """메인 DB에서 결제완료 건을 긁어와서 배송 DB에 넣고 알림톡 발송"""
    if not os.path.exists(MAIN_DB_PATH):
        return jsonify({"success": False, "error": "메인 DB(direct_trade_mall.db) 파일이 폴더에 없습니다."})

    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 메인 DB의 'order' 테이블에서 결제완료 건 조회
        cursor.execute("SELECT * FROM \"order\" WHERE status = '결제완료'")
        main_orders = cursor.fetchall()
        
        count = 0
        for row in main_orders:
            exists = DeliveryTask.query.filter_by(order_id=row['order_id']).first()
            if not exists:
                new_task = DeliveryTask(
                    order_id=row['order_id'],
                    customer_name=row['customer_name'],
                    phone=row['customer_phone'],
                    address=row['delivery_address'],
                    memo=row['request_memo'],
                    product_details=row['product_details']
                )
                db_delivery.session.add(new_task)
                db_delivery.session.commit()
                
                # 등록 즉시 알림톡 발송
                if send_alimtalk(new_task):
                    new_task.alimtalk_sent = True
                    db_delivery.session.commit()
                count += 1
        
        conn.close()
        return jsonify({"success": True, "synced_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# 6. 기사용 배송 관리 화면
@app.route('/')
def driver_dashboard():
    tasks = DeliveryTask.query.filter(DeliveryTask.status != '완료').order_by(DeliveryTask.address.asc()).all()
    
    html = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>바구니삼촌 기사님 페이지</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            body { background-color: #f8fafc; font-family: 'Noto Sans KR', sans-serif; }
            .task-card { background: white; border-radius: 1.5rem; transition: transform 0.2s; }
            .task-card:active { transform: scale(0.98); }
        </style>
    </head>
    <body class="p-4 md:p-8">
        <div class="max-w-md mx-auto">
            <header class="flex justify-between items-center mb-6">
                <div>
                    <h1 class="text-2xl font-black text-green-600 italic">B.UNCLE LOGI</h1>
                    <p class="text-[10px] text-gray-400 font-bold uppercase tracking-widest">Delivery Management</p>
                </div>
                <button onclick="location.reload()" class="bg-white w-10 h-10 rounded-full shadow-sm flex items-center justify-center text-gray-400 hover:text-green-600">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </header>

            <div class="mb-6">
                <button onclick="syncNow()" class="w-full bg-blue-600 text-white py-5 rounded-2xl font-black shadow-xl hover:bg-blue-700 active:scale-95 transition-all flex items-center justify-center gap-3">
                    <i class="fas fa-cloud-download-alt"></i> 새 주문 동기화
                </button>
            </div>

            <div class="space-y-4">
                {% for t in tasks %}
                <div class="task-card p-6 border border-gray-100 shadow-sm relative overflow-hidden">
                    <div class="absolute top-0 left-0 w-2 h-full {% if t.status == '배송중' %}bg-orange-500{% else %}bg-gray-200{% endif %}"></div>
                    
                    <div class="flex justify-between items-start mb-4">
                        <span class="text-[10px] bg-gray-100 px-2 py-1 rounded-md text-gray-500 font-bold">No.{{ t.id }}</span>
                        <span class="text-xs font-black {% if t.status == '배송중' %}text-orange-600{% else %}text-gray-400{% endif %}">{{ t.status }}</span>
                    </div>
                    
                    <h3 class="text-lg font-black text-gray-800 mb-2 leading-tight">{{ t.address }}</h3>
                    <div class="flex items-center gap-2 mb-4">
                        <p class="text-green-600 font-black text-sm">{{ t.customer_name }}</p>
                        <span class="text-gray-300">|</span>
                        <p class="text-gray-500 font-bold text-sm">{{ t.phone }}</p>
                    </div>
                    
                    <div class="bg-gray-50 p-4 rounded-xl text-xs text-gray-500 mb-5 leading-relaxed">
                        <p class="font-black text-gray-700 mb-2 flex items-center gap-1"><i class="fas fa-shopping-basket text-green-500"></i> 장보기 목록</p>
                        {{ t.product_details }}
                    </div>

                    <div class="flex gap-2">
                        {% if t.status == '대기' %}
                        <a href="/status/{{t.id}}/배송중" class="flex-1 bg-orange-500 text-white py-4 rounded-xl font-black text-center shadow-lg shadow-orange-100">배송 시작</a>
                        {% elif t.status == '배송중' %}
                        <a href="/status/{{t.id}}/완료" class="flex-1 bg-green-600 text-white py-4 rounded-xl font-black text-center shadow-lg shadow-green-100">배송 완료</a>
                        {% endif %}
                        <a href="tel:{{t.phone}}" class="w-14 bg-gray-900 text-white rounded-xl flex items-center justify-center shadow-lg"><i class="fas fa-phone-alt text-lg"></i></a>
                    </div>
                </div>
                {% endfor %}
            </div>
            
            {% if not tasks %}
            <div class="py-32 text-center text-gray-300">
                <i class="fas fa-truck-loading text-5xl mb-4 opacity-20"></i>
                <p class="font-black">배송할 물량이 없습니다.</p>
                <p class="text-[11px] mt-2">새 주문 동기화 버튼을 눌러보세요.</p>
            </div>
            {% endif %}
        </div>

        <script>
            async function syncNow() {
                const btn = event.currentTarget;
                btn.disabled = true;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 동기화 중...';
                
                try {
                    const res = await fetch('/sync');
                    const data = await res.json();
                    if(data.success) {
                        alert(data.synced_count + "건의 신규 배송건이 추가되었습니다.");
                        location.reload();
                    } else {
                        alert("에러: " + data.error);
                    }
                } catch(e) {
                    alert("서버 연결에 실패했습니다.");
                } finally {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-cloud-download-alt"></i> 새 주문 동기화';
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, tasks=tasks)

@app.route('/status/<int:tid>/<string:stat>')
def update_status(tid, stat):
    task = DeliveryTask.query.get(tid)
    if task:
        task.status = stat
        db_delivery.session.commit()
    return redirect('/')

# 7. DB 초기화 및 실행
if __name__ == "__main__":
    with app.app_context():
        # delivery.db가 없으면 새로 생성합니다.
        db_delivery.create_all()
    # 로컬 확인을 위해 5001번 포트로 실행
    app.run(host="0.0.0.0", port=5001, debug=True)