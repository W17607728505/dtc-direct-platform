@echo off
chcp 65001 >nul
REM DTC 平台生产模式启动脚本
REM 用法：设置 DTC_BASE_URL 后双击运行；或用 nssm 注册为 Windows 服务实现开机自启

set HOST=127.0.0.1
set PORT=8787
set DTC_ENV=prod
set DTC_ENABLE_RATE_LIMIT=1
set DTC_RATE_LIMIT=120
REM 设置你的正式对外地址（联邦协议链接依赖此项）
if "%DTC_BASE_URL%"=="" set DTC_BASE_URL=https://dtc.yourdomain.com
REM 设置管理令牌（可选但生产强烈建议）
if "%DTC_ADMIN_TOKEN%"=="" set DTC_ADMIN_TOKEN=change-me-please

cd /d %~dp0
echo Starting DTC platform (prod)...
echo Base URL: %DTC_BASE_URL%
python server.py
pause
