"""Build geo.json (route, lots, curb spots, night lots) from raw map data.

Raw inputs come from tools/fetch_geo.py (run by .github/workflows/geo.yml):
  osm.json            OpenStreetMap streets (Overpass, with one-way info)
  lots.json           Tel Aviv GIS layer 970  (Ahuzot HaHof lots)
  loading_signs.json  Tel Aviv GIS layer 449  (loading-zone signs with full text)
  night_lots.json     Tel Aviv GIS layer 488  (resident night lots)
  synagogues.json     Tel Aviv GIS layer 568

Usage: python3 tools/build_geo.py RAW_DIR geo.json [--report]
"""

import json
import math
import os
import re
import sys
from collections import defaultdict

ANCHOR = (32.08830, 34.77990)        # Assuta, used for distances
CURB_RADIUS_M = 700
NIGHT_LOT_RADIUS_M = 850
KX = 111320 * math.cos(math.radians(32.09))
KY = 110540

# The street loop, as the user drives it. Each leg: street name in OSM, and the
# junction nodes (lat, lon) where the leg starts and ends.
LEGS = [
    {"id": "gabirol", "street": "אבן גבירול", "en": "Ibn Gabirol", "turn": "Drive south on", "part": "approach",
     "from": (32.095510, 34.783700), "to": (32.094049, 34.783415)},
    {"id": "hyrcanus", "street": "יוחנן הורקנוס", "en": "Yohanan Hyrcanus", "turn": "Turn right onto", "part": "approach",
     "from": (32.094049, 34.783415), "to": (32.094034, 34.781687)},
    {"id": "binnun_top", "street": "יהושע בן נון", "en": "Yehoshua Bin Nun", "turn": "Turn left onto", "part": "approach",
     "from": (32.094034, 34.781687), "to": (32.090521, 34.781020), "search": True},
    {"id": "binnun", "street": "יהושע בן נון", "en": "Yehoshua Bin Nun", "turn": "Keep going down", "part": "loop",
     "from": (32.090521, 34.781020), "to": (32.088502, 34.780341), "search": True},
    {"id": "jabotinsky", "street": "ז'בוטינסקי", "en": "Jabotinsky", "turn": "Turn left onto", "part": "loop",
     "from": (32.088502, 34.780341), "to": (32.088346, 34.781255)},
    {"id": "harnevo", "street": "הר נבו", "en": "Har Nevo", "turn": "Turn left onto", "part": "loop",
     "from": (32.088346, 34.781255), "to": (32.090126, 34.781653), "search": True},
    {"id": "gilad", "street": "הגלעד", "en": "HaGilad", "turn": "Turn right onto", "part": "loop",
     "from": (32.090126, 34.781653), "to": (32.090077, 34.782044)},
    {"id": "eingedi", "street": "עין גדי", "en": "Ein Gedi", "turn": "Turn left onto", "part": "loop",
     "from": (32.090077, 34.782044), "to": (32.090374, 34.782096)},
    {"id": "yericho", "street": "יריחו", "en": "Yericho", "turn": "Turn left onto", "part": "loop",
     "from": (32.090374, 34.782096), "to": (32.090521, 34.781020)},
]
SYNAGOGUE_HINT = ("יריחו", "5")      # "עטרת צבי" at Yericho 5, on the loop

LOT_KEYS = {"אסותא": "assuta", "בזל": "basel"}
AHUZOT_SITE_ID = {"assuta": 122, "basel": 3}


def J(raw, name):
    with open(os.path.join(raw, name), encoding="utf-8") as f:
        return json.load(f)


def dist(a, b):
    """metres between (lat, lon) points"""
    return math.hypot((a[1] - b[1]) * KX, (a[0] - b[0]) * KY)


# ---------------------------------------------------------------- route

