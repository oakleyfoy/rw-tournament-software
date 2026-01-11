# Troubleshooting Guide

## "Failed to fetch" Error

This error occurs when the frontend cannot connect to the backend API. Here's how to fix it:

### 1. Check if Backend is Running

The backend server must be running on port 8000. To start it:

```bash
cd backend
python -m uvicorn app.main:app --reload
```

You should see output like:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 2. Check if Frontend is Running

The frontend server should be running on port 3000:

```bash
cd frontend
npm run dev
```

You should see:
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:3000/
```

### 3. Verify Backend is Accessible

Open your browser and visit:
- http://localhost:8000/ - Should show `{"message":"RW Tournament Software API"}`
- http://localhost:8000/docs - Should show Swagger API documentation

### 4. Check Browser Console

Open browser DevTools (F12) and check the Console tab for detailed error messages.

### 5. Common Issues

#### Backend Not Started
- **Symptom**: "Failed to fetch" or connection refused
- **Solution**: Start the backend server (see step 1)

#### Wrong Port
- **Symptom**: Backend on different port
- **Solution**: Update `frontend/vite.config.ts` proxy target or set `VITE_API_BASE_URL` environment variable

#### CORS Issues
- **Symptom**: CORS errors in browser console
- **Solution**: Backend already has CORS enabled, but if issues persist, check `backend/app/main.py` CORS settings

#### Firewall/Antivirus
- **Symptom**: Connection timeout
- **Solution**: Allow Python and Node.js through firewall

### Quick Start Script

Use the `start-dev.bat` script to start both servers:

```bash
start-dev.bat
```

This will open two command windows - one for backend, one for frontend.

### Manual Verification

1. **Backend Health Check:**
   ```bash
   curl http://localhost:8000/
   ```
   Should return: `{"message":"RW Tournament Software API"}`

2. **Frontend API Test:**
   Open browser console and run:
   ```javascript
   fetch('http://localhost:8000/api/tournaments')
     .then(r => r.json())
     .then(console.log)
   ```
   Should return an array (empty if no tournaments yet)

### Still Having Issues?

1. Check that both servers are actually running (check task manager or process list)
2. Verify no other application is using ports 8000 or 3000
3. Check Windows Firewall settings
4. Try restarting both servers
5. Clear browser cache and hard refresh (Ctrl+Shift+R)

