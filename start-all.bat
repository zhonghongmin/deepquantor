@echo off
chcp 65001 >nul
setlocal
title DeepQuantor Start
rem One-key start for DeepQuantor.
rem Usage: start-all.bat            double-click: starts all, opens browser, pauses
rem        start-all.bat --silent   no browser / no pause; for automation

set "ROOT=%~dp0"
set "SILENT=0"
if /i "%~1"=="--silent" set "SILENT=1"
set "NEXT_TELEMETRY_DISABLED=1"

echo ============================================
echo   DeepQuantor 一键启动
echo   PostgreSQL :5432 + Redis :6379 + Web :3000
echo ============================================

rem ---- 0) locate Node.js ----
set "NODE_DIR="
if exist "%ROOT%..\Node-22.22.2\node.exe" set "NODE_DIR=%ROOT%..\Node-22.22.2"
if not defined NODE_DIR (
  for %%D in ("%ProgramFiles%\nodejs" "%ProgramFiles(x86)%\nodejs" "C:\nodejs" "%LocalAppData%\Programs\nodejs") do (
    if exist "%%~D\node.exe" set "NODE_DIR=%%~D"
  )
)
if not defined NODE_DIR (
  for /d %%V in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
    if exist "%%V\node.exe" set "NODE_DIR=%%V"
  )
)
if not defined NODE_DIR (
  echo [ERROR] 未找到 Node.js，请检查 D:\develop\Node-22.22.2
  if "%SILENT%"=="0" pause
  exit /b 1
)
set "PATH=%NODE_DIR%;%PATH%"

set "PG_HOME=%ROOT%..\PostgreSQL-16.8\"
set "PG_DATA=%PG_HOME%data"
set "REDIS_HOME=%ROOT%..\Redis-8.10.3\"
set "WEB_DIR=%ROOT%services\web"

rem ---- 0) clean slate: stop-all first (avoid port conflicts / zombie state) ----
echo [0/3] 清场：先执行 stop-all 避免端口冲突 ...
call "%ROOT%stop-all.bat" >nul 2>&1
ping -n 3 127.0.0.1 >nul 2>&1

rem ---- 1) PostgreSQL ----
echo [1/3] PostgreSQL ...
if not exist "%PG_DATA%\PG_VERSION" (
  echo   [skip] data 目录未初始化，请先执行 pg-init.bat
) else (
  netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
  if errorlevel 1 (
    "%PG_HOME%bin\pg_ctl.exe" -D "%PG_DATA%" -l "%PG_HOME%pg.log" -o "-p 5432" start
  ) else (
    echo   已在运行，跳过
  )
)

rem ---- 2) Redis ----
echo [2/3] Redis ...
netstat -ano | findstr ":6379" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  start "DeepQuantor Redis" /min "%REDIS_HOME%redis-server.exe" "%REDIS_HOME%redis.conf"
) else (
  echo   已在运行，跳过
)

rem ---- wait for middleware ----
echo   等待中间件就绪 ...
ping -n 4 127.0.0.1 >nul 2>&1

rem ---- 3) Web ----
echo [3/3] Web (http://localhost:3000) ...
cd /d "%WEB_DIR%"
if not exist package.json (
  echo [ERROR] services\web\package.json 不存在
  if "%SILENT%"=="0" pause
  exit /b 1
)
if not exist ".next\BUILD_ID" (
  echo   首次运行：执行生产构建 ...
  call npm.cmd run build
  if errorlevel 1 (
    echo [ERROR] 构建失败
    if "%SILENT%"=="0" pause
    exit /b 1
  )
)
start "DeepQuantor Web" /min cmd /k "npm.cmd run start"

rem ---- health probe: wait up to 15s for :3000（本地运行，失败仅提示不阻断） ----
set /a TRIES=0
:probe
ping -n 2 127.0.0.1 >nul 2>&1
curl -s -o nul -w "%%{http_code}" http://localhost:3000/admin/overview | findstr "200" >nul 2>&1
if errorlevel 1 (
  set /a TRIES+=1
  if %TRIES% lss 15 goto probe
  echo   [WARN] Web 15 秒内未就绪，请查看 Web 窗口日志
) else (
  echo   Web 就绪 ✓
)

echo.
echo ============================================
echo   启动完成
echo   PostgreSQL :5432   Redis :6379   Web :3000
echo   管理端: http://localhost:3000/admin/overview
echo   停止请运行 stop-all.bat
echo ============================================
if "%SILENT%"=="0" (
  ping -n 3 127.0.0.1 >nul 2>&1
  start "" "http://localhost:3000/admin/overview"
  pause
)
endlocal
exit /b 0
