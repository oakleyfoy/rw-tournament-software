@echo off
REM Create CI Smoke Test PR
REM This script creates a test branch with a trivial change to verify CI

echo ========================================
echo Create CI Smoke Test PR
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

REM Navigate to script directory
cd /d "%~dp0"

REM Check if we're in a git repository
if not exist ".git" (
    echo ERROR: Not a git repository
    echo Please run setup-git-milestone.bat first to initialize the repository
    echo.
    pause
    exit /b 1
)

REM Ensure we're on main branch
echo Switching to main branch...
git checkout main
echo.

REM Create ci-smoke-test branch
set BRANCH_NAME=ci-smoke-test
echo Creating branch: %BRANCH_NAME%
git checkout -b %BRANCH_NAME%
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to create branch
    pause
    exit /b 1
)
echo.

REM Make trivial change to backend/README.md
echo Making trivial change to backend/README.md...
if exist "backend\README.md" (
    echo. >> backend\README.md
    echo Added blank line to backend\README.md
) else (
    echo Warning: backend/README.md not found, creating trivial test file...
    echo # CI Smoke Test > CI_SMOKE_TEST.md
    echo. >> CI_SMOKE_TEST.md
    echo This is a trivial file to test CI workflow. >> CI_SMOKE_TEST.md
)
echo.

REM Stage changes
echo Staging changes...
git add .
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to stage changes
    pause
    exit /b 1
)
echo.

REM Commit
echo Creating commit...
git commit -m "test: CI smoke test"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to create commit
    pause
    exit /b 1
)
echo.

REM Push branch
echo Pushing branch to origin...
git push -u origin %BRANCH_NAME%
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to push branch
    echo Make sure you have configured the remote: git remote add origin ^<URL^>
    pause
    exit /b 1
)
echo.

echo ========================================
echo Branch pushed successfully!
echo ========================================
echo.
echo Next steps:
echo 1. Go to your GitHub repository
echo 2. You should see a prompt: 'Compare & pull request' for branch '%BRANCH_NAME%'
echo 3. Click 'Compare & pull request'
echo 4. Title: 'test: CI smoke test'
echo 5. Description: 'Verify GitHub Actions CI workflow is properly configured'
echo 6. Click 'Create pull request'
echo 7. Wait for CI checks to complete (~1-2 minutes)
echo 8. Verify both jobs pass:
echo    - Backend Tests ^& Lint (green checkmark)
echo    - Frontend Build ^& Lint (green checkmark)
echo.
echo Expected CI Results:
echo √ Backend Tests ^& Lint - ruff check, ruff format, pytest (120 passed)
echo √ Frontend Build ^& Lint - npm ci, npm lint, npm build
echo.
echo After verification:
echo - You can merge the PR or close it without merging
echo - Switch back to main: git checkout main
echo - Delete local branch: git branch -D %BRANCH_NAME%
echo - Delete remote branch: git push origin --delete %BRANCH_NAME%
echo.
pause

