# CLAUDE.md — Instructions for Claude Code

This file guides Claude Code when working on the `taxsector` project.
Read this file first before making any changes.

---

## Task: Apply 2 upgrades to `main.py`

### Upgrade 1: Switch from Claudible to Anthropic native SDK

**Why:** Claudible (OpenAI-compatible wrapper) truncates long streaming responses.
Anthropic native SDK supports up to 8192 tokens per section without cutoff.

#### requirements.txt
Add this line:
```
anthropic==0.49.0
```

#### main.py — Config section
Replace:
```python
CLAUDE_KEY     = os.getenv("CLAUDIBLE_API_KEY", "")
CLAUDE_URL     = os.getenv("CLAUDIBLE_BASE_URL", "https://claudible.io/v1")
CLAUDE_MODEL   = os.getenv("CLAUDIBLE_MODEL", "claude-sonnet-4.6")
```
With:
```python
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
```

#### main.py — imports
Add at the top with other imports:
```python
import anthropic
```

#### main.py — Replace `claude_stream_section()` entirely
```python
async def claude_stream_section(
    section: dict, subject: str, context: str, mode: str, num: int
) -> AsyncGenerator[str, None]:
    if not ANTHROPIC_KEY:
        yield f"<h2>{num}. {section['title']}</h2><p><em>[Anthropic API key not configured]</em></p>"
        return

    prompt = build_section_prompt(section, subject, context, mode, num)
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)

    try:
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f'<p style="color:red">[Error in section {num}: {e}]</p>'
```

#### main.py — Replace Claude call in `suggest_subsections` endpoint
Find the block that calls `CLAUDE_URL/chat/completions` and replace with:
```python
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
    try:
        msg = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text
```
Also update the guard: replace `if not CLAUDE_KEY` → `if not ANTHROPIC_KEY`.

#### main.py — Replace Claude call in `generate_slides` endpoint
Find the block that calls `CLAUDE_URL/chat/completions` and replace with:
```python
    if not ANTHROPIC_KEY:
        raise HTTPException(503, "Anthropic API not configured")
    ...
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    slides_html = msg.content[0].text
```

#### main.py — Update `/health` endpoint
```python
@app.get("/health")
def health(_user: str = Depends(auth)):
    return {
        "status": "ok",
        "model": CLAUDE_MODEL,
        "anthropic_configured": bool(ANTHROPIC_KEY),
        "perplexity_configured": bool(PERPLEXITY_KEY),
        "tvpl_scraper": "enabled",
    }
```

---

### Upgrade 2: Add thuvienphapluat.vn legal document scraper

**Why:** Perplexity is weak on Vietnamese legal/tax regulations.
This scraper fetches real, currently-in-effect legal documents directly from
thuvienphapluat.vn (Vietnam's authoritative legal database) and injects them
into Claude's context for sections about law/tax.

#### main.py — Add after the Perplexity section (`# ── Research: Perplexity ──`)

Add these two blocks:

**Block A — helper `is_legal_or_tax_section()`** (add before `filter_context()`):
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
    ]
    return any(kw in title + " " + subs for kw in keywords)
