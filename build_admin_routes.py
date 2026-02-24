# -*- coding: utf-8 -*-
"""Build admin_routes.py from header + admin_routes_content.txt"""
header = '''# -*- coding: utf-8 -*-
"""Admin routes - extracted from app.py to reduce main file size."""
from __future__ import annotations

import os
import base64
import json
from datetime import datetime

import requests
from flask import (
    Blueprint, request, redirect, url_for, render_template_string,
    flash, jsonify, current_app, send_file,
)
from flask_login import login_required, current_user

# Import app after it is fully loaded (app.py imports this module at the end)
from app import (
    db,
    send_message,
    get_template_content,
    check_admin_permission,
    _get_point_config,
    _get_member_grade_config,
    _get_user_total_paid,
    save_uploaded_file,
    is_address_in_delivery_zone,
    get_delivery_zone_type,
    get_quick_extra_config,
    categories_for_member_grade,
    _is_allowed_image_filename,
    _recalc_order_from_items,
    _save_delivery_proof_image,
    apply_points_on_delivery_complete,
)
from config import TOSS_SECRET_KEY
from models import (
    CategorySettlement, User, Category, Product, Cart, Order, OrderItem, OrderItemLog,
    UserMessage, MessageTemplate, PushSubscription, RestaurantRequest, RestaurantRecommend,
    RestaurantVote, PartnershipInquiry, FreeBoard, DeliveryRequest, DeliveryRequestVote,
    DailyStat, SellerOrderConfirmation, EmailOrderLineStatus, SitePopup, DeliveryZone,
    MemberGradeConfig, PointConfig, PointLog, MarketingCost, Review, UserConsent, Settlement,
)
from werkzeug.utils import secure_filename

admin_bp = Blueprint("admin", __name__)


def _header_html():
    return current_app.config.get("ADMIN_HEADER_HTML", "")


def _footer_html():
    return current_app.config.get("ADMIN_FOOTER_HTML", "")


# ALLOWED_IMAGE_EXTENSIONS used in admin content
ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# --------------------------------------------------------------------------------
# Admin route handlers (body from admin_routes_content.txt)
# --------------------------------------------------------------------------------

'''

with open('admin_routes_content.txt', 'r', encoding='utf-8') as f:
    content = f.read()

with open('admin_routes.py', 'w', encoding='utf-8') as out:
    out.write(header)
    out.write(content)

print('Written admin_routes.py')