def street_path(osm, street, start, end):
    """Shortest node path along one named street, from junction start to end."""
    key = lambda lat, lon: (round(lat, 6), round(lon, 6))
    adj = defaultdict(set)
    for w in osm["elements"]:
        if w.get("tags", {}).get("name") != street or "geometry" not in w:
            continue
        pts = [key(g["lat"], g["lon"]) for g in w["geometry"]]
        for a, b in zip(pts, pts[1:]):
            adj[a].add(b)
            adj[b].add(a)
    def snap(p):
        best = min(adj, key=lambda n: dist(n, p)) if adj else None
        if best is None or dist(best, p) > 15:
            raise SystemExit("route: no node on %s within 15 m of %s" % (street, p))
        return best
    s, e = snap(start), snap(end)
    prev, todo = {s: None}, [s]
    while todo:
        n = todo.pop(0)
        if n == e:
            break
        for m in adj[n]:
            if m not in prev:
                prev[m] = n
                todo.append(m)
    path, n = [], e
    while n is not None:
        path.append(n)
        n = prev[n]
    return [list(p) for p in reversed(path)]


def point_along(path, frac):
    """(lat, lon) at a fraction of a polyline's length."""
    segs = [dist(a, b) for a, b in zip(path, path[1:])]
    target, acc = sum(segs) * frac, 0.0
    for (a, b), d in zip(zip(path, path[1:]), segs):
        if acc + d >= target and d > 0:
            t = (target - acc) / d
            return [round(a[0] + (b[0] - a[0]) * t, 6), round(a[1] + (b[1] - a[1]) * t, 6)]
        acc += d
    return list(path[-1])


def build_route(osm):
    legs = []
    for leg in LEGS:
        path = street_path(osm, leg["street"], leg["from"], leg["to"])
        legs.append({k: leg[k] for k in ("id", "street", "en", "turn", "part")} |
                    {"search": leg.get("search", False), "path": path,
                     "length_m": round(sum(dist(a, b) for a, b in zip(path, path[1:])))})
    by = {l["id"]: l for l in legs}
    # Google Maps waypoints: mid-block points that force this exact order.
    wp = {
        "hyrcanus": point_along(by["hyrcanus"]["path"], 0.35),
        "binnun": point_along(by["binnun"]["path"], 0.5),
        "harnevo": point_along(by["harnevo"]["path"], 0.3),
        "yericho": point_along(by["yericho"]["path"], 0.45),
    }
    return {"legs": legs, "waypoints": wp,
            "loop_m": sum(l["length_m"] for l in legs if l["part"] == "loop")}


# ---------------------------------------------------------------- curb signs

DAY = {"א": 0, "ב": 1, "ג": 2, "ד": 3, "ה": 4, "ו": 5, "ש": 6}   # Sun=0 .. Sat=6
RANGE_RE = re.compile(r"(?<![א-ת])([א-ו])'?\s*(?:-|עד)\s*([א-ו])'?(?![א-ת])")
SINGLE_FRI_RE = re.compile(r"(?:יום|בימי|בימים|ימי|^|\s)ו'\s*(?:וערבי? חג|/|$|\s)")
TIME_RE = re.compile(r"(?:מ|משעה)?\s*-?\s*(\d{1,2})[:.](\d{2})\s*(?:עד|-)\s*-?\s*(?:השעה\s*)?\.?(\d{1,2})[:.](\d{2})")


def norm(text):
    return re.sub(r"\s+", " ", (text or "").replace("\r", " ").replace("\n", " ")).strip()


def classify(text):
    """Who may park outside the restricted hours."""
    t = norm(text)
    if "נכה" in t:
        return "disabled"
    if re.search(r"לרכב מספר|24 שעות|החניה אסורה בכל הימים", t):
        return "none"
    other = t.split("ביתר", 1)[1] if "ביתר" in t else ""
    if other:
        if "תו" in other.split("פריקה")[0]:
            return "permit"
        if re.search(r"החני[הת]\s*מותרת|מותרת\s*החני[הת]", other):
            return "all"
    if "לבעלי תו" in t:
        return "permit"
    return "unclear"


