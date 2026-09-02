from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json, mimetypes, uuid, shutil, re

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'orders.json'
UPLOADS = ROOT / 'uploads'
INDEX = ROOT / 'index.html'
UPLOADS.mkdir(exist_ok=True)
DATA.parent.mkdir(exist_ok=True)
if not DATA.exists(): DATA.write_text('[]', encoding='utf-8')


def read_orders():
    try: return json.loads(DATA.read_text(encoding='utf-8'))
    except Exception: return []

def save_orders(items):
    DATA.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')

def clean_number(value):
    return re.sub(r'[^A-Za-zА-Яа-яЁё0-9_-]', '_', str(value).strip())[:80] or 'без_номера'

def send_json(handler, payload, status=200):
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status); handler.send_header('Content-Type','application/json; charset=utf-8'); handler.send_header('Content-Length', str(len(raw))); handler.end_headers(); handler.wfile.write(raw)

class App(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/orders': return send_json(self, read_orders())
        if path.startswith('/uploads/'):
            file = (ROOT / path.lstrip('/')).resolve()
            if not str(file).startswith(str(UPLOADS.resolve())) or not file.is_file(): return send_json(self, {'error':'Файл не найден'}, 404)
            raw=file.read_bytes(); self.send_response(200); self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path in ('/', '/index.html'):
            raw=INDEX.read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_error(404)
    def do_POST(self):
        if urlparse(self.path).path != '/api/orders': return self.send_error(404)
        length=int(self.headers.get('Content-Length','0'))
        if length > 40*1024*1024: return send_json(self, {'error':'Размер запроса больше 40 МБ'}, 413)
        try:
            boundary=self.headers.get('Content-Type','').split('boundary=',1)[1].encode()
            body=self.rfile.read(length); parts=body.split(b'--'+boundary)
            fields={}; files=[]
            for part in parts:
                if b'\r\n\r\n' not in part: continue
                head, content=part.split(b'\r\n\r\n',1); content=content.rstrip(b'\r\n-')
                name=re.search(br'name="([^"]+)"',head); filename=re.search(br'filename="([^"]*)"',head)
                if not name: continue
                key=name.group(1).decode('utf-8','ignore')
                if filename and filename.group(1): files.append((key, filename.group(1).decode('utf-8','ignore'), content))
                else: fields[key]=content.decode('utf-8','ignore')
            number=fields.get('number','').strip()
            if not number: return send_json(self, {'error':'Укажите номер заказа'}, 400)
            orders=read_orders()
            if any(str(x.get('number','')).casefold()==number.casefold() for x in orders): return send_json(self, {'error':'Такой номер заказа уже существует'}, 409)
            order_id=uuid.uuid4().hex; folder=UPLOADS / clean_number(number); folder.mkdir(exist_ok=True)
            photos=[]
            for _, original, content in files:
                ext=Path(original).suffix.lower()
                if ext not in {'.jpg','.jpeg','.png','.gif','.webp','.bmp'}: continue
                filename=uuid.uuid4().hex[:12]+ext; (folder/filename).write_bytes(content); photos.append('/uploads/'+folder.name+'/'+filename)
            item={'id':order_id,'number':number,'customer':fields.get('customer','').strip(),'date':fields.get('date',''),'status':fields.get('status','new'),'description':fields.get('description','').strip(),'photos':photos}
            orders.insert(0,item); save_orders(orders); return send_json(self,item,201)
        except Exception as e: return send_json(self, {'error':'Не удалось сохранить заказ: '+str(e)}, 400)
    def do_DELETE(self):
        qs=parse_qs(urlparse(self.path).query); oid=qs.get('id',[''])[0]; orders=read_orders(); found=next((x for x in orders if x.get('id')==oid),None)
        if not found: return send_json(self, {'error':'Заказ не найден'},404)
        save_orders([x for x in orders if x.get('id')!=oid]); folder=UPLOADS/clean_number(found.get('number','')); shutil.rmtree(folder,ignore_errors=True); send_json(self, {'ok':True})

print('Трекер заказов: http://127.0.0.1:8000')
ThreadingHTTPServer(('127.0.0.1',8000),App).serve_forever()
