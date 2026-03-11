# BRIEF: Nâng cấp verify_legal_refs() dùng Legal DB

## Mục tiêu
Nâng cấp hàm `verify_legal_refs()` để cross-check văn bản pháp luật
được cite trong báo cáo với Legal DB local (361 văn bản, có trạng thái hiệu lực).
Tự động flag văn bản hết hiệu lực + gợi ý văn bản thay thế.

---

## Bước 1: Load Legal DB từ file JSON

Thêm vào phần đầu file (sau các import hiện tại):

```python
# ── Legal DB ────────────────────────────────────────────────────────────────
import urllib.request

LEGAL_DB_PATH = Path("/app/legal_db.json")
LEGAL_DB_URL  = "https://raw.githubusercontent.com/phanvuhoang/taxsector/main/legal_db.json"

def load_legal_db() -> list:
    """Load Legal DB từ file local. Download nếu chưa có."""
    if LEGAL_DB_PATH.exists():
        try:
            return json.loads(LEGAL_DB_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Fallback: download từ GitHub
    try:
        with urllib.request.urlopen(LEGAL_DB_URL, timeout=10) as r:
            data = r.read().decode("utf-8")
        LEGAL_DB_PATH.write_text(data, encoding="utf-8")
        return json.loads(data)
    except Exception as e:
        print(f"[WARN] Could not load legal DB: {e}")
        return []

LEGAL_DB: list = load_legal_db()

def build_legal_index(db: list) -> dict:
    """
    Build lookup dict: normalized_so_hieu → doc info
    Key examples: "nd132/2020", "tt80/2021", "luat14/2008"
    """
    index = {}
    for doc in db:
        so_hieu = doc.get("so_hieu", "")
        if not so_hieu:
            continue
        # Normalize: lowercase, bỏ dấu cách, bỏ ký tự đặc biệt
        key = re.sub(r'[\s\-/]+', '', so_hieu.lower())
        index[key] = doc
        # Thêm key viết tắt: "NĐ 132/2020" → "nđ132/2020" và "nd132/2020"
        key2 = key.replace('nđ', 'nd').replace('đ', 'd')
        if key2 != key:
            index[key2] = doc
    return index

LEGAL_INDEX: dict = build_legal_index(LEGAL_DB)
```

---

## Bước 2: Commit file legal_db.json vào repo

**QUAN TRỌNG:** Download file JSON từ GDrive và commit vào repo để app load được.

Trong terminal (trên VPS hoặc local), chạy:
```bash
# Download legal_db.json từ đây và commit vào repo
# File path trên GDrive: gdrive:Thanh-AI/LegalDB/all_merged.json
# Đặt tên file trong repo là: legal_db.json
```

**Nếu không download được GDrive**, tạo file `legal_db.json` tối thiểu với các văn bản quan trọng nhất:

```json
[
  {"so_hieu": "NĐ 132/2020/NĐ-CP", "ten": "Nghị định về giao dịch liên kết (Chuyển giá)", "tinh_trang": "con_hieu_luc", "thay_the": null, "ghi_chu": "Thay thế NĐ 20/2017"},
  {"so_hieu": "NĐ 20/2017/NĐ-CP", "ten": "Nghị định quản lý thuế với doanh nghiệp có giao dịch liên kết", "tinh_trang": "het_hieu_luc", "thay_the": "NĐ 132/2020/NĐ-CP", "ghi_chu": "Đã bị thay thế bởi NĐ 132/2020"},
  {"so_hieu": "Luật 48/2024/QH15", "ten": "Luật Thuế giá trị gia tăng 2024", "tinh_trang": "con_hieu_luc", "thay_the": null, "ghi_chu": "Hiệu lực từ 01/07/2025"},
  {"so_hieu": "Luật 13/2008/QH12", "ten": "Luật Thuế giá trị gia tăng 2008", "tinh_trang": "het_hieu_luc", "thay_the": "Luật 48/2024/QH15", "ghi_chu": "Hết hiệu lực 01/07/2025"},
  {"so_hieu": "TT 80/2021/TT-BTC", "ten": "Thông tư hướng dẫn Luật Quản lý thuế", "tinh_trang": "con_hieu_luc", "thay_the": null, "ghi_chu": null},
  {"so_hieu": "NQ 107/2023/QH15", "ten": "Nghị quyết thuế tối thiểu toàn cầu (Pillar 2)", "tinh_trang": "con_hieu_luc", "thay_the": null, "ghi_chu": "Áp dụng từ 01/01/2024"}
]
```

Commit file này vào repo gốc: `git add legal_db.json && git commit -m "data: add legal DB for verification"`

---

## Bước 3: Thêm helper function normalize văn bản

Thêm sau `build_legal_index()`:

