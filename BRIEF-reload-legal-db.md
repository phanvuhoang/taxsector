# BRIEF: Add /api/reload-legal-db endpoint

## Mục tiêu
Thêm endpoint để reload Legal DB từ file mà không cần restart container.
Dùng khi file /app/data/legal_db.json được update từ ngoài (cron job hàng ngày).

## Thêm vào backend (main.py)

### 1. Cập nhật load_legal_db() để check cả /app/data/

Tìm hàm `load_legal_db()`, cập nhật danh sách paths:

```python
def load_legal_db() -> list:
    """Load Legal DB từ file local. Download nếu chưa có."""
    for path in (
        Path("/app/data/legal_db.json"),   # Volume mount — ưu tiên trước
        LEGAL_DB_PATH,                      # /app/legal_db.json (baked in image)
        Path("legal_db.json"),
    ):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                print(f"[Legal DB] Loaded {len(data)} docs from {path}")
                return data
            except Exception as e:
                print(f"[Legal DB] Error reading {path}: {e}")
    # Fallback: download từ GitHub
    try:
        with urllib.request.urlopen(LEGAL_DB_URL, timeout=10) as r:
            data_str = r.read().decode("utf-8")
        LEGAL_DB_PATH.write_text(data_str, encoding="utf-8")
        data = json.loads(data_str)
        print(f"[Legal DB] Downloaded {len(data)} docs from GitHub")
        return data
    except Exception as e:
        print(f"[WARN] Could not load legal DB: {e}")
        return []
```

### 2. Thêm endpoint POST /api/reload-legal-db

Thêm sau các imports/globals (gần chỗ LEGAL_DB và LEGAL_INDEX được định nghĩa):

```python
def reload_legal_db_from_file():
    """Reload LEGAL_DB và LEGAL_INDEX từ file. Thread-safe."""
    global LEGAL_DB, LEGAL_INDEX
    new_db = load_legal_db()
    if new_db:
        LEGAL_DB = new_db
        LEGAL_INDEX = build_legal_index(new_db)
        return len(new_db)
    return 0
```

Thêm endpoint (sau các endpoints hiện có):

```python
@app.post("/api/reload-legal-db")
async def reload_legal_db_endpoint(_user: str = Depends(auth)):
    """Reload Legal DB từ file — dùng khi file được update từ ngoài."""
    count = reload_legal_db_from_file()
    expired = sum(
        1 for d in LEGAL_DB
        if "hết hiệu lực" in str(d.get("tinh_trang","")).lower()
        or "het_hieu_luc" in str(d.get("tinh_trang",""))
    )
    return {
        "status": "ok",
        "docs": count,
        "expired": expired,
        "message": f"Reloaded {count} docs ({expired} expired)"
    }
```

## Không thay đổi gì khác

## Commit message
`feat: add /api/reload-legal-db endpoint + load from volume /app/data/`

## Sau khi xong
Xoá BRIEF-reload-legal-db.md rồi push.
