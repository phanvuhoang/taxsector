# BRIEF: Gamma API Integration — Auto-create slides after report generation

## Tổng quan
Sau khi báo cáo generate xong (HTML saved), tự động gọi Gamma API
để tạo slides trong background. Khi Gamma xong → inject link vào TOC
của báo cáo → THEN thông báo "Completed" cho user.

Flow mới:
```
run_generate_job() done
  → save HTML (như cũ)
  → gọi Gamma API → nhận generationId
  → poll Gamma mỗi 10s cho đến khi completed
  → nhận gammaUrl + pptxUrl
  → inject link "🎬 Xem Slides" vào TOC của file HTML
  → overwrite file HTML
  → job status = "done" + thông báo user
```

---

## Backend changes

### 1. Thêm env var
Đọc từ environment:
```python
GAMMA_API_KEY = os.getenv("GAMMA_API_KEY", "")
GAMMA_API_URL = "https://public-api.gamma.app/v1.0/generations"
```

### 2. Hàm gọi Gamma API

```python
async def create_gamma_slides(subject: str, html_content: str) -> dict:
    """
    Gọi Gamma API để tạo slides từ nội dung báo cáo.
    Trả về {"gammaUrl": "...", "pptxUrl": "..."} khi xong.
    Raise Exception nếu lỗi hoặc timeout.
    """
    import aiohttp, re

    if not GAMMA_API_KEY:
        raise Exception("GAMMA_API_KEY not configured")

    # Strip HTML tags để lấy plain text cho Gamma
    plain_text = re.sub(r'<[^>]+>', ' ', html_content)
    plain_text = re.sub(r'\s+', ' ', plain_text).strip()
    # Giới hạn ~80,000 chars để an toàn (token limit)
    plain_text = plain_text[:80000]

    payload = {
        "inputText": f"# {subject}\n\n{plain_text}",
        "textMode": "condense",
        "format": "presentation",
        "numCards": 60,
        "cardSplit": "auto",
        "additionalInstructions": (
            "Phân tích nội dung một cách chi tiết và mạch lạc. "
            "Vẽ các biểu đồ cần thiết. "
            "Sử dụng tối đa image phù hợp để minh hoạ nội dung một cách phù hợp nhất. "
            "Trình bày rõ ràng, minh họa tối đa bằng các sơ đồ, "
            "sao cho thật dễ hiểu với các chuyên gia tư vấn Thuế, "
            "kể cả những người mới đi làm hay đã đi làm lâu năm."
        ),
        "folderIds": ["m1b4lf5j12yd7ck"],
        "exportAs": "pptx",
        "textOptions": {
            "amount": "extensive",
            "tone": "professional, analytical",
            "audience": "tax professionals, business executives",
            "language": "vi",
        },
        "imageOptions": {
            "source": "aiGenerated",
            "model": "imagen-4-pro",
            "style": "photorealistic, professional, corporate",
        },
        "cardOptions": {
            "dimensions": "16x9",
            "headerFooter": {
                "bottomRight": {
                    "type": "cardNumber"
                },
                "hideFromFirstCard": True,
            }
        },
        "sharingOptions": {
            "externalAccess": "view",
        },
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": GAMMA_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        # Step 1: Submit generation
        async with session.post(GAMMA_API_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Gamma API error {resp.status}: {text}")
            data = await resp.json()
            generation_id = data.get("generationId")
            if not generation_id:
                raise Exception(f"No generationId in response: {data}")

        # Step 2: Poll until completed (max 10 minutes)
        poll_url = f"{GAMMA_API_URL}/{generation_id}"
        for attempt in range(60):  # 60 x 10s = 10 phút
            await asyncio.sleep(10)
            async with session.get(poll_url, headers=headers) as resp:
                if resp.status != 200:
                    continue
                result = await resp.json()
                status = result.get("status")
                if status == "completed":
                    return {
                        "gammaUrl": result.get("gammaUrl", ""),
                        "pptxUrl": result.get("pptxUrl", ""),
                        "generationId": generation_id,
                    }
                elif status == "failed":
                    raise Exception(f"Gamma generation failed: {result}")
                # pending/processing → tiếp tục poll

        raise Exception("Gamma generation timeout after 10 minutes")
```

