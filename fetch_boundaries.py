"""Tải ranh giới hành chính TP.HCM từ OpenStreetMap (Overpass API) và lưu GeoJSON vào boundaries/.
Chỉ cần chạy lại khi ranh giới thay đổi; đồng bộ hằng ngày dùng file đã lưu, không gọi Overpass.

    python -I fetch_boundaries.py districts   # 22 quận/huyện CŨ, theo dữ liệu OSM ngày 01/06/2025
    python -I fetch_boundaries.py wards       # phường/xã MỚI (sau 01/07/2025) của TP.HCM, dữ liệu hiện tại

Dữ liệu © OpenStreetMap contributors, giấy phép ODbL 1.0 (https://www.openstreetmap.org/copyright).
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "CameraGiaoThongSync/1.0 (github.com/MeoPaoo/camera-giao-thong-data)"
OUT = Path(__file__).resolve().parent / "boundaries"
OLD_DATE = "2025-06-01T00:00:00Z"
# Khung bao TP.HCM cũ (trước khi nhập Bình Dương, Bà Rịa – Vũng Tàu): nơi có camera của cổng.
OLD_HCMC_BBOX = "10.35,106.35,11.17,107.03"
# Khung bao mọi camera hiện có (gồm Quốc lộ 51 – Phú Mỹ, Bình Dương, Long An giáp ranh).
WARD_BBOX = "10.35,106.35,11.15,107.15"
OLD_DISTRICTS = {
    "Quận 1", "Quận 3", "Quận 4", "Quận 5", "Quận 6", "Quận 7", "Quận 8", "Quận 10", "Quận 11", "Quận 12",
    "Quận Bình Thạnh", "Quận Gò Vấp", "Quận Phú Nhuận", "Quận Tân Bình", "Quận Tân Phú", "Quận Bình Tân",
    "Thành phố Thủ Đức", "Huyện Bình Chánh", "Huyện Củ Chi", "Huyện Hóc Môn", "Huyện Nhà Bè", "Huyện Cần Giờ",
}
# Quận/huyện cũ của tỉnh lân cận có camera của cổng (Bình Dương, Bà Rịa – Vũng Tàu nay thuộc TP.HCM;
# Long An nay thuộc Tây Ninh). Tên trùng ở nhiều tỉnh (vd. "Huyện Châu Thành") không đưa vào.
NEIGHBOR_DISTRICTS = {
    "Thành phố Dĩ An": "Bình Dương", "Thành phố Thuận An": "Bình Dương", "Thành phố Thủ Dầu Một": "Bình Dương",
    "Thành phố Bến Cát": "Bình Dương", "Thành phố Tân Uyên": "Bình Dương",
    "Thành phố Phú Mỹ": "Bà Rịa – Vũng Tàu",
    "Huyện Cần Giuộc": "Long An", "Huyện Bến Lức": "Long An", "Huyện Cần Đước": "Long An", "Huyện Đức Hòa": "Long An",
    "Thành phố Biên Hòa": "Đồng Nai", "Huyện Nhơn Trạch": "Đồng Nai", "Huyện Long Thành": "Đồng Nai",
}


def overpass(query):
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=400) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # Overpass hay bận: chờ rồi thử lại.
            print(f"  Overpass lỗi ({e}); thử lại sau {30 * (attempt + 1)} giây…", flush=True)
            time.sleep(30 * (attempt + 1))
    raise SystemExit("Không tải được dữ liệu từ Overpass.")


def _key(pt):
    return (round(pt["lon"], 7), round(pt["lat"], 7))


def assemble_rings(ways):
    """Nối các đoạn way (danh sách điểm) thành các vòng khép kín."""
    pending = [[_key(p) for p in w] for w in ways if len(w) >= 2]
    rings = []
    while pending:
        ring = pending.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, seg in enumerate(pending):
                if seg[0] == ring[-1]:
                    ring += seg[1:]
                elif seg[-1] == ring[-1]:
                    ring += seg[-2::-1]
                elif seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                elif seg[0] == ring[0]:
                    ring = seg[:0:-1] + ring
                else:
                    continue
                pending.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append([list(p) for p in ring])
        else:
            print(f"  Bỏ một vòng không khép kín ({len(ring)} điểm)", flush=True)
    return rings


def contains(ring, x, y):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def relation_to_feature(rel):
    outers = [m["geometry"] for m in rel.get("members", []) if m["type"] == "way" and m.get("role") in ("outer", "") and m.get("geometry")]
    inners = [m["geometry"] for m in rel.get("members", []) if m["type"] == "way" and m.get("role") == "inner" and m.get("geometry")]
    outer_rings, inner_rings = assemble_rings(outers), assemble_rings(inners)
    if not outer_rings:
        return None
    polygons = [[o] for o in outer_rings]
    for hole in inner_rings:  # gắn lỗ vào vòng ngoài chứa nó
        for poly in polygons:
            if contains(poly[0], *hole[0]):
                poly.append(hole)
                break
    return {
        "type": "Feature",
        "properties": {"name": rel["tags"]["name"], "osm_relation": rel["id"]},
        "geometry": {"type": "MultiPolygon", "coordinates": polygons},
    }


def save(name, features, note):
    OUT.mkdir(exist_ok=True)
    doc = {"type": "FeatureCollection", "note": note,
           "license": "© OpenStreetMap contributors, ODbL 1.0", "features": features}
    path = OUT / name
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Đã lưu {len(features)} vùng vào {path} ({path.stat().st_size // 1024} KB)")


def districts():
    q = (f'[out:json][timeout:300][date:"{OLD_DATE}"];'
         f'relation["boundary"="administrative"]["admin_level"="6"]({OLD_HCMC_BBOX});out geom;')
    wanted = OLD_DISTRICTS | NEIGHBOR_DISTRICTS.keys()
    rels = [e for e in overpass(q)["elements"] if e.get("tags", {}).get("name") in wanted]
    feats = [f for f in map(relation_to_feature, rels) if f]
    for f in feats:
        name = f["properties"]["name"]
        f["properties"]["province"] = NEIGHBOR_DISTRICTS.get(name, "TP. Hồ Chí Minh")
    missing = wanted - {f["properties"]["name"] for f in feats}
    if missing:
        raise SystemExit(f"Thiếu quận/huyện: {sorted(missing)}")
    save("districts_old.geojson", sorted(feats, key=lambda f: f["properties"]["name"]),
         f"Quận/huyện TP.HCM và tỉnh lân cận trước 01/07/2025 (OSM ngày {OLD_DATE[:10]})")


def _short_province(name):
    for prefix in ("Thành phố ", "Tỉnh "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return "TP. Hồ Chí Minh" if name == "Hồ Chí Minh" else name


def wards():
    # Mọi phường/xã MỚI trong khung bao các camera (TP.HCM cũ + Bình Dương, Phú Mỹ, Long An giáp ranh),
    # kèm tỉnh/thành MỚI chứa nó (vd. Long An cũ nay thuộc Tây Ninh).
    q = (f'[out:json][timeout:900];'
         f'relation["boundary"="administrative"]["admin_level"~"^(4|6)$"]({WARD_BBOX});out geom;')
    elements = overpass(q)["elements"]
    provinces = [(f["properties"]["name"], f) for f in
                 (relation_to_feature(e) for e in elements if e.get("tags", {}).get("admin_level") == "4") if f]
    feats = []
    for rel in elements:
        if rel.get("tags", {}).get("admin_level") != "6" or not rel.get("tags", {}).get("name"):
            continue
        f = relation_to_feature(rel)
        if not f:
            continue
        ring = f["geometry"]["coordinates"][0][0]
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        province = next((name for name, pf in provinces
                         if any(contains(poly[0], cx, cy) for poly in pf["geometry"]["coordinates"])), None)
        if province is None:
            continue
        f["properties"]["province"] = _short_province(province)
        feats.append(f)
    save("wards_new.geojson", sorted(feats, key=lambda f: (f["properties"]["province"], f["properties"]["name"])),
         "Phường/xã sau 01/07/2025 quanh khu vực có camera (OSM, dữ liệu hiện tại)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "districts":
        districts()
    elif what == "wards":
        wards()
    else:
        raise SystemExit("Dùng: python -I fetch_boundaries.py districts|wards")
