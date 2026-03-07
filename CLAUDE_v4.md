# CLAUDE_v4.md — Instructions for Claude Code
## Tax Sector Research App — sectortax.gpt4vn.com
## Version: 4.0 | Date: 2026-03-07 | Author: ThanhAI

---

## Context & Current State

- **App:** FastAPI single-file app (`main.py`, ~1750 lines), Python 3.11
- **GitHub:** github.com/phanvuhoang/taxsector (branch: main)
- **Live URL:** https://sectortax.gpt4vn.com
- **Coolify container:** `b48cggoog8k0gw8s40gskkg0-164819471497`
- **Current auth:** Simple HTTP Basic Auth (single user: hoang/taxsector2026)
- **Reports storage:** Local `/app/reports/` — lost on full container rebuild

### Infrastructure already set up (DO NOT recreate):
- **PostgreSQL** is running at host `postgresql-pgwo0w8g0c0ccg840kw84gs8` port `5432`
- Database `sectortax` exists with tables `users` and `reports` already created
- DB user: `sectortax_user` / password: `SectorTax2026Secure`
- The sectortax container is already connected to the postgres network
- `psycopg2-binary` needs to be added to `requirements.txt`

### Schema (already exists, do NOT recreate):
```sql
users (id, username, email, password_hash, plan, is_active, created_at, last_login)
reports (id, user_id, filename, subject, mode, file_size, storage_path, created_at)
```

---

## Tasks — implement ALL in one pass

---

### Task 1 — Remove "AI Gợi ý cấu trúc" buttons

Remove completely:
- Button `id="btn-recommend"` with `onclick="aiRecommend()"` and the `aiRecommend()` JS function
- The ✨ per-section button calling `suggestSubs()` and the `suggestSubs()` function
- The `/validate-subject` POST endpoint (no longer needed)

Keep everything else intact.

---

### Task 2 — Multi-user auth with PostgreSQL (JWT)

Replace the current HTTP Basic Auth with proper JWT-based session auth.

**2a. Backend changes:**

Add to `requirements.txt`:
```
psycopg2-binary==2.9.9
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
```

Add DB connection pool at startup:
```python
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import timedelta

DB_HOST = os.getenv("DB_HOST", "postgresql-pgwo0w8g0c0ccg840kw84gs8")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "sectortax")
DB_USER = os.getenv("DB_USER", "sectortax_user")
DB_PASS = os.getenv("DB_PASS", "SectorTax2026Secure")
JWT_SECRET = os.getenv("JWT_SECRET", "sectortax-jwt-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
db_pool = None

@app.on_event("startup")
async def startup():
    global db_pool
    try:
        db_pool = ThreadedConnectionPool(1, 10,
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASS)
    except Exception as e:
        print(f"DB connection failed: {e}")
```

**2b. Auth endpoints:**

```python
@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # verify username/password against DB
    # return JWT token + user info

@app.post("/auth/register")  
async def register(...):
    # create new user in DB (plan='free')
    # return JWT token

@app.get("/auth/me")
async def me(token: str = Depends(oauth2_scheme)):
    # return current user info
```

**2c. Dependency injection:**

Replace the existing `auth` dependency with JWT-based:
```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    # decode JWT, fetch user from DB, return user dict
    # raise HTTPException(401) if invalid
```

Use `get_current_user` everywhere the old `auth` dependency was used.

**2d. Fallback:** If DB is unavailable, fall back to env var auth (APP_USERNAME/APP_PASSWORD) so the app doesn't break.

**2e. Frontend login page:**

Replace the browser's HTTP Basic Auth dialog with a proper login page.
When a request returns 401 (not logged in), show a full-page login form:
```html
<!-- Clean login page, same green brand color (#028a39) -->
<!-- Fields: username, password -->
<!-- On success: store JWT in localStorage, redirect to app -->
<!-- "Register" link below login form -->
```

Store JWT in `localStorage` as `sectortax_token`.
Send it as `Authorization: Bearer <token>` header in all API calls (update `apiFetch()`).

---

### Task 3 — Reports: GDrive sync + per-user storage

**3a. Per-user report storage**

Modify `save_report_local()` to:
1. Accept `user_id` parameter
2. Save file to `/app/reports/{user_id}/filename.html` (per-user subfolder)
3. Insert record into `reports` table:
   ```sql
   INSERT INTO reports (user_id, filename, subject, mode, file_size, storage_path)
   VALUES (%s, %s, %s, %s, %s, %s)
   ```

**3b. GDrive sync (best-effort)**

After saving locally, sync to GDrive using `subprocess` to call `rclone` on the **VPS host** via SSH.

Since `rclone` is not inside the container but IS on the VPS host (configured with `gdrive` remote), use this approach:

```python
import subprocess

async def sync_to_gdrive(local_path: str, user_id: int, filename: str):
    """Sync report to GDrive via rclone on VPS host. Best-effort, never blocks."""
    try:
        gdrive_path = f"gdrive:Thanh-AI/TaxResearch/user_{user_id}/{filename}"
        # rclone is on the host, mounted via /usr/local/bin/rclone or similar
        # Use nsenter to run on host, or map rclone binary via volume
        subprocess.Popen(
            ["rclone", "copyto", local_path, gdrive_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass  # GDrive sync failure must never break the app
```

