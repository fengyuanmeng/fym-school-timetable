#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""枫源梦校园课表 — 右侧悬浮课程表
功能：开机自启、透明背景、科目分色、双科目显示、全屏自动隐藏、Win+Shift+F 设置
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime, timedelta
from tkinter import colorchooser, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Tuple

from pynput import keyboard

# ---------- 路径与资源 ----------

def resource_path(relative_path: str) -> str:
    """PyInstaller 打包后也能正确找到资源文件"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(meipass)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(exe_dir)
        candidates.append(os.path.join(exe_dir, "_internal"))
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for base in candidates:
        p = os.path.join(base, relative_path)
        if os.path.exists(p):
            return p
    # 找不到时返回第一个候选，避免崩溃
    return os.path.join(candidates[-1], relative_path)


def config_dir() -> str:
    appdata = os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(appdata, "枫源梦校园课表")
    os.makedirs(d, exist_ok=True)
    return d


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


# ---------- Win32 常量 ----------

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_MINIMIZE = 0x20000000
WS_VISIBLE = 0x10000000
MONITOR_DEFAULTTONEAREST = 2

GetWindowLongW = user32.GetWindowLongW
SetWindowLongW = user32.SetWindowLongW
GetForegroundWindow = user32.GetForegroundWindow
GetWindowRect = user32.GetWindowRect
IsIconic = user32.IsIconic
MonitorFromWindow = user32.MonitorFromWindow
GetMonitorInfoW = user32.GetMonitorInfoW
GetClassNameW = user32.GetClassNameW


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_uint32),
    ]


# ---------- 分层窗口（逐像素透明，彻底消除色键描边） ----------

gdi32 = ctypes.windll.gdi32
ULW_ALPHA = 0x02
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def enable_dpi_awareness():
    """让进程按物理像素工作，分层窗口坐标与渲染一致"""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def push_layered(hwnd: int, image, x: int, y: int) -> None:
    """把 PIL RGBA 图像以“逐像素透明”方式绘制到分层窗口"""
    from PIL import Image, ImageChops
    w, h = image.size
    rgba = image.convert("RGBA")
    r, g, b, a = rgba.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    hdc_screen = user32.GetDC(0)
    memdc = gdi32.CreateCompatibleDC(hdc_screen)
    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(memdc, ctypes.byref(bmi), 0, ctypes.byref(ppv), None, 0)
    old = gdi32.SelectObject(memdc, hbmp)
    ctypes.memmove(ppv, bgra, len(bgra))

    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    size = wintypes.SIZE(w, h)
    src = wintypes.POINT(0, 0)
    dst = wintypes.POINT(int(x), int(y))
    user32.UpdateLayeredWindow(hwnd, hdc_screen, ctypes.byref(dst), ctypes.byref(size),
                               memdc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(0, hdc_screen)


# ---------- 工具函数 ----------

def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def brightness(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def text_for_bg(h: str) -> str:
    return "#ffffff" if brightness(h) < 0.6 else "#000000"


def time_now() -> datetime:
    return datetime.now()


def parse_time(t: str) -> Optional[Tuple[int, int]]:
    try:
        h, m = map(int, t.split(":"))
        return h, m
    except Exception:
        return None


def is_current_period(start: str, end: str, now: datetime) -> bool:
    s = parse_time(start)
    e = parse_time(end)
    if not s or not e:
        return False
    cur = now.hour * 60 + now.minute
    s_min = s[0] * 60 + s[1]
    e_min = e[0] * 60 + e[1]
    return s_min <= cur < e_min


# ---------- 默认配置 ----------

DEFAULT_COLORS = {
    "语文": "#e74c3c",
    "数学": "#2980b9",
    "英语": "#9b59b6",
    "俄语": "#ff9f43",
    "物理": "#1abc9c",
    "化学": "#f1c40f",
    "生物": "#2ecc71",
    "政治": "#e67e22",
    "历史": "#34495e",
    "地理": "#16a085",
    "体育": "#27ae60",
    "自习": "#607d8b",
    "班会": "#8e44ad",
    "早读": "#d35400",
    "音乐": "#9b59b6",
    "美术": "#e91e63",
    "信息": "#00bcd4",
    "通用": "#795548",
    "社团": "#8e44ad",
}

DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


TIMES = [
    ("07:30", "08:15"),
    ("08:30", "09:15"),
    ("09:45", "10:30"),
    ("10:45", "11:30"),
    ("13:15", "14:00"),
    ("14:15", "15:00"),
    ("15:30", "16:10"),
    ("16:25", "17:05"),
    ("17:45", "18:55"),
    ("19:00", "20:05"),
    ("20:15", "21:10"),
]


def make_day(subjects: List[List[str]]) -> List[Dict[str, Any]]:
    """根据 11 节课时间生成一天的课程表"""
    return [
        {"start": s, "end": e, "subjects": subs}
        for (s, e), subs in zip(TIMES, subjects)
    ]


def default_schedule() -> Dict[str, Any]:
    """示例课表（仅供演示；你的实际课表保存在 %APPDATA%\\枫源梦校园课表\\config.json）"""

    # ---------- 物化地（示例：地理 + 化学） ----------
    wuhuadi = {
        "周一": make_day([["语文"], ["地理"], ["化学"], ["数学"], ["英语"],
                          ["物理"], ["体育"], ["语文"], ["地理"], ["自习"], ["自习"]]),
        "周二": make_day([["数学"], ["化学"], ["英语"], ["语文"], ["地理"],
                          ["物理"], ["信息", "通用"], ["数学"], ["化学"], ["自习"], ["自习"]]),
        "周三": make_day([["英语"], ["物理"], ["语文"], ["数学"], ["地理"],
                          ["音乐", "美术"], ["化学"], ["英语"], ["物理"], ["自习"], ["自习"]]),
        "周四": make_day([["化学"], ["数学"], ["语文"], ["英语"], ["物理"],
                          ["地理"], ["政治"], ["历史"], ["数学"], ["自习"], ["自习"]]),
        "周五": make_day([["语文"], ["英语"], ["数学"], ["物理"], ["化学"],
                          ["体育"], ["社团"], ["地理"], ["班会"], ["自习"], ["自习"]]),
        "周六": make_day([["自习"]] * 11),
        "周日": make_day([["自习"]] * 11),
    }

    # ---------- 物生地（示例：地理 + 生物） ----------
    wuhshengdi = {
        "周一": make_day([["语文"], ["生物"], ["地理"], ["数学"], ["英语"],
                          ["物理"], ["体育"], ["语文"], ["生物"], ["自习"], ["自习"]]),
        "周二": make_day([["数学"], ["地理"], ["英语"], ["语文"], ["生物"],
                          ["物理"], ["信息", "通用"], ["数学"], ["地理"], ["自习"], ["自习"]]),
        "周三": make_day([["英语"], ["物理"], ["语文"], ["数学"], ["生物"],
                          ["音乐", "美术"], ["地理"], ["英语"], ["物理"], ["自习"], ["自习"]]),
        "周四": make_day([["地理"], ["数学"], ["语文"], ["英语"], ["物理"],
                          ["生物"], ["政治"], ["历史"], ["数学"], ["自习"], ["自习"]]),
        "周五": make_day([["语文"], ["英语"], ["数学"], ["物理"], ["生物"],
                          ["体育"], ["社团"], ["地理"], ["班会"], ["自习"], ["自习"]]),
        "周六": make_day([["自习"]] * 11),
        "周日": make_day([["自习"]] * 11),
    }

    # ---------- 物化生（示例：生物 + 化学） ----------
    wuhuasheng = {
        "周一": make_day([["语文"], ["生物"], ["化学"], ["数学"], ["英语"],
                          ["物理"], ["体育"], ["语文"], ["生物"], ["自习"], ["自习"]]),
        "周二": make_day([["数学"], ["化学"], ["英语"], ["语文"], ["生物"],
                          ["物理"], ["信息", "通用"], ["数学"], ["化学"], ["自习"], ["自习"]]),
        "周三": make_day([["英语"], ["物理"], ["语文"], ["数学"], ["生物"],
                          ["音乐", "美术"], ["化学"], ["英语"], ["物理"], ["自习"], ["自习"]]),
        "周四": make_day([["化学"], ["数学"], ["语文"], ["英语"], ["物理"],
                          ["生物"], ["政治"], ["历史"], ["数学"], ["自习"], ["自习"]]),
        "周五": make_day([["语文"], ["英语"], ["数学"], ["物理"], ["生物"],
                          ["体育"], ["社团"], ["化学"], ["班会"], ["自习"], ["自习"]]),
        "周六": make_day([["自习"]] * 11),
        "周日": make_day([["自习"]] * 11),
    }

    combos = {
        "物化地": wuhuadi,
        "物生地": wuhshengdi,
        "物化生": wuhuasheng,
    }
    return {
        "version": 3,
        "autostart": True,
        "current_combo": "物化地",
        "merge_combos": True,
        "text_only": True,
        "combos": list(combos.keys()),
        "colors": DEFAULT_COLORS.copy(),
        "schedule": combos,
    }


def load_config() -> Dict[str, Any]:
    path = config_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 兼容旧配置
            for k, v in default_schedule().items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception as e:
            try:
                with open(os.path.join(config_dir(), "load_error.log"), "a", encoding="utf-8") as lf:
                    lf.write(f"加载配置失败，使用默认配置: {e}\n")
            except Exception:
                pass
    return default_schedule()


def save_config(cfg: Dict[str, Any]) -> None:
    path = config_file()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------- 开机自启 ----------

try:
    import winreg as reg

    def autostart_enabled() -> bool:
        try:
            key = reg.OpenKey(reg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Run",
                              0, reg.KEY_READ)
            reg.QueryValueEx(key, "枫源梦校园课表")
            key.Close()
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def set_autostart(enable: bool) -> None:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER,
                          r"Software\Microsoft\Windows\CurrentVersion\Run",
                          0, reg.KEY_SET_VALUE)
        try:
            if enable:
                if getattr(sys, "frozen", False):
                    exe = sys.executable
                else:
                    exe = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
                # 路径含空格时加引号
                reg.SetValueEx(key, "枫源梦校园课表", 0, reg.REG_SZ, exe)
            else:
                try:
                    reg.DeleteValue(key, "枫源梦校园课表")
                except FileNotFoundError:
                    pass
        finally:
            key.Close()
except Exception:
    def autostart_enabled() -> bool:
        return False

    def set_autostart(enable: bool) -> None:
        pass


# ---------- 全屏检测 ----------

SKIP_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "#32768", "TaskManagerWindow", "Windows.UI.Core.CoreWindow",
}


def get_window_rect(hwnd: int) -> Optional[RECT]:
    r = RECT()
    if GetWindowRect(hwnd, ctypes.byref(r)):
        return r
    return None


def get_monitor_rect(hwnd: int) -> Optional[RECT]:
    hmon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return mi.rcMonitor
    return None


def is_fullscreen_app(exclude_hwnds: List[int]) -> bool:
    hwnd = GetForegroundWindow()
    if not hwnd or hwnd in exclude_hwnds:
        return False
    if IsIconic(hwnd):
        return False
    cls = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, cls, 256)
    if cls.value in SKIP_CLASSES:
        return False
    style = GetWindowLongW(hwnd, GWL_STYLE)
    if not (style & WS_VISIBLE):
        return False
    r = get_window_rect(hwnd)
    if not r:
        return False
    mon = get_monitor_rect(hwnd)
    if not mon:
        return False
    w = r.right - r.left
    h = r.bottom - r.top
    mw = mon.right - mon.left
    mh = mon.bottom - mon.top
    return abs(w - mw) <= 8 and abs(h - mh) <= 8


# ---------- 设置窗口 ----------

class PeriodDialog(simpledialog.Dialog):
    """添加/编辑课时弹窗"""
    def __init__(self, parent, period: Optional[Dict[str, Any]] = None):
        self.period = period or {"start": "08:00", "end": "08:45", "subjects": ["语文"]}
        super().__init__(parent, title="编辑课时")

    def body(self, master):
        tk.Label(master, text="开始时间:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.start_var = tk.StringVar(value=self.period.get("start", ""))
        tk.Entry(master, textvariable=self.start_var, width=10).grid(row=0, column=1, padx=5, pady=5)

        tk.Label(master, text="结束时间:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.end_var = tk.StringVar(value=self.period.get("end", ""))
        tk.Entry(master, textvariable=self.end_var, width=10).grid(row=1, column=1, padx=5, pady=5)

        tk.Label(master, text="科目(用英文逗号分隔,最多两个):").grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=(10, 0))
        self.subj_var = tk.StringVar(value=",".join(self.period.get("subjects", [])))
        tk.Entry(master, textvariable=self.subj_var, width=25).grid(row=3, column=0, columnspan=2, padx=5, pady=5)
        return None

    def validate(self):
        s = self.start_var.get().strip()
        e = self.end_var.get().strip()
        subj = [x.strip() for x in self.subj_var.get().split(",") if x.strip()]
        if not (parse_time(s) and parse_time(e)):
            messagebox.showwarning("格式错误", "时间格式为 HH:MM")
            return 0
        if not subj:
            messagebox.showwarning("科目为空", "请至少填写一个科目")
            return 0
        self.result = {"start": s, "end": e, "subjects": subj[:2]}
        return 1


class SettingsWindow:
    def __init__(self, app: "CourseWidget"):
        self.app = app
        self.cfg = app.cfg
        self.window: Optional[tk.Toplevel] = None
        self.day_var = tk.StringVar(value="周一")
        self.tree: Optional[ttk.Treeview] = None
        self.subj_list: Optional[tk.Listbox] = None
        self.combo_var = tk.StringVar(value=self.cfg.get("current_combo", ""))
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self.merge_var = tk.BooleanVar(value=self.cfg.get("merge_combos", False))
        self.textonly_var = tk.BooleanVar(value=self.cfg.get("text_only", False))
        self.build()

    def build(self):
        if self.window is not None and tk.Toplevel.winfo_exists(self.window):
            self.window.lift()
            self.window.focus_force()
            return
        self.window = tk.Toplevel(self.app.root)
        self.window.title("枫源梦校园课表 - 设置")
        self.window.geometry("650x500")
        self.window.minsize(550, 400)
        self.window.resizable(True, True)
        self.window.configure(bg="#f5f5f5")
        try:
            self.window.iconbitmap(resource_path("assets/app.ico"))
        except Exception:
            pass
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        # 顶部：选科组合
        top = tk.Frame(self.window, bg="#f5f5f5")
        top.pack(fill="x", padx=10, pady=8)
        tk.Label(top, text="选科组合:", bg="#f5f5f5").pack(side="left")
        self.combo_box = ttk.Combobox(top, textvariable=self.combo_var,
                                      values=self.cfg.get("combos", []), state="readonly", width=18)
        self.combo_box.pack(side="left", padx=(5, 0))
        self.combo_box.bind("<<ComboboxSelected>>", self.on_combo_change)
        ttk.Button(top, text="添加", command=self.add_combo).pack(side="left", padx=(8, 2))
        ttk.Button(top, text="重命名", command=self.rename_combo).pack(side="left", padx=2)
        ttk.Button(top, text="删除", command=self.del_combo).pack(side="left", padx=2)

        # Notebook
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=10, pady=5)

        # --- 课程表页 ---
        page_schedule = tk.Frame(notebook, bg="#f5f5f5")
        notebook.add(page_schedule, text="课程表")
        left = tk.Frame(page_schedule, bg="#f5f5f5")
        left.pack(side="left", fill="y", padx=(0, 8))
        self.day_list = tk.Listbox(left, exportselection=0, height=7, width=8)
        for d in DAYS:
            self.day_list.insert("end", d)
        self.day_list.select_set(0)
        self.day_list.bind("<<ListboxSelect>>", self.on_day_select)
        self.day_list.pack(pady=(0, 8))
        ttk.Button(left, text="上移", command=lambda: self.move_period(-1)).pack(fill="x", pady=1)
        ttk.Button(left, text="下移", command=lambda: self.move_period(1)).pack(fill="x", pady=1)

        right = tk.Frame(page_schedule, bg="#f5f5f5")
        right.pack(side="left", fill="both", expand=True)
        cols = ("start", "end", "subjects")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=14)
        self.tree.heading("start", text="开始")
        self.tree.heading("end", text="结束")
        self.tree.heading("subjects", text="科目")
        self.tree.column("start", width=70, anchor="center")
        self.tree.column("end", width=70, anchor="center")
        self.tree.column("subjects", width=220, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.edit_period())

        btns = tk.Frame(right, bg="#f5f5f5")
        btns.pack(fill="x")
        ttk.Button(btns, text="添加课时", command=self.add_period).pack(side="left", padx=2)
        ttk.Button(btns, text="编辑", command=self.edit_period).pack(side="left", padx=2)
        ttk.Button(btns, text="删除", command=self.del_period).pack(side="left", padx=2)

        # --- 颜色页 ---
        page_color = tk.Frame(notebook, bg="#f5f5f5")
        notebook.add(page_color, text="科目颜色")
        tk.Label(page_color, text="双击科目可修改颜色", bg="#f5f5f5").pack(anchor="w", padx=8, pady=5)
        self.subj_list = tk.Listbox(page_color, height=16, width=25, exportselection=0)
        self.subj_list.pack(side="left", fill="y", padx=8, pady=5)
        self.subj_list.bind("<Double-1>", lambda e: self.edit_color())
        c_btns = tk.Frame(page_color, bg="#f5f5f5")
        c_btns.pack(side="left", fill="y", padx=5, pady=5)
        ttk.Button(c_btns, text="添加科目", command=self.add_subject).pack(fill="x", pady=2)
        ttk.Button(c_btns, text="修改颜色", command=self.edit_color).pack(fill="x", pady=2)
        ttk.Button(c_btns, text="删除科目", command=self.del_subject).pack(fill="x", pady=2)
        self.color_preview = tk.Canvas(c_btns, width=120, height=40, bg="#cccccc", highlightthickness=1)
        self.color_preview.pack(pady=(15, 0))
        self.subj_list.bind("<<ListboxSelect>>", self.on_subj_select)

        # --- 常规页 ---
        page_general = tk.Frame(notebook, bg="#f5f5f5")
        notebook.add(page_general, text="常规")
        tk.Checkbutton(page_general, text="开机自动启动", variable=self.autostart_var,
                       bg="#f5f5f5").pack(anchor="w", padx=15, pady=6)
        tk.Checkbutton(page_general, text="合并显示所有选科组合（同一节课列出各组合科目）",
                       variable=self.merge_var, bg="#f5f5f5").pack(anchor="w", padx=15, pady=6)
        tk.Checkbutton(page_general, text="纯文字模式（无背景色，仅用字体颜色区分科目）",
                       variable=self.textonly_var, bg="#f5f5f5").pack(anchor="w", padx=15, pady=6)
        tk.Label(page_general,
                 text="快捷键: Win + Shift + F 打开设置\n右键点击悬浮窗可打开设置/退出",
                 bg="#f5f5f5", justify="left").pack(anchor="w", padx=15, pady=8)

        # 底部保存/关闭
        bottom = tk.Frame(self.window, bg="#f5f5f5")
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="保存并应用", command=self.save).pack(side="right", padx=5)
        ttk.Button(bottom, text="关闭", command=self.close).pack(side="right", padx=5)

        self.load_tree()
        self.load_color_list()

    def get_current_schedule(self) -> List[Dict[str, Any]]:
        combo = self.combo_var.get()
        day = self.get_selected_day()
        sched = self.cfg.setdefault("schedule", {}).setdefault(combo, {})
        if day not in sched:
            sched[day] = []
        return sched[day]

    def get_selected_day(self) -> str:
        sel = self.day_list.curselection()
        if sel:
            return DAYS[sel[0]]
        return "周一"

    def on_combo_change(self, event=None):
        self.load_tree()

    def on_day_select(self, event=None):
        self.load_tree()

    def load_tree(self):
        if not self.tree:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, p in enumerate(self.get_current_schedule()):
            self.tree.insert("", "end", iid=str(idx), values=(
                p.get("start", ""), p.get("end", ""), ", ".join(p.get("subjects", []))
            ))

    def selected_period_index(self) -> Optional[int]:
        sel = self.tree.selection()
        if sel:
            try:
                return int(sel[0])
            except Exception:
                return None
        return None

    def add_period(self):
        d = PeriodDialog(self.window)
        if d.result:
            self.get_current_schedule().append(d.result)
            self.load_tree()
            self.tree.selection_set(str(len(self.get_current_schedule()) - 1))

    def edit_period(self):
        idx = self.selected_period_index()
        if idx is None:
            messagebox.showwarning("未选中", "请先选中一行")
            return
        period = self.get_current_schedule()[idx]
        d = PeriodDialog(self.window, period)
        if d.result:
            self.get_current_schedule()[idx] = d.result
            self.load_tree()
            self.tree.selection_set(str(idx))

    def del_period(self):
        idx = self.selected_period_index()
        if idx is None:
            return
        if messagebox.askyesno("确认", "删除选中的课时？"):
            del self.get_current_schedule()[idx]
            self.load_tree()

    def move_period(self, delta: int):
        idx = self.selected_period_index()
        lst = self.get_current_schedule()
        if idx is None or not (0 <= idx + delta < len(lst)):
            return
        lst[idx], lst[idx + delta] = lst[idx + delta], lst[idx]
        self.load_tree()
        self.tree.selection_set(str(idx + delta))

    def load_color_list(self):
        if not self.subj_list:
            return
        self.subj_list.delete(0, "end")
        colors = self.cfg.get("colors", {})
        for subj in sorted(colors.keys()):
            self.subj_list.insert("end", subj)
            self.subj_list.itemconfig("end", {"bg": colors[subj], "fg": text_for_bg(colors[subj])})

    def on_subj_select(self, event=None):
        sel = self.subj_list.curselection()
        if sel:
            subj = self.subj_list.get(sel[0])
            color = self.cfg.get("colors", {}).get(subj, "#cccccc")
            self.color_preview.configure(bg=color)

    def edit_color(self):
        sel = self.subj_list.curselection()
        if not sel:
            return
        subj = self.subj_list.get(sel[0])
        current = self.cfg["colors"].get(subj, "#cccccc")
        c = colorchooser.askcolor(color=current, title=f"选择 {subj} 颜色")
        if c[1]:
            self.cfg["colors"][subj] = c[1]
            self.load_color_list()
            self.subj_list.select_set(sel[0])
            self.on_subj_select()

    def add_subject(self):
        name = simpledialog.askstring("添加科目", "科目名称:", parent=self.window)
        if not name:
            return
        if name in self.cfg.get("colors", {}):
            return
        c = colorchooser.askcolor(title="选择颜色")
        if c[1]:
            self.cfg["colors"][name] = c[1]
            self.load_color_list()

    def del_subject(self):
        sel = self.subj_list.curselection()
        if not sel:
            return
        subj = self.subj_list.get(sel[0])
        if messagebox.askyesno("确认", f"删除科目 {subj}？"):
            self.cfg["colors"].pop(subj, None)
            self.load_color_list()

    def add_combo(self):
        name = simpledialog.askstring("新建选科组合", "组合名称:", parent=self.window)
        if not name:
            return
        name = name.strip()
        if name in self.cfg.get("combos", []):
            messagebox.showwarning("已存在", "该组合已存在")
            return
        combos = self.cfg.setdefault("combos", [])
        combos.append(name)
        self.cfg.setdefault("schedule", {})[name] = {d: [] for d in DAYS}
        self.combo_box["values"] = combos
        self.combo_var.set(name)
        self.load_tree()

    def rename_combo(self):
        old = self.combo_var.get()
        new = simpledialog.askstring("重命名", "新名称:", initialvalue=old, parent=self.window)
        if not new or new.strip() == old:
            return
        new = new.strip()
        combos = self.cfg.get("combos", [])
        if new in combos:
            messagebox.showwarning("已存在", "该名称已存在")
            return
        if old in combos:
            idx = combos.index(old)
            combos[idx] = new
        self.cfg["schedule"][new] = self.cfg["schedule"].pop(old, {d: [] for d in DAYS})
        self.combo_var.set(new)
        self.combo_box["values"] = combos
        if self.cfg.get("current_combo") == old:
            self.cfg["current_combo"] = new

    def del_combo(self):
        name = self.combo_var.get()
        if not name:
            return
        if messagebox.askyesno("确认", f"删除选科组合 {name}？"):
            combos = self.cfg.get("combos", [])
            if name in combos:
                combos.remove(name)
            self.cfg.get("schedule", {}).pop(name, None)
            if combos:
                self.combo_var.set(combos[0])
                self.combo_box["values"] = combos
            else:
                self.combo_var.set("")
                self.combo_box["values"] = []
            self.load_tree()

    def save(self):
        self.cfg["current_combo"] = self.combo_var.get()
        self.cfg["merge_combos"] = self.merge_var.get()
        self.cfg["text_only"] = self.textonly_var.get()
        set_autostart(self.autostart_var.get())
        save_config(self.cfg)
        self.app.cfg = self.cfg
        self.app.refresh()
        messagebox.showinfo("已保存", "配置已保存并应用")

    def close(self):
        if self.window:
            self.window.destroy()
            self.window = None


# ---------- 主悬浮窗口 ----------

class CourseWidget:
    WIDTH = 223
    MIN_ROW_H = 30

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.settings: Optional[SettingsWindow] = None
        self.hidden_by_fullscreen = False
        self._pil_fonts: Dict[Any, Any] = {}
        self._shown = False

        self.root = tk.Tk()
        self.root.title("枫源梦校园课表")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.height = self.screen_h
        self.win_x = self.screen_w - self.WIDTH
        self.win_y = 0
        self.root.geometry(f"{self.WIDTH}x{self.height}+{self.win_x}+{self.win_y}")
        self.root.withdraw()  # 首帧推送前先隐藏，避免闪白

        try:
            self.root.iconbitmap(resource_path("assets/app.ico"))
        except Exception:
            pass

        # 承载鼠标事件的透明画布（内容改用分层窗口绘制）
        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0,
                                width=self.WIDTH, height=self.height)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Double-Button-1>", lambda e: self.open_settings())

        self.root.update_idletasks()
        self._setup_window()
        self.root.after(250, self.refresh)
        self.root.after(600, self.check_fullscreen_loop)
        self.root.after(1000, self.refresh_loop)

    def _hwnd(self) -> int:
        """顶层窗口句柄（Tk 的 winfo_id 返回的是子窗口，需取父窗口 wrapper）"""
        try:
            h = self.root.winfo_id()
            p = user32.GetParent(h)
            return p if p else h
        except Exception:
            return self.root.winfo_id()

    def _setup_window(self):
        try:
            hwnd = self._hwnd()
            ex = GetWindowLongW(hwnd, GWL_EXSTYLE)
            SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_LAYERED)
            # 强制样式生效
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0004 | 0x0020)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        except Exception:
            pass

    def on_right_click(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="设置", command=self.open_settings)
        menu.add_command(label="刷新", command=self.refresh)
        menu.add_separator()
        menu.add_command(label="退出", command=self.exit_app)
        menu.post(event.x_root, event.y_root)

    def open_settings(self):
        if self.settings is None or not tk.Toplevel.winfo_exists(self.settings.window):
            self.settings = SettingsWindow(self)
        else:
            self.settings.build()

    def exit_app(self):
        self.root.destroy()
        sys.exit(0)

    def current_combo(self) -> str:
        return self.cfg.get("current_combo", self.cfg.get("combos", ["默认"])[0])

    def today_schedule(self) -> List[Dict[str, Any]]:
        day_index = datetime.now().weekday()  # 周一=0
        day = DAYS[day_index]
        sched = self.cfg.get("schedule", {}).get(self.current_combo(), {})
        return sched.get(day, [])

    def subject_color(self, name: str) -> str:
        return self.cfg.get("colors", {}).get(name, "#7f8c8d")

    # ---------- Pillow 渲染（逐像素透明，无描边） ----------

    def _pil_font(self, size, bold=False):
        from PIL import ImageFont
        key = (size, bold)
        if key not in self._pil_fonts:
            f = None
            for path in (("C:/Windows/Fonts/" + ("msyhbd.ttc" if bold else "msyh.ttc")),
                         ("C:/Windows/Fonts/" + ("simhei.ttf" if bold else "msyh.ttc")),
                         "msyh.ttc"):
                try:
                    f = ImageFont.truetype(path, size)
                    break
                except Exception:
                    continue
            if f is None:
                f = ImageFont.load_default()
            self._pil_fonts[key] = f
        return self._pil_fonts[key]

    def _sub_fill(self, name):
        if name == "—":
            return (138, 154, 166, 255)
        r, g, b = hex_to_rgb(self.subject_color(name))
        return (r, g, b, 255)

    def _tw(self, d, s, font):
        try:
            return d.textlength(s, font=font)
        except Exception:
            return font.getsize(s)[0]

    def _measure(self, d, subs, font):
        total = 0
        for i, s in enumerate(subs):
            total += self._tw(d, s, font)
            if i < len(subs) - 1:
                total += self._tw(d, "/", font) + 8
        return total

    def _draw_seq(self, d, x, cy, subs, font):
        """在 (x, cy) 左对齐绘制科目序列（cy 为竖直中心），返回结束 x"""
        asc, desc = font.getmetrics()
        top = cy - (asc + desc) / 2
        n = len(subs)
        for i, s in enumerate(subs):
            d.text((x, top), s, font=font, fill=self._sub_fill(s))
            x += self._tw(d, s, font)
            if i < n - 1:
                d.text((x + 2, top), "/", font=font, fill=(127, 143, 153, 255))
                x += self._tw(d, "/", font) + 8
        return x

    def _draw_seq_right(self, d, right_x, cy, subs, font):
        total = self._measure(d, subs, font)
        self._draw_seq(d, right_x - total, cy, subs, font)

    def _draw_cell_bg(self, d, y, row_h, subjects):
        """非纯文字模式：带科目背景色"""
        y1, y2 = y + 2, y + row_h - 4
        x_left, x_right = 40, self.WIDTH
        if len(subjects) <= 1:
            subs = subjects or ["—"]
            color = hex_to_rgb(self.subject_color(subs[0]))
            d.rectangle((x_left, y1, x_right, y2), fill=color + (235,))
            f = self._pil_font(22, True)
            tw = self._tw(d, subs[0], f)
            asc, desc = f.getmetrics()
            d.text(((x_left + x_right - tw) / 2, (y1 + y2) / 2 - (asc + desc) / 2),
                   subs[0], font=f, fill=hex_to_rgb(text_for_bg(subs[0])) + (255,))
        else:
            seg = (x_right - x_left) / 2
            f = self._pil_font(17, True)
            for j, subj in enumerate(subjects[:2]):
                color = hex_to_rgb(self.subject_color(subj))
                sx1 = x_left + j * seg
                sx2 = x_left + (j + 1) * seg
                d.rectangle((sx1, y1, sx2, y2), fill=color + (235,))
                tw = self._tw(d, subj, f)
                asc, desc = f.getmetrics()
                d.text(((sx1 + sx2 - tw) / 2, (y1 + y2) / 2 - (asc + desc) / 2),
                       subj, font=f, fill=hex_to_rgb(text_for_bg(subj)) + (255,))

    def render_image(self):
        from PIL import Image, ImageDraw
        W, H = self.WIDTH, self.height
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        now = time_now()
        day = DAYS[now.weekday()]
        merge = self.cfg.get("merge_combos", False)
        text_only = self.cfg.get("text_only", False)

        f_day = self._pil_font(20, True)
        f_date = self._pil_font(15)
        f_t1 = self._pil_font(17, True)
        f_t2 = self._pil_font(14)
        f_big = self._pil_font(26, True)
        f_mid = self._pil_font(21, True)
        f_tag = self._pil_font(15)
        f_sm = self._pil_font(19, True)

        # 顶部：星期 + 日期 + 短装饰线
        cx = W // 2
        day_w = self._tw(d, day, f_day)
        d.text((cx - day_w - 6, 3), day, font=f_day, fill=(127, 212, 255, 255))
        d.text((cx + 6, 8), f"{now.month}/{now.day}", font=f_date, fill=(154, 167, 176, 255))
        d.line((cx - 42, 33, cx + 42, 33), fill=(61, 74, 83, 255), width=2)

        sched_map = self.cfg.get("schedule", {})
        combos = self.cfg.get("combos", [])
        if not merge:
            combo = self.current_combo()
            periods = sched_map.get(combo, {}).get(day, [])
            max_periods = max(11, len(periods))
        else:
            max_periods = 11
            for c in combos:
                max_periods = max(max_periods, len(sched_map.get(c, {}).get(day, [])))
        if max_periods == 0:
            return img

        top = 38
        row_h = max(self.MIN_ROW_H, (H - top) // max_periods)
        right_x = W - 15

        for i in range(max_periods):
            y = top + i * row_h
            mid = y + row_h / 2

            if not merge:
                p = periods[i] if i < len(periods) else None
                start = p.get("start", "") if p else ""
                end = p.get("end", "") if p else ""
                cur = bool(p) and is_current_period(start, end, now)
                subjects = (p.get("subjects", []) or ["自习"]) if p else []
                groups = [(tuple(subjects), [])]
            else:
                start = end = ""
                cur = False
                groups = []
                for c in combos:
                    pp = sched_map.get(c, {}).get(day, [])
                    if i < len(pp):
                        if not start:
                            start = pp[i].get("start", "")
                            end = pp[i].get("end", "")
                        if is_current_period(pp[i].get("start", ""), pp[i].get("end", ""), now):
                            cur = True
                        sig = tuple(pp[i].get("subjects", []) or ["—"])
                    else:
                        sig = ("—",)
                    for g in groups:
                        if g[0] == sig:
                            g[1].append(c)
                            break
                    else:
                        groups.append([sig, [c]])

            # 时间列
            asc1, desc1 = f_t1.getmetrics()
            d.text((13, mid - 3 - (asc1 + desc1)), start, font=f_t1,
                   fill=(219, 230, 236, 255) if cur else (179, 192, 200, 255))
            d.text((13, mid + 3), end, font=f_t2, fill=(126, 141, 151, 255))

            if not merge:
                if not text_only:
                    self._draw_cell_bg(d, y, row_h, subjects)
                elif len(subjects) <= 1:
                    self._draw_seq_right(d, right_x, mid, subjects or ["—"], f_big)
                else:
                    self._draw_seq_right(d, right_x, y + row_h * 0.3, [subjects[0]], f_sm)
                    self._draw_seq_right(d, right_x, y + row_h * 0.72, [subjects[1]], f_sm)
            else:
                n = len(groups)
                lh = row_h / n
                for gi, (sig, cs) in enumerate(groups):
                    ly = y + gi * lh + lh / 2
                    subs = list(sig) if sig else ["—"]
                    if n == 1:
                        self._draw_seq_right(d, right_x, ly, subs, f_big)
                    else:
                        tag = "·".join(cs)
                        total = self._measure(d, subs, f_mid) + 8 + self._tw(d, tag, f_tag)
                        endx = self._draw_seq(d, right_x - total, ly, subs, f_mid)
                        asc, desc = f_tag.getmetrics()
                        d.text((endx + 8, ly - (asc + desc) / 2), tag, font=f_tag,
                               fill=(95, 158, 196, 255))

            if cur:
                d.rectangle((0, y + 6, 4, y + row_h - 6), fill=(79, 195, 247, 255))

        return img

    def refresh(self):
        try:
            img = self.render_image()
            if not self._shown:
                self._setup_window()
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self._shown = True
            self.win_x = self.screen_w - self.WIDTH
            push_layered(self._hwnd(), img, self.win_x, self.win_y)
        except Exception:
            pass

    def refresh_loop(self):
        self.refresh()
        self.root.after(60000, self.refresh_loop)

    def check_fullscreen_loop(self):
        exclude = [self._hwnd()]
        if self.settings and self.settings.window and tk.Toplevel.winfo_exists(self.settings.window):
            try:
                exclude.append(self.settings.window.winfo_id())
            except Exception:
                pass
        fullscreen = is_fullscreen_app(exclude)
        if fullscreen and not self.hidden_by_fullscreen:
            self.root.withdraw()
            self.hidden_by_fullscreen = True
        elif not fullscreen and self.hidden_by_fullscreen:
            self.root.deiconify()
            self.hidden_by_fullscreen = False
            self.root.after(80, self.refresh)
        self.root.after(500, self.check_fullscreen_loop)


# ---------- 全局热键 ----------

def start_hotkey_listener(open_settings_callback):
    from pynput.keyboard import KeyCode
    KEY_F = KeyCode.from_char("f")

    def is_f(key):
        if key == KEY_F:
            return True
        ch = getattr(key, "char", None)
        if ch and str(ch).lower() == "f":
            return True
        if str(key).lower() == "f":
            return True
        return False

    pressed: set = set()

    def on_press(key):
        pressed.add(key)
        has_win = any(k in pressed for k in (
            keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r
        ))
        has_shift = any(k in pressed for k in (
            keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r
        ))
        has_f = is_f(key) or any(is_f(k) for k in pressed)
        if has_win and has_shift and has_f:
            try:
                open_settings_callback()
            except Exception:
                pass

    def on_release(key):
        pressed.discard(key)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()


# ---------- 单实例 & 启动 ----------

def ensure_single_instance() -> bool:
    mutex_name = "枫源梦校园课表_Mutex_2026"
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenMutexW(0x1F0001, False, mutex_name)
    if h:
        # 已有实例，尝试唤醒它
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "枫源梦校园课表")
            if hwnd:
                user32.ShowWindow(hwnd, 1)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return False
    kernel32.CreateMutexW(None, False, mutex_name)
    return True


def main():
    enable_dpi_awareness()
    if not ensure_single_instance():
        sys.exit(0)

    cfg = load_config()

    # 首次运行写入默认配置并设置自启
    if cfg.get("autostart") and not autostart_enabled():
        try:
            set_autostart(True)
        except Exception:
            pass

    app = CourseWidget(cfg)

    def open_settings_safe():
        try:
            app.root.after(0, app.open_settings)
        except Exception:
            pass

    start_hotkey_listener(open_settings_safe)
    app.root.mainloop()


if __name__ == "__main__":
    main()
