from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# Claude via httpx directly (no SDK timeout issues)
from io import BytesIO
try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_OK = True
    print("[DOCX] python-docx imported successfully")
except ImportError:
    print("[DOCX] python-docx not found, attempting install...")
    try:
        import subprocess as _pip_sp
        _pip_sp.run(["pip", "install", "python-docx", "-q"], check=True, timeout=60)
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        DOCX_OK = True
        print("[DOCX] python-docx installed and imported")
    except Exception as e:
        print(f"[DOCX] Installation failed: {e}")
        DOCX_OK = False

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False
import httpx
import asyncio
import json
import os
import re
import secrets
import subprocess
import shutil
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
    PSYCOPG2_OK = True
except ImportError:
    PSYCOPG2_OK = False

try:
    from passlib.context import CryptContext
    PASSLIB_OK = True
except ImportError:
    PASSLIB_OK = False

try:
    from jose import JWTError, jwt
    JOSE_OK = True
except ImportError:
    JOSE_OK = False

app = FastAPI(title="Tax Sector Research Tool")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "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")
CLAUDIBLE_API_KEY  = os.getenv("CLAUDIBLE_API_KEY", "")
CLAUDIBLE_BASE_URL = os.getenv("CLAUDIBLE_BASE_URL", "https://claudible.io/v1")
CLAUDIBLE_MODEL    = os.getenv("CLAUDIBLE_MODEL", "claude-sonnet-4.6")
CLAUDIBLE_ENDPOINT = CLAUDIBLE_BASE_URL.rstrip("/") + "/chat/completions"
APP_PASSWORD       = os.getenv("APP_PASSWORD", "taxsector2026")
APP_USERNAME       = os.getenv("APP_USERNAME", "hoang")
GDRIVE_FOLDER      = "Thanh-AI/TaxResearch"
REPORTS_DIR        = Path("/app/reports")
REPORTS_DIR.mkdir(exist_ok=True)

# ─── DB / JWT config ──────────────────────────────────────────────────────────
DB_HOST    = os.getenv("DB_HOST", "postgresql-pgwo0w8g0c0ccg840kw84gs8")
DB_PORT    = int(os.getenv("DB_PORT", "5432"))
DB_NAME    = os.getenv("DB_NAME", "sectortax")
DB_USER    = os.getenv("DB_USER", "sectortax_user")
DB_PASS    = os.getenv("DB_PASS", "SectorTax2026Secure")
JWT_SECRET = os.getenv("JWT_SECRET", "sectortax-jwt-secret-change-in-prod")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") if PASSLIB_OK else None
db_pool: "ThreadedConnectionPool | None" = None

@app.on_event("startup")
async def startup():
    global db_pool
    if PSYCOPG2_OK:
        try:
            db_pool = ThreadedConnectionPool(1, 10,
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASS,
                connect_timeout=5)
            print("[DB] Connection pool created")
            # Seed admin user if not exists
            _seed_admin_user()
        except Exception as e:
            print(f"[DB] Connection failed (fallback to env auth): {e}")

    # Check rclone for GDrive backup
    try:
        result = subprocess.run(["rclone", "version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            print("[RCLONE] Available for GDrive backup")
        else:
            print("[RCLONE] Not configured or unavailable")
    except Exception as e:
        print(f"[RCLONE] Check failed: {e}")

def _seed_admin_user():
    """Ensure admin user (hoang) exists in DB with a valid bcrypt hash."""
    if not db_pool or not pwd_context:
        return
    admin_user = os.getenv("APP_USERNAME", "hoang")
    admin_pass = os.getenv("APP_PASSWORD", "taxsector2026")
    conn = None
    try:
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username=%s", (admin_user,))
            if not cur.fetchone():
                hashed = pwd_context.hash(admin_pass)
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, plan, is_active) "
                    "VALUES (%s, %s, %s, 'admin', true) ON CONFLICT (username) DO NOTHING",
                    (admin_user, f"{admin_user}@sectortax.local", hashed)
                )
                conn.commit()
                print(f"[DB] Seeded admin user: {admin_user}")
            else:
                # Update hash in case passlib version changed
                hashed = pwd_context.hash(admin_pass)
                cur.execute(
                    "UPDATE users SET password_hash=%s WHERE username=%s",
                    (hashed, admin_user)
                )
                conn.commit()
    except Exception as e:
        print(f"[DB] Seed admin failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            release_db_conn(conn)

def get_db_conn():
    if db_pool:
        return db_pool.getconn()
    return None

def release_db_conn(conn):
    if db_pool and conn:
        db_pool.putconn(conn)

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

def build_report_system_prompt() -> str:
    now = datetime.now()
    year = now.year
    prev_year = year - 1
    two_years_ago = year - 2
    return f"""Bạn là chuyên gia tư vấn thuế cao cấp tại Việt Nam với 30 năm kinh nghiệm Big 4.
Viết báo cáo phân tích thuế chuyên sâu dựa trên dữ liệu nghiên cứu được cung cấp.

Thời điểm báo cáo: {now.strftime("%m/%Y")}

Yêu cầu:
- Tiếng Việt, chuyên nghiệp, Big 4 style
- Độ dài 10-15 trang A4
- Tập trung vào văn bản pháp luật ĐANG HIỆU LỰC tại thời điểm {now.strftime("%m/%Y")}
- Ưu tiên văn bản ban hành trong {two_years_ago}-{year}. Nếu văn bản cũ hơn vẫn còn hiệu lực và không bị thay thế, vẫn đề cập nhưng ghi rõ năm ban hành
- KHÔNG tự suy đoán hoặc bịa đặt số hiệu văn bản. Chỉ nêu văn bản có trong dữ liệu nghiên cứu
- Dẫn nguồn: số Thông tư, Nghị định, Công văn cụ thể kèm năm ban hành

OUTPUT FORMAT — BẮT BUỘC:
- CHỈ dùng HTML: h2 h3 p ul ol li strong em table thead tbody tr th td
- TUYỆT ĐỐI KHÔNG dùng markdown (**, ##, *, ---, ```, |---|)
- Bullet points nhiều cấp: dùng <ul><li> lồng nhau (<ul> trong <li>) để thể hiện indent
- Bảng: dùng <table><thead><tr><th>...</th></tr></thead><tbody>...</tbody></table>
- KHÔNG có text ngoài các phần được yêu cầu
- Bắt đầu NGAY bằng thẻ h2 đầu tiên"""

# ─── Auth ─────────────────────────────────────────────────────────────────────

def _create_jwt(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_jwt(token: str) -> dict | None:
    if not JOSE_OK:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

def _db_get_user(username: str) -> dict | None:
    conn = get_db_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, plan, is_active FROM users WHERE username=%s",
                (username,)
            )
            row = cur.fetchone()
            if row:
                return {"id": row[0], "username": row[1], "email": row[2],
                        "password_hash": row[3], "plan": row[4], "is_active": row[5]}
            return None
    except Exception:
        return None
    finally:
        release_db_conn(conn)

def _db_get_user_by_id(user_id: int) -> dict | None:
    conn = get_db_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, plan, is_active FROM users WHERE id=%s",
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                return {"id": row[0], "username": row[1], "email": row[2],
                        "plan": row[3], "is_active": row[4]}
            return None
    except Exception:
        return None
    finally:
        release_db_conn(conn)

def _verify_password(plain: str, hashed: str) -> bool:
    if pwd_context:
        try:
            return pwd_context.verify(plain, hashed)
        except Exception:
            return False
    return False

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Validate JWT token and return user dict."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("username")
        if not username:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})

    # Try DB first
    if db_pool:
        conn = None
        try:
            conn = db_pool.getconn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, plan FROM users WHERE username=%s AND is_active=true",
                    (username,)
                )
                row = cur.fetchone()
                if row:
                    return {"id": row[0], "username": row[1], "plan": row[2]}
        except Exception:
            pass
        finally:
            if conn:
                release_db_conn(conn)

    # Fallback: env var user
    env_user = os.getenv("APP_USERNAME", "hoang")
    if username == env_user:
        return {"id": 0, "username": username, "plan": "admin"}

    raise HTTPException(401, "User not found",
                        headers={"WWW-Authenticate": "Bearer"})

