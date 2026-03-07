# CLAUDE_v4_hotfix.md — Urgent fix: dual auth system conflict

## Problem

After v4 deploy, there are TWO auth systems running simultaneously:
1. **JWT login form** (new) — stores token in `localStorage`, works for `/stream`, `/reports`
2. **HTTP Basic Auth** (old `check_auth`) — still used by several endpoints, triggers browser's native Basic Auth popup

When user logs in via the JWT form, the app works briefly, then browser shows a **second login popup** (Basic Auth) when calling `/default-sections`, `/docx`, `/slides`, `/legal-appendix`, etc.

## Fix required

### Step 1: Replace ALL `check_auth` dependencies with `get_current_user`

Find every endpoint using `Depends(check_auth)` and replace with `Depends(get_current_user)`:

```python
# Lines to fix (approximately):
# ~989:  get_default_sections  → Depends(get_current_user)
# ~1120: generate_slides       → Depends(get_current_user)
# ~1171: export_docx           → Depends(get_current_user)
# ~2451: legal-refs            → Depends(get_current_user)
# ~2467: generate_legal_appendix → Depends(get_current_user)
```

Also update the function signatures — these currently use `user: str`, change to `user: dict`:
```python
# Before:
async def get_default_sections(mode: str = "sector", user: str = Depends(check_auth)):
# After:
async def get_default_sections(mode: str = "sector", user: dict = Depends(get_current_user)):
```

### Step 2: Remove HTTP Basic Auth entirely

Remove or comment out:
```python
security = HTTPBasic()
```

Remove `HTTPBasic` and `HTTPBasicCredentials` from imports.

Remove the `check_auth` function entirely (lines ~230-240).

### Step 3: Fix `get_current_user` — remove Basic Auth fallback

In `get_current_user`, remove the HTTP Basic Auth fallback (lines ~197-228). The function should ONLY accept JWT Bearer tokens:

```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Validate JWT token and return user dict."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("username")
        if not username:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")
    
    # Try DB first
    if db_pool:
        conn = None
        try:
            conn = db_pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT id, username, plan FROM users WHERE username=%s AND is_active=true", (username,))
            row = cur.fetchone()
            if row:
                return {"id": row[0], "username": row[1], "plan": row[2]}
        except Exception:
            pass
        finally:
            if conn:
                release_db_conn(conn)
    
    # Fallback: env var user (hoang)
    env_user = os.getenv("APP_USERNAME", "hoang")
    if username == env_user:
        return {"id": 0, "username": username, "plan": "admin"}
    
    raise HTTPException(401, "User not found")
```

### Step 4: Fix `apiFetch` in frontend — handle 401 correctly

When any API call returns 401, clear localStorage and show login form:
```javascript
function apiFetch(url, opts={}) {
  const token = getToken();
  if (!opts.headers) opts.headers = {};
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  return fetch(url, opts).then(resp => {
    if (resp.status === 401) {
      clearToken();
      showLoginPage();
      throw new Error('Session expired. Please log in again.');
    }
    return resp;
  });
}
```

### Step 5: Fix login — seed user correctly

The `hoang` user exists in DB but password hash may be incompatible (bcrypt version issue with passlib).

Add a one-time fix in the `/auth/login` endpoint: if DB lookup fails, fall back to env var check:
```python
# In /auth/login endpoint:
# 1. Try DB lookup + bcrypt verify
# 2. If fails OR user not in DB: check against APP_USERNAME/APP_PASSWORD env vars
# 3. If env var match: return valid JWT token
# This ensures hoang/taxsector2026 always works
```

Also re-seed `hoang` user with a fresh bcrypt hash:
```python
# On app startup, if users table is empty or hoang doesn't exist:
# INSERT hoang with fresh hash using current passlib version
@app.on_event("startup")
async def seed_admin():
    # ... seed hoang user ...
```

---

## Deployment (same as before)

```bash
ssh -i ~/.ssh/id_ed25519_vps root@72.62.197.183
docker cp main.py b48cggoog8k0gw8s40gskkg0-164819471497:/app/main.py
docker restart b48cggoog8k0gw8s40gskkg0-164819471497
sleep 5
# Test: no Basic Auth popup, JWT login works
curl -s -X POST https://sectortax.gpt4vn.com/auth/login \
  -F 'username=hoang' -F 'password=taxsector2026' | python3 -m json.tool
```

## Test checklist after fix:
- [ ] Open sectortax.gpt4vn.com → shows app with login overlay (NOT browser Basic Auth popup)
- [ ] Login with hoang/taxsector2026 → success, app loads
- [ ] Click "Default sections" → loads without Basic Auth popup
- [ ] Export DOCX → works without popup
- [ ] Slides export → works without popup
- [ ] Appendix → works without popup
- [ ] Logout → returns to login form

---
*ThanhAI hotfix — 2026-03-07*
