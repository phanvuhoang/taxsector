# CLAUDE_v2.md — Bug fixes & improvements for taxsector

Read this file and apply ALL changes below to `main.py` and `requirements.txt`.
Do NOT skip any item. After all changes, run `python3 -m py_compile main.py && echo OK`.

---

## Fix 1: Citation numbers & inline links in report

**Problem:** Citations/sources appear in the sources section but are NOT numbered inline in the report text. Claude sometimes writes `[1]`, `[2]` etc. but without actual `<a>` tags.

**Fix:** Update `build_section_prompt()` — reinforce the citation instruction and add a post-processing step to linkify `[N]` patterns.

### A) In `build_section_prompt()`, replace the citations instruction line:
Find:
```python
5. Trích dẫn nguồn inline: <a href="URL" target="_blank">[N]</a>
```
Replace with:
```python
5. QUAN TRỌNG — Trích dẫn nguồn inline bắt buộc: Sau mỗi câu hoặc đoạn có dữ liệu/số liệu/tên văn bản, chèn ngay link nguồn dạng: <a href="URL_NGUON" target="_blank">[N]</a> — thay URL_NGUON bằng URL thực tế từ dữ liệu nghiên cứu. Số [N] tăng dần từ [1]. KHÔNG để [N] không có thẻ <a>.
```

### B) Add a post-processing function after `save_report()`:
```python
def linkify_citations(html: str, citations: list[str]) -> str:
    """Replace bare [N] with <a href=...>[N]</a> using citation URLs."""
    import re
    def replacer(m):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(citations) and citations[idx]:
            url = citations[idx]
            return f'<a href="{url}" target="_blank">[{idx+1}]</a>'
        return m.group(0)
    return re.sub(r'\[(\d+)\](?!</a>)(?![^<]*</a>)', replacer, html)
```

### C) In the `generate()` function, after collecting all `sec_html`, apply linkify before saving:
Find the block:
```python
        # Save
        try:
            filename = save_report(subject, full_html)
```
Replace with:
```python
        # Linkify any bare [N] citations
        unique_citations = list(dict.fromkeys(all_citations))
        full_html = linkify_citations(full_html, unique_citations)

        # Save
        try:
            filename = save_report(subject, full_html)
```

---

## Fix 2: Force latest in-effect legal documents via thuvienphapluat.vn

**Problem:** Perplexity sometimes references outdated/superseded regulations. The TVPL scraper exists but may not be enforced strongly enough.

**Fix A — Strengthen `tvpl_search()` sort/filter params:**

Find in `tvpl_search()`:
```python
    params = {
        "q": query,
        "sbt": "0",   # sort by relevance
        "efts": "1",  # còn hiệu lực only
    }
```
Replace with:
```python
    params = {
        "q": query,
        "sbt": "1",   # sort by date descending (newest first)
        "efts": "1",  # còn hiệu lực only — filters out superseded docs
        "page": "1",
    }
```

**Fix B — Strengthen the system prompt in `build_section_prompt()` for legal/tax sections:**

Find the `table_block` text (inside the `if is_legal or is_tax:` block) and update the instruction:
```python
    table_block = ""
    if is_legal or is_tax:
        table_block = """
QUAN TRỌNG — VĂN BẢN PHÁP LUẬT:
1. CHỈ sử dụng văn bản đang CÒN HIỆU LỰC tại thời điểm hiện tại (2025-2026).
2. Nếu có văn bản mới thay thế/sửa đổi văn bản cũ → chỉ trích dẫn văn bản MỚI NHẤT.
3. KHÔNG trích dẫn văn bản đã bị bãi bỏ, thay thế hoặc hết hiệu lực.
4. Ưu tiên văn bản từ phần "VĂN BẢN PHÁP LUẬT HIỆN HÀNH" trong dữ liệu nghiên cứu.
5. Bắt đầu section bằng bảng tổng hợp văn bản (ít nhất 6-8 văn bản còn hiệu lực):
<table>
  <thead><tr>
    <th>Số hiệu</th><th>Tên văn bản</th><th>Loại</th>
    <th>Ngày ban hành</th><th>Hiệu lực</th><th>Ghi chú sửa đổi</th>
  </tr></thead>
  <tbody>... điền thực tế, ghi rõ nếu văn bản này thay thế văn bản nào ...</tbody>
</table>
"""
```

**Fix C — Add date context to Perplexity queries** in `build_query()`:

