@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.voucher_cache_sync --days 3 --partial-summary >> logs\cache_sync.log 2>&1
