# Windows 11 PowerShell Run Script for Deep Research Engine

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Launching Evidence-First Deep Research Dashboard" -ForegroundColor Cyan
Write-Host " Local URL: http://127.0.0.1:8501" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Ensure local binding to 127.0.0.1 for security
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

