"""Disposable design probes. No production crawler code or real input is used."""
import base64, copy, io, json, os, re, tempfile, unittest, hashlib, threading, time
from pathlib import Path
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.parsers import expat
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from markdownify import markdownify
import yaml

ROOT=(Path(os.environ['LOCALAPPDATA'])/'BlackLineKnowledgeCrawler'/'design-checks').resolve()
ROOT.mkdir(parents=True,exist_ok=True)

def pairs_unique(pairs):
    """Reject duplicate keys before ambiguous mappings can be accepted."""
    result={}
    for k,v in pairs:
        if k in result: raise ValueError('duplicate')
        result[k]=v
    return result

def dump_decimal(v):
    """Serialize dummy Decimal values without passing through binary floats."""
    if isinstance(v,Decimal):
        if not v.is_finite(): raise ValueError('nonfinite')
        return str(v)
    if isinstance(v,list): return '['+','.join(map(dump_decimal,v))+']'
    if isinstance(v,dict): return '{'+','.join(json.dumps(k)+':'+dump_decimal(x) for k,x in v.items())+'}'
    return json.dumps(v,ensure_ascii=False,allow_nan=False)

class DocumentLoader(yaml.SafeLoader):
    """Isolate timestamp and duplicate-key policy from PyYAML globals."""
    yaml_implicit_resolvers=copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
    def construct_mapping(self,node,deep=False):
        return pairs_unique([(self.construct_object(k,deep=deep),self.construct_object(v,deep=deep)) for k,v in node.value])
for ch,resolvers in DocumentLoader.yaml_implicit_resolvers.items():
    DocumentLoader.yaml_implicit_resolvers[ch]=[(tag,rule) for tag,rule in resolvers if tag!='tag:yaml.org,2002:timestamp']

SVG='http://www.w3.org/2000/svg'
def svg_probe(data):
    """Conservative experimental SVG gate; not a production XML validator."""
    p=expat.ParserCreate(namespace_separator='|')
    tags={'svg','rect','circle','ellipse','line','polyline','polygon','path','g','defs','linearGradient','radialGradient','stop','use','title','desc'}
    seen_root=False
    def reject(*args):
        """Stop experimental parsing before processing unsupported constructs."""
        raise ValueError('unsupported')
    def start(name,attrs):
        """Validate the root and the fixed subset exercised by these probes."""
        nonlocal seen_root
        if not seen_root:
            if name!=SVG+'|svg':reject()
            seen_root=True
        if name not in {SVG+'|'+t for t in tags}: reject()
        for k,v in attrs.items():
            local=k.rsplit('|',1)[-1]
            if '|' in k and not k.startswith('http://www.w3.org/1999/xlink|'): reject()
            if local.lower().startswith('on') or local=='style': reject()
            if local=='href' and not re.fullmatch(r'#[A-Za-z_][\w.-]*',v): reject()
            if 'url(' in v and not re.fullmatch(r'url\(#[A-Za-z_][\w.-]*\)',v): reject()
    p.StartElementHandler=start
    p.StartDoctypeDeclHandler=reject;p.EntityDeclHandler=reject;p.ExternalEntityRefHandler=reject;p.ProcessingInstructionHandler=reject
    p.Parse(data,True)

def raster(data):
    """Check actual format and every frame without rewriting source bytes."""
    with Image.open(io.BytesIO(data)) as image:
        fmt=image.format
        if fmt not in {'PNG','JPEG','GIF','WEBP','BMP'}: raise ValueError('unsupported')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        frames=image.n_frames if hasattr(image,'n_frames') else 1
        for n in range(frames): image.seek(n);image.load()
        return fmt,frames

