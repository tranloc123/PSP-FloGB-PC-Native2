from __future__ import annotations
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_pc_fix8_rank_reset.py <ppsspp_repo>')

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()
main_js = PROJECT / 'main.js'
renderer_js = PROJECT / 'renderer' / 'app.js'
build_info = REPO / 'PSP_LIVE_FLOGB_BUILD_INFO.txt'

def must(p: Path):
    if not p.exists():
        raise SystemExit(f'FIX8 missing file: {p}')
    return p

def replace_once(path: Path, old: str, new: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'FIX8 {label}: expected 1 occurrence, found {n}')
    path.write_text(src.replace(old, new, 1), encoding='utf-8')
    print(f'FIX8 {label}: PASS')

def regex_once(path: Path, pattern: str, replacement: str, label: str):
    src = must(path).read_text(encoding='utf-8')
    out, n = re.subn(pattern, lambda _m: replacement, src, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f'FIX8 {label}: expected 1 regex match, found {n}')
    path.write_text(out, encoding='utf-8')
    print(f'FIX8 {label}: PASS')

print('=== PSP FloGB PC Native FIX8: WEEK/MONTH RESET ===')

replace_once(main_js,
    'let statePollTimer = null;',
    'let statePollTimer = null;\nlet rankBoundaryTimer = null;',
    'rank boundary timer field')

replace_once(main_js,
'''function cleanupApp(){
  if (statePollTimer) { clearInterval(statePollTimer); statePollTimer = null; }
  closeAuxWindows();''',
'''function cleanupApp(){
  if (statePollTimer) { clearInterval(statePollTimer); statePollTimer = null; }
  if (rankBoundaryTimer) { clearTimeout(rankBoundaryTimer); rankBoundaryTimer = null; }
  closeAuxWindows();''',
    'rank boundary timer cleanup')

