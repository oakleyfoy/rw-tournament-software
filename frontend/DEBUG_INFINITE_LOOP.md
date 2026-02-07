# Debug Infinite Loop - Steps for User

## Step 1: Confirm Fresh Build

1. **Kill ALL dev servers** (close all terminals running `npm run dev`)

2. **Clear browser cache** or open in incognito/private window

3. **Start fresh**:
```bash
cd "C:\RW Tournament Software\frontend"
npm run dev:editor-on
```

4. Note the URL Vite shows (probably `http://localhost:5173`)

---

## Step 2: Open Browser Console FIRST

**Before opening the editor page**:

1. Open browser DevTools (F12)
2. Go to **Console** tab
3. Clear console (trash icon)
4. **Enable "Preserve log"** (checkbox in console toolbar)

---

## Step 3: Navigate to Editor

Open: `http://localhost:5173/tournaments/1/schedule/editor?versionId=109`

---

## Step 4: Capture Console Output

**Copy EVERYTHING from console** (first 50 lines if too much) and paste here.

Specifically look for:
- Any console.log messages
- Red errors
- How many times "Loading editor…" or similar messages appear
- Any warnings about setState or useEffect

---

## Step 5: Check Network Tab

In DevTools:
1. Go to **Network** tab
2. Look at the **API calls** being made
3. Are there repeated calls to the same endpoint?
4. If yes, paste the endpoint URLs and how many times they're called

---

## What I Need

Paste these 3 things:

1. **Console output** (first 50 lines)
2. **Network requests** (if repeating)
3. **What you see on screen** (blank? error boundary? "Loading editor…" stuck?)

