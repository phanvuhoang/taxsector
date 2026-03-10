# BRIEF: Fix script loading order

## Vấn đề
Sau khi thêm modal-append và các tính năng mới, các `<script>` block
bị đặt SAU login modal trong HTML body. Khi browser parse HTML, button
`onclick="doLogin()"` xuất hiện trước khi function được define → lỗi:
`Uncaught ReferenceError: doLogin is not defined`

## Fix bắt buộc

Trong `HTML_PAGE`, tìm thẻ `</head>` và đảm bảo **script chính** (chứa
`doLogin`, `init`, tất cả state/functions) nằm NGAY TRƯỚC `</head>`,
KHÔNG phải trong `<body>`.

### Cấu trúc đúng:
```html
<head>
  <meta ...>
  <script src="tailwind CDN"></script>
  <style>...</style>

  <!-- Script chính PHẢI ở đây, trong <head> -->
  <script>
    let AUTH = '';
    // ... tất cả state variables
    async function doLogin() { ... }
    async function init() { ... }
    // ... tất cả functions khác
  </script>
</head>
<body>
  <!-- Login modal -->
  <div id="login-modal" ...>
    <button onclick="doLogin()">Đăng nhập</button>
  </div>

  <!-- App shell -->
  <div id="app">...</div>

  <!-- Modal append (mới) — đặt cuối body, KHÔNG có script ở đây -->
  <div id="modal-append">...</div>

  <!-- Script nhỏ cuối body (chỉ event listeners) -->
  <script>
    document.addEventListener('keydown', ...)
  </script>
</body>
```

### Quy tắc:
1. Script chứa functions (`doLogin`, `init`, `openModal`...) → **trong `<head>`**
2. Script chứa event listeners đơn giản → có thể cuối `<body>`
3. **KHÔNG** tách functions ra nhiều `<script>` blocks trong `<body>`
4. Các modal HTML mới (modal-append, modal-regenerate...) → đặt cuối `<body>` TRƯỚC script

## Sau khi fix
Commit message: `fix: move main script to <head> to fix doLogin not defined error`
Push lên GitHub — Coolify sẽ auto-deploy.
Xoá file BRIEF-fix-script-order.md này sau khi apply.
