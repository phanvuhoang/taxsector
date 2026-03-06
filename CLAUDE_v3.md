# CLAUDE_v3.md — 4 fixes for taxsector

Read and apply ALL changes below to `main.py`. After changes: `python3 -m py_compile main.py && echo OK`

---

## Fix 1: Citations — inline numbered links that open in new tab

**Problem:** Claude writes `[1]`, `[2]` etc. but without actual `<a>` tags linked to sources.

### A) Strengthen the prompt instruction in `build_section_prompt()`:

Find the line:
```
5. QUAN TRỌNG — Trích dẫn nguồn inline bắt buộc:
```
Replace the entire line 5 with:
```python
"5. TRÍCH DẪN NGUỒN — BẮT BUỘC TUYỆT ĐỐI:\n"
"   - Sau MỖI câu có số liệu, tên văn bản, hoặc thông tin cụ thể → chèn ngay: <a href=\"URL\" target=\"_blank\" rel=\"noopener\">[N]</a>\n"
"   - N là số thứ tự tăng dần từ 1 trong toàn bộ phần này\n"
"   - URL phải là URL thực tế từ dữ liệu nghiên cứu (Perplexity citations hoặc thuvienphapluat.vn)\n"
"   - Nếu không có URL cụ thể cho câu đó → dùng URL tổng quát của nguồn\n"
"   - KHÔNG viết [N] mà không có thẻ <a href=...>\n"
"   - KHÔNG gộp nhiều câu dùng chung 1 citation số\n"
"   Ví dụ đúng: Thuế GTGT hiện hành là 10%.<a href=\"https://thuvienphapluat.vn/van-ban/...\" target=\"_blank\" rel=\"noopener\">[1]</a>\n"
"   Ví dụ sai: Thuế GTGT hiện hành là 10%.[1] hoặc [1] không có href\n"
```

### B) In the `generate()` function, pass citation URLs into the Claude prompt context:

Find where `ctx` is built (Phase 2), and add the citations list to the context:

```python
            ctx = filter_context(all_results, section)

            # Prepend TVPL legal docs for law/tax sections
            tvpl_docs = all_tvpl.get(section["id"], [])
            if tvpl_docs and is_legal_or_tax_section(section):
                tvpl_text = format_tvpl_results(tvpl_docs)
                if tvpl_text:
                    ctx = tvpl_text + "\n\n" + ctx

            # Inject citation URLs so Claude can use real links
            section_citations = all_results.get(section["id"], {}).get("citations", [])
            tvpl_urls = [d.get("url","") for d in tvpl_docs if d.get("url")]
            all_section_urls = section_citations + tvpl_urls
            if all_section_urls:
                url_list = "\n".join(f"[{i+1}] {u}" for i,u in enumerate(all_section_urls[:20]))
                ctx = f"=== DANH SÁCH URL NGUỒN (dùng cho citation) ===\n{url_list}\n\n" + ctx
```

### C) Add post-processing `linkify_citations()` — kept as safety net:

Make sure this function exists (add after `save_report()` if not already there):

```python
def linkify_citations(html: str, citations: list[str]) -> str:
    """Safety net: replace bare [N] with linked version using citation URLs."""
    def replacer(m):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(citations) and citations[idx]:
            url = citations[idx]
            return f'<a href="{url}" target="_blank" rel="noopener">[{idx+1}]</a>'
        return m.group(0)
    # Only replace [N] that are NOT already inside an <a> tag
    return re.sub(r'(?<!href=")\[(\d+)\](?![^<]*</a>)', replacer, html)
```

And in `generate()`, before `save_report()`:
```python
        unique_citations = list(dict.fromkeys(c for c in all_citations if c))
        full_html = linkify_citations(full_html, unique_citations)
```

---

## Fix 2: Add AI caveat at the bottom of every report

### A) In `save_report()`, add caveat HTML before closing `</body>`:

Find the line in `save_report()` that writes the full HTML. Add this block before `</body></html>`:

```python
CAVEAT_HTML = """
<div style="margin-top:3rem;padding:1rem 1.5rem;background:#f8fafc;border-top:2px solid #e2e8f0;
            border-radius:.5rem;font-size:.8rem;color:#64748b;line-height:1.6">
  <strong>⚠️ Lưu ý quan trọng:</strong> Báo cáo này được tạo tự động bởi
  <strong>Tax Sector Research AI</strong> dựa trên dữ liệu từ Perplexity (sonar model)
  và thuvienphapluat.vn. Nội dung mang tính tham khảo, không thay thế tư vấn pháp lý
  hoặc thuế chuyên nghiệp. Người dùng cần kiểm chứng độc lập trước khi áp dụng.
  Thông tin pháp luật có thể thay đổi — vui lòng xác nhận hiệu lực văn bản tại
  <a href="https://thuvienphapluat.vn" target="_blank" rel="noopener">thuvienphapluat.vn</a>.
  <br><em>Ngày tạo: {date_str}</em>
</div>
"""
```

In `save_report()`, replace the `</body>` line:
```python
    full_html = f"""...
{html_content}
{CAVEAT_HTML.format(date_str=now.strftime("%d/%m/%Y %H:%M"))}
</div>
</body>
</html>"""
```

Also add the caveat to the live report in the frontend. In the JavaScript `finishReport()` function, after setting `content.innerHTML = reportHtml`, append:

```javascript
  // Add AI caveat at bottom
  const caveat = document.createElement('div');
  caveat.style.cssText = 'margin-top:2rem;padding:1rem;background:var(--bg);border-top:2px solid var(--border);border-radius:.5rem;font-size:.8rem;color:var(--muted);line-height:1.6';
  caveat.innerHTML = '<strong>⚠️ Lưu ý:</strong> Báo cáo tạo bởi AI (Tax Sector Research). Mang tính tham khảo, không thay thế tư vấn thuế chuyên nghiệp. Kiểm chứng hiệu lực văn bản tại <a href="https://thuvienphapluat.vn" target="_blank" style="color:var(--brand)">thuvienphapluat.vn</a>.';
  content.appendChild(caveat);
```

---

## Fix 3: Company mode — force latest regulations (same as Sector mode)

**Root cause:** Company mode (c3, c4 sections) uses different keywords than Sector, so:
1. `build_query()` doesn't add legal note for company sections
2. `is_legal_or_tax_section()` misses company section keywords
3. TVPL query for company mode doesn't include the company's industry

### A) Fix `is_legal_or_tax_section()` — add company section keywords:

```python
def is_legal_or_tax_section(section: dict) -> bool:
    """Return True if this section needs legal docs from thuvienphapluat.vn."""
    title = section.get("title", "").lower()
    subs  = " ".join(section.get("sub", [])).lower()
    keywords = [
        "pháp lý", "luật", "quy định", "giấy phép",
        "thuế", "thue", "tndn", "gtgt", "ttđb", "xnk",
        "nhà thầu", "chuyển giá", "ưu đãi", "tuân thủ",
        "phap ly", "van ban", "legal",
        # Company-specific additions:
        "tài chính", "gánh nặng", "tỷ lệ thuế", "rủi ro thuế",
        "thanh tra", "kiểm tra", "giao dịch liên kết", "cấu trúc pháp",
        "rui ro", "tranh chap", "ruling", "cong van",
    ]
    return any(kw in title + " " + subs for kw in keywords)
```

### B) Fix `build_tvpl_query()` — for company mode, include industry context:

