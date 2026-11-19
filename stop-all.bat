@echo off
chcp 65001 >nul
setlocal
title DeepQuantor Stop
rem One-key stop for DeepQuantor.
rem Usage: stop-all.bat   stops Web (:3000), Redis (:6379), PostgreSQL (:5432)

set "ROOT=%~dp0"
set "PG_HOME=%ROOT%..\PostgreSQL-16.8\"
set "PG_DATA=%PG_HOME%data"
set "REDIS_HOME=%ROOT%..\Redis-8.10.3\"

echo ============================================
echo   DeepQuantor 一键停止
echo ============================================

rem ---- 1) Web (:3000): kill listener + its window ----
echo [1/3] 停止 Web (:3000) ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
  taskkill /PID %%a /T /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq DeepQuantor Web*" /T /F >nul 2>&1

rem ---- 2) Redis (:6379): graceful shutdown + window ----
echo [2/3] 停止 Redis (:6379) ...
"%REDIS_HOME%redis-cli.exe" -p 6379 shutdown nosave >nul 2>&1
taskkill /FI "WINDOWTITLE eq DeepQuantor Redis*" /T /F >nul 2>&1

rem ---- 3) PostgreSQL (:5432): fast stop ----
echo [3/3] 停止 PostgreSQL (:5432) ...
"%PG_HOME%bin\pg_ctl.exe" -D "%PG_DATA%" stop -m fast >nul 2>&1

echo.
echo   全部已停止。
endlocal
exit /b 0
