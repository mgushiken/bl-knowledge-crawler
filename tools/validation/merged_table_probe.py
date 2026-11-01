from markdownify import MarkdownConverter
from bs4 import BeautifulSoup
from copy import deepcopy
import hashlib
class ProbeConverter(MarkdownConverter):
    """Trial conversion for the agreed merged-cell HTML table policy."""
    def __init__(self,image_reference,**kwargs):
        """Inject a reference resolver without adding network access."""
        self.image_reference=image_reference
        super().__init__(**kwargs)
    def convert_img(self,el,text,parent_tags):
        """Map fixed dummy images through the same reference resolver."""
        return '!['+el.get('alt','')+']('+self.image_reference(el['src'])+')'
    def convert_table(self,el,text,parent_tags):
        """Retain merged tables and rewrite their images before serializing HTML."""
        merged=any(int(cell.get(attr,'1'))>1 for cell in el.find_all(['td','th']) for attr in ['rowspan','colspan'])
        if not merged:return super().convert_table(el,text,parent_tags)
        clone=deepcopy(el)
        for img in clone.find_all('img'):img['src']=self.image_reference(img['src'])
        return '\n\n'+str(clone)+'\n\n'
html='<h2>Table</h2><table><tr><td rowspan="2">R</td><td>A<img alt="dummy" src="https://example.invalid/image"></td></tr><tr><td>B</td></tr></table>'
outputs=[]
for ref in ('assets/'+'a'*64+'/'+'b'*64+'.png','bl-image-sha256:'+'b'*64):
    md=ProbeConverter(lambda _:ref,heading_style='ATX',strip_pre=None,wrap=False).convert(html)
    soup=BeautifulSoup(md,'html.parser');table=soup.find('table')
    assert table and table.find('td')['rowspan']=='2'
    assert len(table.find_all('tr'))==2 and len(table.find_all('td'))==3
    assert table.find('img')['src']==ref
    assert 'https://example.invalid/image' not in md
    outputs.append(md)
assert hashlib.sha256(outputs[0].encode()).digest()!=hashlib.sha256(outputs[1].encode()).digest()
print('PASS: merged-table HTML retains rows/cells/rowspan and both local/hash image references')

colspan_html='<table><tr><th colspan="2">Merged</th></tr><tr><td>A</td><td><img src="https://example.invalid/image"></td></tr></table>'
for ref in ('assets/image.png','bl-image-sha256:'+'b'*64):
    md=ProbeConverter(lambda _:ref,heading_style='ATX',strip_pre=None,wrap=False).convert(colspan_html)
    table=BeautifulSoup(md,'html.parser').find('table')
    assert table.find('th')['colspan']=='2'
    assert len(table.find_all('tr'))==2 and len(table.find_all(['td','th']))==3
    assert table.find('img')['src']==ref

normal=ProbeConverter(lambda _:'assets/image.png',heading_style='ATX').convert('<table><tr><th>H</th></tr><tr><td>V</td></tr></table>')
assert '<table' not in normal and '| H |' in normal and '| V |' in normal
print('PASS: colspan is retained as HTML and ordinary tables remain Markdown')
