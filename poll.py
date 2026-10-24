"""Check the Assuta and Basel parking lots (Ahuzot HaHof) and log their status.

Run repeatedly by .github/workflows/watch.yml. Each run:
  1. reads both lots' status from the Tel Aviv GIS feed (layer 970),
     falling back to the status image on ahuzot.co.il;
  2. appends one row per lot to <data>/<lot>.csv (assuta.csv, basel.csv);
  3. optionally sends phone alerts through ntfy.sh (NTFY_TOPIC secret).
     Assuta comes first; Basel is the backup:
       - Assuta turns "few spaces" or "full" in the evening;
       - Basel fills up while Assuta is already full;
       - about 20 minutes before the usual "park by" time for tonight.

Standard library only, so the workflow needs no pip install.
Usage: python poll.py --data DIR      (or --analyze to print the pattern)
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IL = ZoneInfo("Asia/Jerusalem")

# Order matters: the first lot is the preferred one.
LOTS = [
    {"key": "assuta", "code": 122, "name": "אסותא", "en": "Assuta"},
    {"key": "basel", "code": 3, "name": "בזל", "en": "Basel"},
]
GIS_URL = (
    "https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2/MapServer/970/query"
    "?where=1%3D1&outFields=code_achoza,shem_chenyon,status_chenyon,tr_status_chenyon"
    "&returnGeometry=false&f=json"
)
AHUZOT_URL = "https://www.ahuzot.co.il/Parking/ParkingDetails/?ID=%d"

FULL, FEW, FREE, CLOSED, UNKNOWN = "מלא", "מעט", "פנוי", "סגור", "unknown"
KNOWN = {FULL, FEW, FREE, CLOSED}
AHUZOT_IMG = {"male": FULL, "meat": FEW, "panui": FREE}
EN = {FULL: "full", FEW: "few spaces", FREE: "room", CLOSED: "closed", UNKNOWN: "no data"}

# Analysis settings (mirrored in index.html — keep them in sync).
EVENING_START_H = 15      # an "evening" runs 15:00 -> 04:00 next day
EVENING_END_H = 4
STALE_MIN = 90            # feed timestamp older than this = status unknown
FRESH_SRC_MIN = 20        # use the feed's own timestamp when it's this fresh
MAX_GAP_MIN = 45          # a fill time needs a check within 45 min before it
MIN_CHECKS_FOR_NO_FILL = 40   # evening counts as "didn't fill" with this coverage
LEAD_MIN = 25             # "park by" = usual fill time minus this
ALERT_AHEAD_MIN = 20      # heads-up alert goes out up to this long before "park by"
WEEKS_BACK = 8

HEADERS = {"User-Agent": "track-parking logger (personal, 1 request / 5 min)"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------- fetching

def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def wallclock_from_feed(ms):
    """tr_status_chenyon is Israel wall-clock time mislabeled as UTC epoch ms."""
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def read_gis():
    data = json.loads(fetch(GIS_URL))
    if "error" in data:
        raise RuntimeError(data["error"])
    found = {}
    for f in data.get("features", []):
        a = f.get("attributes", {})
        for lot in LOTS:
            if a.get("code_achoza") == lot["code"] or (lot["key"] not in found and (a.get("shem_chenyon") or "").strip() == lot["name"]):
                status = a.get("status_chenyon")
                found[lot["key"]] = {
                    "status": status if status in KNOWN else UNKNOWN,
                    "source_time": wallclock_from_feed(a.get("tr_status_chenyon")),
                    "source": "gis",
                }
    return found


def read_ahuzot(code):
    """Status image and its timestamp from the lot's ahuzot.co.il page."""
    html = fetch(AHUZOT_URL % code)
    m = re.search(r'ParkingDetailsTable.*?IconText[^>]*>\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*<.*?<img[^>]+src="([^"]+)"',
                  html, re.S | re.I)
    if m:
        d, mo, y, h, mi, src = m.groups()
        when = datetime(int(y), int(mo), int(d), int(h), int(mi))
    else:
        m2 = re.search(r'ParkingDetailsTable.*?<img[^>]+src="([^"]+)"', html, re.S | re.I)
        src, when = (m2.group(1) if m2 else ""), None
    stem = src.rsplit("/", 1)[-1].split(".")[0].lower()
    return {"status": AHUZOT_IMG.get(stem, UNKNOWN), "source_time": when, "source": "ahuzot"}


