@echo off
cd /d "%~dp0"
py -3.13 -c "import playwright, customtkinter, qrcode" 2>nul || (py -3.13 -m pip install -r requirements.txt)
if not exist web\dist\index.html (cd web && call npm install --no-audit --no-fund && call npm run build && cd ..)
start "" pyw -3.13 main.py
