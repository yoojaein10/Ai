@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.deposit_voucher_sync --days 7 --send --include-yak >> logs\deposit_voucher_yak.log 2>&1
