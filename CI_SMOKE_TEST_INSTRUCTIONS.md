# CI Smoke Test PR - Instructions

## Current Situation

**Status**: ❌ Git is not installed on this system

I cannot execute Git commands directly because Git is not available in PowerShell. However, I've prepared everything you need to complete this task once Git is installed.

## What You Need to Do

### Step 1: Install Git (if not already installed)

1. Download: https://git-scm.com/downloads
2. Run installer with default options
3. **Important**: Ensure "Git from the command line and also from 3rd-party software" is selected
4. Restart PowerShell after installation
5. Verify: `git --version`

### Step 2: Run the Automated Script

I've created an automated script that will handle all the steps:

**Option A - PowerShell (Recommended):**
```powershell
.\create-ci-smoke-test-pr.ps1
```

**Option B - Batch File:**
```cmd
create-ci-smoke-test-pr.bat
```

The script will:
1. ✓ Verify Git is installed
2. ✓ Switch to main branch
3. ✓ Create branch `ci-smoke-test`
4. ✓ Append blank line to `backend/README.md`
5. ✓ Commit with message: `test: CI smoke test`
6. ✓ Push branch to origin
7. ✓ Display next steps with PR creation link

### Step 3: Create Pull Request on GitHub

1. Go to your GitHub repository
2. Click **"Compare & pull request"** (should appear automatically)
3. **Title**: `test: CI smoke test`
4. **Description**: `Verify GitHub Actions CI workflow is properly configured`
5. Click **"Create pull request"**

### Step 4: Wait for CI Checks

GitHub Actions will automatically run. Expected duration: ~1-2 minutes

### Step 5: Copy CI Results

Once checks complete, you should see:

```
✓ Backend Tests & Lint
✓ Frontend Build & Lint
```

Click "Details" on each job to see full output.

---

## Manual Commands (Alternative)

If you prefer to run commands manually instead of using the script:

```powershell
# Navigate to project
cd "C:\RW Tournament Software"

# Ensure on main branch
git checkout main

# Create new branch
git checkout -b ci-smoke-test

# Make trivial change
Add-Content -Path "backend\README.md" -Value ""

# Stage and commit
git add .
git commit -m "test: CI smoke test"

# Push branch
git push -u origin ci-smoke-test
```

Then create PR on GitHub as described above.

---

## Expected CI Output

### Backend Tests & Lint Job
```
✓ Set up job
✓ Run actions/checkout@v4
✓ Set up Python 3.12
✓ Install dependencies
✓ Lint with ruff
   ruff check . - All checks passed!
   ruff format --check . - 71 files already formatted
✓ Run tests
   pytest -q --tb=short
   120 passed, 4 skipped in ~5-7s
✓ Complete job
```

### Frontend Build & Lint Job
```
✓ Set up job
✓ Run actions/checkout@v4
✓ Set up Node.js 20
✓ Install dependencies
   npm ci
✓ Lint
   npm run lint
✓ Build
   npm run build
   vite v5.0.8 building for production...
   ✓ built in ~3-4s
✓ Complete job
```

---

## What to Paste Back

After CI completes, paste these items:

### 1. Job Names + Status
```
✓ Backend Tests & Lint (ubuntu-latest) - Passed in XXs
✓ Frontend Build & Lint (ubuntu-latest) - Passed in XXs
```

### 2. CI Run URL
Example: `https://github.com/username/repo/actions/runs/12345678`

You can find this by:
- Going to the "Actions" tab in your repo
- Clicking on the workflow run
- Copying the URL from your browser

---

## After Verification

Once you've confirmed CI is working:

### Option 1: Merge the PR
Click "Merge pull request" on GitHub

### Option 2: Close without merging
1. Close the PR on GitHub
2. Clean up locally:
```powershell
git checkout main
git branch -D ci-smoke-test
git push origin --delete ci-smoke-test
```

---

## Troubleshooting

### "Git not found"
→ Install Git from https://git-scm.com/downloads and restart PowerShell

### "Not a git repository"
→ Run `setup-git-milestone.ps1` first to initialize the repository

### "No remote configured"
→ Add remote: `git remote add origin https://github.com/USERNAME/REPO.git`

### CI Checks Fail
→ Check the logs in GitHub Actions for specific errors
→ Both jobs should pass with current codebase (120 tests passing, 0 lint errors)

---

## Files Ready

✓ `create-ci-smoke-test-pr.ps1` - PowerShell automation script
✓ `create-ci-smoke-test-pr.bat` - Batch automation script  
✓ `CI_SMOKE_TEST_INSTRUCTIONS.md` - This file
✓ `.github/workflows/ci.yml` - CI workflow (already committed)
✓ All linting errors fixed (33 → 0)
✓ All tests passing (120 passed, 4 skipped)

**Status**: Everything is ready once Git is installed!

