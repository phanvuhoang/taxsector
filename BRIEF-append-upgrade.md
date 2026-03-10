# BRIEF: Nâng cấp tính năng Bổ sung & Regenerate

## Tổng quan
Nâng cấp 2 tính năng đã có (append-sections, regenerate-section) với UX tốt hơn.
Reuse tối đa code hiện tại — KHÔNG viết lại từ đầu.

---

## Tính năng 1: Nâng cấp modal "➕ Bổ sung"

### Mô tả
Modal hiện tại chỉ cho chọn sections có sẵn. Nâng cấp thêm:
- Input box để nhập topic tùy chỉnh
- Nút "+ Thêm topic" để add vào danh sách
- Trong mỗi topic mới có nút "+ Thêm subtopic"

### Layout modal mới:

```
┌──────────────────────────────────────────────┐
│  ➕ Bổ sung vào báo cáo                       │
├──────────────────────────────────────────────┤
│                                              │
│  📋 SECTIONS CÓ SẴN (chưa có trong báo cáo) │
│  ─────────────────────────────────────────   │
│  ☐ [tên section chưa có 1]                   │
│  ☐ [tên section chưa có 2]                   │
│  (nếu tất cả đã có → hiện "Đã có đầy đủ")   │
│                                              │
│  ✏️ THÊM PHẦN TÙY CHỈNH                     │
│  ─────────────────────────────────────────   │
│  ┌────────────────────────────┐  [+ Thêm]   │
│  │ Nhập tên phần mới...       │              │
│  └────────────────────────────┘              │
│                                              │
│  [Danh sách topics đã thêm:]                 │
│  ┌──────────────────────────────────────┐    │
│  │ 📄 Ưu đãi thuế đặc thù          [✕] │    │
│  │   ├ Khu công nghệ cao            [✕] │    │
│  │   ├ Doanh nghiệp khởi nghiệp     [✕] │    │
│  │   └ [+ Thêm subtopic]                │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │ 📄 Rủi ro thuế quốc tế          [✕] │    │
│  │   └ [+ Thêm subtopic]                │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  [Generate sections đã chọn]  [Đóng]        │
└──────────────────────────────────────────────┘
```

### Logic JavaScript

```javascript
// State cho append modal
let appendCustomSections = []; 
// Format: [{id, title, sub: [{id, title}], enabled: true}]

function openAppendModal() {
  if (!reportHtml) { alert('Chưa có báo cáo'); return; }
  
  // Detect sections đã có trong báo cáo
  const existing = detectExistingSections(reportHtml, sections);
  
  // Render 2 phần: preset sections + custom input
  renderAppendPreset(existing);   // sections có sẵn chưa có trong report
  renderAppendCustom();           // danh sách custom topics đã add
  
  openModal('modal-append');
}

function addCustomTopic() {
  const input = document.getElementById('append-topic-input');
  const title = input.value.trim();
  if (!title) return;
  
  const id = 'custom_' + Date.now();
  appendCustomSections.push({id, title, sub: [], enabled: true});
  input.value = '';
  renderAppendCustom();
}

function addSubtopic(topicId) {
  const input = document.getElementById('sub-input-' + topicId);
  const title = input.value.trim();
  if (!title) return;
  
  const topic = appendCustomSections.find(s => s.id === topicId);
  if (topic) {
    topic.sub.push({id: 'sub_' + Date.now(), title});
    input.value = '';
    renderAppendCustom();
  }
}

function removeCustomTopic(topicId) {
  appendCustomSections = appendCustomSections.filter(s => s.id !== topicId);
  renderAppendCustom();
}

function removeSubtopic(topicId, subId) {
  const topic = appendCustomSections.find(s => s.id === topicId);
  if (topic) {
    topic.sub = topic.sub.filter(s => s.id !== subId);
    renderAppendCustom();
  }
}

function renderAppendCustom() {
  const container = document.getElementById('append-custom-list');
  if (appendCustomSections.length === 0) {
    container.innerHTML = '<p class="text-sm" style="color:var(--muted)">Chưa có phần tùy chỉnh nào.</p>';
    return;
  }
  
  container.innerHTML = appendCustomSections.map(topic => `
    <div class="border rounded-lg p-3 mb-2" style="border-color:var(--border);background:var(--surface)">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-sm">📄 ${esc(topic.title)}</span>
        <button onclick="removeCustomTopic('${topic.id}')" 
          class="text-red-400 hover:text-red-600 text-xs">✕</button>
      </div>
      
      <!-- Subtopics list -->
      ${topic.sub.map(sub => `
        <div class="flex items-center gap-2 ml-4 mb-1">
          <span class="text-xs" style="color:var(--muted)">├ ${esc(sub.title)}</span>
          <button onclick="removeSubtopic('${topic.id}','${sub.id}')" 
            class="text-red-300 hover:text-red-500 text-xs">✕</button>
        </div>
      `).join('')}
      
      <!-- Add subtopic input -->
      <div class="flex gap-2 ml-4 mt-2">
        <input id="sub-input-${topic.id}" type="text" 
          placeholder="Thêm subtopic..."
          onkeydown="if(event.key==='Enter')addSubtopic('${topic.id}')"
          class="flex-1 border rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-green-400"
          style="border-color:var(--border);background:var(--bg);color:var(--text)">
        <button onclick="addSubtopic('${topic.id}')" 
          class="text-xs px-2 py-1 rounded" 
          style="background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0">
          + Subtopic
        </button>
      </div>
    </div>
  `).join('');
}
```

