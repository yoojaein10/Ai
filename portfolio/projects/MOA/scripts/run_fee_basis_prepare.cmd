@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m app.services.fee_basis --months-back 5 >> logs\fee_basis_prepare.log 2>&1
