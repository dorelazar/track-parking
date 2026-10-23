import json, urllib.request, urllib.parse, os, re
OUT="out"; os.makedirs(OUT, exist_ok=True)
H={"User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"}
def get(url,data=None,t=60,h=None):
    req=urllib.request.Request(url,data=data,headers=h or H)
    with urllib.request.urlopen(req,timeout=t) as r: return r.read()
def save(n,fn):
    try: b=fn(); open(os.path.join(OUT,n),"wb").write(b); print("ok",n,len(b))
    except Exception as e: open(os.path.join(OUT,n+".err"),"w").write(repr(e)); print("ERR",n,e)
for i in (122,3):
    save("ahuzot_%d.html"%i, lambda: get("https://www.ahuzot.co.il/Parking/ParkingDetails/?ID=%d"%i))
save("ahuzot_all.html", lambda: get("https://www.ahuzot.co.il/Parking/All/"))
save("ahuzot_home.html", lambda: get("https://www.ahuzot.co.il/"))
R="https://gisn.tel-aviv.gov.il/arcgis/rest/services"
for svc in ["IView2MapHeb","IView2RekaHeb"]:
    save("svc_%s.json"%svc, lambda: get(R+"/%s/MapServer/layers?f=json"%svc, t=180))
for path in ["docs/services","docs/services/CityParkingStations","docs/services/ParkingInfo","api-docs","swagger.json"]:
    save("apiportal_%s.html"%path.replace("/","_"), lambda: get("https://apiportal.tel-aviv.gov.il/"+path))
big=[34.7660,32.0790,34.7960,32.1010]
p={"where":"1=1","outFields":"*","returnGeometry":"true","outSR":"4326","f":"json","geometry":",".join(map(str,big)),"geometryType":"esriGeometryEnvelope","inSR":"4326","spatialRel":"esriSpatialRelIntersects"}
save("signs_big.json", lambda: get(R+"/IView2/MapServer/449/query", data=urllib.parse.urlencode(p).encode()))
save("lines_big.json", lambda: get(R+"/IView2/MapServer/450/query", data=urllib.parse.urlencode(p).encode()))
q='[out:json][timeout:60];(way(around:800,32.0890,34.7800)[highway]["parking:condition:both:time_interval"];way(around:800,32.0890,34.7800)[highway][~"^parking:.*"~"."];node(around:800,32.0890,34.7800)[~"^parking"~"."];);out tags geom;'
for host in ["https://overpass-api.de/api/interpreter","https://overpass.private.coffee/api/interpreter"]:
    try: open(os.path.join(OUT,"osm_parking.json"),"wb").write(get(host,data=urllib.parse.urlencode({"data":q}).encode(),t=90)); print("ok osm"); break
    except Exception as e: print("ERR osm",e)
