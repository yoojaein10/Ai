@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.popbill_sync >> logs\popbill_sync.log 2>&1
