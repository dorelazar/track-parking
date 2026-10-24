import json, urllib.request, os, re
OUT="out"; os.makedirs(OUT, exist_ok=True)
H={"User-Agent":"Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile Safari/537.36"}
def get(u,t=40):
    with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=t) as r: return r.read().decode("utf-8","replace")
res={}
for i in (122,3,77,86):
    try:
        h=get("https://www.ahuzot.co.il/Parking/ParkingDetails/?ID=%d"%i)
        m=re.search(r'ParkingDetailsTable.*?IconText[^>]*>([^<]+)<.*?<img[^>]+src="([^"]+)"',h,re.S)
        res[i]=m.groups() if m else "no match"
    except Exception as e: res[i]="ERR "+repr(e)
try:
    d=json.loads(get("https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2/MapServer/970/query?where=1%3D1&outFields=shem_chenyon,status_chenyon,tr_status_chenyon,UniqueId&returnGeometry=false&f=json"))
    ts=[f["attributes"]["tr_status_chenyon"] for f in d["features"]]
    import datetime
    res["gis_max"]=str(datetime.datetime.utcfromtimestamp(max(t for t in ts if t)/1000)); res["gis_min"]=str(datetime.datetime.utcfromtimestamp(min(t for t in ts if t)/1000))
    res["gis_uniq"]=list({f["attributes"]["UniqueId"] for f in d["features"]})[:3]
    res["gis_lots"]={f["attributes"]["shem_chenyon"]:f["attributes"]["status_chenyon"] for f in d["features"] if f["attributes"]["shem_chenyon"] in ("אסותא","בזל")}
except Exception as e: res["gis"]="ERR "+repr(e)
json.dump(res,open(OUT+"/now.json","w"),ensure_ascii=False,indent=1); print(res)