### API call khi Generate
Gộp sections preset đã check + custom sections lại rồi gọi `/append-sections`:

```javascript
async function doAppend() {
  // Thu thập preset sections đã check
  const checkedPreset = [...document.querySelectorAll('#append-preset-list input:checked')]
    .map(cb => sections.find(s => s.id === cb.value))
    .filter(Boolean);
  
  // Gộp với custom sections
  const toGenerate = [...checkedPreset, ...appendCustomSections.filter(s => s.enabled)];
  
  if (toGenerate.length === 0) { alert('Chọn ít nhất 1 section'); return; }
  
  // Truyền subject và context từ báo cáo hiện tại
  const currentSubject = document.getElementById('rpt-title')?.textContent
    ?.replace('Phân Tích Thuế — ', '') || '';
  
  // Gọi API (stream) — reuse logic từ /generate hiện tại
  await streamAppendSections(currentSubject, mode, toGenerate, reportHtml);
}
```

### Backend `/append-sections` endpoint
Nhận thêm `existing_summary` (200 chars đầu của reportHtml) để Claude biết context:

```python
@app.post("/append-sections")
async def append_sections(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    subject = body.get("subject", "")
    mode = body.get("mode", "sector")
    new_sections = body.get("sections", [])
    existing_html = body.get("existing_html", "")
    
    # Thêm context summary vào prompt của từng section mới
    context_hint = f"\n\nLƯU Ý: Đây là phần BỔ SUNG vào báo cáo về {subject}. " \
                   f"Báo cáo đã có {len(existing_html)//500} phần. " \
                   f"Viết nhất quán với nội dung đã có, không lặp lại."
    
    # Stream — reuse generate_report logic, chỉ với sections mới
    # ... (tương tự /generate nhưng chỉ loop qua new_sections)
```

---

## Tính năng 2: Regenerate section (giữ nguyên + thêm context)

### Nâng cấp nhỏ
Khi regenerate, truyền thêm `existing_context` = nội dung 2 sections xung quanh
để Claude viết nhất quán hơn:

```python
@app.post("/regenerate-section")  
async def regenerate_section(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    subject = body.get("subject", "")
    mode = body.get("mode", "sector")
    section_id = body.get("section_id", "")
    section_title = body.get("section_title", "")
    section_subs = body.get("section_subs", [])
    existing_context = body.get("existing_context", "")  # NEW: context từ sections khác
    
    # Thêm vào prompt: "Đây là regenerate section X, các sections khác đã có: ..."
```

---

## Style & UX rules
1. Màu chủ đạo: `#028a39` (var(--brand)) — nhất quán với app
2. Input fields: style giống các input hiện tại trong app
3. Nút "+ Thêm": small, outline green style
4. Nút "✕" xoá: màu đỏ nhạt, chỉ đậm khi hover
5. Khi đang generate: disable nút, hiện spinner, cho phép cancel
6. Sau khi append xong: auto-save report (overwrite nếu đang xem saved file)
7. Reset `appendCustomSections = []` khi đóng modal

---

## Quan trọng — Không làm

- KHÔNG viết lại các functions hiện tại (doLogin, loadSections, generate, v.v.)
- KHÔNG thay đổi backend endpoints hiện tại (chỉ ADD mới)
- KHÔNG thay đổi cấu trúc HTML hiện tại ngoài modal-append
- Script chính PHẢI nằm trong `<head>`, trước tất cả HTML body (lỗi đã fix trước đó)

---

## Commit message
`feat: upgrade append-modal with custom topics/subtopics + context-aware regenerate`

## Sau khi implement xong
Xoá file BRIEF-append-upgrade.md này khỏi repo rồi push.
