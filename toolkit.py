"""
工具箱 - 单文件入口（供 PyInstaller 打包）
运行方式：toolkit.exe          → 启动器
         toolkit.exe answer  → 答题助手
         toolkit.exe clicker → 连点器
"""
import sys
import os
import subprocess
import tkinter as tk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_answer():
    import answer
    root = tk.Tk()
    answer.AnswerApp(root)
    root.mainloop()


def run_clicker():
    import main
    root = tk.Tk()
    main.ClickerApp(root)
    root.mainloop()


def run_launcher():
    root = tk.Tk()
    root.title("工具箱")
    root.geometry("400x360")
    root.configure(bg="#f0f2f5")
    root.resizable(False, False)

    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - 400) // 2
    y = (sh - 360) // 2
    root.geometry(f"+{x}+{y}")

    tk.Label(root, text="\U0001f6e0\ufe0f 工具箱",
             font=("微软雅黑", 26, "bold"), fg="#2c3e50", bg="#f0f2f5").pack(pady=(30, 8))

    tk.Label(root, text="选择一个工具启动",
             font=("微软雅黑", 14), fg="#7f8c8d", bg="#f0f2f5").pack(pady=(0, 20))

    def launch(tool):
        root.withdraw()
        subprocess.run([sys.executable, tool], cwd=BASE_DIR)
        root.deiconify()
        root.lift()
        root.focus_force()

    tk.Button(root, text="\U0001f4d6  屏幕答题助手\nOCR识别 + AI答题",
              font=("微软雅黑", 15), bg="#3498db", fg="white",
              width=24, height=3, bd=0, cursor="hand2",
              activebackground="#2980b9",
              command=lambda: launch("answer")).pack(pady=8)

    tk.Button(root, text="\U0001f5b1  屏幕连点器\n图案匹配自动点击",
              font=("微软雅黑", 15), bg="#e67e22", fg="white",
              width=24, height=3, bd=0, cursor="hand2",
              activebackground="#d35400",
              command=lambda: launch("clicker")).pack(pady=8)

    tk.Label(root, text="关闭此窗口即退出", font=("微软雅黑", 10),
             fg="#bdc3c7", bg="#f0f2f5").pack(side="bottom", pady=10)

    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        tool = sys.argv[1]
        if tool == "answer":
            run_answer()
        elif tool == "clicker":
            run_clicker()
        else:
            run_launcher()
    else:
        run_launcher()