def windows(text):
    """Restricted windows [{days:[...], from:'HH:MM', to:'HH:MM'}] before 'ביתר'."""
    t = norm(text).split("ביתר", 1)[0]
    out, days = [], None
    tokens = []
    for m in RANGE_RE.finditer(t):
        tokens.append((m.start(), "days", list(range(DAY[m.group(1)], DAY[m.group(2)] + 1))))
    for m in SINGLE_FRI_RE.finditer(t):
        if not any(s <= m.start() + 1 < s + 12 for s, kind, _ in tokens if kind == "days"):
            tokens.append((m.start(), "days", [5]))
    for m in TIME_RE.finditer(t):
        tokens.append((m.start(), "time", ("%02d:%s" % (int(m.group(1)), m.group(2)), "%02d:%s" % (int(m.group(3)), m.group(4)))))
    for _, kind, val in sorted(tokens, key=lambda x: x[0]):
        if kind == "days":
            days = val
        else:
            out.append({"days": days if days is not None else [0, 1, 2, 3, 4, 5], "from": val[0], "to": val[1]})
    return out


def nearest_street(osm, p):
    """(Hebrew name, English name) of the closest named street to (lat, lon)."""
    best, name = 1e9, ("", "")
    for w in osm["elements"]:
        t = w.get("tags", {})
        if "name" not in t or t.get("highway") in ("footway", "pedestrian", "steps", "path", "cycleway"):
            continue
        g = w["geometry"]
        for a, b in zip(g, g[1:]):
            ax, ay = (a["lon"] - p[1]) * KX, (a["lat"] - p[0]) * KY
            bx, by = (b["lon"] - p[1]) * KX, (b["lat"] - p[0]) * KY
            dx, dy = bx - ax, by - ay
            L = dx * dx + dy * dy
            u = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
            d = math.hypot(ax + u * dx, ay + u * dy)
            if d < best:
                best, name = d, (t["name"], t.get("name:en", ""))
    return name


def build_curbs(raw, legs, osm):
    signs = J(raw, "loading_signs.json").get("features", [])
    route_pts = [p for l in legs for p in l["path"]]
    out = []
    for f in signs:
        a, g = f["attributes"], f["geometry"]
        p = (g["y"], g["x"])
        d = dist(p, ANCHOR)
        if d > CURB_RADIUS_M or a.get("status") not in (None, "קיים"):
            continue
        who = classify(a.get("traffic_sign_text"))
        if who in ("disabled", "none", "permit"):
            continue
        win = windows(a.get("traffic_sign_text"))
        if not win:
            continue
        street = nearest_street(osm, p)
        out.append({
            "id": a["traffic_sign_id"], "lat": round(p[0], 6), "lon": round(p[1], 6),
            "street": street[0], "street_en": street[1],
            "who": who, "windows": win,
            "walk_m": round(d), "route_m": round(min(dist(p, q) for q in route_pts)),
            "text": norm(a.get("traffic_sign_text")),
        })
    return sorted(out, key=lambda c: c["walk_m"])


# ---------------------------------------------------------------- lots & places

def build_lots(raw):
    lots = {}
    for f in J(raw, "lots.json")["features"]:
        a, g = f["attributes"], f["geometry"]
        key = LOT_KEYS.get((a.get("shem_chenyon") or "").strip())
        if key:
            lots[key] = {"key": key, "name": a["shem_chenyon"], "gis_code": a["code_achoza"], "site_id": AHUZOT_SITE_ID[key],
                         "address": a["ktovet"].replace(" תל-אביב יפו", ""), "lat": round(g["y"], 6), "lon": round(g["x"], 6)}
    for f in J(raw, "night_lots.json")["features"]:
        a = f["attributes"]
        key = LOT_KEYS.get((a.get("shem") or "").replace("חניון ", "").strip())
        if key in lots:
            lots[key]["capacity"] = a.get("num_vehicles")
            lots[key]["night_note"] = "Free at night and on weekends with a matching resident permit"
    missing = set(LOT_KEYS.values()) - set(lots)
    if missing:
        raise SystemExit("lots missing from layer 970: %s" % missing)
    return lots


