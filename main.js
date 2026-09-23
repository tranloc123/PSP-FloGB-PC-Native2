const { app, BrowserWindow, ipcMain, dialog, shell, globalShortcut, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { Worker } = require('worker_threads');
const WebSocket = require('ws');

const ROOT = __dirname;
const BUNDLED_DATA = path.join(ROOT, 'data');
const DATA = path.join(app.getPath('userData'), 'data');
const SETTINGS_FILE = path.join(DATA, 'settings.json');
const RULES_FILE = path.join(DATA, 'gift-actions.json');
const LEARNED_FILE = path.join(DATA, 'learned-gifts.json');
const RANKINGS_FILE = path.join(DATA, 'rankings.json');
const CONTROLLER_PORT = 8797;

let win, liveWin, overlayWin, controllerWorker;
let overlayMenuOpen = false;
let statePollTimer = null;
let quitting = false;
let sessionTeams = new Map();
let lastControllerState = null;
let recentScoreIds = new Map();

function readJson(file, fallback) { try { return JSON.parse(fs.readFileSync(file,'utf8')); } catch { return fallback; } }
function writeJson(file, obj) { fs.mkdirSync(path.dirname(file), {recursive:true}); fs.writeFileSync(file, JSON.stringify(obj,null,2)); }
function settings(){ return readJson(SETTINGS_FILE, {}); }
function rules(){ return readJson(RULES_FILE, {version:2,mode:'game-actions-only',defaultGift:{enabled:false},rules:{}}); }

async function postApi(endpoint, body={}) {
  const r = await fetch(`http://127.0.0.1:${CONTROLLER_PORT}${endpoint}`, {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
async function getState(){ const r=await fetch(`http://127.0.0.1:${CONTROLLER_PORT}/api/state`); return r.json(); }

function startController() {
  if (controllerWorker) return;
  const cfg=settings();
  const workerPath = path.join(ROOT,'core','controller-service.js');
  try {
    controllerWorker = new Worker(workerPath, {
      stdout:true,
      stderr:true,
      env:{...process.env, SCBD_PPSSPP_DEBUGGER:cfg.ppssppDebugger || 'ws://127.0.0.1:9000/debugger'}
    });
    controllerWorker.stdout?.on('data', d => { const m=String(d).trim(); if(m) sendLog(m); });
    controllerWorker.stderr?.on('data', d => { const m=String(d).trim(); if(m) sendLog(m,'error'); });
    controllerWorker.on('error', e => { sendLog('Controller worker: '+e.message,'error'); controllerWorker=null; });
    controllerWorker.on('exit', code => { if(!quitting && code!==0) sendLog(`Controller dừng (${code})`,'error'); controllerWorker=null; });
  } catch(e) {
    controllerWorker=null;
    sendLog('Không thể khởi động Controller: '+e.message,'error');
  }
}
function restartController(){
  const w=controllerWorker; controllerWorker=null;
  try{w?.terminate();}catch{}
  setTimeout(startController,500);
}
function sendLog(message, kind='info'){ win?.webContents.send('app-log',{message,kind,at:Date.now()}); }

function stopController(){
  const w=controllerWorker; controllerWorker=null;
  try { w?.terminate(); } catch {}
}
function closeAuxWindows(){
  try { if (overlayWin && !overlayWin.isDestroyed()) overlayWin.destroy(); } catch {}
  overlayWin = null;
  try { if (liveWin && !liveWin.isDestroyed()) liveWin.destroy(); } catch {}
  liveWin = null;
}
function cleanupApp(){
  if (statePollTimer) { clearInterval(statePollTimer); statePollTimer = null; }
  closeAuxWindows();
  stopController();
}
function createMain() {
  win = new BrowserWindow({width:1500,height:900,minWidth:1180,minHeight:720,backgroundColor:'#0b0f16',webPreferences:{nodeIntegration:true,contextIsolation:false}});
  win.loadFile(path.join(ROOT,'renderer','index.html'));
  // Main Control Center is the owner of the whole FloGB session.
  // Closing it must also close the transparent overlay and TikTok window.
  win.on('closed', () => {
    win = null;
    if (!quitting) app.quit();
  });
}
function setOverlayMenu(open){
  overlayMenuOpen=!!open;
  if(!overlayWin || overlayWin.isDestroyed()) return overlayMenuOpen;
  try{
    overlayWin.setAlwaysOnTop(true,'screen-saver');
    overlayWin.setIgnoreMouseEvents(!overlayMenuOpen,{forward:true});
    overlayWin.setFocusable(overlayMenuOpen);
    overlayWin.webContents.send('overlay-menu',overlayMenuOpen);
    if(overlayMenuOpen){ overlayWin.show(); overlayWin.focus(); }
  }catch{}
  return overlayMenuOpen;
}
function createOverlay(){
  if (overlayWin && !overlayWin.isDestroyed()) return overlayWin;
  const bounds=screen.getPrimaryDisplay().bounds;
  overlayWin=new BrowserWindow({x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height,transparent:true,frame:false,alwaysOnTop:true,skipTaskbar:true,focusable:false,resizable:false,hasShadow:false,webPreferences:{nodeIntegration:true,contextIsolation:false}});
  overlayWin.setAlwaysOnTop(true,'screen-saver');
  overlayWin.setIgnoreMouseEvents(true,{forward:true});
  overlayWin.loadFile(path.join(ROOT,'overlay','overlay.html'));
  overlayWin.webContents.on('did-finish-load',()=>overlayWin?.webContents.send('overlay-menu',overlayMenuOpen));
  overlayWin.on('closed',()=>{ overlayWin=null; overlayMenuOpen=false; });
  return overlayWin;
}
function normalizeUsername(v){ return String(v||'').trim().replace(/^@/,'').split(/[/?#]/)[0]; }
function openLive(username){
  username=normalizeUsername(username); if(!username) throw new Error('Thiếu TikTok @username');
  const cfg=settings(); cfg.liveUsername=username; writeJson(SETTINGS_FILE,cfg);
  if(liveWin&&!liveWin.isDestroyed()) liveWin.close();
  liveWin=new BrowserWindow({width:520,height:820,title:`TikTok LIVE @${username}`,webPreferences:{preload:path.join(ROOT,'live-preload.js'),nodeIntegration:false,contextIsolation:false,sandbox:false}});
  liveWin.webContents.on('dom-ready',()=>{
    try{ const code=fs.readFileSync(path.join(ROOT,'probe','probe.js'),'utf8'); liveWin.webContents.executeJavaScript(code).catch(e=>sendLog('Probe inject: '+e.message,'error')); }catch(e){sendLog(e.message,'error');}
  });
  liveWin.on('closed',()=>{ liveWin=null; });
  liveWin.loadURL(`https://www.tiktok.com/@${encodeURIComponent(username)}/live`);
}

function stableName(user={}){ return String(user.uniqueId||user.nickname||user.id||'viewer'); }
function cleanupRecent(){ const now=Date.now(); for(const [k,t] of recentScoreIds) if(now-t>120000) recentScoreIds.delete(k); }
function markScore(id){ cleanupRecent(); if(!id) return false; if(recentScoreIds.has(id)) return true; recentScoreIds.set(id,Date.now()); return false; }
function dayKey(ts=Date.now()){ return new Date(ts).toISOString().slice(0,10); }
function addRanking(user, points, kind){
  if(!user?.id) return; const db=readJson(RANKINGS_FILE,{users:{}}); const id=String(user.id);
  const u=db.users[id]||{id,uniqueId:'',nickname:'',avatar:'',total:0,gifts:0,likes:0,daily:{}};
  u.uniqueId=user.uniqueId||u.uniqueId; u.nickname=user.nickname||u.nickname; u.avatar=user.avatar||u.avatar;
  const p=Math.max(0,Number(points)||0); u.total=(u.total||0)+p; if(kind==='gift')u.gifts=(u.gifts||0)+1; if(kind==='like')u.likes=(u.likes||0)+p;
  const dk=dayKey(); u.daily=u.daily||{}; u.daily[dk]=(u.daily[dk]||0)+p; db.users[id]=u; writeJson(RANKINGS_FILE,db);
}
function calcSupportValue(evt){
  const units=Math.max(1,Number(evt?.units)||1);
  const diamonds=Math.max(0,Number(evt?.diamonds)||0);
  return Math.max(1, diamonds || units);
}
function findGiftRule(evt){
  const cfg=rules(); const p=evt?.payload||{}; const id=String(p.giftId||''); const byName=String(p.giftName||'').trim().toLowerCase();
  if(id && cfg.rules?.[id]) return cfg.rules[id];
  return Object.values(cfg.rules||{}).find(r=>String(r.name||'').trim().toLowerCase()===byName) || null;
}
function learnGift(evt){
  const p=evt.payload||{}; if(!p.giftId) return; const db=readJson(LEARNED_FILE,{}); const id=String(p.giftId); const old=db[id]||{};
  db[id]={giftId:id,name:p.giftName||old.name||'',diamondCount:Number(p.diamondCount||old.diamondCount||0),imageUrl:p.imageUrl||p.iconUrl||old.imageUrl||'',seenCount:Number(old.seenCount||0)+1,lastSeen:Date.now(),lastSender:stableName(evt.user)};
  writeJson(LEARNED_FILE,db);
}

function floatToU32(v){ const b=Buffer.allocUnsafe(4); b.writeFloatLE(Number(v)||0,0); return b.readUInt32LE(0); }
function u32ToFloat(v){ const b=Buffer.allocUnsafe(4); b.writeUInt32LE(v>>>0,0); return b.readFloatLE(0); }
async function ppssppCommand(fn){
  const url=settings().ppssppDebugger||'ws://127.0.0.1:9000/debugger';
  return new Promise((resolve,reject)=>{ const ws=new WebSocket(url,'debugger.ppsspp.org'); let ticket=1; const pending=new Map(); const timer=setTimeout(()=>{try{ws.close()}catch{};reject(new Error('FloGB Engine debugger timeout'));},5000);
    ws.on('message',raw=>{let m;try{m=JSON.parse(String(raw))}catch{return};const p=pending.get(m.ticket);if(p&&('uintValue'in m||'value'in m)){pending.delete(m.ticket);p((m.uintValue??m.value)>>>0);}});
    ws.on('open',async()=>{ const api={readU32:a=>new Promise((r,j)=>{const t=ticket++;pending.set(t,r);ws.send(JSON.stringify({event:'memory.read_u32',ticket:t,address:a>>>0}));setTimeout(()=>{if(pending.delete(t))j(new Error('read timeout'))},1000)}),writeU32:(a,v)=>ws.send(JSON.stringify({event:'memory.write_u32',ticket:ticket++,address:a>>>0,value:v>>>0})),tap:(button,duration=2)=>ws.send(JSON.stringify({event:'input.buttons.press',ticket:ticket++,button,duration}))};
      try{const out=await fn(api);clearTimeout(timer);ws.close();resolve(out);}catch(e){clearTimeout(timer);ws.close();reject(e);}
    }); ws.on('error',e=>{clearTimeout(timer);reject(e)});
  });
}
const HP={P1:0x08BE364C,P2:0x08BFA30C};
async function applySingleAction(action, memberTeam, evt){
  const type=String(action?.type||action?.action||'').trim(); if(!type||type==='none') return;
  if(type==='delay'){ await new Promise(r=>setTimeout(r,Math.min(5000,Math.max(0,Number(action.ms||action.amount)||0)))); return; }
  if(type==='winner_p1'||type==='winner_p2'){ await postApi('/api/manual/ko',{winnerTeam:type.endsWith('p1')?'P1':'P2'}); return; }
  if(type==='input'){
    const button=String(action.button||'cross'); const count=Math.min(20,Math.max(1,Number(action.count||action.amount)||1)); const gap=Math.min(1500,Math.max(40,Number(action.gapMs)||100));
    await ppssppCommand(async api=>{for(let i=0;i<count;i++){api.tap(button,2);await new Promise(r=>setTimeout(r,gap));}}); return;
  }
  if(type==='heal_team'||type==='damage_enemy'||type==='set_hp'){
    if(!memberTeam) return; let target=String(action.target||memberTeam).toUpperCase();
    if(type==='damage_enemy') target=memberTeam==='P1'?'P2':'P1';
    if(target!=='P1'&&target!=='P2') target=memberTeam;
    const mult=Math.max(1,Number(evt.units)||1); const amount=Math.abs(Number(action.amount)||0)*mult; const cap=Math.max(1,Number(action.hpCap)||250);
    await ppssppCommand(async api=>{ const raw=await api.readU32(HP[target]); let hp=u32ToFloat(raw);
      if(type==='heal_team') hp=Math.min(cap,hp+amount); else if(type==='damage_enemy') hp=Math.max(0,hp-amount); else hp=Math.max(0,Math.min(cap,Number(action.value??action.amount)||0));
      api.writeU32(HP[target],floatToU32(hp)); }); return;
  }
  if(type==='video'||type==='effect'){ win?.webContents.send('game-action',{type,action,evt}); return; }
}
async function applyRuleActions(rule, memberTeam, evt){
  if(!rule || rule.enabled===false) return;
  const actions=Array.isArray(rule.actions)&&rule.actions.length ? rule.actions : (rule.action&&rule.action!=='none' ? [{type:rule.action,amount:rule.amount,button:rule.button,hpCap:rule.hpCap}] : []);
  for(const action of actions) await applySingleAction(action,memberTeam,evt);
}

async function routeReport({kind,payload}){
  if(kind==='NORMALIZED_EVENT'){
    const e=typeof payload==='string'?JSON.parse(payload):payload; if(!e||!e.type)return;
    if(e.type==='comment'){
      const text=String(e.payload?.text||'').trim(), name=stableName(e.user);
      if(text==='1'||text==='2'){ const team=text==='1'?'P1':'P2'; sessionTeams.set(String(e.user?.id||name),team); await postApi('/api/test/team',{username:name,team}); }
      else if(/^\/pick\s+/i.test(text)) await postApi('/api/test/comment',{username:name,comment:text});
    }
    win?.webContents.send('live-event',e); return;
  }
  if(kind==='SCORING_EVENT'){
    const e=typeof payload==='string'?JSON.parse(payload):payload; if(!e||markScore(e.scoringId))return;
    const name=stableName(e.user), team=sessionTeams.get(String(e.user?.id||name))||null;
    if(e.type==='gift'){
      learnGift(e);
      // Ranking support is fixed from the real gift event. It is NOT a configurable game rule.
      // This preserves Winner Top1/BXH behavior from the APK branch while Rule only controls gameplay.
      const support=calcSupportValue(e); addRanking(e.user,support,'gift'); await postApi('/api/test/gift',{username:name,points:support});
      const rule=findGiftRule(e); await applyRuleActions(rule,team,e);
    }
    win?.webContents.send('scoring-event',e);
  }
}

ipcMain.on('scbd-live-report',(_,msg)=>routeReport(msg).catch(e=>sendLog('Route event: '+e.message,'error')));
ipcMain.handle('get-settings',()=>settings());
ipcMain.handle('save-settings',(_,v)=>{writeJson(SETTINGS_FILE,{...settings(),...v});restartController();return settings();});
ipcMain.handle('choose-file',async(_,filters)=>{const r=await dialog.showOpenDialog({properties:['openFile'],filters:filters||[]});return r.canceled?'':r.filePaths[0];});
ipcMain.handle('open-live',(_,u)=>{openLive(u);return true;});
ipcMain.handle('toggle-overlay',()=>{if(overlayWin&&!overlayWin.isDestroyed()){overlayWin.close();overlayWin=null;return false;}createOverlay();return true;});
ipcMain.handle('toggle-overlay-menu',()=>{if(!overlayWin||overlayWin.isDestroyed())createOverlay();return setOverlayMenu(!overlayMenuOpen);});
ipcMain.handle('set-overlay-menu',(_,open)=>setOverlayMenu(!!open));
ipcMain.handle('ppsspp-tap',(_,button)=>ppssppCommand(api=>api.tap(String(button||'cross'),2)));
ipcMain.handle('launch-ppsspp',()=>{
  const c=settings();
  const bundled=path.join(ROOT,'engine','PPSSPPWindows64.exe');
  const exe=bundled;
  if(!fs.existsSync(exe)) throw new Error('Thiếu PSP FloGB Native Engine. Bản 1.2.0 không còn chạy PPSSPP gốc/fallback. Hãy dùng bản được build bởi workflow Native Unified.');
  let debuggerPort=9000;
  try{ debuggerPort=Number(new URL(c.ppssppDebugger||'ws://127.0.0.1:9000/debugger').port)||9000; }catch{}
  const args=[`--debugger=${debuggerPort}`];
  if(c.isoPath){ if(!fs.existsSync(c.isoPath)) throw new Error('Không tìm thấy game: '+c.isoPath); args.push(c.isoPath); }
  sendLog(`Khởi chạy PSP FloGB Native Engine + Remote Debugger port ${debuggerPort}`);
  return new Promise((resolve,reject)=>{
    const child=spawn(exe,args,{detached:true,stdio:'ignore'});
    let settled=false;
    child.once('error',e=>{if(!settled){settled=true;reject(new Error('Không thể chạy PPSSPP: '+e.message));}});
    child.once('spawn',()=>{if(!settled){settled=true;child.unref();resolve(true);}});
  });
});
ipcMain.handle('get-rules',()=>rules());
ipcMain.handle('save-rules',(_,v)=>{writeJson(RULES_FILE,v);return v;});
ipcMain.handle('get-learned-gifts',()=>readJson(LEARNED_FILE,{}));
ipcMain.handle('get-rankings',()=>readJson(RANKINGS_FILE,{users:{}}));
ipcMain.handle('reset-session',async()=>{sessionTeams.clear();await postApi('/api/session/reset');return true;});
ipcMain.handle('controller-state',()=>lastControllerState);
ipcMain.handle('manual-winner',(_,team)=>postApi('/api/manual/ko',{winnerTeam:team}));
ipcMain.handle('test-gift',async(_,x)=>{await postApi('/api/test/team',{username:x.username||'TEST',team:x.team||'P1'});return postApi('/api/test/gift',{username:x.username||'TEST',points:Number(x.points)||0});});
ipcMain.handle('get-engine-info',()=>{const bundled=path.join(ROOT,'engine','PPSSPPWindows64.exe');return {bundledPath:bundled,bundledExists:fs.existsSync(bundled),mode:fs.existsSync(bundled)?'NATIVE_FLOGB':'NATIVE_ENGINE_MISSING'};});
ipcMain.handle('open-external',(_,url)=>shell.openExternal(url));

app.whenReady().then(()=>{
  fs.mkdirSync(DATA,{recursive:true});
  // Seed bundled defaults once, then keep mutable data outside the portable Temp folder.
  for(const name of ['settings.json','gift-actions.json','learned-gifts.json','rankings.json']){
    const src=path.join(BUNDLED_DATA,name), dst=path.join(DATA,name);
    try{ if(!fs.existsSync(dst) && fs.existsSync(src)) fs.copyFileSync(src,dst); }catch{}
  }
  startController();
  createMain();
  if(settings().showOverlay)createOverlay();
  try{
    globalShortcut.register('F10',()=>{
      if(!overlayWin||overlayWin.isDestroyed())createOverlay();
      setOverlayMenu(!overlayMenuOpen);
    });
  }catch(e){ sendLog('Không đăng ký được F10: '+e.message,'error'); }
  statePollTimer=setInterval(async()=>{
    try{
      lastControllerState=await getState();
      if(win && !win.isDestroyed()) win.webContents.send('controller-state',lastControllerState);
      if(overlayWin && !overlayWin.isDestroyed()) overlayWin.webContents.send('controller-state',lastControllerState);
    }catch{}
  },500);
});
app.on('before-quit',()=>{
  quitting=true;
  try{globalShortcut.unregisterAll();}catch{}
  cleanupApp();
});
app.on('window-all-closed',()=>{
  cleanupApp();
  app.quit();
});
