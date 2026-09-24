from __future__ import annotations

from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_pc_fix9_multistream_online.py <ppsspp_repo>')

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()
main_js = PROJECT / 'main.js'
renderer_js = PROJECT / 'renderer' / 'app.js'
renderer_html = PROJECT / 'renderer' / 'index.html'
build_info = REPO / 'PSP_LIVE_FLOGB_BUILD_INFO.txt'


def must(p: Path):
    if not p.exists():
        raise SystemExit(f'FIX9 missing file: {p}')
    return p


def replace_once(path: Path, old: str, new: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'FIX9 {label}: expected 1 occurrence, found {n}')
    path.write_text(src.replace(old, new, 1), encoding='utf-8')
    print(f'FIX9 {label}: PASS')


def regex_once(path: Path, pattern: str, replacement: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    out, n = re.subn(pattern, lambda _m: replacement, src, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f'FIX9 {label}: expected 1 regex match, found {n}')
    path.write_text(out, encoding='utf-8')
    print(f'FIX9 {label}: PASS')


print('=== PSP FloGB PC Native FIX9: MULTI-STREAMER ONLINE ===')

# ---------------------------------------------------------------------------
# Electron/runtime primitives.
# ---------------------------------------------------------------------------
replace_once(
    main_js,
    "const { app, BrowserWindow, ipcMain, dialog, shell, globalShortcut, screen } = require('electron');",
    "const { app, BrowserWindow, ipcMain, dialog, shell, globalShortcut, screen, safeStorage } = require('electron');",
    'Electron safeStorage import')

replace_once(
    main_js,
    "const WebSocket = require('ws');",
    "const WebSocket = require('ws');\nconst crypto = require('crypto');",
    'crypto import')

replace_once(
    main_js,
    "const RANKINGS_FILE = path.join(DATA, 'rankings.json');",
    "const RANKINGS_FILE = path.join(DATA, 'rankings.json');\nconst ONLINE_QUEUE_FILE = path.join(DATA, 'online-score-queue.json');\nconst ONLINE_SESSION_FILE = path.join(DATA, 'online-session.json');",
    'online data files')

replace_once(
    main_js,
    "let rankBoundaryTimer = null;",
    "let rankBoundaryTimer = null;\nlet onlineFlushTimer = null;\nlet onlineRankTimer = null;\nlet onlineFlushBusy = false;\nlet onlineSession = null;\nlet onlineStatus = {configured:false,authenticated:false,streamer:null,lastError:'',lastSyncAt:0,queueSize:0};\nlet onlineRankCache = {streamer:{week:[],month:[],valid:false,at:0},global:{week:[],month:[],valid:false,at:0}};",
    'online runtime state')

replace_once(
    main_js,
    "  if (rankBoundaryTimer) { clearTimeout(rankBoundaryTimer); rankBoundaryTimer = null; }\n  closeAuxWindows();",
    "  if (rankBoundaryTimer) { clearTimeout(rankBoundaryTimer); rankBoundaryTimer = null; }\n  if (onlineFlushTimer) { clearInterval(onlineFlushTimer); onlineFlushTimer = null; }\n  if (onlineRankTimer) { clearInterval(onlineRankTimer); onlineRankTimer = null; }\n  closeAuxWindows();",
    'online timer cleanup')

# ---------------------------------------------------------------------------
# Supabase Auth + RPC. No service-role/secret key is ever stored in the EXE.
# Refresh token is persisted with Electron safeStorage (Windows DPAPI).
# ---------------------------------------------------------------------------
online_runtime = r'''function onlineCfg(){
  const s=settings();
  return {
    enabled:s.onlineRankingEnabled===true,
    url:String(s.supabaseUrl||'').trim().replace(/\/+$/,''),
    key:String(s.supabasePublishableKey||'').trim(),
    email:String(s.supabaseEmail||'').trim(),
    nativeScope:['local','streamer','global'].includes(String(s.nativeRankingScope||''))?String(s.nativeRankingScope):'local'
  };
}
function onlineConfigured(){
  const c=onlineCfg();
  return !!(c.enabled && /^https:\/\/.+\.supabase\.co$/i.test(c.url) && c.key);
}
function onlineQueue(){
  const q=readJson(ONLINE_QUEUE_FILE,[]);
  return Array.isArray(q)?q:[];
}
function writeOnlineQueue(q){
  writeJson(ONLINE_QUEUE_FILE,Array.isArray(q)?q:[]);
  onlineStatus.queueSize=Array.isArray(q)?q.length:0;
}
function saveOnlineRefreshToken(token){
  try{
    if(!token){try{fs.unlinkSync(ONLINE_SESSION_FILE)}catch{};return false;}
    if(!safeStorage.isEncryptionAvailable()){
      sendLog('ONLINE: Windows secure storage unavailable; session will not persist after closing app','error');
      return false;
    }
    const enc=safeStorage.encryptString(String(token)).toString('base64');
    writeJson(ONLINE_SESSION_FILE,{v:1,refreshTokenEnc:enc,savedAt:Date.now()});
    return true;
  }catch(e){sendLog('ONLINE session save: '+e.message,'error');return false;}
}
function loadOnlineRefreshToken(){
  try{
    if(!safeStorage.isEncryptionAvailable())return '';
    const x=readJson(ONLINE_SESSION_FILE,{});
    if(!x.refreshTokenEnc)return '';
    return safeStorage.decryptString(Buffer.from(String(x.refreshTokenEnc),'base64'));
  }catch{return '';}
}
function setOnlineSession(data,persist=true){
  if(!data?.access_token){onlineSession=null;onlineStatus.authenticated=false;return null;}
  onlineSession={
    accessToken:String(data.access_token),
    refreshToken:String(data.refresh_token||onlineSession?.refreshToken||''),
    expiresAt:Date.now()+Math.max(30,Number(data.expires_in)||3600)*1000-30000,
    user:data.user||onlineSession?.user||null
  };
  onlineStatus.authenticated=true;
  onlineStatus.lastError='';
  if(persist && onlineSession.refreshToken)saveOnlineRefreshToken(onlineSession.refreshToken);
  return onlineSession;
}
async function supabaseAuth(grant,body){
  const c=onlineCfg();
  if(!c.url||!c.key)throw new Error('Chưa cấu hình Supabase URL / Publishable Key.');
  const r=await fetch(`${c.url}/auth/v1/token?grant_type=${encodeURIComponent(grant)}`,{
    method:'POST',headers:{'content-type':'application/json','apikey':c.key},body:JSON.stringify(body||{})
  });
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data?.msg||data?.error_description||data?.message||`Supabase Auth HTTP ${r.status}`);
  return data;
}
async function onlineLogin(email,password){
  const data=await supabaseAuth('password',{email:String(email||'').trim(),password:String(password||'')});
  setOnlineSession(data,true);
  const me=await supabaseRpc('flogb_my_streamer',{});
  const row=Array.isArray(me)?me[0]:me;
  if(!row?.streamer_id){await onlineLogout();throw new Error('Tài khoản Supabase này chưa được gắn với streamer trong bảng streamers.');}
  onlineStatus.streamer=row;
  await flushOnlineQueue();
  await refreshOnlineRankCache();
  return publicOnlineStatus();
}
async function onlineRefresh(){
  const refresh=onlineSession?.refreshToken||loadOnlineRefreshToken();
  if(!refresh)throw new Error('Chưa đăng nhập Supabase.');
  const data=await supabaseAuth('refresh_token',{refresh_token:refresh});
  setOnlineSession(data,true);
  return onlineSession.accessToken;
}
async function ensureOnlineAccess(){
  if(!onlineConfigured())throw new Error('Online ranking chưa được bật/cấu hình.');
  if(onlineSession?.accessToken && Date.now()<onlineSession.expiresAt)return onlineSession.accessToken;
  return onlineRefresh();
}
async function onlineLogout(){
  onlineSession=null;
  onlineStatus.authenticated=false;
  onlineStatus.streamer=null;
  onlineStatus.lastError='';
  onlineRankCache={streamer:{week:[],month:[],valid:false,at:0},global:{week:[],month:[],valid:false,at:0}};
  saveOnlineRefreshToken('');
  return publicOnlineStatus();
}
async function supabaseRpc(name,args={}){
  const c=onlineCfg();
  let token=await ensureOnlineAccess();
  const call=async(t)=>{
    const r=await fetch(`${c.url}/rest/v1/rpc/${encodeURIComponent(name)}`,{
      method:'POST',
      headers:{'content-type':'application/json','apikey':c.key,'Authorization':`Bearer ${t}`},
      body:JSON.stringify(args||{})
    });
    const data=await r.json().catch(()=>null);
    return {r,data};
  };
  let out=await call(token);
  if(out.r.status===401){token=await onlineRefresh();out=await call(token);}
  if(!out.r.ok)throw new Error(out.data?.message||out.data?.hint||out.data?.details||`Supabase RPC ${name} HTTP ${out.r.status}`);
  return out.data;
}
function publicOnlineStatus(){
  const c=onlineCfg();
  return {
    enabled:c.enabled,configured:onlineConfigured(),authenticated:!!onlineStatus.authenticated,
    streamer:onlineStatus.streamer,lastError:onlineStatus.lastError||'',lastSyncAt:onlineStatus.lastSyncAt||0,
    queueSize:onlineQueue().length,nativeScope:c.nativeScope,secureStorage:safeStorage.isEncryptionAvailable()
  };
}
async function restoreOnlineSession(){
  onlineStatus.configured=onlineConfigured();
  onlineStatus.queueSize=onlineQueue().length;
  if(!onlineConfigured())return publicOnlineStatus();
  const refresh=loadOnlineRefreshToken();
  if(!refresh)return publicOnlineStatus();
  try{
    onlineSession={refreshToken:refresh,accessToken:'',expiresAt:0,user:null};
    await onlineRefresh();
    const me=await supabaseRpc('flogb_my_streamer',{});
    const row=Array.isArray(me)?me[0]:me;
    if(row?.streamer_id)onlineStatus.streamer=row;
    sendLog(`ONLINE AUTH RESTORED | ${row?.display_name||row?.tiktok_username||row?.streamer_id||'streamer'}`);
  }catch(e){
    onlineStatus.lastError=e.message;
    onlineStatus.authenticated=false;
    sendLog('ONLINE restore: '+e.message,'error');
  }
  return publicOnlineStatus();
}
function enqueueOnlineScore(evt,points){
  if(!onlineCfg().enabled)return false;
  const u=evt?.user||{};
  const viewerId=String(u.id||u.secUid||u.uniqueId||'').trim();
  if(!viewerId)return false;
  const eventId=String(evt?.scoringId||evt?.eventId||`local-${viewerId}-${Date.now()}-${crypto.randomUUID()}`);
  const q=onlineQueue();
  if(q.some(x=>x.eventId===eventId))return true;
  q.push({
    eventId,viewerId,username:String(u.uniqueId||u.nickname||viewerId),avatarUrl:String(u.avatar||''),
    points:Math.max(0,Number(points)||0),occurredAt:new Date().toISOString()
  });
  writeOnlineQueue(q);
  return true;
}
async function flushOnlineQueue(){
  if(onlineFlushBusy||!onlineConfigured())return false;
  const q=onlineQueue();
  if(!q.length)return true;
  onlineFlushBusy=true;
  try{
    await ensureOnlineAccess();
    const batch=q.slice(0,20);
    const done=new Set();
    for(let i=0;i<batch.length;i+=5){
      const chunk=batch.slice(i,i+5);
      const results=await Promise.allSettled(chunk.map(async item=>{
        await supabaseRpc('flogb_apply_score',{
          p_event_id:item.eventId,p_tiktok_user_id:item.viewerId,p_username:item.username,
          p_avatar_url:item.avatarUrl,p_points:item.points,p_occurred_at:item.occurredAt
        });
        return item.eventId;
      }));
      for(const x of results)if(x.status==='fulfilled')done.add(x.value);
      const firstFail=results.find(x=>x.status==='rejected');
      if(firstFail){onlineStatus.lastError=String(firstFail.reason?.message||firstFail.reason||'sync failed');break;}
    }
    if(done.size){
      const next=q.filter(x=>!done.has(x.eventId));
      writeOnlineQueue(next);
      onlineStatus.lastSyncAt=Date.now();
      onlineStatus.lastError='';
      sendLog(`ONLINE SYNC ${done.size} event(s) | pending=${next.length}`);
    }
    return done.size>0;
  }catch(e){
    onlineStatus.lastError=e.message;
    return false;
  }finally{onlineFlushBusy=false;}
}
async function fetchOnlineLeaderboard(scope='streamer',period='week',limit=100){
  scope=scope==='global'?'global':'streamer';
  period=['week','month','total'].includes(period)?period:'week';
  const data=await supabaseRpc('flogb_leaderboard',{p_scope:scope,p_period:period,p_limit:Math.max(1,Math.min(100,Number(limit)||100))});
  return (Array.isArray(data)?data:[]).map(r=>({
    rank:Number(r.rank)||0,id:String(r.viewer_tiktok_id||''),username:String(r.username||r.viewer_tiktok_id||'viewer'),
    avatar:String(r.avatar_url||''),score:Number(r.score)||0
  }));
}
async function refreshOnlineRankCache(){
  if(!onlineConfigured()||!onlineStatus.authenticated)return false;
  try{
    for(const scope of ['streamer','global']){
      const [week,month]=await Promise.all([
        fetchOnlineLeaderboard(scope,'week',100),fetchOnlineLeaderboard(scope,'month',100)
      ]);
      onlineRankCache[scope]={week,month,valid:true,at:Date.now()};
    }
    onlineStatus.lastError='';
    return true;
  }catch(e){onlineStatus.lastError=e.message;return false;}
}
function selectedNativeOnlineRows(){
  const c=onlineCfg();
  if(c.nativeScope==='local'||!onlineStatus.authenticated)return null;
  const b=onlineRankCache[c.nativeScope];
  if(!b?.valid)return null;
  return {
    week:b.week.map(r=>({name:r.username,avatar:r.avatar,score:r.score})),
    month:b.month.map(r=>({name:r.username,avatar:r.avatar,score:r.score}))
  };
}
function startOnlineBackground(){
  if(onlineFlushTimer)clearInterval(onlineFlushTimer);
  if(onlineRankTimer)clearInterval(onlineRankTimer);
  onlineFlushTimer=setInterval(()=>flushOnlineQueue().catch(()=>{}),5000);
  onlineRankTimer=setInterval(()=>refreshOnlineRankCache().catch(()=>{}),10000);
}'''

replace_once(
    main_js,
    "function settings(){ return readJson(SETTINGS_FILE, {}); }\nfunction rules(){ return readJson(RULES_FILE, {version:2,mode:'game-actions-only',defaultGift:{enabled:false},rules:{}}); }",
    "function settings(){ return readJson(SETTINGS_FILE, {}); }\n" + online_runtime + "\nfunction rules(){ return readJson(RULES_FILE, {version:2,mode:'game-actions-only',defaultGift:{enabled:false},rules:{}}); }",
    'Supabase runtime engine')

# Queue every real gift after local persistence. Local game/ranking remains authoritative fallback.
replace_once(
    main_js,
    "      addRanking(e.user,support,'gift');\n      const reply=await postApi('/api/live/gift',{traceId,user:e.user||{},points:support});",
    "      addRanking(e.user,support,'gift');\n      enqueueOnlineScore(e,support);\n      flushOnlineQueue().catch(()=>{});\n      const reply=await postApi('/api/live/gift',{traceId,user:e.user||{},points:support});",
    'real gift online queue')

# Native WEEK/MONTH can switch Local / Streamer / Global at runtime without rebuilding.
replace_once(
    main_js,
    "    await pushRankIfChanged('WEEK',persistentRows('weekScore'));\n    await pushRankIfChanged('MONTH',persistentRows('monthScore'));",
    "    const onlineNative=selectedNativeOnlineRows();\n    await pushRankIfChanged('WEEK',onlineNative ? onlineNative.week : persistentRows('weekScore'));\n    await pushRankIfChanged('MONTH',onlineNative ? onlineNative.month : persistentRows('monthScore'));",
    'native online ranking scope')

# IPC endpoints.
replace_once(
    main_js,
    "ipcMain.handle('get-settings',()=>settings());",
    "ipcMain.handle('get-settings',()=>settings());\nipcMain.handle('online-status',()=>publicOnlineStatus());\nipcMain.handle('online-login',async(_,x={})=>onlineLogin(x.email,x.password));\nipcMain.handle('online-logout',()=>onlineLogout());\nipcMain.handle('online-test',async()=>{await ensureOnlineAccess();const me=await supabaseRpc('flogb_my_streamer',{});onlineStatus.streamer=Array.isArray(me)?me[0]:me;await flushOnlineQueue();await refreshOnlineRankCache();return publicOnlineStatus();});\nipcMain.handle('online-flush',async()=>{await flushOnlineQueue();return publicOnlineStatus();});\nipcMain.handle('get-online-rankings',async(_,x={})=>fetchOnlineLeaderboard(x.scope,x.period,x.limit));",
    'online IPC endpoints')

# Startup: local reset first, then recover online auth in background. No network blocks app startup.
replace_once(
    main_js,
    "  syncRankingPeriods('startup');\n  scheduleRankBoundaryCheck();\n  if(settings().showOverlay)createOverlay();",
    "  syncRankingPeriods('startup');\n  scheduleRankBoundaryCheck();\n  startOnlineBackground();\n  restoreOnlineSession().then(()=>{flushOnlineQueue().catch(()=>{});refreshOnlineRankCache().catch(()=>{});});\n  if(settings().showOverlay)createOverlay();",
    'online startup recovery')

# ---------------------------------------------------------------------------
# Renderer UI.
# ---------------------------------------------------------------------------
ranking_old = '''<section id="ranking" class="tab"><div class="card"><div class="toolbar"><div><h3>BXH Top 100</h3><p class="muted">BXH giữ riêng để Winner Top1 hoạt động y như nhánh APK. Gift Rule không còn mục “cộng điểm”.</p></div><select id="rankMode"><option value="all">Tổng</option><option value="week">Tuần</option><option value="month">Tháng</option></select></div><div id="rank100" class="rank100"></div></div></section>'''
ranking_new = '''<section id="ranking" class="tab"><div class="card"><div class="toolbar"><div><h3>BXH Top 100</h3><p class="muted">Local vẫn chạy khi mất mạng. Online có BXH riêng streamer và BXH toàn hệ thống.</p></div><div class="row"><select id="rankScope"><option value="local">Local</option><option value="streamer">Streamer</option><option value="global">Toàn hệ thống</option></select><select id="rankMode"><option value="all">Tổng</option><option value="week">Tuần</option><option value="month">Tháng</option></select></div></div><div id="onlineRankStatus" class="muted">ONLINE: chưa kiểm tra</div><div id="rank100" class="rank100"></div></div></section>'''
replace_once(renderer_html, ranking_old, ranking_new, 'ranking scope UI')

settings_old = '''<section id="settings" class="tab"><div class="grid2"><div class="card"><h3>Hiển thị</h3><label class="check"><input type="checkbox" id="showOverlay"> Tự mở overlay</label></div><div class="card"><h3>Nguyên tắc Rule</h3><p class="muted">Gift chưa cấu hình: chỉ ghi nhận/BXH, không bấm nút, không đổi HP, không ép winner.</p></div></div><button id="saveSettings" class="primary">Lưu cài đặt</button></section>'''
settings_new = '''<section id="settings" class="tab"><div class="grid2"><div class="card"><h3>Hiển thị</h3><label class="check"><input type="checkbox" id="showOverlay"> Tự mở overlay</label><label>BXH Native</label><select id="nativeRankingScope"><option value="local">Local</option><option value="streamer">Streamer online</option><option value="global">Toàn hệ thống</option></select></div><div class="card"><h3>Nguyên tắc Rule</h3><p class="muted">Gift chưa cấu hình: chỉ ghi nhận/BXH, không bấm nút, không đổi HP, không ép winner.</p></div></div><div class="card"><h3>Supabase / Multi-streamer</h3><label class="check"><input type="checkbox" id="onlineRankingEnabled"> Bật BXH online dùng chung</label><label>Project URL</label><input id="supabaseUrl" placeholder="https://xxxxx.supabase.co"><label>Publishable key</label><input id="supabasePublishableKey" placeholder="sb_publishable_..."><label>Email streamer</label><input id="supabaseEmail" type="email" placeholder="streamer@example.com"><label>Password (không lưu vào file settings)</label><input id="supabasePassword" type="password" placeholder="••••••••"><div class="row"><button id="btnOnlineLogin" class="primary">ĐĂNG NHẬP</button><button id="btnOnlineTest">TEST / SYNC</button><button id="btnOnlineLogout">ĐĂNG XUẤT</button></div><div id="onlineStatus" class="muted">Chưa kết nối.</div><p class="muted">EXE chỉ lưu Publishable Key. Refresh token được mã hóa bằng Windows secure storage; không chứa Supabase Secret/Service Role key.</p></div><button id="saveSettings" class="primary">Lưu cài đặt</button></section>'''
replace_once(renderer_html, settings_old, settings_new, 'Supabase settings UI')

# Init settings values.
# Do NOT match the entire init() line. Earlier gameplay patches intentionally
# inject installGameTestConsole() at the beginning and refreshTestGiftSelect()
# at the end, so an exact full-function anchor is brittle.
replace_once(
    renderer_js,
    "$('showOverlay').checked=s.showOverlay!==false;",
    "$('showOverlay').checked=s.showOverlay!==false;$('onlineRankingEnabled').checked=s.onlineRankingEnabled===true;$('supabaseUrl').value=s.supabaseUrl||'';$('supabasePublishableKey').value=s.supabasePublishableKey||'';$('supabaseEmail').value=s.supabaseEmail||'';$('nativeRankingScope').value=s.nativeRankingScope||'local';",
    'renderer online init settings')

# Unified gameplay patch 1.2.1 appends refreshTestGiftSelect() before init closes.
# Accept that generated form first, while retaining a controlled fallback for
# source trees where the tester injection is intentionally absent.
_renderer_src = must(renderer_js).read_text(encoding='utf-8')
_init_tail_full = "renderGiftTable();refreshTestGiftSelect();}"
_init_tail_base = "renderGiftTable();}"
if _init_tail_full in _renderer_src:
    replace_once(
        renderer_js,
        _init_tail_full,
        "renderGiftTable();refreshTestGiftSelect();await refreshOnlineStatus();}",
        'renderer online init tail')
elif _init_tail_base in _renderer_src:
    replace_once(
        renderer_js,
        _init_tail_base,
        "renderGiftTable();await refreshOnlineStatus();}",
        'renderer online init tail fallback')
else:
    raise SystemExit('FIX9 renderer online init tail: no supported init tail marker found')

replace_once(
    renderer_js,
    "async function saveSettings(){const cur=await ipcRenderer.invoke('get-settings');return ipcRenderer.invoke('save-settings',{...cur,liveUsername:$('liveUsername').value,isoPath:$('isoPath').value,ppssppDebugger:$('debuggerUrl').value,showOverlay:$('showOverlay').checked});}",
    "async function saveSettings(){const cur=await ipcRenderer.invoke('get-settings');return ipcRenderer.invoke('save-settings',{...cur,liveUsername:$('liveUsername').value,isoPath:$('isoPath').value,ppssppDebugger:$('debuggerUrl').value,showOverlay:$('showOverlay').checked,onlineRankingEnabled:$('onlineRankingEnabled').checked,supabaseUrl:$('supabaseUrl').value.trim(),supabasePublishableKey:$('supabasePublishableKey').value.trim(),supabaseEmail:$('supabaseEmail').value.trim(),nativeRankingScope:$('nativeRankingScope').value});}",
    'renderer save online settings')

# Insert online UI helpers before periodScore.
online_renderer = r'''async function refreshOnlineStatus(){
  try{
    const s=await ipcRenderer.invoke('online-status');
    const label=s.authenticated?`ONLINE OK | ${s.streamer?.display_name||s.streamer?.tiktok_username||'streamer'} | queue ${s.queueSize}`:(s.configured?'Đã cấu hình, chưa đăng nhập':'Chưa cấu hình');
    if($('onlineStatus'))$('onlineStatus').textContent=label+(s.lastError?` | ${s.lastError}`:'');
    if($('onlineRankStatus'))$('onlineRankStatus').textContent='ONLINE: '+label;
    return s;
  }catch(e){if($('onlineStatus'))$('onlineStatus').textContent='ONLINE ERROR: '+e.message;return null;}
}
$('btnOnlineLogin').onclick=async()=>{try{await saveSettings();await ipcRenderer.invoke('online-login',{email:$('supabaseEmail').value,password:$('supabasePassword').value});$('supabasePassword').value='';await refreshOnlineStatus();await loadRanking();}catch(e){alert('Supabase login: '+e.message);await refreshOnlineStatus();}};
$('btnOnlineLogout').onclick=async()=>{await ipcRenderer.invoke('online-logout');await refreshOnlineStatus();};
$('btnOnlineTest').onclick=async()=>{try{await saveSettings();await ipcRenderer.invoke('online-test');await refreshOnlineStatus();await loadRanking();}catch(e){alert('Supabase test: '+e.message);await refreshOnlineStatus();}};
setInterval(refreshOnlineStatus,5000);'''
replace_once(renderer_js, "function periodScore(u,mode){", online_renderer + "\nfunction periodScore(u,mode){", 'renderer online controls')

# Online/local ranking source.
regex_once(
    renderer_js,
    r"async function loadRanking\(\)\{.*?\}\n\$\('rankMode'\)\.onchange=loadRanking;",
    """async function loadRanking(){const mode=$('rankMode').value,scope=$('rankScope').value;let rows=[];if(scope==='local'){rankings=await ipcRenderer.invoke('get-rankings');rows=Object.values(rankings.users||{}).map(u=>({...u,username:u.uniqueId||u.nickname||u.id,score:periodScore(u,mode)})).sort((a,b)=>b.score-a.score).slice(0,100);}else{try{rows=await ipcRenderer.invoke('get-online-rankings',{scope,period:mode==='all'?'total':mode,limit:100});}catch(e){$('onlineRankStatus').textContent='ONLINE ERROR: '+e.message;rows=[];}}$('rank100').innerHTML=rows.map((u,i)=>`<div class=\"r\"><b>#${i+1}</b><span>${u.avatar?`<img src=\"${esc(u.avatar)}\">`:''} ${esc(u.username||u.uniqueId||u.nickname||u.id)}</span><b>${Number(u.score||0).toLocaleString()}</b><span>${scope==='local'?`${u.gifts||0} quà`:scope.toUpperCase()}</span></div>`).join('')||'<div class=\"muted\">Chưa có dữ liệu.</div>';await refreshOnlineStatus();}\n$('rankMode').onchange=loadRanking;$('rankScope').onchange=loadRanking;""",
    'renderer shared leaderboard')

# Saving Settings can alter native scope immediately; refresh online state afterward.
replace_once(
    renderer_js,
    "$('launchPP').onclick=async()=>{try{await saveSettings();await ipcRenderer.invoke('launch-ppsspp')}catch(e){alert('Không thể khởi chạy FloGB Engine: '+(e?.message||e))}};$('saveSettings').onclick=async()=>{await saveSettings();alert('Đã lưu cài đặt.')};",
    "$('launchPP').onclick=async()=>{try{await saveSettings();await ipcRenderer.invoke('launch-ppsspp')}catch(e){alert('Không thể khởi chạy FloGB Engine: '+(e?.message||e))}};$('saveSettings').onclick=async()=>{await saveSettings();await refreshOnlineStatus();alert('Đã lưu cài đặt.')};",
    'renderer settings status refresh')

# ---------------------------------------------------------------------------
# Static truth checks. Build stops before MSBuild if online wiring is incomplete.
# ---------------------------------------------------------------------------
m = main_js.read_text(encoding='utf-8')
r = renderer_js.read_text(encoding='utf-8')
h = renderer_html.read_text(encoding='utf-8')

main_need = [
    'safeStorage','ONLINE_QUEUE_FILE','online-score-queue.json','supabaseAuth','supabaseRpc',
    "flogb_apply_score", "flogb_leaderboard", 'enqueueOnlineScore(e,support)',
    'selectedNativeOnlineRows()', "nativeRankingScope", 'startOnlineBackground()',
    'restoreOnlineSession()', "p_event_id:item.eventId"
]
missing=[x for x in main_need if x not in m]
if missing: raise SystemExit(f'FIX9 main preflight missing: {missing}')

for secret_marker in ('SUPABASE_SERVICE_ROLE_KEY','SUPABASE_SECRET_KEYS','sb_secret_'):
    if secret_marker in m:
        raise SystemExit(f'FIX9 SECURITY STOP: secret-key marker leaked into desktop main.js: {secret_marker}')

renderer_need=['rankScope','btnOnlineLogin','refreshOnlineStatus','get-online-rankings','nativeRankingScope']
missing=[x for x in renderer_need if x not in (r+h)]
if missing: raise SystemExit(f'FIX9 renderer preflight missing: {missing}')

if 'type="password"' not in h or 'supabasePublishableKey' not in h:
    raise SystemExit('FIX9 settings UI missing password/publishable key fields')

if build_info.exists():
    with build_info.open('a',encoding='utf-8') as f:
        f.write(
            '\nPSP FloGB PC Native FIX9\n'
            'Multi-streamer Supabase ranking: runtime configurable\n'
            'Scopes: Local / Streamer / Global\n'
            'Offline queue + event dedupe RPC\n'
            'Publishable key only in desktop app; no service-role/secret key\n'
            'Refresh token protected with Electron safeStorage / Windows DPAPI\n'
            'Native WEEK/MONTH can switch ranking scope without rebuilding EXE\n'
        )

print('FIX9 SOURCE PREFLIGHT PASS')
print('Desktop secret/service-role key markers: 0')
print('Online configuration is runtime-only: NO rebuild needed for new Supabase project/streamer')
print('=== FIX9 PASS ===')