def read_all():
    """Read both sources and keep the fresher status for each lot.

    The city GIS feed sometimes freezes for hours while ahuzot.co.il keeps
    updating (seen on 2026-10-24: GIS stuck at 06:42, the site live at 11:29).
    """
    gis, err = {}, ""
    try:
        gis = read_gis()
    except Exception as e:  # noqa: BLE001
        err = "gis: %s" % e
    out = {}
    for lot in LOTS:
        cands = []
        g = gis.get(lot["key"])
        if g and g["status"] != UNKNOWN:
            cands.append(g)
        try:
            a = read_ahuzot(lot["code"])
            if a["status"] != UNKNOWN:
                cands.append(a)
        except Exception as e:  # noqa: BLE001
            err += "; ahuzot %s: %s" % (lot["key"], e)
        if not cands:
            out[lot["key"]] = g or {"status": UNKNOWN, "source_time": None, "source": "error"}
            continue
        # Newest timestamp wins; a source without a timestamp counts as old.
        out[lot["key"]] = max(cands, key=lambda c: c["source_time"] or datetime.min)
    return out, err


# ---------------------------------------------------------------- log file

FIELDS = ["checked_at", "status", "source_time", "source"]
FMT = "%Y-%m-%dT%H:%M"


def load_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_row(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


# ---------------------------------------------------------------- analysis

def parse_t(s):
    return datetime.strptime(s, FMT) if s else None


def effective(row):
    """(event_time, status) for one logged check; status UNKNOWN if stale."""
    checked = parse_t(row["checked_at"])
    src = parse_t(row.get("source_time", ""))
    status = row["status"] if row["status"] in KNOWN else UNKNOWN
    if src is not None:
        age = (checked - src).total_seconds() / 60
        if age > STALE_MIN:
            status = UNKNOWN
        elif 0 <= age <= FRESH_SRC_MIN:
            return src, status
    return checked, status


def evening_of(t):
    if t.hour >= EVENING_START_H:
        return t.date()
    if t.hour < EVENING_END_H:
        return t.date() - timedelta(days=1)
    return None


def minutes_after_noon(t, evening):
    noon = datetime.combine(evening, datetime.min.time()) + timedelta(hours=12)
    return int((t - noon).total_seconds() // 60)


def evenings(rows):
    """{evening_date: {'few': min|None|'gap', 'full': ..., 'checks': n, 'filled': bool, 'usable': bool}}"""
    by = {}
    for row in rows:
        try:
            t, s = effective(row)
        except (ValueError, KeyError):
            continue
        ev = evening_of(t)
        if ev is None or s == UNKNOWN:
            continue
        by.setdefault(ev, []).append((t, s))

    out = {}
    for ev, pts in by.items():
        pts.sort()
        start = datetime.combine(ev, datetime.min.time()) + timedelta(hours=EVENING_START_H)
        res = {"checks": len(pts), "few": None, "full": None}
        for key, hit in (("few", {FEW, FULL}), ("full", {FULL})):
            prev = start - timedelta(minutes=30)   # first check must be near 15:00
            for t, s in pts:
                if s in hit:
                    if (t - prev) <= timedelta(minutes=MAX_GAP_MIN):
                        res[key] = minutes_after_noon(t, ev)
                    else:
                        res[key] = "gap"
                    break
                prev = t
        res["filled"] = isinstance(res["full"], int)
        res["usable"] = res["filled"] or (res["full"] is None and len(pts) >= MIN_CHECKS_FOR_NO_FILL)
        out[ev] = res
    return out


def predict(evs, weekday, today):
    """Prediction for evenings on `weekday` (Mon=0). Returns dict or None."""
    since = today - timedelta(weeks=WEEKS_BACK)
    same = [(d, r) for d, r in evs.items() if d.weekday() == weekday and since <= d < today and r["usable"]]
    scope = "weekday"
    if sum(1 for _, r in same if r["filled"]) < 2:
        same = [(d, r) for d, r in evs.items() if today - timedelta(days=21) <= d < today and r["usable"]]
        scope = "all"
    fulls = [r["full"] for _, r in same if r["filled"]]
    if len(fulls) < 2:
        return None
    fews = [r["few"] for _, r in same if isinstance(r["few"], int)]
    med = int(statistics.median(fulls))
    return {
        "scope": scope,
        "full_median": med,
        "full_earliest": min(fulls),
        "few_median": int(statistics.median(fews)) if fews else None,
        "filled": len(fulls),
        "evenings": len(same),
        "arrive_by": med - LEAD_MIN,
    }


def hhmm(m):
    h, mm = divmod(m, 60)
    return "%02d:%02d" % ((12 + h) % 24, mm)


# ---------------------------------------------------------------- alerts

def notify(title, message, page_url=None, priority=3):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    body = {"topic": topic, "title": title, "message": message, "tags": ["car"], "priority": priority}
    if page_url:
        body["click"] = page_url
    req = urllib.request.Request(
        "https://ntfy.sh/", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **HEADERS}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception as e:  # noqa: BLE001
        print("ntfy failed:", e, file=sys.stderr)
        return False


def last_two(rows):
    """(previous known status, current status) from a lot's log."""
    cur = effective(rows[-1])[1] if rows else UNKNOWN
    prev = None
    for row in reversed(rows[:-1]):
        s = effective(row)[1]
        if s != UNKNOWN:
            prev = s
            break
    return prev, cur


def plan_alerts(rows_by_lot, now, sent):
    """Return [(key, title, message, priority)] to send now. Pure, for testing."""
    ev = evening_of(now)
    if ev is None:
        return []
    k = ev.isoformat()
    a_prev, a_cur = last_two(rows_by_lot["assuta"])
    b_prev, b_cur = last_two(rows_by_lot["basel"])
    t = now.strftime("%H:%M")
    out = []

    def basel_hint():
        if b_cur in (FREE, FEW):
            return "Basel has %s." % EN[b_cur]
        if b_cur == FULL:
            return "Basel is full too, so start the street route."
        return "No live data for Basel."

    if a_cur == FEW and a_prev not in (None, FEW) and (k + ":assuta:few") not in sent:
        out.append((k + ":assuta:few", "Assuta: few spaces left",
                    "Few spaces at Assuta at %s. Go now to get a spot. %s" % (t, basel_hint()), 4))
    if a_cur == FULL and a_prev not in (None, FULL) and (k + ":assuta:full") not in sent:
        out.append((k + ":assuta:full", "Assuta is full",
                    "Assuta filled at about %s. %s" % (t, basel_hint()), 4))
    if b_cur == FULL and b_prev not in (None, FULL) and a_cur == FULL and (k + ":basel:full") not in sent:
        out.append((k + ":basel:full", "Both lots are full",
                    "Basel filled at about %s and Assuta is full. Start the street route." % t, 4))

    if a_cur != FULL and (k + ":pre") not in sent:
        pa = predict(evenings(rows_by_lot["assuta"]), ev.weekday(), ev)
        pb = predict(evenings(rows_by_lot["basel"]), ev.weekday(), ev)
        p = pa or pb
        if p:
            mins = minutes_after_noon(now, ev)
            if p["arrive_by"] - ALERT_AHEAD_MIN <= mins < p["arrive_by"]:
                day = DAY_NAMES[ev.weekday()] + "s" if p["scope"] == "weekday" else "recent evenings"
                parts = []
                if pa:
                    parts.append("Assuta usually fills around %s" % hhmm(pa["full_median"]))
                if pb:
                    parts.append("Basel around %s" % hhmm(pb["full_median"]))
                out.append((k + ":pre", "Head home to park soon",
                            "%s on %s. Aim to park by %s." % (", ".join(parts), day, hhmm(p["arrive_by"])), 4))
    return out


def run_alerts(rows_by_lot, now, state_path):
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    sent = state.setdefault("sent", {})
    page = os.environ.get("PAGE_URL") or None
    changed = False
    if not state.get("welcomed") and os.environ.get("NTFY_TOPIC", "").strip():
        if notify("Parking alerts are on",
                  "You'll get a message when Assuta gets few spaces or fills, when Basel fills too, "
                  "and about 20 minutes before tonight's park-by time.", page, 3):
            state["welcomed"] = now.strftime(FMT)
            changed = True
    for key, title, msg, prio in plan_alerts(rows_by_lot, now, sent):
        if notify(title, msg, page, prio):
            sent[key] = now.strftime(FMT)
            changed = True
    if changed:
        cutoff = (now.date() - timedelta(days=14)).isoformat()
        state["sent"] = {k: v for k, v in sent.items() if k[:10] >= cutoff}
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="folder holding the <lot>.csv logs")
    ap.add_argument("--analyze", action="store_true", help="print the pattern and exit")
    args = ap.parse_args()
    os.makedirs(args.data, exist_ok=True)
    path = lambda lot: os.path.join(args.data, lot["key"] + ".csv")
    now = datetime.now(IL).replace(tzinfo=None, second=0, microsecond=0)

    if args.analyze:
        for lot in LOTS:
            evs = evenings(load_rows(path(lot)))
            print("==", lot["en"])
            for d in sorted(evs)[-14:]:
                r = evs[d]
                f = hhmm(r["full"]) if isinstance(r["full"], int) else r["full"]
                print(" ", d, d.strftime("%a"), "checks=%d" % r["checks"], "full=%s" % f)
            for wd in range(7):
                p = predict(evs, wd, now.date() + timedelta(days=1))
                print(" ", DAY_NAMES[wd][:3], p and (hhmm(p["full_median"]), "%d/%d" % (p["filled"], p["evenings"])))
        return

    statuses, err = read_all()
    for lot in LOTS:
        st = statuses[lot["key"]]
        row = {
            "checked_at": now.strftime(FMT),
            "status": st["status"],
            "source_time": st["source_time"].strftime(FMT) if st["source_time"] else "",
            "source": st["source"],
        }
        append_row(path(lot), row)
        print(lot["en"], row)
    if err:
        print("warnings:", err)
    rows = {lot["key"]: load_rows(path(lot)) for lot in LOTS}
    run_alerts(rows, now, os.path.join(args.data, "alerts.json"))


if __name__ == "__main__":
    main()
