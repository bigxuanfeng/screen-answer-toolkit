"""
屏幕答题助手 v1.0
功能：
  1. 框选屏幕区域 → OCR识别题目文字
  2. 发送给 DeepSeek AI 获取答案
  3. 热键：Ctrl+Shift+A 快速框选
依赖：pip install pytesseract pillow opencv-python numpy mss openai pyautogui keyboard
      + 安装 Tesseract-OCR: https://github.com/UB-Mannheim/tesseract/wiki (下载安装)
"""

# ========== 高 DPI 适配 ==========
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Per-Monitor DPI
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
import os
import json
import threading
import time
from datetime import datetime

# ========== 可选依赖 ==========
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

# ========== 配置 ==========
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__) or "."
CONFIG_FILE = os.path.join(BASE_DIR, "answer_config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ========== 区域选择器（复用连点器的逻辑） ==========
class RegionSelector:
    def __init__(self, parent_root):
        self.region = None
        self.sx = self.sy = 0
        self.sx_root = self.sy_root = 0

        self.root = tk.Toplevel(parent_root)
        self.root.attributes("-fullscreen", True, "-topmost", True, "-alpha", 0.22)
        self.root.configure(bg="#1a1a2e")
        self.root.focus_force()
        self.root.grab_set()

        self.canvas = tk.Canvas(self.root, cursor="crosshair", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        sw = self.root.winfo_screenwidth()
        self.canvas.create_text(sw // 2, 24,
                                text="\U0001f5b1 拖拽框选题目区域  |  ESC 取消",
                                fill="white", font=("微软雅黑", 14, "bold"), anchor="n")

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
            outline="#00ff88", width=3, tags="sel_rect")

    def on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.sx, self.sy, event.x, event.y)

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


