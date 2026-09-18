@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.batch.tams_tax_sync >> logs\tams_sync.log 2>&1
.venv\Scripts\python.exe -m app.batch.tams_to_ledger >> logs\tams_sync.log 2>&1
