#!/usr/bin/env python3
"""Tax Sector Research Tool — Single-file FastAPI application"""

import os, asyncio, json, re, io, secrets, time
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from docx import Document
from docx.shared import RGBColor
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY", "")
CLAUDE_KEY     = os.getenv("CLAUDIBLE_API_KEY", "")
CLAUDE_URL     = os.getenv("CLAUDIBLE_BASE_URL", "https://claudible.io/v1")
CLAUDE_MODEL   = os.getenv("CLAUDIBLE_MODEL", "claude-sonnet-4.6")
APP_USER       = os.getenv("APP_USERNAME", "hoang")
APP_PASS       = os.getenv("APP_PASSWORD", "taxsector2026")
REPORTS_DIR    = Path(os.getenv("REPORTS_DIR", "./reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Auth ──────────────────────────────────────────────────────────────────────
security = HTTPBasic()

def auth(creds: HTTPBasicCredentials = Depends(security)):
    ok = (
        secrets.compare_digest(creds.username.encode(), APP_USER.encode()) and
        secrets.compare_digest(creds.password.encode(), APP_PASS.encode())
    )
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return creds.username

# ── Default sections ──────────────────────────────────────────────────────────
SECTOR_SECTIONS = [
    {"id": "s1", "title": "Tong quan ve nganh",
     "sub": ["Quy mo thi truong", "Dac diem kinh doanh", "Mo hinh doanh thu/chi phi"], "enabled": True},
    {"id": "s2", "title": "Dac thu cua nganh",
     "sub": ["Chuoi cung ung upstream/downstream", "Working capital cycle", "Dac diem tai san"], "enabled": True},
    {"id": "s3", "title": "Su phat trien tai Viet Nam & Big Players",
     "sub": ["Tang truong 5 nam gan nhat", "Doanh nghiep lon nhat", "FDI", "M&A"], "enabled": True},
    {"id": "s4", "title": "Cac quy dinh phap ly quan trong",
     "sub": ["Luat chuyen nganh", "Dieu kien kinh doanh", "Giay phep", "Han che FDI"], "enabled": True},
    {"id": "s5", "title": "Phan tich cac loai thue ap dung",
     "sub": ["Thue TNDN", "Thue GTGT", "Thue Nha thau", "Thue TTDB", "Thue XNK", "Phi & le phi"], "enabled": True},
    {"id": "s6", "title": "Cac van de thue dac thu cua nganh",
     "sub": ["Rui ro doanh thu/chi phi", "Chuyen gia", "Uu dai thue", "Hoa don dac thu", "Khau tru thue"], "enabled": True},
    {"id": "s7", "title": "Thong le & van de thue quoc te",
     "sub": ["BEPS", "Chuyen gia quoc te", "So sanh voi khu vuc", "Hiep dinh thue"], "enabled": True},
]

SECTOR_SECTIONS_VI = [
    {"id": "s1", "title": "Tổng quan về ngành",
     "sub": ["Quy mô thị trường", "Đặc điểm kinh doanh", "Mô hình doanh thu/chi phí"], "enabled": True},
    {"id": "s2", "title": "Đặc thù của ngành",
     "sub": ["Chuỗi cung ứng upstream/downstream", "Working capital cycle", "Đặc điểm tài sản"], "enabled": True},
    {"id": "s3", "title": "Sự phát triển tại Việt Nam & Big Players",
     "sub": ["Tăng trưởng 5 năm gần nhất", "Doanh nghiệp lớn nhất", "FDI", "M&A"], "enabled": True},
    {"id": "s4", "title": "Các quy định pháp lý quan trọng",
     "sub": ["Luật chuyên ngành", "Điều kiện kinh doanh", "Giấy phép", "Hạn chế FDI"], "enabled": True},
    {"id": "s5", "title": "Phân tích các loại thuế áp dụng",
     "sub": ["Thuế TNDN", "Thuế GTGT", "Thuế Nhà thầu", "Thuế TTĐB", "Thuế XNK", "Phí & lệ phí"], "enabled": True},
    {"id": "s6", "title": "Các vấn đề thuế đặc thù của ngành",
     "sub": ["Rủi ro doanh thu/chi phí", "Chuyển giá", "Ưu đãi thuế", "Hóa đơn đặc thù", "Khấu trừ thuế"], "enabled": True},
    {"id": "s7", "title": "Thông lệ & vấn đề thuế quốc tế",
     "sub": ["BEPS", "Chuyển giá quốc tế", "So sánh với khu vực", "Hiệp định thuế"], "enabled": True},
]

COMPANY_SECTIONS_VI = [
    {"id": "c1", "title": "Giới thiệu công ty",
     "sub": ["Lịch sử hình thành", "Cơ cấu sở hữu", "Hoạt động kinh doanh chính"], "enabled": True},
    {"id": "c2", "title": "Mô hình kinh doanh & chuỗi giá trị",
     "sub": ["Sản phẩm/dịch vụ", "Khách hàng mục tiêu", "Nhà cung cấp", "Chuỗi giá trị"], "enabled": True},
    {"id": "c3", "title": "Phân tích tài chính & thuế",
     "sub": ["Doanh thu & lợi nhuận", "Gánh nặng thuế", "Tỷ lệ thuế hiệu quả", "So sánh ngành"], "enabled": True},
    {"id": "c4", "title": "Rủi ro thuế đặc thù",
     "sub": ["Rủi ro thanh tra", "Chuyển giá", "Cấu trúc pháp lý", "Giao dịch liên kết"], "enabled": True},
    {"id": "c5", "title": "Khuyến nghị",
     "sub": ["Tối ưu hóa thuế", "Tuân thủ", "Cơ hội ưu đãi", "Rủi ro cần theo dõi"], "enabled": True},
]

# ── Research: Perplexity ──────────────────────────────────────────────────────
def build_query(section: dict, subject: str, mode: str) -> str:
    mode_ctx = "ngành" if mode == "sector" else "công ty"
    subs = ", ".join(section.get("sub", []))
    return (
        f"Nghiên cứu chuyên sâu về: {section['title']} — {mode_ctx} {subject} tại Việt Nam năm 2024-2025\n"
        f"Chi tiết cần tìm: {subs}\n"
        f"Bao gồm: số hiệu văn bản pháp luật cụ thể, số liệu thị trường, "
        f"tên doanh nghiệp, ví dụ thực tế, nguồn đáng tin cậy"
    )

async def perplexity_search(query: str, model: str = "sonar") -> dict:
    if not PERPLEXITY_KEY:
        return {"content": f"[Perplexity API key not set]\n\nQuery was: {query[:200]}", "citations": []}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content":
             "Bạn là chuyên gia nghiên cứu thuế và pháp lý Việt Nam. "
             "Cung cấp thông tin chính xác, đầy đủ, có số liệu cụ thể và nguồn tham khảo."},
            {"role": "user", "content": query},
        ],
        "max_tokens": 2000,
        "return_citations": True,
        "return_related_questions": False,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        try:
            r = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {PERPLEXITY_KEY}"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            return {"content": content, "citations": citations}
        except Exception as e:
            return {"content": f"[Research error: {e}]", "citations": []}