# ========== 镂空区域确认窗口（多窗口拼合，兼容性好） ==========
class RegionConfirmOverlay:
    """用多个半透明窗口围出镂空区域 + 绿色边框 + 底部按钮"""
    def __init__(self, parent_root, region):
        self.region = region
        self.confirmed = False
        self._wins = []

        left, top, w, h = region
        sw = parent_root.winfo_screenwidth()
        sh = parent_root.winfo_screenheight()

        # 4 个半透明遮罩条围出中间镂空区域
        self._add_strip(0, 0, sw, top)                     # 顶上
        self._add_strip(0, top + h, sw, sh - top - h)      # 底下
        self._add_strip(0, top, left, h)                   # 左边
        self._add_strip(left + w, top, sw - left - w, h)    # 右边

        # 绿色边框（4 根细条）
        bw = 3
        self._add_border(left - bw, top - bw, w + bw * 2, bw)           # 上
        self._add_border(left - bw, top + h, w + bw * 2, bw)            # 下
        self._add_border(left - bw, top, bw, h)                          # 左
        self._add_border(left + w, top, bw, h)                           # 右

        # 底部按钮栏
        bar = tk.Toplevel(parent_root)
        bar.attributes("-topmost", True, "-alpha", 0.92)
        bar.overrideredirect(True)
        bar.configure(bg="#1a1a2e")
        bar.geometry(f"{sw}x72+0+{sh - 72}")
        bar.focus_force()
        bar.grab_set()
        self.root = bar  # 供 wait_window 使用

        btn_frame = tk.Frame(bar, bg="#1a1a2e")
        btn_frame.pack(expand=True)

        tk.Button(btn_frame, text="\u2713 确认答题", font=("微软雅黑", 14, "bold"),
                  bg="#27ae60", fg="white", bd=0, padx=32, pady=8, cursor="hand2",
                  command=self._on_confirm).pack(side="left", padx=12)
        tk.Button(btn_frame, text="\u2716 取消", font=("微软雅黑", 14, "bold"),
                  bg="#7f8c8d", fg="white", bd=0, padx=32, pady=8, cursor="hand2",
                  command=self._on_cancel).pack(side="left", padx=12)

        bar.bind("<Escape>", self._on_cancel)
        bar.bind("<Return>", self._on_confirm)
        self._wins.append(bar)

    def _add_strip(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return
        win = tk.Toplevel()
        win.attributes("-topmost", True, "-alpha", 0.65)
        win.overrideredirect(True)
        win.configure(bg="#1a1a2e")
        win.geometry(f"{w}x{h}+{x}+{y}")
        self._wins.append(win)

    def _add_border(self, x, y, w, h):
        if w <= 0 or h <= 0:
            return
        win = tk.Toplevel()
        win.attributes("-topmost", True, "-alpha", 0.9)
        win.overrideredirect(True)
        win.configure(bg="#00ff88")
        win.geometry(f"{w}x{h}+{x}+{y}")
        self._wins.append(win)

    def _on_confirm(self, event=None):
        self.confirmed = True
        self.destroy()

    def _on_cancel(self, event=None):
        self.destroy()

    def destroy(self):
        for w in self._wins:
            try:
                w.destroy()
            except Exception:
                pass


# ========== 可拖拽缩放的固定边框 ==========
class PersistentBorder:
    """可拖拽移动 + 四角缩放的固定截图边框 + 浮动工具栏"""
    def __init__(self, app, region):
        self.app = app
        self._bw = 4
        left, top, w, h = region
        left, top = int(left), int(top)
        w, h = int(w), int(h)
        self._region = (left, top, w, h)

        cw, ch = w + self._bw * 2, h + self._bw * 2

        self.root = tk.Toplevel()
        self.root.attributes("-topmost", True, "-alpha", 0.10)
        self.root.overrideredirect(True)
        self.root.configure(bg="#00ff88")
        self.root.geometry(f"{cw}x{ch}+{left - self._bw}+{top - self._bw}")

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg="#00ff88",
                                cursor="fleur")
        self.canvas.pack(fill="both", expand=True)

        # 绿色边框
        self._border_id = self.canvas.create_rectangle(
            0, 0, cw, ch, outline="#00ff88", width=self._bw * 2)

        # 四角缩放把手
        hs = 12
        self._handle_tags = {
            "nw": (0, 0, hs, hs),
            "ne": (cw - hs, 0, cw, hs),
            "sw": (0, ch - hs, hs, ch),
            "se": (cw - hs, ch - hs, cw, ch),
        }
        for tag, coords in self._handle_tags.items():
            hid = self.canvas.create_rectangle(*coords,
                                               fill="#00ff88", outline="#00cc66",
                                               width=1, tags=("handle", tag))

        # 把手悬停光标
        self.canvas.tag_bind("handle", "<Enter>",
                             lambda e, t=tag: self.canvas.config(cursor=self._cursor_for(t)))
        self.canvas.tag_bind("handle", "<Leave>",
                             lambda e: self.canvas.config(cursor="fleur"))

        # 拖拽事件
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._drag = {"x": 0, "y": 0, "mode": None}

        # 浮动工具栏
        self._toolbar = self._create_toolbar()

    def _cursor_for(self, tag):
        return {"nw": "size_nw_se", "se": "size_nw_se",
                "ne": "size_ne_sw", "sw": "size_ne_sw"}.get(tag, "fleur")

    def _create_toolbar(self):
        bar = tk.Toplevel()
        bar.attributes("-topmost", True, "-alpha", 0.92)
        bar.overrideredirect(True)
        bar.configure(bg="#1a1a2e")

        btn_frame = tk.Frame(bar, bg="#1a1a2e")
        btn_frame.pack(padx=3, pady=3)

        tk.Button(btn_frame, text="\U0001f4f8 截图", font=("微软雅黑", 10, "bold"),
                  bg="#e67e22", fg="white", bd=0, padx=10, pady=3, cursor="hand2",
                  command=self._capture).pack(side="left", padx=2)
        tk.Button(btn_frame, text="\u2715", font=("微软雅黑", 10, "bold"),
                  bg="#e74c3c", fg="white", bd=0, padx=8, pady=3, cursor="hand2",
                  command=self.app.clear_region).pack(side="left", padx=2)

        self._position_toolbar(bar)
        return bar

    def _position_toolbar(self, bar=None):
        if bar is None:
            bar = self._toolbar
        bar.update_idletasks()
        bar_w = bar.winfo_width()
        bar_h = bar.winfo_height()
        l, t, w, h = self._region
        bar_x = max(0, l + w // 2 - bar_w // 2)
        bar_y = max(0, t - bar_h - 6)
        bar.geometry(f"+{bar_x}+{bar_y}")

    def _on_press(self, event):
        self._drag["x"] = event.x_root
        self._drag["y"] = event.y_root
        # 判断是否在把手上
        overlapping = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        for oid in overlapping:
            tags = self.canvas.gettags(oid)
            for tag in tags:
                if tag in ("nw", "ne", "sw", "se"):
                    self._drag["mode"] = tag
                    return
        self._drag["mode"] = "move"

    def _on_drag(self, event):
        if not self._drag["mode"]:
            return
        dx = event.x_root - self._drag["x"]
        dy = event.y_root - self._drag["y"]
        self._drag["x"] = event.x_root
        self._drag["y"] = event.y_root

        mode = self._drag["mode"]
        if mode == "move":
            nx = self.root.winfo_x() + dx
            ny = self.root.winfo_y() + dy
            self.root.geometry(f"+{nx}+{ny}")
            self._toolbar.geometry(
                f"+{self._toolbar.winfo_x() + dx}+{self._toolbar.winfo_y() + dy}")
            self._sync_from_window()
        else:
            self._resize(mode, dx, dy)

    def _resize(self, corner, dx, dy):
        l, t, w, h = self._region
        bw = self._bw
        if "w" in corner:
            l += dx; w -= dx
        if "e" in corner:
            w += dx
        if "n" in corner:
            t += dy; h -= dy
        if "s" in corner:
            h += dy
        w = max(20, w)
        h = max(20, h)
        self._region = (l, t, w, h)
        self.root.geometry(f"{w + bw*2}x{h + bw*2}+{l - bw}+{t - bw}")

    def _on_release(self, event):
        self._drag["mode"] = None
        self._sync_from_window()
        self._save_region()
        self._position_toolbar()
        # 重绘把手位置
        self.canvas.delete("handle")
        cw = self.root.winfo_width()
        ch = self.root.winfo_height()
        hs = 12
        for tag, coords in [
            ("nw", (0, 0, hs, hs)),
            ("ne", (cw - hs, 0, cw, hs)),
            ("sw", (0, ch - hs, hs, ch)),
            ("se", (cw - hs, ch - hs, cw, ch)),
        ]:
            self.canvas.create_rectangle(*coords,
                                         fill="#00ff88", outline="#00cc66",
                                         width=1, tags=("handle", tag))

    def _sync_from_window(self):
        bw = self._bw
        x = self.root.winfo_x() + bw
        y = self.root.winfo_y() + bw
        w = self.root.winfo_width() - bw * 2
        h = self.root.winfo_height() - bw * 2
        self._region = (x, y, w, h)

    def _save_region(self):
        region = self._region
        self.app.saved_region = region
        self.app.config["saved_region"] = list(int(v) for v in region)
        save_config(self.app.config)
        self.app._update_region_display()

    def _capture(self):
        self._save_region()
        if self.app.saved_region:
            self.app.answer_text.delete("1.0", "end")
            self.app.ocr_text.delete("1.0", "end")
            self.app.log(f"\U0001f4f8 截图区域: {self.app.saved_region}")
            self.app._process_region(self.app.saved_region)

    def destroy(self):
        try:
            self._toolbar.destroy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ========== 主应用 ==========
class AnswerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("屏幕答题助手 v1.0")
        self.root.geometry("750x720")
        self.root.minsize(600, 650)
        self.root.attributes("-topmost", True)

        self.config = load_config()
        self.saved_region = self.config.get("saved_region", None)
        self._persistent_border = None  # PersistentBorder 实例
        self.sct = mss.MSS() if HAS_MSS else None
        self.ai_client = None
        self._init_ai()

        self.build_ui()
        self.load_config_ui()

        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("ctrl+shift+a", self.quick_capture)
            except Exception:
                pass

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _init_ai(self):
        api_key = self.config.get("api_key", "")
        base_url = self.config.get("base_url", "https://api.deepseek.com")
        model = self.config.get("model", "deepseek-v4-flash")
        if api_key and HAS_OPENAI:
            self.ai_client = OpenAI(api_key=api_key, base_url=base_url)
            self.config["model"] = model

    # ==================== UI ====================

    def build_ui(self):
        # 标题
        header = tk.Frame(self.root, bg="#2c3e50", height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="\U0001f4d6 屏幕答题助手",
                 font=("微软雅黑", 17, "bold"), fg="white", bg="#2c3e50").pack(side="left", padx=16, pady=8)
        tk.Label(header, text="Ctrl+Shift+A 截图识别",
                 font=("微软雅黑", 11), fg="#95a5a6", bg="#2c3e50").pack(side="right", padx=16, pady=8)

        main = tk.Frame(self.root, bg="#f0f2f5", padx=12, pady=8)
        main.pack(fill="both", expand=True)

        # ===== API 配置 =====
        api_frame = tk.LabelFrame(main, text="AI 配置", font=("微软雅黑", 11, "bold"), bg="#f0f2f5", padx=8, pady=4)
        api_frame.pack(fill="x", pady=(0, 6))

        tk.Label(api_frame, text="API Key:", font=("微软雅黑", 11), bg="#f0f2f5").grid(row=0, column=0, sticky="e", padx=3)
        self.api_key_var = tk.StringVar()
        tk.Entry(api_frame, textvariable=self.api_key_var, font=("微软雅黑", 11), width=42,
                 show="*").grid(row=0, column=1, sticky="w", padx=3)

        tk.Label(api_frame, text="Base URL:", font=("微软雅黑", 11), bg="#f0f2f5").grid(row=1, column=0, sticky="e", padx=3)
        self.base_url_var = tk.StringVar(value="https://api.deepseek.com")
        tk.Entry(api_frame, textvariable=self.base_url_var, font=("微软雅黑", 11), width=42).grid(row=1, column=1, sticky="w", padx=3)

        tk.Label(api_frame, text="Model:", font=("微软雅黑", 11), bg="#f0f2f5").grid(row=2, column=0, sticky="e", padx=3)
        self.model_var = tk.StringVar(value="deepseek-v4-flash")
        tk.Entry(api_frame, textvariable=self.model_var, font=("微软雅黑", 11), width=42).grid(row=2, column=1, sticky="w", padx=3)

        btn_row = tk.Frame(api_frame, bg="#f0f2f5")
        btn_row.grid(row=3, column=1, sticky="w", pady=(4, 0))
        tk.Button(btn_row, text="保存配置", font=("微软雅黑", 11), bg="#3498db", fg="white", bd=0, padx=10,
                  command=self.save_api_config).pack(side="left", padx=(0, 8))
        self.api_status = tk.Label(btn_row, text="未配置", font=("微软雅黑", 11), fg="#e74c3c", bg="#f0f2f5")
        self.api_status.pack(side="left")

        # ===== OCR 状态 =====
        ocr_frame = tk.Frame(main, bg="#f0f2f5")
        ocr_frame.pack(fill="x", pady=(0, 6))
        tesseract_ok = self._check_tesseract()
        self.ocr_status = tk.Label(ocr_frame,
                                   text=f"OCR: {'\u2705 Tesseract 就绪' if tesseract_ok else '\u274c 未检测到 Tesseract'}",
                                   font=("微软雅黑", 11), fg="#27ae60" if tesseract_ok else "#e74c3c", bg="#f0f2f5")
        self.ocr_status.pack(side="left")
        if not tesseract_ok:
            tk.Label(ocr_frame, text="  (需安装: winget install UB-Mannheim.TesseractOCR)", font=("微软雅黑", 10),
                     fg="#999", bg="#f0f2f5").pack(side="left")

        # ===== OCR 结果 =====
        ocr_res_frame = tk.LabelFrame(main, text="识别文字", font=("微软雅黑", 11, "bold"), bg="#f0f2f5", padx=8, pady=4)
        ocr_res_frame.pack(fill="x", pady=(0, 6))
        self.ocr_text = tk.Text(ocr_res_frame, font=("微软雅黑", 18), height=5, wrap="word")
        self.ocr_text.pack(fill="x")

        # OCR 文字操作按钮
        ocr_btn_row = tk.Frame(ocr_res_frame, bg="#f0f2f5")
        ocr_btn_row.pack(fill="x", pady=(4, 0))
        self.btn_capture = tk.Button(ocr_btn_row, text="\U0001f4f8 截图识别",
                                     font=("微软雅黑", 11, "bold"), bg="#e67e22", fg="white",
                                     padx=14, pady=4, bd=0, cursor="hand2",
                                     command=self.quick_capture)
        self.btn_capture.pack(side="left", padx=(0, 6))
        tk.Button(ocr_btn_row, text="\U0001f310 翻译成中文", font=("微软雅黑", 10),
                  bg="#8e44ad", fg="white", bd=0, padx=10, pady=4, cursor="hand2",
                  command=self.translate_text).pack(side="left", padx=(0, 6))
        tk.Button(ocr_btn_row, text="\U0001f4ac 回答", font=("微软雅黑", 10, "bold"),
                  bg="#27ae60", fg="white", bd=0, padx=14, pady=4, cursor="hand2",
                  command=self.answer_question).pack(side="left", padx=(0, 6))
        tk.Button(ocr_btn_row, text="\U0001f4cb 复制", font=("微软雅黑", 10),
                  bg="#555", fg="white", bd=0, padx=10, pady=4, cursor="hand2",
                  command=self.copy_ocr_text).pack(side="left")

        # ===== AI 答案 =====
        ans_frame = tk.LabelFrame(main, text="AI 答案", font=("微软雅黑", 11, "bold"), bg="#f0f2f5", padx=8, pady=4)
        ans_frame.pack(fill="both", expand=True, pady=(0, 6))
        self.answer_text = tk.Text(ans_frame, font=("微软雅黑", 18), wrap="word",
                                   bg="#1e272e", fg="#d2dae2",
                                   insertbackground="white", bd=1, relief="solid")
        self.answer_text.pack(fill="both", expand=True)

        # ===== 固定区域信息 =====
        region_frame = tk.Frame(main, bg="#f0f2f5")
        region_frame.pack(fill="x", pady=(0, 6))
        self.region_label = tk.Label(region_frame, text="\U0001f4cd 固定区域: 未设置",
                                     font=("微软雅黑", 11), bg="#f0f2f5", fg="#555")
        self.region_label.pack(side="left")
        self.btn_clear_region = tk.Button(region_frame, text="清除", font=("微软雅黑", 10),
                                          bd=0, fg="#999", bg="#f0f2f5", cursor="hand2",
                                          command=self.clear_region)
        self.btn_clear_region.pack(side="left", padx=(8, 0))

        # ===== 操作按钮 =====
        btn_frame = tk.Frame(main, bg="#f0f2f5")
        btn_frame.pack(fill="x")
        self.btn_select = tk.Button(btn_frame, text="\U0001f5b1 框选截图区域",
                                    font=("微软雅黑", 13), bg="#3498db", fg="white",
                                    padx=16, pady=8, bd=0, cursor="hand2",
                                    command=self.select_region_only)
        self.btn_select.pack(side="left", padx=(0, 8))
        self.btn_answer = tk.Button(btn_frame, text="\U0001f4ac 重新作答",
                                    font=("微软雅黑", 13), bg="#27ae60", fg="white",
                                    padx=16, pady=8, bd=0, cursor="hand2",
                                    command=self.re_answer)
        self.btn_answer.pack(side="left")

    def _check_tesseract(self):
        if not HAS_TESSERACT:
            return False
        import shutil as _shutil
        found = None
        for path in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Users\linxuan\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        ]:
            if os.path.exists(path):
                found = path
                break
        if not found:
            found = _shutil.which("tesseract")
        if not found:
            return False

        pytesseract.pytesseract.tesseract_cmd = found

        # 用户可写目录存放语言包（避免 Program Files 权限问题）
        user_tessdata = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "tesseract_tessdata")
        os.makedirs(user_tessdata, exist_ok=True)
        os.environ["TESSDATA_PREFIX"] = user_tessdata

        # 复制 eng.traineddata（如果用户目录没有）
        default_tessdata = os.path.join(os.path.dirname(found), "tessdata")
        eng_src = os.path.join(default_tessdata, "eng.traineddata")
        eng_dst = os.path.join(user_tessdata, "eng.traineddata")
        if os.path.exists(eng_src) and not os.path.exists(eng_dst):
            _shutil.copy2(eng_src, eng_dst)

        # 检查中文语言包，缺失则自动下载
        chi_sim_path = os.path.join(user_tessdata, "chi_sim.traineddata")
        if not os.path.exists(chi_sim_path):
            self.root.after(500, lambda: self.log("中文语言包缺失，正在自动下载..."))
            self.root.after(500, lambda: threading.Thread(
                target=self._download_chi_sim, args=(user_tessdata,), daemon=True).start())
        return True

    def _download_chi_sim(self, tessdata_dir):
        import urllib.request
        dest = os.path.join(tessdata_dir, "chi_sim.traineddata")
        # 多镜像尝试（国内可用 CDN 优先）
        urls = [
            "https://gh-proxy.com/https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata",
            "https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata@main/chi_sim.traineddata",
            "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/chi_sim.traineddata",
        ]
        for url in urls:
            try:
                self.root.after(0, lambda u=url: self.log(f"下载中... (~15MB，首次需要等待)"))
                urllib.request.urlretrieve(url, dest)
                # 验证大小（正常约 15MB）
                if os.path.getsize(dest) > 1000000:
                    self.root.after(0, lambda: self.log("\u2705 中文语言包下载完成"))
                    return
                else:
                    os.remove(dest)
            except Exception:
                if os.path.exists(dest) and os.path.getsize(dest) < 1000000:
                    os.remove(dest)
                continue
        self.root.after(0, lambda: self.log(
            f"\u26a0 自动下载失败，请手动下载 chi_sim.traineddata 放到 {tessdata_dir}"))

    def load_config_ui(self):
        self.api_key_var.set(self.config.get("api_key", ""))
        self.base_url_var.set(self.config.get("base_url", "https://api.deepseek.com"))
        self.model_var.set(self.config.get("model", "deepseek-v4-flash"))
        if self.ai_client:
            self.api_status.config(text="\u2705 已配置", fg="#27ae60")
        self._update_region_display()
        if self.saved_region:
            self.show_persistent_border()

    # ==================== 业务逻辑 ====================

    def log(self, msg):
        if not hasattr(self, "answer_text"):
            return  # UI 还没构建完，跳过
        self.answer_text.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.answer_text.see("end")

    def save_api_config(self):
        self.config["api_key"] = self.api_key_var.get()
        self.config["base_url"] = self.base_url_var.get()
        self.config["model"] = self.model_var.get()
        save_config(self.config)
        self._init_ai()
        if self.ai_client:
            self.api_status.config(text="\u2705 已配置", fg="#27ae60")
            self.log("API 配置已保存")
        else:
            self.api_status.config(text="\u26a0\ufe0f 配置不完整", fg="#e67e22")

    def select_region_only(self):
        """框选区域并固定保存（仅设置区域，不识别）"""
        if not HAS_MSS:
            messagebox.showerror("缺少依赖", "请安装 mss: pip install mss")
            return

        self.root.update()

        selector = RegionSelector(self.root)
        self.root.wait_window(selector.root)

        region = selector.region
        if not region:
            self.log("\u2716 已取消")
            return

        # 保存区域到配置
        self.saved_region = region
        self.config["saved_region"] = list(region)
        save_config(self.config)
        self._update_region_display()

        # 弹出镂空确认窗口（只确认区域范围，不处理）
        overlay = RegionConfirmOverlay(self.root, region)
        self.root.wait_window(overlay.root)

        if overlay.confirmed:
            self.show_persistent_border()
            self.log(f"\u2705 区域已固定: {region}，点击「截图识别」开始答题")
        else:
            self.log("\u2716 已取消")

    def _process_region(self, region):
        left, top, w, h = region
        raw = self.sct.grab({"left": left, "top": top, "width": w, "height": h})
        img_bgr = cv2.cvtColor(np.array(raw), cv2.COLOR_RGBA2BGR)

        # OCR
        text = self._ocr(img_bgr)
        self.root.after(0, lambda: self.ocr_text.insert("1.0", text))
        self.log(f"OCR 识别完成 ({len(text)} 字)")

        if not text.strip():
            self.log("\u26a0 OCR 未识别到文字，请检查截图区域或安装 Tesseract")

    def _ocr(self, img_bgr):
        if self._check_tesseract():
            # 中文 OCR：原始灰度 + 降噪，不二值化（避免笔画断裂）
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            # 放大图像提高小字识别率
            h, w = gray.shape
            if w < 500:
                gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            try:
                text = pytesseract.image_to_string(gray, lang="chi_sim+eng",
                                                    config="--psm 6")
            except pytesseract.TesseractError as e:
                return f"(中文语言包缺失: {e})\n请下载 chi_sim.traineddata 放到 Tesseract 的 tessdata 目录"
            return text.strip()
        else:
            return "(Tesseract 未安装，无法 OCR。请在终端执行: winget install UB-Mannheim.TesseractOCR)"

    def _ask_ai(self, question):
        try:
            response = self.ai_client.chat.completions.create(
                model=self.config.get("model", "deepseek-v4-flash"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是答题助手。用户通过OCR扫描了一道题目，请根据题目内容给出准确答案。\n\n"
                            "要求：\n"
                            "1. 先用简短的话给出最终答案\n"
                            "2. 选择题标注选项\n"
                            "3. 如有必要，简要解释解题思路\n"
                            "4. 用清晰易读的中文回答"
                        )
                    },
                    {"role": "user", "content": f"请回答以下题目：\n\n{question}"}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            answer = response.choices[0].message.content
        except Exception as e:
            answer = f"AI 请求失败: {e}"

        self.root.after(0, lambda: self._show_answer(answer))

    def _show_answer(self, answer):
        self.answer_text.delete("1.0", "end")
        self.answer_text.insert("1.0", answer)
        self.log("AI 回答完成")

    def confirm_and_process(self):
        """使用已固定的区域 → 弹出镂空确认窗口 → OCR → AI"""
        if not self.saved_region:
            self.log("\u26a0 请先框选截图区域")
            return

        # 弹出镂空确认窗口
        overlay = RegionConfirmOverlay(self.root, self.saved_region)
        self.root.wait_window(overlay.root)

        if not overlay.confirmed:
            self.log("\u2716 已取消")
            return

        self.answer_text.delete("1.0", "end")
        self.ocr_text.delete("1.0", "end")
        self.log(f"使用固定区域: {self.saved_region}")
        self._process_region(self.saved_region)

    def quick_capture(self):
        """截图识别：已固定区域直接识别，未固定则先框选"""
        if not HAS_MSS:
            messagebox.showerror("缺少依赖", "请安装 mss: pip install mss")
            return

        # 如果已有固定边框，直接识别
        if self.saved_region and self._persistent_border:
            self.answer_text.delete("1.0", "end")
            self.ocr_text.delete("1.0", "end")
            self.log(f"\U0001f4f8 截图区域: {self.saved_region}")
            self._process_region(self.saved_region)
            return

        self.root.update()
        selector = RegionSelector(self.root)
        self.root.wait_window(selector.root)

        region = selector.region
        if not region:
            self.log("\u2716 已取消")
            return

        # 保存区域
        self.saved_region = region
        self.config["saved_region"] = list(region)
        save_config(self.config)
        self._update_region_display()

        # 镂空确认窗口
        overlay = RegionConfirmOverlay(self.root, region)
        self.root.wait_window(overlay.root)

        if not overlay.confirmed:
            self.log("\u2716 已取消")
            return

        # 显示固定边框并开始识别
        self.show_persistent_border()
        self.answer_text.delete("1.0", "end")
        self.ocr_text.delete("1.0", "end")
        self.log(f"\U0001f4f8 截图区域: {region}")
        self._process_region(self.saved_region)

    def _update_region_display(self):
        if self.saved_region:
            l, t, w, h = self.saved_region
            self.region_label.config(
                text=f"\U0001f4cd 固定区域: 左={l} 顶={t} 宽={w} 高={h}",
                fg="#27ae60")
        else:
            self.region_label.config(text="\U0001f4cd 固定区域: 未设置", fg="#555")

    def clear_region(self):
        self.saved_region = None
        self.config.pop("saved_region", None)
        save_config(self.config)
        self.hide_persistent_border()
        self._update_region_display()
        self.log("\u2716 已清除固定区域")

    def show_persistent_border(self):
        """显示可拖拽缩放 + 浮动工具栏的固定边框"""
        self.hide_persistent_border()
        if not self.saved_region:
            return
        self._persistent_border = PersistentBorder(self, self.saved_region)

    def hide_persistent_border(self):
        if self._persistent_border:
            self._persistent_border.destroy()
            self._persistent_border = None

    def re_answer(self):
        text = self.ocr_text.get("1.0", "end").strip()
        if not text:
            self.log("请先框选并识别题目")
            return
        if not self.ai_client:
            self.log("请先配置 API Key")
            return
        self.answer_text.delete("1.0", "end")
        self.log("重新请求 AI...")
        threading.Thread(target=self._ask_ai, args=(text,), daemon=True).start()

    def copy_ocr_text(self):
        """复制识别文字到剪贴板"""
        text = self.ocr_text.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.log("\U0001f4cb 已复制到剪贴板")

    def edit_and_re_answer(self):
        """使用 OCR 框中修改后的文字重新请求 AI"""
        text = self.ocr_text.get("1.0", "end").strip()
        if not text:
            self.log("识别文字为空")
            return
        if not self.ai_client:
            self.log("\u26a0 请先配置 API Key")
            return
        self.answer_text.delete("1.0", "end")
        self.log("使用修改后的文字重新请求 AI...")
        threading.Thread(target=self._ask_ai, args=(text,), daemon=True).start()

    def answer_question(self):
        """用当前识别文字请求 AI 回答"""
        text = self.ocr_text.get("1.0", "end").strip()
        if not text:
            self.log("识别文字为空")
            return
        if not self.ai_client:
            self.log("\u26a0 请先配置 API Key")
            return
        self.answer_text.delete("1.0", "end")
        self.log("正在请求 AI...")
        threading.Thread(target=self._ask_ai, args=(text,), daemon=True).start()

    def translate_text(self):
        """将识别文字翻译成中文"""
        text = self.ocr_text.get("1.0", "end").strip()
        if not text:
            self.log("识别文字为空")
            return
        if not self.ai_client:
            self.log("\u26a0 请先配置 API Key")
            return
        self.log("正在翻译成中文...")
        threading.Thread(target=self._ask_translate, args=(text,), daemon=True).start()

    def _ask_translate(self, text):
        try:
            response = self.ai_client.chat.completions.create(
                model=self.config.get("model", "deepseek-v4-flash"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个翻译助手。请将用户输入的文字翻译成中文。\n\n"
                            "要求：\n"
                            "1. 如果输入全部由中文字符组成（不含任何英文、日文、韩文等），直接原样返回，不加任何说明\n"
                            "2. 如果输入包含非中文内容，翻译为中文并输出\n"
                            "3. 保持原文语气和风格\n"
                            "4. 遇到无法翻译的专有名词（人名、品牌、地名等），用方括号标注原文\n"
                            "5. 只输出翻译结果，不要加任何解释或说明"
                        )
                    },
                    {"role": "user", "content": text}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            result = response.choices[0].message.content
            self.root.after(0, lambda: self._set_ocr_text(result, text))
        except Exception as e:
            self.root.after(0, lambda: self.log(f"翻译失败: {e}"))

    def _set_ocr_text(self, result, original):
        result_clean = result.strip()
        import re
        has_foreign = bool(re.search(r'[a-zA-Z\u3040-\u30ff\uac00-\ud7af]', original))
        if not has_foreign:
            self.log("\u2139\ufe0f 已是中文，无需翻译")
            return
        self.ocr_text.delete("1.0", "end")
        self.ocr_text.insert("1.0", result_clean)
        # 检查翻译结果是否还有残留的非中文内容（专有名词等）
        still_foreign = bool(re.search(r'[a-zA-Z\u3040-\u30ff\uac00-\ud7af]', result_clean))
        if still_foreign:
            self.log("\u26a0\ufe0f 翻译完成，但可能包含无法翻译的专有名词")
        else:
            self.log("\u2705 翻译完成")

    def on_close(self):
        self.hide_persistent_border()
        save_config(self.config)
        self.root.destroy()


# ========== 启动 ==========
if __name__ == "__main__":
    root = tk.Tk()
    app = AnswerApp(root)
    root.mainloop()
