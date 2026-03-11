# BRIEF: Fix Gamma timeout

## Vấn đề
`create_gamma_slides()` poll tối đa 60 lần × 10s = 10 phút.
Gamma tạo 60 slides mất hơn 10 phút → timeout → không inject link vào báo cáo.

## Fix — 2 thay đổi trong `create_gamma_slides()`

### 1. Giảm numCards từ 60 → 30
```python
"numCards": 30,   # Giảm từ 60 → tạo nhanh hơn, đủ nội dung
```

### 2. Tăng timeout từ 10 phút → 20 phút
```python
for _ in range(120):  # max 20 minutes (tăng từ 60)
    await asyncio.sleep(10)
```

## Không thay đổi gì khác

## Commit message
`fix: reduce Gamma slides to 30 cards + increase timeout to 20min`

## Sau khi xong
Xoá BRIEF-fix-gamma-timeout.md rồi push lên branch main.
Nhắn Thanh "deploy stable" để merge vào stable và deploy.