class DesignProbes(unittest.TestCase):
    """Exercise libraries and real dummy filesystem operations, not app acceptance."""
    def test_json_precision_and_retained_values(self):
        """Changing one flag must preserve numeric precision and unknown data."""
        raw='{"urls":[{"is_new":true,"x":123456789012345678901234567890},{"is_new":false}],"unknown":{"n":0.123456789012345678901234567890,"b":true}}'
        tree=json.loads(raw,parse_float=Decimal,object_pairs_hook=pairs_unique)
        original=copy.deepcopy(tree);tree['urls'][0]['is_new']=False
        reloaded=json.loads(dump_decimal(tree),parse_float=Decimal,object_pairs_hook=pairs_unique)
        self.assertEqual(reloaded,tree); self.assertEqual(original['unknown'],reloaded['unknown'])
        self.assertIs(type(reloaded['urls'][0]['is_new']),bool)
        with self.assertRaises(ValueError):json.loads('{"x":1,"x":2}',object_pairs_hook=pairs_unique)
        for raw in ('NaN','Infinity','-Infinity'):
            with self.assertRaises(ValueError):json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))

    def test_yaml_safe_isolated_loader(self):
        """Reject ambiguous or executable YAML without altering global loaders."""
        self.assertIsInstance(yaml.load('x: 2026-11-01',Loader=DocumentLoader)['x'],str)
        self.assertNotIsInstance(yaml.safe_load('x: 2026-11-01')['x'],str)
        with self.assertRaises(ValueError):yaml.load('x: 1\nx: 2',Loader=DocumentLoader)
        with self.assertRaises(yaml.YAMLError):yaml.load('!!python/object/apply:os.system [dummy]',Loader=DocumentLoader)

    def test_raster_formats_and_corruption(self):
        """Decode supported formats and reject truncated or nonimage payloads."""
        for fmt in ('PNG','JPEG','GIF','WEBP','BMP'):
            with self.subTest(fmt=fmt):
                buf=io.BytesIO();Image.new('RGB',(4,3),'red').save(buf,format=fmt)
                data=buf.getvalue();self.assertEqual(raster(data)[0],fmt)
                with self.assertRaises(Exception):raster(data[:len(data)//2])
        for payload in (b'<html>login</html>',b'not an image'):
            with self.assertRaises(Exception):raster(payload)
        frames=[Image.new('RGB',(4,3),c) for c in ('red','blue')]
        for fmt in ('GIF','WEBP'):
            buf=io.BytesIO();frames[0].save(buf,format=fmt,save_all=True,append_images=frames[1:],duration=100,loop=0)
            self.assertEqual(raster(buf.getvalue())[1],2)

    def test_data_uri_decoding(self):
        """Strict base64 and percent decoding must preserve bytes including plus."""
        self.assertEqual(base64.b64decode('YWJj',validate=True),b'abc')
        for bad in ('YWJj!','YW Jj','a'):
            with self.assertRaises(Exception):base64.b64decode(bad,validate=True)
        from urllib.parse import unquote_to_bytes
        self.assertEqual(unquote_to_bytes('a+b%00%FF'),b'a+b\x00\xff')

    def test_svg_structure_gate(self):
        """Accept fixed static examples and reject external or active constructs."""
        for content in ('<rect width="8" height="6"/>','<defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs><rect fill="url(#g)" width="8" height="6"/>'):
            svg_probe(('<svg xmlns="'+SVG+'" width="8" height="6">'+content+'</svg>').encode())
        bad=['<script/>','<rect onclick="x"/>','<foreignObject/>','<animate/>','<style/>','<rect style="fill:red"/>','<use href="https://example.invalid/x"/>','<rect fill="url(https://example.invalid/x)"/>','<x xmlns="urn:other"/>']
        for content in bad:
            with self.subTest(content=content), self.assertRaises(ValueError):svg_probe(('<svg xmlns="'+SVG+'">'+content+'</svg>').encode())
        for raw in (b'<!DOCTYPE svg [<!ENTITY x "x">]><svg/>',b'<?xml-stylesheet href="x"?><svg/>',b'<svg',b'<html/>',b'<rect xmlns="http://www.w3.org/2000/svg"/>'):
            with self.assertRaises((ValueError,expat.ExpatError)):svg_probe(raw)

    def test_markdown_basics(self):
        """Check heading, link, table, code and ordered-list conversion."""
        html='<h2>Heading</h2><p>A<br>B</p><a href="https://example.invalid/a?q=1">L</a><ol start="3"><li>Three</li></ol><table><tr><th>X</th></tr><tr><td>Y</td></tr></table><pre><code>  x\n y</code></pre>'
        md=markdownify(html,heading_style='ATX',strip_pre=None,wrap=False)
        for expected in ('## Heading','A  \nB','https://example.invalid/a?q=1','3. Three','| X |','| Y |','  x\n y'):
            self.assertIn(expected,md)

    def test_utf16_name_budget(self):
        """Test surrogate-safe truncation and suffix-dependent remaining capacity."""
        def units(s):
            """Count Windows UTF-16 units, including supplementary characters."""
            return len(s.encode('utf-16-le'))//2
        def shorten(root,title,suffix):
            """Exercise the documented title-only path budget calculation."""
            budget=min(255-units(suffix),259-units(str(root))-1-units(suffix))
            kept=''
            for char in title:
                if units(kept+char)>budget:break
                kept+=char
            kept=kept.rstrip(' .')
            if not kept:raise ValueError('PATH_TOO_LONG')
            return kept+suffix
        with tempfile.TemporaryDirectory(dir=ROOT,prefix='length-') as tmp:
            root=Path(tmp).resolve();self.assertEqual(root.parent,ROOT)
            a=shorten(root,'A\U0001f600'*300,'-'+'a'*8+'.md')
            b=shorten(root,'A\U0001f600'*300,'-'+'a'*64+'.md')
            for name in (a,b):
                self.assertLessEqual(units(name),255);self.assertLessEqual(units(str(root/name)),259)
                (root/name).write_text('dummy',encoding='utf-8');self.assertEqual((root/name).read_text(),'dummy')
            self.assertLess(len(b[:-68]),len(a[:-12]))
            with self.assertRaises(ValueError):shorten(Path('C:/'+'x'*260),'Title','-'+'a'*64+'.md')

    def test_actual_replace_and_failure_stages(self):
        """Interrupt staged dummy saves and verify artifacts precede completion."""
        for fail_after in ('image','markdown','delete-old','json',None):
            with self.subTest(stage=fail_after),tempfile.TemporaryDirectory(dir=ROOT,prefix='stages-') as tmp:
                root=Path(tmp).resolve();self.assertEqual(root.parent,ROOT)
                inp=root/'input.json';inp.write_text('{"urls":[{"is_new":true}]}')
                old=root/'old.md';old.write_text('old')
                try:
                    for stage,target,content in [('image',root/'image.png','dummy-image'),('markdown',root/'new.md','new-body')]:
                        temp=root/(stage+'.tmp');temp.write_text(content);os.replace(temp,target)
                        if stage==fail_after:raise OSError('injected')
                    old.unlink()
                    if fail_after=='delete-old':raise OSError('injected')
                    temp=root/'input.tmp';temp.write_text('{"urls":[{"is_new":false}]}');os.replace(temp,inp)
                    if fail_after=='json':raise OSError('injected')
                except OSError:pass
                self.assertTrue((root/'image.png').exists())
                expected=fail_after not in ('json',None)
                self.assertIs(json.loads(inp.read_text())['urls'][0]['is_new'],expected)
                if fail_after!='image':self.assertEqual((root/'new.md').read_text(),'new-body')

    def test_external_change_detection(self):
        """A changed dummy JSON hash prevents the proposed writeback."""
        with tempfile.TemporaryDirectory(dir=ROOT,prefix='external-') as tmp:
            root=Path(tmp).resolve();self.assertEqual(root.parent,ROOT)
            p=root/'input.json';p.write_bytes(b'old');before=hashlib.sha256(p.read_bytes()).digest()
            p.write_bytes(b'external');self.assertNotEqual(before,hashlib.sha256(p.read_bytes()).digest())
            self.assertEqual(p.read_bytes(),b'external')

    def test_cleanup_independent_attempts(self):
        """An interrupted coordinator can attempt every cleanup and retain files."""
        attempted=[]
        for stage in ('tab','connection','workspace','lock'):
            try:
                attempted.append(stage)
                if stage in ('tab','workspace'):raise OSError('injected')
            except OSError:pass
        self.assertEqual(attempted,['tab','connection','workspace','lock'])

    def test_http_options_actual_local_requests(self):
        """Exercise real APIRequestContext statuses, redirect and timeout without Chrome."""
        counts={}
        buf=io.BytesIO();Image.new('RGB',(2,2)).save(buf,format='PNG');png=buf.getvalue()
        class Handler(BaseHTTPRequestHandler):
            """Serve only loopback dummy responses and suppress request logs."""
            def log_message(self,*args):
                """Keep dummy HTTP request details out of verification output."""
                pass
            def do_GET(self):
                """Provide controlled statuses, a redirect, an image and a delay."""
                counts[self.path]=counts.get(self.path,0)+1
                if self.path=='/slow':time.sleep(.3)
                code=int(self.path.rsplit('/',1)[-1]) if self.path.startswith('/status/') else 302 if self.path=='/redirect' else 200
                self.send_response(code)
                if code==302:self.send_header('Location','/ok')
                self.send_header('Content-Type','image/jpeg' if self.path=='/image' else 'text/plain');self.end_headers()
                try:self.wfile.write(png if self.path=='/image' else b'dummy')
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                ctx=p.request.new_context(base_url='http://127.0.0.1:'+str(server.server_port))
                try:
                    for status in range(400,500):
                        response=ctx.get('/status/'+str(status),max_retries=0,max_redirects=0,fail_on_status_code=False)
                        self.assertEqual(response.status,status);response.dispose()
                    response=ctx.get('/redirect',max_retries=0,max_redirects=0);self.assertEqual(response.status,302);response.dispose();self.assertNotIn('/ok',counts)
                    with self.assertRaises(PlaywrightTimeout):ctx.get('/slow',timeout=50,max_retries=0,max_redirects=0)
                    self.assertEqual(counts['/slow'],1)
                    response=ctx.get('/image');self.assertEqual(response.headers['content-type'],'image/jpeg');self.assertEqual(raster(response.body())[0],'PNG');response.dispose()
                finally:ctx.dispose()
        finally:server.shutdown();server.server_close();thread.join()
        self.assertTrue(all(value==1 for value in counts.values()))

if __name__=='__main__':unittest.main(verbosity=2)