# ── Context filtering ─────────────────────────────────────────────────────────
KEYWORD_MAP = {
    "pháp lý": ["s4", "c4"],
    "luật": ["s4", "c4"],
    "quy định": ["s4", "c4"],
    "thuế": ["s5", "s6", "s7", "c3", "c4"],
    "tổng quan": ["s1", "c1"],
    "đặc thù": ["s2", "s6"],
    "big player": ["s3"],
    "doanh nghiep": ["s3", "c1"],
    "quoc te": ["s7"],
    "tài chính": ["c3"],
    "khuyến nghị": ["c5"],
    "mô hình": ["s1", "s2", "c2"],
    "chuỗi": ["s2", "c2"],
}

def filter_context(all_results: dict, section: dict) -> str:
    title_lower = section["title"].lower()
    relevant = {section["id"]}
    for kw, ids in KEYWORD_MAP.items():
        if kw in title_lower:
            relevant.update(ids)

    parts = []
    # Own section first
    if section["id"] in all_results:
        parts.append(all_results[section["id"]].get("content", "")[:5000])
    # Related sections (shorter)
    for sid in relevant:
        if sid != section["id"] and sid in all_results:
            parts.append(all_results[sid].get("content", "")[:2000])

    return "\n\n---\n\n".join(parts)[:10000]

# ── Claude per-section streaming ──────────────────────────────────────────────
def build_section_prompt(section: dict, subject: str, context: str, mode: str, num: int) -> str:
    mode_ctx = "ngành" if mode == "sector" else "công ty"
    sub_list = "\n".join(f"- {s}" for s in section.get("sub", []))
    title = section["title"]

    is_legal = any(k in title.lower() for k in ["pháp lý", "luật", "quy định", "phap ly", "luat"])
    is_tax   = any(k in title.lower() for k in ["thuế", "thue"])

    table_block = ""
    if is_legal or is_tax:
        table_block = """
QUAN TRỌNG: Bắt đầu với bảng tổng hợp văn bản pháp luật/thuế liên quan (ít nhất 6-8 văn bản):
<table>
  <thead><tr>
    <th>Số hiệu</th><th>Tên văn bản</th><th>Loại</th>
    <th>Ngày hiệu lực</th><th>Tình trạng</th><th>Liên quan</th>
  </tr></thead>
  <tbody>... (điền thực tế) ...</tbody>
</table>
"""

    return f"""Bạn là chuyên gia thuế Big 4 (Deloitte/PwC/EY/KPMG) viết báo cáo phân tích thuế chuyên nghiệp bằng tiếng Việt.

Viết PHẦN {num}: "{title}" trong báo cáo phân tích về {mode_ctx}: **{subject}**

Các chủ đề bắt buộc đề cập:
{sub_list}
{table_block}
DỮ LIỆU NGHIÊN CỨU (dùng thông tin này, bổ sung thêm kiến thức của bạn):
{context}

YÊU CẦU TUYỆT ĐỐI:
1. Output là HTML THUẦN TÚY — KHÔNG markdown, KHÔNG backticks, KHÔNG code block
2. Bắt đầu bằng: <h2>{num}. {title}</h2>
3. Dùng thẻ HTML: <h3>, <p>, <ul><li>, <ol><li>, <table> — KHÔNG <div> thừa
4. Văn phong: chuyên nghiệp, cụ thể, dẫn chứng số liệu và tên văn bản pháp luật thực tế
5. Trích dẫn nguồn inline: <a href="URL" target="_blank">[N]</a>
6. Tối thiểu 700 từ — đầy đủ, không rút gọn
7. KHÔNG viết lời mở đầu/kết luận tổng quát — chỉ nội dung của phần này"""

async def claude_stream_section(
    section: dict, subject: str, context: str, mode: str, num: int
) -> AsyncGenerator[str, None]:
    if not CLAUDE_KEY:
        yield f"<h2>{num}. {section['title']}</h2><p><em>[Claude API key not configured]</em></p>"
        return

    prompt = build_section_prompt(section, subject, context, mode, num)
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2000,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {CLAUDE_KEY}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST", f"{CLAUDE_URL}/chat/completions",
                headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        pass
        except Exception as e:
            yield f'<p style="color:red">[Error in section {num}: {e}]</p>'

# ── Report persistence ────────────────────────────────────────────────────────
def safe_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", s)[:60].strip()

