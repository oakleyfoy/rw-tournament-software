@echo off
REM Setup Git Milestone and CI Workflow
REM This script initializes git, creates the milestone commit, tags it, and pushes to GitHub

echo ========================================
echo Git Milestone Setup Script
echo ========================================
echo.

REM Check if git is installed
where git >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Git is not installed or not in PATH
    echo.
    echo Please install Git from: https://git-scm.com/downloads
    echo After installation, restart this script.
    echo.
    pause
    exit /b 1
)

echo Git found! Version:
git --version
echo.

REM Navigate to project directory
cd /d "%~dp0"

REM Check if .git directory exists
if not exist ".git" (
    echo Initializing Git repository...
    git init
    echo.
) else (
    echo Git repository already initialized.
    echo.
)

REM Check git status
echo Checking git status...
git status
echo.

echo ========================================
echo Step 1: Create milestone commit
echo ========================================
echo.
echo Staging all files...
git add .
echo.

echo Creating commit...
git commit -m "chore: green test suite milestone (120 passed)" -m "All backend tests passing: 120 passed, 4 skipped" -m "CI workflow configured with backend tests, lint, and frontend build"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Note: If you see "nothing to commit" message, that's OK - the repo is already clean.
    echo Continuing to tag creation...
    echo.
)

echo.
echo ========================================
echo Step 2: Create tag
echo ========================================
echo.
echo Creating tag v1-scheduling-green-suite...
git tag -a v1-scheduling-green-suite -m "Green test suite milestone - 120 tests passing"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo WARNING: Tag creation failed. Tag may already exist.
    echo To replace existing tag, run: git tag -f v1-scheduling-green-suite
    echo.
)

echo.
echo ========================================
echo Step 3: Push to GitHub
echo ========================================
echo.
echo NOTE: Before pushing, ensure you have:
echo 1. Created a GitHub repository
echo 2. Set up the remote (if not already done):
echo    git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
echo.

REM Check if remote exists
git remote -v >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Current remotes:
    git remote -v
    echo.
    
    echo Do you want to push now? (Y/N)
    set /p PUSH_CONFIRM=
    if /i "%PUSH_CONFIRM%"=="Y" (
        echo.
        echo Pushing to origin main...
        git push -u origin main
        echo.
        echo Pushing tag...
        git push origin v1-scheduling-green-suite
        echo.
        echo ========================================
        echo SUCCESS!
        echo ========================================
        echo.
        echo Next steps:
        echo 1. Go to your GitHub repository
        echo 2. Check the Actions tab to verify CI is running
        echo 3. Create a trivial PR to test the CI workflow
        echo.
    ) else (
        echo.
        echo Skipped pushing. To push manually, run:
        echo   git push -u origin main
        echo   git push origin v1-scheduling-green-suite
        echo.
    )
) else (
    echo No remote configured. To set up GitHub remote:
    echo 1. Create a repository on GitHub
    echo 2. Run: git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
    echo 3. Run: git push -u origin main
    echo 4. Run: git push origin v1-scheduling-green-suite
    echo.
)

echo.
echo ========================================
echo Script complete!
echo ========================================
echo.
echo Workflow file location: .github\workflows\ci.yml
echo.
pause

