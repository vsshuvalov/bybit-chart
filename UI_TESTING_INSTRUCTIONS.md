# UI Testing Instructions

## 🔧 Fix Applied

**Created:** `web/.env`
```
VITE_API_URL=http://83.147.234.167
```

**Action Required:** Restart Vite dev server

```bash
# In terminal
cd /Users/vs/Desktop/bybit-chart/web
npm run dev
```

---

## 🧪 How to Test

### 1. Open Browser
```
http://localhost:5173
```

### 2. Open DevTools Console (F12)

**Check environment variable loaded:**
```javascript
import.meta.env.VITE_API_URL
// Should show: "http://83.147.234.167"
```

**Test API calls:**
```javascript
fetch('http://83.147.234.167/api/v1/drawings?symbol=BTCUSDT')
  .then(r => r.json())
  .then(d => console.log('Drawings:', d))
```

### 3. Check Network Tab

**Expected:**
- ✅ Requests go to `http://83.147.234.167/api/v1/...` (NOT localhost:8000)
- ✅ Status: 200 OK
- ✅ **No CORS errors**

---

## ✅ Success Criteria

- ✅ VITE_API_URL points to production (83.147.234.167)
- ✅ No CORS errors
- ✅ API responses visible in console
- ✅ Drawings/workspaces data loads

---

**After restart, reload browser:** http://localhost:5173
