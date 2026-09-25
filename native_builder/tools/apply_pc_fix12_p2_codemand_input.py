from __future__ import annotations
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_pc_fix12_p2_codemand_input.py <ppsspp_repo>')

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parent.parent if SCRIPT.parent.name == 'tools' else SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()
main_js = PROJECT / 'main.js'
renderer_js = PROJECT / 'renderer' / 'app.js'
controller_js = PROJECT / 'core' / 'controller-service.js'
build_info = REPO / 'PSP_LIVE_FLOGB_BUILD_INFO.txt'

for p in (main_js, renderer_js, controller_js):
    if not p.exists(): raise SystemExit(f'FIX12 missing file: {p}')

def replace_once(path, old, new, label):
    s = path.read_text(encoding='utf-8'); n = s.count(old)
    if n != 1: raise SystemExit(f'FIX12 {label}: expected 1 occurrence, found {n}')
    path.write_text(s.replace(old,new,1), encoding='utf-8'); print(f'FIX12 {label}: PASS')

print('=== PSP FloGB FIX12: REAL P2 CODEMASK BUTTON INPUT ===')

p2_runtime = r'''
const P2_CODEMASK_ADDR=0x088F0BC8;
const P2_CODEMASK_ORIGINAL=0x8D470688;
const P2_CODEMASK_NEUTRAL=0x34060000;
const P2_BUTTON_MASKS=Object.freeze({
  select:0x4000,start:0x8000,up:0x2000,right:0x0400,down:0x1000,left:0x0800,
  l:0x0002,ltrigger:0x0002,r:0x0010,rtrigger:0x0010,
  triangle:0x0100,circle:0x0020,cross:0x0040,square:0x0200
});
let p2CodeMaskQueue=Promise.resolve();
function p2ButtonMask(button){
  const key=String(button||'').trim().toLowerCase();
  const mask=P2_BUTTON_MASKS[key];
  if(!mask)throw new Error(`P2 chưa hỗ trợ nút: ${button}`);
  return {key,mask};
}
function p2CodeMaskTap(button,holdMs=80,gapMs=55){
  const job=async()=>{
    const {key,mask}=p2ButtonMask(button);
    const hold=Math.max(45,Math.min(180,Number(holdMs)||80));
    const gap=Math.max(35,Math.min(250,Number(gapMs)||55));
    return ppssppCommand(async api=>{
      const original=(await api.readU32(P2_CODEMASK_ADDR))>>>0;
      const isOriginal=original===P2_CODEMASK_ORIGINAL;
      const isForced=((original>>>16)===0x3406);
      if(!isOriginal&&!isForced)throw new Error(`P2 CODEMASK sai opcode tại 0x088F0BC8: 0x${original.toString(16).padStart(8,'0').toUpperCase()}`);
      const forced=(P2_CODEMASK_NEUTRAL|mask)>>>0;
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const writeVerified=async(word,label)=>{
        api.writeU32(P2_CODEMASK_ADDR,word>>>0); await sleep(18);
        const rb=(await api.readU32(P2_CODEMASK_ADDR))>>>0;
        if(rb!==(word>>>0))throw new Error(`P2 ${label} readback fail: 0x${rb.toString(16).padStart(8,'0').toUpperCase()}`);
      };
      let restored=false;
      try{
        await writeVerified(forced,'DOWN'); await sleep(hold);
        await writeVerified(P2_CODEMASK_NEUTRAL,'UP'); await sleep(gap);
        await writeVerified(original,'RESTORE'); restored=true;
        return {ok:true,side:'P2',button:key,mask,address:P2_CODEMASK_ADDR,original};
      }finally{
        if(!restored){ try{api.writeU32(P2_CODEMASK_ADDR,original>>>0);}catch{} }
      }
    });
  };
  const run=p2CodeMaskQueue.then(job,job); p2CodeMaskQueue=run.catch(()=>{}); return run;
}
'''
replace_once(main_js, "const HP={P1:0x08BE364C,P2:0x08BFA30C};", p2_runtime+"const HP={P1:0x08BE364C,P2:0x08BFA30C};", 'P2 code-mask runtime')

