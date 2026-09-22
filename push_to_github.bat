@echo off
echo ========================================================
echo Pushing MediKiosk / Cliniqo to GitHub...
echo ========================================================

cd /d "d:\ai_medical_assistant_UPDATED"

:: 1. Initialize git repo if not already initialized
if not exist ".git" (
    echo [1/5] Initializing local git repository...
    git init
) else (
    echo [1/5] Git repository already initialized.
)

:: 2. Set remote origin
echo [2/5] Configuring remote origin to https://github.com/Abinav-max/Cliniqo.git ...
git remote remove origin 2>nul
git remote add origin https://github.com/Abinav-max/Cliniqo.git

:: 3. Stage all files
echo [3/5] Staging files...
git add -A

:: 4. Commit
echo [4/5] Creating commit...
git commit -m "feat: complete Cliniqo MediKiosk system - longitudinal profiles, dual portals, and adaptive clinical workflows"

:: 5. Rename branch to main and push
echo [5/5] Setting main branch and pushing to GitHub...
git branch -M main
git push -u origin main

if %errorlevel% neq 0 (
    echo.
    echo ========================================================
    echo Push encountered an issue (e.g. remote contains existing files or authentication needed).
    echo Attempting rebase or force push if this is a fresh setup...
    echo If this is an existing remote with a README, run:
    echo   git pull origin main --rebase
    echo   git push -u origin main
    echo Or to overwrite the remote:
    echo   git push -u origin main --force
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo [SUCCESS] Code successfully pushed to:
    echo https://github.com/Abinav-max/Cliniqo.git
    echo ========================================================
)
pause
