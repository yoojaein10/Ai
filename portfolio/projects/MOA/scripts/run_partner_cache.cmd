@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.partner_cache_sync >> logs\partner_cache.log 2>&1
