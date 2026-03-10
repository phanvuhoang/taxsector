# BRIEF: Edit Report — Add Sections & Regenerate Section

## Mục tiêu
Cho phép người dùng bổ sung sections mới hoặc regenerate lại một section
vào báo cáo đã tạo — không cần generate lại toàn bộ report.

---

## Tính năng 1: "➕ Bổ sung sections" button

### UI
Khi đang xem report (phase = "report"), thêm button **"➕ Bổ sung"** vào toolbar
cạnh các nút hiện có (Lưu, Word, PowerPoint...).

Khi click → hiện modal/panel với:
- Tiêu đề: "Bổ sung sections vào báo cáo"
- Hiển thị danh sách TẤT CẢ sections (giống panel chọn sections lúc tạo report)
- Những section đã có trong report hiện tại → **disable + gạch xám** (không chọn được)
- Những section chưa có → **có thể chọn** (checkbox)
- Nút **"Generate sections đã chọn"**

### Logic backend
- Endpoint mới: `POST /append-sections`
- Body: `{ "subject": "...", "mode": "sector|company", "sections": [...], "existing_html": "..." }`
- Chỉ research + generate các sections được chọn (không generate lại phần đã có)
- Stream kết quả giống `/generate` hiện tại
- Kết quả append vào cuối `existing_html`

### Detect sections đã có trong report
Scan HTML hiện tại tìm các `<h2>` heading → map về section id.
Dùng function:
```python
def detect_existing_sections(html: str, sections_list: list) -> list:
    """Return list of section ids already present in html."""
    existing = []
    soup = BeautifulSoup(html, "html.parser")
    headings = [h.get_text(strip=True).lower() for h in soup.find_all("h2")]
    for s in sections_list:
        if any(s["title"].lower() in h for h in headings):
            existing.append(s["id"])
    return existing
```

---

## Tính năng 2: "🔄 Regenerate" button mỗi section

### UI
Mỗi `<h2>` section trong report → thêm nút nhỏ **🔄** ở góc phải heading khi hover.

Click 🔄 → confirm dialog: *"Regenerate lại section này? Nội dung cũ sẽ bị thay thế."*
→ Confirm → gọi API regenerate → replace section đó trong DOM.

Implement bằng JavaScript: sau khi report render xong, scan tất cả `<h2>`,
wrap mỗi cái bằng div có position:relative, thêm nút 🔄.

### Logic backend
- Endpoint mới: `POST /regenerate-section`
- Body: `{ "subject": "...", "mode": "sector|company", "section_id": "s1", "section_title": "...", "section_subs": [...] }`
- Chỉ research + generate section đó
- Stream HTML của section đó về client
- Client replace đoạn HTML từ `<h2>` section đó đến `<h2>` section tiếp theo

### Extract section từ HTML (để replace)
```javascript
function replaceSectionInHTML(fullHtml, sectionTitle, newSectionHtml) {
    // Tìm vị trí của section cần replace
    // Từ <h2>N. {title}</h2> đến <h2> tiếp theo (hoặc cuối file)
    const parser = new DOMParser();
    const doc = parser.parseFromString(fullHtml, 'text/html');
    const h2s = doc.querySelectorAll('h2');
    for (const h2 of h2s) {
        if (h2.textContent.includes(sectionTitle)) {
            // Replace từ h2 này đến h2 tiếp theo
            // ... implementation
        }
    }
}
```

---

## Notes cho Claude Code

1. Giữ nguyên tất cả logic hiện tại — chỉ ADD, không sửa existing code
2. Reuse functions đã có: `perplexity_search`, `tvpl_search`, `claude_stream_section`, `verify_legal_refs`
3. Nút "➕ Bổ sung" và "🔄" chỉ hiện khi đang ở phase "report"
4. Style nhất quán với UI hiện tại (Tailwind, màu #028a39)
5. Sau khi append/regenerate xong → tự động lưu lại file report (overwrite file cũ nếu đang xem saved report, hoặc save mới nếu chưa lưu)

---

## Commit message
`feat: add append-sections and regenerate-section to existing reports`

## Sau khi implement xong
Xoá file BRIEF-edit-report.md này khỏi repo.