```python
def build_tvpl_query(section: dict, subject: str, mode: str = "sector") -> str:
    title = section.get("title", "").lower()
    subs  = " ".join(section.get("sub", [])).lower()

    # For company mode: extract likely industry or use company name + "thuế"
    base_subject = subject
    if mode == "company":
        # Add "thuế" context since company analysis focuses on tax compliance
        base_subject = f"{subject} doanh nghiệp"

    kw_map = {
        "thuế gtgt": "thuế giá trị gia tăng",
        "thuế tndn": "thuế thu nhập doanh nghiệp",
        "thuế ttđb": "thuế tiêu thụ đặc biệt",
        "thuế xnk": "thuế xuất nhập khẩu",
        "nhà thầu": "thuế nhà thầu",
        "chuyển giá": "chuyển giá giao dịch liên kết",
        "ưu đãi": f"ưu đãi thuế {base_subject}",
        "tranh chấp": f"tranh chấp thuế {base_subject}",
        "giao dịch liên kết": "chuyển giá giao dịch liên kết",
        "tài chính": f"thuế {base_subject}",
        "thuế": f"thuế {base_subject}",
        "pháp lý": base_subject,
        "luật": base_subject,
        "quy định": base_subject,
    }
    for kw, q in kw_map.items():
        if kw in title or kw in subs:
            return q
    return f"thuế {base_subject}"
```

### C) Fix `build_query()` — pass mode context more explicitly for company:

Find `build_query()` and update the legal note section:

```python
def build_query(section: dict, subject: str, mode: str) -> str:
    from datetime import datetime
    current_year = datetime.now().year
    mode_ctx = "ngành" if mode == "sector" else "công ty"

    # For company mode, add industry hint to help Perplexity find relevant laws
    subject_ctx = subject
    if mode == "company":
        subject_ctx = f"{subject} (phân tích thuế doanh nghiệp)"

    subs = ", ".join(section.get("sub", []))
    title_lower = section.get("title", "").lower()
    is_legal = any(k in title_lower for k in [
        "pháp lý","luật","quy định","thuế","thue","tài chính","rủi ro","tranh chấp"
    ])
    legal_note = (
        f"\nLƯU Ý BẮT BUỘC: Chỉ trích dẫn văn bản pháp luật CÒN HIỆU LỰC tính đến {current_year}. "
        f"Ưu tiên Luật/Nghị định/Thông tư được ban hành hoặc sửa đổi trong 2020-{current_year}. "
        f"Nếu có văn bản mới thay thế → bắt buộc dùng văn bản MỚI NHẤT, ghi rõ nó thay thế văn bản nào. "
        f"KHÔNG trích dẫn văn bản đã bị bãi bỏ."
    ) if is_legal else ""

    return (
        f"Nghiên cứu chuyên sâu về: {section['title']} — {mode_ctx} {subject_ctx} tại Việt Nam năm {current_year}\n"
        f"Chi tiết cần tìm: {subs}\n"
        f"Bao gồm: số hiệu văn bản pháp luật cụ thể, số liệu thị trường, "
        f"tên doanh nghiệp, ví dụ thực tế, nguồn đáng tin cậy"
        f"{legal_note}"
    )
```

### D) Pass `mode` into `build_tvpl_query()` call in `generate()`:

Find the call to `build_tvpl_query()` in Phase 1 and update:
```python
            tvpl_tasks = [
                tvpl_search(build_tvpl_query(s, subject, mode))
                if is_legal_or_tax_section(s)
                else _empty()
                for s in batch
            ]
```
(Make sure `_empty()` async helper exists — add if not present:)
```python
async def _empty():
    return []
```

---

## Fix 4: AI recommends research sections before starting (smart pre-analysis)

**Feature:** Before the user clicks "Bắt đầu phân tích", add a button "✨ AI Gợi ý cấu trúc" that:
1. Takes the subject name (company or sector)
2. Calls a new `/recommend-sections` endpoint
3. Claude analyzes what a tax consultant needs to research for that subject
4. Returns recommended sections with sub-items, replacing/augmenting the current section list

### A) Add new endpoint `/recommend-sections` in FastAPI:

