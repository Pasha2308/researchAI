# Windows 11 PowerShell Setup Script for Deep Research Engine

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Evidence-First Deep Research Engine - Windows Setup" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python version
try {
    $pythonVersion = python --version
    Write-Host "[✓] Found Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[✗] Python was not found in PATH. Please install Python 3.12+ from python.org." -ForegroundColor Red
    exit 1
}

# 2. Upgrade pip and install dependencies
Write-Host "[*] Installing Python dependencies from requirements.txt..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 3. Environment configuration template
if (-Not (Test-Path ".env")) {
    Write-Host "[*] Creating .env file from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "[!] Notice: Please edit .env and enter your GROQ_API_KEY." -ForegroundColor Magenta
} else {
    Write-Host "[✓] .env file already exists." -ForegroundColor Green
}

# 4. Verify SQLite and Database initialization
Write-Host "[*] Initializing SQLite database schema and FTS5 search..." -ForegroundColor Yellow
python -c "from research_engine.database.connection import init_database; fts=init_database(); print(f'Database initialized. FTS5 support: {fts}')"

Write-Host "`n[✓] Setup complete! You can now run:" -ForegroundColor Green
Write-Host "    .\scripts\run_windows.ps1        (to launch the Streamlit dashboard)" -ForegroundColor White
Write-Host "    python cli.py --help             (to run from the command line)`n" -ForegroundColor White