def save_report(subject: str, html_content: str) -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    base = safe_filename(subject)
    n = 1
    while True:
        name = f"{date_str} - {base} - {n}.html"
        if not (REPORTS_DIR / name).exists():
            break
        n += 1

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
<p><em>Ngay tao: {datetime.now().strftime("%d/%m/%Y %H:%M")}</em></p>
<div id="report-body">
{html_content}
</div>
</body>
</html>"""
    (REPORTS_DIR / name).write_text(full_html, encoding="utf-8")
    return name

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Tax Sector Research")

# ── SSE stream endpoint ───────────────────────────────────────────────────────
@app.post("/stream")
async def stream_report(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    subject  = body.get("subject", "").strip()
    mode     = body.get("mode", "sector")
    sections = body.get("sections", [])
    sonar    = body.get("sonar_model", "sonar")

    if not subject:
        raise HTTPException(400, "Missing subject")

    enabled = [s for s in sections if s.get("enabled")]
    if not enabled:
        raise HTTPException(400, "No sections enabled")

    async def generate():
        def sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield sse({"type": "ping"})
        yield sse({"type": "status", "message": f"Đang nghiên cứu '{subject}'..."})

        # Phase 1: parallel research in batches of 4
        all_results: dict = {}
        all_citations: list = []
        total = len(enabled)

        for batch_start in range(0, total, 4):
            batch = enabled[batch_start:batch_start + 4]

            for i, sec in enumerate(batch):
                yield sse({
                    "type": "progress",
                    "step": batch_start + i + 1,
                    "total": total,
                    "label": f"Đang nghiên cứu: {sec['title']}",
                })

            results = await asyncio.gather(*[
                perplexity_search(build_query(s, subject, mode), sonar)
                for s in batch
            ])

            for sec, res in zip(batch, results):
                all_results[sec["id"]] = res
                all_citations.extend(res.get("citations", []))
                yield sse({
                    "type": "progress",
                    "step": batch_start + batch.index(sec) + 1,
                    "total": total,
                    "label": f"Xong research: {sec['title']}",
                })

        # Phase 2: Claude per section
        yield sse({"type": "ai_start", "total": len(enabled)})
        full_html = ""

        for i, section in enumerate(enabled):
            yield sse({
                "type": "status",
                "message": f"AI đang viết phần {i + 1}/{len(enabled)}: {section['title']}",
            })
            ctx = filter_context(all_results, section)
            sec_html = ""

            async for chunk in claude_stream_section(section, subject, ctx, mode, i + 1):
                yield sse({"type": "chunk", "text": chunk})
                sec_html += chunk
                await asyncio.sleep(0)

            full_html += sec_html + "\n"
            yield sse({"type": "ping"})

        # Citations
        unique_urls = list(dict.fromkeys(all_citations))
        yield sse({"type": "citations", "urls": unique_urls})

        # Save
        try:
            filename = save_report(subject, full_html)
        except Exception:
            filename = None

        yield sse({"type": "done", "filename": filename, "drive": False})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

# ── Default sections ──────────────────────────────────────────────────────────
@app.get("/default-sections")
def default_sections(mode: str = "sector", _user: str = Depends(auth)):
    return SECTOR_SECTIONS_VI if mode == "sector" else COMPANY_SECTIONS_VI

# ── Suggest subsections ───────────────────────────────────────────────────────
@app.post("/suggest-subsections")
async def suggest_subsections(request: Request, _user: str = Depends(auth)):
    body = await request.json()
    title   = body.get("title", "")
    subject = body.get("subject", "")

    if not CLAUDE_KEY:
        return {"suggestions": []}

    prompt = (
        f'Đề xuất 4-5 chủ đề con phù hợp cho phần "{title}" '
        f'trong báo cáo phân tích thuế về: {subject}\n'
        f'Trả về JSON array, ví dụ: ["Chủ đề 1", "Chủ đề 2"]\n'
        f'Chỉ trả về JSON array, không giải thích thêm.'
    )
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            r = await client.post(
                f"{CLAUDE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {CLAUDE_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
            content = r.json()["choices"][0]["message"]["content"]
            match = re.search(r'\[.*\]', content, re.DOTALL)
            suggestions = json.loads(match.group()) if match else []
        except Exception:
            suggestions = []
    return {"suggestions": suggestions}

# ── Reports ───────────────────────────────────────────────────────────────────
@app.get("/reports")
def list_reports(_user: str = Depends(auth)):
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        size = f"{stat.st_size // 1024} KB" if stat.st_size >= 1024 else f"{stat.st_size} B"
        reports.append({
            "name": f.name,
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
            "size": size,
        })
    return reports

@app.get("/report/{name:path}")
def get_report(name: str, _user: str = Depends(auth)):
    path = (REPORTS_DIR / name).resolve()
    try:
        path.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid path")
    if not path.exists():
        raise HTTPException(404)
    return HTMLResponse(path.read_text(encoding="utf-8"))

@app.delete("/report/{name:path}")
def delete_report(name: str, _user: str = Depends(auth)):
    path = (REPORTS_DIR / name).resolve()
    try:
        path.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid path")
    if not path.exists():
        raise HTTPException(404)
    path.unlink()
    return {"ok": True}

# ── DOCX export ───────────────────────────────────────────────────────────────
@app.post("/docx")
async def export_docx(request: Request, _user: str = Depends(auth)):
    body    = await request.json()
    html    = body.get("html", "")
    subject = body.get("subject", "Báo cáo")

    doc = Document()
    title_para = doc.add_heading(f"Phân Tích Thuế — {subject}", 0)
    if title_para.runs:
        title_para.runs[0].font.color.rgb = RGBColor(0x02, 0x8A, 0x39)
    doc.add_paragraph(f"Ngày tạo: {datetime.now().strftime('%d/%m/%Y')}")

    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(["h2", "h3", "p", "li", "table"]):
        text = el.get_text(strip=True)
        if not text:
            continue
        tag = el.name
        if tag == "h2":
            p = doc.add_heading(text, level=1)
            if p.runs:
                p.runs[0].font.color.rgb = RGBColor(0x02, 0x8A, 0x39)
        elif tag == "h3":
            doc.add_heading(text, level=2)
        elif tag == "p":
            doc.add_paragraph(text)
        elif tag == "li":
            doc.add_paragraph(text, style="List Bullet")
        elif tag == "table":
            rows = el.find_all("tr")
            if not rows:
                continue
            cols = max(len(r.find_all(["th", "td"])) for r in rows)
            if cols == 0:
                continue
            t = doc.add_table(rows=0, cols=cols)
            t.style = "Table Grid"
            for row in rows:
                cells = row.find_all(["th", "td"])
                row_cells = t.add_row().cells
                for j, cell in enumerate(cells[:cols]):
                    row_cells[j].text = cell.get_text(strip=True)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    safe = re.sub(r'[^\w\s-]', '', subject)[:50].strip().replace(' ', '_')
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="PhanTichThue_{safe}.docx"'},
    )

# ── Slides ────────────────────────────────────────────────────────────────────
@app.post("/slides")
async def generate_slides(request: Request, _user: str = Depends(auth)):
    body    = await request.json()
    html    = body.get("html", "")
    subject = body.get("subject", "Báo cáo")

    if not CLAUDE_KEY:
        raise HTTPException(503, "Claude API not configured")

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)[:8000]

    prompt = f"""Tạo bộ slides thuyết trình HTML hoàn chỉnh từ báo cáo phân tích thuế về: {subject}