rank_runtime = r'''const RANK_TIME_ZONE = 'Asia/Ho_Chi_Minh';
const RANK_VN_OFFSET_MS = 7 * 60 * 60 * 1000;

function rankDateParts(ts=Date.now()){
  const parts=new Intl.DateTimeFormat('en-CA',{
    timeZone:RANK_TIME_ZONE,year:'numeric',month:'2-digit',day:'2-digit'
  }).formatToParts(new Date(ts));
  const v={};
  for(const p of parts) if(p.type!=='literal') v[p.type]=p.value;
  return {year:Number(v.year),month:Number(v.month),day:Number(v.day)};
}
function ymd(y,m,d){
  return `${String(y).padStart(4,'0')}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
}
function shiftDateKey(key,days){
  const [y,m,d]=String(key).split('-').map(Number);
  const dt=new Date(Date.UTC(y,m-1,d));
  dt.setUTCDate(dt.getUTCDate()+Number(days||0));
  return dt.toISOString().slice(0,10);
}
function dayKey(ts=Date.now()){
  const p=rankDateParts(ts);
  return ymd(p.year,p.month,p.day);
}
function weekKey(ts=Date.now()){
  const p=rankDateParts(ts);
  const dt=new Date(Date.UTC(p.year,p.month-1,p.day));
  const mondayOffset=(dt.getUTCDay()+6)%7;
  dt.setUTCDate(dt.getUTCDate()-mondayOffset);
  return dt.toISOString().slice(0,10);
}
function monthKey(ts=Date.now()){
  const p=rankDateParts(ts);
  return `${String(p.year).padStart(4,'0')}-${String(p.month).padStart(2,'0')}`;
}
function rankPeriodKeys(ts=Date.now()){
  return {day:dayKey(ts),week:weekKey(ts),month:monthKey(ts)};
}
function legacyCurrentScores(u,ts=Date.now()){
  const keys=rankPeriodKeys(ts);
  const weekEnd=shiftDateKey(keys.week,6);
  let week=0,month=0;
  for(const [d,v] of Object.entries(u?.daily||{})){
    const n=Math.max(0,Number(v)||0);
    if(d>=keys.week && d<=weekEnd) week+=n;
    if(String(d).startsWith(keys.month+'-')) month+=n;
  }
  return {week,month};
}
function ensureRankingPeriods(db,ts=Date.now()){
  db=db&&typeof db==='object'?db:{};
  db.users=db.users&&typeof db.users==='object'?db.users:{};
  db.meta=db.meta&&typeof db.meta==='object'?db.meta:{};
  const keys=rankPeriodKeys(ts);
  const initialized=db.meta.rankPeriodsV1===1;
  const oldWeek=String(db.meta.weekKey||'');
  const oldMonth=String(db.meta.monthKey||'');
  const weekChanged=initialized && oldWeek!==keys.week;
  const monthChanged=initialized && oldMonth!==keys.month;
  let changed=!initialized || weekChanged || monthChanged;

  for(const u of Object.values(db.users)){
    if(!u||typeof u!=='object') continue;
    if(!initialized){
      const legacy=legacyCurrentScores(u,ts);
      if(!Number.isFinite(Number(u.weekScore))) u.weekScore=legacy.week;
      if(!Number.isFinite(Number(u.monthScore))) u.monthScore=legacy.month;
    }
    if(weekChanged) u.weekScore=0;
    if(monthChanged) u.monthScore=0;
    if(!Number.isFinite(Number(u.weekScore))) u.weekScore=0;
    if(!Number.isFinite(Number(u.monthScore))) u.monthScore=0;
    if(u.daily && Object.keys(u.daily).length) changed=true;
    u.daily={};
  }

  db.meta.rankPeriodsV1=1;
  db.meta.timeZone=RANK_TIME_ZONE;
  db.meta.weekKey=keys.week;
  db.meta.monthKey=keys.month;
  db.meta.checkedAt=Number(ts);
  if(weekChanged) db.meta.lastWeekResetAt=Number(ts);
  if(monthChanged) db.meta.lastMonthResetAt=Number(ts);
  return {db,changed,weekChanged,monthChanged,keys,oldWeek,oldMonth};
}
function syncRankingPeriods(reason='runtime',ts=Date.now()){
  const raw=readJson(RANKINGS_FILE,{users:{}});
  const result=ensureRankingPeriods(raw,ts);
  if(result.changed){
    writeJson(RANKINGS_FILE,result.db);
    try{
      if(result.weekChanged) nativeRankHashes.delete('WEEK');
      if(result.monthChanged) nativeRankHashes.delete('MONTH');
    }catch{}
    if(result.weekChanged) sendLog(`BXH TUẦN RESET | ${result.oldWeek||'-'} -> ${result.keys.week} | ${RANK_TIME_ZONE}`);
    if(result.monthChanged) sendLog(`BXH THÁNG RESET | ${result.oldMonth||'-'} -> ${result.keys.month} | ${RANK_TIME_ZONE}`);
    if(!result.weekChanged && !result.monthChanged) sendLog(`BXH PERIOD INIT | week=${result.keys.week} month=${result.keys.month} | ${RANK_TIME_ZONE}`);
  }
  return result;
}
function nextVietnamMidnightDelay(ts=Date.now()){
  const p=rankDateParts(ts);
  const nextUtc=Date.UTC(p.year,p.month-1,p.day+1)-RANK_VN_OFFSET_MS;
  return Math.max(1000,nextUtc-Number(ts)+250);
}
function scheduleRankBoundaryCheck(){
  if(rankBoundaryTimer){clearTimeout(rankBoundaryTimer);rankBoundaryTimer=null;}
  rankBoundaryTimer=setTimeout(()=>{
    try{syncRankingPeriods('midnight');}catch(e){sendLog('BXH reset check: '+e.message,'error');}
    scheduleRankBoundaryCheck();
  },nextVietnamMidnightDelay());
}
function addRanking(user, points, kind){
  if(!user?.id) return;
  const db=readJson(RANKINGS_FILE,{users:{}});
  const period=ensureRankingPeriods(db);
  const id=String(user.id);
  const u=period.db.users[id]||{id,uniqueId:'',nickname:'',avatar:'',total:0,gifts:0,likes:0,weekScore:0,monthScore:0,daily:{}};
  u.uniqueId=user.uniqueId||u.uniqueId;
  u.nickname=user.nickname||u.nickname;
  u.avatar=user.avatar||u.avatar;
  const p=Math.max(0,Number(points)||0);
  u.total=(u.total||0)+p;
  u.weekScore=Math.max(0,Number(u.weekScore)||0)+p;
  u.monthScore=Math.max(0,Number(u.monthScore)||0)+p;
  if(kind==='gift')u.gifts=(u.gifts||0)+1;
  if(kind==='like')u.likes=(u.likes||0)+p;
  u.daily={};
  period.db.users[id]=u;
  writeJson(RANKINGS_FILE,period.db);
}'''