# ─── Markdown → HTML ──────────────────────────────────────────────────────────
def inline_md(text: str) -> str:
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__',          r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*',          r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`',            r'<code>\1</code>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', text)
    return text

def parse_pipe_table(lines: list) -> str:
    rows = []
    for line in lines:
        if re.match(r'^\|[-:\s|]+\|$', line.strip()):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)
    if not rows:
        return ""
    html = '<table><thead><tr>' + ''.join(f'<th>{inline_md(c)}</th>' for c in rows[0]) + '</tr></thead><tbody>'
    for row in rows[1:]:
        html += '<tr>' + ''.join(f'<td>{inline_md(c)}</td>' for c in row) + '</tr>'
    return html + '</tbody></table>'

def md_to_html(text: str) -> str:
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if '|' in stripped and stripped.startswith('|'):
            tbl = []
            while i < len(lines) and '|' in lines[i].strip() and lines[i].strip().startswith('|'):
                tbl.append(lines[i].strip())
                i += 1
            result.append(parse_pipe_table(tbl))
            continue
        m = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if m:
            lv = len(m.group(1))
            result.append(f'<h{min(lv,3)}>{inline_md(m.group(2))}</h{min(lv,3)}>')
            i += 1; continue
        if re.match(r'^[-*•]\s+', stripped):
            result.append('<ul>')
            while i < len(lines) and re.match(r'^[-*•]\s+', lines[i].strip()):
                item = re.sub(r'^[-*•]\s+', '', lines[i].strip())
                result.append(f'<li>{inline_md(item)}</li>')
                i += 1
            result.append('</ul>')
            continue
        if re.match(r'^\d+[.)]\s+', stripped):
            result.append('<ol>')
            while i < len(lines) and re.match(r'^\d+[.)]\s+', lines[i].strip()):
                item = re.sub(r'^\d+[.)] ', '', lines[i].strip())
                result.append(f'<li>{inline_md(item)}</li>')
                i += 1
            result.append('</ol>')
            continue
        if not stripped: i += 1; continue
        if re.match(r'^<[a-zA-Z/]', stripped): result.append(stripped); i += 1; continue
        result.append(f'<p>{inline_md(stripped)}</p>')
        i += 1
    return '\n'.join(result)

def clean_html(text: str) -> str:
    text = re.sub(r'```html\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = re.sub(r'^(#{1,6})\s+(.+)$',
                  lambda m: f'<h{min(len(m.group(1)),3)}>{m.group(2)}</h{min(len(m.group(1)),3)}>',
                  text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and line.strip().startswith('|') and not line.strip().startswith('<'):
            tbl = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip().startswith('|'):
                tbl.append(lines[i])
                i += 1
            result.append(parse_pipe_table(tbl))
            continue
        result.append(line)
        i += 1
    return '\n'.join(result)

# ─── Perplexity ───────────────────────────────────────────────────────────────
async def perplexity_search(query: str, client: httpx.AsyncClient, report_date: datetime,
                            recency: str = "month") -> dict:
    """
    recency: "month" | "year" | None
    - "month": tin tức/số liệu mới nhất (thị trường, big players, M&A)
    - "year": văn bản pháp luật mới ban hành gần đây
    - None: không filter — dùng cho query văn bản nền tảng đang hiệu lực
    """
    year = report_date.year
    prev_year = year - 1
    payload = {
        "model": "sonar-pro",   # dùng sonar-pro cho legal queries để chính xác hơn
        "messages": [
            {"role": "system", "content": (
                f"Chuyên gia nghiên cứu pháp luật và thuế Việt Nam. "
                f"Thời điểm tham chiếu: {report_date.strftime('%m/%Y')}. "
                f"Liệt kê đầy đủ, chính xác số hiệu văn bản (Luật, Nghị định, Thông tư, Công văn) kèm năm ban hành. "
                f"KHÔNG suy đoán — chỉ nêu những gì có căn cứ từ nguồn đáng tin cậy. "
                f"Với văn bản pháp luật: nêu rõ văn bản nào đang hiệu lực, văn bản nào đã bị thay thế/sửa đổi."
            )},
            {"role": "user", "content": query}
        ],
        "max_tokens": 3000,
        "temperature": 0.1,
        "return_citations": True,
    }
    if recency:
        payload["search_recency_filter"] = recency

    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        r = await client.post(PERPLEXITY_URL, json=payload, headers=headers, timeout=90.0)
        r.raise_for_status()
        d = r.json()
        return {"content": d["choices"][0]["message"]["content"], "citations": d.get("citations", []), "success": True}
    except Exception as e:
        return {"content": f"Lỗi: {e}", "citations": [], "success": False}

# ─── Default section templates ────────────────────────────────────────────────
DEFAULT_SECTOR_SECTIONS = [
    {
        "id": "overview", "title": "Tổng quan về ngành",
        "sub": ["Quy mô thị trường, doanh thu toàn ngành (số liệu 2024-2026)", "Đặc điểm kinh doanh, mô hình doanh thu", "Chuỗi cung ứng upstream / downstream"]
    },
    {
        "id": "market", "title": "Thị trường & Big Players",
        "sub": ["Tăng trưởng ngành 2020-2025 và dự báo 2030", "Top doanh nghiệp lớn nhất (tên, doanh thu, thị phần)", "FDI trong ngành, xu hướng M&A"]
    },
    {
        "id": "legal", "title": "Quy định pháp lý quan trọng",
        "sub": ["Luật chuyên ngành (số hiệu, năm ban hành, bản mới nhất)", "Nghị định & Thông tư hướng dẫn quan trọng nhất", "Điều kiện kinh doanh, giấy phép đặc thù", "Hạn chế đầu tư nước ngoài (nếu có)"]
    },
    {
        "id": "tax", "title": "Phân tích các loại thuế áp dụng",
        "sub": ["Thuế TNDN: thuế suất, ưu đãi đặc thù (văn bản 2024-2026)", "Thuế GTGT: thuế suất đặc thù từng sản phẩm/dịch vụ", "Thuế Nhà thầu (FCT): khi nào phát sinh, thuế suất", "Thuế TTĐB (nếu có): đối tượng chịu thuế, thuế suất", "Thuế XNK: MFN, ưu đãi FTA CPTPP/EVFTA/RCEP", "Phí và thuế khác đặc thù ngành"]
    },
    {
        "id": "tax_deep", "title": "Công văn hướng dẫn & Tranh chấp thuế",
        "sub": ["Công văn của Tổng cục Thuế / Cục Thuế hướng dẫn thuế ngành (số hiệu, nội dung)", "Các vụ thanh tra, truy thu, tranh chấp thuế nổi bật trong ngành", "Vấn đề thường gặp khi quyết toán: marketing, hoa hồng, royalty, chuyển giá"]
    },
    {
        "id": "issues", "title": "Vấn đề thuế đặc thù của ngành",
        "sub": ["Nhận dạng và ghi nhận doanh thu: rủi ro, tranh chấp", "Chi phí được trừ / không được trừ đặc thù ngành", "Chuyển lỗ, ưu đãi thuế: điều kiện và rủi ro mất ưu đãi", "Hoá đơn chứng từ: rủi ro đặc thù", "Khấu trừ tại nguồn: thuế TNCN, thuế nhà thầu", "Chuyển giá (transfer pricing) với giao dịch liên kết"]
    },
    {
        "id": "international", "title": "Thông lệ & Vấn đề thuế quốc tế",
        "sub": ["Thông lệ thuế quốc tế cho ngành (Singapore, Thái Lan, Malaysia)", "Tác động BEPS 2.0 / Pillar Two (thuế tối thiểu toàn cầu 15%)", "Rủi ro PE (permanent establishment) phổ biến"]
    },
]

DEFAULT_COMPANY_SECTIONS = [
    {
        "id": "co_overview", "title": "Tổng quan về công ty & các sector hoạt động",
        "sub": ["Lịch sử, quy mô, cơ cấu pháp lý (TNHH/CP/FDI/JV)", "Các ngành/sector mà công ty đang hoạt động", "Doanh thu, lợi nhuận, nhân sự (số liệu mới nhất)"]
    },
    {
        "id": "co_sector_char", "title": "Đặc thù từng sector của công ty",
        "sub": ["Doanh thu & chi phí của từng sector tạo ra từ đâu", "Chuỗi cung ứng upstream/downstream từng sector", "Đặc thù riêng của công ty so với ngành"]
    },
    {
        "id": "co_growth", "title": "Sự phát triển của công ty & cạnh tranh",
        "sub": ["Lịch sử phát triển và milestones quan trọng", "Vị trí thị trường, thị phần từng sector", "Đối thủ cạnh tranh chính trong từng sector", "Kế hoạch và xu hướng phát triển 2025-2030"]
    },
    {
        "id": "co_legal", "title": "Quy định pháp lý áp dụng cho công ty",
        "sub": ["Luật & Nghị định áp dụng cho từng sector công ty hoạt động (văn bản mới nhất 2024-2026)", "Điều kiện kinh doanh & giấy phép đặc thù", "Hạn chế FDI, cơ cấu sở hữu nước ngoài"]
    },
    {
        "id": "co_tax", "title": "Phân tích thuế áp dụng cho từng sector của công ty",
        "sub": ["Thuế TNDN: thuế suất, ưu đãi đang hưởng, điều kiện (văn bản 2024-2026)", "Thuế GTGT: thuế suất đặc thù sản phẩm/dịch vụ của công ty", "Thuế Nhà thầu, TTĐB, XNK áp dụng", "Giao dịch liên kết: royalty, phí quản lý, vay nội bộ"]
    },
    {
        "id": "co_tax_issues", "title": "Vấn đề thuế đặc thù của công ty",
        "sub": ["Vấn đề thuế đặc thù từ từng sector hoạt động", "Rủi ro thuế đặc thù của công ty này (đã biết & có thể phát sinh)", "Công văn / thanh tra / truy thu thuế liên quan đến công ty (nếu có)", "Chuyển giá, thin capitalization, royalty với công ty mẹ"]
    },
    {
        "id": "co_international", "title": "Vấn đề thuế quốc tế của công ty",
        "sub": ["Cấu trúc holding quốc tế, công ty mẹ và BEPS exposure", "Tác động Pillar Two (thuế tối thiểu 15%) với tập đoàn", "Rủi ro PE, withholding tax trong giao dịch xuyên biên giới"]
    },
]

# ─── Build queries from flexible sections ─────────────────────────────────────
def sections_to_queries(sections: list, subject_context: str, report_date: datetime) -> list[dict]:
    """
    Legal sections (id: legal, co_legal) → 3 queries: inventory table + deep analysis + new 2024+
    Tax sections (id: tax*, co_tax*) → 3 queries: tax law inventory table + analysis + new 2024+
    Market/other → 1 query with appropriate recency
    """
    year = report_date.year
    prev_year = year - 1
    queries = []

    TAX_IDS   = {"tax", "tax_deep", "co_tax", "co_tax_issues"}
    LEGAL_IDS = {"legal", "co_legal"}
    MARKET_IDS = {"overview", "market", "co_overview", "co_sector_char", "co_growth"}

    for sec in sections:
        sec_id  = sec.get("id", "")
        title   = sec.get("title", "")
        subs    = sec.get("sub", [])
        sub_txt = "\n".join(f"- {s}" for s in subs) if subs else ""

        is_tax    = sec_id in TAX_IDS or any(k in sec_id for k in ["tax", "thue"])
        is_legal  = sec_id in LEGAL_IDS or any(k in sec_id for k in ["legal", "phap"])
        is_market = sec_id in MARKET_IDS

        if is_legal:
            queries.append({
                "id": f"{sec_id}_inventory",
                "label": f"{title} — Danh mục văn bản",
                "recency": None,
                "query": (
                    f"Lập DANH MỤC ĐẦY ĐỦ tất cả văn bản pháp luật (Luật, Pháp lệnh, Nghị định, Thông tư, "
                    f"Quyết định) đang có hiệu lực HOẶC đã ban hành nhưng chưa có hiệu lực, "
                    f"điều chỉnh hoạt động của doanh nghiệp trong ngành: {subject_context}\n\n"
                    f"Phạm vi: văn bản liên quan đến đăng ký kinh doanh, điều kiện hoạt động, "
                    f"quản lý chuyên ngành, lao động, môi trường, cạnh tranh, đầu tư nước ngoài, "
                    f"sở hữu trí tuệ, và bất kỳ quy định nào ảnh hưởng trực tiếp đến {subject_context}.\n\n"
                    f"Với MỖI văn bản ghi rõ:\n"
                    f"- Số hiệu đầy đủ (VD: Luật số 23/2018/QH14)\n"
                    f"- Tên văn bản\n"
                    f"- Ngày ban hành và ngày có hiệu lực\n"
                    f"- Tình trạng: Đang hiệu lực / Chưa có hiệu lực (ghi ngày) / Sắp hết hiệu lực\n"
                    f"- Lý do liên quan đến {subject_context}\n"
                    f"KHÔNG giới hạn năm. Bao gồm văn bản từ 2000-2023 nếu vẫn hiệu lực. "
                    f"Tiếng Việt. Nguồn: thuvienphapluat.vn, luatvietnam.vn, chinhphu.vn."
                )
            })
            queries.append({
                "id": f"{sec_id}_foundation",
                "label": f"{title} — Phân tích chi tiết",
                "recency": None,
                "query": (
                    f"Phân tích chi tiết các quy định pháp lý quan trọng nhất áp dụng cho: {subject_context}\n"
                    f"Nội dung:\n{sub_txt}\n\n"
                    f"Yêu cầu: điều kiện kinh doanh, giấy phép, hạn chế FDI, compliance obligations, "
                    f"chế tài vi phạm. Không giới hạn năm. Dẫn số hiệu cụ thể. Tiếng Việt."
                )
            })
            queries.append({
                "id": f"{sec_id}_new",
                "label": f"{title} — Mới & Sắp hiệu lực {prev_year}-{year}",
                "recency": "year",
                "query": (
                    f"Văn bản pháp luật MỚI BAN HÀNH hoặc SẮP CÓ HIỆU LỰC trong {prev_year}-{year} "
                    f"liên quan đến: {subject_context}\n"
                    f"Tìm: Luật mới, sửa đổi Luật, Nghị định, Thông tư mới. "
                    f"Ghi rõ ngày có hiệu lực và nội dung thay đổi chính. Tiếng Việt."
                )
            })

        elif is_tax:
            queries.append({
                "id": f"{sec_id}_inventory",
                "label": f"{title} — Danh mục văn bản thuế",
                "recency": None,
                "query": (
                    f"Lập DANH MỤC ĐẦY ĐỦ tất cả văn bản pháp luật về THUẾ (Luật thuế, Nghị định, "
                    f"Thông tư Bộ Tài chính/Tổng cục Thuế) đang có hiệu lực HOẶC đã ban hành "
                    f"nhưng chưa có hiệu lực, áp dụng cho doanh nghiệp ngành: {subject_context}\n\n"
                    f"Bao gồm ĐẦY ĐỦ tất cả:\n"
                    f"1. Thuế TNDN: Luật số 14/2008/QH12 và các sửa đổi, Luật mới (nếu có), "
                    f"   Nghị định 218/2013, các sửa đổi, Thông tư 78/2014 và các sửa đổi\n"
                    f"2. Thuế GTGT: Luật số 13/2008/QH12 và các sửa đổi, Luật mới (nếu có), "
                    f"   Nghị định 209/2013, các sửa đổi, Thông tư 219/2013 và các sửa đổi\n"
                    f"3. Thuế TNCN: Luật số 04/2007/QH12 và các sửa đổi, hướng dẫn liên quan ngành\n"
                    f"4. Thuế Nhà thầu: Thông tư 103/2014/TT-BTC và sửa đổi\n"
                    f"5. Thuế TTĐB (nếu áp dụng): Luật và sửa đổi\n"
                    f"6. Thuế XNK, FTA (nếu áp dụng)\n"
                    f"7. Quản lý thuế: Luật số 38/2019/QH14, Nghị định, Thông tư\n"
                    f"8. Hóa đơn: Nghị định 123/2020, Thông tư 78/2021 và sửa đổi\n"
                    f"9. Giao dịch liên kết: Nghị định 132/2020 và sửa đổi\n"
                    f"10. Ưu đãi thuế đặc thù ngành {subject_context}\n\n"
                    f"Với MỖI văn bản: số hiệu, tên, ngày ban hành, ngày hiệu lực, "
                    f"tình trạng (hiệu lực/chưa hiệu lực/đã được sửa đổi bởi...), "
                    f"nội dung chính liên quan {subject_context}.\n"
                    f"KHÔNG bỏ sót văn bản dù ban hành từ 2003. Tiếng Việt. "
                    f"Nguồn: thuvienphapluat.vn, mof.gov.vn, gdt.gov.vn."
                )
            })
            queries.append({
                "id": f"{sec_id}_foundation",
                "label": f"{title} — Phân tích chi tiết",
                "recency": None,
                "query": (
                    f"Phân tích chi tiết quy định thuế áp dụng cho: {subject_context}\n"
                    f"Nội dung:\n{sub_txt}\n\n"
                    f"Yêu cầu: thuế suất cụ thể, điều kiện ưu đãi, công văn hướng dẫn TCT/Bộ TC, "
                    f"rủi ro thuế phổ biến, vụ thanh tra/tranh chấp nổi bật. "
                    f"Không giới hạn năm. Tiếng Việt."
                )
            })
            queries.append({
                "id": f"{sec_id}_new",
                "label": f"{title} — Thay đổi thuế {prev_year}-{year}",
                "recency": "year",
                "query": (
                    f"Thay đổi THUẾ quan trọng nhất trong {prev_year}-{year} "
                    f"ảnh hưởng đến doanh nghiệp ngành: {subject_context}\n"
                    f"Tìm: Luật thuế mới, sửa đổi Luật TNDN/GTGT/QLT, Nghị định mới, Thông tư mới nhất. "
                    f"Ghi rõ ngày hiệu lực và tác động. Tiếng Việt."
                )
            })

        else:
            recency = "month" if is_market else "year"
            queries.append({
                "id": sec_id,
                "label": title,
                "recency": recency,
                "query": (
                    f"Nghiên cứu chuyên sâu về: {title}\n"
                    f"Đối tượng: {subject_context}\n"
                    f"Nội dung:\n{sub_txt}\n\n"
                    f"Yêu cầu: Tiếng Việt. Số liệu mới nhất. Nêu nguồn và năm."
                )
            })

    return queries

# ─── Save helpers ─────────────────────────────────────────────────────────────
def save_report_local(subject: str, html: str, sources: list,
                      user_id: int = 0, mode: str = "sector") -> str:
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    safe_name = re.sub(r'[^\w\s\-]', '', subject).strip()[:50]

    # Per-user subfolder when user_id > 0
    if user_id:
        user_dir = REPORTS_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
    else:
        user_dir = REPORTS_DIR

    existing = list(user_dir.glob(f"{date_str} - *.html"))
    seq = len(existing) + 1
    fname = f"{date_str} - {safe_name} - {seq}.html"
    storage_path = str(user_dir / fname)

    sources_html = ''.join(f'<li><a href="{u}">{u}</a></li>' for u in sources)
    full = f"""<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<title>Báo cáo thuế — {subject}</title>
<style>
body{{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1f2937}}
h2{{color:#028a39;border-bottom:2px solid #a7d9b8;padding-bottom:6px;margin-top:2rem;font-size:1.3rem}}
h3{{color:#016d2d;margin-top:1.2rem}}
p{{line-height:1.85;margin-bottom:.6rem;font-size:.975rem}}
ul{{list-style:disc;margin-left:1.5rem;margin-bottom:.75rem}}
ul ul{{list-style:circle;margin-left:1.5rem;margin-top:.25rem}}
ul ul ul{{list-style:square;margin-left:1.5rem}}
ol{{list-style:decimal;margin-left:1.5rem;margin-bottom:.75rem}}
li{{margin-bottom:.35rem;line-height:1.75;font-size:.95rem}}
table{{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.9rem}}
th{{background:#028a39;color:#fff;padding:.5rem .75rem;text-align:left}}
td{{padding:.4rem .75rem;border-bottom:1px solid #e5e7eb}}
tr:nth-child(even) td{{background:#e6f4ec}}
.footer{{margin-top:2rem;font-size:.75rem;color:#9ca3af;font-style:italic;border-top:1px solid #e5e7eb;padding-top:1rem}}
</style></head><body>
<div style="background:#028a39;color:white;padding:20px;border-radius:8px;margin-bottom:2rem">
<div style="font-size:.75rem;opacity:.8;margin-bottom:4px">TAX RESEARCH REPORT</div>
<h1 style="margin:0;font-size:1.5rem;color:white">Phân Tích Thuế — {subject}</h1>
<div style="opacity:.8;font-size:.85rem;margin-top:6px">{now.strftime("%d/%m/%Y %H:%M")}</div>
</div>
{html}
<div class="footer"><strong>Nguồn tham khảo ({len(sources)} links):</strong><ol>{sources_html}</ol>
Báo cáo tổng hợp tự động bởi AI. Mang tính tham khảo.</div>
</body></html>"""
    (user_dir / fname).write_text(full, encoding="utf-8")

    # Insert DB record
    if db_pool and user_id:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO reports (user_id, filename, subject, mode, file_size, storage_path) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, fname, subject, mode,
                     (user_dir / fname).stat().st_size, storage_path)
                )
                conn.commit()
        except Exception:
            conn.rollback()
        finally:
            release_db_conn(conn)

    # Sync to GDrive (non-blocking background)
    if shutil.which("rclone"):
        try:
            gdrive_path = f"gdrive:Thanh-AI/TaxResearch/user_{user_id}/{fname}"
            subprocess.Popen(
                ["rclone", "copyto", storage_path, gdrive_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
    return fname

# ─── SSE stream ───────────────────────────────────────────────────────────────

async def claude_stream_httpx(system: str, user_prompt: str, max_tokens: int = 12000):
    """Stream Claude via raw httpx — no SDK timeout issues."""
    headers = {
        "Authorization": f"Bearer {CLAUDIBLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CLAUDIBLE_MODEL,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_prompt}
        ]
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=300, write=60, pool=30)) as client:
        async with client.stream("POST", CLAUDIBLE_ENDPOINT, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    text = chunk["choices"][0]["delta"].get("content", "")
                    if text:
                        yield text
                except Exception:
                    continue


async def claude_call_httpx(system: str, user_prompt: str, max_tokens: int = 8000) -> str:
    """Non-streaming Claude call via raw httpx."""
    headers = {
        "Authorization": f"Bearer {CLAUDIBLE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CLAUDIBLE_MODEL,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_prompt}
        ]
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=120, write=60, pool=30)) as client:
        resp = await client.post(CLAUDIBLE_ENDPOINT, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def generate_report_stream(mode: str, subject: str, sections: list, user_id: int = 0):
    try:
        report_date = datetime.now()
        yield f"data: {json.dumps({'type':'status','message':f'Bắt đầu nghiên cứu: {subject}...'},ensure_ascii=False)}\n\n"

        queries = sections_to_queries(sections, subject, report_date)
        research = {}
        citations_all = []
        total = len(queries)

        # ── Parallel Perplexity queries (asyncio.gather) ──────────────────────
        # Group: market/overview queries run fully parallel;
        # legal/tax queries run in small batches to avoid rate limits
        BATCH = 4  # max concurrent requests
        async with httpx.AsyncClient() as client:
            yield f"data: {json.dumps({'type':'progress','step':0,'total':total,'label':'Đang khởi động...'},ensure_ascii=False)}\n\n"
            for batch_start in range(0, total, BATCH):
                batch = queries[batch_start:batch_start+BATCH]
                tasks = [perplexity_search(q["query"], client, report_date, recency=q.get("recency","month")) for q in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for q, res in zip(batch, results):
                    if isinstance(res, Exception):
                        res = {"content": f"[Lỗi: {res}]", "citations": [], "success": False}
                    research[q["id"]] = res
                    for u in res.get("citations", []):
                        if u not in citations_all:
                            citations_all.append(u)
                done_so_far = min(batch_start + BATCH, total)
                yield f"data: {json.dumps({'type':'progress','step':done_so_far,'total':total,'label':batch[-1]['label']},ensure_ascii=False)}\n\n"
                if batch_start + BATCH < total:
                    await asyncio.sleep(0.5)  # brief pause between batches
                yield 'data: {"type":"ping"}\n\n'

        yield f"data: {json.dumps({'type':'ai_start','total':total},ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type':'status','message':'Tổng hợp báo cáo với Claude AI...'},ensure_ascii=False)}\n\n"

        # Group research by base section id for synthesis
        ctx_parts = []
        seen_bases = []
        for q in queries:
            base_id = q["id"].replace("_foundation","").replace("_new","")
            if base_id not in seen_bases:
                seen_bases.append(base_id)
                # Gather all queries for this base section
                related = [r for r in queries if r["id"].replace("_foundation","").replace("_new","") == base_id]
                combined = "\n\n".join(
                    f"[{r['label'].upper()}]\n{research.get(r['id'],{}).get('content','(không có dữ liệu)')}"
                    for r in related
                )
                ctx_parts.append(combined)
        ctx = "\n\n" + "="*60 + "\n\n".join(ctx_parts)
        # Build sections structure from ORIGINAL sections (not expanded queries)
        sections_structure = "\n".join(
            f"<h2>{i+1}. {sec['title']}</h2>\n" +
            ("\n".join(f"  (bao gồm: {s})" for s in sec.get("sub",[])))
            for i, sec in enumerate(sections)
        )
        # Build citation map: URL index → short label
        citation_map = {url: i+1 for i, url in enumerate(citations_all)}
        citations_json = json.dumps(citation_map, ensure_ascii=False)

        prompt = f"""Viết báo cáo phân tích thuế chuyên sâu cho: {subject}
Thời điểm báo cáo: {report_date.strftime("%m/%Y")}

CẤU TRÚC BÁO CÁO — {len(sections)} phần:
{sections_structure}

HƯỚNG DẪN PHẦN PHÁP LÝ (section "Quy định pháp lý") — BẮT BUỘC:
Ở ĐẦU phần này, tạo bảng HTML đầy đủ với CỘT: Số hiệu | Tên văn bản | Loại | Ngày hiệu lực | Tình trạng | Liên quan đến ngành/công ty
- Liệt kê TẤT CẢ văn bản từ dữ liệu inventory, không bỏ sót
- Văn bản chưa có hiệu lực: ghi ngày hiệu lực tương lai, tô màu <span style="color:#d97706">Chưa hiệu lực</span>
- Văn bản mới {report_date.year-1}-{report_date.year}: <strong style="color:#028a39">MỚI</strong>
- Sau bảng: phân tích chi tiết theo chủ đề

HƯỚNG DẪN PHẦN THUẾ (section "Phân tích thuế") — BẮT BUỘC:
Ở ĐẦU phần này, tạo bảng HTML đầy đủ với CỘT: Loại thuế | Văn bản gốc | Văn bản sửa đổi mới nhất | Ngày hiệu lực | Thuế suất / Nội dung chính | Đặc thù ngành
- Bao gồm ĐẦY ĐỦ: TNDN, GTGT, TNCN, Nhà thầu, TTĐB, XNK, QLT, Hóa đơn, Giao dịch liên kết, Ưu đãi
- Văn bản cũ vẫn hiệu lực (2003-2023): PHẢI liệt kê, ghi "đang hiệu lực"
- Văn bản mới thay thế: ghi rõ thay thế văn bản nào
- Sau bảng: phân tích chi tiết theo từng loại thuế

QUY TẮC CHUNG:
- Tổng hợp CẢ BA nguồn (inventory + foundation + new) cho mỗi phần
- KHÔNG bỏ sót văn bản quan trọng dù ban hành trước 2024
- KHÔNG tự thêm số hiệu không có trong dữ liệu nghiên cứu
- Văn bản mới {report_date.year-1}-{report_date.year}: highlight bằng <strong>

CITATIONS INLINE:
Khi trích dẫn thông tin từ nguồn, thêm link inline: <a href="URL_NGUON" target="_blank" style="color:#028a39;font-size:.75em">[N]</a>
Danh sách URL theo thứ tự: {citations_json}

DỮ LIỆU NGHIÊN CỨU:
{ctx}

FORMAT BẮT BUỘC: HTML thuần. KHÔNG markdown. Bullet nhiều cấp = <ul> lồng nhau. Bắt đầu ngay bằng <h2>."""

        report_html = ""
        if not CLAUDIBLE_API_KEY:
            for q in queries:
                report_html += f"<h2>{q['label']}</h2>{md_to_html(research.get(q['id'],{}).get('content',''))}"
            yield f"data: {json.dumps({'type':'report','html':report_html},ensure_ascii=False)}\n\n"
        else:
            # ── Per-section calls: nhỏ hơn → không bị token limit ──────────────
            system_prompt = build_report_system_prompt()
            total_sec = len(sections)
            for sec_idx, sec in enumerate(sections):
                sec_title = sec["title"]
                sec_subs  = sec.get("sub", [])
                yield f"data: {json.dumps({'type':'status','message':f'Claude đang viết: {sec_title}...'},ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type':'progress','step':total+sec_idx+1,'total':total+total_sec,'label':f'Viết: {sec_title}'},ensure_ascii=False)}\n\n"

                sub_hint = ("\nBao gồm các nội dung: " + ", ".join(sec_subs)) if sec_subs else ""
                # Pick relevant research context for this section (filtered)
                keyword_map = {
                    "tổng quan": ["overview","general"],
                    "đặc thù": ["overview","market"],
                    "phát triển": ["market","players"],
                    "players": ["market","players"],
                    "quy định": ["legal","regulations"],
                    "pháp lý": ["legal","regulations"],
                    "phân tích thuế": ["tax","vat","cit"],
                    "vấn đề thuế": ["issues","risks","tax"],
                    "đặc thù ngành": ["issues","risks"],
                    "quốc tế": ["international","global"],
                    "thông lệ": ["international","global"],
                }
                sec_title_lower = sec_title.lower()
                # Find matching research keys
                matched_keys = []
                for kw, res_keys in keyword_map.items():
                    if kw in sec_title_lower:
                        matched_keys.extend(res_keys)
                
                # Build filtered context — only relevant research parts
                ctx_parts_filtered = []
                for part in ctx_parts:
                    part_lower = part.lower()
                    if not matched_keys or any(k in part_lower[:200] for k in matched_keys):
                        ctx_parts_filtered.append(part[:3000])  # cap each part
                
                sec_ctx = ("\n\n" + "="*40 + "\n\n").join(ctx_parts_filtered) if ctx_parts_filtered else ctx[:5000]

                sec_prompt = f"""Viết PHẦN "{sec_title}" trong báo cáo phân tích thuế cho: {subject} ({report_date.strftime("%m/%Y")}){sub_hint}

QUY TẮC:
- Viết đầy đủ, chuyên sâu, ít nhất 600 từ
- Dùng HTML thuần (h3, p, ul, li, table, strong, em) — KHÔNG markdown
- Bắt đầu ngay bằng <h2>{sec_idx+1}. {sec_title}</h2>
- Trích dẫn văn bản pháp luật cụ thể khi có (số hiệu, năm)
{"- Tạo bảng HTML đầy đủ ở đầu phần nếu là phần Pháp lý hoặc Thuế" if any(k in sec_title.lower() for k in ["quy định","pháp lý","thuế","legal","tax"]) else ""}

DỮ LIỆU NGHIÊN CỨU:
{sec_ctx[:6000]}"""

                sec_html = ""
                MAX_RETRIES = 2
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        async for text in claude_stream_httpx(system_prompt, sec_prompt, max_tokens=2000):
                            sec_html += text
                            report_html += text
                            yield f"data: {json.dumps({'type':'chunk','text':text},ensure_ascii=False)}\n\n"
                        yield 'data: {"type":"ping"}\n\n'
                        break
                    except Exception as e:
                        if attempt < MAX_RETRIES:
                            yield f"data: {json.dumps({'type':'status','message':f'Lỗi phần {sec_title}, thử lại...'},ensure_ascii=False)}\n\n"
                            await asyncio.sleep(2)
                            report_html = report_html[:-len(sec_html)]
                            sec_html = ""
                            continue
                        else:
                            report_html += f"<h2>{sec_idx+1}. {sec_title}</h2><p><em>[Lỗi tạo nội dung phần này]</em></p>"
                            yield f"data: {json.dumps({'type':'chunk','text':f'<h2>{sec_idx+1}. {sec_title}</h2><p><em>[Lỗi]</em></p>'},ensure_ascii=False)}\n\n"

        report_html = clean_html(report_html)
        fname = save_report_local(subject, report_html, citations_all,
                                  user_id=user_id, mode=mode)

        yield f"data: {json.dumps({'type':'citations','urls':citations_all},ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type':'done','filename':fname,'drive':False},ensure_ascii=False)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type':'error','message':str(e)},ensure_ascii=False)}\n\n"

# ─── Auth endpoints ───────────────────────────────────────────────────────────

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    username = form_data.username.strip()
    password = form_data.password

    # Try DB auth first
    if db_pool:
        user = _db_get_user(username)
        if user and user.get("is_active") and _verify_password(password, user["password_hash"]):
            token = _create_jwt({"sub": str(user["id"]), "username": user["username"]})
            # Update last_login
            conn = get_db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (user["id"],))
                    conn.commit()
            except Exception:
                pass
            finally:
                release_db_conn(conn)
            return {"access_token": token, "token_type": "bearer",
                    "username": user["username"], "plan": user["plan"]}

    # Fallback: env var auth
    ok_u = secrets.compare_digest(username.encode(), APP_USERNAME.encode())
    ok_p = secrets.compare_digest(password.encode(), APP_PASSWORD.encode())
    if ok_u and ok_p:
        token = _create_jwt({"sub": "0", "username": username})
        return {"access_token": token, "token_type": "bearer",
                "username": username, "plan": "admin"}

    raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không đúng")


@app.post("/auth/register")
async def register(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    email    = body.get("email", "").strip()

    if not username or not password:
        raise HTTPException(400, "Thiếu username hoặc password")
    if len(password) < 6:
        raise HTTPException(400, "Mật khẩu phải ít nhất 6 ký tự")

    if not db_pool or not pwd_context:
        raise HTTPException(503, "Đăng ký chưa khả dụng (DB chưa kết nối)")

    hashed = pwd_context.hash(password)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, email, password_hash, plan) VALUES (%s,%s,%s,'free') RETURNING id",
                (username, email, hashed)
            )
            user_id = cur.fetchone()[0]
            conn.commit()
        token = _create_jwt({"sub": str(user_id), "username": username})
        return {"access_token": token, "token_type": "bearer",
                "username": username, "plan": "free"}
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, "Tên đăng nhập đã tồn tại")
        raise HTTPException(500, f"Lỗi đăng ký: {e}")
    finally:
        release_db_conn(conn)


