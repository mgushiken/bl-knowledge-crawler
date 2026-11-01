state.fixture=await context.newPage();
state.fixtureRequests=0;
await state.fixture.route('https://example.invalid/probe/**',async route=>{state.fixtureRequests++;await new Promise(r=>setTimeout(r,250));try{await route.fulfill({status:200,headers:{'access-control-allow-origin':'*'},body:'delayed'});}catch{}});
try {
 const result=await state.fixture.evaluate(async()=>{
  const checks={};
  const canvas=document.createElement('canvas');canvas.width=3;canvas.height=2;canvas.getContext('2d').fillRect(0,0,3,2);
  const data=canvas.toDataURL('image/png');const bytes=await (await fetch(data)).arrayBuffer();
  const b64=btoa(String.fromCharCode(...new Uint8Array(bytes)));
  const blob=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
  checks.blobMatchesData=[...new Uint8Array(await (await fetch(blob)).arrayBuffer())].join() === [...new Uint8Array(bytes)].join();
  URL.revokeObjectURL(blob);try{await fetch(blob);checks.revokedBlobRejected=false;}catch{checks.revokedBlobRejected=true;}
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),50);
  try{await fetch('https://example.invalid/probe/hang',{signal:controller.signal});checks.timeoutAbort=false;}catch(e){checks.timeoutAbort=e.name==='AbortError';}finally{clearTimeout(timer);}
  const decode=async text=>{const u=URL.createObjectURL(new Blob([text],{type:'image/svg+xml'}));try{const image=new Image();image.src=u;await image.decode();return image.naturalWidth>0&&image.naturalHeight>0;}finally{URL.revokeObjectURL(u);}};
  checks.staticSvgDecode=await decode('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="6"><rect width="8" height="6" fill="red"/></svg>');
  try{await decode('<svg');checks.brokenSvgRejected=false;}catch{checks.brokenSvgRejected=true;}
  const host=document.createElement('section');host.className='probe';document.body.append(host);
  host.innerHTML='<p class="snapshot">before</p><div hidden>nonempty</div><img alt="one"><div style="height:3000px"></div><img alt="two" loading="lazy">';
  const imgs=host.querySelectorAll('img');imgs[0].src=data;imgs[1].src=data;
  checks.hiddenNonemptyDetected=host.querySelector('[hidden]').textContent.length>0&&host.querySelector('[hidden]').getClientRects().length===0;
  const snap=host.innerHTML;host.querySelector('.snapshot').textContent='after';checks.snapshotMutationDetected=host.innerHTML!==snap;
  const closed=document.createElement('div');closed.attachShadow({mode:'closed'}).innerHTML='<span>hidden from extraction</span>';checks.closedShadowUnavailable=closed.shadowRoot===null;
  return {checks,b64};
 });
 await state.fixture.locator('img[alt="two"]').scrollIntoViewIfNeeded();
 const images=await state.fixture.locator('.probe img').evaluateAll(es=>es.map(e=>({complete:e.complete,width:e.naturalWidth,height:e.naturalHeight,ref:!!(e.currentSrc||e.src)})));
 console.log({checks:result.checks,twoImagesDecoded:images.length===2&&images.every(i=>i.complete&&i.width===3&&i.height===2&&i.ref),timeoutRequests:state.fixtureRequests});
 console.log('DUMMY_BYTES='+result.b64);
} finally {await state.fixture.unroute('https://example.invalid/probe/**');await state.fixture.close();delete state.fixture;delete state.fixtureRequests;}
