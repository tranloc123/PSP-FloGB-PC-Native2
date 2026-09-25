from __future__ import annotations
from pathlib import Path
import json, re, sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_pc_fix10_control_center.py <ppsspp_repo>')

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()
main_js = PROJECT / 'main.js'
renderer_js = PROJECT / 'renderer' / 'app.js'
renderer_html = PROJECT / 'renderer' / 'index.html'
data_dir = PROJECT / 'data'
build_info = REPO / 'PSP_LIVE_FLOGB_BUILD_INFO.txt'

def must(p: Path):
    if not p.exists(): raise SystemExit(f'FIX10 missing file: {p}')
    return p

def replace_once(path: Path, old: str, new: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    n = src.count(old)
    if n != 1: raise SystemExit(f'FIX10 {label}: expected 1 occurrence, found {n}')
    path.write_text(src.replace(old, new, 1), encoding='utf-8')
    print(f'FIX10 {label}: PASS')

def regex_once(path: Path, pattern: str, replacement: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    out, n = re.subn(pattern, lambda _m: replacement, src, count=1, flags=re.S)
    if n != 1: raise SystemExit(f'FIX10 {label}: expected 1 regex match, found {n}')
    path.write_text(out, encoding='utf-8')
    print(f'FIX10 {label}: PASS')

print('=== PSP FloGB FIX10: CONTROL CENTER + GLOBAL NATIVE RANK ===')

# 1) Starter catalog + manual gifts. Synthetic name:* rules work before real giftId arrives.
starter = [
    {'giftId':'name:tiktok','name':'TikTok','diamondCount':1},
    {'giftId':'name:rose','name':'Rose','diamondCount':1},
    {'giftId':'name:rosa','name':'Rosa','diamondCount':10},
    {'giftId':'name:gg','name':'GG','diamondCount':1},
    {'giftId':'name:heart-me','name':'Heart Me','diamondCount':1},
    {'giftId':'name:finger-heart','name':'Finger Heart','diamondCount':5},
    {'giftId':'name:lucky-pig','name':'Lucky Pig','diamondCount':10},
    {'giftId':'name:little-kiss','name':'Little Kiss','diamondCount':15},
    {'giftId':'name:perfume','name':'Perfume','diamondCount':20},
    {'giftId':'name:hand-hearts','name':'Hand Hearts','diamondCount':100},
    {'giftId':'name:money-gun','name':'Money Gun','diamondCount':500},
    {'giftId':'name:lion','name':'Lion','diamondCount':29999},
]
data_dir.mkdir(parents=True, exist_ok=True)
(data_dir/'gift-catalog.json').write_text(json.dumps(starter, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(f'FIX10 starter gift catalog: PASS ({len(starter)} gifts)')

replace_once(main_js,
    "const LEARNED_FILE = path.join(DATA, 'learned-gifts.json');",
    "const LEARNED_FILE = path.join(DATA, 'learned-gifts.json');\nconst GIFT_CATALOG_FILE = path.join(BUNDLED_DATA, 'gift-catalog.json');",
    'gift catalog file')

replace_once(main_js,
    "ipcMain.handle('get-learned-gifts',()=>readJson(LEARNED_FILE,{}));",
    """ipcMain.handle('get-learned-gifts',()=>readJson(LEARNED_FILE,{}));
ipcMain.handle('get-gift-catalog',()=>readJson(GIFT_CATALOG_FILE,[]));
ipcMain.handle('add-manual-gift',(_,x={})=>{
  const name=String(x.name||'').trim();
  if(!name)throw new Error('Thiếu tên quà.');
  const slug=name.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');\n  const key='name:'+(slug||crypto.createHash('sha1').update(name).digest('hex').slice(0,12));
  const db=readJson(LEARNED_FILE,{});
  db[key]={giftId:key,name,diamondCount:Math.max(0,Number(x.diamondCount)||0),imageUrl:'',seenCount:0,lastSeen:0,lastSender:'CATALOG'};
  writeJson(LEARNED_FILE,db);
  return db[key];
});""",
    'gift catalog IPC')

# 2) Rule editor must not redraw itself on every live gift.
replace_once(renderer_js,
    "const { ipcRenderer } = require('electron');",
    "const { ipcRenderer } = require('electron');\nlet giftCatalog=[];",
    'renderer gift catalog state')

regex_once(renderer_js,
    r"ipcRenderer\.on\('scoring-event',\(_,e\)=>\{\$\('lastScoring'\)\.textContent=JSON\.stringify\(e,null,2\);loadGifts\(\)\}\);",
    "ipcRenderer.on('scoring-event',(_,e)=>{$('lastScoring').textContent=JSON.stringify(e,null,2);});",
    'stop live Rule rerender')

src = renderer_js.read_text(encoding='utf-8')
m = re.search(r"(async function init\(\)\{.*?learned=await ipcRenderer\.invoke\('get-learned-gifts'\);)", src, flags=re.S)
if not m: raise SystemExit('FIX10 init catalog anchor missing')
src = src[:m.end()] + "giftCatalog=await ipcRenderer.invoke('get-gift-catalog');" + src[m.end():]
renderer_js.write_text(src, encoding='utf-8')
print('FIX10 init gift catalog: PASS')

gift_rows = r'''function giftRows(){
  const q=norm($('giftSearch')?.value),f=$('giftFilter')?.value||'all';
  const cm=Object.fromEntries((giftCatalog||[]).map(g=>[String(g.giftId),g]));
  const ids=new Set([...Object.keys(cm),...Object.keys(learned||{}),...Object.keys(giftRules.rules||{})]);
  const rows=[];
  for(const id of ids){
    const c=cm[id]||{},l=learned[id]||{},r=giftRules.rules?.[id]||{};
    const g={giftId:id,name:l.name||c.name||r.name||id,diamondCount:Number(l.diamondCount??c.diamondCount??0)||0,seenCount:Number(l.seenCount||0),lastSender:l.lastSender||'',configured:!!giftRules.rules?.[id]};
    if(q&&!norm(g.name+' '+g.giftId).includes(q))continue;
    if(f==='configured'&&!g.configured)continue;
    if(f==='unconfigured'&&g.configured)continue;
    rows.push(g);
  }
  return rows.sort((a,b)=>(Number(b.configured)-Number(a.configured))||(b.seenCount-a.seenCount)||a.name.localeCompare(b.name));
}'''
regex_once(renderer_js, r"function giftRows\(\)\{.*?\}\nfunction renderGiftTable\(\)", gift_rows+"\nfunction renderGiftTable()", 'catalog gift rows')

psp_helper = r'''function pspButtonOptions(selected){
  const buttons=[['cross','X / CROSS'],['circle','O / CIRCLE'],['square','SQUARE'],['triangle','TRIANGLE'],['up','D-PAD UP'],['down','D-PAD DOWN'],['left','D-PAD LEFT'],['right','D-PAD RIGHT'],['ltrigger','L'],['rtrigger','R'],['start','START'],['select','SELECT']];
  const cur=String(selected||'cross').toLowerCase();
  return buttons.map(([v,label])=>`<option value="${v}" ${cur===v?'selected':''}>${label}</option>`).join('');
}
'''
replace_once(renderer_js, "function renderGiftTable(){", psp_helper+"function renderGiftTable(){", 'PSP button helper')
replace_once(renderer_js,
    '''<input class="cellInput button" value="${esc(a.button||'cross')}" title="cross/start/up/down/left/right">''',
    '''<select class="cellSelect button">${pspButtonOptions(a.button||'cross')}</select>''',
    'PSP full button dropdown')
replace_once(renderer_js,
    "l=learned[id]||{};giftRules.rules=giftRules.rules||{};giftRules.rules[id]={name:l.name||id,enabled:true,actions:[{type:'input',button:'cross',amount:1}]};",
    "l=learned[id]||(giftCatalog||[]).find(x=>String(x.giftId)===String(id))||{};giftRules.rules=giftRules.rules||{};giftRules.rules[id]={name:l.name||id,enabled:true,actions:[{type:'input',button:'cross',amount:1}]};",
    'catalog Add Rule name')
replace_once(renderer_js,
    "async function loadGifts(){giftRules=await ipcRenderer.invoke('get-rules');learned=await ipcRenderer.invoke('get-learned-gifts');renderGiftTable();}",
    "async function loadGifts(){giftRules=await ipcRenderer.invoke('get-rules');learned=await ipcRenderer.invoke('get-learned-gifts');giftCatalog=await ipcRenderer.invoke('get-gift-catalog');renderGiftTable();}",
    'manual refresh data')

replace_once(renderer_html,
    '<button id="btnSaveRules" class="primary">Lưu Rule</button>',
    '<div class="row"><button id="btnRefreshGifts">Làm mới quà</button><button id="btnSaveRules" class="primary">Lưu Rule</button></div>',
    'refresh gift button')
replace_once(renderer_html,
    '<div class="giftTableWrap"><table>',
    '<div class="row"><input id="manualGiftName" placeholder="Tên quà khác chưa có"><input id="manualGiftDiamond" type="number" min="0" placeholder="Xu (tùy chọn)"><button id="btnAddManualGift">+ Thêm quà thủ công</button></div><div class="giftTableWrap"><table>',
    'manual gift controls')

handlers = r'''$('btnRefreshGifts').onclick=()=>loadGifts();
$('btnAddManualGift').onclick=async()=>{
  const name=$('manualGiftName').value.trim();
  if(!name)return alert('Nhập tên quà trước.');
  try{await ipcRenderer.invoke('add-manual-gift',{name,diamondCount:Number($('manualGiftDiamond').value)||0});$('manualGiftName').value='';$('manualGiftDiamond').value='';await loadGifts();}
  catch(e){alert('Thêm quà: '+e.message);}
};
'''
replace_once(renderer_js, "$('giftSearch').oninput=renderGiftTable;", handlers+"$('giftSearch').oninput=renderGiftTable;", 'gift manual handlers')

# 3) Disable external Electron overlay; hide app leaderboard surfaces.
regex_once(main_js, r"function createOverlay\(\)\{.*?\n\}\nfunction normalizeUsername", "function createOverlay(){ return null; }\nfunction normalizeUsername", 'disable Electron overlay')
ms = main_js.read_text(encoding='utf-8')
if "  if(settings().showOverlay)createOverlay();" in ms:
    ms = ms.replace("  if(settings().showOverlay)createOverlay();", "  // FIX10: external Electron overlay disabled; rankings are native in-game.", 1)
main_js.write_text(ms, encoding='utf-8')
print('FIX10 disable auto overlay: PASS')

replace_once(renderer_html, '<button id="btnOverlay">Overlay</button>', '<button id="btnOverlay" style="display:none" aria-hidden="true">Overlay</button>', 'hide Overlay button')
replace_once(renderer_html, '<button class="nav" data-tab="ranking">BXH</button>', '<button class="nav" style="display:none" aria-hidden="true" data-tab="ranking">BXH</button>', 'hide BXH nav')
replace_once(renderer_html, '<div class="grid2"><div class="card"><h3>P1 TOP 10</h3>', '<div class="grid2" style="display:none" aria-hidden="true"><div class="card"><h3>P1 TOP 10</h3>', 'hide app match top')
replace_once(renderer_html, '<section id="ranking" class="tab">', '<section id="ranking" class="tab" style="display:none" aria-hidden="true">', 'hide app ranking page')

h = renderer_html.read_text(encoding='utf-8')
h = h.replace('<label class="check"><input type="checkbox" id="showOverlay"> Tự mở overlay</label>', '<label class="check" style="display:none"><input type="checkbox" id="showOverlay"> Tự mở overlay</label>', 1)
h = h.replace('<label>BXH Native</label><select id="nativeRankingScope"><option value="local">Local</option><option value="streamer">Streamer online</option><option value="global">Toàn hệ thống</option></select>', '<label style="display:none">BXH Native</label><select id="nativeRankingScope" style="display:none"><option value="global" selected>Toàn hệ thống</option></select>', 1)
h = h.replace('<select id="rankScope"><option value="local">Local</option><option value="streamer">Streamer</option><option value="global">Toàn hệ thống</option></select>', '<select id="rankScope" style="display:none"><option value="global" selected>Toàn hệ thống</option></select>', 1)
renderer_html.write_text(h, encoding='utf-8')
print('FIX10 hidden compatibility controls: PASS')
replace_once(renderer_js, "function renderRank(el,rows=[]){$(el).innerHTML=", "function renderRank(el,rows=[]){if(!$(el))return;$(el).innerHTML=", 'safe rank render')

# 4) Persistent online ranking is GLOBAL ONLY across all streamer accounts.
replace_once(main_js,
    "nativeScope:['local','streamer','global'].includes(String(s.nativeRankingScope||''))?String(s.nativeRankingScope):'local'",
    "nativeScope:'global'",
    'force global native scope')
replace_once(main_js, "scope=scope==='global'?'global':'streamer';", "scope='global';", 'force global RPC scope')
replace_once(main_js, "for(const scope of ['streamer','global']){", "for(const scope of ['global']){", 'global cache only')

global_rows = r'''function selectedNativeOnlineRows(){
  const b=onlineRankCache.global;
  if(!b?.valid)return {week:[],month:[]};
  return {week:b.week.map(r=>({name:r.username,avatar:r.avatar,score:r.score})),month:b.month.map(r=>({name:r.username,avatar:r.avatar,score:r.score}))};
}'''
regex_once(main_js, r"function selectedNativeOnlineRows\(\)\{.*?\n\}", global_rows, 'global native rows')
replace_once(renderer_js, "$('nativeRankingScope').value=s.nativeRankingScope||'local';", "$('nativeRankingScope').value='global';", 'renderer global scope')

# 5) Keep the LIVE collector stable while editing Rules.
open_live = r'''function openLive(username){
  username=normalizeUsername(username); if(!username) throw new Error('Thiếu TikTok @username');
  const cfg=settings(); cfg.liveUsername=username; writeJson(SETTINGS_FILE,cfg);
  if(liveWin&&!liveWin.isDestroyed()){
    if(String(liveWin.__flogbUsername||'').toLowerCase()===username.toLowerCase()){try{liveWin.show();liveWin.focus();}catch{};return;}
    try{liveWin.destroy();}catch{}; liveWin=null;
  }
  liveWin=new BrowserWindow({width:520,height:820,title:`TikTok LIVE @${username}`,webPreferences:{preload:path.join(ROOT,'live-preload.js'),nodeIntegration:false,contextIsolation:false,sandbox:false,backgroundThrottling:false}});
  liveWin.__flogbUsername=username;
  liveWin.webContents.on('dom-ready',()=>{try{const code=fs.readFileSync(path.join(ROOT,'probe','probe.js'),'utf8');liveWin.webContents.executeJavaScript(code).catch(e=>sendLog('Probe inject: '+e.message,'error'));}catch(e){sendLog(e.message,'error');}});
  liveWin.on('closed',()=>{liveWin=null;});
  liveWin.loadURL(`https://www.tiktok.com/@${encodeURIComponent(username)}/live`);
}'''
regex_once(main_js, r"function openLive\(username\)\{.*?\n\}\n\nfunction stableName", open_live+"\n\nfunction stableName", 'stable LIVE collector')

# Preflight
m = main_js.read_text(encoding='utf-8'); r = renderer_js.read_text(encoding='utf-8'); h = renderer_html.read_text(encoding='utf-8')
for marker in ('GIFT_CATALOG_FILE','get-gift-catalog','add-manual-gift',"nativeScope:'global'","scope='global';",'backgroundThrottling:false'):
    if marker not in m: raise SystemExit(f'FIX10 main marker missing: {marker}')
for marker in ('giftCatalog','pspButtonOptions','btnRefreshGifts','btnAddManualGift',"$('nativeRankingScope').value='global';"):
    if marker not in r: raise SystemExit(f'FIX10 renderer marker missing: {marker}')
if 'textContent=JSON.stringify(e,null,2);loadGifts()' in r: raise SystemExit('FIX10 live auto-rerender survived')
if '<input class="cellInput button"' in r: raise SystemExit('FIX10 free-text PSP button input survived')
for marker in ('rankScope','btnOnlineLogin','get-online-rankings','nativeRankingScope'):
    if marker not in (r+h): raise SystemExit(f'FIX10 old workflow compatibility marker missing: {marker}')

if build_info.exists():
    with build_info.open('a', encoding='utf-8') as f:
        f.write('\nPSP FloGB FIX10\nGift starter catalog + manual gift\nRule editor stable during LIVE\nExternal Electron overlay/BXH hidden\nPersistent WEEK/MONTH forced GLOBAL\nFull PSP button dropdown\n')

print('FIX10 SOURCE PREFLIGHT PASS')
print('=== FIX10 PASS ===')
