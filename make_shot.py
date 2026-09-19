import datetime
import os

import main
from PIL import Image, ImageDraw, ImageFont

main.enable_dpi_awareness()
cfg = main.default_schedule()  # 示例课表
os.makedirs("docs", exist_ok=True)

try:
    f_title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 30)
    f_sub = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
except Exception:
    f_title = f_sub = ImageFont.load_default()


def shot(dt, out, title, subs):
    main.time_now = lambda: dt
    w = main.CourseWidget(cfg)
    w.height = 1000
    img = w.render_image()
    try:
        w.root.destroy()
    except Exception:
        pass
    img = img.crop((0, 0, 223, 720))

    W, H = 480, 760
    bg = Image.new("RGB", (W, H), (18, 20, 24))
    d = ImageDraw.Draw(bg)
    for y in range(H):
        t = y / H
        d.line((0, y, W, y), fill=(int(22 + 26 * t), int(26 + 30 * t), int(34 + 38 * t)))

    d.text((30, 150), title, font=f_title, fill=(120, 200, 255))
    yy = 198
    for s in subs:
        d.text((32, yy), s, font=f_sub, fill=(150, 160, 175))
        yy += 28

    bg.paste(img, (W - 223 - 22, 26), img)
    bg.save(out)
    print("saved", out, bg.size)


shot(datetime.datetime(2026, 9, 21, 10, 20), "docs/preview.png",
     "枫源梦校园课表",
     ["fym-school-timetable", "桌面侧边悬浮 · 背景全透明", "多选科组合合并对照"])

shot(datetime.datetime(2026, 9, 26, 9, 0), "docs/preview-weekend.png",
     "周末 · 全部自习",
     ["same class, no repeats", "相同科目只显示一次", "背景完全透明"])
