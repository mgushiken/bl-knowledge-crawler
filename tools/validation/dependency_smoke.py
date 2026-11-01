from pathlib import Path
import sys
from importlib.metadata import version
from playwright.sync_api import sync_playwright
from PIL import Image
from markdownify import markdownify
import yaml,io,json
# This only starts the bundled driver; it does not connect to or launch a browser.
with sync_playwright() as p:
    assert p.chromium.name=='chromium'
b=io.BytesIO();Image.new('RGB',(2,2)).save(b,format='PNG')
with Image.open(io.BytesIO(b.getvalue())) as im:im.load();assert im.size==(2,2)
assert yaml.safe_load('x: 1')['x']==1
assert '# Probe' in markdownify('<h1>Probe</h1>',heading_style='ATX')
print(json.dumps({'probe':'dependency-smoke','ok':True,'frozen':bool(getattr(sys,'frozen',False))}))