```

**Block B — `build_tvpl_query()`, `tvpl_search()`, `format_tvpl_results()`**
(add in `# ── Research: thuvienphapluat.vn ──` block):
```python
# ── Research: thuvienphapluat.vn ─────────────────────────────────────────────
TVPL_BASE = "https://thuvienphapluat.vn"

def build_tvpl_query(section: dict, subject: str) -> str:
    title = section.get("title", "").lower()
    subs  = " ".join(section.get("sub", [])).lower()
    kw_map = {
        "thuế gtgt": "thuế giá trị gia tăng",
        "thuế tndn": "thuế thu nhập doanh nghiệp",
        "thuế ttđb": "thuế tiêu thụ đặc biệt",
        "thuế xnk": "thuế xuất nhập khẩu",
        "nhà thầu": "thuế nhà thầu",
        "chuyển giá": "chuyển giá",
        "ưu đãi": f"ưu đãi thuế {subject}",
        "thuế": f"thuế {subject}",
        "pháp lý": subject,
        "luật": subject,
        "quy định": subject,
    }
    for kw, q in kw_map.items():
        if kw in title or kw in subs:
            return q
    return subject


async def tvpl_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Scrape thuvienphapluat.vn for currently-in-effect legal documents.
    Returns list of {title, url, doc_type, issued_date, issuer, status}.
    """
    params = {
        "q": query,
        "sbt": "0",   # sort by relevance
        "efts": "1",  # còn hiệu lực only
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Referer": TVPL_BASE,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:
        try:
            r = await client.get(
                f"{TVPL_BASE}/van-ban-phap-luat.aspx",
                params=params,
                headers=headers,
            )
            r.raise_for_status()
        except Exception as e:
            return [{"error": str(e)}]

    soup = BeautifulSoup(r.text, "lxml")
    results = []

    # Try multiple selectors — TVPL may change structure
    items = (
        soup.select("div.doc-item") or
        soup.select("ul.result-list > li") or
        soup.select(".document-list .item") or
        soup.select("table.list-vb tr") or
        soup.select("a[href*='/van-ban/']")
    )

    doc_types = [
        "Luật", "Nghị định", "Thông tư", "Quyết định",
        "Nghị quyết", "Chỉ thị", "Công văn", "Pháp lệnh",
        "Hiệp định", "Thông tư liên tịch", "Nghị quyết liên tịch",
    ]
    issuers = [
        "Quốc hội", "Chính phủ", "Bộ Tài chính", "Bộ Kế hoạch và Đầu tư",
        "Tổng cục Thuế", "Bộ Công Thương", "Ngân hàng Nhà nước",
        "Bộ Lao động", "UBND", "Bộ Xây dựng",
    ]

    for item in items[:max_results]:
        doc = {}
        link = item.select_one("a[href*='/van-ban/']") or (item if item.name == "a" else None)
        if not link:
            continue
        doc["title"] = link.get_text(strip=True)
        href = link.get("href", "")
        doc["url"] = href if href.startswith("http") else f"{TVPL_BASE}{href}"
        if not doc["title"] or not doc["url"]:
            continue

        meta = item.get_text(" ", strip=True)
        doc["doc_type"] = next((t for t in doc_types if t in doc["title"]), "Văn bản")
        date_m = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', meta)
        doc["issued_date"] = date_m.group(1) if date_m else ""
        doc["issuer"] = next((i for i in issuers if i in meta), "")
        doc["status"] = "Còn hiệu lực"
        results.append(doc)

    return results


def format_tvpl_results(docs: list[dict]) -> str:
    """Format TVPL docs as context text for Claude."""
    valid = [d for d in docs if "error" not in d and d.get("title")]
    if not valid:
        return ""
    lines = ["=== VĂN BẢN PHÁP LUẬT HIỆN HÀNH (nguồn: thuvienphapluat.vn) ===\n"]
    for i, d in enumerate(valid, 1):
        lines.append(
            f"{i}. [{d['doc_type']}] {d['title']}\n"
            f"   URL: {d['url']}\n"
            f"   Ban hành: {d.get('issued_date','')} | "
            f"Cơ quan: {d.get('issuer','')} | Trạng thái: Còn hiệu lực\n"
        )
    return "\n".join(lines)
```

#### main.py — Update Phase 1 inside `generate()` to run TVPL in parallel

In the `generate()` async function, find the Phase 1 loop and update it so
each batch runs `tvpl_search` in parallel with `perplexity_search`:

```python
        # Phase 1: parallel research — Perplexity + thuvienphapluat.vn
        all_results: dict = {}
        all_tvpl: dict = {}
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

            perplexity_tasks = [
                perplexity_search(build_query(s, subject, mode), sonar)
                for s in batch
            ]
            tvpl_tasks = [
                tvpl_search(build_tvpl_query(s, subject))
                if is_legal_or_tax_section(s)
                else asyncio.coroutine(lambda: [])()
                for s in batch
            ]

            perplexity_results, tvpl_results = await asyncio.gather(
                asyncio.gather(*perplexity_tasks),
                asyncio.gather(*tvpl_tasks),
            )

            for sec, pres, tres in zip(batch, perplexity_results, tvpl_results):
                all_results[sec["id"]] = pres
                all_tvpl[sec["id"]]    = tres or []
                all_citations.extend(pres.get("citations", []))
                all_citations.extend(
                    d.get("url", "") for d in (tres or []) if d.get("url")
                )
                tvpl_note = f" (+{len(tres)} văn bản PL)" if tres else ""
                yield sse({
                    "type": "progress",
                    "step": batch_start + batch.index(sec) + 1,
                    "total": total,
                    "label": f"Xong research: {sec['title']}{tvpl_note}",
                })
```

#### main.py — Inject TVPL docs into Claude context in Phase 2

Find the Phase 2 section inside `generate()` where `ctx` is built, and
update it to prepend TVPL docs for legal/tax sections:

```python
            ctx = filter_context(all_results, section)

            # Prepend TVPL legal docs for law/tax sections
            tvpl_docs = all_tvpl.get(section["id"], [])
            if tvpl_docs and is_legal_or_tax_section(section):
                tvpl_text = format_tvpl_results(tvpl_docs)
                if tvpl_text:
                    ctx = tvpl_text + "\n\n" + ctx

            sec_html = ""
            async for chunk in claude_stream_section(section, subject, ctx, mode, i + 1):
```

---

## After making changes

1. Run a quick syntax check:
   ```bash
   python3 -m py_compile main.py && echo "OK"
   ```

2. Commit and push:
   ```bash
   git add main.py requirements.txt
   git commit -m "feat: switch to Anthropic native SDK + add thuvienphapluat.vn scraper"
   git push origin main
   ```

Coolify will auto-deploy on push. No manual steps needed.

---

## Note on asyncio coroutine for empty tvpl_tasks

The line `asyncio.coroutine(lambda: [])()` may show a deprecation warning in Python 3.11+.
Use this instead if needed:
```python
async def _empty():
    return []

tvpl_tasks = [
    tvpl_search(build_tvpl_query(s, subject))
    if is_legal_or_tax_section(s)
    else _empty()
    for s in batch
]
```
