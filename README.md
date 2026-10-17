# Danh mục camera giao thông TP.HCM

Dữ liệu cho app **Camera Giao Thông**. GitHub Actions đồng bộ hằng ngày với bản đồ công khai của
[Cổng thông tin giao thông TP.HCM](https://giaothong.hochiminhcity.gov.vn/Map.aspx); GitHub Pages
phục vụ file cho app:

```
https://<tài-khoản>.github.io/camera-giao-thong-data/cameras.json
```

## Cấu trúc `docs/cameras.json`

```json
{
  "version": 1,
  "updatedAt": "2026-10-17T10:00:00Z",
  "count": 800,
  "cameras": [
    {
      "id": "59ca317602eb490011a0a408",
      "name": "QL1 - Tỉnh lộ 10 B (2)",
      "latitude": 10.7492,
      "longitude": 106.5939,
      "imageUrl": "https://giaothong.hochiminhcity.gov.vn/render/ImageHandler.ashx?id=59ca317602eb490011a0a408",
      "videoUrl": "http://camera.thongtingiaothong.vn/s/59ca317602eb490011a0a408/index.m3u8"
    }
  ]
}
```

`imageUrl` = ảnh chụp định kỳ (có thể `null` với camera chỉ có video). `videoUrl` = luồng HLS trực tiếp (không bắt buộc).

Khu vực hành chính (gắn tự động mỗi lần đồng bộ):

- `district` — quận/huyện theo **địa giới cũ** (trước 01/07/2025), vd. `"Quận 1"`. `oldProvince` chỉ có khi ngoài TP.HCM cũ, vd. `"Bình Dương"`.
- `ward` — phường/xã theo **địa giới mới** (sau 01/07/2025).

Ranh giới lưu trong `boundaries/` (GeoJSON), tải bằng `python -I fetch_boundaries.py districts|wards` từ OpenStreetMap — chỉ chạy lại khi địa giới thay đổi. Dữ liệu ranh giới và các trường `district`/`oldProvince`/`ward` © OpenStreetMap contributors, giấy phép [ODbL 1.0](https://www.openstreetmap.org/copyright).

## Đồng bộ

- **Tự động:** `.github/workflows/sync.yml` chạy 03:17 sáng (giờ VN) mỗi ngày; có thay đổi thì commit, Pages tự cập nhật trong vài phút.
- **Chạy ngay:** tab **Actions → Đồng bộ danh mục camera → Run workflow**.
- **Trên máy:** `python -I sync_catalog.py` rồi `git commit` + `git push` (dùng khi cổng chặn máy chủ GitHub ở nước ngoài).

Camera không còn trên cổng chỉ bị xóa khi ảnh **chắc chắn hỏng** (ảnh "IMAGE NOT AVAILABLE", 404/410) **2 lần đồng bộ liên tiếp** (trường `missCount`); lỗi mạng/hết giờ không tính, vì máy chạy GitHub ở nước ngoài hay gặp.

Script dừng **và không ghi file** khi: không tải được dữ liệu cổng, cổng trả < 300 camera, sắp xóa > 10% danh mục, hoặc danh mục mới không hợp lệ. Khi đó workflow báo đỏ, app vẫn dùng danh mục cũ.

Mỗi lần chạy chỉ gửi 2 yêu cầu lấy danh sách + vài chục yêu cầu kiểm tra ảnh (chỉ camera mới hoặc camera không còn trên cổng), giãn 0,7 giây/yêu cầu.

**Máy chủ video HTTP mới** (workflow cảnh báo vàng): app chỉ phát video HTTP từ các máy chủ được khai báo trong `network_security_config.xml` và `lib/data/video_hosts.dart`. Cần thêm máy chủ đó vào app và phát hành bản mới; trước đó app tự bỏ qua video của máy chủ lạ (ảnh vẫn chạy).

> GitHub tạm tắt lịch chạy của repo không có hoạt động trong 60 ngày. Nếu thấy workflow bị tắt, vào tab Actions bấm **Enable workflow**.

## Nguồn và giấy phép

Xem [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Dữ liệu camera thuộc đơn vị vận hành cổng; repo này chỉ lưu danh mục (tên, tọa độ, đường dẫn), không lưu hình ảnh hay video.
