import json, urllib.request, urllib.parse, os
OUT = "out"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "track-parking probe (personal)"}
BASE = "https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2/MapServer/%d/query"
def get(url, data=None, t=120):
    req = urllib.request.Request(url, data=data, headers=H)
    with urllib.request.urlopen(req, timeout=t) as r: return r.read()
def q(layer, name, bbox=None, where="1=1", geom=True):
    p = {"where": where, "outFields": "*", "returnGeometry": "true" if geom else "false", "outSR": "4326", "f": "json"}
    if bbox:
        p.update({"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"})
    try:
        b = get(BASE % layer, data=urllib.parse.urlencode(p).encode())
        open(os.path.join(OUT, name), "wb").write(b); print("ok", name, len(b))
    except Exception as e:
        open(os.path.join(OUT, name + ".err"), "w").write(repr(e)); print("ERR", name, e)
near = [34.7700, 32.0820, 34.7920, 32.0980]   # ~1 km around Basel/Assuta
q(507, "streets.json", near)
q(450, "loading_lines.json", near)
q(449, "loading_signs.json", near)
q(568, "synagogues.json", near)
q(544, "zones.json", near)
q(488, "night_lots.json")
q(970, "lots.json")
# OpenStreetMap: streets with parking tags around the lots (backup / extra detail)
oq = '[out:json][timeout:60];way(around:900,32.0890,34.7800)[highway][name];out tags geom;'
for host in ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]:
    try:
        b = get(host, data=urllib.parse.urlencode({"data": oq}).encode()); open(os.path.join(OUT, "osm.json"), "wb").write(b); print("ok osm", host, len(b)); break
    except Exception as e:
        print("ERR osm", host, e)
