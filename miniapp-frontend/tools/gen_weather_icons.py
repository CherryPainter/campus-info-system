#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成小程序天气图标 PNG（替代 emoji，跨设备渲染一致）。
输出到 src/assets/weather/，文件名为天气图标键（sun/cloud/...）。
用 Pillow 绘制，256 绘制后降采样到 128 抗锯齿。
"""
import math
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "src", "assets", "weather")
os.makedirs(OUT, exist_ok=True)

S = 256  # 绘制分辨率（2x），最终降采样到 128


def new_canvas():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def draw_sun(draw, cx, cy, r, color):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    for i in range(12):
        a = math.radians(i * 30)
        r1 = r + 12
        r2 = r + 30
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        x2, y2 = cx + r2 * math.cos(a), cy + r2 * math.sin(a)
        draw.line([x1, y1, x2, y2], fill=color, width=12)


def draw_cloud(draw, cx, cy, scale, color):
    parts = [
        (cx - 60 * scale, cy + 6 * scale, 42 * scale, 36 * scale),
        (cx - 18 * scale, cy - 20 * scale, 54 * scale, 48 * scale),
        (cx + 36 * scale, cy - 8 * scale, 46 * scale, 42 * scale),
        (cx + 6 * scale, cy + 20 * scale, 74 * scale, 38 * scale),
    ]
    for (x, y, rx, ry) in parts:
        draw.ellipse([x - rx, y - ry, x + rx, y + ry], fill=color)
    draw.rectangle([cx - 80 * scale, cy + 18 * scale, cx + 80 * scale, cy + 42 * scale], fill=color)


def draw_drops(draw, cx, top, n, color, thick=10):
    gap = 150 / max(n, 1)
    for i in range(n):
        x = cx - (n - 1) * gap / 2 + i * gap
        draw.line([x, top, x, top + 46], fill=color, width=thick, joint="curve")


def draw_snow(draw, cx, top, n):
    gap = 150 / max(n, 1)
    for i in range(n):
        x = cx - (n - 1) * gap / 2 + i * gap
        draw.ellipse([x - 9, top, x + 9, top + 18], fill="#E1F5FE", outline="#81D4FA", width=4)


def bolt(draw, cx, top, color):
    pts = [
        (cx - 6, top),
        (cx - 26, top + 60),
        (cx - 4, top + 60),
        (cx + 8, top + 120),
        (cx - 30, top + 64),
        (cx - 8, top + 64),
    ]
    draw.polygon(pts, fill=color)


def fog_lines(draw, cx, top, color):
    for i, off in enumerate([0, 26, 52]):
        y = top + off
        draw.line([cx - 78, y, cx - 20, y], fill=color, width=12, joint="curve")
        draw.line([cx - 8, y, cx + 78, y], fill=color, width=12, joint="curve")


def save(img, name):
    img = img.resize((128, 128), Image.LANCZOS)
    img.save(os.path.join(OUT, f"{name}.png"))
    print(f"  -> {name}.png")


# 调色板
SUN = "#FFB300"
CLOUD = "#90A4AE"
CLOUD_L = "#CFD8DC"
RAIN = "#29B6F6"
BOLT = "#FFCA28"

# 1. 晴
im = new_canvas(); d = ImageDraw.Draw(im); draw_sun(d, 128, 128, 52, SUN); save(im, "sun")

# 2. 多云 / 晴间多云（sun + cloud）
im = new_canvas(); d = ImageDraw.Draw(im)
draw_sun(d, 86, 86, 34, SUN)
draw_cloud(d, 150, 165, 0.92, CLOUD)
save(im, "sun-cloud")

# 3. 阴 / 多云兜底（cloud）
im = new_canvas(); d = ImageDraw.Draw(im); draw_cloud(d, 128, 140, 1.0, CLOUD); save(im, "cloud")

# 4. 小雨
im = new_canvas(); d = ImageDraw.Draw(im)
draw_cloud(d, 128, 110, 0.95, CLOUD)
draw_drops(d, 128, 150, 3, RAIN, thick=11)
save(im, "rain")

# 5. 大雨 / 暴雨
im = new_canvas(); d = ImageDraw.Draw(im)
draw_cloud(d, 128, 100, 0.95, CLOUD)
draw_drops(d, 128, 138, 5, RAIN, thick=12)
save(im, "heavy-rain")

# 6. 雪
im = new_canvas(); d = ImageDraw.Draw(im)
draw_cloud(d, 128, 110, 0.95, CLOUD)
draw_snow(d, 128, 152, 3)
save(im, "snow")

# 7. 雷阵雨
im = new_canvas(); d = ImageDraw.Draw(im)
draw_cloud(d, 128, 104, 0.95, CLOUD)
bolt(d, 128, 140, BOLT)
save(im, "thunder")

# 8. 雾 / 霾
im = new_canvas(); d = ImageDraw.Draw(im)
draw_cloud(d, 128, 96, 0.82, CLOUD_L)
fog_lines(d, 128, 150, CLOUD)
save(im, "fog")

print("全部图标生成完成：", OUT)