```python
def normalize_doc_ref(ref: str) -> list:
    """
    Normalize số hiệu văn bản thành các key có thể lookup trong LEGAL_INDEX.
    Input:  "Nghị định 132/2020/NĐ-CP" hoặc "NĐ 132/2020" hoặc "132/2020/ND-CP"
    Output: ["nđ132/2020nđcp", "nd132/2020ndcp", "132/2020", ...]
    """
    ref_lower = ref.lower().strip()
    keys = []

    # Key 1: full normalized
    keys.append(re.sub(r'[\s\-]+', '', ref_lower))

    # Key 2: chỉ phần số/năm
    m = re.search(r'(\d+/\d{4})', ref)
    if m:
        keys.append(m.group(1))

    # Key 3: viết tắt loại + số/năm
    abbrevs = {
        r'ngh[iị]\s*[dđ][iị]nh': 'nd',
        r'th[oô]ng\s*t[uư]': 'tt',
        r'quy[eế]t\s*[dđ][iị]nh': 'qd',
        r'lu[aậ]t': 'luat',
        r'ngh[iị]\s*quy[eế]t': 'nq',
        r'ch[iỉ]\s*th[iị]': 'ct',
        r'c[oô]ng\s*v[aă]n': 'cv',
    }
    for pattern, abbr in abbrevs.items():
        if re.search(pattern, ref_lower):
            m2 = re.search(r'(\d+/\d{4})', ref)
            if m2:
                keys.append(f"{abbr}{m2.group(1).replace('/', '')}")
            break

    return list(set(keys))


def lookup_in_legal_db(ref: str) -> dict | None:
    """Tìm văn bản trong Legal DB. Trả về doc info hoặc None nếu không tìm thấy."""
    for key in normalize_doc_ref(ref):
        key_norm = re.sub(r'[\s\-/]+', '', key.lower())
        if key_norm in LEGAL_INDEX:
            return LEGAL_INDEX[key_norm]
        # Fuzzy: check substring
        for db_key, doc in LEGAL_INDEX.items():
            if key_norm in db_key or db_key in key_norm:
                return doc
    return None
```

---

## Bước 4: Nâng cấp `verify_legal_refs()`

Thay toàn bộ hàm `verify_legal_refs()` hiện tại bằng:

```python
async def verify_legal_refs(html: str) -> str:
    """
    Scan HTML báo cáo, tìm tất cả số hiệu văn bản pháp luật,
    cross-check với Legal DB:
    - Văn bản HẾT HIỆU LỰC → highlight đỏ + gợi ý thay thế
    - Văn bản không có trong DB → query TVPL để verify
    - Văn bản CÒN HIỆU LỰC trong DB → không làm gì
    """
    refs = list(set(LEGAL_REF_PATTERN.findall(html)))
    if not refs:
        return html

    expired_refs   = {}   # ref → thay_the
    unverified_refs = []  # ref không có trong DB, cần query TVPL

    for ref in refs:
        doc = lookup_in_legal_db(ref)
        if doc:
            status = doc.get("tinh_trang", "")
            if status in ("het_hieu_luc", "het_hieu_lực", "hết hiệu lực"):
                replacement = doc.get("thay_the") or doc.get("van_ban_thay_the", "")
                note = doc.get("ghi_chu", "")
                expired_refs[ref] = {"replacement": replacement, "note": note}
            # Còn hiệu lực → OK, bỏ qua
        else:
            unverified_refs.append(ref)

    # Query TVPL cho các văn bản không có trong DB
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for ref in unverified_refs[:10]:  # Giới hạn 10 để tránh chậm
            try:
                r = await client.get(
                    "https://thuvienphapluat.vn/van-ban-phap-luat.aspx",
                    params={"q": ref, "sbt": "1"},
                    headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "vi-VN"},
                )
                if ref not in r.text and r.status_code == 200:
                    # Không tìm thấy → mark unverified
                    expired_refs[ref] = {"replacement": None, "note": "Không tìm thấy trên TVPL"}
            except Exception:
                pass

    # Apply highlights vào HTML
    for ref, info in expired_refs.items():
        replacement = info.get("replacement", "")
        note = info.get("note", "")

        if replacement:
            tooltip = f"⚠️ Văn bản này đã HẾT HIỆU LỰC. Thay thế bởi: {replacement}. {note}"
            styled = (
                f'<span title="{tooltip}" '
                f'style="background:#fee2e2;border-bottom:2px solid #ef4444;'
                f'cursor:help;padding:0 2px;border-radius:2px">'
                f'⚠️ {ref} '
                f'<small style="color:#ef4444;font-weight:600">'
                f'[HẾT HIỆU LỰC → xem {replacement}]</small></span>'
            )
        else:
            tooltip = f"⚠️ {note or 'Cần kiểm tra hiệu lực văn bản này'}"
            styled = (
                f'<span title="{tooltip}" '
                f'style="background:#fff3cd;border-bottom:2px solid #f59e0b;'
                f'cursor:help;padding:0 2px;border-radius:2px">'
                f'⚠️ {ref}</span>'
            )
        html = html.replace(ref, styled, 1)

    return html
```

---

## Bước 5: Thêm vào system prompt của Perplexity

Tìm chỗ build system prompt cho Perplexity research (có `KHÔNG trích dẫn văn bản đã bị bãi bỏ`).
Thêm đoạn này vào ngay sau:

```python
# Inject danh sách văn bản đã hết hiệu lực vào system prompt
expired_list = [
    f"- {d['so_hieu']}: HẾT HIỆU LỰC, thay bởi {d.get('thay_the','')}"
    for d in LEGAL_DB
    if d.get("tinh_trang") in ("het_hieu_luc", "hết hiệu lực")
][:20]  # Giới hạn 20 để không quá dài

if expired_list:
    expired_text = "\n".join(expired_list)
    system_prompt += f"""

DANH SÁCH VĂN BẢN ĐÃ HẾT HIỆU LỰC — TUYỆT ĐỐI KHÔNG TRÍCH DẪN:
{expired_text}

Nếu cần đề cập các văn bản trên, PHẢI dùng văn bản thay thế tương ứng."""
```

---

## Không thay đổi
- Tất cả endpoints khác
- Background job flow
- Frontend JS
- LEGAL_REF_PATTERN regex (giữ nguyên)

## Commit message
`feat: upgrade verify_legal_refs with Legal DB cross-check + expired doc warning`

## Sau khi xong
Xoá BRIEF-legal-db-verify.md rồi push.

## Lưu ý cho Claude Code
File `legal_db.json` cần được commit vào repo. Nếu không có file này,
tạo file tối thiểu như hướng dẫn ở Bước 2. App vẫn chạy được nếu không
có Legal DB (fallback về TVPL query như cũ).