Nội dung báo cáo:
{text}

YÊU CẦU:
- 8-12 slides: slide 1 là trang tiêu đề, mỗi slide sau cho 1 phần chính, slide cuối là khuyến nghị
- Mỗi slide: tiêu đề lớn + 4-6 bullet points súc tích
- Style: chuyên nghiệp, màu xanh #028a39, nền trắng/xám nhạt
- Navigation: nút Prev/Next + phím mũi tên ← →
- JavaScript thuần (không framework)
- Print: mỗi slide ra 1 trang A4 landscape (@media print)
- Font đủ lớn: h2 2rem, li 1.1rem
- Output: file HTML hoàn chỉnh từ <!DOCTYPE html> đến </html>
- KHÔNG dùng markdown hay backtick trong output"""

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4000,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        r = await client.post(
            f"{CLAUDE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {CLAUDE_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        slides_html = r.json()["choices"][0]["message"]["content"]

    # Strip markdown wrapper if present
    m = re.search(r'```html\s*(.*?)\s*```', slides_html, re.DOTALL)
    if m:
        slides_html = m.group(1)

    return {"slides_html": slides_html}

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health(_user: str = Depends(auth)):
    return {"status": "ok", "model": CLAUDE_MODEL}

# ── Frontend ──────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi" class="scroll-smooth">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tax Sector Research</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root{--brand:#028a39;--brand-dk:#016d2d;--bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--text:#1e293b;--muted:#64748b}
body.dark{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--muted:#94a3b8}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;transition:background .2s,color .2s}

/* Reading progress */
#reading-bar{position:fixed;top:0;left:0;height:3px;background:var(--brand);width:0;z-index:1000;transition:width .1s}

/* Section card */
.sec-card{background:var(--surface);border:1px solid var(--border);border-radius:.5rem;padding:.75rem;margin-bottom:.5rem;transition:opacity .2s}
.sec-card.off{opacity:.45}
.sub-chip{display:inline-flex;align-items:center;gap:.2rem;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:9999px;padding:.1rem .5rem;font-size:.75rem}
body.dark .sub-chip{background:#064e3b;border-color:#065f46}
.sub-chip button{color:#9ca3af;cursor:pointer;line-height:1;font-size:.85rem}
.sub-chip button:hover{color:#ef4444}

/* Report content */
#report-content h2{font-size:1.2rem;font-weight:700;color:var(--brand);margin:2rem 0 .75rem;border-bottom:2px solid var(--brand);padding-bottom:.25rem}
#report-content h3{font-size:1rem;font-weight:600;margin:1.25rem 0 .4rem}
#report-content p{margin:.5rem 0;line-height:1.75}
#report-content ul,#report-content ol{padding-left:1.5rem;margin:.5rem 0}
#report-content li{margin:.25rem 0}
#report-content table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.875rem;display:block;overflow-x:auto}
#report-content th{background:var(--brand);color:#fff;padding:.5rem .6rem;text-align:left}
#report-content td{padding:.4rem .6rem;border:1px solid var(--border)}
#report-content tr:nth-child(even) td{background:#f8fafc}
body.dark #report-content tr:nth-child(even) td{background:#162032}
#report-content a{color:var(--brand)}

/* Surface/border helpers */
.surface{background:var(--surface);border:1px solid var(--border)}
.btn{display:inline-flex;align-items:center;gap:.375rem;padding:.375rem .75rem;border-radius:.5rem;font-size:.875rem;font-weight:500;cursor:pointer;transition:background .15s}
.btn-gray{background:#f1f5f9;color:var(--text)}
.btn-gray:hover{background:#e2e8f0}
.btn-green{background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d}
.btn-green:hover{background:#dcfce7}
body.dark .btn-gray{background:#334155;color:var(--text)}
body.dark .btn-gray:hover{background:#475569}
body.dark .btn-green{background:#064e3b;border-color:#065f46;color:#6ee7b7}

/* Fade in */
.fade-in{animation:fi .25s ease}
@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* Print */
@media print{.no-print{display:none!important}#report-content{font-size:11pt}}

/* Input dark */
body.dark input,body.dark textarea,body.dark select{background:#1e293b;color:var(--text);border-color:var(--border)}
body.dark .sec-card input[type=text]{background:transparent}
</style>
</head>
<body>
<div id="reading-bar"></div>

<!-- ── Login Modal ──────────────────────────────────────────── -->
<div id="login-modal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
  <div class="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-sm mx-4">
    <div class="text-center mb-6">
      <div class="text-5xl mb-3">📊</div>
      <h1 class="text-2xl font-bold text-gray-800">Tax Research</h1>
      <p class="text-gray-400 text-sm mt-1">Phân tích thuế AI — Việt Nam</p>
    </div>
    <div class="space-y-3">
      <input id="li-user" type="text" placeholder="Tên đăng nhập" value="hoang"
        class="w-full border rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-green-400 text-gray-800">
      <input id="li-pass" type="password" placeholder="Mật khẩu"
        class="w-full border rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-green-400 text-gray-800"
        onkeydown="if(event.key==='Enter')doLogin()">
      <button onclick="doLogin()"
        class="w-full bg-green-600 hover:bg-green-700 text-white font-semibold py-2.5 rounded-lg transition">
        Đăng nhập
      </button>
      <p id="li-err" class="text-red-500 text-sm text-center hidden">Sai tên đăng nhập hoặc mật khẩu</p>
    </div>
  </div>
</div>

<!-- ── App Shell ─────────────────────────────────────────────── -->
<div id="app" class="max-w-4xl mx-auto px-4 py-5">

  <!-- Header -->
  <header class="flex items-center justify-between mb-5">
    <div class="flex items-center gap-3 cursor-pointer" onclick="newReport()">
      <span class="text-3xl">📊</span>
      <div>
        <h1 class="text-lg font-bold">Tax Sector Research</h1>
        <p class="text-xs" style="color:var(--muted)">Phân tích thuế AI — Việt Nam</p>
      </div>
    </div>
    <button onclick="toggleDark()" id="dark-btn" class="text-xl p-2 rounded-lg btn-gray">☀️</button>
  </header>

  <!-- ── SETUP PHASE ─────────────────────────────────────────── -->
  <div id="ph-setup">
    <!-- Tabs -->
    <div class="flex gap-2 mb-4">
      <button id="tab-sector" onclick="setMode('sector')"
        class="px-5 py-2 rounded-full text-sm font-medium transition bg-green-600 text-white">
        🏭 Ngành / Lĩnh vực
      </button>
      <button id="tab-company" onclick="setMode('company')"
        class="px-5 py-2 rounded-full text-sm font-medium transition bg-gray-100 text-gray-600 hover:bg-gray-200">
        🏢 Doanh nghiệp
      </button>
    </div>

    <!-- Subject input -->
    <div class="surface rounded-xl p-5 mb-4 shadow-sm">
      <label id="subj-label" class="block text-sm font-medium mb-2">Tên ngành / lĩnh vực:</label>
      <input id="subj-input" type="text"
        placeholder="VD: Bất động sản, Fintech, Sản xuất thép, Thương mại điện tử..."
        class="w-full border border-gray-200 rounded-lg px-4 py-3 text-lg focus:outline-none focus:ring-2 focus:ring-green-400"
        onkeydown="if(event.key==='Enter')startResearch()">
      <div class="flex items-center gap-5 mt-3">
        <span class="text-sm" style="color:var(--muted)">Research model:</span>
        <label class="flex items-center gap-1.5 cursor-pointer text-sm">
          <input type="radio" name="sonar" value="sonar" checked class="accent-green-600"> Sonar (nhanh)
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer text-sm">
          <input type="radio" name="sonar" value="sonar-pro" class="accent-green-600"> Sonar Pro (sâu)
        </label>
      </div>
    </div>

    <!-- Section editor -->
    <div class="surface rounded-xl p-5 mb-4 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <h2 class="font-semibold text-sm uppercase tracking-wide" style="color:var(--muted)">Cấu trúc báo cáo</h2>
        <div class="flex gap-2">
          <button onclick="resetSections()" class="btn btn-gray text-xs">↩ Đặt lại</button>
          <button onclick="addSection()" class="btn btn-green text-xs">+ Thêm phần</button>
        </div>
      </div>
      <div id="sections-list"></div>
    </div>

    <!-- Submit -->
    <button onclick="startResearch()"
      class="w-full bg-green-600 hover:bg-green-700 active:bg-green-800 text-white font-bold
             py-4 rounded-xl text-lg shadow-md transition">
      🔍 Bắt đầu phân tích
    </button>
    <p class="text-center text-xs mt-2" style="color:var(--muted)">Ước tính 2–5 phút tuỳ số lượng phần</p>
  </div>

  <!-- ── PROGRESS PHASE ──────────────────────────────────────── -->
  <div id="ph-progress" class="hidden">
    <div class="surface rounded-xl p-5 mb-4 shadow-sm">
      <div class="flex items-center gap-3 mb-4">
        <div class="animate-spin text-2xl select-none">⚙️</div>
        <div class="flex-1">
          <p id="prog-status" class="font-medium">Đang khởi động...</p>
          <p id="prog-subject" class="text-sm" style="color:var(--muted)"></p>
        </div>
        <button onclick="cancelResearch()" class="btn btn-gray text-xs text-red-500">✕ Huỷ</button>
      </div>
      <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div id="prog-bar" class="h-full bg-green-500 transition-all duration-500 rounded-full" style="width:0%"></div>
      </div>
      <div class="flex justify-between text-xs mt-1" style="color:var(--muted)">
        <span id="prog-label">Bắt đầu...</span>
        <span id="prog-pct">0%</span>
      </div>
    </div>
    <div id="step-list" class="space-y-2 mb-4"></div>
    <div id="partial-wrap" class="surface rounded-xl p-5 hidden">
      <p class="font-medium text-green-700 mb-3 text-sm">📝 Đang tạo báo cáo...</p>
      <div id="partial-body" class="text-sm overflow-y-auto max-h-80"></div>
    </div>
  </div>

  <!-- ── REPORT PHASE ────────────────────────────────────────── -->
  <div id="ph-report" class="hidden">
    <!-- Toolbar -->
    <div class="no-print flex flex-wrap items-center gap-2 mb-4 surface rounded-xl p-3 shadow-sm sticky top-2 z-40">
      <button onclick="window.print()" class="btn btn-gray">🖨️ In/PDF</button>
      <button id="btn-slides" onclick="doSlides()" class="btn btn-gray">📑 Slides</button>
      <button id="btn-docx" onclick="doDocx()" class="btn btn-gray">📄 Word</button>
      <button onclick="openReports()" class="btn btn-gray">📂 Báo cáo đã lưu</button>
      <div class="flex-1"></div>
      <button onclick="chgFont(-1)" class="btn btn-gray font-bold">A−</button>
      <button onclick="chgFont(1)"  class="btn btn-gray font-bold">A+</button>
      <button onclick="toggleDark()" id="dark-btn2" class="btn btn-gray">☀️</button>
      <button onclick="newReport()" class="btn btn-green">+ Mới</button>
    </div>

    <!-- Report card -->
    <div class="surface rounded-xl shadow-sm overflow-hidden">
      <!-- Header band -->
      <div class="bg-green-700 text-white px-6 py-5">
        <p class="text-green-300 text-xs uppercase tracking-widest font-medium">Báo cáo phân tích thuế</p>
        <h1 id="rpt-title" class="text-xl font-bold mt-1">—</h1>
        <p id="rpt-meta" class="text-green-300 text-xs mt-1"></p>
      </div>
      <!-- TOC -->
      <div id="toc-wrap" class="border-b px-6 py-3 bg-gray-50 hidden" style="background:var(--bg)">
        <p class="text-xs font-semibold uppercase tracking-wide mb-2" style="color:var(--muted)">Mục lục</p>
        <div id="toc-list" class="space-y-0.5"></div>
      </div>
      <!-- Content -->
      <div id="report-content" class="px-8 py-6" style="font-size:16px"></div>
      <!-- Sources -->
      <div id="src-wrap" class="border-t px-6 py-4 hidden" style="background:var(--bg)">
        <button onclick="toggleSrc()" class="text-sm font-semibold flex items-center gap-2" style="color:var(--muted)">
          <span id="src-arrow">▶</span> Nguồn tham khảo (<span id="src-count">0</span>)
        </button>
        <div id="src-list" class="hidden mt-2 space-y-1"></div>
      </div>
    </div>
  </div>
</div><!-- /app -->

<!-- ── Reports Modal ─────────────────────────────────────────── -->
<div id="modal-reports" class="fixed inset-0 bg-black/50 z-50 hidden flex items-center justify-center">
  <div class="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 max-h-[80vh] flex flex-col"
       style="background:var(--surface);color:var(--text)">
    <div class="p-5 border-b flex items-center justify-between" style="border-color:var(--border)">
      <h2 class="font-bold">📂 Báo cáo đã lưu</h2>
      <button onclick="closeModal('modal-reports')" class="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
    </div>
    <div id="reports-list" class="flex-1 overflow-y-auto p-4 space-y-2"></div>
  </div>
</div>

<!-- ── Slides Modal ──────────────────────────────────────────── -->
<div id="modal-slides" class="fixed inset-0 bg-black/80 z-50 hidden flex items-center justify-center">
  <div class="bg-white rounded-2xl shadow-2xl w-full max-w-4xl mx-4 flex flex-col" style="height:85vh">
    <div class="p-4 border-b flex items-center justify-between shrink-0">
      <h2 class="font-bold text-gray-800">📑 Trình chiếu</h2>
      <button onclick="closeModal('modal-slides')" class="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
    </div>
    <iframe id="slides-frame" class="flex-1 w-full rounded-b-2xl" src="about:blank"></iframe>
  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────
let AUTH = '';
let mode = 'sector';
let sections = [];
let reportHtml = '';
let citations = [];
let currentFile = null;
let fontSize = 16;
let dark = false;
let abortCtrl = null;

// ── Auth ──────────────────────────────────────────────────────
async function doLogin() {
  const u = document.getElementById('li-user').value.trim();
  const p = document.getElementById('li-pass').value.trim();
  AUTH = 'Basic ' + btoa(u + ':' + p);
  try {
    const r = await fetch('/health', {headers: {Authorization: AUTH}});
    if (r.ok) {
      document.getElementById('login-modal').classList.add('hidden');
      init();
    } else {
      document.getElementById('li-err').classList.remove('hidden');
      AUTH = '';
    }
  } catch(e) {
    document.getElementById('li-err').classList.remove('hidden');
    AUTH = '';
  }
}

// ── Init ──────────────────────────────────────────────────────
async function init() {
  await loadSections();
}

// ── Mode ──────────────────────────────────────────────────────
function setMode(m) {
  mode = m;
  const on  = 'px-5 py-2 rounded-full text-sm font-medium transition bg-green-600 text-white';
  const off = 'px-5 py-2 rounded-full text-sm font-medium transition bg-gray-100 text-gray-600 hover:bg-gray-200';
  document.getElementById('tab-sector').className  = m === 'sector'  ? on : off;
  document.getElementById('tab-company').className = m === 'company' ? on : off;
  document.getElementById('subj-label').textContent = m === 'sector'
    ? 'Tên ngành / lĩnh vực cần phân tích:' : 'Tên công ty cần phân tích:';
  document.getElementById('subj-input').placeholder = m === 'sector'
    ? 'VD: Bất động sản, Fintech, Sản xuất thép...' : 'VD: Vinamilk, FPT, Masan Group...';
  loadSections();
}

// ── Sections ──────────────────────────────────────────────────
async function loadSections() {
  const r = await fetch('/default-sections?mode=' + mode, {headers: {Authorization: AUTH}});
  sections = await r.json();
  renderSections();
}

function resetSections() { loadSections(); }

function renderSections() {
  const el = document.getElementById('sections-list');
  el.innerHTML = '';
  sections.forEach((s, i) => el.appendChild(makeCard(s, i)));
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function makeCard(sec, i) {
  const div = document.createElement('div');
  div.className = 'sec-card' + (sec.enabled ? '' : ' off');
  div.dataset.id = sec.id;

  const chips = sec.sub.map((s, j) => `<span class="sub-chip">${esc(s)}<button onclick="rmSub('${sec.id}',${j})">✕</button></span>`).join('');

  div.innerHTML = `
    <div class="flex items-center gap-2 mb-2">
      <input type="checkbox" ${sec.enabled ? 'checked' : ''} class="accent-green-600 w-4 h-4 cursor-pointer"
        onchange="togSec('${sec.id}',this.checked)">
      <input type="text" value="${esc(sec.title)}"
        class="flex-1 font-medium text-sm border-0 focus:outline-none focus:ring-1 focus:ring-green-300 rounded px-1"
        style="background:transparent"
        onblur="updTitle('${sec.id}',this.value)">
      <button onclick="suggestSubs('${sec.id}')" class="text-xs px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-50" style="color:var(--muted)" title="AI gợi ý chủ đề con">✨</button>
      <button onclick="rmSec('${sec.id}')" class="text-gray-300 hover:text-red-400 text-sm px-1">✕</button>
    </div>
    <div class="flex flex-wrap gap-1 ml-6">
      ${chips}
      <button onclick="addSub('${sec.id}')"
        class="text-xs px-2 py-0.5 rounded-full border border-dashed border-gray-300 hover:border-green-400 hover:text-green-600 transition"
        style="color:var(--muted)">+ thêm</button>
    </div>`;
  return div;
}

function togSec(id, enabled) {
  const s = sections.find(x => x.id === id);
  if (s) {
    s.enabled = enabled;
    const card = document.querySelector(`[data-id="${id}"]`);
    if (card) card.className = 'sec-card' + (enabled ? '' : ' off');
  }
}

function updTitle(id, t) {
  const s = sections.find(x => x.id === id);
  if (s) s.title = t;
}

function rmSec(id) {
  sections = sections.filter(s => s.id !== id);
  renderSections();
}

function addSection() {
  const id = 's' + Date.now();
  sections.push({id, title: 'Phần mới', sub: [], enabled: true});
  renderSections();
  setTimeout(() => {
    const inp = document.querySelector(`[data-id="${id}"] input[type="text"]`);
    if (inp) { inp.focus(); inp.select(); }
  }, 50);
}

function rmSub(secId, idx) {
  const s = sections.find(x => x.id === secId);
  if (s) { s.sub.splice(idx, 1); renderSections(); }
}

function addSub(secId) {
  const name = prompt('Nhập tên chủ đề con:');
  if (name && name.trim()) {
    const s = sections.find(x => x.id === secId);
    if (s) { s.sub.push(name.trim()); renderSections(); }
  }
}

async function suggestSubs(secId) {
  const s = sections.find(x => x.id === secId);
  if (!s) return;
  const subject = document.getElementById('subj-input').value.trim() || '(chưa nhập)';
  const r = await fetch('/suggest-subsections', {
    method: 'POST',
    headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
    body: JSON.stringify({title: s.title, subject})
  });
  const {suggestions} = await r.json();
  if (suggestions && suggestions.length) {
    suggestions.forEach(sg => { if (!s.sub.includes(sg)) s.sub.push(sg); });
    renderSections();
  }
}

// ── Research ──────────────────────────────────────────────────
async function startResearch() {
  const subject = document.getElementById('subj-input').value.trim();
  if (!subject) { alert('Vui lòng nhập tên ngành hoặc công ty'); return; }
  const enabled = sections.filter(s => s.enabled);
  if (!enabled.length) { alert('Vui lòng bật ít nhất một phần'); return; }

  const sonar = document.querySelector('input[name="sonar"]:checked').value;
  showPhase('progress');
  document.getElementById('prog-subject').textContent = subject;
  reportHtml = '';
  citations = [];
  currentFile = null;
  document.getElementById('step-list').innerHTML = '';
  document.getElementById('partial-body').innerHTML = '';
  document.getElementById('partial-wrap').classList.add('hidden');

  abortCtrl = new AbortController();

  try {
    const res = await fetch('/stream', {
      method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({subject, mode, sections, sonar_model: sonar}),
      signal: abortCtrl.signal,
    });

    if (!res.ok) { showErr('Lỗi server: ' + res.status); return; }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { handleEvt(JSON.parse(line.slice(6)), subject); } catch(e) {}
        }
      }
    }
  } catch(e) {
    if (e.name !== 'AbortError') showErr('Lỗi kết nối: ' + e.message);
  }
}

function cancelResearch() {
  if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
  showPhase('setup');
}

function handleEvt(evt, subject) {
  switch (evt.type) {
    case 'status':
      document.getElementById('prog-status').textContent = evt.message;
      break;
    case 'progress': {
      const pct = Math.round(evt.step / evt.total * 100);
      document.getElementById('prog-bar').style.width = pct + '%';
      document.getElementById('prog-pct').textContent = pct + '%';
      document.getElementById('prog-label').textContent = evt.label || '';
      const item = document.createElement('div');
      item.className = 'flex items-center gap-2 text-sm surface rounded-lg px-3 py-2 fade-in';
      item.innerHTML = '<span class="text-green-500">✓</span> ' + esc(evt.label || '');
      document.getElementById('step-list').appendChild(item);
      item.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      break;
    }
    case 'ai_start':
      document.getElementById('prog-status').textContent = 'AI đang viết báo cáo...';
      document.getElementById('partial-wrap').classList.remove('hidden');
      break;
    case 'chunk':
      reportHtml += evt.text;
      document.getElementById('partial-body').innerHTML += evt.text;
      break;
    case 'citations':
      citations = citations.concat(evt.urls);
      break;
    case 'done':
      currentFile = evt.filename;
      finishReport(subject);
      break;
    case 'error':
      showErr(evt.message);
      break;
  }
}

function finishReport(subject) {
  showPhase('report');
  document.getElementById('rpt-title').textContent = 'Phân Tích Thuế — ' + subject;
  document.getElementById('rpt-meta').textContent =
    'Ngày tạo: ' + new Date().toLocaleDateString('vi-VN') +
    (currentFile ? ' · Đã lưu: ' + currentFile : '');

  const content = document.getElementById('report-content');
  content.innerHTML = reportHtml;
  content.style.fontSize = fontSize + 'px';

  buildTOC();
  buildSources();
  setupScroll();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

// ── TOC ───────────────────────────────────────────────────────
function buildTOC() {
  const h2s = document.getElementById('report-content').querySelectorAll('h2');
  if (h2s.length < 2) return;
  const list = document.getElementById('toc-list');
  list.innerHTML = '';
  h2s.forEach((h, i) => {
    h.id = 'sec-' + i;
    const a = document.createElement('a');
    a.href = '#sec-' + i;
    a.className = 'block text-sm py-0.5 hover:underline';
    a.style.color = 'var(--brand)';
    a.textContent = h.textContent;
    a.onclick = e => { e.preventDefault(); h.scrollIntoView({behavior: 'smooth'}); };
    list.appendChild(a);
  });
  document.getElementById('toc-wrap').classList.remove('hidden');
}

// ── Sources ───────────────────────────────────────────────────
function buildSources() {
  const unique = [...new Set(citations)];
  if (!unique.length) return;
  const list = document.getElementById('src-list');
  list.innerHTML = '';
  unique.forEach((url, i) => {
    const d = document.createElement('div');
    d.className = 'text-xs';
    d.style.color = 'var(--muted)';
    d.innerHTML = `[${i+1}] <a href="${esc(url)}" target="_blank" class="hover:underline" style="color:var(--brand)">${esc(url)}</a>`;
    list.appendChild(d);
  });
  document.getElementById('src-count').textContent = unique.length;
  document.getElementById('src-wrap').classList.remove('hidden');
}

function toggleSrc() {
  const list = document.getElementById('src-list');
  const hidden = list.classList.toggle('hidden');
  document.getElementById('src-arrow').textContent = hidden ? '▶' : '▼';
}

// ── Scroll progress ───────────────────────────────────────────
function setupScroll() {
  window.addEventListener('scroll', () => {
    const d = document.documentElement;
    const pct = d.scrollTop / (d.scrollHeight - d.clientHeight);
    document.getElementById('reading-bar').style.width = (pct * 100) + '%';
  });
}

// ── Toolbar ───────────────────────────────────────────────────
function chgFont(delta) {
  fontSize = Math.max(12, Math.min(22, fontSize + delta));
  document.getElementById('report-content').style.fontSize = fontSize + 'px';
}

function toggleDark() {
  dark = !dark;
  document.body.classList.toggle('dark', dark);
  const icon = dark ? '🌙' : '☀️';
  document.getElementById('dark-btn').textContent = icon;
  const b2 = document.getElementById('dark-btn2');
  if (b2) b2.textContent = icon;
}

async function doSlides() {
  if (!reportHtml) return;
  const subject = document.getElementById('rpt-title').textContent.replace('Phân Tích Thuế — ', '');
  const btn = document.getElementById('btn-slides');
  btn.textContent = '⏳ Đang tạo...';
  btn.disabled = true;
  try {
    const r = await fetch('/slides', {
      method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({html: reportHtml, subject}),
    });
    if (r.ok) {
      const {slides_html} = await r.json();
      document.getElementById('slides-frame').srcdoc = slides_html;
      openModal('modal-slides');
    } else {
      alert('Không thể tạo slides');
    }
  } catch(e) { alert('Lỗi: ' + e.message); }
  finally { btn.textContent = '📑 Slides'; btn.disabled = false; }
}

async function doDocx() {
  if (!reportHtml) return;
  const subject = document.getElementById('rpt-title').textContent.replace('Phân Tích Thuế — ', '');
  const btn = document.getElementById('btn-docx');
  btn.textContent = '⏳ Đang xuất...';
  btn.disabled = true;
  try {
    const r = await fetch('/docx', {
      method: 'POST',
      headers: {Authorization: AUTH, 'Content-Type': 'application/json'},
      body: JSON.stringify({html: reportHtml, subject}),
    });
    if (r.ok) {
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = (currentFile || subject).replace('.html', '') + '.docx';
      a.click();
      URL.revokeObjectURL(url);
    } else {
      alert('Không thể xuất Word');
    }
  } catch(e) { alert('Lỗi: ' + e.message); }
  finally { btn.textContent = '📄 Word'; btn.disabled = false; }
}

// ── Reports modal ─────────────────────────────────────────────
async function openReports() {
  openModal('modal-reports');
  const list = document.getElementById('reports-list');
  list.innerHTML = '<p class="text-sm text-center py-4" style="color:var(--muted)">Đang tải...</p>';
  try {
    const r = await fetch('/reports', {headers: {Authorization: AUTH}});
    const rpts = await r.json();
    if (!rpts.length) {
      list.innerHTML = '<p class="text-sm text-center py-4" style="color:var(--muted)">Chưa có báo cáo nào</p>';
      return;
    }
    list.innerHTML = '';
    rpts.forEach(rpt => {
      const div = document.createElement('div');
      div.className = 'flex items-center gap-2 p-3 rounded-lg border fade-in';
      div.style.borderColor = 'var(--border)';
      div.innerHTML = `
        <div class="flex-1 min-w-0">
          <p class="font-medium text-sm truncate">${esc(rpt.name)}</p>
          <p class="text-xs" style="color:var(--muted)">${rpt.date} · ${rpt.size}</p>
        </div>
        <button onclick="loadSavedReport('${esc(rpt.name)}')" class="btn btn-green text-xs shrink-0">📂 Mở</button>
        <a href="/report/${encodeURIComponent(rpt.name)}" target="_blank"
           class="btn btn-gray text-xs shrink-0">↗</a>
        <button onclick="delReport('${esc(rpt.name)}',this)" class="btn text-xs shrink-0 text-red-400 hover:bg-red-50">🗑</button>`;
      list.appendChild(div);
    });
  } catch(e) {
    list.innerHTML = '<p class="text-sm text-center py-4 text-red-500">Lỗi tải danh sách</p>';
  }
}

async function loadSavedReport(name) {
  closeModal('modal-reports');
  try {
    const r = await fetch('/report/' + encodeURIComponent(name), {headers: {Authorization: AUTH}});
    const html = await r.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const body = doc.getElementById('report-body');
    reportHtml = body ? body.innerHTML : doc.body.innerHTML;
    currentFile = name;
    citations = [];

    // Try to extract title
    const h1 = doc.querySelector('h1');
    const subject = h1 ? h1.textContent.replace('Phan Tich Thue — ', '').replace('Phân Tích Thuế — ', '') : name;

    showPhase('report');
    document.getElementById('rpt-title').textContent = 'Phân Tích Thuế — ' + subject;
    document.getElementById('rpt-meta').textContent = 'Đã lưu: ' + name;
    document.getElementById('report-content').innerHTML = reportHtml;
    document.getElementById('report-content').style.fontSize = fontSize + 'px';
    document.getElementById('toc-wrap').classList.add('hidden');
    document.getElementById('src-wrap').classList.add('hidden');
    buildTOC();
    setupScroll();
    window.scrollTo({top: 0, behavior: 'smooth'});
  } catch(e) { alert('Không thể tải báo cáo: ' + e.message); }
}

async function delReport(name, btn) {
  if (!confirm('Xóa báo cáo "' + name + '"?')) return;
  try {
    const r = await fetch('/report/' + encodeURIComponent(name), {
      method: 'DELETE', headers: {Authorization: AUTH}
    });
    if (r.ok) btn.closest('.flex').remove();
    else alert('Không thể xóa');
  } catch(e) { alert('Lỗi: ' + e.message); }
}

function newReport() {
  if (currentFile || reportHtml) {
    if (!confirm('Bắt đầu báo cáo mới? Báo cáo hiện tại vẫn được lưu.')) return;
  }
  showPhase('setup');
  reportHtml = ''; currentFile = null; citations = [];
  document.getElementById('step-list').innerHTML = '';
  document.getElementById('partial-body').innerHTML = '';
  document.getElementById('report-content').innerHTML = '';
  document.getElementById('toc-wrap').classList.add('hidden');
  document.getElementById('src-wrap').classList.add('hidden');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

// ── Helpers ───────────────────────────────────────────────────
function showPhase(p) {
  ['setup','progress','report'].forEach(x =>
    document.getElementById('ph-' + x).classList.toggle('hidden', x !== p));
}

function showErr(msg) {
  document.getElementById('prog-status').textContent = '❌ ' + msg;
  document.getElementById('prog-bar').style.background = '#ef4444';
}

function openModal(id)  { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// Close modal on backdrop click
document.querySelectorAll('[id^="modal-"]').forEach(m =>
  m.addEventListener('click', e => { if (e.target === m) closeModal(m.id); }));

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') ['modal-reports','modal-slides'].forEach(closeModal);
});
</script>
</body>
</html>"""

# ── Serve frontend ────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(HTML_PAGE)
