@echo off
cd /d C:\A10Bridge
.venv\Scripts\python.exe -m scripts.roll_account_opening >> logs\account_opening_roll.log 2>&1
