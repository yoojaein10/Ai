@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --log-config scripts\uvicorn_log_config.json >> logs\server.log 2>&1
