@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.deposit_voucher_sync --days 7 --send >> logs\deposit_voucher.log 2>&1
