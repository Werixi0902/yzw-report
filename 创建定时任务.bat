@echo off
chcp 65001 >nul
echo ===================================================
echo   创建 Windows 定时任务 - 每日考勤推送
echo ===================================================
echo.

set PYTHON=C:\Users\Yuan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
set SCRIPT=C:\Users\Yuan\Documents\云筑网劳务实名制数据抓取\main.py

echo Python: %PYTHON%
echo 脚本: %SCRIPT%
echo.

echo 正在创建定时任务（每天 8:00 执行）...

schtasks /CREATE /TN "每日考勤推送" /TR "'%PYTHON%' '%SCRIPT%' --full-send" /SC DAILY /ST 08:00 /RL HIGHEST /F

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo   定时任务创建成功！
    echo ===================================================
    echo.
    echo 任务名称: 每日考勤推送
    echo 执行时间: 每天 8:00
    echo 执行命令: %PYTHON% %SCRIPT% --full-send
    echo.
) else (
    echo.
    echo 创建失败，请以管理员身份运行此脚本
)
pause
