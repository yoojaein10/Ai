@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days 365 --monthly-chunks >> logs\cache_sync_year.log 2>&1
