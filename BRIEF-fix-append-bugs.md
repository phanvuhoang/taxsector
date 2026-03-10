# BRIEF: Fix append-sections — 2 bugs cần fix

## Bug 1: TypeError khi generate (backend)

### Vấn đề
`build_query()` ở line ~116 gọi `", ".join(section.get("sub", []))`.
Custom sections gửi sub dạng `[{id, title}]` (list of objects) thay vì `["string"]`
→ TypeError: sequence item 0: expected str instance, dict found

### Fix trong backend — hàm `build_query()`:
Tìm dòng:
```python
subs = ", ".join(section.get("sub", []))
```

Thay bằng:
```python
raw_subs = section.get("sub", [])
# Handle cả 2 format: list of strings VÀ list of {id, title} objects
subs = ", ".join(
    s["title"] if isinstance(s, dict) else s
    for s in raw_subs
)
```

### Fix tương tự trong `build_section_prompt()`:
Tìm dòng tương tự join sub list (có thể là `sub_list = "\n".join(...)`):
```python
sub_list = "\n".join(f"- {s}" for s in section.get("sub", []))
```
Thay bằng:
```python
raw_subs = section.get("sub", [])
sub_list = "\n".join(
    f"- {s['title'] if isinstance(s, dict) else s}"
    for s in raw_subs
)
```

---

## Bug 2: Sections mới không hiển thị sau khi generate

### Vấn đề
Sau khi stream xong, code chỉ làm:
```javascript
reportHtml += '\n' + appendedHtml;
```
Nhưng KHÔNG update DOM → người dùng không thấy gì thay đổi.

### Fix trong JavaScript — cuối hàm `streamAppendSections()`:
Tìm đoạn sau khi stream done:
```javascript
reportHtml += '\n' + appendedHtml;
buildTOC();
buildSources();
closeModal('modal-append');
```

Thêm dòng render vào DOM TRƯỚC `buildTOC()`:
```javascript
// Append new sections vào report-content DOM
const content = document.getElementById('report-content');
if (content && appendedHtml) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = appendedHtml;
    // Append từng node vào cuối report
    [...tempDiv.childNodes].forEach(child => content.appendChild(child.cloneNode(true)));
}

reportHtml += '\n' + appendedHtml;
buildTOC();
buildSources();

// Scroll xuống cuối để thấy sections mới
content?.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'start' });

closeModal('modal-append');
appendCustomSections = [];
```

---

## Không thay đổi gì khác
Chỉ fix đúng 2 chỗ trên. Không viết lại functions khác.
Script chính vẫn phải nằm trong `<head>` (đã fix trước đó — giữ nguyên).

## Commit message
`fix: append-sections — handle dict subs format + render new sections to DOM`

## Sau khi xong
Xoá file BRIEF-fix-append-bugs.md rồi push.