```python
@app.post("/recommend-sections")
async def recommend_sections(request: Request, _user: str = Depends(auth)):
    body    = await request.json()
    subject = body.get("subject", "").strip()
    mode    = body.get("mode", "sector")

    if not subject:
        raise HTTPException(400, "Missing subject")
    if not ANTHROPIC_KEY:
        # Return default sections if no API key
        return {"sections": SECTOR_SECTIONS_VI if mode == "sector" else COMPANY_SECTIONS_VI}

    mode_ctx = "ngành/lĩnh vực" if mode == "sector" else "công ty"
    prompt = f"""Bạn là chuyên gia tư vấn thuế Big 4 (Deloitte/PwC/EY/KPMG) với 20 năm kinh nghiệm.

Nhà tư vấn thuế cần nghiên cứu về {mode_ctx}: **{subject}**

Hãy đề xuất cấu trúc báo cáo phân tích thuế TỐI ƯU cho đối tượng này. 
Dựa trên đặc thù của {subject}, hãy:
1. Xác định các section quan trọng nhất (5-8 section)
2. Với mỗi section, liệt kê 4-6 sub-items CỤ THỂ cho {subject} (không chung chung)
3. Đặc biệt chú ý các vấn đề thuế đặc thù, rủi ro cao, hoặc quy định mới nhất cho ngành/công ty này

Trả về JSON ARRAY theo format sau, KHÔNG giải thích thêm:
[
  {{
    "id": "s1",
    "title": "Tên section tiếng Việt",
    "sub": ["sub-item 1 cụ thể", "sub-item 2 cụ thể", ...],
    "enabled": true
  }},
  ...
]

Chỉ trả về JSON array, bắt đầu bằng [ và kết thúc bằng ]."""

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
    try:
        msg = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text.strip()
        # Extract JSON array
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            sections = json.loads(match.group())
            # Ensure all sections have required fields
            for i, s in enumerate(sections):
                if "id" not in s:
                    s["id"] = f"r{i+1}"
                if "enabled" not in s:
                    s["enabled"] = True
            return {"sections": sections, "ai_recommended": True}
        else:
            # Fallback to defaults
            return {"sections": SECTOR_SECTIONS_VI if mode == "sector" else COMPANY_SECTIONS_VI}
    except Exception as e:
        return {"sections": SECTOR_SECTIONS_VI if mode == "sector" else COMPANY_SECTIONS_VI,
                "error": str(e)}
```

### B) Update the frontend — add "✨ AI Gợi ý" button and flow:

In `HTML_PAGE`, find the subject input section and add a button after the input:

```html
<!-- After the sonar model radio buttons, add: -->
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

In the JavaScript section, add the `aiRecommend()` function:

```javascript
async function aiRecommend() {
  const subject = document.getElementById('subj-input').value.trim();
  if (!subject) {
    alert('Vui lòng nhập tên ngành hoặc công ty trước');
    return;
  }
  const btn = document.getElementById('btn-recommend');
  const hint = document.getElementById('recommend-hint');
  btn.textContent = '⏳ AI đang phân tích...';
  btn.disabled = true;
  hint.textContent = 'Đang gợi ý sections phù hợp với ' + subject + '...';

  try {
    const r = await fetch('/recommend-sections', {
      method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({subject, mode}),
    });
    if (r.ok) {
      const data = await r.json();
      if (data.sections && data.sections.length) {
        sections = data.sections;
        renderSections();
        hint.textContent = data.ai_recommended
          ? `✅ AI đã đề xuất ${data.sections.length} sections tối ưu cho "${subject}"`
          : '⚠️ Dùng sections mặc định (AI không khả dụng)';
      }
    } else {
      hint.textContent = 'Không thể lấy gợi ý — dùng sections mặc định';
    }
  } catch(e) {
    hint.textContent = 'Lỗi: ' + e.message;
  } finally {
    btn.textContent = '✨ AI Gợi ý cấu trúc cho chủ đề này';
    btn.disabled = false;
  }
}
```

---

## After all changes

```bash
python3 -m py_compile main.py && echo "Syntax OK"
git add main.py
git commit -m "fix: inline citations with links, AI caveat, company mode latest laws, AI section recommender"
git push origin main
```
