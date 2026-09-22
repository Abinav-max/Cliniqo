# Set working directory to project root
Set-Location "d:\ai_medical_assistant_UPDATED"

Write-Host "=== Pushing Cliniqo to GitHub ===" -ForegroundColor Cyan

# 1. Initialize Git repository
if (-not (Test-Path ".git")) {
    Write-Host "[1/5] Initializing Git repository..." -ForegroundColor Yellow
    git init
} else {
    Write-Host "[1/5] Git repository already initialized." -ForegroundColor Green
}

# 2. Add or update remote origin
Write-Host "[2/5] Setting remote origin..." -ForegroundColor Yellow
$remotes = git remote
if ($remotes -contains "origin") {
    git remote set-url origin "https://github.com/Abinav-max/Cliniqo.git"
} else {
    git remote add origin "https://github.com/Abinav-max/Cliniqo.git"
}

# 3. Stage all files
Write-Host "[3/5] Staging files..." -ForegroundColor Yellow
git add -A

# 4. Commit changes
Write-Host "[4/5] Committing changes..." -ForegroundColor Yellow
git commit -m "feat: complete Cliniqo MediKiosk system with full Render cloud deployment support (Docker, Tesseract OCR, durable SQLite vault)"

# 5. Branch main & push
Write-Host "[5/5] Setting main branch & pushing..." -ForegroundColor Yellow
git branch -M main
git push -u origin main
