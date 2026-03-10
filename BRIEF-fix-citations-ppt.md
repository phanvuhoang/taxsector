# BRIEF: Fix citations numbering + PPT export

## Fix 1: Reference list không hiển thị khi mở báo cáo đã lưu

### Vấn đề
`buildSources()` dùng array `citations` (in-memory).
Khi mở báo cáo đã lưu, `citations = []` → không render references.

### Fix: Embed citations URLs vào file HTML khi save

Trong `save_report()`, trước khi wrap HTML, inject citations dưới dạng
JSON script tag để restore khi mở lại:

```python
def save_report(subject: str, html_content: str, citations: list = None, filename_override: str = None) -> str:
    # ... tên file như cũ ...
    
    # Inject citations data vào HTML
    citations_script = ""
    if citations:
        import json
        citations_json = json.dumps(citations)
        citations_script = f'<script id="report-citations" type="application/json">{citations_json}</script>\n'
    
    full_html = f"""<!DOCTYPE html>
<html>...
{citations_script}
{html_content}
...</html>"""
```

Cập nhật tất cả chỗ gọi `save_report()` để truyền `citations` list:
- Trong `run_generate_job()`: truyền `all_citations`
- Trong `run_append_job()`: truyền citations từ research mới

### Fix frontend: restore citations khi mở saved report

Trong hàm `openSavedReport()` hoặc chỗ load saved report HTML,
sau khi set `reportHtml`, thêm:

```javascript
// Restore citations từ embedded JSON
function restoreCitations(html) {
  const match = html.match(/<script id="report-citations" type="application\/json">([\s\S]*?)<\/script>/);
  if (match) {
    try {
      citations = JSON.parse(match[1]);
    } catch(e) { citations = []; }
  } else {
    // Fallback: extract URLs từ <a href> trong report
    citations = [];
    const urlMatches = html.matchAll(/href="(https?:\/\/[^"]+)"/g);
    const seen = new Set();
    for (const m of urlMatches) {
      if (!seen.has(m[1])) { seen.add(m[1]); citations.push(m[1]); }
    }
  }
}
```

Gọi `restoreCitations(html)` ngay trước `buildSources()` khi load saved report.

---

## Fix 2: PPT export lỗi khi xem saved report

### Vấn đề
Khi xem saved report, biến `subject` có thể là empty string hoặc
lấy từ `rpt-title` element không tồn tại → `/slides` nhận subject rỗng → lỗi.

### Fix trong JS — hàm export slides:

Tìm đoạn code gọi `/slides` (có `btn-slides`).
Sửa lại cách lấy subject:

```javascript
async function exportSlides() {
  const btn = document.getElementById('btn-slides');
  
  // Lấy subject từ nhiều nguồn (fallback chain)
  const subject = 
    document.getElementById('rpt-title')?.textContent?.replace('Phân Tích Thuế — ', '').trim() ||
    currentFile?.replace('.html', '').replace(/-\d{8}-\d{4}(-a\d+)?$/, '').trim() ||
    'BaoCao';
  
  if (!reportHtml) { alert('Chưa có báo cáo để xuất'); return; }
  
  btn.textContent = '⏳ Đang tạo PPTX...';
  btn.disabled = true;
  
  try {
    const r = await fetch('/slides', {
      method: 'POST',
      headers: { Authorization: AUTH, 'Content-Type': 'application/json' },
      body: JSON.stringify({ html: reportHtml, subject }),
    });
    
    if (r.ok) {
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = (currentFile || subject).replace('.html', '') + '.pptx';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      const errText = await r.text().catch(() => 'Unknown error');
      alert('Không xuất được PPTX: ' + errText);
    }
  } catch(e) {
    alert('Lỗi kết nối: ' + e.message);
  } finally {
    btn.textContent = '📊 Slides';
    btn.disabled = false;
  }
}
```

---

## Không thay đổi gì khác
- Script trong `<head>` — giữ nguyên
- Background job logic — giữ nguyên
- Tất cả endpoints khác

## Commit message
`fix: restore citations when opening saved report + fix PPT export subject`

## Sau khi xong
Xoá BRIEF-fix-citations-ppt.md rồi push.
