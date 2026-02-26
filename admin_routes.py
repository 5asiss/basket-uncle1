# -------------------------------------------------------------------------------
# 관리자(admin) 라우트 등록 모듈 - app.py 경량화
# app.py에서 register_admin_routes(app) 호출로 등록
# -------------------------------------------------------------------------------
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='')


def register_admin_routes(app):
    """app이 완전히 로드된 뒤 호출. admin 뷰 함수를 app에서 가져와 Blueprint로 등록."""
    # 이미 등록된 경우(순환 import로 인한 재호출) add_url_rule 방지
    if 'admin' in app.blueprints:
        return
    from flask_login import login_required
    from app import (
        admin_logi_redirect,
        admin_settlement_complete,
        admin_settlement_order_status,
        admin_settlement_toss_payment,
        admin_settlement_item_status,
        admin_settlement_bulk_item_status,
        admin_messages_send,
        admin_messages_template,
        admin_popup_save,
        admin_popup_delete,
        admin_popup_upload,
        admin_order_print,
        admin_auth_status,
        admin_bulk_request_delivery,
        admin_order_item_status,
        admin_order_items,
        admin_settle_order,
        admin_delivery_zone_api,
        admin_member_grade_set,
        admin_member_grade_config,
        admin_member_grade_auto_apply,
        admin_point_config,
        admin_point_adjust,
        admin_point_log,
        admin_member_send_message,
        admin_member_delete,
        admin_dashboard,
        admin_product_bulk_upload_template,
        admin_product_bulk_upload,
        admin_restaurant_request_comment,
        admin_restaurant_request_hide,
        admin_restaurant_request_notice_toggle,
        admin_restaurant_request_notice_write,
        admin_delivery_request_comment,
        admin_delivery_request_hide,
        admin_delivery_request_notice_toggle,
        admin_delivery_request_notice_write,
        admin_partnership_comment,
        admin_partnership_hide,
        admin_partnership_notice_toggle,
        admin_partnership_notice_write,
        admin_email_setup,
        admin_seller_order_preview,
        admin_seller_send_manual_email,
        admin_seller_send_order_email,
        admin_backup_run,
        admin_backup_cron,
        admin_review_delete,
        admin_board_comment_delete,
        admin_seed_test_data,
        admin_delete_test_data,
        admin_seed_virtual_reviews,
        admin_seed_virtual_orders,
        admin_seed_virtual_payment_orders,
        admin_seed_virtual_board_data,
        admin_product_add,
        admin_product_edit,
        admin_delete,
        admin_category_add,
        admin_category_edit,
        admin_category_move,
        admin_category_delete,
        admin_delete_products_by_category,
        admin_sellers_excel,
        admin_orders_sales_excel,
        admin_orders_sales_detail_image,
        admin_orders_delivery_summary_image,
        admin_orders_sales_summary_excel,
        admin_orders_sales_summary_image,
        admin_orders_settlement_detail_excel,
        admin_settlement_category_excel,
        admin_orders_excel,
        admin_revenue_report_download,
    )

    # /admin/logi
    admin_bp.add_url_rule('/admin/logi', view_func=admin_logi_redirect)
    admin_bp.add_url_rule('/admin/logi/', view_func=admin_logi_redirect)

    # settlement
    admin_bp.add_url_rule('/admin/settlement/complete', view_func=login_required(admin_settlement_complete), methods=['POST'])
    admin_bp.add_url_rule('/admin/settlement/order_status', view_func=login_required(admin_settlement_order_status), methods=['POST'])
    admin_bp.add_url_rule('/admin/settlement/toss_payment', view_func=login_required(admin_settlement_toss_payment), methods=['GET'])
    admin_bp.add_url_rule('/admin/settlement/item_status', view_func=login_required(admin_settlement_item_status), methods=['POST'])
    admin_bp.add_url_rule('/admin/settlement/bulk_item_status', view_func=login_required(admin_settlement_bulk_item_status), methods=['POST'])

    # messages
    admin_bp.add_url_rule('/admin/messages/send', view_func=login_required(admin_messages_send), methods=['POST'])
    admin_bp.add_url_rule('/admin/messages/template', view_func=login_required(admin_messages_template), methods=['POST'])

    # popup
    admin_bp.add_url_rule('/admin/popup/save', view_func=login_required(admin_popup_save), methods=['POST'])
    admin_bp.add_url_rule('/admin/popup/delete/<int:pid>', view_func=login_required(admin_popup_delete), methods=['POST'])
    admin_bp.add_url_rule('/admin/popup/upload', view_func=login_required(admin_popup_upload), methods=['POST'])

    # order
    admin_bp.add_url_rule('/admin/order/print', view_func=login_required(admin_order_print))
    admin_bp.add_url_rule('/admin/order/bulk_request_delivery', view_func=login_required(admin_bulk_request_delivery), methods=['POST'])
    admin_bp.add_url_rule('/admin/order/item_status', view_func=login_required(admin_order_item_status), methods=['POST'])
    admin_bp.add_url_rule('/admin/order/<int:order_id>/items', view_func=login_required(admin_order_items))
    admin_bp.add_url_rule('/admin/order/<int:order_id>/settle', view_func=login_required(admin_settle_order))

    # auth
    admin_bp.add_url_rule('/admin/auth-status', view_func=admin_auth_status)

    # delivery_zone
    admin_bp.add_url_rule('/admin/delivery_zone/api', view_func=login_required(admin_delivery_zone_api), methods=['GET', 'POST'])

    # member_grade
    admin_bp.add_url_rule('/admin/member_grade/set', view_func=login_required(admin_member_grade_set), methods=['POST'])
    admin_bp.add_url_rule('/admin/member_grade/config', view_func=login_required(admin_member_grade_config), methods=['POST'])
    admin_bp.add_url_rule('/admin/member_grade/auto_apply', view_func=login_required(admin_member_grade_auto_apply), methods=['POST'])

    # point
    admin_bp.add_url_rule('/admin/point/config', view_func=login_required(admin_point_config), methods=['POST'])
    admin_bp.add_url_rule('/admin/point/adjust', view_func=login_required(admin_point_adjust), methods=['POST'])
    admin_bp.add_url_rule('/admin/point/log', view_func=login_required(admin_point_log))

    # api member
    admin_bp.add_url_rule('/admin/api/member/<int:uid>/message', view_func=login_required(admin_member_send_message), methods=['POST'])
    admin_bp.add_url_rule('/admin/api/member/<int:uid>/delete', view_func=login_required(admin_member_delete), methods=['POST'])

    # 수익통계 리포트 다운로드 (catch-all 전에 등록)
    admin_bp.add_url_rule('/admin/revenue_report/download', view_func=login_required(admin_revenue_report_download))

    # 대시보드: /admin, /admin/, /admin/<path> (나머지는 위의 구체 라우트가 처리)
    def _admin_dashboard_with_path(path=''):
        return admin_dashboard()
    admin_bp.add_url_rule('/admin', view_func=login_required(admin_dashboard), endpoint='admin_dashboard')
    admin_bp.add_url_rule('/admin/', view_func=login_required(admin_dashboard), endpoint='admin_dashboard_slash')
    admin_bp.add_url_rule('/admin/<path:path>', view_func=login_required(_admin_dashboard_with_path), endpoint='admin_dashboard_path')

    # product bulk
    admin_bp.add_url_rule('/admin/product/bulk_upload_template', view_func=login_required(admin_product_bulk_upload_template))
    admin_bp.add_url_rule('/admin/product/bulk_upload', view_func=login_required(admin_product_bulk_upload), methods=['POST'])

    # board
    admin_bp.add_url_rule('/admin/board/restaurant-request/<int:rid>/comment', view_func=login_required(admin_restaurant_request_comment), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/restaurant-request/<int:rid>/hide', view_func=login_required(admin_restaurant_request_hide), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/restaurant-request/<int:rid>/notice', view_func=login_required(admin_restaurant_request_notice_toggle), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/restaurant-request/notice/write', view_func=login_required(admin_restaurant_request_notice_write), methods=['GET', 'POST'])
    # app.py에 @app.route 없이 정의된 배송요청 뷰 (폼에서 /admin/board/delivery-request/... 호출)
    admin_bp.add_url_rule('/admin/board/delivery-request/<int:did>/comment', view_func=login_required(admin_delivery_request_comment), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/delivery-request/<int:did>/hide', view_func=login_required(admin_delivery_request_hide), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/delivery-request/<int:did>/notice', view_func=login_required(admin_delivery_request_notice_toggle), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/delivery-request/notice/write', view_func=login_required(admin_delivery_request_notice_write), methods=['GET', 'POST'])
    admin_bp.add_url_rule('/admin/board/partnership/<int:pid>/comment', view_func=login_required(admin_partnership_comment), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/partnership/<int:pid>/hide', view_func=login_required(admin_partnership_hide), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/partnership/<int:pid>/notice', view_func=login_required(admin_partnership_notice_toggle), methods=['POST'])
    admin_bp.add_url_rule('/admin/board/partnership/notice/write', view_func=login_required(admin_partnership_notice_write), methods=['GET', 'POST'])

    # email / seller
    admin_bp.add_url_rule('/admin/email_setup', view_func=login_required(admin_email_setup))
    admin_bp.add_url_rule('/admin/seller/order_preview', view_func=login_required(admin_seller_order_preview))
    admin_bp.add_url_rule('/admin/seller/send_manual_email', view_func=login_required(admin_seller_send_manual_email), methods=['POST'])
    admin_bp.add_url_rule('/admin/seller/send_order_email', view_func=login_required(admin_seller_send_order_email), methods=['POST'])

    # backup
    admin_bp.add_url_rule('/admin/backup/run', view_func=login_required(admin_backup_run), methods=['POST'])
    admin_bp.add_url_rule('/admin/backup/cron', view_func=admin_backup_cron)

    # review
    admin_bp.add_url_rule('/admin/review/delete/<int:rid>', view_func=login_required(admin_review_delete))
    # board comment
    admin_bp.add_url_rule('/admin/board/comment/delete/<int:cid>', view_func=login_required(admin_board_comment_delete), methods=['POST'])

    # seed / test
    admin_bp.add_url_rule('/admin/seed_test_data', view_func=login_required(admin_seed_test_data))
    admin_bp.add_url_rule('/admin/delete_test_data', view_func=login_required(admin_delete_test_data))
    admin_bp.add_url_rule('/admin/seed_virtual_reviews', view_func=login_required(admin_seed_virtual_reviews))
    admin_bp.add_url_rule('/admin/seed_virtual_orders', view_func=login_required(admin_seed_virtual_orders))
    admin_bp.add_url_rule('/admin/seed_virtual_payment_orders', view_func=login_required(admin_seed_virtual_payment_orders))
    admin_bp.add_url_rule('/admin/seed_virtual_board_data', view_func=login_required(admin_seed_virtual_board_data))

    # product crud
    admin_bp.add_url_rule('/admin/add', view_func=login_required(admin_product_add), methods=['GET', 'POST'])
    admin_bp.add_url_rule('/admin/edit/<int:pid>', view_func=login_required(admin_product_edit), methods=['GET', 'POST'])
    admin_bp.add_url_rule('/admin/delete/<int:pid>', view_func=login_required(admin_delete))

    # category
    admin_bp.add_url_rule('/admin/category/add', view_func=login_required(admin_category_add), methods=['POST'])
    admin_bp.add_url_rule('/admin/category/edit/<int:cid>', view_func=login_required(admin_category_edit), methods=['GET', 'POST'])
    admin_bp.add_url_rule('/admin/category/move/<int:cid>/<string:direction>', view_func=login_required(admin_category_move))
    admin_bp.add_url_rule('/admin/category/delete/<int:cid>', view_func=login_required(admin_category_delete))
    admin_bp.add_url_rule('/admin/category/delete_products', view_func=login_required(admin_delete_products_by_category))

    # excel
    admin_bp.add_url_rule('/admin/sellers/excel', view_func=login_required(admin_sellers_excel))
    admin_bp.add_url_rule('/admin/orders/sales_excel', view_func=login_required(admin_orders_sales_excel))
    admin_bp.add_url_rule('/admin/orders/sales_detail_image', view_func=login_required(admin_orders_sales_detail_image))
    admin_bp.add_url_rule('/admin/orders/delivery_summary_image', view_func=login_required(admin_orders_delivery_summary_image))
    admin_bp.add_url_rule('/admin/orders/sales_summary_excel', view_func=login_required(admin_orders_sales_summary_excel))
    admin_bp.add_url_rule('/admin/orders/sales_summary_image', view_func=login_required(admin_orders_sales_summary_image))
    admin_bp.add_url_rule('/admin/orders/settlement_detail_excel', view_func=login_required(admin_orders_settlement_detail_excel))
    admin_bp.add_url_rule('/admin/settlement/category_excel', view_func=login_required(admin_settlement_category_excel))
    admin_bp.add_url_rule('/admin/orders/excel', view_func=login_required(admin_orders_excel))

    app.register_blueprint(admin_bp)
