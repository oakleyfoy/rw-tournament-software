# Setup Git Milestone and CI Workflow
# This script initializes git, creates the milestone commit, tags it, and pushes to GitHub

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Git Milestone Setup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if git is installed
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Git is not installed or not in PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Git from: https://git-scm.com/downloads"
    Write-Host "After installation, restart this script."
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Git found! Version:" -ForegroundColor Green
git --version
Write-Host ""

# Navigate to script directory
Set-Location $PSScriptRoot

# Check if .git directory exists
if (-not (Test-Path ".git")) {
    Write-Host "Initializing Git repository..." -ForegroundColor Yellow
    git init
    git branch -M main
    Write-Host ""
} else {
    Write-Host "Git repository already initialized." -ForegroundColor Green
    Write-Host ""
}

# Check git status
Write-Host "Checking git status..." -ForegroundColor Cyan
git status
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Step 1: Create milestone commit" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Staging all files..."
git add .
Write-Host ""

Write-Host "Creating commit..."
git commit -m "chore: green test suite milestone (120 passed)" -m "All backend tests passing: 120 passed, 4 skipped" -m "CI workflow configured with backend tests, lint, and frontend build"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Note: If you see 'nothing to commit' message, that's OK - the repo is already clean." -ForegroundColor Yellow
    Write-Host "Continuing to tag creation..." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Step 2: Create tag" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Creating tag v1-scheduling-green-suite..."
git tag -a v1-scheduling-green-suite -m "Green test suite milestone - 120 tests passing"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "WARNING: Tag creation failed. Tag may already exist." -ForegroundColor Yellow
    Write-Host "To replace existing tag, run: git tag -f v1-scheduling-green-suite" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Step 3: Push to GitHub" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: Before pushing, ensure you have:" -ForegroundColor Yellow
Write-Host "1. Created a GitHub repository" -ForegroundColor Yellow
Write-Host "2. Set up the remote (if not already done):" -ForegroundColor Yellow
Write-Host "   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git" -ForegroundColor Yellow
Write-Host ""

# Check if remote exists
$remotes = git remote 2>$null
if ($remotes) {
    Write-Host "Current remotes:" -ForegroundColor Green
    git remote -v
    Write-Host ""
    
    $pushConfirm = Read-Host "Do you want to push now? (Y/N)"
    if ($pushConfirm -eq "Y" -or $pushConfirm -eq "y") {
        Write-Host ""
        Write-Host "Pushing to origin main..." -ForegroundColor Cyan
        git push -u origin main
        Write-Host ""
        Write-Host "Pushing tag..." -ForegroundColor Cyan
        git push origin v1-scheduling-green-suite
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "SUCCESS!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Cyan
        Write-Host "1. Go to your GitHub repository"
        Write-Host "2. Check the Actions tab to verify CI is running"
        Write-Host "3. Create a trivial PR to test the CI workflow"
        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "Skipped pushing. To push manually, run:" -ForegroundColor Yellow
        Write-Host "  git push -u origin main"
        Write-Host "  git push origin v1-scheduling-green-suite"
        Write-Host ""
    }
} else {
    Write-Host "No remote configured. To set up GitHub remote:" -ForegroundColor Yellow
    Write-Host "1. Create a repository on GitHub"
    Write-Host "2. Run: git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git"
    Write-Host "3. Run: git push -u origin main"
    Write-Host "4. Run: git push origin v1-scheduling-green-suite"
    Write-Host ""
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Script complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Workflow file location: .github\workflows\ci.yml" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to exit"

