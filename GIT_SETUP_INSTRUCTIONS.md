# Green Test Suite Milestone Setup

This document contains the commands to create a "green suite" milestone commit and set up CI.

## Prerequisites

Ensure Git is installed and available in your PATH. You can download Git from https://git-scm.com/downloads

## Steps to Execute

### 1. Initialize Git Repository (if not already done)

```bash
cd "C:\RW Tournament Software"
git init
```

### 2. Configure Git (if not already configured)

```bash
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 3. Add All Files

```bash
git add .
```

### 4. Create the Green Suite Milestone Commit

```bash
git commit -m "chore: green test suite milestone (120 passed)

All backend tests now passing:
- 120 tests passed
- 5 tests skipped
- 0 failures
- 0 errors

Key fixes:
- Fixed test_checksum_determinism to use API for tournament creation
- Added missing fixtures to test_team_injection_v1.py tests
- Fixed setup_bracket_event fixture to properly finalize events

Added CI workflow to prevent regression."
```

### 5. Create Git Tag

```bash
git tag -a v1-scheduling-green-suite -m "Green test suite milestone - 120 tests passing"
```

### 6. Create GitHub Repository (if not already done)

Go to https://github.com/new and create a new repository for this project.

### 7. Add Remote and Push

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
git push origin v1-scheduling-green-suite
```

## CI Workflow

The CI workflow has been created at `.github/workflows/ci.yml` and will automatically run on:
- Pushes to `main`, `master`, or `develop` branches
- Pull requests to `main`, `master`, or `develop` branches

### CI Jobs

1. **Backend Tests & Lint**
   - Runs `ruff check .` and `ruff format --check .`
   - Runs `pytest -q --tb=short`
   - Fails fast on any non-zero exit codes

2. **Frontend Build & Lint**
   - Runs `npm ci`
   - Runs `npm run lint` (if available)
   - Runs `npm run build`
   - Fails fast on any non-zero exit codes

## Verification

After pushing, you can verify the CI is working by:

1. Going to your GitHub repository
2. Clicking on the "Actions" tab
3. You should see the CI workflow running
4. Check that both "Backend Tests & Lint" and "Frontend Build & Lint" jobs pass

To test that CI catches failures:

1. Create a new branch: `git checkout -b test-ci`
2. Introduce a trivial failure (e.g., add `assert False` to a test)
3. Commit and push: `git add . && git commit -m "test: verify CI fails" && git push origin test-ci`
4. Create a PR on GitHub
5. Verify that the CI check fails
6. Close the PR and delete the branch

## Files Created

- `.gitignore` - Git ignore rules for Python, Node, and common files
- `.github/workflows/ci.yml` - GitHub Actions CI workflow
- `backend/pyproject.toml` - Ruff configuration and pytest settings
- `GIT_SETUP_INSTRUCTIONS.md` - This file

## Next Steps

After running these commands and pushing to GitHub:

1. Enable branch protection rules on `main` branch
2. Require CI checks to pass before merging
3. Optionally enable "Require branches to be up to date before merging"

