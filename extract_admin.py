# -*- coding: utf-8 -*-
"""Extract admin route line numbers from app.py."""
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "@app.route('/admin" in line or (i >= 1 and 'def admin_' in line):
        print(i + 1, line.rstrip()[:90])