Find:
```python
def build_query(section: dict, subject: str, mode: str) -> str:
    mode_ctx = "ngành" if mode == "sector" else "công ty"
    subs = ", ".join(section.get("sub", []))
    return (
        f"Nghiên cứu chuyên sâu về: {section['title']} — {mode_ctx} {subject} tại Việt Nam năm 2024-2025\n"
        f"Chi tiết cần tìm: {subs}\n"
        f"Bao gồm: số hiệu văn bản pháp luật cụ thể, số liệu thị trường, "
        f"tên doanh nghiệp, ví dụ thực tế, nguồn đáng tin cậy"
    )
```
Replace with:
```python
def build_query(section: dict, subject: str, mode: str) -> str:
    from datetime import datetime
    current_year = datetime.now().year
    mode_ctx = "ngành" if mode == "sector" else "công ty"
    subs = ", ".join(section.get("sub", []))
    is_legal = any(k in section.get("title","").lower() for k in ["pháp lý","luật","quy định","thuế","thue"])
    legal_note = (
        f"\nLƯU Ý QUAN TRỌNG: Chỉ trích dẫn văn bản pháp luật CÒN HIỆU LỰC tính đến {current_year}. "
        f"Nếu có Luật/Nghị định/Thông tư mới thay thế → bắt buộc dùng văn bản MỚI NHẤT. "
        f"Ghi rõ văn bản nào thay thế văn bản nào."
    ) if is_legal else ""
    return (
        f"Nghiên cứu chuyên sâu về: {section['title']} — {mode_ctx} {subject} tại Việt Nam năm {current_year}\n"
        f"Chi tiết cần tìm: {subs}\n"
        f"Bao gồm: số hiệu văn bản pháp luật cụ thể, số liệu thị trường, "
        f"tên doanh nghiệp, ví dụ thực tế, nguồn đáng tin cậy"
        f"{legal_note}"
    )
```

---

## Fix 3: Add missing sub-items — tax disputes & sector-specific rulings

**Problem:** Default sections are missing "Tranh chấp thuế" and "Công văn đặc thù" sub-items.

**Fix:** Update `SECTOR_SECTIONS_VI` and `COMPANY_SECTIONS_VI` default sections.

In `SECTOR_SECTIONS_VI`, find section `s6` and update its `sub` list:
```python
    {"id": "s6", "title": "Các vấn đề thuế đặc thù của ngành",
     "sub": [
         "Rủi ro doanh thu/chi phí",
         "Chuyển giá",
         "Ưu đãi thuế",
         "Hóa đơn đặc thù",
         "Khấu trừ thuế",
         "Tranh chấp thuế & án lệ",
         "Công văn/hướng dẫn đặc thù của Tổng cục Thuế cho ngành",
     ], "enabled": True},
```

In `COMPANY_SECTIONS_VI`, find section `c4` and update:
```python
    {"id": "c4", "title": "Rủi ro thuế đặc thù",
     "sub": [
         "Rủi ro thanh tra",
         "Chuyển giá",
         "Cấu trúc pháp lý",
         "Giao dịch liên kết",
         "Tranh chấp thuế & lịch sử thanh/kiểm tra",
         "Công văn/ruling đặc thù áp dụng cho công ty/ngành",
     ], "enabled": True},
```

Also update `SECTOR_SECTIONS` (ASCII version, same ids) to match. Find `s6` in `SECTOR_SECTIONS`:
```python
    {"id": "s6", "title": "Cac van de thue dac thu cua nganh",
     "sub": ["Rui ro doanh thu/chi phi", "Chuyen gia", "Uu dai thue",
             "Hoa don dac thu", "Khau tru thue",
             "Tranh chap thue & an le",
             "Cong van/huong dan dac thu Tong cuc Thue cho nganh"], "enabled": True},
```

---

## Fix 4: Replace HTML slides with PPTX export (python-pptx, 16:9)

**Problem:** HTML slides are broken (only cover shows). Replace with proper PPTX file download.

### A) Add to `requirements.txt`:
```
python-pptx==1.0.2
```

### B) Replace the entire `/slides` endpoint with a PPTX generator:

Remove the old `/slides` endpoint and replace with:

```python
# ── PPTX export ───────────────────────────────────────────────────────────────
@app.post("/slides")
async def export_pptx(request: Request, _user: str = Depends(auth)):
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor as PptxRGB
    from pptx.enum.text import PP_ALIGN

    body    = await request.json()
    html    = body.get("html", "")
    subject = body.get("subject", "Báo cáo")

    BRAND   = PptxRGB(0x02, 0x8A, 0x39)
    WHITE   = PptxRGB(0xFF, 0xFF, 0xFF)
    DARK    = PptxRGB(0x1E, 0x29, 0x3B)
    LIGHT   = PptxRGB(0xF8, 0xFA, 0xFC)

    prs = Presentation()
    prs.slide_width  = Inches(13.333)   # 16:9
    prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]  # completely blank

    def add_rect(slide, l, t, w, h, fill_color=None, line_color=None):
        shape = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
        shape.line.fill.background()
        if fill_color:
            shape.fill.solid()
            shape.fill.fore_color.rgb = fill_color
        else:
            shape.fill.background()
        if line_color:
            shape.line.color.rgb = line_color
        else:
            shape.line.fill.background()
        return shape

    def add_text_box(slide, text, l, t, w, h, font_size=18, bold=False,
                     color=None, align=PP_ALIGN.LEFT, wrap=True):
        txBox = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
        txBox.word_wrap = wrap
        tf = txBox.text_frame
        tf.word_wrap = wrap
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(font_size)
        run.font.bold = bold
        if color:
            run.font.color.rgb = color
        return txBox

    # Parse sections from HTML
    soup = BeautifulSoup(html, "html.parser")

    # --- Slide 1: Cover ---
    slide = prs.slides.add_slide(blank_layout)
    add_rect(slide, 0, 0, 13.333, 7.5, fill_color=BRAND)
    add_text_box(slide, "PHÂN TÍCH THUẾ",
                 0.8, 1.5, 11.5, 1.0,
                 font_size=20, bold=False, color=PptxRGB(0xBB, 0xF7, 0xD0),
                 align=PP_ALIGN.CENTER)
    add_text_box(slide, subject,
                 0.8, 2.5, 11.5, 2.0,
                 font_size=36, bold=True, color=WHITE,
                 align=PP_ALIGN.CENTER)
    from datetime import datetime
    add_text_box(slide, datetime.now().strftime("%d/%m/%Y"),
                 0.8, 5.5, 11.5, 0.8,
                 font_size=16, color=PptxRGB(0xBB, 0xF7, 0xD0),
                 align=PP_ALIGN.CENTER)

    # --- Content slides: one per h2 section ---
    h2_sections = soup.find_all("h2")

    for h2 in h2_sections:
        title_text = h2.get_text(strip=True)

        # Collect bullet points from siblings until next h2
        bullets = []
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            if sib.name in ("p", "li"):
                t = sib.get_text(strip=True)
                if t and len(t) > 10:
                    bullets.append(t[:200])
            elif sib.name in ("ul", "ol"):
                for li in sib.find_all("li"):
                    t = li.get_text(strip=True)
                    if t:
                        bullets.append(t[:200])
            if len(bullets) >= 7:
                break

        slide = prs.slides.add_slide(blank_layout)

        # Header bar
        add_rect(slide, 0, 0, 13.333, 1.4, fill_color=BRAND)
        add_text_box(slide, title_text,
                     0.4, 0.1, 12.5, 1.2,
                     font_size=22, bold=True, color=WHITE,
                     align=PP_ALIGN.LEFT)

        # Content area background
        add_rect(slide, 0, 1.4, 13.333, 6.1, fill_color=LIGHT)

        # Bullet points
        if bullets:
            txBox = slide.shapes.add_textbox(
                Inches(0.5), Inches(1.7), Inches(12.3), Inches(5.5)
            )
            txBox.word_wrap = True
            tf = txBox.text_frame
            tf.word_wrap = True

            for i, bullet in enumerate(bullets[:7]):
                if i == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.space_before = Pt(6)
                run = p.add_run()
                run.text = f"▪  {bullet}"
                run.font.size = Pt(16)
                run.font.color.rgb = DARK
        else:
            add_text_box(slide, "(Xem báo cáo đầy đủ để biết chi tiết)",
                         0.5, 2.5, 12.3, 1.0,
                         font_size=16, color=PptxRGB(0x94, 0xA3, 0xB8))

    # --- Last slide: Thank you ---
    slide = prs.slides.add_slide(blank_layout)
    add_rect(slide, 0, 0, 13.333, 7.5, fill_color=BRAND)
    add_text_box(slide, "Cảm ơn",
                 0.8, 2.5, 11.5, 1.5,
                 font_size=40, bold=True, color=WHITE,
                 align=PP_ALIGN.CENTER)
    add_text_box(slide, "Báo cáo được tạo bởi Tax Sector Research AI",
                 0.8, 4.2, 11.5, 1.0,
                 font_size=16, color=PptxRGB(0xBB, 0xF7, 0xD0),
                 align=PP_ALIGN.CENTER)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)

    safe = re.sub(r'[^\w\s-]', '', subject)[:50].strip().replace(' ', '_')
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="TaxSlides_{safe}.pptx"'},
    )
```

