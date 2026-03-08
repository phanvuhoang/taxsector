# CLAUDE_v5.md — 4 enhancements for taxsector

Read and apply ALL changes below to `main.py`. Test after changes: `python3 -m py_compile main.py && echo OK`

---

## Change 1: Remove "✨ AI Gợi ý cấu trúc" button

**Reason:** Feature added in v3 but not working reliably / not needed.

**Action:** In the `HTML_PAGE` string, find and DELETE this entire block:

```html
<div class="mt-3 flex items-center gap-3">
  <button id="btn-recommend" onclick="aiRecommend()"
    class="btn btn-green text-sm">
    ✨ AI Gợi ý cấu trúc cho chủ đề này
  </button>
  <span id="recommend-hint" class="text-xs" style="color:var(--muted)">
    Nhập tên ngành/công ty rồi bấm để AI đề xuất sections phù hợp
  </span>
</div>
```

Also find and DELETE the `aiRecommend()` JavaScript function (around line 1800+):

```javascript
async function aiRecommend() {
  const subject = document.getElementById('subj-input').value.trim();
  // ... entire function ...
}
```

And DELETE the `/recommend-sections` endpoint in the Python code (around line 1030):

```python
@app.post("/recommend-sections")
async def recommend_sections(request: Request, user: dict = Depends(get_current_user)):
    # ... entire endpoint ...
```

**Verification:** Search for "aiRecommend" and "recommend-sections" — should find NO matches after deletion.

---

## Change 2: "Báo cáo đã lưu" button on main screen + enhanced list

### A) Add button to main screen (before starting analysis)

In `HTML_PAGE`, find the main header section (around "Tax Sector Research Tool" title) and add the button AFTER the mode selector (sector/company toggle):

```html
<!-- After the mode toggle div, add: -->
<div class="mt-4">
  <button onclick="showReports()" 
    class="w-full sm:w-auto bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white px-6 py-3 rounded-xl font-semibold text-sm shadow-lg hover:shadow-xl transition-all flex items-center justify-center gap-2">
    📂 Báo cáo đã lưu
    <span class="text-xs opacity-75" id="reports-count-badge"></span>
  </button>
</div>
```

### B) Update reports modal with search box + expand more

Find the reports modal HTML (around line 1450) and REPLACE the entire `<div id="reports-modal" ...>` block with:

```html
<div id="reports-modal" class="hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
  <div class="bg-white rounded-3xl shadow-2xl max-w-3xl w-full max-h-[85vh] flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between p-6 border-b border-gray-200">
      <div>
        <h3 class="text-xl font-bold text-gray-800">📂 Báo cáo đã lưu</h3>
        <p class="text-xs text-gray-500 mt-1">Sắp xếp từ mới nhất → cũ nhất</p>
      </div>
      <button onclick="closeReports()" class="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
    </div>
    
    <!-- Search box -->
    <div class="px-6 py-4 border-b border-gray-100">
      <input type="text" id="reports-search" placeholder="🔍 Tìm kiếm báo cáo theo tên ngành, công ty..." 
        oninput="filterReports(this.value)"
        class="w-full px-4 py-2.5 rounded-xl border border-gray-300 focus:border-green-500 focus:ring-2 focus:ring-green-200 outline-none text-sm transition-all">
    </div>
    
    <!-- Report list (scrollable) -->
    <div class="flex-1 overflow-y-auto p-6">
      <div id="reports-list" class="space-y-2">
        <p class="text-sm text-gray-400">Đang tải...</p>
      </div>
    </div>
  </div>
</div>
```

### C) Update reports list rendering (sort + limit 10 + expand)

Already done in existing code — verify these functions exist and work:
- `loadReportsList(showAll=false)` — loads and sorts by mtime DESC
- `renderReportList(data, showAll=false)` — shows 10 by default, "Xem thêm" button if more
- `filterReports(query)` — filters by subject/name

**Add badge count update:** In `loadReportsList()`, after loading data, add:

```javascript
async function loadReportsList(showAll=false){
  // ... existing code ...
  const data = await resp.json();
  data.sort((a,b)=>(b.mtime||0)-(a.mtime||0));
  allReportsData = data;
  
  // Update badge count on main screen button
  const badge = document.getElementById('reports-count-badge');
  if(badge) badge.textContent = data.length ? `(${data.length})` : '';
  
  renderReportList(data, showAll);
}
```

---

## Change 3: Fix "Xuất báo cáo ra file docx" button (unstable)

**Root cause analysis:** The docx export likely fails because:
1. Missing `python-docx` library in some environments
2. Timeout issues with large reports
3. HTML parsing errors (bs4 missing or malformed HTML)

### A) Add dependency check and auto-install fallback

At the top of `main.py`, find the docx import section and UPDATE:

```python
try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_OK = True
    print("[DOCX] python-docx imported successfully")
except ImportError:
    print("[DOCX] python-docx not found, attempting install...")
    try:
        import subprocess as _pip_sp
        _pip_sp.run(["pip", "install", "python-docx", "-q"], check=True, timeout=60)
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        DOCX_OK = True
        print("[DOCX] python-docx installed and imported")
    except Exception as e:
        print(f"[DOCX] Installation failed: {e}")
        DOCX_OK = False
```

### B) Add better error handling and timeout in `export_docx()` endpoint

Find the `@app.post("/export-docx")` endpoint (around line 1207) and wrap the conversion logic:

```python
@app.post("/export-docx")
async def export_docx(request_body: dict, user: dict = Depends(get_current_user)):
    if not DOCX_OK:
        raise HTTPException(500, "python-docx library not available")
    if not BS4_OK:
        raise HTTPException(500, "beautifulsoup4 library not available")
    
    subject = request_body.get("subject", "Report")
    html_content = request_body.get("html", "")
    
    if not html_content.strip():
        raise HTTPException(400, "Missing HTML content")
    
    try:
        # Run conversion in thread pool (avoid blocking)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_html_to_docx, subject, html_content)
            buffer = future.result(timeout=30)  # 30s timeout
        
        return StreamingResponse(
            BytesIO(buffer.getvalue()),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="TaxReport_{subject[:30]}_{datetime.now():%Y%m%d}.docx"'}
        )
    
    except concurrent.futures.TimeoutError:
        raise HTTPException(504, "Export timeout — report too large or server busy")
    except Exception as e:
        print(f"[DOCX] Export error: {e}")
        raise HTTPException(500, f"Export failed: {str(e)[:200]}")


def _html_to_docx(subject: str, html_content: str) -> BytesIO:
    """Helper: convert HTML to DOCX (runs in thread pool)."""
    doc = DocxDocument()
    
    # Title
    title = doc.add_heading(f"Phân Tích Thuế — {subject}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Parse HTML
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Extract text with basic formatting
    for elem in soup.descendants:
        if elem.name == "h2":
            doc.add_heading(elem.get_text(strip=True), level=1)
        elif elem.name == "h3":
            doc.add_heading(elem.get_text(strip=True), level=2)
        elif elem.name == "p":
            text = elem.get_text(strip=True)
            if text:
                p = doc.add_paragraph(text)
                p.style = "Normal"
        elif elem.name == "ul":
            for li in elem.find_all("li", recursive=False):
                doc.add_paragraph(li.get_text(strip=True), style="List Bullet")
        elif elem.name == "ol":
            for li in elem.find_all("li", recursive=False):
                doc.add_paragraph(li.get_text(strip=True), style="List Number")
    
    # Save to buffer
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer
```

**Note:** If conversion is still slow, consider caching docx files or offering async download.

---

## Change 4: Store reports on Google Drive (not local VPS)

**Problem:** Reports saved to `/app/reports/` or `REPORTS_DIR` are lost when container restarts.

**Solution:** Upload reports to Google Drive via `rclone` after generation.

### A) Verify `rclone` is available and configured

At startup, check rclone:

```python
@app.on_event("startup")
async def startup():
    global db_pool
    # ... existing DB pool setup ...
    
    # Check rclone for GDrive backup
    try:
        result = subprocess.run(["rclone", "version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            print("[RCLONE] Available for GDrive backup")
        else:
            print("[RCLONE] Not configured or unavailable")
    except Exception as e:
        print(f"[RCLONE] Check failed: {e}")
```

### B) Update `save_report_local()` to also save to GDrive

Find `save_report_local()` function (around line 604) and ADD GDrive upload at the end:

```python
def save_report_local(subject: str, html: str, sources: list, 
                      mode: str = "sector") -> str:
    """Save report HTML to local + upload to GDrive."""
    now = datetime.now()
    fname = f"{now:%Y%m%d} - {subject[:50]} - {now:%H%M}.html"
    
    # Clean filename
    fname = re.sub(r'[<>:"/\\|?*]', '', fname)
    
    # Full HTML document
    full_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Phân Tích Thuế — {subject}</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 2rem auto; padding: 1rem; line-height: 1.7; color: #1f2937; }}
  h1 {{ color: #059669; border-bottom: 3px solid #059669; padding-bottom: 0.5rem; }}
  h2 {{ color: #047857; margin-top: 2rem; }}
  h3 {{ color: #065f46; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; }}
  th {{ background: #f3f4f6; font-weight: 600; }}
  a {{ color: #059669; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .disclaimer {{ margin-top: 3rem; padding: 1rem; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 0.5rem; font-size: 0.85rem; color: #64748b; }}
</style>
</head>
<body>
<h1>Phân Tích Thuế — {subject}</h1>
<p style="color: #6b7280; font-size: 0.9rem;">Ngày tạo: {now:%d/%m/%Y %H:%M} | Mode: {mode} | Perplexity + Claude AI</p>
{html}
<div class="disclaimer">
  <strong>⚠️ Lưu ý:</strong> Báo cáo này được tạo tự động bởi <strong>Tax Sector Research AI</strong> 
  dựa trên dữ liệu từ Perplexity (sonar model) và thuvienphapluat.vn. Nội dung mang tính tham khảo, 
  không thay thế tư vấn pháp lý hoặc thuế chuyên nghiệp. Người dùng cần kiểm chứng độc lập trước khi áp dụng.
  <br><em>Generated: {now:%Y-%m-%d %H:%M:%S}</em>
</div>
</body>
</html>"""
    
    # Save to local (for immediate access)
    local_path = REPORTS_DIR / fname
    local_path.write_text(full_html, encoding="utf-8")
    print(f"[REPORT] Saved locally: {fname}")
    
    # Upload to GDrive via rclone (async, non-blocking)
    try:
        gdrive_dest = f"{GDRIVE_FOLDER}/{fname}"
        subprocess.Popen(
            ["rclone", "copyto", str(local_path), f"gdrive:{gdrive_dest}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"[REPORT] Uploading to GDrive: {gdrive_dest}")
    except Exception as e:
        print(f"[REPORT] GDrive upload failed (non-fatal): {e}")
    
    return fname
```

