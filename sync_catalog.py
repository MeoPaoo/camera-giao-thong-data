"""Đồng bộ danh mục camera giao thông TP.HCM với bản đồ công khai của cổng
https://giaothong.hochiminhcity.gov.vn và ghi docs/cameras.json (GitHub Pages phục vụ file này).

    python -I sync_catalog.py            # đồng bộ
    python -I sync_catalog.py --check    # chỉ kiểm tra file hiện tại hợp lệ

Quy tắc:
- Camera MỚI trên cổng: thử ảnh chụp (giãn 0,7 giây/lần). Có ảnh thật → imageUrl; có
  VideoStreaming + VideoUrl → videoUrl. Không có cả hai thì bỏ qua (thử lại lần sau).
- Camera ĐÃ CÓ: cập nhật videoUrl theo cổng; giữ tên/vị trí/ảnh để danh mục ổn định.
- Camera KHÔNG CÒN trên cổng: chỉ giữ nếu ảnh chụp vẫn tải được.
- An toàn: lỗi tải/đọc dữ liệu, cổng trả quá ít camera, hoặc sắp xóa >10% danh mục
  → dừng với mã lỗi, KHÔNG ghi file. Không đổi gì → không ghi file.
"""
import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE = "https://giaothong.hochiminhcity.gov.vn"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
APP_UA = "CameraGiaoThongSync/1.0 (+https://github.com)"
CATALOG = Path(__file__).resolve().parent / "docs" / "cameras.json"
# Máy chủ video HTTP mà app cho phép (network_security_config.xml của app). Máy chủ mới
# phải được thêm vào app và phát hành bản mới; trước đó app sẽ bỏ qua video của chúng.
APP_ALLOWED_HTTP_VIDEO_HOSTS = {"camera.thongtingiaothong.vn", "125.234.114.126", "125.234.133.4"}
MIN_PORTAL_ROWS = 300
MIN_CATALOG = 400
MAX_REMOVE_RATIO = 0.10
SNAPSHOT_DELAY = 0.7
MISS_LIMIT = 2  # số lần đồng bộ liên tiếp ảnh chắc chắn hỏng trước khi xóa camera


def log(msg):
    print(msg, flush=True)


def warn(msg):
    # GitHub Actions hiển thị dòng ::warning:: trong trang kết quả.
    print(f"::warning::{msg}", flush=True)


# ---------- AjaxPro: new Ajax.Web.DataTable(...) / new Date(...) -> JSON ----------
def _replace_calls(s, prefix, open_tok, close_tok):
    out, i = [], 0
    while True:
        j = s.find(prefix, i)
        if j < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:j])
        k = start = j + len(prefix)
        depth, in_str = 1, False
        while depth:
            c = s[k]
            if in_str:
                if c == "\\":
                    k += 1
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            k += 1
        out.append(open_tok + _replace_calls(s[start:k - 1], prefix, open_tok, close_tok) + close_tok)
        i = k


def ajaxpro_loads(text):
    text = re.sub(r"new Date\(Date\.UTC\([^)]*\)\)", "null", text)
    text = re.sub(r"new Date\([^)]*\)", "null", text)
    text = _replace_calls(text, "new Ajax.Web.DataTable(", '{"__datatable":[', "]}")
    return json.loads(re.sub(r";\s*/\*\s*$", "", text.strip()))


def table_rows(dt):
    cols, rows = dt["__datatable"]
    names = [c[0] for c in cols]
    return [dict(zip(names, r)) for r in rows]