@app.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "plan": user.get("plan","free"),
            "id": user.get("id", 0)}


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(user: dict = Depends(get_current_user)):
    return HTML_PAGE

@app.post("/stream")
async def stream_report(request_body: dict, user: dict = Depends(get_current_user)):
    mode     = request_body.get("mode", "sector")
    subject  = request_body.get("subject", "")
    sections = request_body.get("sections", [])
    if not subject or not sections:
        raise HTTPException(400, "Missing subject or sections")
    user_id = user.get("id", 0)
    return StreamingResponse(
        generate_report_stream(mode, subject, sections, user_id=user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Content-Type-Options": "nosniff",
        }
    )

@app.get("/default-sections")
async def get_default_sections(mode: str = "sector", user: dict = Depends(get_current_user)):
    data = DEFAULT_SECTOR_SECTIONS if mode == "sector" else DEFAULT_COMPANY_SECTIONS
    return JSONResponse(data)

@app.get("/reports")
async def list_reports(user: dict = Depends(get_current_user)):
    user_id = user.get("id", 0)
    # Try DB query first
    if db_pool and user_id:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT filename, subject, file_size, storage_path, "
                    "EXTRACT(EPOCH FROM created_at) as mtime "
                    "FROM reports WHERE user_id=%s ORDER BY created_at DESC LIMIT 100",
                    (user_id,)
                )
                rows = cur.fetchall()
                if rows:
                    result = []
                    for r in rows:
                        fname, subject, fsize, spath, mtime = r
                        result.append({
                            "name": fname, "size": fsize or 0,
                            "mtime": float(mtime or 0),
                            "url": f"/report/{fname}",
                            "subject": subject or fname
                        })
                    return JSONResponse(result)
        except Exception:
            pass
        finally:
            release_db_conn(conn)

    # Fallback: filesystem (per-user dir or root)
    if user_id:
        user_dir = REPORTS_DIR / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
    else:
        user_dir = REPORTS_DIR
    files = sorted(user_dir.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
    reports = [{
        "name": f.name, "size": f.stat().st_size,
        "mtime": f.stat().st_mtime, "url": f"/report/{f.name}",
        "source": "local"
    } for f in files[:100]]

    # GDrive reports (if local has < 5)
    if len(reports) < 5 and shutil.which("rclone"):
        try:
            gdrive_folder = f"gdrive:{GDRIVE_FOLDER}/user_{user_id}"
            result = subprocess.run(
                ["rclone", "lsjson", gdrive_folder],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                gdrive_files = json.loads(result.stdout)
                local_names = {r["name"] for r in reports}
                for f in gdrive_files:
                    if f["Name"].endswith(".html") and f["Name"] not in local_names:
                        try:
                            mtime = datetime.fromisoformat(
                                f["ModTime"].replace("Z", "+00:00")).timestamp()
                        except Exception:
                            mtime = 0
                        reports.append({
                            "name": f["Name"],
                            "size": f.get("Size", 0),
                            "mtime": mtime,
                            "url": f"/report/{f['Name']}",
                            "source": "gdrive"
                        })
        except Exception as e:
            print(f"[REPORTS] GDrive list failed: {e}")

    reports.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return JSONResponse(reports[:100])


def _find_report_path(fname: str, user_id: int) -> "Path | None":
    """Find report file, checking user dir then root reports dir."""
    if not fname.endswith(".html"):
        return None
    # User-specific subfolder first
    if user_id:
        p = REPORTS_DIR / str(user_id) / fname
        if p.exists():
            return p
    # Legacy root location
    p = REPORTS_DIR / fname
    if p.exists():
        return p
    return None


@app.delete("/report/{fname}")
async def delete_report(fname: str, user: dict = Depends(get_current_user)):
    user_id = user.get("id", 0)
    path = _find_report_path(fname, user_id)
    if not path:
        raise HTTPException(404)

    # Access control: verify ownership via DB
    if db_pool and user_id:
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM reports WHERE filename=%s AND user_id=%s",
                            (fname, user_id))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(403, "Access denied")
                cur.execute("DELETE FROM reports WHERE filename=%s AND user_id=%s",
                            (fname, user_id))
                conn.commit()
        except HTTPException:
            raise
        except Exception:
            conn.rollback()
        finally:
            release_db_conn(conn)

    path.unlink(missing_ok=True)
    if shutil.which("rclone"):
        try:
            subprocess.Popen(
                ["rclone", "deletefile",
                 f"gdrive:Thanh-AI/TaxResearch/user_{user_id}/{fname}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass
    return JSONResponse({"ok": True})


@app.get("/report/{fname}", response_class=HTMLResponse)
async def get_report(fname: str, user: dict = Depends(get_current_user)):
    user_id = user.get("id", 0)
    path = _find_report_path(fname, user_id)

    if path:
        # Access control via DB (soft check — falls back to allow if DB unavailable)
        if db_pool and user_id:
            conn = get_db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM reports WHERE filename=%s AND user_id=%s",
                                (fname, user_id))
                    if not cur.fetchone():
                        raise HTTPException(403, "Access denied")
            except HTTPException:
                raise
            except Exception:
                pass  # DB error: allow access
            finally:
                release_db_conn(conn)
        return HTMLResponse(path.read_text(encoding="utf-8"))

    # Try GDrive if not found locally
    if shutil.which("rclone"):
        safe_name = re.sub(r'[<>:"/\\|?*]', '', fname)
        try:
            result = subprocess.run(
                ["rclone", "cat", f"gdrive:{GDRIVE_FOLDER}/user_{user_id}/{safe_name}"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                return HTMLResponse(result.stdout)
        except Exception as e:
            print(f"[REPORT] GDrive fetch failed: {e}")

    raise HTTPException(404, "Report not found")


@app.post("/slides")
async def generate_slides(request_body: dict, user: dict = Depends(get_current_user)):
    html    = request_body.get("html", "")
    subject = request_body.get("subject", "Báo cáo")
    if not html:
        raise HTTPException(400, "Missing html")

    if not CLAUDIBLE_API_KEY:
        raise HTTPException(503, "Claude API not configured")

    prompt = f"""Chuyển báo cáo phân tích thuế sau thành bộ slides trình bày chuyên nghiệp.

CHỦ ĐỀ: {subject}

YÊU CẦU:
- Tạo 12-15 slides bằng tiếng Việt dùng reveal.js
- Mỗi slide: thẻ <section>
- Nội dung súc tích, tối đa 5-6 bullet points mỗi slide
- Highlight số liệu và điểm quan trọng bằng <span style="color:#028a39;font-weight:bold">

CẤU TRÚC SLIDES:
1. Title slide: tên ngành/công ty, ngày, "Phân Tích Thuế — Tax Research Report"
2-3. Tóm tắt key findings & số liệu nổi bật
4-12. Mỗi section h2 trong báo cáo = 1-2 slides với bullet points
13. Regulatory summary: bảng tóm tắt văn bản quan trọng nhất (3-5 văn bản)
14. Risk & lưu ý quan trọng
15. Disclaimer & nguồn tham khảo

OUTPUT: Trả về TOÀN BỘ HTML page với reveal.js CDN. Bắt đầu bằng <!DOCTYPE html>.
Dùng theme white. Primary color #028a39. Font tiếng Việt.

NỘI DUNG BÁO CÁO:
{html[:8000]}"""

    system = """Bạn là chuyên gia thiết kế presentation thuế chuyên nghiệp.
Tạo slides reveal.js hoàn chỉnh, đẹp, professional.
Output PHẢI là HTML page hoàn chỉnh bắt đầu bằng <!DOCTYPE html> và kết thúc bằng </html>.
KHÔNG thêm markdown, KHÔNG thêm giải thích ngoài HTML."""

    try:
        slides_html = (await claude_call_httpx(system, prompt, max_tokens=8000)).strip()
        # Strip markdown if any
        if slides_html.startswith("```"):
            slides_html = slides_html.split("\n",1)[1].rsplit("```",1)[0]
        return HTMLResponse(slides_html)
    except Exception as e:
        raise HTTPException(500, f"Claude error: {e}")




def _html_to_docx(subject: str, html_content: str) -> BytesIO:
    """Helper: convert HTML to DOCX (runs in thread pool)."""
    from html.parser import HTMLParser
    doc = DocxDocument()

    # Title
    title_para = doc.add_heading(f"Phân Tích Thuế — {subject}", 0)
    title_para.runs[0].font.color.rgb = RGBColor(0x02, 0x8a, 0x39)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"Ngày tạo: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    doc.add_paragraph("Nguồn: Perplexity Sonar + Claude AI | taxsector.gpt4vn.com")
    doc.add_paragraph()

    # Parse HTML
    class DocxBuilder(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current_tag = None
            self.current_para = None
            self.text_buf = ""
            self.skip_tags = {"script","style","a"}
            self.in_skip = False
            self.in_table = False
            self.table_rows = []
            self.current_row = []
            self.is_header_row = False

        def handle_starttag(self, tag, attrs):
            self.current_tag = tag
            if tag in self.skip_tags:
                self.in_skip = True
            elif tag == "table":
                self.in_table = True
                self.table_rows = []
            elif tag == "tr":
                self.current_row = []
            elif tag in ("th",):
                self.is_header_row = True

        def handle_endtag(self, tag):
            if tag in self.skip_tags:
                self.in_skip = False
            elif tag in ("h2","h3","h4","p","li"):
                t = self.text_buf.strip()
                if t:
                    if self.current_tag == "h2" or tag == "h2":
                        h = doc.add_heading(t, level=1)
                        h.runs[0].font.color.rgb = RGBColor(0x02, 0x8a, 0x39)
                    elif tag == "h3":
                        h = doc.add_heading(t, level=2)
                        h.runs[0].font.color.rgb = RGBColor(0x01, 0x6d, 0x2d)
                    elif tag == "h4":
                        doc.add_heading(t, level=3)
                    elif tag == "li":
                        p = doc.add_paragraph(t, style="List Bullet")
                        if p.runs: p.runs[0].font.size = Pt(11)
                    else:
                        p = doc.add_paragraph(t)
                        if p.runs: p.runs[0].font.size = Pt(11)
                self.text_buf = ""
            elif tag in ("td","th"):
                self.current_row.append(self.text_buf.strip())
                self.text_buf = ""
            elif tag == "tr":
                if self.current_row:
                    self.table_rows.append((self.current_row, self.is_header_row))
                self.is_header_row = False
                self.current_row = []
            elif tag == "table":
                self.in_table = False
                if self.table_rows:
                    max_cols = max(len(r[0]) for r in self.table_rows)
                    if max_cols > 0:
                        tbl = doc.add_table(rows=len(self.table_rows), cols=max_cols)
                        tbl.style = "Table Grid"
                        for ri, (row_data, is_hdr) in enumerate(self.table_rows):
                            for ci, cell_text in enumerate(row_data[:max_cols]):
                                cell = tbl.rows[ri].cells[ci]
                                cell.text = cell_text
                                if is_hdr:
                                    for run in cell.paragraphs[0].runs:
                                        run.font.bold = True
                                        run.font.color.rgb = RGBColor(0x02, 0x8a, 0x39)
                        doc.add_paragraph()
                self.table_rows = []

        def handle_data(self, data):
            if not self.in_skip and not self.in_table or self.current_tag in ("td","th"):
                self.text_buf += data

    builder = DocxBuilder()
    builder.feed(html_content)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


@app.post("/docx")
async def export_docx(request_body: dict, user: dict = Depends(get_current_user)):
    """Convert report HTML to DOCX and return as download."""
    import concurrent.futures
    from fastapi.responses import Response
    html    = request_body.get("html", "")
    subject = request_body.get("subject", "Báo cáo")
    if not html or not html.strip():
        raise HTTPException(400, "Không có nội dung báo cáo để xuất.")
    if not DOCX_OK:
        raise HTTPException(503, "python-docx không khả dụng.")
    if not BS4_OK:
        raise HTTPException(503, "BeautifulSoup không khả dụng.")

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_html_to_docx, subject, html)
            buf = future.result(timeout=30)

        safe_name = re.sub(r'[^\w\s-]', '', subject).strip()[:40]
        filename = f"TaxReport_{safe_name}_{datetime.now().strftime('%Y%m%d')}.docx"
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except concurrent.futures.TimeoutError:
        raise HTTPException(504, "Export timeout — report too large or server busy")
    except HTTPException:
        raise
    except Exception as e:
        print(f"[DOCX] Export error: {e}")
        raise HTTPException(500, f"Lỗi tạo DOCX: {str(e)[:200]}")


# ─── Frontend ─────────────────────────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tax Sector Research</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  :root{--p:#028a39;--pd:#016d2d;--pl:#e6f4ec;--pb:#a7d9b8}
  .bg-p{background:var(--p)}.bg-pd{background:var(--pd)}.bg-pl{background:var(--pl)}
  .text-p{color:var(--p)}.text-pd{color:var(--pd)}
  .border-p{border-color:var(--p)}.border-pb{border-color:var(--pb)}
  .btn-p{background:var(--p);color:#fff}.btn-p:hover{background:var(--pd)}
  .ring-p:focus{outline:none;box-shadow:0 0 0 2px var(--pb)}
  .chip{background:var(--pl);color:var(--p);border:1px solid var(--pb)}
  .chip:hover{background:#d0eddc}
  .tab-on{background:var(--p);color:#fff}
  .tab-off{background:#f3f4f6;color:#6b7280}.tab-off:hover{background:var(--pl);color:var(--p)}

  /* Section builder */
  .section-card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin-bottom:10px;transition:border-color .2s}
  .section-card:hover{border-color:var(--pb)}
  .section-card.dragging{opacity:.5;border:2px dashed var(--p)}
  .sub-item{display:flex;align-items:center;gap:8px;margin-bottom:6px}
  .sub-item input{flex:1;font-size:.8rem;border:1px solid #e5e7eb;border-radius:6px;padding:4px 8px;color:#374151}
  .sub-item input:focus{outline:none;border-color:var(--pb)}

  @media print{#app-header,#input-wrap,.no-print{display:none!important}body{background:#fff}#report-wrap{max-width:100%;margin:0;padding:0}}
  #report-content h2{font-size:1.3rem;font-weight:700;color:var(--p);margin-top:2rem;margin-bottom:.75rem;padding-bottom:.5rem;border-bottom:2px solid var(--pb);page-break-after:avoid}
  #report-content h3{font-size:1.1rem;font-weight:600;color:var(--pd);margin-top:1.25rem;margin-bottom:.4rem}
  #report-content p{margin-bottom:.6rem;line-height:1.85;color:#1f2937;font-size:.975rem}
  #report-content ul{list-style:disc;margin-left:1.5rem;margin-bottom:.75rem}
  #report-content ul ul{list-style:circle;margin-left:1.5rem;margin-top:.3rem;margin-bottom:.3rem}
  #report-content ul ul ul{list-style:square;margin-left:1.5rem}
  #report-content ol{list-style:decimal;margin-left:1.5rem;margin-bottom:.75rem}
  #report-content ol ol{list-style:lower-alpha;margin-left:1.5rem;margin-top:.3rem}
  #report-content li{margin-bottom:.35rem;line-height:1.75;font-size:.95rem}
  #report-content strong{color:var(--pd);font-weight:600}
  #report-content table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.9rem}
  #report-content th{background:var(--p);color:#fff;padding:.5rem .75rem;text-align:left}
  #report-content td{padding:.4rem .75rem;border-bottom:1px solid #e5e7eb}
  #report-content tr:nth-child(even) td{background:var(--pl)}
  #report-content code{background:#f3f4f6;padding:.1rem .3rem;border-radius:3px;font-size:.85em}
  .step-done{color:var(--p)!important}.step-active{color:#2563eb!important}
  .dot-done{border-color:var(--p)!important;background:var(--pl)!important;color:var(--p)!important}
  .dot-active{border-color:#2563eb!important;background:#eff6ff!important;color:#2563eb!important}

  /* Reading progress bar */
  #reading-progress{position:fixed;top:0;left:0;width:0%;height:3px;background:var(--p);z-index:9999;transition:width .1s}

  /* TOC sidebar */
  #toc-sidebar{position:fixed;right:1rem;top:50%;transform:translateY(-50%);width:200px;max-height:80vh;overflow-y:auto;background:white;border:1px solid #e5e7eb;border-radius:12px;padding:12px;box-shadow:0 4px 20px rgba(0,0,0,.08);z-index:100;display:none}
  #toc-sidebar h4{font-size:.7rem;font-weight:700;color:var(--p);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--pb)}
  .toc-item{display:block;font-size:.72rem;color:#6b7280;padding:3px 6px;border-radius:4px;cursor:pointer;line-height:1.4;text-decoration:none;transition:all .15s}
  .toc-item:hover{background:var(--pl);color:var(--p)}
  .toc-item.active{background:var(--pl);color:var(--p);font-weight:600}
  .toc-progress{font-size:.65rem;color:#9ca3af;text-align:center;margin-top:8px;padding-top:6px;border-top:1px solid #f3f4f6}
  @media(max-width:1280px){#toc-sidebar{display:none!important}}
</style>
</head>
<body class="bg-gray-50 min-h-screen">

<!-- Login page overlay -->
<div id="login-page" class="hidden fixed inset-0 bg-gray-50 z-[200] flex items-center justify-center p-4">
  <div class="bg-white rounded-2xl shadow-xl w-full max-w-sm p-8">
    <div class="text-center mb-6">
      <div class="text-4xl mb-2">🔍</div>
      <h1 class="text-xl font-bold text-gray-800">Tax Sector Research</h1>
      <p class="text-sm text-gray-500 mt-1">Đăng nhập để tiếp tục</p>
    </div>
    <div id="login-err" class="hidden mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700"></div>
    <div id="register-err" class="hidden mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700"></div>

    <!-- Login form -->
    <div id="login-form-wrap">
      <input id="login-user" type="text" placeholder="Tên đăng nhập" autocomplete="username"
        class="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-green-400">
      <input id="login-pass" type="password" placeholder="Mật khẩu" autocomplete="current-password"
        class="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-green-400"
        onkeydown="if(event.key==='Enter')doLogin()">
      <button onclick="doLogin()" id="btn-login"
        class="w-full bg-green-600 hover:bg-green-700 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors">
        Đăng nhập
      </button>
      <p class="text-center text-xs text-gray-400 mt-4">
        Chưa có tài khoản?
        <a onclick="showRegister()" class="text-green-600 hover:underline cursor-pointer">Đăng ký</a>
      </p>
    </div>

    <!-- Register form -->
    <div id="register-form-wrap" class="hidden">
      <input id="reg-user" type="text" placeholder="Tên đăng nhập" autocomplete="username"
        class="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-green-400">
      <input id="reg-email" type="email" placeholder="Email (tuỳ chọn)"
        class="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-green-400">
      <input id="reg-pass" type="password" placeholder="Mật khẩu (≥6 ký tự)" autocomplete="new-password"
        class="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-green-400"
        onkeydown="if(event.key==='Enter')doRegister()">
      <button onclick="doRegister()" id="btn-register"
        class="w-full bg-green-600 hover:bg-green-700 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors">
        Tạo tài khoản
      </button>
      <p class="text-center text-xs text-gray-400 mt-4">
        Đã có tài khoản?
        <a onclick="showLogin()" class="text-green-600 hover:underline cursor-pointer">Đăng nhập</a>
      </p>
    </div>
  </div>
</div>

<!-- Reading progress bar -->
<div id="reading-progress"></div>

<!-- TOC Sidebar -->
<div id="toc-sidebar">
  <h4>📋 Mục lục</h4>
  <div id="toc-items"></div>
  <div class="toc-progress"><span id="toc-pct">0</span>% đã đọc</div>
</div>

<div id="app-header" class="bg-p text-white py-4 px-4 shadow-md no-print">
  <div class="max-w-5xl mx-auto flex items-center justify-between">
    <div>
      <h1 class="text-lg font-bold">🔍 Tax Sector Research</h1>
      <p class="text-green-200 text-xs mt-0.5">Phân tích thuế chuyên sâu · Perplexity + Claude AI</p>
    </div>
    <button onclick="showReports()" class="text-xs bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg font-medium">📂 Báo cáo đã lưu</button>
  </div>
</div>

<div id="input-wrap" class="max-w-5xl mx-auto mt-6 px-4 no-print">
  <div class="bg-white rounded-2xl shadow-sm p-6 border border-gray-200">

    <!-- Mode tabs -->
    <div class="flex gap-2 mb-5">
      <button id="tab-sector"  onclick="setMode('sector')"  class="tab-on  text-sm px-4 py-2 rounded-lg font-semibold transition-colors">🏭 Phân tích ngành</button>
      <button id="tab-company" onclick="setMode('company')" class="tab-off text-sm px-4 py-2 rounded-lg font-semibold transition-colors">🏢 Phân tích công ty</button>
    </div>

    <!-- Reports shortcut on main screen -->
    <div class="mb-5">
      <button onclick="showReports()"
        class="w-full sm:w-auto bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white px-6 py-3 rounded-xl font-semibold text-sm shadow-lg hover:shadow-xl transition-all flex items-center justify-center gap-2">
        📂 Báo cáo đã lưu
        <span class="text-xs opacity-75" id="reports-count-badge"></span>
      </button>
    </div>

    <!-- Subject input -->
    <div id="subject-sector">
      <label class="block text-xs font-semibold text-gray-600 mb-1.5">Ngành / Sector</label>
      <input id="sector-input" type="text" placeholder="VD: FMCG, Bất động sản, Ngân hàng, Dược phẩm..."
        class="w-full border border-gray-300 rounded-xl px-4 py-2.5 text-sm ring-p focus:border-transparent">
      <div class="flex flex-wrap gap-1.5 mt-2 items-center">
        <span class="text-xs text-gray-400">Thử:</span>
        <button onclick="qs('FMCG')"               class="chip text-xs px-2.5 py-0.5 rounded-full">FMCG</button>
        <button onclick="qs('Bất động sản')"        class="chip text-xs px-2.5 py-0.5 rounded-full">Bất động sản</button>
        <button onclick="qs('Ngân hàng')"           class="chip text-xs px-2.5 py-0.5 rounded-full">Ngân hàng</button>
        <button onclick="qs('Sản xuất ô tô')"       class="chip text-xs px-2.5 py-0.5 rounded-full">Sản xuất ô tô</button>
        <button onclick="qs('Dược phẩm')"           class="chip text-xs px-2.5 py-0.5 rounded-full">Dược phẩm</button>
        <button onclick="qs('Logistics')"           class="chip text-xs px-2.5 py-0.5 rounded-full">Logistics</button>
        <button onclick="qs('Công nghệ thông tin')" class="chip text-xs px-2.5 py-0.5 rounded-full">CNTT</button>
        <button onclick="qs('Năng lượng tái tạo')"  class="chip text-xs px-2.5 py-0.5 rounded-full">Năng lượng TT</button>
      </div>
    </div>
    <div id="subject-company" class="hidden grid grid-cols-2 gap-3">
      <div>
        <label class="block text-xs font-semibold text-gray-600 mb-1.5">Tên công ty</label>
        <input id="company-input" type="text" placeholder="VD: Vinamilk, Masan, Samsung Vietnam..."
          class="w-full border border-gray-300 rounded-xl px-4 py-2.5 text-sm ring-p">
      </div>
      <div>
        <label class="block text-xs font-semibold text-gray-600 mb-1.5">Ngành chính</label>
        <input id="sector-company-input" type="text" placeholder="VD: FMCG, Sản xuất điện tử..."
          class="w-full border border-gray-300 rounded-xl px-4 py-2.5 text-sm ring-p">
      </div>
    </div>

    <!-- Section Builder -->
    <div class="mt-5">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-gray-700">📋 Nội dung báo cáo <span id="section-count" class="text-xs font-normal text-gray-400"></span></h3>
        <div class="flex gap-2">
          <button onclick="resetSections()" class="text-xs text-gray-500 hover:text-p px-2 py-1 rounded border border-gray-200 hover:border-p transition-colors">↺ Mặc định</button>
          <button onclick="addSection()"    class="text-xs btn-p px-3 py-1 rounded-lg font-medium transition-colors">+ Thêm phần</button>
        </div>
      </div>
      <p class="text-xs text-gray-400 mb-3">Kéo thả để sắp xếp · Click tiêu đề để chỉnh sửa · Xoá phần không cần · Thêm sub-items chi tiết</p>
      <div id="sections-container"></div>
    </div>

    <!-- Cost estimate + Run button -->
    <div class="mt-5 flex items-center justify-between">
      <div class="text-xs text-gray-400">
        ⏱ ~<span id="est-time">90</span>s · 💰 ~$<span id="est-cost">0.08</span> (Perplexity + Claude)
      </div>
      <button onclick="startResearch()" class="btn-p px-8 py-3 rounded-xl font-bold text-sm shadow-sm transition-colors">
        Nghiên cứu →
      </button>
    </div>
  </div>
</div>

<!-- Progress -->
<div id="progress-wrap" class="max-w-5xl mx-auto mt-5 px-4 hidden no-print">
  <div class="bg-white rounded-2xl shadow-sm p-5 border border-gray-200">
    <div id="status-text" class="text-sm font-semibold mb-3 text-p"></div>
    <div class="w-full bg-gray-100 rounded-full h-2 mb-4">
      <div id="progress-bar" class="h-2 rounded-full transition-all duration-500 bg-p" style="width:0%"></div>
    </div>
    <div id="steps-container" class="grid grid-cols-2 gap-1.5"></div>
  </div>
</div>

<!-- Report -->
<div id="report-wrap" class="max-w-5xl mx-auto mt-5 px-4 mb-16 hidden">
  <div class="bg-p text-white p-6 rounded-t-2xl">
    <div class="text-xs opacity-70 font-semibold tracking-widest mb-2">TAX RESEARCH REPORT</div>
    <h1 id="report-title" class="text-xl font-bold"></h1>
    <div class="text-green-200 text-xs mt-2"><span id="report-date"></span> · Perplexity + Claude AI</div>
  </div>
  <div class="bg-gray-100 border-x border-gray-200 px-5 py-2.5 flex flex-wrap gap-2 items-center no-print">
    <button onclick="window.print()"  class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">🖨️ In/PDF</button>
    <button onclick="copyReport()"    class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">📋 Copy</button>
    <button onclick="openDashboard()" class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">📊 Dashboard</button>
    <button id="btn-appendix" onclick="openAppendix()" class="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 text-sm disabled:opacity-50">📋 Appendix</button>
        <button id="btn-slides" class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">📑 Slides</button>
    <button onclick="exportDocx()"    id="btn-docx"   class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">📄 Word</button>
    <button onclick="showReports()"   class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">📂 Xem lại</button>
    <button onclick="resetForm()"     class="text-xs bg-white border border-gray-300 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-gray-700 font-medium">← Mới</button>
    <div class="flex items-center gap-1 no-print" title="Cỡ chữ">
      <button onclick="changeFontSize(-1)" class="text-xs bg-white border border-gray-300 hover:bg-gray-50 w-7 h-7 rounded-lg text-gray-700 font-bold leading-none">A-</button>
      <button onclick="changeFontSize(1)"  class="text-xs bg-white border border-gray-300 hover:bg-gray-50 w-7 h-7 rounded-lg text-gray-700 font-bold leading-none">A+</button>
    </div>
    <span id="sources-count" class="ml-auto text-xs text-gray-400"></span>
  </div>
  <div class="bg-white shadow-sm rounded-b-2xl border border-gray-200 px-8 py-8">
    <div id="report-content" class="text-gray-800 text-base leading-relaxed"></div>
    <div id="sources-section" class="hidden mt-8 pt-5 border-t-2 border-pb">
      <h3 class="text-sm font-bold text-gray-700 mb-3">📚 Nguồn tham khảo</h3>
      <div id="sources-list" class="text-xs text-gray-500 space-y-1"></div>
    </div>
    <div id="disclaimer" class="hidden mt-5 text-xs text-gray-400 italic bg-gray-50 p-3 rounded-lg border border-gray-100">
      <strong>Lưu ý:</strong> Báo cáo tổng hợp tự động bởi AI, mang tính tham khảo. Ngày tạo: <span id="gen-date"></span>
    </div>
  </div>
</div>

<!-- Reports modal -->
<div id="reports-modal" class="hidden fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4 no-print">
  <div class="bg-white rounded-3xl shadow-2xl max-w-3xl w-full max-h-[85vh] flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between p-6 border-b border-gray-200">
      <div>
        <h3 class="text-xl font-bold text-gray-800">📂 Báo cáo đã lưu</h3>
        <p class="text-xs text-gray-500 mt-1">Sắp xếp từ mới nhất → cũ nhất</p>
      </div>
      <button onclick="closeReports()" class="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
    </div>
    <!-- Search box -->
    <div class="px-6 py-4 border-b border-gray-100">
      <input type="text" id="reports-search" placeholder="🔍 Tìm kiếm báo cáo theo tên ngành, công ty..."
        oninput="filterReports(this.value)"
        class="w-full px-4 py-2.5 rounded-xl border border-gray-300 focus:border-green-500 focus:ring-2 focus:ring-green-200 outline-none text-sm transition-all">
    </div>
    <!-- Report list (scrollable) -->
    <div class="flex-1 overflow-y-auto p-6">
      <div id="reports-list" class="space-y-2">
        <p class="text-sm text-gray-400">Đang tải...</p>
      </div>
    </div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
let mode = 'sector';

// ── Auth — JWT stored in localStorage ────────────────────────────────────────
function getToken() { return localStorage.getItem('sectortax_token') || ''; }
function setToken(t, username) {
  localStorage.setItem('sectortax_token', t);
  if(username) localStorage.setItem('sectortax_user', username);
}
function clearToken() {
  localStorage.removeItem('sectortax_token');
  localStorage.removeItem('sectortax_user');
}

function apiFetch(url, opts={}) {
  const token = getToken();
  if(!opts.headers) opts.headers = {};
  if(token) opts.headers['Authorization'] = 'Bearer ' + token;
  return fetch(url, opts).then(resp => {
    if(resp.status === 401) {
      clearToken();
      showLoginPage();
      throw new Error('Session expired. Please log in again.');
    }
    return resp;
  });
}

function showLoginPage() {
  document.getElementById('login-page').classList.remove('hidden');
}
function hideLoginPage() {
  document.getElementById('login-page').classList.add('hidden');
}
function showLogin() {
  document.getElementById('login-form-wrap').classList.remove('hidden');
  document.getElementById('register-form-wrap').classList.add('hidden');
  document.getElementById('login-err').classList.add('hidden');
}
function showRegister() {
  document.getElementById('login-form-wrap').classList.add('hidden');
  document.getElementById('register-form-wrap').classList.remove('hidden');
  document.getElementById('register-err').classList.add('hidden');
}

async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  const errEl = document.getElementById('login-err');
  errEl.classList.add('hidden');
  if(!username || !password) { errEl.textContent='Vui lòng nhập đầy đủ.'; errEl.classList.remove('hidden'); return; }
  const btn = document.getElementById('btn-login');
  btn.textContent = '⏳ Đang đăng nhập...'; btn.disabled = true;
  try {
    const fd = new FormData();
    fd.append('username', username); fd.append('password', password);
    const r = await fetch('/auth/login', {method:'POST', body: fd});
    if(r.ok) {
      const data = await r.json();
      setToken(data.access_token, data.username);
      hideLoginPage();
      initApp();
    } else {
      const err = await r.json().catch(()=>({detail:'Lỗi đăng nhập'}));
      errEl.textContent = err.detail || 'Sai tên đăng nhập hoặc mật khẩu';
      errEl.classList.remove('hidden');
    }
  } catch(e) {
    errEl.textContent = 'Lỗi kết nối: ' + e.message;
    errEl.classList.remove('hidden');
  } finally { btn.textContent='Đăng nhập'; btn.disabled=false; }
}

async function doRegister() {
  const username = document.getElementById('reg-user').value.trim();
  const password = document.getElementById('reg-pass').value;
  const email    = document.getElementById('reg-email').value.trim();
  const errEl = document.getElementById('register-err');
  errEl.classList.add('hidden');
  if(!username || !password) { errEl.textContent='Vui lòng nhập đầy đủ.'; errEl.classList.remove('hidden'); return; }
  const btn = document.getElementById('btn-register');
  btn.textContent = '⏳ Đang tạo...'; btn.disabled = true;
  try {
    const r = await fetch('/auth/register', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username, password, email})
    });
    if(r.ok) {
      const data = await r.json();
      setToken(data.access_token, data.username);
      hideLoginPage();
      initApp();
    } else {
      const err = await r.json().catch(()=>({detail:'Lỗi đăng ký'}));
      errEl.textContent = err.detail || 'Không tạo được tài khoản';
      errEl.classList.remove('hidden');
    }
  } catch(e) {
    errEl.textContent = 'Lỗi: ' + e.message;
    errEl.classList.remove('hidden');
  } finally { btn.textContent='Tạo tài khoản'; btn.disabled=false; }
}

function initApp() {
  // Called after successful login or if token already exists
  loadDefaultSections();
  loadReportsList().catch(()=>{});
}
let sections = [];
let isDone = false;
let dragSrc = null;

// ── Mode switch ───────────────────────────────────────────────────────────────
function setMode(m) {
  mode = m;
  document.getElementById('subject-sector').classList.toggle('hidden', m!=='sector');
  document.getElementById('subject-company').classList.toggle('hidden', m!=='company');
  document.getElementById('tab-sector').className  = (m==='sector'  ? 'tab-on' : 'tab-off') + ' text-sm px-4 py-2 rounded-lg font-semibold transition-colors';
  document.getElementById('tab-company').className = (m==='company' ? 'tab-on' : 'tab-off') + ' text-sm px-4 py-2 rounded-lg font-semibold transition-colors';
  loadDefaultSections();
}
function qs(s){ document.getElementById('sector-input').value=s; }

// ── Load default sections from server ─────────────────────────────────────────
async function loadDefaultSections() {
  const r = await apiFetch(`/default-sections?mode=${mode}`);
  sections = await r.json();
  renderSections();
}

function resetSections(){ loadDefaultSections(); }

// ── Section rendering ─────────────────────────────────────────────────────────
function renderSections() {
  const container = document.getElementById('sections-container');
  container.innerHTML = '';
  sections.forEach((sec, idx) => {
    const card = document.createElement('div');
    card.className = 'section-card';
    card.draggable = true;
    card.dataset.idx = idx;
    card.innerHTML = `
      <div class="flex items-start gap-2">
        <div class="cursor-grab text-gray-300 hover:text-gray-500 mt-1 select-none" title="Kéo để sắp xếp">⠿</div>
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs font-bold text-p bg-pl px-2 py-0.5 rounded">${idx+1}</span>
            <input type="text" value="${escHtml(sec.title)}" onchange="updateTitle(${idx},this.value)"
              class="flex-1 text-sm font-semibold text-gray-800 border-0 bg-transparent focus:outline-none focus:bg-gray-50 focus:px-2 rounded">
          </div>
          <div id="subs-${idx}" class="ml-5 space-y-1">
            ${(sec.sub||[]).map((s,si)=>subItemHtml(idx,si,s)).join('')}
          </div>
          <button onclick="addSub(${idx})" class="ml-5 mt-1 text-xs text-p hover:text-pd flex items-center gap-1">
            <span class="text-base leading-none">+</span> Thêm sub-item
          </button>
        </div>
        <button onclick="removeSection(${idx})" class="text-gray-300 hover:text-red-400 text-lg leading-none mt-0.5" title="Xoá phần này">×</button>
      </div>`;
    // Drag events
    card.addEventListener('dragstart', e => { dragSrc=idx; card.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; });
    card.addEventListener('dragend',   ()  => card.classList.remove('dragging'));
    card.addEventListener('dragover',  e   => { e.preventDefault(); e.dataTransfer.dropEffect='move'; });
    card.addEventListener('drop',      e   => { e.preventDefault(); if(dragSrc!==null && dragSrc!==idx){ moveSec(dragSrc,idx); } });
    container.appendChild(card);
  });
  updateEstimates();
  document.getElementById('section-count').textContent = `(${sections.length} phần)`;
}

function subItemHtml(idx, si, val) {
  return `<div class="sub-item" id="sub-${idx}-${si}">
    <span class="text-gray-300 text-xs select-none">•</span>
    <input type="text" value="${escHtml(val)}" onchange="updateSub(${idx},${si},this.value)" placeholder="Mô tả nội dung cần phân tích...">
    <button onclick="removeSub(${idx},${si})" class="text-gray-300 hover:text-red-400 text-sm leading-none flex-shrink-0">×</button>
  </div>`;
}

function escHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ── Section mutations ──────────────────────────────────────────────────────────
function updateTitle(idx, val){ sections[idx].title = val; updateEstimates(); }
function updateSub(idx, si, val){ sections[idx].sub[si] = val; }
function removeSub(idx, si){ sections[idx].sub.splice(si,1); renderSections(); }
function addSub(idx){ sections[idx].sub = sections[idx].sub||[]; sections[idx].sub.push(''); renderSections(); setTimeout(()=>{ const subs=document.querySelectorAll(`#subs-${idx} input`); if(subs.length) subs[subs.length-1].focus(); },50); }
function removeSection(idx){ sections.splice(idx,1); renderSections(); }
function addSection(){ sections.push({id:'custom_'+Date.now(), title:'Nội dung mới', sub:['']}); renderSections(); setTimeout(()=>{ const cards=document.querySelectorAll('.section-card'); const last=cards[cards.length-1]; if(last){ last.querySelector('input[type=text]').focus(); last.scrollIntoView({behavior:'smooth',block:'nearest'}); } },50); }
function moveSec(from, to){ const item=sections.splice(from,1)[0]; sections.splice(to,0,item); dragSrc=null; renderSections(); }

function updateEstimates(){
  const n = sections.length;
  // Legal sections (~60% of default sections) generate 2 queries each
  const LEGAL_KW = ['quy định','pháp lý','luật','thuế','công văn','tranh chấp','hóa đơn','hoá đơn','chuyển giá','giao dịch'];
  const legalCount = sections.filter(s => LEGAL_KW.some(kw => s.title.toLowerCase().includes(kw))).length;
  const totalQueries = n + legalCount; // extra query per legal section
  document.getElementById('est-time').textContent = Math.round(totalQueries * 15 + 30);
  document.getElementById('est-cost').textContent = (totalQueries * 0.008 + 0.04).toFixed(2);
}

// ── Research ──────────────────────────────────────────────────────────────────
function getSubject(){
  if(mode==='sector'){
    return document.getElementById('sector-input').value.trim();
  } else {
    const co = document.getElementById('company-input').value.trim();
    const sec = document.getElementById('sector-company-input').value.trim();
    return co && sec ? `${co} (ngành ${sec})` : (co || sec);
  }
}

function startResearch(){
  const subject = getSubject();
  if(!subject){ alert('Vui lòng nhập ngành hoặc tên công ty.'); return; }
  if(!sections.length){ alert('Vui lòng thêm ít nhất 1 phần báo cáo.'); return; }

  // Sync current input values to sections array
  document.querySelectorAll('.section-card').forEach((card, idx) => {
    const titleEl = card.querySelector('div.flex input[type=text]');
    if(titleEl) sections[idx].title = titleEl.value;
    const subEls = card.querySelectorAll('.sub-item input');
    sections[idx].sub = Array.from(subEls).map(el=>el.value).filter(v=>v.trim());
  });

  isDone = false;
  document.getElementById('progress-wrap').classList.remove('hidden');
  document.getElementById('report-wrap').classList.add('hidden');
  document.getElementById('report-content').innerHTML = '';
  document.getElementById('sources-section').classList.add('hidden');
  document.getElementById('disclaimer').classList.add('hidden');
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('status-text').textContent = 'Đang khởi động...';

  // Build dynamic step indicators
  const stepsEl = document.getElementById('steps-container');
  stepsEl.innerHTML = sections.map((sec,i) =>
    `<div id="step-${i+1}" class="flex items-center gap-2 text-xs text-gray-400 p-2 rounded-lg">
      <div class="step-dot w-5 h-5 rounded-full border-2 border-gray-300 flex-shrink-0 flex items-center justify-center text-xs font-bold">${i+1}</div>
      <span class="truncate">${escHtml(sec.title)}</span>
    </div>`
  ).join('') +
    `<div id="step-ai" class="flex items-center gap-2 text-xs text-gray-400 p-2 rounded-lg col-span-2">
      <div class="step-dot w-5 h-5 rounded-full border-2 border-gray-300 flex-shrink-0 flex items-center justify-center text-xs font-bold">AI</div>
      <span>Tổng hợp với Claude AI</span>
    </div>`;

  document.getElementById('report-title').textContent = `Phân Tích Thuế — ${subject}`;
  document.getElementById('report-date').textContent = new Date().toLocaleDateString('vi-VN',{year:'numeric',month:'long',day:'numeric'});

  const body = JSON.stringify({mode, subject, sections: sections.map(s=>({id:s.id,title:s.title,sub:s.sub||[]}))});
  startSSE(subject, body);
}


async function startSSE(subject, body) {
  let reportHtml = '';
  const MAX_RETRIES = 3;
  let attempt = 0;

  async function doStream() {
    const resp = await fetch('/stream', {
      method:'POST',
      credentials: 'include',
      headers:{'Content-Type':'application/json', 'Authorization':'Basic '+AUTH_CREDS},
      body
    });
    if(!resp.ok) throw new Error('HTTP ' + resp.status);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while(true) {
      const {done, value} = await reader.read();
      if(done) break;
      buf += decoder.decode(value, {stream:true});
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for(const part of parts){
        if(!part.startsWith('data:')) continue;
        let d; try{ d=JSON.parse(part.slice(5).trim()); } catch{ continue; }
        if(d.type==='ping') continue; // keepalive
        handleEvent(d, reportHtml, (h)=>{ reportHtml=h; });
      }
    }
  }

  try {
    while(attempt <= MAX_RETRIES) {
      try {
        await doStream();
        break;
      } catch(e) {
        attempt++;
        if(isDone) break;
        if(attempt > MAX_RETRIES) {
          document.getElementById('status-text').textContent = `Lỗi sau ${MAX_RETRIES} lần thử: ${e.message}`;
          break;
        }
        const retryMsg = reportHtml
          ? `Kết nối bị ngắt (lần ${attempt}/${MAX_RETRIES}), đang tiếp tục...`
          : `Lỗi kết nối (lần ${attempt}/${MAX_RETRIES}), thử lại...`;
        document.getElementById('status-text').textContent = retryMsg;
        if(!reportHtml) reportHtml = ''; // full restart if nothing received
        await new Promise(r=>setTimeout(r, 1500 * attempt));
      }
    }
    if(!isDone && reportHtml) finalize(reportHtml);
  } catch(e){
    document.getElementById('status-text').textContent = `Lỗi: ${e.message}`;
  }
}

function handleEvent(d, reportHtml, setHtml) {
  if(d.type==='status') document.getElementById('status-text').textContent = d.message;

  if(d.type==='progress'){
    if(d.step>1) setStepState(d.step-1,'done');
    setStepState(d.step,'active');
    const pct = Math.round(((d.step-1)/(d.total+1))*100);
    document.getElementById('progress-bar').style.width = pct+'%';
    document.getElementById('status-text').textContent = `Nghiên cứu: ${d.label}...`;
  }

  if(d.type==='ai_start'){
    for(let i=1;i<=d.total;i++) setStepState(i,'done');
    setStepState('ai','active');
    document.getElementById('progress-bar').style.width = '85%';
    document.getElementById('report-wrap').classList.remove('hidden');
  }

  if(d.type==='chunk'){
    reportHtml += d.text;
    setHtml(reportHtml);
    document.getElementById('report-content').innerHTML =
      reportHtml.replace(/```html\n?/g,'').replace(/```\n?/g,'');
  }

  if(d.type==='report'){
    document.getElementById('report-wrap').classList.remove('hidden');
    document.getElementById('report-content').innerHTML = d.html;
  }

  if(d.type==='citations') renderSources(d.urls||[]);

  if(d.type==='done'){ finalize(reportHtml); }

  if(d.type==='error') document.getElementById('status-text').textContent = `Lỗi: ${d.message}`;
}

let reportHtmlGlobal = '';
let subjectGlobal = '';

function finalize(reportHtml){
  isDone = true;
  reportHtmlGlobal = reportHtml;
  subjectGlobal = getSubject();
  setStepState('ai','done');
  document.getElementById('progress-bar').style.width='100%';
  document.getElementById('progress-wrap').classList.add('hidden');
  document.getElementById('disclaimer').classList.remove('hidden');
  document.getElementById('gen-date').textContent = new Date().toLocaleDateString('vi-VN');
  const c = document.getElementById('report-content');
  c.innerHTML = c.innerHTML.replace(/```html\n?/g,'').replace(/```\n?/g,'');
  buildTOC();
  initReadingProgress();
  setTimeout(()=>document.getElementById('report-wrap').scrollIntoView({behavior:'smooth',block:'start'}),300);
}

// ── TOC & Reading Progress ────────────────────────────────────────────────────
function buildTOC() {
  const headings = document.querySelectorAll('#report-content h2');
  if(headings.length < 2){ document.getElementById('toc-sidebar').style.display='none'; return; }
  const tocEl = document.getElementById('toc-items');
  tocEl.innerHTML = '';
  headings.forEach((h, i) => {
    const id = `section-${i}`;
    h.id = id;
    const a = document.createElement('a');
    a.className = 'toc-item';
    a.textContent = h.textContent.replace(/^\d+\.\s*/,'');
    a.href = `#${id}`;
    a.onclick = (e) => { e.preventDefault(); h.scrollIntoView({behavior:'smooth',block:'start'}); };
    tocEl.appendChild(a);
  });
  document.getElementById('toc-sidebar').style.display='block';
}

function initReadingProgress(){
  const bar = document.getElementById('reading-progress');
  const pctEl = document.getElementById('toc-pct');
  const tocItems = document.querySelectorAll('.toc-item');
  const headings = document.querySelectorAll('#report-content h2');

  window.addEventListener('scroll', () => {
    // Progress bar
    const scrollTop = window.scrollY;
    const docH = document.documentElement.scrollHeight - window.innerHeight;
    const pct = docH > 0 ? Math.round((scrollTop / docH) * 100) : 0;
    bar.style.width = pct + '%';
    if(pctEl) pctEl.textContent = pct;

    // Highlight active TOC item
    let active = 0;
    headings.forEach((h, i) => {
      if(h.getBoundingClientRect().top < 120) active = i;
    });
    tocItems.forEach((item, i) => {
      item.classList.toggle('active', i === active);
    });
  }, {passive:true});
}

function setStepState(n, state){
  const el = document.getElementById(`step-${n}`); if(!el) return;
  const dot = el.querySelector('.step-dot');
  el.classList.remove('step-done','step-active','text-gray-400');
  dot.classList.remove('dot-done','dot-active');
  if(state==='done')  { el.classList.add('step-done');   dot.classList.add('dot-done');   dot.innerHTML='✓'; }
  else if(state==='active'){ el.classList.add('step-active'); dot.classList.add('dot-active'); dot.innerHTML='⟳'; }
  else                { el.classList.add('text-gray-400'); }
}

function renderSources(urls){
  if(!urls?.length) return;
  document.getElementById('sources-section').classList.remove('hidden');
  document.getElementById('sources-count').textContent = `${urls.length} nguồn`;
  document.getElementById('sources-list').innerHTML = urls.map((u,i)=>{
    const d=u.replace(/^https?:\/\//,'').substring(0,90);
    return `<div class="flex gap-2"><span class="text-gray-400 shrink-0">[${i+1}]</span><a href="${u}" target="_blank" rel="noopener" class="text-p hover:opacity-80 underline break-all text-xs">${d}</a></div>`;
  }).join('');
}

// ── Font size ──────────────────────────────────────────────────────────────────
let fontSizeStep = 0; // steps from base
function changeFontSize(delta){
  fontSizeStep = Math.max(-3, Math.min(5, fontSizeStep + delta));
  const base = 1 + fontSizeStep * 0.06;
  const rc = document.getElementById('report-content');
  if(rc) rc.style.fontSize = base + 'rem';
  // Also adjust headings proportionally
  const style = document.getElementById('dynamic-font-style') || (() => {
    const s = document.createElement('style');
    s.id = 'dynamic-font-style';
    document.head.appendChild(s);
    return s;
  })();
  const h2size = (1.3 + fontSizeStep * 0.06).toFixed(2);
  const h3size = (1.1 + fontSizeStep * 0.06).toFixed(2);
  style.textContent = `#report-content h2{font-size:${h2size}rem!important} #report-content h3{font-size:${h3size}rem!important} #report-content li,#report-content td{font-size:${(0.95+fontSizeStep*0.06).toFixed(2)}rem!important}`;
}

function copyReport(){
  const t=document.getElementById('report-content').innerText;
  navigator.clipboard.writeText(t).then(()=>{
    const b=event.target; const o=b.textContent;
    b.textContent='✓ Đã copy!'; setTimeout(()=>b.textContent=o,2000);
  });
}

function resetForm(){
  document.getElementById('report-wrap').classList.add('hidden');
  document.getElementById('progress-wrap').classList.add('hidden');
  window.scrollTo({top:0,behavior:'smooth'});
}

// ── Export DOCX ──────────────────────────────────────────────────────────────
async function exportDocx(){
  const html = document.getElementById('report-content').innerHTML;
  const subject = subjectGlobal || document.getElementById('report-title').textContent || 'BaoCao';
  if(!html){ alert('Chưa có báo cáo.'); return; }
  const btn = document.getElementById('btn-docx');
  btn.textContent = '⏳ Đang xuất...';
  btn.disabled = true;
  try {
    const resp = await apiFetch('/docx', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({html, subject})
    });
    if(!resp.ok) {
      const errText = await resp.text();
      alert(`Không xuất được DOCX: ${errText}`);
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `TaxReport_${subject.slice(0,30)}_${new Date().toISOString().slice(0,10)}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch(e){ alert(`Lỗi xuất Word: ${e.message}`); }
  finally { btn.textContent='📄 Word'; btn.disabled=false; }
}

async function showReports(){
  document.getElementById('reports-modal').classList.remove('hidden');
  await loadReportsList();
}

let allReportsData = [];

const renderReportRow = f => {
  const displayName = (f.subject || f.name).replace(/\.html$/, '');
  const datePart = f.name.slice(0,8).replace(/(\d{4})(\d{2})(\d{2})/,'$3/$2/$1');
  const url = f.url || `/report/${f.name}`;
  return `
  <div class="flex items-center gap-2 bg-gray-50 p-3 rounded-xl border border-gray-200">
    <div class="flex-1 min-w-0">
      <div class="text-sm font-medium text-gray-800 truncate">${displayName}</div>
      <div class="text-xs text-gray-400">${datePart} · ${((f.size||0)/1024).toFixed(0)} KB</div>
    </div>
    <button onclick="openReportInApp('${f.name}')" class="text-xs bg-green-50 text-green-700 hover:bg-green-100 border border-green-200 px-2 py-1.5 rounded-lg font-medium flex-shrink-0">📂 Mở</button>
    <a href="${url}" target="_blank" class="text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 rounded-lg font-medium flex-shrink-0" title="Mở tab mới">↗</a>
    <button onclick="deleteReport('${f.name}')" class="text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 px-2 py-1.5 rounded-lg flex-shrink-0 transition-colors" title="Xóa báo cáo">🗑</button>
  </div>`;
};

function renderReportList(data, showAll=false) {
  const list = document.getElementById('reports-list');
  if(!data.length){ list.innerHTML='<p class="text-sm text-gray-400">Chưa có báo cáo nào.</p>'; return; }
  const LIMIT = 10;
  const display = showAll ? data : data.slice(0, LIMIT);
  let html = display.map(renderReportRow).join('');
  if(!showAll && data.length > LIMIT){
    html += `<div class="text-center pt-2">
      <button onclick="loadReportsList(true)" class="text-xs text-green-700 hover:text-green-900 border border-green-200 hover:bg-green-50 px-4 py-2 rounded-lg font-medium">
        📂 Xem thêm ${data.length - LIMIT} báo cáo
      </button></div>`;
  }
  list.innerHTML = html;
}

function filterReports(query) {
  if(!query.trim()) {
    renderReportList(allReportsData, false);
    return;
  }
  const q = query.toLowerCase();
  const filtered = allReportsData.filter(f =>
    (f.subject || f.name || '').toLowerCase().includes(q) ||
    f.name.toLowerCase().includes(q)
  );
  renderReportList(filtered, true);
}

async function loadReportsList(showAll=false){
  const list=document.getElementById('reports-list');
  list.innerHTML='<p class="text-sm text-gray-400">Đang tải...</p>';
  const searchEl = document.getElementById('reports-search');
  if(searchEl) searchEl.value = '';
  try{
    const resp = await apiFetch('/reports');
    if(!resp || !resp.ok) { list.innerHTML='<p class="text-sm text-red-400">Không tải được danh sách.</p>'; return; }
    const data = await resp.json();
    data.sort((a,b)=>(b.mtime||0)-(a.mtime||0));
    allReportsData = data;
    // Update badge count on main screen button
    const badge = document.getElementById('reports-count-badge');
    if(badge) badge.textContent = data.length ? `(${data.length})` : '';
    renderReportList(data, showAll);
  } catch(e){ list.innerHTML=`<p class="text-sm text-red-500">Lỗi: ${e.message}</p>`; }
}

// Open saved report inside the main app (full toolbar, font controls, dashboard, slides)
async function openReportInApp(fname){
  closeReports();
  try {
    const resp = await apiFetch(`/report/${encodeURIComponent(fname)}`);
    if(!resp.ok) throw new Error('Không tải được báo cáo');
    const savedHtml = await resp.text();
    const parser = new DOMParser();
    const savedDoc = parser.parseFromString(savedHtml, 'text/html');
    // Extract report content inner HTML
    const reportDiv = savedDoc.querySelector('#report-content');
    const reportInner = reportDiv ? reportDiv.innerHTML : savedDoc.body.innerHTML;
    // Extract subject from title or filename
    const titleEl = savedDoc.querySelector('h1');
    const savedTitle = titleEl
      ? titleEl.textContent.replace(/^Phân Tích Thuế\s*[—-]\s*/,'').trim()
      : fname.replace(/^\d+ - /,'').replace(/ - \d+\.html$/,'');
    // Extract citation URLs
    const sourceLinks = [...new Set(Array.from(savedDoc.querySelectorAll('a[href^="http"]')).map(a=>a.href))];
    // Load into app UI
    subjectGlobal = savedTitle;
    reportHtmlGlobal = reportInner;
    isDone = true;
    document.getElementById('report-wrap').classList.remove('hidden');
    document.getElementById('report-title').textContent = 'Phân Tích Thuế — ' + savedTitle;
    const datePart = fname.slice(0,8).replace(/(\d{4})(\d{2})(\d{2})/,'$3/$2/$1');
    document.getElementById('report-date').textContent = datePart + ' · đã lưu · Perplexity + Claude AI';
    document.getElementById('progress-wrap').classList.add('hidden');
    document.getElementById('disclaimer').classList.remove('hidden');
    document.getElementById('gen-date').textContent = datePart;
    const c = document.getElementById('report-content');
    c.innerHTML = reportInner;
    c.innerHTML = c.innerHTML.replace(/```html\n?/g,'').replace(/```\n?/g,'');
    if(sourceLinks.length){
      document.getElementById('sources-count').textContent = sourceLinks.length + ' nguồn';
      const sl = document.getElementById('sources-list');
      sl.innerHTML = sourceLinks.slice(0,60).map((u,i)=>`<div><span class="text-green-700 font-bold">[${i+1}]</span> <a href="${u}" target="_blank" class="hover:underline break-all text-xs">${u}</a></div>`).join('');
      document.getElementById('sources-section').classList.remove('hidden');
    }
    buildTOC();
    initReadingProgress();
    window.scrollTo({top:0, behavior:'smooth'});
  } catch(e){ alert('Lỗi mở báo cáo: ' + e.message); }
}

async function deleteReport(fname){
  if(!confirm(`Xóa báo cáo "${fname.replace('.html','')}"?`)) return;
  try{
    const r = await apiFetch(`/report/${encodeURIComponent(fname)}`, {method:'DELETE'});
    if(r.ok){ await loadReportsList(); }
    else{ alert('Không xóa được báo cáo.'); }
  } catch(e){ alert(`Lỗi: ${e.message}`); }
}

function closeReports(){ document.getElementById('reports-modal').classList.add('hidden'); }


// ── Dashboard ────────────────────────────────────────────────────────────────
function openDashboard(){
  const html = document.getElementById('report-content').innerHTML;
  const subject = subjectGlobal || document.getElementById('report-title').textContent || 'Báo cáo';
  const genDate = new Date().toLocaleDateString('vi-VN');

  const parser = new DOMParser();
  const doc = parser.parseFromString('<div>'+html+'</div>', 'text/html');

  // Extract sections (h2)
  const sections = Array.from(doc.querySelectorAll('h2')).map(h=>h.textContent.trim());

  // Extract tables
  const tables = Array.from(doc.querySelectorAll('table')).map(t=>t.outerHTML);

  // Extract risk items (keywords)
  const riskKW = ['rủi ro','tranh chấp','phạt','vi phạm','thanh tra','truy thu','cưỡng chế','xử phạt'];
  const allText = doc.body.innerText || doc.body.textContent || '';
  const sentences = allText.split(/[.!?\n]/).filter(s=>s.trim().length>20);
  const riskItems = sentences.filter(s=>riskKW.some(k=>s.toLowerCase().includes(k))).slice(0,10);

  // Extract numbers/metrics
  const numRegex = /(\d[\d,.]*\s*(?:tỷ|nghìn tỷ|triệu|%|USD|VND|tỷ đồng|nghìn|năm))/gi;
  const nums = [...new Set((allText.match(numRegex)||[]).slice(0,12))];

  // Count regulations
  const regCount = (allText.match(/\b(?:Luật|Nghị định|Thông tư|Quyết định|Công văn)\s+(?:số\s+)?\d+/gi)||[]).length;

  // Build section cards HTML
  const sectionCards = sections.map((s,i)=>`
    <div class="bg-white rounded-xl border border-gray-200 p-4 hover:border-green-400 hover:shadow-md transition-all cursor-pointer" onclick="scrollToSection(${i})">
      <div class="text-xs font-bold text-green-700 mb-1">Phần ${i+1}</div>
      <div class="text-sm font-semibold text-gray-800 leading-snug">${s.replace(/^\d+\.\s*/,'')}</div>
    </div>`).join('');

  // Build metrics
  const metricItems = [
    {icon:'📋', label:'Phần báo cáo', val: sections.length},
    {icon:'📜', label:'Văn bản PL trích dẫn', val: regCount || 'N/A'},
    {icon:'⚠️', label:'Điểm rủi ro', val: riskItems.length},
    {icon:'🔢', label:'Số liệu tham chiếu', val: nums.length},
  ];
  const metricsHTML = metricItems.map(m=>`
    <div class="bg-white rounded-xl border border-gray-200 p-5 text-center">
      <div class="text-3xl mb-2">${m.icon}</div>
      <div class="text-3xl font-bold text-green-700">${m.val}</div>
      <div class="text-xs text-gray-500 mt-1">${m.label}</div>
    </div>`).join('');

  // Risk cards
  const riskHTML = riskItems.length ? riskItems.map(r=>`
    <div class="flex gap-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
      <span class="text-amber-500 flex-shrink-0">⚠️</span>
      <p class="text-sm text-amber-900 leading-relaxed">${r.trim()}</p>
    </div>`).join('') :
    '<p class="text-sm text-gray-400 italic">Không phát hiện điểm rủi ro nổi bật.</p>';

  // Tables HTML
  const tablesHTML = tables.length ? tables.map((t,i)=>`
    <div class="mb-6">
      <div class="text-xs font-bold text-gray-500 mb-2">Bảng ${i+1}</div>
      <div class="overflow-x-auto rounded-xl border border-gray-200">${t}</div>
    </div>`).join('') :
    '<p class="text-sm text-gray-400 italic">Không có bảng dữ liệu.</p>';

  // Numbers list
  const numsHTML = nums.length ? `<div class="flex flex-wrap gap-2">${nums.map(n=>`<span class="bg-green-50 text-green-800 border border-green-200 rounded-full px-3 py-1 text-xs font-semibold">${n.trim()}</span>`).join('')}</div>` :
    '<p class="text-sm text-gray-400 italic">Không trích xuất được số liệu.</p>';

  const dashHTML = `<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard — ${subject}</title>
<script src="https://cdn.tailwindcss.com"><\/script>
<style>
  body{font-family:Arial,sans-serif;background:#f9fafb}
  table{width:100%;border-collapse:collapse;font-size:.9rem}
  th{background:#028a39;color:#fff;padding:.5rem .75rem;text-align:left;font-size:.82rem}
  td{padding:.45rem .75rem;border-bottom:1px solid #e5e7eb;font-size:.88rem;vertical-align:top}
  tr:nth-child(even) td{background:#f0fdf4}
</style></head>
<body class="p-6 max-w-6xl mx-auto">
  <div class="bg-gradient-to-r from-green-700 to-green-500 text-white rounded-2xl p-8 mb-6">
    <div class="text-xs font-bold opacity-70 uppercase tracking-widest mb-2">📊 Visual Dashboard · Tax Research</div>
    <h1 class="text-2xl font-bold mb-1">${subject}</h1>
    <div class="text-green-100 text-sm">${genDate} · Perplexity + Claude AI</div>
  </div>

  <div class="grid grid-cols-4 gap-4 mb-6">${metricsHTML}</div>

  <div class="grid grid-cols-3 gap-6 mb-6">
    <div class="col-span-2 bg-white rounded-2xl border border-gray-200 p-5">
      <h2 class="text-base font-bold text-gray-700 mb-4">📑 Các phần báo cáo</h2>
      <div class="grid grid-cols-2 gap-3">${sectionCards}</div>
    </div>
    <div class="bg-white rounded-2xl border border-gray-200 p-5">
      <h2 class="text-base font-bold text-gray-700 mb-4">🔢 Số liệu nổi bật</h2>
      ${numsHTML}
    </div>
  </div>

  <div class="bg-white rounded-2xl border border-gray-200 p-5 mb-6">
    <h2 class="text-base font-bold text-gray-700 mb-4">📋 Bảng dữ liệu từ báo cáo</h2>
    ${tablesHTML}
  </div>

  <div class="bg-white rounded-2xl border border-gray-200 p-5 mb-6">
    <h2 class="text-base font-bold text-amber-700 mb-4">⚠️ Điểm rủi ro & Lưu ý</h2>
    <div class="space-y-2">${riskHTML}</div>
  </div>

  <div class="text-xs text-gray-400 text-center py-4">Dashboard tự động từ Tax Sector Research Tool · ${genDate}</div>
</body></html>`;

  const w = window.open('','_blank');
  w.document.write(dashHTML);
  w.document.close();
}

// ── Slides ────────────────────────────────────────────────────────────────────
async function openSlides(){
  const html = document.getElementById('report-content').innerHTML;
  const subject = subjectGlobal || document.getElementById('report-title').textContent || 'Báo cáo';
  if(!html){ alert('Chưa có báo cáo để tạo slides.'); return; }

  const btn = document.getElementById('btn-slides');
  btn.textContent = '⏳ Đang tạo...';
  btn.disabled = true;

  try {
    const resp = await apiFetch('/slides', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({html, subject})
    });
    if(!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const slidesHtml = await resp.text();
    const w = window.open('','_blank');
    w.document.write(slidesHtml);
    w.document.close();
  } catch(e){
    alert(`Không tạo được slides: ${e.message}`);
  } finally {
    btn.textContent = '📑 Slides';
    btn.disabled = false;
  }
}


// ── Legal Appendix ────────────────────────────────────────────────────────────
async function openAppendix(){
  const subject = subjectGlobal || document.getElementById('subject-input')?.value || '';
  const btn = document.getElementById('btn-appendix');
  btn.textContent = '⏳ Đang tạo...';
  btn.disabled = true;
  try {
    const resp = await apiFetch('/legal-appendix', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({subject: subject, report_html: document.getElementById('report-content')?.innerHTML || ''})
    });
    if(!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    // Show in modal or new window
    const w = window.open('','_blank');
    w.document.write('<html><body style="font-family:sans-serif;padding:24px">' + data.appendix_html + '</body></html>');
    w.document.close();
  } catch(e){
    alert('Không tạo được Appendix: ' + e.message);
  } finally {
    btn.textContent = '📋 Appendix';
    btn.disabled = false;
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  const token = getToken();
  if(token) {
    // Verify token is still valid
    apiFetch('/auth/me').then(r => {
      if(r && r.ok) {
        initApp();
      } else {
        showLoginPage();
      }
    }).catch(() => {
      // If /auth/me fails (network), still try to use cached token
      initApp();
    });
  } else {
    showLoginPage();
  }
});
</script>
</body>
</html>"""



# ─────────────────────────────────────────────────────────────────────────────
# LEGAL REFERENCES API — Văn bản pháp luật liên quan đến chủ đề
# ─────────────────────────────────────────────────────────────────────────────

import urllib.request as _urllib_req

LEGAL_DB_URL = "https://raw.githubusercontent.com/phanvuhoang/taxsector/main/legal_db.json"

# Embedded fallback DB (top key docs per category)
LEGAL_DB_EMBEDDED = {
    "CIT": [
        {"so_hieu": "14/2008/QH12", "ten": "Luật Thuế Thu nhập Doanh nghiệp 2008 (đã sửa đổi)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-thue-thu-nhap-doanh-nghiep-2008-14-2008-QH12-85986.aspx"},
        {"so_hieu": "218/2013/NĐ-CP", "ten": "NĐ 218/2013 hướng dẫn Luật Thuế TNDN", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-218-2013-ND-CP-huong-dan-Luat-thue-thu-nhap-doanh-nghiep-216979.aspx"},
        {"so_hieu": "96/2015/TT-BTC", "ten": "TT 96/2015 về chi phí được trừ CIT", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-96-2015-TT-BTC-huong-dan-thue-thu-nhap-doanh-nghiep-286266.aspx"},
    ],
    "VAT": [
        {"so_hieu": "48/2024/QH15", "ten": "Luật Thuế GTGT 2024 (MỚI — hiệu lực 01/07/2025)", "tinh_trang": "Hiệu lực từ 01/07/2025", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-Thue-gia-tri-gia-tang-2024-48-2024-QH15-634509.aspx"},
        {"so_hieu": "219/2013/TT-BTC", "ten": "TT 219/2013 hướng dẫn Luật Thuế GTGT", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-219-2013-TT-BTC-huong-dan-Luat-Thue-gia-tri-gia-tang-220100.aspx"},
    ],
    "PIT": [
        {"so_hieu": "04/2007/QH12", "ten": "Luật Thuế Thu nhập Cá nhân 2007 (đã sửa đổi)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-Thue-thu-nhap-ca-nhan-2007-04-2007-QH12-65387.aspx"},
        {"so_hieu": "NQ 954/2020", "ten": "NQ 954/2020 — Giảm trừ gia cảnh: bản thân 11tr, phụ thuộc 4.4tr/tháng", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-quyet-954-2020-UBTVQH14-dieu-chinh-muc-giam-tru-gia-canh-thue-thu-nhap-ca-nhan-444439.aspx"},
        {"so_hieu": "111/2013/TT-BTC", "ten": "TT 111/2013 hướng dẫn Luật Thuế TNCN", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-111-2013-TT-BTC-huong-dan-Luat-Thue-thu-nhap-ca-nhan-201324.aspx"},
    ],
    "TransferPricing": [
        {"so_hieu": "132/2020/NĐ-CP", "ten": "NĐ 132/2020 — Quản lý thuế giao dịch liên kết (HIỆN HÀNH)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-132-2020-ND-CP-quan-ly-thue-doanh-nghiep-giao-dich-lien-ket-459208.aspx"},
        {"so_hieu": "45/2021/TT-BTC", "ten": "TT 45/2021 hướng dẫn NĐ 132/2020 về chuyển giá", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-45-2021-TT-BTC-huong-dan-Nghi-dinh-132-2020-ND-CP-giao-dich-lien-ket-481827.aspx"},
        {"so_hieu": "20/2017/NĐ-CP", "ten": "NĐ 20/2017 ⛔ ĐÃ HẾT HIỆU LỰC — thay bởi NĐ 132/2020", "tinh_trang": "HẾT HIỆU LỰC", "link": ""},
    ],
    "TaxAdmin": [
        {"so_hieu": "38/2019/QH14", "ten": "Luật Quản lý Thuế 2019 (hiệu lực 01/07/2020)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-Quan-ly-thue-2019-38-2019-QH14-393760.aspx"},
        {"so_hieu": "126/2020/NĐ-CP", "ten": "NĐ 126/2020 hướng dẫn Luật Quản lý Thuế", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-126-2020-ND-CP-huong-dan-Luat-quan-ly-thue-457344.aspx"},
        {"so_hieu": "80/2021/TT-BTC", "ten": "TT 80/2021 hướng dẫn kê khai, nộp thuế, hoàn thuế", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-80-2021-TT-BTC-huong-dan-Luat-Quan-ly-thue-Nghi-dinh-126-2020-ND-CP-491201.aspx"},
    ],
    "FCT": [
        {"so_hieu": "103/2014/TT-BTC", "ten": "TT 103/2014 — Thuế nhà thầu nước ngoài (HIỆN HÀNH)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-103-2014-TT-BTC-huong-dan-thuc-hien-nghia-vu-thue-ap-dung-doi-voi-to-chuc-ca-nhan-nuoc-ngoai-238461.aspx"},
    ],
    "HoaDon": [
        {"so_hieu": "123/2020/NĐ-CP", "ten": "NĐ 123/2020 — Hóa đơn, chứng từ (bắt buộc từ 01/07/2022)", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Nghi-dinh-123-2020-ND-CP-hoa-don-chung-tu-457339.aspx"},
        {"so_hieu": "78/2021/TT-BTC", "ten": "TT 78/2021 hướng dẫn hóa đơn điện tử", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-78-2021-TT-BTC-huong-dan-Nghi-dinh-123-2020-ND-CP-hoa-don-chung-tu-491185.aspx"},
    ],
    "InternationalTax": [
        {"so_hieu": "205/2013/TT-BTC", "ten": "TT 205/2013 hướng dẫn áp dụng Hiệp định tránh đánh thuế hai lần", "tinh_trang": "Còn hiệu lực", "link": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Thong-tu-205-2013-TT-BTC-huong-dan-Hiep-dinh-tranh-danh-thue-hai-lan-220619.aspx"},
        {"so_hieu": "NQ 107/2023/QH15", "ten": "NQ 107/2023 — Thuế tối thiểu toàn cầu Pillar 2 (15%) từ 2024", "tinh_trang": "Còn hiệu lực", "link": ""},
    ],
    "DatDai": [
        {"so_hieu": "31/2024/QH15", "ten": "Luật Đất đai 2024 — hiệu lực 01/08/2024, ảnh hưởng lớn BĐS", "tinh_trang": "Còn hiệu lực từ 01/08/2024", "link": "https://thuvienphapluat.vn/van-ban/Bat-dong-san/Luat-Dat-dai-2024-31-2024-QH15-571019.aspx"},
        {"so_hieu": "48/2010/QH12", "ten": "Luật Thuế sử dụng đất phi nông nghiệp", "tinh_trang": "Còn hiệu lực", "link": ""},
    ],
}

# Keyword → category mapping
LEGAL_KEYWORD_MAP = {
    "cit": ["CIT"], "thuế tndn": ["CIT"], "thu nhập doanh nghiệp": ["CIT"], "corporate": ["CIT"],
    "vat": ["VAT"], "gtgt": ["VAT"], "giá trị gia tăng": ["VAT"], "value added": ["VAT"],
    "pit": ["PIT"], "tncn": ["PIT"], "thu nhập cá nhân": ["PIT"], "personal income": ["PIT"],
    "chuyển giá": ["TransferPricing"], "transfer pricing": ["TransferPricing"], "giao dịch liên kết": ["TransferPricing"],
    "nhà thầu": ["FCT"], "foreign contractor": ["FCT"], "fct": ["FCT"], "withholding": ["FCT"],
    "hóa đơn": ["HoaDon"], "invoice": ["HoaDon"], "chứng từ": ["HoaDon"],
    "quản lý thuế": ["TaxAdmin"], "kê khai": ["TaxAdmin"], "hoàn thuế": ["TaxAdmin"],
    "hiệp định": ["InternationalTax"], "dta": ["InternationalTax"], "tax treaty": ["InternationalTax"], "pillar": ["InternationalTax"], "tối thiểu": ["InternationalTax"],
    "đất đai": ["DatDai"], "bất động sản": ["DatDai"], "real estate": ["DatDai"], "bds": ["DatDai"],
    "tiêu thụ đặc biệt": ["SCT"], "excise": ["SCT"],
    "hộ kinh doanh": ["HoaDon", "PIT"], "hộ kd": ["HoaDon", "PIT"], "thuế khoán": ["PIT"],
}

def get_relevant_legal_cats(subject: str, sections: list = None) -> list:
    """Determine relevant legal categories from subject/sections."""
    subject_lower = subject.lower()
    cats = set()
    for kw, cat_list in LEGAL_KEYWORD_MAP.items():
        if kw in subject_lower:
            cats.update(cat_list)
    # Always include TaxAdmin for tax research
    if cats:
        cats.add("TaxAdmin")
    return list(cats) if cats else list(LEGAL_DB_EMBEDDED.keys())

@app.get("/legal-refs")
async def get_legal_refs(
    subject: str = "",
    cats: str = "",
    user: dict = Depends(get_current_user)
):
    """Return relevant legal references for a given subject."""
    if cats:
        selected_cats = [c.strip() for c in cats.split(",") if c.strip() in LEGAL_DB_EMBEDDED]
    else:
        selected_cats = get_relevant_legal_cats(subject)

    result = {}
    for cat in selected_cats:
        if cat in LEGAL_DB_EMBEDDED:
            result[cat] = LEGAL_DB_EMBEDDED[cat]

    return JSONResponse({"subject": subject, "categories": selected_cats, "refs": result})

@app.post("/legal-appendix")
async def generate_legal_appendix(request_body: dict, user: dict = Depends(get_current_user)):
    """Generate HTML appendix with legal references for a report subject."""
    subject = request_body.get("subject", "")
    cats = request_body.get("cats", "")
    report_html = request_body.get("report_html", "")

    if cats:
        selected_cats = [c.strip() for c in cats.split(",") if c.strip() in LEGAL_DB_EMBEDDED]
    else:
        selected_cats = get_relevant_legal_cats(subject)

    # Build appendix HTML
    cat_labels = {
        "CIT": "Thuế Thu nhập Doanh nghiệp (CIT)",
        "VAT": "Thuế Giá trị Gia tăng (VAT/GTGT)",
        "PIT": "Thuế Thu nhập Cá nhân (PIT/TNCN)",
        "TransferPricing": "Chuyển giá / Giao dịch liên kết",
        "TaxAdmin": "Quản lý Thuế",
        "FCT": "Thuế Nhà thầu Nước ngoài (FCT)",
        "HoaDon": "Hóa đơn & Chứng từ",
        "InternationalTax": "Thuế Quốc tế / Tax Treaty",
        "DatDai": "Thuế Đất đai & Bất động sản",
        "SCT": "Thuế Tiêu thụ Đặc biệt (SCT)",
    }

    rows_html = ""
    for cat in selected_cats:
        docs = LEGAL_DB_EMBEDDED.get(cat, [])
        if not docs:
            continue
        label = cat_labels.get(cat, cat)
        for doc in docs:
            status_color = "#dc2626" if "HẾT HIỆU LỰC" in doc.get("tinh_trang","") else "#16a34a"
            link = doc.get("link","")
            sh = doc.get("so_hieu","")
            sh_html = f'<a href="{link}" target="_blank" style="color:#1d4ed8">{sh}</a>' if link else sh
            rows_html += f"""
            <tr>
              <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-weight:500;white-space:nowrap">{label}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;white-space:nowrap">{sh_html}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;font-size:13px">{doc.get("ten","")}</td>
              <td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;color:{status_color};white-space:nowrap;font-size:12px">{doc.get("tinh_trang","")}</td>
            </tr>"""

    from datetime import datetime
    gen_date = datetime.now().strftime("%d/%m/%Y")
    appendix_html = f"""
<div style="margin-top:32px;padding:24px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;font-family:sans-serif">
  <h2 style="font-size:16px;font-weight:700;color:#1e40af;margin:0 0 4px 0">📋 PHỤ LỤC — Văn bản Pháp quy Áp dụng</h2>
  <p style="font-size:12px;color:#64748b;margin:0 0 16px 0">Chủ đề: <strong>{subject}</strong> · Tổng hợp: ThanhAI · {gen_date}</p>
  <table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff">
    <thead>
      <tr style="background:#1e40af;color:#fff">
        <th style="padding:8px;text-align:left">Lĩnh vực</th>
        <th style="padding:8px;text-align:left">Số hiệu</th>
        <th style="padding:8px;text-align:left">Tên văn bản</th>
        <th style="padding:8px;text-align:left">Tình trạng</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="font-size:11px;color:#94a3b8;margin:12px 0 0 0">
    ⚠️ Thông tin tham khảo. Vui lòng kiểm tra trạng thái hiệu lực tại
    <a href="https://thuvienphapluat.vn" target="_blank">thuvienphapluat.vn</a> hoặc
    <a href="https://vbpl.vn" target="_blank">vbpl.vn</a>
  </p>
</div>"""

    return JSONResponse({"appendix_html": appendix_html, "categories": selected_cats})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
