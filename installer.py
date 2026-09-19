#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""枫源梦校园课表 —— 安装程序（自解压安装包）
免管理员：安装到当前用户目录 %LOCALAPPDATA%\\Programs\\枫源梦校园课表
自动创建：桌面快捷方式 + 开始菜单快捷方式 + 开机自启 + 卸载程序

静默安装：  枫源梦校园课表_安装包.exe --silent
可选环境变量：FYM_TARGET(安装目录) FYM_NO_REG=1(不写自启) FYM_NO_SHORTCUT=1(不建快捷方式)
"""

import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

APP_NAME = "枫源梦校园课表"
EXE_NAME = "枫源梦校园课表.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NO_WINDOW = 0x08000000


def bundle_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def src_app_dir() -> str:
    for cand in (os.path.join(bundle_dir(), "app"),
                 os.path.join(bundle_dir(), APP_NAME),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", APP_NAME)):
        if os.path.isdir(cand):
            return cand
    raise RuntimeError("安装包内未找到程序文件（app 目录）")


def target_dir() -> str:
    env = os.environ.get("FYM_TARGET")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def desktop_dir() -> str:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        v, _ = winreg.QueryValueEx(k, "Desktop")
        winreg.CloseKey(k)
        if v and os.path.isdir(v):
            return v
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def startmenu_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


def make_shortcut(lnk: str, target: str, workdir: str, icon: str, desc: str) -> None:
    ps = (
        "$W=New-Object -ComObject WScript.Shell;"
        f"$s=$W.CreateShortcut('{lnk}');"
        f"$s.TargetPath='{target}';"
        f"$s.WorkingDirectory='{workdir}';"
        f"$s.IconLocation='{icon}';"
        f"$s.Description='{desc}';"
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", ps],
                   creationflags=NO_WINDOW, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


UNINSTALL_BAT = """@echo off
title 卸载 {app}
echo 正在卸载 {app} ...
taskkill /f /im "{exe}" >nul 2>nul
reg delete "HKCU\\{runkey}" /v "{app}" /f >nul 2>nul
del /f /q "%USERPROFILE%\\Desktop\\{app}.lnk" >nul 2>nul
rmdir /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{app}" >nul 2>nul
echo.
echo 已卸载 {app}。
echo 程序文件夹即将自动删除...
start "" cmd /c "timeout /t 2 >nul & rmdir /s /q \\"%~dp0\\""
exit
"""


def install(log, target=None, do_shortcuts=True, do_autostart=True):
    """执行安装，返回安装后的 exe 路径。target 为空则用默认目录。"""
    src = src_app_dir()
    dst = target or target_dir()
    exe = os.path.join(dst, EXE_NAME)

    log("关闭正在运行的旧版本…")
    subprocess.run(["taskkill", "/f", "/im", EXE_NAME],
                   creationflags=NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)

    log("复制程序文件…")
    if os.path.isdir(dst):
        # 仅当是“上次的安装目录”或“空目录”时才整体清空，避免误删用户其它文件
        has_ours = os.path.exists(os.path.join(dst, EXE_NAME))
        try:
            is_empty = not os.listdir(dst)
        except Exception:
            is_empty = False
        if has_ours or is_empty:
            shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)

    ic = exe + ",0"
    if do_shortcuts:
        log("创建快捷方式…")
        try:
            make_shortcut(os.path.join(desktop_dir(), APP_NAME + ".lnk"), exe, dst, ic, APP_NAME)
        except Exception:
            pass
        try:
            sm = os.path.join(startmenu_dir(), APP_NAME)
            os.makedirs(sm, exist_ok=True)
            make_shortcut(os.path.join(sm, APP_NAME + ".lnk"), exe, dst, ic, APP_NAME)
            make_shortcut(os.path.join(sm, "卸载 " + APP_NAME + ".lnk"),
                          os.path.join(dst, "卸载.bat"), dst, ic, "卸载 " + APP_NAME)
        except Exception:
            pass

    if do_autostart:
        log("设置开机自启…")
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
            winreg.CloseKey(k)
        except Exception:
            pass

    log("写入卸载程序…")
    with open(os.path.join(dst, "卸载.bat"), "w", encoding="gbk", errors="ignore") as f:
        f.write(UNINSTALL_BAT.format(app=APP_NAME, exe=EXE_NAME, runkey=RUN_KEY))

    log("完成")
    return exe


def silent_install() -> int:
    logfile = os.path.join(os.environ.get("TEMP", "."), "fym_install.log")
    lines = []

    def log(m):
        lines.append(m)
        try:
            with open(logfile, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            pass

    try:
        install(log,
                do_shortcuts=(os.environ.get("FYM_NO_SHORTCUT") != "1"),
                do_autostart=(os.environ.get("FYM_NO_REG") != "1"))
        log("OK")
        return 0
    except Exception as e:
        log("FAIL: " + repr(e))
        return 1


class Installer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME + " 安装程序")
        self.root.geometry("500x380")
        self.root.resizable(False, False)
        self.root.configure(bg="#f4f6f8")
        try:
            self.root.iconbitmap(os.path.join(bundle_dir(), "assets", "app.ico"))
        except Exception:
            pass
        self.path_var = tk.StringVar(value=target_dir())
        self.advanced = tk.BooleanVar(value=False)
        self._build()
        self.exe_path = None

    def _build(self):
        head = tk.Frame(self.root, bg="#1f6feb", height=54)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, bg="#1f6feb", fg="white",
                 font=("Microsoft YaHei", 15, "bold")).pack(side="left", padx=16, pady=10)
        tk.Label(head, text="安装程序", bg="#1f6feb", fg="#cfe0ff",
                 font=("Microsoft YaHei", 10)).pack(side="left", pady=14)

        body = tk.Frame(self.root, bg="#f4f6f8")
        body.pack(fill="both", expand=True, padx=18, pady=14)

        tk.Label(body, text="安装位置（可修改）：", bg="#f4f6f8", fg="#333",
                 font=("Microsoft YaHei", 10)).pack(anchor="w")
        row = tk.Frame(body, bg="#f4f6f8")
        row.pack(fill="x", pady=(4, 0))
        self.path_entry = ttk.Entry(row, textvariable=self.path_var,
                                    font=("Microsoft YaHei", 9))
        self.path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", width=7, command=self.browse).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="默认", width=6, command=self.reset_path).pack(side="left", padx=(4, 0))

        opts = tk.Frame(body, bg="#f4f6f8")
        opts.pack(fill="x", pady=(8, 0))
        self.autostart_var = tk.BooleanVar(value=True)
        self.shortcut_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="开机自启", variable=self.autostart_var,
                       bg="#f4f6f8", font=("Microsoft YaHei", 9)).pack(side="left")
        tk.Checkbutton(opts, text="创建桌面/开始菜单快捷方式", variable=self.shortcut_var,
                       bg="#f4f6f8", font=("Microsoft YaHei", 9)).pack(side="left", padx=(12, 0))

        tk.Label(body, text="提示：装到系统盘(如 Program Files)需以管理员身份运行本安装包。",
                 bg="#f4f6f8", fg="#8a8a8a", font=("Microsoft YaHei", 8),
                 wraplength=450, justify="left").pack(anchor="w", pady=(6, 8))

        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100, length=450)
        self.bar.pack(fill="x", pady=(4, 6))
        self.status = tk.Label(body, text="准备就绪", bg="#f4f6f8", fg="#333",
                               font=("Microsoft YaHei", 9), anchor="w")
        self.status.pack(fill="x")

        btns = tk.Frame(self.root, bg="#f4f6f8")
        btns.pack(fill="x", padx=18, pady=(0, 14))
        self.install_btn = ttk.Button(btns, text="开始安装", command=self.start)
        self.install_btn.pack(side="right")
        ttk.Button(btns, text="退出", command=self.root.destroy).pack(side="right", padx=8)

    def browse(self):
        from tkinter import filedialog
        init = self.path_var.get() or target_dir()
        d = filedialog.askdirectory(title="选择安装位置", initialdir=init,
                                    mustexist=False)
        if d:
            # 若选中的是盘符根或已存在的目录，直接作为安装目录
            self.path_var.set(os.path.normpath(d))

    def reset_path(self):
        self.path_var.set(target_dir())

    def start(self):
        self.install_btn.config(state="disabled")
        self.bar["value"] = 0

        def work():
            try:
                ticks = {"n": 0}

                def log(m):
                    ticks["n"] += 1
                    self.root.after(0, lambda: self.bar.config(
                        value=min(95, int(ticks["n"] / 6 * 100))))
                    self.root.after(0, lambda: self.status.config(text=m))

                self.exe_path = install(log)
                self.root.after(0, lambda: self.bar.config(value=100))
                self.root.after(0, lambda: self.status.config(text="安装完成！"))
                self.root.after(300, self.done)
            except Exception as e:
                self.root.after(0, lambda: self.fail(e))

        threading.Thread(target=work, daemon=True).start()

    def done(self):
        from tkinter import messagebox
        self.install_btn.config(state="normal")
        if messagebox.askyesno(APP_NAME, "安装完成！\n\n是否立即启动 " + APP_NAME + "？"):
            try:
                subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path),
                                 creationflags=0x00000008 | NO_WINDOW)
            except Exception:
                try:
                    os.startfile(self.exe_path)
                except Exception:
                    pass
        self.root.destroy()

    def fail(self, e):
        from tkinter import messagebox
        self.install_btn.config(state="normal")
        messagebox.showerror(APP_NAME, "安装失败：\n" + str(e))
        self.status.config(text="安装失败")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--silent" in sys.argv or "/S" in sys.argv or "-s" in sys.argv:
        sys.exit(silent_install())
    else:
        Installer().run()