**Note for Claude Code:** Check if `rclone` is available inside the container via `shutil.which('rclone')`. If not available, skip GDrive sync silently. The Dockerfile can optionally install rclone — add this to Dockerfile if needed:
```dockerfile
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://rclone.org/install.sh | bash && \
    rm -rf /var/lib/apt/lists/*
```
But DO NOT add this if it makes the build too heavy. Local storage is sufficient for now.

**3c. Reports listing (GET /reports)**

Modify to return only the current user's reports from DB:
```sql
SELECT r.filename, r.subject, r.file_size, r.created_at, r.storage_path
FROM reports r
WHERE r.user_id = %s
ORDER BY r.created_at DESC
LIMIT 100
```

**3d. Report access control**

`GET /report/{fname}` — only serve if the report belongs to current user.
`DELETE /report/{fname}` — only delete if report belongs to current user, delete from DB too.

---

### Task 4 — "Báo cáo đã lưu" UI improvements

**4a. Always visible on header**

The "📂 Báo cáo đã lưu" button is already in the header at line ~1045. Make sure it's visible and functional even before a report is generated (currently may be hidden). It should always be clickable from the moment the page loads.

**4b. Reports modal improvements**

Update `loadReportsList()`:

1. **Show 10 most recent** by default, sorted newest first
2. **"Xem thêm" button** if total > 10:
   ```html
   <button onclick="loadReportsList(true)" class="...">
     📂 Xem thêm (N báo cáo)
   </button>
   ```
3. **Search box** at top of modal:
   ```html
   <input type="text" id="reports-search" 
     placeholder="🔍 Tìm theo tên báo cáo..."
     class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-3"
     oninput="filterReports(this.value)">
   ```
4. `filterReports(query)` — real-time filter by subject/filename, case-insensitive, shows all matches (ignores 10-item limit)

---

### Task 5 — Fix DOCX export

The `/docx` endpoint fails intermittently. Fix:

1. Add at top of file:
```python
try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False
```

2. In `/docx` endpoint, validate inputs first:
```python
if not html or not html.strip():
    raise HTTPException(400, "Không có nội dung báo cáo để xuất.")
if not BS4_OK:
    raise HTTPException(503, "BeautifulSoup không khả dụng.")
```

3. Wrap document generation in try/except:
```python
try:
    # ... existing code ...
except Exception as e:
    raise HTTPException(500, f"Lỗi tạo DOCX: {str(e)}")
```

4. Frontend `exportDocx()` — show actual server error message:
```javascript
const errText = await resp.text();
alert(`Không xuất được DOCX: ${errText}`);
```

---

## Deployment instructions

After making all changes:

### Step 1: Commit to GitHub
```bash
git add -A
git commit -m "feat: multi-user auth, PostgreSQL reports, UI improvements, docx fix"
git push origin main
```

### Step 2: Deploy to Coolify container
```bash
# SSH to VPS
ssh -i ~/.ssh/id_ed25519_vps root@72.62.197.183

# Copy main.py to running container
docker cp main.py b48cggoog8k0gw8s40gskkg0-164819471497:/app/main.py

# Install new dependencies inside container
docker exec b48cggoog8k0gw8s40gskkg0-164819471497 pip install \
  psycopg2-binary==2.9.9 \
  "python-jose[cryptography]==3.3.0" \
  "passlib[bcrypt]==1.7.4" \
  python-multipart==0.0.9 -q

# Restart
docker restart b48cggoog8k0gw8s40gskkg0-164819471497

# Verify
curl -s https://sectortax.gpt4vn.com/ | grep -c 'login\|Đăng nhập'
```

### Step 3: Add env vars in Coolify dashboard (cl.gpt4vn.com)
Add these to the sectortax application environment:
```
DB_HOST=postgresql-pgwo0w8g0c0ccg840kw84gs8
DB_PORT=5432
DB_NAME=sectortax
DB_USER=sectortax_user
DB_PASS=SectorTax2026Secure
JWT_SECRET=sectortax-jwt-2026-change-this
```

### Step 4: Create default admin user
After deployment, the `hoang` user needs to be seeded into PostgreSQL:
```bash
docker exec postgresql-pgwo0w8g0c0ccg840kw84gs8 psql -U XknVFqfKI30PJava -d sectortax -c "
  INSERT INTO users (username, email, password_hash, plan)
  VALUES ('hoang', 'vuhoang04@gmail.com', 
    crypt('taxsector2026', gen_salt('bf')), 'admin')
  ON CONFLICT (username) DO NOTHING;
"
```
Or implement a `/auth/seed-admin` endpoint (protected, one-time use).

---

## Important constraints

1. **Single file** — keep everything in `main.py`, do not split into multiple files
2. **Graceful degradation** — if DB is down, app must still work (fall back to env var auth + local reports)
3. **No breaking changes** — existing reports in `/app/reports/` should still be accessible
4. **Keep existing features** — all current functionality (Perplexity research, Claude AI, Dashboard, Slides, DOCX, Appendix) must continue working
5. **Do NOT change** the Coolify docker-compose or Dockerfile unless strictly necessary

---

*Written by ThanhAI — tax.gpt4vn.com | 2026-03-07*
