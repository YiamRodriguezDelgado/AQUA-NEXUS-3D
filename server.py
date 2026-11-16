"""AQUA NEXUS v1.6 - servidor sin dependencias externas."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen, Request
import json, os, socket, webbrowser, time, re, csv, io, math, xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        path=urlparse(self.path).path
        if path!='/api/stations/import': return self.send_json({'ok':False,'error':'Ruta no disponible'},404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1500000: return self.send_json({'ok':False,'error':'CSV vacío o mayor a 1,5 MB'},413)
            raw=self.rfile.read(length).decode('utf-8-sig')
            delim=';' if raw.splitlines()[0].count(';')>raw.splitlines()[0].count(',') else ','
            reader=csv.DictReader(io.StringIO(raw),delimiter=delim)
            required={'fecha','nivel_m','caudal_m3s'}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                return self.send_json({'ok':False,'error':'Columnas requeridas: fecha,nivel_m,caudal_m3s'},400)
            from datetime import datetime
            records=[]
            for row in reader:
                try:
                    day=date.fromisoformat(row['fecha'].strip())
                    def numeric(v):
                        v=(v or '').strip().replace(',','.')
                        if not v:return None
                        f=float(v)
                        return f if math.isfinite(f) else None
                    level=numeric(row.get('nivel_m'))
                    flow=numeric(row.get('caudal_m3s'))
                    if level is None and flow is None:continue
                    records.append({'date':day.isoformat(),'month':day.strftime('%Y%m'),'level_m':level,'flow_m3s':flow})
                except (ValueError,TypeError): continue
                if len(records)>10000:break
            if not records:return self.send_json({'ok':False,'error':'No hay observaciones válidas con fechas ISO AAAA-MM-DD'},400)
            records.sort(key=lambda r:r['date'])
            return self.send_json({'ok':True,'source':'CSV importado por el usuario; procedencia no verificada','count':len(records),'records':records,'min_date':records[0]['date'],'max_date':records[-1]['date']})
        except Exception as exc:return self.send_json({'ok':False,'error':str(exc)},400)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/nasa/historical':
            params=parse_qs(urlparse(self.path).query)
            zone=params.get('zone',['artigas'])[0].lower()
            sites={'artigas':(-30.40,-56.47),'salto':(-31.39,-57.96),'paysandu':(-32.32,-58.08)}
            if zone not in sites:return self.send_json({'ok':False,'error':'Zona inválida'},400)
            try:
                lat,lon=sites[zone]
                query=urlencode({'parameters':'PRECTOTCORR','community':'AG','longitude':lon,'latitude':lat,'start':'20180101','end':'20251231','format':'JSON','time-standard':'UTC'})
                req=Request('https://power.larc.nasa.gov/api/temporal/daily/point?'+query,headers={'User-Agent':'AquaNexus/2.6 educational'})
                with urlopen(req,timeout=60) as resp:data=json.load(resp)
                daily=data['properties']['parameter']['PRECTOTCORR']
                grouped={}
                for d,v in daily.items():
                    try:
                        val=float(v)
                        if not math.isfinite(val) or val<0:continue
                        key=d[:4]+'-'+d[4:6]
                        grouped[key]=grouped.get(key,0)+val
                    except (ValueError,TypeError):continue
                records=[{'mes':k,'lluvia_mm':round(v,2)} for k,v in sorted(grouped.items())]
                return self.send_json({'ok':True,'zone':zone,'source':'NASA POWER PRECTOTCORR diario, sumado por mes; punto aproximado de ciudad','coordinates':{'lat':lat,'lon':lon},'records':records,'count':len(records),'coverage':'2018-2025','limitations':'Precipitación en un punto de rejilla, no observación de superficie inundada ni predicción.'})
            except Exception as exc:return self.send_json({'ok':False,'error':'No se pudo consultar NASA POWER: '+str(exc)},503)
        if path == '/api/health':
            return self.send_json({'ok': True, 'version':'3.4', 'mode':'prototipo'})
        if path == '/api/gibs/layers':
            # Discover GIBS layers rather than assuming an unavailable IMERG layer.
            try:
                req=Request('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0',headers={'User-Agent':'AquaNexus/1.9'})
                with urlopen(req,timeout=18) as response: raw=response.read(4000000)
                root=ET.fromstring(raw)
                layers=[]
                for layer in root.iter():
                    if layer.tag.rsplit('}',1)[-1]!='Layer':continue
                    nm=next((n.text for n in layer if n.tag.rsplit('}',1)[-1]=='Name'),None)
                    title=next((n.text for n in layer if n.tag.rsplit('}',1)[-1]=='Title'),None)
                    if nm and any(x in (nm+' '+str(title)).lower() for x in ('imerg','precipitation','rainfall')):
                        layers.append({'id':nm,'title':title or nm})
                return self.send_json({'ok':True,'source':'NASA GIBS WMS GetCapabilities','layers':layers[:60]})
            except Exception as exc:return self.send_json({'ok':False,'error':str(exc)},503)
        if path == '/api/gibs/map':
            params=parse_qs(urlparse(self.path).query)
            layer=params.get('layer',[''])[0]
            # Only identifiers previously discovered by GIBS are selectable in the UI.
            if not re.fullmatch(r'[A-Za-z0-9_\-]{3,130}',layer):return self.send_json({'ok':False,'error':'Nombre de capa inválido'},400)
            day=params.get('date',['2025-01-15'])[0]
            try:date.fromisoformat(day)
            except ValueError:return self.send_json({'ok':False,'error':'Fecha inválida'},400)
            query=urlencode({'SERVICE':'WMS','VERSION':'1.1.1','REQUEST':'GetMap','LAYERS':layer,'STYLES':'','FORMAT':'image/png','TRANSPARENT':'TRUE','SRS':'EPSG:4326','BBOX':'-59,-35.5,-50,-26','WIDTH':'800','HEIGHT':'760','TIME':day})
            try:
                req=Request('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?'+query,headers={'User-Agent':'AquaNexus/1.9'})
                with urlopen(req,timeout=25) as response:
                    content_type=response.headers.get('Content-Type','')
                    data=response.read(6000000)
                if 'image/png' not in content_type or not data.startswith(b'\x89PNG'):raise ValueError('GIBS no devolvió una imagen PNG para esta fecha y capa')
                self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except Exception as exc:return self.send_json({'ok':False,'error':str(exc)},503)
            return
        if path == '/api/hydro/osm':
            # On-demand real OSM waterway records around the binational Cuareim basin.
            # This is an inventory, not an official basin delineation or a flood forecast.
            query = '[out:json][timeout:20];(way["waterway"="river"]["name"](-31.25,-58.45,-29.55,-55.70););out tags center 65;'
            try:
                endpoint='https://overpass.kumi.systems/api/interpreter?'+urlencode({'data':query})
                req=Request(endpoint,headers={'User-Agent':'AquaNexusPrototype/1.8 (educational hydrology)'})
                with urlopen(req,timeout=23) as res: data=json.load(res)
                elements=data.get('elements',[])
                names=sorted({e.get('tags',{}).get('name','').strip() for e in elements if e.get('tags',{}).get('name')})
                return self.send_json({'ok':True,'source':'OpenStreetMap / Overpass API','region':'Cuareim y entorno binacional (rectangulo de consulta)','count_segments':len(elements),'names':names[:75],'limitations':'Inventario OSM incompleto; no es hidrografia oficial ni representa caudales.'})
            except Exception as exc:
                return self.send_json({'ok':False,'error':str(exc),'names':[]},503)
        if path == '/api/nasa/power':
            url = ('https://power.larc.nasa.gov/api/temporal/monthly/point?'
                   'parameters=PRECTOTCORR&community=AG&longitude=-56.90&latitude=-30.40'
                   '&format=JSON&start=2023&end=2025')
            try:
                req=Request(url,headers={'User-Agent':'AquaNexusPrototype/1.8'})
                with urlopen(req,timeout=15) as res:
                    data=json.load(res)
                values=data.get('properties',{}).get('parameter',{}).get('PRECTOTCORR',{})
                records=[{'month':k,'mm_day':v} for k,v in sorted(values.items()) if len(k)==6 and isinstance(v,(float,int)) and v>=0]
                if not records: raise ValueError('NASA POWER no devolvio meses validos')
                return self.send_json({'ok':True,'source':'NASA POWER','location':'Artigas, Uruguay (punto, no cuenca)','unit':'mm/dia, promedio mensual','records':records})
            except Exception as exc:
                return self.send_json({'ok':False,'error':str(exc),'records':[]},503)
        if path == '/': self.path='/static/index.html'
        return super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma','no-cache')
        self.send_header('Expires','0')
        super().end_headers()

    def send_json(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw))); self.end_headers();self.wfile.write(raw)

if __name__=='__main__':
    port=int(os.environ.get('AQUA_PORT','8711'))
    while port<8711:
        with socket.socket() as s:
            try: s.bind(('127.0.0.1',port));break
            except OSError:port+=1
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'AQUA NEXUS 3D v3.7 CASO HISTORICO SINAE: http://127.0.0.1:{port}',flush=True)
    try: webbrowser.open(f'http://127.0.0.1:{port}/?version=4.0&nocache={int(time.time())}')
    except Exception: pass
    try: server.serve_forever()
    except KeyboardInterrupt: pass
