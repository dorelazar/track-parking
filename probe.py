import json, urllib.request, urllib.parse, os
OUT="out"; os.makedirs(OUT, exist_ok=True)
H={"User-Agent":"track-parking probe (personal)"}
R="https://gisn.tel-aviv.gov.il/arcgis/rest/services"
def get(url,data=None,t=120):
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=H),timeout=t) as r: return r.read()
def save(n,b): open(os.path.join(OUT,n),"wb").write(b); print("ok",n,len(b))
for folder in ["OpenData","WM","Utilities"]:
    try:
        d=json.loads(get(R+"/"+folder+"?f=json")); save(folder+".json", json.dumps(d,ensure_ascii=False).encode())
        for s in d.get("services",[]):
            try: save("svc_"+s["name"].replace("/","_")+".json", get("%s/%s/%s/layers?f=json"%(R,s["name"],s["type"]),t=180))
            except Exception as e: print("ERR",s,e)
    except Exception as e: print("ERR folder",folder,e)
near=[34.7740,32.0850,34.7860,32.0950]
p={"where":"1=1","outFields":"*","returnGeometry":"true","outSR":"4326","f":"json","geometry":",".join(map(str,near)),"geometryType":"esriGeometryEnvelope","inSR":"4326","spatialRel":"esriSpatialRelIntersects"}
for lid in (449,450):
    try: save("near_%d.json"%lid, get(R+"/IView2/MapServer/%d/query"%lid, data=urllib.parse.urlencode(p).encode()))
    except Exception as e: print("ERR",lid,e)