### 3. Hàm inject Gamma link vào HTML file

```python
def inject_gamma_link(filename: str, gamma_url: str, pptx_url: str = None):
    """
    Inject link Gamma slides vào phần TOC của file HTML đã lưu.
    Tìm <div id="toc"> hoặc đầu file, thêm link "🎬 Xem Slides".
    """
    path = REPORTS_DIR / filename
    if not path.exists():
        return

    content = path.read_text(encoding="utf-8")

    # Tạo link HTML
    links_html = f'''
<div id="gamma-links" style="margin:1rem 0;padding:0.75rem 1rem;
     background:#f0fdf4;border-radius:0.5rem;border:1px solid #bbf7d0">
  <a href="{gamma_url}" target="_blank" rel="noopener"
     style="color:#028a39;font-weight:600;text-decoration:none;font-size:0.95rem">
    🎬 Xem Slides (Gamma)
  </a>'''

    if pptx_url:
        links_html += f'''
  &nbsp;|&nbsp;
  <a href="{pptx_url}" target="_blank" rel="noopener"
     style="color:#028a39;font-weight:600;text-decoration:none;font-size:0.95rem">
    ⬇️ Tải PPTX
  </a>'''

    links_html += '\n</div>'

    # Inject sau thẻ <body> hoặc trước nội dung đầu tiên
    if '<body>' in content:
        content = content.replace('<body>', '<body>\n' + links_html, 1)
    else:
        # Fallback: thêm vào đầu content
        content = links_html + content

    path.write_text(content, encoding="utf-8")
```

### 4. Cập nhật `run_generate_job()` — thêm Gamma step

Tìm phần cuối `run_generate_job()` sau khi `save_report()` thành công.
Thay đoạn set `job["status"] = "done"` bằng:

```python
        # ── Phase 4: Gamma Slides (nếu API key đã config) ─────
        if GAMMA_API_KEY:
            job["progress"] = 97
            job["message"] = "🎬 Đang tạo slides với Gamma (có thể mất 2-5 phút)..."

            try:
                gamma_result = await create_gamma_slides(subject, full_html)
                gamma_url  = gamma_result.get("gammaUrl", "")
                pptx_url   = gamma_result.get("pptxUrl", "")

                if gamma_url:
                    inject_gamma_link(filename, gamma_url, pptx_url)
                    job["gammaUrl"] = gamma_url
                    job["pptxUrl"]  = pptx_url

            except Exception as e:
                # Gamma lỗi → không fail cả job, chỉ log
                print(f"[WARN] Gamma API failed: {e}")
                job["gammaUrl"] = None

        # Done!
        job["status"]   = "done"
        job["progress"] = 100
        job["message"]  = "✅ Hoàn thành!" + (
            " Slides đã sẵn sàng trên Gamma." if job.get("gammaUrl") else ""
        )
        job["filename"] = filename
        job["done_at"]  = datetime.now().isoformat()
```

### 5. Cập nhật `run_append_job()` — tương tự

Sau khi save append file xong, thêm Gamma step giống hệt trên
(copy nguyên đoạn Phase 4, dùng `combined_html` thay `full_html`).

### 6. Thêm `aiohttp` vào requirements.txt
```
aiohttp>=3.9.0
```
(Nếu đã có trong requirements.txt thì bỏ qua.)

---

## Frontend changes

### 1. Poll job — hiển thị Gamma progress

Trong `pollJob()`, update message khi job đang ở Gamma phase:

```javascript
// Gamma đang chạy — message sẽ chứa "Gamma"
if (job.message && job.message.includes('Gamma')) {
  document.getElementById('gen-status-msg').textContent = job.message;
  // Đổi icon progress bar thành màu tím Gamma
  document.getElementById('gen-progress-bar').style.background = '#6366f1';
} else {
  document.getElementById('gen-progress-bar').style.background = 'var(--brand)';
}
```

### 2. Toast khi done — thêm link Gamma nếu có

Trong `showJobDone()` (hoặc hàm hiển thị toast khi job completed):

```javascript
function showJobDone(job) {
  localStorage.removeItem('current_job_id');
  await loadReports();

  let toastHtml = `
    <div style="position:fixed;bottom:2rem;right:2rem;z-index:9999;
                background:#fff;border:1px solid #bbf7d0;border-radius:.75rem;
                padding:1rem 1.5rem;box-shadow:0 4px 20px rgba(0,0,0,.1);max-width:340px">
      <p style="font-weight:600;font-size:.9rem;margin-bottom:.5rem">
        ✅ Báo cáo hoàn thành!
      </p>
      <p style="font-size:.8rem;color:var(--muted);margin-bottom:.75rem">
        ${esc(job.subject)}
      </p>
      <div style="display:flex;gap:.5rem;flex-wrap:wrap">
        <button onclick="openSavedReport('${job.filename}')"
          style="flex:1;font-size:.8rem;padding:.4rem .75rem;border-radius:.5rem;
                 background:var(--brand);color:#fff;border:none;cursor:pointer;font-weight:600">
          📄 Mở báo cáo
        </button>`;

  if (job.gammaUrl) {
    toastHtml += `
        <a href="${esc(job.gammaUrl)}" target="_blank"
          style="flex:1;font-size:.8rem;padding:.4rem .75rem;border-radius:.5rem;
                 background:#6366f1;color:#fff;text-decoration:none;
                 text-align:center;font-weight:600">
          🎬 Xem Slides
        </a>`;
  }

  toastHtml += `
      </div>
    </div>`;

  const toast = document.createElement('div');
  toast.innerHTML = toastHtml;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 20000);
}
```

Cập nhật chỗ gọi `showJobDone()` — truyền toàn bộ `job` object thay vì chỉ `filename, subject`.

### 3. Khi mở saved report — hiển thị Gamma link nếu có trong HTML

Trong `openSavedReport()`, sau khi render HTML vào DOM:

```javascript
// Kiểm tra xem report có Gamma link không
const gammaDiv = document.getElementById('gamma-links');
if (gammaDiv) {
  // Link đã được inject vào HTML, hiện sẵn rồi — không cần làm gì thêm
  gammaDiv.style.display = 'block';
}
```

### 4. Bỏ nút "Slides" (python-pptx) cũ
Xoá element `btn-slides` và hàm `exportSlides()` — không cần nữa vì Gamma export PPTX rồi.

---

## Không thay đổi
- Background job flow — giữ nguyên
- `save_report()` — giữ nguyên
- Script trong `<head>` — giữ nguyên
- Tất cả endpoints khác

## Dependency cần thêm
Thêm vào `requirements.txt`:
```
aiohttp>=3.9.0
```

## Env var cần set trong Coolify
```
GAMMA_API_KEY=<anh insert vào Coolify env var>
```
App đọc từ env, không hardcode trong code.

## Test sau khi deploy
1. Set `GAMMA_API_KEY` trong Coolify env vars → save → redeploy
2. Tạo báo cáo mới
3. Progress bar chuyển sang tím khi đến Gamma phase (~97%)
4. Chờ ~3-5 phút → toast hiện "✅ Hoàn thành! Slides đã sẵn sàng"
5. Toast có 2 nút: "📄 Mở báo cáo" + "🎬 Xem Slides"
6. Mở báo cáo → TOC đầu trang có link "🎬 Xem Slides (Gamma)" + "⬇️ Tải PPTX"

## Commit message
`feat: Gamma API integration — auto-create slides after report generation`

## Sau khi xong
Xoá BRIEF-gamma-integration.md rồi push.
