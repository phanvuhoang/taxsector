# BRIEF: Fix PPTX export + Reference numbering

## Fix 1: PPTX export lỗi do subject undefined

### Vấn đề
Khi xem saved report, biến `subject` lấy từ `rpt-title` element
có thể trả về empty string → `/slides` endpoint nhận subject rỗng → lỗi.

### Fix trong JS — hàm export slides (tìm đoạn có `btn-slides`):

```javascript
async function exportSlides() {
  const btn = document.getElementById('btn-slides');

  // Fallback chain lấy subject
  const subject =
    document.getElementById('rpt-title')?.textContent
      ?.replace('Phân Tích Thuế —', '').trim() ||
    (currentFile || '').replace('.html', '')
      .replace(/-a\d+$/, '')
      .replace(/-\d{8}-?\d{0,4}$/, '')
      .trim() ||
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
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } else {
      const errText = await r.text().catch(() => 'Lỗi không xác định');
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

## Fix 2: Reference list không hiển thị khi mở saved report

### Vấn đề
`citations` array chỉ tồn tại trong memory khi generate.
Khi mở saved report, `citations = []` → `buildSources()` không render gì.

### Fix A: Embed citations vào file HTML khi save (backend)

Trong `save_report()`, thêm param `citations` và inject JSON vào file:

```python
def save_report(subject: str, html_content: str,
                citations: list = None,
                filename_override: str = None) -> str:
    # ... tên file như cũ ...

    citations_tag = ""
    if citations:
        import json as _json
        citations_tag = (
            f'<script id="report-citations" type="application/json">'
            f'{_json.dumps(citations)}'
            f'</script>\n'
        )

    full_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>{subject}</title>
{citations_tag}</head>
<body>
{html_content}
</body>
</html>"""

    path = REPORTS_DIR / filename
    path.write_text(full_html, encoding="utf-8")
    return filename
```

Cập nhật tất cả chỗ gọi `save_report()`:
- `run_generate_job()`: truyền `citations=unique_urls` (list URLs đã collect)
- `run_append_job()`: truyền `citations=new_citations`

### Fix B: Restore citations khi mở saved report (frontend)

Thêm function `restoreCitations()`:

```javascript
function restoreCitations(html) {
  const match = html.match(
    /<script id="report-citations" type="application\/json">([\s\S]*?)<\/script>/
  );
  if (match) {
    try { citations = JSON.parse(match[1]); return; } catch(e) {}
  }
  // Fallback: extract URLs từ href trong HTML
  citations = [];
  const seen = new Set();
  for (const m of html.matchAll(/href="(https?:\/\/[^"#][^"]*?)"/g)) {
    if (!seen.has(m[1])) { seen.add(m[1]); citations.push(m[1]); }
  }
}
```

Gọi `restoreCitations(html)` ngay trước `buildSources()` ở mọi chỗ
load/render report HTML (khi mở saved report, khi generate xong, khi append xong).

### Fix C: buildSources() — đảm bảo render đúng thứ tự số

Kiểm tra lại `buildSources()` — đảm bảo dùng `[i+1]` để đánh số:

```javascript
function buildSources() {
  const unique = [...new Set(citations.filter(u => u && u.startsWith('http')))];
  if (!unique.length) {
    document.getElementById('src-wrap')?.classList.add('hidden');
    return;
  }
  const list = document.getElementById('src-list');
  list.innerHTML = '';
  unique.forEach((url, i) => {
    const d = document.createElement('div');
    d.className = 'text-xs mb-1';
    d.style.color = 'var(--muted)';
    // Hiện tên domain thay vì full URL cho gọn
    let displayUrl = url;
    try { displayUrl = new URL(url).hostname + new URL(url).pathname.slice(0, 40); } catch(e) {}
    d.innerHTML = `<span style="color:var(--text);font-weight:600">[${i + 1}]</span> `
      + `<a href="${esc(url)}" target="_blank" rel="noopener"
            class="hover:underline" style="color:var(--brand)">${esc(displayUrl)}</a>`;
    list.appendChild(d);
  });
  document.getElementById('src-count').textContent = unique.length;
  document.getElementById('src-wrap')?.classList.remove('hidden');
}
```

---

## Không thay đổi gì khác
- Background job logic — giữ nguyên
- Script trong `<head>` — giữ nguyên
- Tất cả endpoints khác

## Commit message
`fix: PPTX export subject fallback + embed citations in saved report HTML`

## Sau khi xong
Xoá BRIEF-fix-pptx-citations.md rồi push.