# ---------- Cổng giao thông ----------
def fetch_portal_rows():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(urllib.request.Request(f"{BASE}/Map.aspx", headers={"User-Agent": BROWSER_UA}), timeout=90).read()
    body = json.dumps({
        "path": "/root/vdms/tangthu/data/layerdata/camera", "isInTree": False, "searchKey": "",
        "layer": ["CAMERA"], "detail": True, "page": 0, "limit": -1,
        "filterQuery": ["Publish:true"], "sortby": None,
        "returnFields": ["CamId", "DisplayName", "Title", "Location", "CamStatus", "VideoStreaming", "VideoUrl"],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/ajaxpro/VDMS.Web.Library.AJAX.FolderAjax,VDMS.Web.Library.ashx", data=body,
        headers={"User-Agent": BROWSER_UA, "X-AjaxPro-Method": "SearchQuery",
                 "Content-Type": "text/plain; charset=utf-8", "Referer": f"{BASE}/Map.aspx"})
    data = ajaxpro_loads(opener.open(req, timeout=180).read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"Cổng trả lỗi: {data['error']}")
    return table_rows(data["value"][1][1])


def point(row):
    try:
        shape = row["Location"]["__datatable"][1][0][1]
        lon, lat = map(float, re.match(r"POINT\(([-\d.]+) ([-\d.]+)\)", shape).groups())
    except (TypeError, KeyError, IndexError, AttributeError, ValueError):
        return None
    # Chỉ nhận tọa độ quanh TP.HCM (loại dữ liệu lỗi kiểu 0,0).
    return (lat, lon) if 10.0 <= lat <= 11.6 and 106.2 <= lon <= 107.2 else None


def video_url(row):
    url = (row.get("VideoUrl") or "").strip()
    u = urlparse(url)
    ok = str(row.get("VideoStreaming")) in ("1", "True", "true") and u.scheme in ("http", "https") and u.hostname
    return url if ok else None


def image_url(cam_id):
    return f"{BASE}/render/ImageHandler.ashx?id={cam_id}"


def snapshot_state(cam_id):
    """True = ảnh thật (HTTP 200, image/*, > 5 KB).
    False = chắc chắn không có ảnh (ảnh "IMAGE NOT AVAILABLE" không có Content-Type, ảnh quá nhỏ, 404/410).
    None = chưa rõ (lỗi mạng, hết giờ, 5xx...) — máy chạy ở nước ngoài hay gặp, KHÔNG dùng để xóa."""
    try:
        req = urllib.request.Request(image_url(cam_id), headers={"User-Agent": APP_UA, "Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            kind = (resp.headers.get("Content-Type") or "").lower()
            size = len(resp.read(8_000_000))
            if resp.status != 200:
                return None
            return kind.startswith("image/") and size > 5000
    except urllib.error.HTTPError as e:
        return False if e.code in (404, 410) else None
    except Exception:
        return None
    finally:
        time.sleep(SNAPSHOT_DELAY)


# ---------- Quận/huyện (cũ) và phường/xã (mới) từ ranh giới OSM trong boundaries/ ----------
BOUNDARIES = Path(__file__).resolve().parent / "boundaries"


def _in_ring(ring, x, y):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _ring_distance(ring, x, y):
    """Khoảng cách (độ) từ điểm tới cạnh gần nhất của vòng."""
    best = float("inf")
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        px, py = ax + t * dx, ay + t * dy
        best = min(best, ((x - px) ** 2 + (y - py) ** 2) ** 0.5)
    return best


class Areas:
    def __init__(self, path):
        self.items = []
        if not Path(path).exists():
            return
        for f in json.loads(Path(path).read_text(encoding="utf-8"))["features"]:
            for poly in f["geometry"]["coordinates"]:
                xs = [p[0] for p in poly[0]]
                ys = [p[1] for p in poly[0]]
                self.items.append((min(xs), min(ys), max(xs), max(ys), poly, f["properties"]))

    def __bool__(self):
        return bool(self.items)

    def find(self, lat, lon, tolerance=0.005):
        """Thuộc tính (name, province…) của vùng chứa điểm. Điểm rơi vào khe giữa các vùng (sông, mép
        ranh giới) thì lấy vùng có cạnh gần nhất trong khoảng [tolerance] độ (~500 m). Không có → None."""
        for x0, y0, x1, y1, poly, props in self.items:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _in_ring(poly[0], lon, lat) \
                    and not any(_in_ring(hole, lon, lat) for hole in poly[1:]):
                return props
        best, best_d = None, tolerance
        for x0, y0, x1, y1, poly, props in self.items:
            if not (x0 - tolerance <= lon <= x1 + tolerance and y0 - tolerance <= lat <= y1 + tolerance):
                continue
            d = _ring_distance(poly[0], lon, lat)
            if d < best_d:
                best, best_d = props, d
        return best


HCMC = "TP. Hồ Chí Minh"


def annotate(cameras):
    """Gắn 'district' (quận/huyện cũ, kèm 'oldProvince' nếu ngoài TP.HCM cũ) và 'ward' (phường/xã mới,
    kèm 'newProvince' nếu ngoài TP.HCM mới). Bỏ trường khi không xác định được."""
    stats = {}
    for field, file in (("district", "districts_old.geojson"), ("ward", "wards_new.geojson")):
        areas = Areas(BOUNDARIES / file)
        if not areas:
            continue
        found = 0
        for cam in cameras:
            props = areas.find(cam["latitude"], cam["longitude"])
            if props:
                cam[field] = props["name"]
                found += 1
            else:
                cam.pop(field, None)
            # Tỉnh/thành chỉ ghi khi khác TP.HCM: cũ (Bình Dương…) cho quận, mới (Tây Ninh…) cho phường.
            province_field = "oldProvince" if field == "district" else "newProvince"
            province = props.get("province") if props else None
            if province and province != HCMC:
                cam[province_field] = province
            else:
                cam.pop(province_field, None)
        stats[field] = found
    return stats


# ---------- Danh mục ----------
def load_catalog():
    if not CATALOG.exists():
        return []
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return data["cameras"] if isinstance(data, dict) else data


def validate(cameras):
    errors, ids = [], set()
    for c in cameras:
        cid = c.get("id")
        if not cid or not str(c.get("name", "")).strip():
            errors.append(f"thiếu id/tên: {c}")
            continue
        if cid in ids:
            errors.append(f"trùng id {cid}")
        ids.add(cid)
        lat, lon = c.get("latitude"), c.get("longitude")
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180):
            errors.append(f"tọa độ sai {cid}")
        img, vid = c.get("imageUrl"), c.get("videoUrl")
        if img is None and vid is None:
            errors.append(f"không có ảnh lẫn video {cid}")
        if img is not None and urlparse(img).scheme != "https":
            errors.append(f"ảnh không phải HTTPS {cid}")
        if vid is not None and urlparse(vid).scheme not in ("http", "https"):
            errors.append(f"video sai {cid}")
    return errors


def write_catalog(cameras):
    cameras = sorted(cameras, key=lambda c: c["id"])
    doc = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "giaothong.hochiminhcity.gov.vn (bản đồ công khai) + WME WazeVN traffic cams list (MIT); quận/phường: ranh giới © OpenStreetMap contributors (ODbL)",
        "count": len(cameras),
        "cameras": cameras,
    }
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sync():
    current = load_catalog()
    by_id = {c["id"]: dict(c) for c in current}
    try:
        rows = fetch_portal_rows()
    except Exception as e:
        log(f"Không tải được dữ liệu cổng: {type(e).__name__}: {e}")
        return 2
    portal = {}
    for r in rows:
        cid = (r.get("CamId") or "").strip()
        if cid:
            portal[cid] = r
    log(f"Cổng: {len(rows)} camera công khai. Danh mục hiện tại: {len(current)}.")
    if len(portal) < MIN_PORTAL_ROWS:
        log(f"Cổng chỉ trả {len(portal)} camera (< {MIN_PORTAL_ROWS}) — nghi dữ liệu lỗi, dừng.")
        return 3

    added, video_changed, removed, kept_missing = [], 0, [], 0
    for cid, r in portal.items():
        vid = video_url(r)
        if cid in by_id:
            cam = by_id[cid]
            if cam.get("videoUrl") != vid:
                if vid is None:
                    cam.pop("videoUrl", None)
                    if cam.get("imageUrl") is None:   # chỉ có video mà video bị gỡ
                        removed.append(cid)
                        continue
                else:
                    cam["videoUrl"] = vid
                video_changed += 1
            continue
        pos = point(r)
        name = (r.get("DisplayName") or r.get("Title") or "").strip()
        if not pos or not name:
            continue
        # Camera mới chỉ thêm ảnh khi chắc chắn có ảnh thật; chưa rõ thì để lần sau.
        img = image_url(cid) if snapshot_state(cid) is True else None
        if img is None and vid is None:
            continue
        cam = {"id": cid, "name": name, "latitude": pos[0], "longitude": pos[1], "imageUrl": img}
        if vid:
            cam["videoUrl"] = vid
        by_id[cid] = cam
        added.append(cid)

    # Camera không còn trên cổng: chỉ xóa khi ảnh CHẮC CHẮN hỏng MISS_LIMIT lần liên tiếp.
    for cid in [c for c in list(by_id) if c not in portal]:
        cam = by_id[cid]
        state = snapshot_state(cid) if cam.get("imageUrl") else False
        if state is False:
            cam["missCount"] = cam.get("missCount", 0) + 1
            if cam["missCount"] >= MISS_LIMIT:
                removed.append(cid)
                continue
        elif state is True:
            cam.pop("missCount", None)
        kept_missing += 1
    for cid in removed:
        by_id.pop(cid, None)

    if current and len(removed) > MAX_REMOVE_RATIO * len(current):
        log(f"Sắp xóa {len(removed)}/{len(current)} camera (> {MAX_REMOVE_RATIO:.0%}) — dừng để kiểm tra tay.")
        return 4
    result = list(by_id.values())
    if len(result) < MIN_CATALOG:
        log(f"Danh mục chỉ còn {len(result)} camera (< {MIN_CATALOG}) — dừng.")
        return 5
    area_stats = annotate(result)
    errors = validate(result)
    if errors:
        log("Danh mục không hợp lệ:\n  " + "\n  ".join(errors[:20]))
        return 6

    hosts = {urlparse(c["videoUrl"]).hostname for c in result
             if c.get("videoUrl") and urlparse(c["videoUrl"]).scheme == "http"}
    for h in sorted(hosts - APP_ALLOWED_HTTP_VIDEO_HOSTS):
        warn(f"Máy chủ video HTTP mới '{h}': cần thêm vào network_security_config.xml và video_hosts.dart của app.")

    if area_stats:
        log("Xác định khu vực: " + ", ".join(f"{k} {v}/{len(result)}" for k, v in area_stats.items()))
    log(f"Thêm {len(added)}, đổi video {video_changed}, xóa {len(removed)}, "
        f"giữ {kept_missing} camera không còn trên cổng nhưng ảnh vẫn chạy. Tổng {len(result)}.")
    before = sorted(current, key=lambda c: c["id"])
    after = sorted(result, key=lambda c: c["id"])
    if before == after:
        log("Không có thay đổi — giữ nguyên file.")
        return 0
    write_catalog(result)
    log(f"Đã ghi {CATALOG}.")
    return 0


def check():
    cams = load_catalog()
    errors = validate(cams)
    log(f"{len(cams)} camera, {len(errors)} lỗi.")
    for e in errors[:20]:
        log("  " + e)
    return 1 if errors or len(cams) < MIN_CATALOG else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="chỉ kiểm tra docs/cameras.json")
    sys.exit(check() if parser.parse_args().check else sync())