### C) Update the frontend button — change label & download behavior:

In the HTML_PAGE JavaScript, find the `doSlides()` function and replace entirely:
```javascript
async function doSlides() {
  if (!reportHtml) return;
  const subject = document.getElementById('rpt-title').textContent.replace('Phân Tích Thuế — ', '');
  const btn = document.getElementById('btn-slides');
  btn.textContent = '⏳ Đang tạo PPTX...';
  btn.disabled = true;
  try {
    const r = await fetch('/slides', {
      method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({html: reportHtml, subject}),
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
      alert('Không thể tạo PPTX');
    }
  } catch(e) { alert('Lỗi: ' + e.message); }
  finally { btn.textContent = '📑 Slides PPTX'; btn.disabled = false; }
}
```

Also update the button label in HTML from `📑 Slides` to `📑 Slides PPTX`:
```html
<button id="btn-slides" onclick="doSlides()" class="btn btn-gray">📑 Slides PPTX</button>
```

Also remove the `modal-slides` div and the `openModal('modal-slides')` call since we no longer show slides inline.

---

## Fix 5: Fix word-spacing in DOCX export

**Problem:** Words run together in exported Word file (e.g. "khảnăngtự tạo").

**Fix:** In the `export_docx()` endpoint, improve the BeautifulSoup text extraction to preserve spacing.

Find in `export_docx()`:
```python
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["h2", "h3", "p", "li", "table"]):
        text = el.get_text(strip=True)
```
Replace with:
```python
    soup = BeautifulSoup(html, "html.parser")
    # Insert spaces around inline tags to prevent word merging
    for tag in soup.find_all(["a", "strong", "em", "span", "b", "i"]):
        tag.insert_before(" ")
        tag.insert_after(" ")
    for el in soup.find_all(["h2", "h3", "p", "li", "table"]):
        text = " ".join(el.get_text(" ", strip=False).split())  # normalize whitespace
```

---

## Fix 6: Rename saved report files to use datetime format

**Problem:** Files saved as `20250306 - Subject - 1.html`, `- 2.html` etc. instead of datetime.

**Fix:** Replace `save_report()` function:

```python
def save_report(subject: str, html_content: str) -> str:
    now = datetime.now()
    date_str = now.strftime("%d%m%Y")
    time_str = now.strftime("%H%M")
    base = safe_filename(subject)
    name = f"{date_str} - {base} - {time_str}.html"

    # Handle rare collision (same subject, same minute)
    if (REPORTS_DIR / name).exists():
        name = f"{date_str} - {base} - {now.strftime('%H%M%S')}.html"

    full_html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Phan Tich Thue — {subject}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1.5rem;line-height:1.75;color:#1e293b}}
h1{{color:#028a39;border-bottom:3px solid #028a39;padding-bottom:.5rem}}
h2{{color:#028a39;border-bottom:2px solid #028a39;padding-bottom:4px;margin-top:2.5rem}}
h3{{margin-top:1.5rem;color:#1e293b}}
table{{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.875rem}}
th{{background:#028a39;color:#fff;padding:8px;text-align:left}}
td{{padding:6px 8px;border:1px solid #e2e8f0}}
tr:nth-child(even) td{{background:#f8fafc}}
a{{color:#028a39}}
ul,ol{{padding-left:1.5rem}}
li{{margin:.25rem 0}}
p{{margin:.6rem 0}}
@media print{{body{{max-width:100%}}}}
</style>
</head>
<body>
<h1>Phan Tich Thue — {subject}</h1>
<p><em>Ngay tao: {now.strftime("%d/%m/%Y %H:%M")}</em></p>
<div id="report-body">
{html_content}
</div>
</body>
</html>"""
    (REPORTS_DIR / name).write_text(full_html, encoding="utf-8")
    return name
```

---

## After all changes

```bash
python3 -m py_compile main.py && echo "Syntax OK"
git add main.py requirements.txt
git commit -m "fix: citations linkify, force latest legal docs, add dispute/ruling sections, PPTX export, docx spacing, datetime filenames"
git push origin main
```
