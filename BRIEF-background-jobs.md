# BRIEF: Background Job Generation

## Tổng quan
Chuyển từ "stream trong browser" sang "background job trên server".
User click Tạo → nhận job_id → có thể đóng tab → báo cáo tự lưu khi xong.

---

## Architecture thay đổi

### Trước (hiện tại):
```
Browser → POST /generate (stream) → nhận HTML chunks → render DOM → save
```

### Sau (mới):
```
Browser → POST /generate → nhận {job_id} ngay lập tức
Server  → chạy background task: research + generate + save file
Browser → poll GET /job/{job_id} mỗi 3s → hiện progress
Xong    → file tự có trong /reports → hiện trong "Báo cáo đã lưu"
```

---

## Backend changes

### 1. Job storage (in-memory, đủ dùng)
Thêm vào đầu main.py sau các import:

```python
import asyncio, uuid
from datetime import datetime

# In-memory job store
jobs: dict[str, dict] = {}
# Format: {
#   "job_id": {
#     "status": "pending|running|done|error",
#     "progress": 0-100,
#     "message": "Đang research...",
#     "subject": "FPT",
#     "mode": "company",
#     "filename": None,  # set khi done
#     "error": None,
#     "created_at": "ISO string",
#     "done_at": None,
#   }
# }
```

### 2. Endpoint POST /generate — trả về job_id ngay

Tìm endpoint `/generate` hiện tại (StreamingResponse).
Thay TOÀN BỘ bằng:

```python
@app.post("/generate")
async def generate(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    subject  = body.get("subject", "").strip()
    mode     = body.get("mode", "sector")
    sections = body.get("sections", [])

    if not subject:
        raise HTTPException(400, "subject required")

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Đang khởi tạo...",
        "subject": subject,
        "mode": mode,
        "filename": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
        "done_at": None,
    }

    # Chạy background — không await
    asyncio.create_task(run_generate_job(job_id, subject, mode, sections))

    return {"job_id": job_id}
```

### 3. Hàm background `run_generate_job()`
Đây là hàm chính — chứa toàn bộ logic research + generate hiện tại,
nhưng thay vì yield chunks thì update jobs[job_id] và cuối cùng save file.

```python
async def run_generate_job(job_id: str, subject: str, mode: str, sections: list):
    job = jobs[job_id]
    total_sections = len([s for s in sections if s.get("enabled", True)])
    
    try:
        job["status"] = "running"
        
        # ── Phase 1: Perplexity Research ──────────────────────
        job["message"] = "🔍 Đang research với Perplexity..."
        job["progress"] = 5
        
        # Copy toàn bộ logic Perplexity research từ /generate cũ vào đây
        # (phần tạo sonar client, batch research, all_results dict)
        # ... [giữ nguyên logic, chỉ bỏ yield]
        
        # ── Phase 2: Generate từng section với Claude ─────────
        enabled = [s for s in sections if s.get("enabled", True)]
        all_html_parts = []
        
        for i, section in enumerate(enabled):
            pct = 10 + int((i / total_sections) * 80)
            job["progress"] = pct
            job["message"] = f"✍️ Đang viết phần {i+1}/{total_sections}: {section['title']}"
            
            context = build_context(section, all_results)
            section_html = ""
            
            # Collect full text từ Claude stream
            async for chunk in claude_stream_section(section, subject, context, mode, i+1):
                section_html += chunk
            
            all_html_parts.append(section_html)
        
        # ── Phase 3: Post-process & Save ──────────────────────
        job["progress"] = 92
        job["message"] = "🔎 Đang kiểm tra văn bản pháp luật..."
        
        full_html = "\n".join(all_html_parts)
        full_html = await verify_legal_refs(full_html)
        full_html = linkify_citations(full_html, citations)
        
        job["progress"] = 97
        job["message"] = "💾 Đang lưu báo cáo..."
        
        filename = save_report(subject, full_html)
        
        # Done!
        job["status"] = "done"
        job["progress"] = 100
        job["message"] = "✅ Hoàn thành!"
        job["filename"] = filename
        job["done_at"] = datetime.now().isoformat()
        
    except Exception as e:
        job["status"] = "error"
        job["message"] = f"❌ Lỗi: {str(e)}"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()
```

### 4. Endpoint GET /job/{job_id} — poll status

```python
@app.get("/job/{job_id}")
async def get_job(job_id: str, _user: str = Depends(auth)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
```

### 5. Cleanup jobs cũ (optional nhưng nên có)
Thêm background task cleanup mỗi giờ — xoá jobs > 24h:

```python
async def cleanup_old_jobs():
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now().timestamp() - 86400
        to_delete = [
            jid for jid, j in jobs.items()
            if datetime.fromisoformat(j["created_at"]).timestamp() < cutoff
        ]
        for jid in to_delete:
            del jobs[jid]

# Trong startup event hoặc lifespan:
@app.on_event("startup")
async def startup():
    asyncio.create_task(cleanup_old_jobs())
```

---

## Frontend changes

### 1. Sau khi click "Tạo báo cáo" — nhận job_id
Thay vì xử lý stream, nhận job_id rồi bắt đầu poll:

```javascript
async function startGenerate() {
  // ... validate input như cũ ...
  
  const resp = await fetch('/generate', {
    method: 'POST',
    headers: { Authorization: AUTH, 'Content-Type': 'application/json' },
    body: JSON.stringify({ subject, mode, sections: enabledSections }),
  });
  
  const { job_id } = await resp.json();
  currentJobId = job_id;
  
  // Chuyển sang phase "generating" — hiện progress UI
  phase = 'generating';
  render();
  
  // Bắt đầu poll
  startPolling(job_id);
}
```