regex_once(main_js,
    r"function dayKey\(ts=Date\.now\(\)\)\{.*?\}\nfunction addRanking\(user, points, kind\)\{.*?\n\}",
    rank_runtime,
    'Vietnam period engine + explicit week/month scores')

persistent_runtime = r'''function persistentRows(field){
  const db=readJson(RANKINGS_FILE,{users:{}});
  return Object.values(db.users||{}).map(u=>({
    name:u.uniqueId||u.nickname||u.id||'viewer',
    avatar:u.avatar||'', score:Math.max(0,Number(u?.[field])||0),
  })).filter(r=>r.score>0).sort((a,b)=>b.score-a.score).slice(0,100);
}'''

regex_once(main_js,
    r"function scoreSince\(u, days\)\{.*?\n\}\nfunction persistentRows\(days\)\{.*?\n\}",
    persistent_runtime,
    'native ranking explicit period counters')

replace_once(main_js, "await pushRankIfChanged('WEEK',persistentRows(7));", "await pushRankIfChanged('WEEK',persistentRows('weekScore'));", 'native WEEK source')
replace_once(main_js, "await pushRankIfChanged('MONTH',persistentRows(30));", "await pushRankIfChanged('MONTH',persistentRows('monthScore'));", 'native MONTH source')

replace_once(renderer_js,
"""function periodScore(u,mode){if(mode==='all')return Number(u.total||0);const n=new Date(),cut=new Date(n);cut.setHours(0,0,0,0);cut.setDate(cut.getDate()-(mode==='week'?6:29));let v=0;for(const [d,x] of Object.entries(u.daily||{}))if(new Date(d)>=cut)v+=Number(x||0);return v;}""",
"""function periodScore(u,mode){if(mode==='all')return Number(u.total||0);if(mode==='week')return Number(u.weekScore||0);if(mode==='month')return Number(u.monthScore||0);return 0;}""",
    'renderer exact period score')

replace_once(main_js,
    "ipcMain.handle('get-rankings',()=>readJson(RANKINGS_FILE,{users:{}}));",
    "ipcMain.handle('get-rankings',()=>{syncRankingPeriods('ui');return readJson(RANKINGS_FILE,{users:{}});});",
    'UI ranking boundary check')

replace_once(main_js,
'''  startController();
  createMain();
  if(settings().showOverlay)createOverlay();''',
'''  startController();
  createMain();
  syncRankingPeriods('startup');
  scheduleRankBoundaryCheck();
  if(settings().showOverlay)createOverlay();''',
    'startup ranking reset scheduler')

m = main_js.read_text(encoding='utf-8')
r = renderer_js.read_text(encoding='utf-8')
required = [
    "const RANK_TIME_ZONE = 'Asia/Ho_Chi_Minh';",
    'weekScore', 'monthScore', "syncRankingPeriods('startup')",
    'scheduleRankBoundaryCheck();', "persistentRows('weekScore')",
    "persistentRows('monthScore')", 'BXH TUẦN RESET', 'BXH THÁNG RESET'
]
missing = [x for x in required if x not in m]
if missing:
    raise SystemExit(f'FIX8 main preflight missing: {missing}')
for forbidden in ('persistentRows(7)','persistentRows(30)','function scoreSince(u, days)','new Date(ts).toISOString().slice(0,10)'):
    if forbidden in m:
        raise SystemExit(f'FIX8 rolling/UTC marker survived: {forbidden}')
if "cut.setDate(cut.getDate()-(mode==='week'?6:29))" in r:
    raise SystemExit('FIX8 renderer rolling 7/30 calculation survived')
if 'u.weekScore' not in r or 'u.monthScore' not in r:
    raise SystemExit('FIX8 renderer explicit period counters missing')

if build_info.exists():
    with build_info.open('a', encoding='utf-8') as f:
        f.write('\nPSP FloGB PC Native FIX8\nRanking timezone: Asia/Ho_Chi_Minh\nWeekly reset: Monday 00:00\nMonthly reset: day 1 00:00\nWeekly/monthly history: not retained\nLifetime total: retained\n')

print('FIX8 SOURCE PREFLIGHT PASS')
print('Weekly reset: Monday 00:00 Asia/Ho_Chi_Minh')
print('Monthly reset: day 1 00:00 Asia/Ho_Chi_Minh')
print('Old weekly/monthly history: NOT RETAINED')
print('=== FIX8 PASS ===')
