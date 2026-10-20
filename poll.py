"""Check Assuta parking lot (Ahuzot HaHof, Jabotinsky 62) and log its status.

Runs every ~10 minutes from GitHub Actions. Each run:
  1. reads the lot's status from the Tel Aviv GIS feed (layer 970),
     falling back to the status image on ahuzot.co.il;
  2. appends one row to <data>/assuta.csv;
  3. optionally sends phone alerts through ntfy.sh (NTFY_TOPIC secret):
       - when Assuta turns "few spaces" or "full" in the evening;
       - ~25 minutes before the time it usually fills on this weekday.

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

LOT_CODE = 122            # Ahuzot HaHof's id for Assuta (ahuzot.co.il ?ID=122)
LOT_NAME = "אסותא"
GIS_URL = (
    "https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2/MapServer/970/query"
    "?where=1%3D1&outFields=code_achoza,shem_chenyon,status_chenyon,tr_status_chenyon"
    "&returnGeometry=false&f=json"
)
AHUZOT_URL = "https://www.ahuzot.co.il/Parking/ParkingDetails/?ID=%d" % LOT_CODE

FULL, FEW, FREE, CLOSED, UNKNOWN = "מלא", "מעט", "פנוי", "סגור", "unknown"
KNOWN = {FULL, FEW, FREE, CLOSED}
AHUZOT_IMG = {"male": FULL, "meat": FEW, "panui": FREE}

# Analysis settings (mirrored in index.html — keep them in sync).
EVENING_START_H = 15      # an "evening" runs 15:00 -> 04:00 next day
EVENING_END_H = 4
STALE_MIN = 90            # feed timestamp older than this = status unknown
FRESH_SRC_MIN = 20        # use the feed's own timestamp when it's this fresh
MAX_GAP_MIN = 45          # a fill time needs a check within 45 min before it
MIN_CHECKS_FOR_NO_FILL = 40   # evening counts as "didn't fill" with this coverage
LEAD_MIN = 25             # "get there by" = usual fill time minus this
ALERT_AHEAD_MIN = 20      # heads-up alert goes out up to this long before "get there by"
WEEKS_BACK = 8

HEADERS = {"User-Agent": "assuta-parking-logger (personal, 1 request / 10 min)"}


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
    for f in data.get("features", []):
        a = f.get("attributes", {})
        if a.get("code_achoza") == LOT_CODE or LOT_NAME in (a.get("shem_chenyon") or ""):
            status = a.get("status_chenyon")
            return {
                "status": status if status in KNOWN else UNKNOWN,
                "source_time": wallclock_from_feed(a.get("tr_status_chenyon")),
                "source": "gis",
            }
    raise RuntimeError("Assuta not found in GIS feed")


def read_ahuzot():
    html = fetch(AHUZOT_URL)
    m = re.search(r'ParkingDetailsTable.*?<img[^>]+src="([^"]+)"', html, re.S | re.I)
    stem = m.group(1).rsplit("/", 1)[-1].split(".")[0].lower() if m else ""
    return {"status": AHUZOT_IMG.get(stem, UNKNOWN), "source_time": None, "source": "ahuzot"}


def read_status():
    errors = []
    for reader in (read_gis, read_ahuzot):
        try:
            return reader()
        except Exception as e:  # noqa: BLE001 - log and try the next source
            errors.append("%s: %s" % (reader.__name__, e))
    return {"status": UNKNOWN, "source_time": None, "source": "error", "error": "; ".join(errors)}


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
    """{evening_date: {'few': min|None, 'full': min|None, 'checks': n, 'usable_full': bool, ...}}"""
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

def notify(title, message, page_url=None):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    body = {"topic": topic, "title": title, "message": message, "tags": ["car"]}
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


def run_alerts(rows, current, now, state_path):
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    ev = evening_of(now)
    if ev is None:
        return
    key = ev.isoformat()
    page = os.environ.get("PAGE_URL") or None
    changed = False

    # 1) Status just turned few/full this evening.
    prev = None
    for row in reversed(rows[:-1]):
        _, s = effective(row)
        if s != UNKNOWN:
            prev = s
            break
    _, cur = effective(rows[-1])
    sent = state.setdefault("sent", {})
    if cur in (FEW, FULL) and prev not in (None, cur) and sent.get(key + ":" + cur) is None:
        if cur == FEW:
            ok = notify("Assuta: few spaces left", "Few spaces at Assuta now (%s). Go now to get a spot." % now.strftime("%H:%M"), page)
        else:
            ok = notify("Assuta is full", "Assuta turned full at about %s. Check the page for Plan B." % now.strftime("%H:%M"), page)
        if ok:
            sent[key + ":" + cur] = now.strftime(FMT)
            changed = True

    # 2) Heads-up before the usual fill time.
    p = predict(evenings(rows), ev.weekday(), ev)
    if p and cur != FULL and sent.get(key + ":pre") is None:
        mins = minutes_after_noon(now, ev)
        if p["arrive_by"] - ALERT_AHEAD_MIN <= mins < p["arrive_by"]:
            ok = notify(
                "Head to Assuta soon",
                "It usually fills around %s on %ss (%d of %d evenings). Aim to park by %s."
                % (hhmm(p["full_median"]), ev.strftime("%A") if p["scope"] == "weekday" else "recent day",
                   p["filled"], p["evenings"], hhmm(p["arrive_by"])), page)
            if ok:
                sent[key + ":pre"] = now.strftime(FMT)
                changed = True

    if changed:
        # keep two weeks of alert history
        cutoff = (ev - timedelta(days=14)).isoformat()
        state["sent"] = {k: v for k, v in sent.items() if k[:10] >= cutoff}
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="folder holding assuta.csv")
    ap.add_argument("--analyze", action="store_true", help="print the pattern and exit")
    args = ap.parse_args()
    os.makedirs(args.data, exist_ok=True)
    log = os.path.join(args.data, "assuta.csv")
    now = datetime.now(IL).replace(tzinfo=None, second=0, microsecond=0)

    if args.analyze:
        rows = load_rows(log)
        evs = evenings(rows)
        for d in sorted(evs):
            r = evs[d]
            f = hhmm(r["full"]) if isinstance(r["full"], int) else r["full"]
            print(d, d.strftime("%a"), "checks=%d" % r["checks"], "full=%s" % f)
        for wd in range(7):
            print(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd], predict(evs, wd, now.date() + timedelta(days=1)))
        return

    st = read_status()
    row = {
        "checked_at": now.strftime(FMT),
        "status": st["status"],
        "source_time": st["source_time"].strftime(FMT) if st["source_time"] else "",
        "source": st["source"],
    }
    append_row(log, row)
    print("Assuta:", row, st.get("error", ""))
    rows = load_rows(log)
    run_alerts(rows, st, now, os.path.join(args.data, "alerts.json"))


if __name__ == "__main__":
    main()