### 2. Poll function

```javascript
let pollTimer = null;
let currentJobId = null;

function startPolling(job_id) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollJob(job_id), 3000);
}

async function pollJob(job_id) {
  try {
    const r = await fetch(`/job/${job_id}`, { headers: { Authorization: AUTH } });
    const job = await r.json();
    
    // Update progress bar
    document.getElementById('gen-progress-bar').style.width = job.progress + '%';
    document.getElementById('gen-status-msg').textContent = job.message;
    document.getElementById('gen-subject-label').textContent = job.subject;
    
    if (job.status === 'done') {
      clearInterval(pollTimer);
      pollTimer = null;
      
      // Refresh danh sách reports
      await loadReports();
      
      // Hiện thông báo thành công + link mở báo cáo
      showJobDone(job.filename, job.subject);
      phase = 'idle';
      render();
    }
    
    if (job.status === 'error') {
      clearInterval(pollTimer);
      pollTimer = null;
      showError(job.message);
      phase = 'idle';
      render();
    }
    
  } catch(e) {
    console.error('Poll error:', e);
  }
}
```

### 3. Phase "generating" UI
Khi phase = 'generating', thay vì hiện report frame, hiện:

```html
<!-- Progress screen -->
<div id="phase-generating">
  <div class="text-center py-12">
    <div class="text-5xl mb-4">⏳</div>
    <h2 class="text-xl font-bold mb-2">Đang tạo báo cáo</h2>
    <p id="gen-subject-label" class="text-lg mb-6" style="color:var(--brand)"></p>
    
    <!-- Progress bar -->
    <div class="w-full max-w-md mx-auto bg-gray-200 rounded-full h-3 mb-3">
      <div id="gen-progress-bar" 
           class="h-3 rounded-full transition-all duration-500"
           style="width:0%;background:var(--brand)"></div>
    </div>
    
    <p id="gen-status-msg" class="text-sm mb-8" style="color:var(--muted)">
      Đang khởi tạo...
    </p>
    
    <p class="text-sm" style="color:var(--muted)">
      💡 Bạn có thể đóng tab này. Báo cáo sẽ tự lưu khi xong.<br>
      Mở lại app → vào "Báo cáo đã lưu" để xem kết quả.
    </p>
    
    <button onclick="cancelJob()" 
      class="mt-6 text-sm px-4 py-2 rounded border"
      style="border-color:var(--border);color:var(--muted)">
      Huỷ
    </button>
  </div>
</div>
```

### 4. Khi mở lại app — resume polling nếu có job đang chạy
Khi init(), check localStorage xem có job đang pending không:

```javascript
async function init() {
  await loadSections();
  await loadReports();
  
  // Resume polling nếu có job chưa xong
  const savedJobId = localStorage.getItem('current_job_id');
  if (savedJobId) {
    const r = await fetch(`/job/${savedJobId}`, { headers: { Authorization: AUTH } });
    if (r.ok) {
      const job = await r.json();
      if (job.status === 'running' || job.status === 'pending') {
        currentJobId = savedJobId;
        phase = 'generating';
        render();
        startPolling(savedJobId);
      } else {
        localStorage.removeItem('current_job_id');
      }
    }
  }
}

// Lưu job_id khi bắt đầu generate
function startPolling(job_id) {
  localStorage.setItem('current_job_id', job_id);
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollJob(job_id), 3000);
}

// Xoá khi done/error
// Trong pollJob, sau khi done: localStorage.removeItem('current_job_id');
```

### 5. Thông báo khi xong

```javascript
function showJobDone(filename, subject) {
  localStorage.removeItem('current_job_id');
  
  // Hiện toast notification
  const toast = document.createElement('div');
  toast.innerHTML = `
    <div style="position:fixed;bottom:2rem;right:2rem;z-index:999;
                background:#fff;border:1px solid #bbf7d0;border-radius:.75rem;
                padding:1rem 1.5rem;box-shadow:0 4px 20px rgba(0,0,0,.1);
                max-width:320px">
      <p class="font-semibold text-sm mb-1">✅ Báo cáo đã hoàn thành!</p>
      <p class="text-sm mb-3" style="color:var(--muted)">${esc(subject)}</p>
      <button onclick="openSavedReport('${filename}')" 
        class="w-full text-sm py-2 rounded-lg text-white font-medium"
        style="background:var(--brand)">
        Mở báo cáo →
      </button>
    </div>
  `;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 15000);
}
```

---

## Không thay đổi
- Logic Perplexity research — copy nguyên vào `run_generate_job()`
- Logic Claude generation — dùng lại `claude_stream_section()` 
- `save_report()` — dùng nguyên
- `verify_legal_refs()` — dùng nguyên
- Tất cả endpoints khác (/reports, /report/{f}, /default-sections, v.v.)
- Script chính PHẢI trong `<head>` — giữ nguyên

---

## Lưu ý quan trọng cho Claude Code

1. `run_generate_job()` là async function — dùng `await` cho tất cả async calls
2. `asyncio.create_task()` cần được gọi trong async context (trong endpoint)
3. Jobs dict là in-memory — restart server = mất jobs đang chạy (acceptable)
4. Nếu `/generate` cũ có logic phức tạp (batching, retry) → giữ nguyên, chỉ wrap vào background task
5. Test: tạo báo cáo → đóng tab → mở lại → vào "Báo cáo đã lưu" → thấy báo cáo mới

---

## Commit message
`feat: background job generation — generate runs on server, browser can close tab`

## Sau khi xong
Xoá BRIEF-background-jobs.md rồi push.
