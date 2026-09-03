@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo 正在运行端到端演示（自动校验 15 项流程）...
echo.
python run_demo.py
pause