HOURS_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(?:-|ועד|עד)\s*(\d{1,2}):(\d{2})")


def build_night_lots(raw):
    ahuzot_names = {(f["attributes"].get("shem_chenyon") or "").strip() for f in J(raw, "lots.json")["features"]}
    out = []
    for f in J(raw, "night_lots.json")["features"]:
        a, g = f["attributes"], f["geometry"]
        p = (g["y"], g["x"])
        d = dist(p, ANCHOR)
        name = (a.get("shem") or "").strip()
        if d > NIGHT_LOT_RADIUS_M or a.get("ahuzat_hof_code") or name in ahuzot_names or name.replace("חניון ", "") in ahuzot_names:
            continue
        kind = a.get("sug_chenyon") or ""
        notes = " ".join(x for x in (a.get("heaarot"), a.get("hearot_atar")) if x and x.strip())
        m = HOURS_RE.search(notes)
        hours = "%02d:%s–%02d:%s" % (int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)) if m else None
        price = (a.get("taarif_layla") or "").strip()
        if "מוסדות חינוך" in kind:
            label, detail = "School yard, open to residents at night", "Rules on the sign at the gate"
        elif "פרטיים" in kind:
            label = "Private lot, monthly night subscription"
            detail = ("₪%s a month" % price) if price.isdigit() else "Ask the lot for the price"
        else:
            label, detail = "Night lot", ""
        out.append({"name": name, "address": a.get("ktovet"), "lat": round(p[0], 6), "lon": round(p[1], 6),
                    "spaces": a.get("num_vehicles"), "kind": label, "hours": hours, "detail": detail,
                    "phone": (a.get("phone") or "").strip() or None, "walk_m": round(d)})
    return sorted(out, key=lambda x: x["walk_m"])


def build_synagogue(raw):
    if not os.path.exists(os.path.join(raw, "synagogues.json")):
        return {"name": 'עטרת צבי "יקרי"', "address": "יריחו 5", "lat": 32.090541, "lon": 34.781622}
    for f in J(raw, "synagogues.json")["features"]:
        a, g = f["attributes"], f["geometry"]
        if (a.get("name_str") or "").strip() == SYNAGOGUE_HINT[0] and (a.get("bait") or "").strip() == SYNAGOGUE_HINT[1]:
            return {"name": a["name_bet_cneset"].strip(), "address": "יריחו 5", "lat": round(g["y"], 6), "lon": round(g["x"], 6)}
    return None


def main():
    raw, out = sys.argv[1], sys.argv[2]
    osm = J(raw, "osm.json")
    route = build_route(osm)
    geo = {
        "lots": build_lots(raw),
        "route": route,
        "synagogue": build_synagogue(raw),
        "curbs": build_curbs(raw, route["legs"], osm),
        "night_lots": build_night_lots(raw),
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, separators=(",", ":"))
    if "--report" in sys.argv:
        print("loop %d m; legs:" % route["loop_m"], ", ".join("%s %dm" % (l["en"], l["length_m"]) for l in route["legs"]))
        print("waypoints", route["waypoints"])
        print("lots", {k: (v["lat"], v["lon"], v.get("capacity")) for k, v in geo["lots"].items()})
        print("synagogue", geo["synagogue"])
        for c in geo["curbs"]:
            print("\nCURB %s %s %s walk=%dm route=%dm %s" % (c["id"], c["street_en"] or c["street"], c["who"], c["walk_m"], c["route_m"], c["windows"]))
            print("   ", c["text"][:260])
        for n in geo["night_lots"]:
            print("NIGHT", n)


if __name__ == "__main__":
    main()
