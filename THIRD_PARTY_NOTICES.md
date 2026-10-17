# Danh mục camera

`app/src/main/assets/cameras.json` được chuyển đổi từ phần HCMC của **wme-wazevn-traffic-cams-list**, tác giả **tranlong5252**, phiên bản **2026.06.03.02**. Các mục trùng ID được gộp lại. Đây là danh mục cộng đồng, không phải API danh sách chính thức của cổng giao thông.

- Trang nguồn: https://greasyfork.org/en/scripts/497466-wme-wazevn-traffic-cams-list/code
- Bản nguồn cố định: https://update.greasyfork.org/scripts/497466/1841719/wme-wazevn-traffic-cams-list.js
- Giấy phép được khai báo trong metadata nguồn: MIT.

Thay đổi trong bản app 1.0.1: giữ ID, tên và tọa độ từ danh mục; thay URL ảnh bằng `https://giaothong.hochiminhcity.gov.vn/render/ImageHandler.ashx?id=<ID>` theo hàm `buildCamInfoExpand` của `https://giaothong.hochiminhcity.gov.vn/public/global.js`. Handler cũ trên cổng 8007 trả 403 trong môi trường kiểm tra.

**Đồng bộ với cổng (từ bản app 2.0):** từ 17/10/2026, danh mục được đồng bộ hằng ngày với dữ liệu bản đồ công khai của https://giaothong.hochiminhcity.gov.vn/Map.aspx (thêm camera mới, vị trí, tên hiển thị, đường dẫn video HLS `VideoUrl`) bằng `sync_catalog.py` trong repo https://github.com/MeoPaoo/camera-giao-thong-data. Dữ liệu và luồng video thuộc đơn vị vận hành cổng; app chỉ phát trực tiếp từ máy chủ của họ, không lưu hay phân phối lại video.

Metadata gốc:

```text
// ==UserScript==
// @name         wme-wazevn-traffic-cams-list
// @namespace    asd
// @version      2026.06.03.02
// @description  List of traffic cams in VietNam. To be used with WME WazeVN script.
// @author       tranlong5252
// @license      MIT
// ==/UserScript==
```

MIT License

Copyright (c) tranlong5252

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Giấy phép của danh mục không cấp quyền truy cập hoặc tái phân phối hình ảnh camera. Hình ảnh vẫn được yêu cầu trực tiếp từ máy chủ cổng giao thông; ứng dụng không đóng gói ảnh.
