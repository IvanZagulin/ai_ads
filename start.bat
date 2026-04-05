@echo off
taskkill /F /IM python.exe 2>nul
timeout /t 1 /nobreak >nul
cd E:\ИИ управление рекламой\backend
start "" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
timeout /t 2 /nobreak >nul
cd E:\ИИ управление рекламой\frontend
start "" cmd /k python -m http.server 3000
