# 屏幕答题与自动化工具箱

OCR识别 + DeepSeek AI答题 + 多语言翻译 + OpenCV图案匹配连点器

## 快速开始

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 安装 Tesseract-OCR（必需）
```bash
winget install UB-Mannheim.TesseractOCR
```
首次运行软件时，中文语言包会**自动下载**，无需手动操作。

### 3. 启动
直接双击 `dist\工具箱.exe` 即可运行。

### 4. 自行打包（可选）
如需重新生成 `工具箱.exe`：
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name 工具箱 toolkit.py
```

## 功能

### 📖 屏幕答题助手 (`answer.py`)
- 框选屏幕区域 → OCR识别文字 → DeepSeek AI答题 → 多语言翻译成中文
- **保留截图框开关**：截图识别后可选择是否保留区域边框，方便连续截图
- 支持快捷键 `Ctrl+Shift+A` 快速截图识别

### 🖱 屏幕连点器 (`main.py`)
- 截图目标图案 → OpenCV模板匹配 → 自动点击 → 支持多目标循环
- **连续截图模式**：开启后可连续框选多个图案，无需反复点击添加
- **循环间隔调节**：每轮执行完毕后的等待时间可调（0.1~30秒）
- **循环/单轮模式**：支持无限循环或执行一轮即停
- 配置自动保存，下次启动自动恢复
- 支持快捷键 `F6` 开始 / `F7` 停止

## 配置

首次使用答题助手需要配置 DeepSeek API Key：
- 打开软件 → 填入 API Key → 保存

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+A` | 框选截图识别 |
| `F6` | 连点器开始 |
| `F7` | 连点器停止 |
