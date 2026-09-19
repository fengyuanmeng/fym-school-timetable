#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包脚本：把课程表程序编译为独立 EXE"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")


def run():
    # PyInstaller 会在构建前自动清理旧产物（--noconfirm）
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "枫源梦校园课表",
        "--noconsole",
        "--onedir",
        "--noconfirm",
        "--icon", os.path.join(ROOT, "assets", "app.ico"),
        "--add-data", f"{os.path.join(ROOT, 'assets')};assets",
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        os.path.join(ROOT, "main.py"),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print("\n打包完成，可执行文件:")
    print(os.path.join(DIST, "枫源梦校园课表", "枫源梦校园课表.exe"))


if __name__ == "__main__":
    run()
