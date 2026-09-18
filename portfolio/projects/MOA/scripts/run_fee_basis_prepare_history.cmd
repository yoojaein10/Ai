@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.services.fee_basis --months-back 1 >> logs\fee_basis_prepare_history.log 2>&1
