// Read-only observation in an owned anonymous context; never enters credentials.
state.authContext=await context.browser().newContext();state.authPage=await state.authContext.newPage();
state.authNavigation=[];state.authFailures=[];
state.authPage.on('response',r=>{try{if(r.request().isNavigationRequest()&&r.request().frame()===state.authPage.mainFrame()){const u=new URL(r.url());state.authNavigation.push({origin:u.origin,path:u.pathname,status:r.status()});}}catch{}});
state.authPage.on('requestfailed',r=>{try{if(r.isNavigationRequest())state.authFailures.push((r.failure()?.errorText||'').match(/net::ERR_[A-Z_]+/)?.[0]||'NAVIGATION_FAILED');}catch{}});
try{
 try{await state.authPage.goto('https://blackline.my.site.com/BlackLineCommunity/s/article/PingAM---Configuring-Single-Sign-On-SSO-SAML-Claims-Mapping-for-BlackLine',{waitUntil:'domcontentloaded',timeout:30000});}catch(e){console.log({navigationError:e.name,networkCode:String(e.message).match(/net::ERR_[A-Z_]+/)?.[0]||null});}
 let last='',stable=0,result=null;const until=Date.now()+20000;
 while(Date.now()<until){
  try{result=await state.authPage.evaluate(()=>({origin:location.origin,path:location.pathname,ready:document.readyState,passwordCount:document.querySelectorAll('input[type=password]').length,inputs:[...document.querySelectorAll('input')].map(e=>({type:e.type,name:e.name,id:e.id,visible:e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'})),forms:[...document.forms].map(f=>({method:f.method,actionOrigin:new URL(f.action,location.href).origin,actionPath:new URL(f.action,location.href).pathname})),articleCount:document.querySelectorAll('.acknowltngKnowledgeArticleItem').length,loginButton:[...document.querySelectorAll('button,input[type=submit]')].some(e=>/sign\s*in|log\s*in/i.test(e.textContent||e.getAttribute('value')||''))}));
   const key=result.origin+result.path;if(key===last)stable++;else{last=key;stable=0;}if(stable>=6&&result.ready==='complete')break;
  }catch{stable=0;}
  await new Promise(r=>setTimeout(r,250));
 }
 console.log({snapshot:result,navigation:state.authNavigation,failures:state.authFailures});
}finally{await state.authContext.close();delete state.authContext;delete state.authPage;delete state.authNavigation;delete state.authFailures;}