### C) Update `/reports` endpoint to list from GDrive if local is empty

Find the `@app.get("/reports")` endpoint and UPDATE:

```python
@app.get("/reports")
async def list_reports(user: dict = Depends(get_current_user)):
    """List saved reports from local + GDrive."""
    reports = []
    
    # Local reports
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*.html"):
            reports.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                "subject": f.name.split(" - ")[1] if " - " in f.name else f.stem,
                "url": f"/report/{f.name}",
                "source": "local"
            })
    
    # GDrive reports (if local is empty or has <5 reports)
    if len(reports) < 5:
        try:
            result = subprocess.run(
                ["rclone", "lsjson", f"gdrive:{GDRIVE_FOLDER}/"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                gdrive_files = json.loads(result.stdout)
                for f in gdrive_files:
                    if f["Name"].endswith(".html"):
                        reports.append({
                            "name": f["Name"],
                            "size": f["Size"],
                            "mtime": datetime.fromisoformat(f["ModTime"].replace("Z", "+00:00")).timestamp(),
                            "subject": f["Name"].split(" - ")[1] if " - " in f["Name"] else f["Name"].replace(".html", ""),
                            "url": f"/report/{f['Name']}",  # Will fetch from GDrive on demand
                            "source": "gdrive"
                        })
        except Exception as e:
            print(f"[REPORTS] GDrive list failed: {e}")
    
    # Sort by mtime desc
    reports.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return reports
```

### D) Update `/report/{filename}` endpoint to fetch from GDrive if not local

```python
@app.get("/report/{filename}")
async def get_report(filename: str, user: dict = Depends(get_current_user)):
    """Serve saved report HTML (local or GDrive)."""
    # Sanitize filename
    safe_name = re.sub(r'[<>:"/\\|?*]', '', filename)
    local_path = REPORTS_DIR / safe_name
    
    # Try local first
    if local_path.exists():
        return HTMLResponse(local_path.read_text(encoding="utf-8"))
    
    # Try GDrive
    try:
        result = subprocess.run(
            ["rclone", "cat", f"gdrive:{GDRIVE_FOLDER}/{safe_name}"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return HTMLResponse(result.stdout)
    except Exception as e:
        print(f"[REPORT] GDrive fetch failed: {e}")
    
    raise HTTPException(404, "Report not found")
```

---

## After all changes

```bash
# Syntax check
python3 -m py_compile main.py && echo "✅ Syntax OK"

# Test locally (if possible)
# python3 main.py

# Commit
git add main.py CLAUDE_v5.md
git commit -m "feat: remove AI suggest button, reports on main screen + search + GDrive storage, fix docx export"
git push origin main
```

---

## Deployment notes for Thanh AI

After Claude Code commits the changes:

1. **SSH to VPS:**
   ```bash
   ssh -i ~/.ssh/id_ed25519_vps root@72.62.197.183
   ```

2. **Pull latest code:**
   ```bash
   cd /data/tax-research-tool  # or wherever the repo is
   git pull origin main
   ```

3. **Restart container (via Coolify or Docker):**
   ```bash
   docker restart tax-research-tool
   # Or via Coolify UI: redeploy the app
   ```

4. **Verify:**
   - Check https://taxsector.gpt4vn.com
   - Test "Báo cáo đã lưu" button on main screen
   - Test search box
   - Test docx export (should not timeout)
   - Verify reports are being uploaded to GDrive (check `rclone lsd gdrive:Thanh-AI/TaxResearch/`)

---

**Claude v5 features:**
1. ❌ Removed "AI Gợi ý" button + endpoint
2. ✅ "Báo cáo đã lưu" on main screen with count badge
3. ✅ Search box + sort + expand (10 default, "xem thêm" for more)
4. ✅ Fixed docx export with timeout handling + better error messages
5. ✅ GDrive storage via rclone (reports persist across restarts)
