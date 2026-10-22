import json, urllib.request, urllib.parse, os, sys, time
OUT = "out"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "track-parking probe (personal)"}
def get(url, data=None, t=90):
    req = urllib.request.Request(url, data=data, headers=H)
    with urllib.request.urlopen(req, timeout=t) as r: return r.read()
def save(name, b):
    open(os.path.join(OUT, name), "wb").write(b if isinstance(b, bytes) else b.encode())
def safe(name, fn):
    try: save(name, fn()); print("ok", name)
    except Exception as e: save(name + ".err", repr(e)); print("ERR", name, e)

GIS = "https://gisn.tel-aviv.gov.il/arcgis/rest/services"
safe("services.json", lambda: get(GIS + "?f=json"))
safe("iview2_layers.json", lambda: get(GIS + "/IView2/MapServer/layers?f=json", t=180))
safe("lots_970.json", lambda: get(GIS + "/IView2/MapServer/970/query?where=1%3D1&outFields=*&returnGeometry=false&f=json"))

q = """[out:json][timeout:60];
(
 way(around:900,32.0890,34.7840)[highway][name];
 nwr(around:900,32.0890,34.7840)[amenity=place_of_worship];
 nwr(around:900,32.0890,34.7840)[amenity=parking];
 way(around:900,32.0890,34.7840)["parking:lane:both"];
 way(around:900,32.0890,34.7840)["parking:both"];
 way(around:900,32.0890,34.7840)["parking:left"];
 way(around:900,32.0890,34.7840)["parking:right"];
);
out tags geom;"""
for host in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
    try:
        save("osm.json", get(host, data=urllib.parse.urlencode({"data": q}).encode(), t=120)); print("ok osm", host); break
    except Exception as e: print("ERR osm", host, e)
