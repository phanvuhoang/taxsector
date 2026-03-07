# CLAUDE_v4.md — Instructions for Claude Code
## Tax Sector Research App — sectortax.gpt4vn.com

### Context
- App: FastAPI + Python, deployed on Coolify VPS (72.62.197.183)
- GitHub: github.com/phanvuhoang/taxsector (branch: main)
- File to edit: `main.py` (single-file app, ~1750 lines)
- Container name (Coolify): `b48cggoog8k0gw8s40gskkg0-164819471497`
- Volume mount: `/opt/tax-research-reports` → `/app/reports` (local VPS only)
- rclone is NOT available inside the container — only on the VPS host
- python-docx 1.1.2 is installed in container

---

## Tasks

### Task 1 — Remove "AI Gợi ý cấu trúc" button

Remove the button with id `btn-recommend` and its associated JS function `aiRecommend()`.
Also remove the `suggestSubs()` function and any button calling it (the ✨ per-section AI suggest button).
Remove the `/validate-subject` API endpoint as well — it's no longer needed.
Keep all other buttons and functionality intact.

---

### Task 2 — Google Drive report storage (persist across container restarts)

**Problem:** Reports saved to `/app/reports` inside the container are lost when Coolify rebuilds/restarts the container. The VPS volume mount `/opt/tax-research-reports:/app/reports` helps for restarts, but not for full rebuilds.

**Solution:** Use Google Drive as the source of truth via the Google Drive API (service account or API key approach). Since `rclone` is not inside the container, use the `google-auth` + `googleapiclient` Python libraries instead.

**Implementation details:**

1. Add to `requirements.txt`:
   ```
   google-auth==2.29.0
   google-auth-httplib2==0.2.0
   google-api-python-client==2.131.0
   ```

2. Add env var `GDRIVE_FOLDER_ID` — the Google Drive folder ID for report storage.
   The folder is `gdrive:Thanh-AI/TaxResearch/` on the owner's Drive.
   Folder ID will be provided via environment variable.

3. Use a **Service Account JSON** stored as env var `GDRIVE_SERVICE_ACCOUNT_JSON` (base64-encoded).
   If the env var is not set, fall back to local-only storage (graceful degradation).

4. Modify `save_report_local()`:
   - Save to `/app/reports/` as before (local cache)
   - After saving, upload to GDrive asynchronously (non-blocking, use `asyncio.create_task`)
   - Upload function: `async def upload_to_gdrive(fname: str, content: bytes)`

5. Modify `list_reports` endpoint (`GET /reports`):
   - First check local `/app/reports/` 
   - Also list files from GDrive folder
   - Merge, deduplicate by filename, return combined list sorted newest first
   - If GDrive file not in local cache, download it on-demand when opened

6. Modify `GET /report/{fname}`:
   - If file exists locally, serve it
   - If not, try to download from GDrive, cache locally, then serve

7. Modify `DELETE /report/{fname}`:
   - Delete from local + GDrive

**IMPORTANT:** All GDrive operations must fail gracefully — if GDrive is unavailable or not configured, the app continues working with local storage only. Never let a GDrive error break the app.

---

### Task 3 — "Báo cáo đã lưu" button improvements

**3a. Show button on initial screen (before report is generated)**

Currently the "📂 Báo cáo đã lưu" button only appears after a report is generated (inside `#report-wrap`). 

Move it to the **header bar** so it's always visible. The header already has it at line ~1045, but it may be hidden or not rendering on initial load — make sure it's always visible regardless of state.

**3b. Reports list UI improvements**

In the `loadReportsList()` function, update the reports modal to:

1. **Sort newest first** (already done, keep it)
2. **Show 10 most recent by default**, with a "📂 Xem thêm (N báo cáo)" button if total > 10
3. **Add a search box** at the top of the modal:
   ```html
   <input type="text" id="reports-search" placeholder="🔍 Tìm báo cáo..." 
     class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-green-300"
     oninput="filterReports(this.value)">
   ```
4. Implement `filterReports(query)` — filters the displayed list in real-time by filename (case-insensitive, Vietnamese-aware)
5. When searching, ignore the 10-item limit (show all matching results)

---

### Task 4 — Fix DOCX export (intermittent failures)

The `/docx` endpoint uses `BeautifulSoup` for HTML parsing. Failures occur when:
- `bs4` import fails silently
- HTML passed is empty or malformed
- `Document()` from python-docx raises on edge cases

**Fixes:**

1. Add explicit import guard at top of file:
   ```python
   try:
       from bs4 import BeautifulSoup
       BS4_OK = True
   except ImportError:
       BS4_OK = False
   ```

2. In `/docx` endpoint, add validation:
   ```python
   if not html or not html.strip():
       raise HTTPException(400, "Không có nội dung báo cáo để xuất. Vui lòng tạo báo cáo trước.")
   if not BS4_OK:
       raise HTTPException(503, "BeautifulSoup không khả dụng. Liên hệ admin.")
   ```

3. Wrap the entire document generation in try/except:
   ```python
   try:
       # ... existing docx generation code ...
   except Exception as e:
       raise HTTPException(500, f"Lỗi xuất DOCX: {str(e)}")
   ```

4. In the frontend `exportDocx()` JS function, improve error handling:
   - Show the actual error message from the server (not just "Không xuất được")
   - Disable the button while exporting, re-enable after
   - Example:
   ```javascript
   } catch(e) {
     alert(`Không xuất được DOCX: ${e.message}`);
   }
   ```

---

## Deployment

After making changes:
1. Commit to `main` branch on GitHub
2. SSH to VPS: `ssh -i ~/.ssh/id_ed25519_vps root@72.62.197.183`
3. Copy file to running Coolify container:
   ```bash
   docker cp /path/to/main.py b48cggoog8k0gw8s40gskkg0-164819471497:/app/main.py
   docker restart b48cggoog8k0gw8s40gskkg0-164819471497
   ```
4. Verify: `curl -s -u hoang:taxsector2026 https://sectortax.gpt4vn.com/ | grep 'Báo cáo đã lưu'`

Note: Do NOT use `docker build` — just copy `main.py` directly into the running container. The container already has all dependencies installed.

---

## Environment Variables (already set in Coolify)
```
PERPLEXITY_API_KEY=pplx-...
CLAUDIBLE_API_KEY=sk-...
CLAUDIBLE_BASE_URL=https://claudible.io/v1
CLAUDIBLE_MODEL=claude-sonnet-4.6
APP_USERNAME=hoang
APP_PASSWORD=taxsector2026
REPORTS_DIR=/app/reports
```

Variables to ADD in Coolify for GDrive (Task 2):
```
GDRIVE_FOLDER_ID=<folder_id_of_Thanh-AI/TaxResearch>
GDRIVE_SERVICE_ACCOUNT_JSON=<base64_encoded_service_account_json>
```

---

*Written by ThanhAI — 2026-03-07*
