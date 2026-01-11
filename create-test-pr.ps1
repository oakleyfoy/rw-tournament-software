# Create a Trivial Test PR
# This script creates a test branch with a trivial README change to verify CI

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Create Test PR for CI Verification" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if git is installed
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Git is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Navigate to script directory
Set-Location $PSScriptRoot

# Ensure we're on main branch
Write-Host "Switching to main branch..." -ForegroundColor Cyan
git checkout main
Write-Host ""

# Create test branch
$branchName = "test-ci-verification"
Write-Host "Creating branch: $branchName" -ForegroundColor Cyan
git checkout -b $branchName
Write-Host ""

# Make a trivial change to README
Write-Host "Making trivial change to backend README..." -ForegroundColor Cyan
$readmePath = "backend\README.md"
if (Test-Path $readmePath) {
    # Add a blank line at the end
    Add-Content -Path $readmePath -Value "`n"
    Write-Host "Added blank line to $readmePath" -ForegroundColor Green
} else {
    Write-Host "README not found, creating trivial test file..." -ForegroundColor Yellow
    Set-Content -Path "CI_TEST.md" -Value "# CI Test`n`nThis is a trivial file to test CI workflow.`n"
}
Write-Host ""

# Stage and commit
Write-Host "Staging changes..." -ForegroundColor Cyan
git add .
Write-Host ""

Write-Host "Creating commit..." -ForegroundColor Cyan
git commit -m "test: verify CI workflow with trivial change"
Write-Host ""

# Push branch
Write-Host "Pushing branch to origin..." -ForegroundColor Cyan
git push -u origin $branchName
Write-Host ""

Write-Host "========================================" -ForegroundColor Green
Write-Host "Branch pushed successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Go to your GitHub repository"
Write-Host "2. You should see a prompt to create a Pull Request"
Write-Host "3. Click 'Compare & pull request'"
Write-Host "4. Create the PR and watch the CI checks run"
Write-Host "5. Verify all checks pass (Backend Tests & Lint, Frontend Build & Lint)"
Write-Host ""
Write-Host "After verification, you can:" -ForegroundColor Yellow
Write-Host "- Close the PR without merging"
Write-Host "- Switch back to main: git checkout main"
Write-Host "- Delete the test branch: git branch -D $branchName"
Write-Host "- Delete remote branch: git push origin --delete $branchName"
Write-Host ""
Read-Host "Press Enter to exit"

