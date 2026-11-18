import sys, math
from PIL import Image, ImageDraw, ImageFilter, ImageChops
S = 2048                      # 超采样画布
out = sys.argv[1]

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
def hexc(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
m = int(S * 100 / 1024)       # macOS 图标网格：四周留白
box = (m, m, S - m, S - m)
r = int((S - 2 * m) * 0.225)

# 阴影
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle((box[0], box[1] + 24, box[2], box[3] + 24), r, fill=(10, 60, 45, 90))
img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(36)))

# 薄荷绿渐变底
grad = Image.new("RGBA", (S, S))
c1, c2 = hexc("#4BE0B8"), hexc("#109473")
gp = grad.load()
for y in range(S):
    for x in range(0, S, 4):
        t = min(1, max(0, (x * 0.35 + y * 0.65) / S))
        c = lerp(c1, c2, t) + (255,)
        for k in range(4):
            if x + k < S: gp[x + k, y] = c
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle(box, r, fill=255)
base = Image.new("RGBA", (S, S), (0, 0, 0, 0)); base.paste(grad, (0, 0), mask)
# 顶部柔光
hl = Image.new("L", (S, S), 0)
ImageDraw.Draw(hl).ellipse((-S * 0.3, -S * 0.9, S * 1.3, S * 0.55), fill=34)
hl = ImageChops.multiply(hl.filter(ImageFilter.GaussianBlur(220)), mask)
base = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), base, hl)
img = Image.alpha_composite(img, base)

d = ImageDraw.Draw(img)
W = (255, 255, 255, 255)
cx, cy = S * 0.41, S * 0.5
# 圆角播放三角形
tri = Image.new("L", (S, S), 0)
td = ImageDraw.Draw(tri)
h = S * 0.30
pts = [(cx - h * 0.42, cy - h * 0.5), (cx - h * 0.42, cy + h * 0.5), (cx + h * 0.48, cy)]
td.polygon(pts, fill=255)
rr = int(S * 0.028)
tri = tri.filter(ImageFilter.MaxFilter(1))
tri = tri.filter(ImageFilter.GaussianBlur(rr)).point(lambda v: 255 if v > 128 else 0)  # 圆角
img.paste(W, (0, 0), tri.filter(ImageFilter.GaussianBlur(1.5)))
# 声波弧线
lw = int(S * 0.042)
for i, (rad, a) in enumerate(((S * 0.15, 255), (S * 0.245, 235))):
    ox = cx + h * 0.22
    bb = (ox - rad, cy - rad, ox + rad, cy + rad)
    d.arc(bb, -42, 42, fill=(255, 255, 255, a), width=lw)
    for ang in (-42, 42):   # 圆头端点
        px = ox + (rad - lw / 2) * math.cos(math.radians(ang))
        py = cy + (rad - lw / 2) * math.sin(math.radians(ang))
        d.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=(255, 255, 255, a))
img.resize((1024, 1024), Image.LANCZOS).save(out)
