# Create CI Smoke Test PR
# This script creates a test branch with a trivial change to verify CI

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Create CI Smoke Test PR" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if git is installed
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Git is not installed or not in PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Git from: https://git-scm.com/downloads" -ForegroundColor Yellow
    Write-Host "After installation, restart PowerShell and run this script again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Git found! Version:" -ForegroundColor Green
git --version
Write-Host ""

# Navigate to script directory
Set-Location $PSScriptRoot

# Check if we're in a git repository
if (-not (Test-Path ".git")) {
    Write-Host "ERROR: Not a git repository" -ForegroundColor Red
    Write-Host "Please run setup-git-milestone.ps1 first to initialize the repository" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Ensure we're on main branch
Write-Host "Switching to main branch..." -ForegroundColor Cyan
git checkout main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Warning: Could not switch to main branch" -ForegroundColor Yellow
    Write-Host ""
}

# Create ci-smoke-test branch
$branchName = "ci-smoke-test"
Write-Host "Creating branch: $branchName" -ForegroundColor Cyan
git checkout -b $branchName
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to create branch" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Make trivial change to backend/README.md
Write-Host "Making trivial change to backend/README.md..." -ForegroundColor Cyan
$readmePath = "backend\README.md"
if (Test-Path $readmePath) {
    # Append a blank line
    Add-Content -Path $readmePath -Value ""
    Write-Host "Added blank line to $readmePath" -ForegroundColor Green
} else {
    Write-Host "Warning: backend/README.md not found, creating trivial test file..." -ForegroundColor Yellow
    Set-Content -Path "CI_SMOKE_TEST.md" -Value "# CI Smoke Test`n`nThis is a trivial file to test CI workflow.`n"
}
Write-Host ""

# Stage changes
Write-Host "Staging changes..." -ForegroundColor Cyan
git add .
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to stage changes" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Commit
Write-Host "Creating commit..." -ForegroundColor Cyan
git commit -m "test: CI smoke test"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to create commit" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Push branch
Write-Host "Pushing branch to origin..." -ForegroundColor Cyan
git push -u origin $branchName
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to push branch" -ForegroundColor Red
    Write-Host "Make sure you have configured the remote: git remote add origin <URL>" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Green
Write-Host "Branch pushed successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Go to your GitHub repository" -ForegroundColor White
Write-Host "2. You should see a prompt: 'Compare & pull request' for branch '$branchName'" -ForegroundColor White
Write-Host "3. Click 'Compare & pull request'" -ForegroundColor White
Write-Host "4. Title: 'test: CI smoke test'" -ForegroundColor White
Write-Host "5. Description: 'Verify GitHub Actions CI workflow is properly configured'" -ForegroundColor White
Write-Host "6. Click 'Create pull request'" -ForegroundColor White
Write-Host "7. Wait for CI checks to complete (~1-2 minutes)" -ForegroundColor White
Write-Host "8. Verify both jobs pass:" -ForegroundColor White
Write-Host "   - Backend Tests & Lint (green checkmark)" -ForegroundColor Green
Write-Host "   - Frontend Build & Lint (green checkmark)" -ForegroundColor Green
Write-Host ""
Write-Host "Expected CI Results:" -ForegroundColor Cyan
Write-Host "✓ Backend Tests & Lint - ruff check, ruff format, pytest (120 passed)" -ForegroundColor Green
Write-Host "✓ Frontend Build & Lint - npm ci, npm lint, npm build" -ForegroundColor Green
Write-Host ""
Write-Host "After verification:" -ForegroundColor Yellow
Write-Host "- You can merge the PR or close it without merging" -ForegroundColor White
Write-Host "- Switch back to main: git checkout main" -ForegroundColor White
Write-Host "- Delete local branch: git branch -D $branchName" -ForegroundColor White
Write-Host "- Delete remote branch: git push origin --delete $branchName" -ForegroundColor White
Write-Host ""

# Get the repository URL for convenience
$remoteUrl = git remote get-url origin 2>$null
if ($remoteUrl) {
    Write-Host "Your repository:" -ForegroundColor Cyan
    Write-Host $remoteUrl -ForegroundColor White
    
    # Try to parse GitHub URL and show PR creation link
    if ($remoteUrl -match "github\.com[:/](.+?)(?:\.git)?$") {
        $repoPath = $matches[1]
        $prUrl = "https://github.com/$repoPath/compare/$branchName"
        Write-Host ""
        Write-Host "Direct PR creation link:" -ForegroundColor Cyan
        Write-Host $prUrl -ForegroundColor White
    }
}

Write-Host ""
Read-Host "Press Enter to exit"

