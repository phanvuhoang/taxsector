# BRIEF: Append sections — chạy background như generate

## Tổng quan
Hiện tại append-sections vẫn dùng stream cũ → bị stuck.
Chuyển sang background job giống /generate, save thành file mới có suffix a01, a02...

---

## Logic đặt tên file mới

Khi append, save thành file MỚI (không overwrite) với suffix:
```
Original:  "10032026 - FPT - 1430.html"
Append 1:  "10032026 - FPT - 1430-a01.html"
Append 2:  "10032026 - FPT - 1430-a02.html"
```

Function đặt tên trong backend:
```python
def make_append_filename(original_filename: str) -> str:
    """
    Tạo tên file mới cho append version.
    "abc.html" → "abc-a01.html"
    "abc-a01.html" → "abc-a02.html"
    """
    import re
    base = original_filename.replace('.html', '')
    match = re.search(r'-a(\d+)$', base)
    if match:
        n = int(match.group(1)) + 1
        base = re.sub(r'-a\d+$', f'-a{n:02d}', base)
    else:
        base = base + '-a01'
    return base + '.html'
```

---

## Backend changes

### 1. Endpoint POST /append-sections — trả về job_id ngay

Tìm endpoint `/append-sections` hiện tại.
Thay bằng background job pattern giống /generate:

```python
@app.post("/append-sections")
async def append_sections(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    subject         = body.get("subject", "").strip()
    mode            = body.get("mode", "sector")
    new_sections    = body.get("sections", [])
    original_file   = body.get("original_file", "")  # tên file gốc đang xem

    if not subject or not new_sections:
        raise HTTPException(400, "subject and sections required")

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Đang khởi tạo bổ sung...",
        "subject": subject,
        "mode": mode,
        "filename": None,
        "original_file": original_file,
        "is_append": True,       # flag để UI biết đây là append job
        "error": None,
        "created_at": datetime.now().isoformat(),
        "done_at": None,
    }

    asyncio.create_task(run_append_job(job_id, subject, mode, new_sections, original_file))
    return {"job_id": job_id}
```

### 2. Hàm background `run_append_job()`

```python
async def run_append_job(job_id: str, subject: str, mode: str,
                          new_sections: list, original_file: str):
    job = jobs[job_id]
    total = len(new_sections)

    try:
        job["status"] = "running"
        sonar = "sonar-pro"

        # ── Phase 1: Research sections mới ────────────────────
        job["message"] = "🔍 Đang research với Perplexity..."
        job["progress"] = 5

        all_results = {}
        tasks = [perplexity_search(build_query(s, subject, mode), sonar)
                 for s in new_sections]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for s, r in zip(new_sections, results):
            if not isinstance(r, Exception):
                all_results[s["id"]] = r

        # ── Phase 2: Generate từng section mới ────────────────
        new_html_parts = []
        for i, section in enumerate(new_sections):
            pct = 10 + int((i / total) * 80)
            job["progress"] = pct
            job["message"] = f"✍️ Đang viết {i+1}/{total}: {section['title']}"

            context = build_context(section, all_results)
            # Thêm hint: đây là bổ sung, viết nhất quán
            context += f"\n\nLƯU Ý: Đây là phần BỔ SUNG vào báo cáo về {subject}. Viết nhất quán."

            section_html = ""
            async for chunk in claude_stream_section(section, subject, context, mode, i+1):
                section_html += chunk
            new_html_parts.append(section_html)

        # ── Phase 3: Đọc file gốc + ghép + save file mới ──────
        job["progress"] = 92
        job["message"] = "💾 Đang lưu báo cáo bổ sung..."

        appended_html = "\n".join(new_html_parts)
        appended_html = await verify_legal_refs(appended_html)

        # Đọc nội dung file gốc nếu có
        original_content = ""
        if original_file:
            orig_path = REPORTS_DIR / original_file
            if orig_path.exists():
                # Đọc phần body content từ file gốc (không lấy wrapper HTML)
                orig_full = orig_path.read_text(encoding="utf-8")
                # Extract nội dung giữa <body> tags
                body_match = re.search(r'<body[^>]*>(.*?)</body>', orig_full, re.DOTALL)
                if body_match:
                    original_content = body_match.group(1)

        # Ghép: nội dung gốc + sections mới
        combined_html = original_content + "\n" + appended_html

        # Save với tên file mới (suffix a01, a02...)
        new_filename = make_append_filename(original_file) if original_file else None
        filename = save_report(subject, combined_html, filename_override=new_filename)

        job["status"] = "done"
        job["progress"] = 100
        job["message"] = "✅ Báo cáo bổ sung đã lưu!"
        job["filename"] = filename
        job["done_at"] = datetime.now().isoformat()

    except Exception as e:
        job["status"] = "error"
        job["message"] = f"❌ Lỗi: {str(e)}"
        job["error"] = str(e)
        import traceback; traceback.print_exc()
```

### 3. Cập nhật `save_report()` — thêm param `filename_override`

Tìm function `save_report(subject, html_content)`.
Thêm optional param:

```python
def save_report(subject: str, html_content: str, filename_override: str = None) -> str:
    if filename_override:
        filename = filename_override
    else:
        # logic tạo tên file hiện tại (giữ nguyên)
        timestamp = datetime.now().strftime("%d%m%Y-%H%M")
        safe = re.sub(r'[^\w\s-]', '', subject)[:40].strip()
        filename = f"{safe}-{timestamp}.html"
    
    # ... phần còn lại giữ nguyên
```

---

## Frontend changes

### 1. Sau khi submit append modal — poll giống generate

Tìm hàm `doAppend()` hoặc hàm submit trong modal-append.
Thay bằng:

```javascript
async function doAppend() {
  // Thu thập sections đã chọn (preset + custom) — giữ logic hiện tại
  const toGenerate = getSelectedAppendSections(); // hoặc logic hiện tại
  if (toGenerate.length === 0) { alert('Chọn ít nhất 1 section'); return; }

  const currentSubject = document.getElementById('rpt-title')?.textContent
    ?.replace('Phân Tích Thuế — ', '').trim() || '';

  // Lấy tên file gốc đang xem
  const originalFile = currentFile || '';

  const statusEl = document.getElementById('append-status');
  statusEl.textContent = '⏳ Đang gửi yêu cầu...';

  try {
    const resp = await fetch('/append-sections', {
      method: 'POST',
      headers: { Authorization: AUTH, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject: currentSubject,
        mode,
        sections: toGenerate,
        original_file: originalFile,
      }),
    });

    const { job_id } = await resp.json();

    // Đóng modal
    closeModal('modal-append');
    appendCustomSections = [];

    // Hiện toast thông báo đang chạy background
    showAppendToast(job_id, currentSubject);

    // Poll job — khi xong refresh danh sách reports + hiện toast done
    startAppendPolling(job_id, currentSubject);

  } catch(e) {
    statusEl.textContent = '❌ Lỗi: ' + e.message;
  }
}
```

### 2. Poll append job

```javascript
function startAppendPolling(job_id, subject) {
  // Lưu vào localStorage để resume nếu refresh
  const appendJobs = JSON.parse(localStorage.getItem('append_jobs') || '[]');
  appendJobs.push({ job_id, subject, started: Date.now() });
  localStorage.setItem('append_jobs', JSON.stringify(appendJobs));

  const timer = setInterval(async () => {
    try {
      const r = await fetch(`/job/${job_id}`, { headers: { Authorization: AUTH } });
      const job = await r.json();

      if (job.status === 'done') {
        clearInterval(timer);
        removeAppendJob(job_id);
        await loadReports(); // refresh list
        showAppendDoneToast(job.filename, subject);
      }
      if (job.status === 'error') {
        clearInterval(timer);
        removeAppendJob(job_id);
        alert('Lỗi bổ sung: ' + job.message);
      }
    } catch(e) {}
  }, 3000);
}

function removeAppendJob(job_id) {
  const jobs = JSON.parse(localStorage.getItem('append_jobs') || '[]');
  localStorage.setItem('append_jobs', JSON.stringify(jobs.filter(j => j.job_id !== job_id)));
}
```

### 3. Toast notifications

```javascript
function showAppendToast(job_id, subject) {
  showToast(`⏳ Đang bổ sung báo cáo "${subject}" trong background...`, 8000);
}

function showAppendDoneToast(filename, subject) {
  showToast(`✅ Bổ sung hoàn thành! <a href="#" onclick="openSavedReport('${filename}');return false"
    style="color:var(--brand);font-weight:600">Mở báo cáo →</a>`, 15000);
}

// Generic toast function (nếu chưa có, thêm vào):
function showToast(html, duration = 8000) {
  const toast = document.createElement('div');
  toast.style.cssText = `position:fixed;bottom:2rem;right:2rem;z-index:9999;
    background:#fff;border:1px solid #bbf7d0;border-radius:.75rem;
    padding:1rem 1.5rem;box-shadow:0 4px 20px rgba(0,0,0,.1);max-width:320px;font-size:.875rem`;
  toast.innerHTML = html;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}
```

### 4. Resume append jobs khi mở lại app
Trong `init()`, sau phần resume generate job hiện tại, thêm:

```javascript
// Resume append jobs
const appendJobs = JSON.parse(localStorage.getItem('append_jobs') || '[]');
for (const { job_id, subject } of appendJobs) {
  const r = await fetch(`/job/${job_id}`, { headers: { Authorization: AUTH } }).catch(() => null);
  if (!r?.ok) { removeAppendJob(job_id); continue; }
  const job = await r.json();
  if (job.status === 'done') {
    showAppendDoneToast(job.filename, subject);
    removeAppendJob(job_id);
    await loadReports();
  } else if (job.status === 'running' || job.status === 'pending') {
    startAppendPolling(job_id, subject);
  } else {
    removeAppendJob(job_id);
  }
}
```

---

## Không thay đổi
- Background generate job (`run_generate_job`) — giữ nguyên
- Tất cả endpoints khác
- Script trong `<head>` — giữ nguyên
- UI modal-append (chỉ thay hàm submit)

---

## Commit message
`feat: append-sections runs as background job, saves as new file with -a01/-a02 suffix`

## Sau khi xong
Xoá BRIEF-append-background.md rồi push.
