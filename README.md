# 屏幕答题与自动化工具箱

OCR识别 + DeepSeek AI答题 + 多语言翻译 + OpenCV图案匹配连点器

## 快速开始

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 安装 Tesseract-OCR（必需，一步完成）
```bash
winget install UB-Mannheim.TesseractOCR
```
首次运行软件时，中文语言包会**自动下载**，无需手动操作。

### 3. 启动
双击 `launcher.pyw`（无终端窗口）或 `launch.bat`

## 功能

| 工具 | 功能 |
|------|------|
| 📖 屏幕答题助手 | 框选屏幕区域 → OCR识别 → AI答题 → 多语言翻译成中文 |
| 🖱 屏幕连点器 | 截图目标图案 → 自动匹配点击 → 支持多目标循环 |

## 配置

首次使用答题助手需要配置 DeepSeek API Key：
- 打开软件 → 填入 API Key → 保存

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+A` | 框选截图识别 |
| `F6` | 连点器开始 |
| `F7` | 连点器停止 |
