#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
屏幕图案连点器 v2.0
功能：
  1. 内置截图功能 - 点击按钮拖拽框选目标图案
  2. 多图案列表 - 支持添加多个目标，按顺序逐个点击
  3. 无限循环 / 单轮执行
  4. 全局热键 F6=开始  F7=停止
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
import pyautogui


# ========== 中文路径兼容（OpenCV imread/imwrite 不支持含中文路径）==========
def _cv2_read(path, flags=cv2.IMREAD_GRAYSCALE):
    """读取图像，兼容中文路径"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), flags)
    except Exception:
        return None


def _cv2_write(path, img):
    """保存图像，兼容中文路径"""
    try:
        _, buf = cv2.imencode(".png", img)
        with open(path, "wb") as f:
            f.write(buf)
        return True
    except Exception:
        return False
import time
import keyboard
import threading
import mss
import os
import json
from datetime import datetime

# ========== 目录配置 ==========
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)
PATTERNS_DIR = os.path.join(BASE_DIR, "patterns")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
os.makedirs(PATTERNS_DIR, exist_ok=True)


# ====================================================================
#  区域选择器（全屏半透明遮罩 + 拖拽框选）
# ====================================================================
class RegionSelector:
    """全屏半透明遮罩，鼠标拖拽框选区域"""

    def __init__(self, parent_root):
        self.region = None
        self.sx = self.sy = 0
        self.sx_root = self.sy_root = 0

        self.root = tk.Toplevel(parent_root)
        self.root.attributes("-fullscreen", True, "-topmost", True, "-alpha", 0.22)
        self.root.configure(bg="#1a1a2e")
        self.root.focus_force()
        self.root.grab_set()

        self.canvas = tk.Canvas(self.root, cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 操作提示
        sw = self.root.winfo_screenwidth()
        self.canvas.create_text(sw // 2, 24,
                                text="\U0001f5b1 按住左键拖拽框选目标  |  ESC 取消",
                                fill="white", font=("微软雅黑", 14, "bold"),
                                anchor="n")

        # 绑定事件
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.destroy())

        self.rect_id = None

    def on_press(self, event):
        self.sx, self.sy = event.x, event.y
        self.sx_root, self.sy_root = event.x_root, event.y_root
        self.canvas.delete("sel_rect")
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#00ff88", width=3, tags="sel_rect"
        )

    def on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id,
                               self.sx, self.sy,
                               event.x, event.y)

    def on_release(self, event):
        x1, y1 = self.sx_root, self.sy_root
        x2, y2 = event.x_root, event.y_root
        left, top = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)

        if w < 10 or h < 10:
            return

        self.region = (left, top, w, h)
        self.destroy()

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ====================================================================
#  主应用
# ====================================================================
class ClickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("屏幕图案连点器 v2.0")
        self.root.geometry("720x620")
        self.root.minsize(640, 540)
        self.root.configure(bg="#f0f2f5")
        self.root.attributes("-topmost", True)  # 窗口置顶

        # ---- 状态 ----
        self.running = False
        self.patterns = []          # [filename, ...] 有序
        self.sct = mss.MSS()

        # ---- 配置变量 ----
        self.confidence = tk.DoubleVar(value=0.80)
        self.click_delay = tk.DoubleVar(value=0.5)
        self.loop_mode = tk.StringVar(value="loop")   # loop | once

        # ---- 加载 ----
        self.load_config()
        self.load_patterns()

        # ---- 构建界面 ----
        self.build_ui()

        # ---- 全局热键 ----
        keyboard.add_hotkey("f6", self.start_clicking)
        keyboard.add_hotkey("f7", self.stop_clicking)

        # ---- 窗口关闭 ----
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ======================== 界面 ========================

    def build_ui(self):
        # ========== 顶栏标题 ==========
        header = tk.Frame(self.root, bg="#2c3e50", height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📸 屏幕图案连点器",
                 font=("微软雅黑", 14, "bold"), fg="white",
                 bg="#2c3e50").pack(side="left", padx=20, pady=8)
        tk.Label(header, text="F6 开始 · F7 停止",
                 font=("微软雅黑", 9), fg="#95a5a6",
                 bg="#2c3e50").pack(side="right", padx=20, pady=8)

        main = tk.Frame(self.root, bg="#f0f2f5", padx=12, pady=10)
        main.pack(fill="both", expand=True)

        # ========== 图案列表区 ==========
        tk.Label(main, text="🎯 目标图案（按顺序点击）:",
                 font=("微软雅黑", 10, "bold"),
                 bg="#f0f2f5").pack(anchor="w")

        list_frame = tk.Frame(main, bg="#f0f2f5")
        list_frame.pack(fill="both", pady=(4, 6), expand=True)

        # 列表框
        list_box_frame = tk.Frame(list_frame, bg="#f0f2f5")
        list_box_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_box_frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_box_frame, font=("微软雅黑", 10),
            yscrollcommand=scrollbar.set,
            selectmode="single", bd=1, relief="solid",
            bg="white", fg="#2c3e50",
            activestyle="none"
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Delete>", lambda e: self.remove_pattern())

        # 操作按钮
        op_frame = tk.Frame(main, bg="#f0f2f5")
        op_frame.pack(fill="x", pady=(0, 8))

        btn_style = dict(font=("微软雅黑", 9), padx=10, pady=2, bd=0, cursor="hand2")

        def make_btn(text, color, cmd, **kw):
            btn = tk.Button(op_frame, text=text, bg=color,
                            fg="white", command=cmd, **btn_style, **kw)
            btn.pack(side="left", padx=(0, 5))
            return btn

        self.btn_add = make_btn("📷 截图添加", "#3498db", self.capture_and_add)
        self.btn_remove = make_btn("🗑 删除", "#e74c3c", self.remove_pattern)
        self.btn_up = make_btn("↑ 上移", "#7f8c8d", self.move_up)
        self.btn_down = make_btn("↓ 下移", "#7f8c8d", self.move_down)
        self.btn_clear = make_btn("清空", "#95a5a6", self.clear_patterns)

        # ========== 设置 ==========
        sets = tk.LabelFrame(main, text="设置", font=("微软雅黑", 10, "bold"),
                             bg="#f0f2f5", padx=10, pady=5)
        sets.pack(fill="x", pady=(0, 8))

        # 阈值
        tk.Label(sets, text="匹配阈值:", font=("微软雅黑", 9),
                 bg="#f0f2f5").grid(row=0, column=0, sticky="w", padx=3)
        tk.Scale(sets, from_=0.50, to=0.99, resolution=0.01,
                 orient="horizontal", length=180,
                 variable=self.confidence,
                 font=("微软雅黑", 7), bg="#f0f2f5",
                 highlightthickness=0).grid(row=0, column=1, sticky="w", padx=3)
        tk.Label(sets, text="↑ 严格   宽松 ↓",
                 font=("微软雅黑", 8), fg="#999",
                 bg="#f0f2f5").grid(row=0, column=2, sticky="w")

        # 点击延迟
        tk.Label(sets, text="点击间隔:", font=("微软雅黑", 9),
                 bg="#f0f2f5").grid(row=1, column=0, sticky="w", padx=3)
        delay_frame = tk.Frame(sets, bg="#f0f2f5")
        delay_frame.grid(row=1, column=1, sticky="w", padx=3)
        tk.Scale(delay_frame, from_=0.1, to=3.0, resolution=0.1,
                 orient="horizontal", length=180,
                 variable=self.click_delay,
                 font=("微软雅黑", 7), bg="#f0f2f5",
                 highlightthickness=0).pack(side="left")
        tk.Label(delay_frame, text="秒", font=("微软雅黑", 9),
                 bg="#f0f2f5").pack(side="left", padx=5)

        # 模式
        tk.Label(sets, text="执行模式:", font=("微软雅黑", 9),
                 bg="#f0f2f5").grid(row=2, column=0, sticky="w", padx=3)
        mode_frame = tk.Frame(sets, bg="#f0f2f5")
        mode_frame.grid(row=2, column=1, sticky="w", padx=3)
        tk.Radiobutton(mode_frame, text="♾ 无限循环", variable=self.loop_mode,
                       value="loop", font=("微软雅黑", 9),
                       bg="#f0f2f5", selectcolor="white").pack(side="left")
        tk.Radiobutton(mode_frame, text="▶ 只执行一轮", variable=self.loop_mode,
                       value="once", font=("微软雅黑", 9),
                       bg="#f0f2f5", selectcolor="white").pack(side="left", padx=(20, 0))

        # ========== 控制按钮 ==========
        ctrl_frame = tk.Frame(main, bg="#f0f2f5")
        ctrl_frame.pack(fill="x", pady=(0, 6))

        self.btn_start = tk.Button(
            ctrl_frame, text="▶  开始  (F6)",
            font=("微软雅黑", 12, "bold"), bg="#27ae60", fg="white",
            padx=24, pady=6, bd=0, cursor="hand2",
            command=self.start_clicking
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        self.btn_stop = tk.Button(
            ctrl_frame, text="■  停止  (F7)",
            font=("微软雅黑", 12, "bold"), bg="#e74c3c", fg="white",
            padx=24, pady=6, bd=0, cursor="hand2", state="disabled",
            command=self.stop_clicking
        )
        self.btn_stop.pack(side="left")

        self.lbl_status = tk.Label(ctrl_frame, text="就绪",
                                   font=("微软雅黑", 9), fg="#27ae60",
                                   bg="#f0f2f5")
        self.lbl_status.pack(side="right", padx=10)

        # ========== 日志 ==========
        log_frame = tk.LabelFrame(main, text="运行日志",
                                  font=("微软雅黑", 10, "bold"),
                                  bg="#f0f2f5")
        log_frame.pack(fill="both", expand=True)

        log_scroll = tk.Scrollbar(log_frame)
        log_scroll.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_frame, font=("Consolas", 9), height=7,
            yscrollcommand=log_scroll.set,
            state="disabled", wrap="word",
            bg="#1e272e", fg="#a4b0be",
            insertbackground="white", bd=1, relief="solid"
        )
        self.log_text.pack(fill="both", expand=True)
        log_scroll.config(command=self.log_text.yview)

        # ========== 状态栏 ==========
        bar = tk.Label(self.root, text="就绪 | F6 开始连点  F7 停止",
                       font=("微软雅黑", 9), bd=1, relief="sunken",
                       anchor="w", padx=12, bg="#ecf0f1")
        bar.pack(fill="x", side="bottom")

        # 刷新列表
        self.refresh_list()

    # ======================== 图案管理 ========================

    def load_patterns(self):
        self.patterns.clear()
        if not os.path.isdir(PATTERNS_DIR):
            return
        files = sorted(f for f in os.listdir(PATTERNS_DIR) if f.endswith(".png"))
        self.patterns.extend(files)

    def refresh_list(self):
        self.listbox.delete(0, "end")
        for i, name in enumerate(self.patterns):
            path = os.path.join(PATTERNS_DIR, name)
            if os.path.exists(path):
                img = _cv2_read(path)
                if img is not None:
                    h, w = img.shape
                    self.listbox.insert("end", f"  {i+1}. {name}  ({w}x{h})")
                    continue
            self.listbox.insert("end", f"  {i+1}. {name}  (missing)")

    def get_selected_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else -1

    def capture_and_add(self):
        """截图框选区域 → 保存为图案 → 加入列表"""
        if self.running:
            messagebox.showwarning("提示", "请先停止连点")
            return

        # 不隐藏主窗口，直接弹出全屏遮罩
        selector = RegionSelector(self.root)
        self.root.wait_window(selector.root)  # 阻塞等待用户完成选择

        region = selector.region
        if not region:
            self.log("✋ 取消截图")
            return

        left, top, w, h = region
        self.log(f"📐 框选区域: ({left}, {top})  {w}x{h}")

        # 截取该区域
        raw = self.sct.grab({"left": left, "top": top,
                             "width": w, "height": h})
        gray = cv2.cvtColor(np.array(raw), cv2.COLOR_RGB2GRAY)

        # 保存
        ts = datetime.now().strftime("%H%M%S")
        filename = f"pat_{ts}.png"
        _cv2_write(os.path.join(PATTERNS_DIR, filename), gray)

        self.patterns.append(filename)
        self.refresh_list()

        self.log(f"✅ 添加图案 #{len(self.patterns)}: {filename} ({w}x{h})")
        self.save_config()

    def remove_pattern(self):
        if self.running:
            return
        idx = self.get_selected_index()
        if idx < 0:
            messagebox.showinfo("提示", "请先选中一个图案")
            return

        name = self.patterns[idx]
        path = os.path.join(PATTERNS_DIR, name)
        if os.path.exists(path):
            os.remove(path)

        del self.patterns[idx]
        self.refresh_list()
        self.log(f"🗑 删除图案: {name}")
        self.save_config()

    def move_up(self):
        if self.running:
            return
        idx = self.get_selected_index()
        if idx <= 0:
            return
        self.patterns[idx], self.patterns[idx-1] = self.patterns[idx-1], self.patterns[idx]
        self.refresh_list()
        self.listbox.select_set(idx-1)
        self.save_config()

    def move_down(self):
        if self.running:
            return
        idx = self.get_selected_index()
        if idx < 0 or idx >= len(self.patterns) - 1:
            return
        self.patterns[idx], self.patterns[idx+1] = self.patterns[idx+1], self.patterns[idx]
        self.refresh_list()
        self.listbox.select_set(idx+1)
        self.save_config()

    def clear_patterns(self):
        if self.running:
            return
        if not self.patterns:
            return
        if not messagebox.askyesno("确认", "确定清空所有图案？"):
            return

        for name in self.patterns:
            path = os.path.join(PATTERNS_DIR, name)
            if os.path.exists(path):
                os.remove(path)
        self.patterns.clear()
        self.refresh_list()
        self.log("🧹 已清空所有图案")
        self.save_config()

    # ======================== 连点逻辑 ========================

    def set_ui_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_start.config(state=state,
                              bg="#95a5a6" if busy else "#27ae60")
        self.btn_stop.config(state="normal" if busy else "disabled")
        for b in (self.btn_add, self.btn_remove, self.btn_up,
                  self.btn_down, self.btn_clear):
            b.config(state=state)
        self.lbl_status.config(text="🔄 运行中..." if busy else "就绪",
                               fg="#e74c3c" if busy else "#27ae60")

    def start_clicking(self):
        if self.running:
            return
        if not self.patterns:
            messagebox.showwarning("提示", "请先添加至少一个目标图案")
            return

        self.running = True
        self.set_ui_busy(True)

        conf = self.confidence.get()
        delay = self.click_delay.get()
        mode = self.loop_mode.get()
        self.log("=" * 40)
        self.log(f"🚀 开始连点 | 阈值={conf:.2f} 间隔={delay:.1f}s 模式={'♾循环' if mode=='loop' else '▶单轮'}")
        self.log(f"   共 {len(self.patterns)} 个图案")

        threading.Thread(target=self._worker,
                         args=(conf, delay, mode),
                         daemon=True).start()

    def stop_clicking(self):
        self.running = False
        self.log("⏹ 手动停止")

    def _worker(self, confidence, delay, mode):
        """后台工作线程"""
        loop = mode == "loop"

        while self.running:
            for idx, name in enumerate(self.patterns):
                if not self.running:
                    break

                path = os.path.join(PATTERNS_DIR, name)
                if not os.path.exists(path):
                    self.log(f"⚠ [{idx+1}] {name} 文件不存在，跳过")
                    continue

                template = _cv2_read(path)
                if template is None:
                    self.log(f"⚠ [{idx+1}] {name} 图片损坏，跳过")
                    continue

                th, tw = template.shape

                # 搜索直到找到
                searched = False
                retries = 0
                max_retries = 30  # 约 delay*30 秒后放弃

                while self.running and not searched:
                    # 截屏 + 匹配
                    monitor = self.sct.monitors[1]
                    raw = self.sct.grab(monitor)
                    screen = cv2.cvtColor(np.array(raw), cv2.COLOR_RGB2GRAY)

                    result = cv2.matchTemplate(screen, template,
                                               cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)

                    if max_val >= confidence:
                        cx = max_loc[0] + tw // 2 + monitor["left"]
                        cy = max_loc[1] + th // 2 + monitor["top"]

                        pyautogui.moveTo(cx, cy, duration=0.03)
                        pyautogui.click()
                        self.log(f"👆 [{idx+1}/{len(self.patterns)}] {name}  ({cx},{cy}) {max_val:.2f}")
                        time.sleep(0.2)  # 防止连点
                        searched = True
                    else:
                        retries += 1
                        if retries >= max_retries:
                            self.log(f"⏱ [{idx+1}/{len(self.patterns)}] {name} 未找到（已跳过）")
                            searched = True
                        else:
                            time.sleep(delay)

            # 一轮结束
            if not loop:
                self.log("✅ 全部执行完毕")
                break
            else:
                self.log("🔄 一轮执行完毕，继续循环...")

        # 恢复 UI
        self.root.after(0, self._on_finish)

    def _on_finish(self):
        self.running = False
        self.set_ui_busy(False)
        self.log("--- 停止 ---")

    # ======================== 日志 ========================

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ======================== 配置 & 关闭 ========================

    def save_config(self):
        data = {
            "confidence": round(self.confidence.get(), 2),
            "click_delay": round(self.click_delay.get(), 1),
            "loop_mode": self.loop_mode.get(),
            "patterns": self.patterns,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.confidence.set(data.get("confidence", 0.8))
            self.click_delay.set(data.get("click_delay", 0.5))
            self.loop_mode.set(data.get("loop_mode", "loop"))
        except Exception:
            pass

    def on_close(self):
        self.running = False
        self.save_config()
        self.root.destroy()


# ====================================================================
#  启动
# ====================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = ClickerApp(root)
    root.mainloop()
