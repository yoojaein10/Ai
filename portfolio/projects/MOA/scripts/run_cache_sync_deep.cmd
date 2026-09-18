@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days 60 >> logs\cache_sync_deep.log 2>&1
