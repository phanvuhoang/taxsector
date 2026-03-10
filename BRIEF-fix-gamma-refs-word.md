# BRIEF: Fix Gamma + Duplicate refs + Word refs

## Fix 1: Gamma API — accept HTTP 201 as success

### Vấn đề
Gamma API trả HTTP 201 khi tạo thành công, nhưng code check `!= 200` → bị coi là lỗi → skip.

### Fix trong `create_gamma_slides()`:
Tìm đoạn:
```python
async with session.post(GAMMA_API_URL, json=payload, headers=headers) as resp:
    if resp.status != 200:
        text = await resp.text()
        raise Exception(f"Gamma API error {resp.status}: {text}")
```

Thay bằng:
```python
async with session.post(GAMMA_API_URL, json=payload, headers=headers) as resp:
    if resp.status not in (200, 201):
        text = await resp.text()
        raise Exception(f"Gamma API error {resp.status}: {text}")
```

---

## Fix 2: Bỏ refs_html khỏi file HTML — chỉ dùng sidebar buildSources()

### Lý do
Hiện có 2 chỗ hiển thị "Nguồn tham khảo":
1. `refs_html` append vào cuối file HTML (trong `<body>`) — tĩnh, không cập nhật khi append sections
2. `buildSources()` trong app sidebar — dynamic, restore từ citations, đúng hơn

→ Bỏ refs_html khỏi file HTML, giữ sidebar. Sidebar collapsible, không ảnh hưởng append flow.

### Fix trong backend — XOÁ cả 2 đoạn tạo refs_html:

**Chỗ 1** — stream endpoint, tìm và xoá:
```python
# XOÁ đoạn này hoàn toàn:
if unique_urls:
    refs_html = '<hr><h2>Nguồn tham khảo</h2><div style="margin-top:.75rem">'
    for i, url in enumerate(unique_urls[:50], 1):
        short = (url[:80] + '...') if len(url) > 80 else url
        refs_html += f'<div style="margin:.3rem 0;font-size:.875rem"><b>[{i}]</b> <a href="{url}" target="_blank" rel="noopener" style="color:#028a39">{short}</a></div>'
    refs_html += '</div>'
    full_html_with_refs = full_html + refs_html
else:
    full_html_with_refs = full_html

# THAY bằng:
full_html_with_refs = full_html
```

**Chỗ 2** — background job `run_generate_job()`, tìm và xoá:
```python
# XOÁ đoạn này hoàn toàn:
if unique_citations:
    refs_html = '<hr><h2>Nguồn tham khảo</h2><div style="margin-top:.75rem">'
    for i, url in enumerate(unique_citations[:50], 1):
        short = (url[:80] + '...') if len(url) > 80 else url
        refs_html += f'<div style="margin:.3rem 0;font-size:.875rem"><b>[{i}]</b> <a href="{url}" target="_blank" rel="noopener" style="color:#028a39">{short}</a></div>'
    refs_html += '</div>'
    full_html = full_html + refs_html

# Xoá hết — full_html dùng nguyên không append refs
```

---

## Fix 3: Word export — thêm Nguồn tham khảo vào cuối file .docx

### Vấn đề
`export_docx` chỉ parse HTML body, không có refs.

### Fix trong `/docx` endpoint:

Sau khi parse xong HTML (sau vòng loop `for el in soup...`), thêm refs section:

```python
        # ── Thêm Nguồn tham khảo vào cuối Word doc ────────────
        refs_raw = body.get("citations", [])  # frontend truyền lên
        if refs_raw:
            doc.add_heading(normalize_text("Nguồn tham khảo"), level=1)
            for i, url in enumerate(refs_raw[:50], 1):
                try:
                    p = doc.add_paragraph(style="List Number")
                    run = p.add_run(normalize_text(url))
                    run.font.color.rgb = RGBColor(0x02, 0x8A, 0x39)
                    run.font.size = Pt(9)
                except Exception:
                    doc.add_paragraph(normalize_text(f"[{i}] {url}"))
```

### Fix trong frontend — truyền citations khi export Word:

Tìm hàm export docx trong JS (có `btn-word` hoặc `/docx`):
```javascript
// Thêm citations vào body khi gọi /docx
body: JSON.stringify({
    html: reportHtml,
    subject: subject,
    citations: citations,   // THÊM DÒNG NÀY
}),
```

### Fix trong backend — đọc citations từ request:
```python
# Trong export_docx, thêm:
refs_raw = body.get("citations", [])
```

---

## Không thay đổi
- Background job flow — giữ nguyên
- `buildSources()` sidebar — giữ nguyên
- Script trong `<head>` — giữ nguyên
- Tất cả endpoints khác

## Commit message
`fix: Gamma 201 status + remove duplicate refs from HTML + add refs to Word export`

## Sau khi xong
Xoá BRIEF-fix-gamma-refs-word.md rồi push.
