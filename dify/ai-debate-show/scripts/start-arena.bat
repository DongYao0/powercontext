@echo off
rem ==========================================================================
rem  《再说一遍？AI 记仇辩论夜》Arena 服务启动脚本（Windows）
rem
rem  行为约定：
rem    * 只做检查与启动，不安装任何依赖；
rem    * 端口被占用时只提示 PID 并安全退出，不结束任何进程；
rem    * 服务在前台运行，日志写入项目内 logs/ 目录；
rem    * 不读取、不输出、不记录任何令牌的具体值。
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 > nul

rem --- 1. 定位项目目录（由脚本自身位置推导，不依赖当前终端目录） ---
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"

rem --- 2. 端口 ---
if "%ARENA_PORT%"=="" set "ARENA_PORT=8088"

rem --- 3. 检查 python ---
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到可执行的 python。
    echo        请先安装 Python 3.11 或更高版本，并确保 python 已经在 PATH 中。
    exit /b 1
)

rem --- 4. 检查端口占用（只提示，不结束进程） ---
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:":%ARENA_PORT% .*LISTENING"') do (
    if not defined PORT_PID set "PORT_PID=%%P"
)
if defined PORT_PID (
    echo [警告] 端口 %ARENA_PORT% 已经被占用，PID 为 %PORT_PID%。
    echo        本脚本不会自动结束任何进程。请先自行处理该进程，
    echo        或用 ARENA_PORT 环境变量换一个端口后重试。
    exit /b 2
)

rem --- 5. 日志目录与带时间戳的日志文件 ---
set "LOG_DIR=%PROJECT_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
if not exist "%LOG_DIR%" (
    echo [错误] 无法创建日志目录：%LOG_DIR%
    exit /b 1
)
set "STAMP="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "STAMP=%%T"
if not defined STAMP set "STAMP=run"
set "LOG_FILE=%LOG_DIR%\arena-%STAMP%.log"

rem --- 6. 提示信息 ---
echo [信息] 项目目录：%PROJECT_DIR%
echo [信息] 监听端口：%ARENA_PORT%
if defined POWERCONTEXT_BASE_URL (
    echo [信息] 记忆能力：已配置，将召回历史并写入结算记忆。
) else (
    echo [信息] 记忆能力：未配置，本场没有跨会话翻旧账，对局照常可玩。
)
echo [信息] 日志文件：%LOG_FILE%
echo [信息] 按 Ctrl+C（随后按 Y）停止服务。
echo [信息] 实时查看日志：Get-Content -Wait "%LOG_FILE%"
echo.

rem --- 7. 前台启动 ---
set "PYTHONPATH=%PROJECT_DIR%"
set "PYTHONUNBUFFERED=1"
rem 让日志文件固定写成 UTF-8，不受控制台代码页影响
set "PYTHONIOENCODING=utf-8"
cd /d "%PROJECT_DIR%"
python -m arena_service.server >>"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo [信息] 服务已退出，退出码 %EXIT_CODE%。日志：%LOG_FILE%
exit /b %EXIT_CODE%
