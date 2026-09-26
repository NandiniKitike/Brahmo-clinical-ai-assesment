# BRAHMO Clinical AI - One-shot setup script
# Run this from inside the brahmo-clinical-ai folder:
#   cd "c:\Users\HP\Downloads\Brahmo Clinical AI Assessment\brahmo-clinical-ai"
#   .\setup.ps1

Set-Location $PSScriptRoot

Write-Host "=== Step 1: Creating Python 3.11 virtual environment ===" -ForegroundColor Cyan
py -3.11 -m venv .venv

Write-Host "=== Step 2: Activating virtual environment ===" -ForegroundColor Cyan
.\.venv\Scripts\Activate.ps1

Write-Host "=== Step 3: Upgrading pip ===" -ForegroundColor Cyan
python -m pip install --upgrade pip

Write-Host "=== Step 4: Installing requirements ===" -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host ""
Write-Host "=== Setup Complete! ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Make sure your .env file has your DB password and Gemini API key"
Write-Host "  2. Create the DB: run 'python scripts/load_all_data.py'"
Write-Host "  3. Start the API: run 'uvicorn app.main:app --reload'"