replace_once(main_js,
"    await ppssppCommand(async api=>{for(let i=0;i<count;i++){await api.tap(button,2);await new Promise(r=>setTimeout(r,gap));}}); return;",
"""    if(memberTeam==='P2'){
      for(let i=0;i<count;i++) await p2CodeMaskTap(button,80,Math.min(250,Math.max(35,gap)));
    }else{
      await ppssppCommand(async api=>{for(let i=0;i<count;i++){await api.tap(button,2);await new Promise(r=>setTimeout(r,gap));}});
    }
    return;""", 'route input Rule by team')

replace_once(main_js,
"ipcMain.handle('ppsspp-tap',(_,button)=>ppssppCommand(api=>api.tap(String(button||'cross'),2)));",
"""ipcMain.handle('ppsspp-tap',(_,button)=>ppssppCommand(api=>api.tap(String(button||'cross'),2)));
ipcMain.handle('ppsspp-p2-tap',(_,button)=>p2CodeMaskTap(String(button||'cross'),80,55));""", 'P2 test IPC')

replace_once(renderer_js,
"""        <b>PSP Button Test</b>
        <div class=\"row\" style=\"margin-top:10px;flex-wrap:wrap\">""",
"""        <b>PSP Button Test</b>
        <div class=\"row\" style=\"margin-top:8px\"><select id=\"testPspSide\"><option value=\"P1\">P1 / PSP PAD</option><option value=\"P2\">P2 / SLOT 1</option></select></div>
        <div class=\"row\" style=\"margin-top:10px;flex-wrap:wrap\">""", 'P1/P2 PSP selector')

replace_once(renderer_js,
"""      await ipcRenderer.invoke('ppsspp-tap',btn.dataset.psp);
      status.textContent='Da gui nut PSP: '+btn.dataset.psp.toUpperCase();""",
"""      const side=document.getElementById('testPspSide')?.value||'P1';
      await ipcRenderer.invoke(side==='P2'?'ppsspp-p2-tap':'ppsspp-tap',btn.dataset.psp);
      status.textContent=`Da gui ${side}: ${btn.dataset.psp.toUpperCase()}${side==='P2'?' | CODEMASK 0x088F0BC8':''}`;""", 'P2 PSP test handler')

replace_once(controller_js, "inputP2:'NOT_WIRED_GAME_INTERNAL_PATH',", "inputP2:'CODEMASK_DYNAMIC_0x088F0BC8',", 'P2 capability status')

m=main_js.read_text(encoding='utf-8'); r=renderer_js.read_text(encoding='utf-8'); c=controller_js.read_text(encoding='utf-8')
for x in ('P2_CODEMASK_ADDR=0x088F0BC8','P2_CODEMASK_ORIGINAL=0x8D470688','p2CodeMaskTap','ppsspp-p2-tap',"if(memberTeam==='P2')",'square:0x0200','triangle:0x0100','circle:0x0020','cross:0x0040'):
    if x not in m: raise SystemExit(f'FIX12 main preflight missing: {x}')
for x in ('id="testPspSide"','P2 / SLOT 1','ppsspp-p2-tap','CODEMASK 0x088F0BC8'):
    if x not in r: raise SystemExit(f'FIX12 renderer preflight missing: {x}')
if "inputP2:'NOT_WIRED_GAME_INTERNAL_PATH'" in c: raise SystemExit('FIX12 old NOT_WIRED marker survived')
if "inputP2:'CODEMASK_DYNAMIC_0x088F0BC8'" not in c: raise SystemExit('FIX12 P2 capability marker missing')

if build_info.exists():
    with build_info.open('a',encoding='utf-8') as f:
        f.write('\nPSP FloGB FIX12\nP2 code-mask input @ 0x088F0BC8\nP2 Gift Rule input wired\n')
print('FIX12 SOURCE PREFLIGHT PASS')
print('P1 input: physical PSP pad route')
print('P2 input: dynamic code-mask route @ 0x088F0BC8')
print('=== FIX12 PASS ===')
