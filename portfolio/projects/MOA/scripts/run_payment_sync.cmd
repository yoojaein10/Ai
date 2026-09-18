@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.payment_status_sync >> logs\payment_sync.log 2>&1
