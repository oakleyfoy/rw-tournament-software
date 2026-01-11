# Git Milestone and CI Setup - Complete Instructions

## Current Status

✅ **CI Workflow File**: `.github/workflows/ci.yml` already exists and is properly configured  
✅ **Test Suite**: 120 tests passing, 4 skipped  
✅ **.gitignore**: Properly configured  
❌ **Git Repository**: Not yet initialized (Git not currently accessible on system)

## Prerequisites

### Install Git
Git must be installed and accessible from your command line:
1. Download from: https://git-scm.com/downloads
2. Install with default options (ensure "Git from the command line and also from 3rd-party software" is selected)
3. Restart your terminal/PowerShell after installation
4. Verify installation: `git --version`

## Automated Setup (Recommended)

Two scripts have been created to automate the entire process:

### Option 1: PowerShell Script (Recommended for Windows)
```powershell
.\setup-git-milestone.ps1
```

### Option 2: Batch Script
```cmd
setup-git-milestone.bat
```

These scripts will:
1. ✅ Check if Git is installed
2. ✅ Initialize the repository (if needed)
3. ✅ Stage all files
4. ✅ Create the milestone commit with message: `chore: green test suite milestone (120 passed)`
5. ✅ Create tag: `v1-scheduling-green-suite`
6. ✅ Prompt you to push to GitHub (if remote is configured)

## Manual Setup (Alternative)

If you prefer to run commands manually:

### Step 1: Initialize Repository
```bash
cd "C:\RW Tournament Software"
git init
git branch -M main
```

### Step 2: Stage All Files
```bash
git add .
```

### Step 3: Create Milestone Commit
```bash
git commit -m "chore: green test suite milestone (120 passed)" -m "All backend tests passing: 120 passed, 4 skipped" -m "CI workflow configured with backend tests, lint, and frontend build"
```

### Step 4: Create Tag
```bash
git tag -a v1-scheduling-green-suite -m "Green test suite milestone - 120 tests passing"
```

### Step 5: Configure GitHub Remote
First, create a repository on GitHub, then:
```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
```

### Step 6: Push Commit and Tag
```bash
git push -u origin main
git push origin v1-scheduling-green-suite
```

## CI Workflow Details

**File Location**: `.github/workflows/ci.yml`

### Triggers
- Push to `main`, `master`, or `develop` branches
- Pull requests to `main`, `master`, or `develop` branches

### Jobs

#### Job 1: Backend Tests & Lint
- **Platform**: ubuntu-latest
- **Python**: 3.12
- **Steps**:
  1. ✅ Checkout code
  2. ✅ Set up Python with pip cache
  3. ✅ Install dependencies from requirements.txt
  4. ✅ Run `ruff check .` (linting)
  5. ✅ Run `ruff format --check .` (format check)
  6. ✅ Run `pytest -q --tb=short` (120 tests)

#### Job 2: Frontend Build & Lint
- **Platform**: ubuntu-latest
- **Node**: 20
- **Steps**:
  1. ✅ Checkout code
  2. ✅ Set up Node.js with npm cache
  3. ✅ Run `npm ci` (clean install)
  4. ✅ Run `npm run lint` (ESLint)
  5. ✅ Run `npm run build` (TypeScript + Vite build)

### Fail-Fast Behavior
- ❌ No `continue-on-error` anywhere
- ❌ Any non-zero exit code will fail the job
- ❌ Failed jobs will block PR merging (if branch protection is enabled)

## Testing CI with a Pull Request

After pushing the commit and tag, use the provided script to create a test PR:

```powershell
.\create-test-pr.ps1
```

This will:
1. Create a branch `test-ci-verification`
2. Make a trivial whitespace change to README
3. Commit and push the branch
4. Prompt you to create a PR on GitHub

### Expected CI Results

When you create the PR, GitHub Actions should show:

```
✓ Backend Tests & Lint (completed in ~30s)
  ✓ Set up job
  ✓ Checkout code
  ✓ Set up Python 3.12
  ✓ Install dependencies
  ✓ Lint with ruff
  ✓ Run tests
  ✓ Post setup

✓ Frontend Build & Lint (completed in ~45s)
  ✓ Set up job
  ✓ Checkout code
  ✓ Set up Node.js
  ✓ Install dependencies
  ✓ Lint
  ✓ Build
  ✓ Post setup
```

## Verification Checklist

After completing the setup:

- [ ] Repository initialized with `git init`
- [ ] All files staged and committed
- [ ] Commit message: `chore: green test suite milestone (120 passed)`
- [ ] Tag created: `v1-scheduling-green-suite`
- [ ] Commit pushed to GitHub
- [ ] Tag pushed to GitHub
- [ ] GitHub Actions tab shows CI workflow
- [ ] Test PR created
- [ ] CI runs automatically on PR
- [ ] Both jobs pass:
  - [ ] Backend Tests & Lint (green ✓)
  - [ ] Frontend Build & Lint (green ✓)

## Return Summary

### 1. Workflow File Path
```
.github/workflows/ci.yml
```

### 2. CI Job Configuration
```yaml
Jobs:
  - backend (Backend Tests & Lint)
    Steps: lint (ruff) → format check → pytest
  - frontend (Frontend Build & Lint) 
    Steps: npm ci → npm lint → npm build
```

### 3. Expected CI Output
Once CI runs on your test PR, you should see:
```
✓ Backend Tests & Lint
✓ Frontend Build & Lint
```

## Troubleshooting

### Git Not Found
- Ensure Git is installed from https://git-scm.com/downloads
- Restart terminal after installation
- Check: `git --version`

### Tests Failing in CI
- Run locally: `cd backend && pytest -q`
- Should show: 120 passed, 4 skipped

### Frontend Build Failing
- Run locally: `cd frontend && npm ci && npm run build`
- Check for TypeScript errors

### Remote Not Set
- Create GitHub repository first
- Run: `git remote add origin https://github.com/USERNAME/REPO.git`

## Next Steps After CI is Green

1. **Enable Branch Protection** (Recommended)
   - Go to Settings → Branches → Add rule for `main`
   - Require status checks to pass before merging
   - Select: Backend Tests & Lint, Frontend Build & Lint

2. **Add Status Badge to README** (Optional)
   ```markdown
   ![CI](https://github.com/USERNAME/REPO/workflows/CI/badge.svg)
   ```

3. **Configure Dependabot** (Optional)
   - Automatic dependency updates
   - Will trigger CI on each update PR

## Files Created by This Setup

- `setup-git-milestone.ps1` - PowerShell automation script
- `setup-git-milestone.bat` - Batch automation script
- `create-test-pr.ps1` - Create test PR for CI verification
- `COMPLETE_SETUP_INSTRUCTIONS.md` - This file

## Support

If you encounter issues:
1. Check Git installation: `git --version`
2. Verify tests pass locally: `cd backend && pytest -q`
3. Verify frontend builds: `cd frontend && npm ci && npm run build`
4. Check GitHub Actions logs for specific error messages

