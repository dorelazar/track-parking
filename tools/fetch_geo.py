"""Download the raw map data that tools/build_geo.py turns into geo.json.

Usage: python3 tools/fetch_geo.py RAW_DIR
Sources: Tel Aviv municipality GIS (IView2 MapServer) and OpenStreetMap (Overpass).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

H = {"User-Agent": "track-parking map refresh (personal, monthly)"}
LAYER = "https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2/MapServer/%d/query"
BOX = [34.7700, 32.0820, 34.7920, 32.0980]          # about 1 km around Assuta and Basel
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def post(url, params, timeout=120, tries=4):
    """POST with retries: the city server sometimes answers 502/504 for a minute."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), headers=H)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            print("retrying after", e)
            time.sleep(15 * (attempt + 1))


def layer(lid, box=True):
    p = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "json"}
    if box:
        p.update({"geometry": ",".join(map(str, BOX)), "geometryType": "esriGeometryEnvelope",
                  "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"})
    data = post(LAYER % lid, p)
    if "error" in json.loads(data):
        raise RuntimeError("layer %d: %s" % (lid, data[:200]))
    return data


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    files = {"lots.json": (lambda: layer(970, box=False), True),
             "loading_signs.json": (lambda: layer(449), True),
             "night_lots.json": (lambda: layer(488, box=False), True),
             "synagogues.json": (lambda: layer(568), False)}
    for name, (fn, required) in files.items():
        try:
            data = fn()
        except Exception as e:  # noqa: BLE001
            if required:
                raise
            print("skipped optional", name, e)
            continue
        open(os.path.join(out, name), "wb").write(data)
        print("ok", name)
    q = '[out:json][timeout:60];way(around:900,32.0890,34.7800)[highway][name];out tags geom;'
    for host in OVERPASS:
        try:
            open(os.path.join(out, "osm.json"), "wb").write(post(host, {"data": q}))
            print("ok osm.json from", host)
            return
        except Exception as e:  # noqa: BLE001 - try the next mirror
            print("overpass failed:", host, e)
    raise SystemExit("all Overpass mirrors failed")


if __name__ == "__main__":
    main()
