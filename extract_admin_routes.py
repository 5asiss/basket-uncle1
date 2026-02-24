# -*- coding: utf-8 -*-
"""Extract admin route blocks from app.py. Run once to generate admin_routes_content.txt"""
import re

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find all @app.route('/admin...') and the function that follows until next @app.route
blocks = []
i = 0
while i < len(lines):
        # Find the end: next @app.route (any) at column 0
    line = lines[i]
    if re.match(r"@app\.route\s*\(\s*['\"]\/admin", line):
        start = i
        j = i + 1
        while j < len(lines):
            if re.match(r"^@app\.route\s*\(", lines[j]):
                break
            j += 1
        end = j
        chunk = lines[start:end]
        # If this block contains admin_dashboard (no route above it), split: before dashboard + dashboard with routes
        dash_idx = None
        for k, ln in enumerate(chunk):
            if re.search(r"def admin_dashboard\s*\(", ln):
                dash_idx = k
                break
        if dash_idx is not None:
            # Include @login_required in admin_dashboard block: find its line index
            dash_start = dash_idx
            while dash_start > 0 and not re.match(r"^@login_required", chunk[dash_start]):
                dash_start -= 1
            if dash_start >= 0:
                blocks.append((start, start + dash_start, chunk[:dash_start]))
                dash_block = ["@admin_bp.route('/admin')\n", "@admin_bp.route('/admin/')\n"] + chunk[dash_start:]
                blocks.append((start + dash_start, end, dash_block))
                i = end
                continue
        blocks.append((start, end, chunk))
        i = end
    else:
        i += 1

print(f"Found {len(blocks)} admin route blocks")
for idx, (s, e, block) in enumerate(blocks):
    first = block[0].strip()[:60]
    print(f"  Block {idx+1}: lines {s+1}-{e} ({e-s} lines) {first}...")

# Write concatenated blocks for admin_routes (with @app.route -> @admin_bp.route)
out_lines = []
for _, _, block in blocks:
    for line in block:
        new_line = line.replace('@app.route(', '@admin_bp.route(')
        # HEADER_HTML -> _header_html(), FOOTER_HTML -> _footer_html()
        new_line = re.sub(r'\bHEADER_HTML\b', '_header_html()', new_line)
        new_line = re.sub(r'\bFOOTER_HTML\b', '_footer_html()', new_line)
        out_lines.append(new_line)

with open('admin_routes_content.txt', 'w', encoding='utf-8') as out:
    out.writelines(out_lines)
print(f"Written {len(out_lines)} lines to admin_routes_content.txt")
