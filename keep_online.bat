@echo off
chcp 65001 >nul
REM ============================================================
REM DTC 平台长期在线脚本（无需 GitHub / Render / 域名）
REM 作用：确保后端服务 + cloudflared 隧道常驻，
REM       并把当前公网地址写入 public_url.txt
REM 用法：双击运行一次即可；如需开机自启，见下方说明。
REM ============================================================

cd /d %~dp0
set ROOT=%cd%
set CF=%ROOT%\..\cloudflared.exe
set LOG=%ROOT%\..\_dtc_tunnel.log
set URLFILE=%ROOT%\public_url.txt

if not exist "%CF%" ( set CF=%ROOT%\..\cloudflared.exe )

echo [1/3] 启动后端服务（如已在运行则跳过）...
netstat -ano | findstr ":8787" >nul
if errorlevel 1 (
  start "" /min cmd /c "cd /d %ROOT% && python server.py"
  echo     后端已启动
) else (
  echo     后端已在运行
)

echo [2/3] 等待服务就绪...
timeout /t 3 /nobreak >nul

echo [3/3] 启动 cloudflared 隧道...
netstat -ano | findstr ":8787" >nul
start "" /min cmd /c ""%CF%" tunnel --no-autoupdate --url http://127.0.0.1:8787 > "%LOG%" 2>&1"

echo 等待隧道分配公网地址（约 10 秒）...
timeout /t 12 /nobreak >nul

REM 从日志抓取公网地址并写入文件
for /f "tokens=*" %%i in ('findstr /r "https://.*trycloudflare.com" "%LOG%"') do set LINE=%%i
for /f "tokens=2 delims=|" %%a in ("%LINE%") do set URL=%%a
set URL=%URL: =%
if defined URL (
  > "%URLFILE%" echo %URL%
  echo.
  echo 当前公网地址已写入 %URLFILE% :
  echo   %URL%
) else (
  echo 未抓到地址，请查看日志：%LOG%
)

echo.
echo 提示：临时隧道地址在重启后会变化。
echo 若要真正固定地址，需要自有域名 + Cloudflare 账户，
echo 或将项目部署到 GitHub+Render（步骤见 DEPLOY.md）。
pause
