@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000"^| findstr "LISTENING"') do taskkill //F //PID %%a
timeout /t 2 /nobreak
taskkill //F //IM python.exe 2>nul
