"""Self-contained HTML replay dashboard: every scenario x controller, one seeded run each.

The file embeds the recorded runs as JSON and needs no network, server or library. Open it in
any browser. All numbers shown are ground truth from the simulator, not estimates.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict

import numpy as np

from .config import load_scenario
from .criteria import effective_rules, evaluate, load_criteria
from .metrics import compute_metrics
from .runner import CONTROLLERS, list_scenarios, prepare_cfg
from .simulation import run_simulation
from .supervisor import MODE_NAMES

STRIDE = 4          # keep every 4th step (2.5 Hz at dt = 0.1)


def _clean(x):
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if (math.isnan(x) or math.isinf(x)) else round(x, 3)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def record_run(path: str, controller: str, seed: int, crit: Dict[str, Any]) -> Dict[str, Any]:
    cfg = prepare_cfg(path, controller, None)
    res = run_simulation(cfg, seed=seed)
    tr = res.trace
    m = compute_metrics(res, crit["evaluation"])
    ok, details = evaluate(m, effective_rules(crit, cfg))
    sl = slice(0, tr.steps, STRIDE)
    pos = np.round(tr.pos[sl], 1)
    est = np.linalg.norm(tr.est_pos[sl] - tr.pos[sl], axis=2)
    return {
        "scenario": cfg["name"], "description": cfg["description"], "controller": controller, "seed": seed,
        "dt": tr.dt * STRIDE, "n": tr.n,
        "pos": [[[_clean(v) for v in d] for d in frame] for frame in pos.tolist()],
        "mode": tr.mode[sl].tolist(), "air": tr.airborne[sl].astype(int).tolist(),
        "bat": np.round(tr.battery[sl], 0).astype(int).tolist(), "peers": tr.peers[sl].tolist(),
        "esterr": [[_clean(v) for v in row] for row in np.round(est, 1).tolist()],
        "ferr": [_clean(v) for v in tr.form_err[sl]], "sep": [_clean(v) for v in tr.min_sep[sl]],
        "faults": [{"type": f.type, "drones": f.drones, "t_on": _clean(f.t_on), "t_off": _clean(f.t_off)} for f in res.faults],
        "events": [{"t": _clean(t), "kind": k, "obs": o, "subj": s, "detail": d} for (t, k, o, s, d) in res.events
                   if k in ("MODE", "LEADER") and (t > 1.0 or k == "MODE")],
        "passed": bool(ok),
        "criteria": [{"name": d["criterion"], "value": _clean(d["value"]) if not isinstance(d["value"], bool) else d["value"],
                      "rule": d["rule"], "passed": d["passed"]} for d in details],
        "geofence": cfg["safety"]["geofence"], "waypoints": cfg["mission"]["waypoints"],
    }


def build_dashboard(out_path: str, scen_dir: str, crit_path: str, seed: int = 1000) -> str:
    crit = load_criteria(crit_path)
    runs = []
    for p in list_scenarios(scen_dir):
        for c in CONTROLLERS:
            runs.append(record_run(p, c, seed, crit))
    html = TEMPLATE.replace("__DATA__", json.dumps({"runs": runs, "modes": list(MODE_NAMES)}, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SwarmSim Replay</title>
<style>
:root{--bg:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--good:#0b7a0b;--bad:#d03b3b;--warn:#b36b00;--tint:#eeede8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--bad:#e66767;--warn:#fab219;--tint:#232321}}
:root[data-theme="dark"]{--bg:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--bad:#e66767;--warn:#fab219;--tint:#232321}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 40px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:end;justify-content:space-between;margin-bottom:14px}
h1{font-size:20px;margin:0 0 2px}.sub{color:var(--ink2);font-size:13px;margin:0}
.ctl{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
label{display:flex;flex-direction:column;font-size:11.5px;color:var(--ink2);gap:3px}
select,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:8px;padding:7px 10px;min-height:36px}
button{cursor:pointer}button:hover,select:hover{border-color:var(--muted)}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:14px}
@media (max-width:860px){.grid{grid-template-columns:minmax(0,1fr)}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;min-width:0;overflow-x:auto}
.card h2{font-size:12.5px;margin:0 0 8px;color:var(--ink2);font-weight:600;letter-spacing:.02em;text-transform:uppercase}
canvas{width:100%;display:block}
.verdict{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.badge{font-weight:700;font-size:12px;padding:3px 9px;border-radius:999px;border:1.5px solid currentColor}
.badge.pass{color:var(--good)}.badge.fail{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{font-weight:600;color:var(--ink2);text-align:left;font-size:11.5px;border-bottom:1px solid var(--axis);padding:4px 6px}
td{padding:4px 6px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
td.num,th.num{text-align:right}
.ok{color:var(--good)}.no{color:var(--bad);font-weight:600}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:10px 0 0}
input[type=range]{flex:1 1 140px;accent-color:var(--s1);min-width:80px}
.tlabel{font-variant-numeric:tabular-nums;min-width:96px;text-align:right;font-size:13px;color:var(--ink2)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-top:8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.log{max-height:190px;overflow:auto;font-size:12.5px}
.log div{padding:3px 4px;border-bottom:1px solid var(--grid);cursor:pointer;display:flex;gap:10px}
.log div:hover{background:var(--tint)}.log b{font-variant-numeric:tabular-nums;color:var(--ink2);min-width:54px}
.desc{font-size:13px;color:var(--ink2);margin:0 0 10px}
.full{grid-column:1/-1}
.note{font-size:11.5px;color:var(--muted);margin-top:14px}
</style></head><body><div class="wrap">
<header><div><h1>SwarmSim replay</h1><p class="sub">Recorded simulation runs (ground truth). Simulation only, no hardware or operational capability.</p></div>
<div class="ctl"><label>Scenario<select id="sc"></select></label><label>Controller<select id="ct"></select></label>
<button id="theme" title="Toggle light or dark theme" aria-label="Toggle theme">Theme</button></div></header>
<p class="desc" id="desc"></p>
<div class="grid">
<section class="card"><h2>Top-down view</h2><canvas id="map" aria-label="Top-down map of the drone swarm"></canvas>
<div class="controls"><button id="play" aria-label="Play or pause">Play</button><button id="restart" aria-label="Restart">Restart</button>
<input type="range" id="slider" min="0" max="100" value="0" aria-label="Time"><span class="tlabel" id="tl"></span>
<label style="flex-direction:row;align-items:center;gap:6px">Speed<select id="spd"><option value="1">1x</option><option value="2" selected>2x</option><option value="4">4x</option><option value="8">8x</option></select></label></div>
<div class="legend" id="legend"></div></section>
<section class="card"><div class="verdict"><h2 style="margin:0">Verdict for this run</h2><span class="badge" id="badge"></span></div>
<table id="crit"><thead><tr><th>Criterion</th><th class="num">Value</th><th>Rule</th><th></th></tr></thead><tbody></tbody></table>
<p class="note">One seeded run. The full campaign (30 trials per case) is in REPORT.pdf.</p></section>
<section class="card"><h2>Drones at the cursor</h2><table id="dt"><thead><tr><th>Drone</th><th>Mode</th><th class="num">Alt m</th><th class="num">Battery</th><th class="num">Peers</th><th class="num">Est. error m</th></tr></thead><tbody></tbody></table></section>
<section class="card"><h2>Events (click to jump)</h2><div class="log" id="log"></div></section>
<section class="card full"><h2>Formation error and minimum separation</h2><canvas id="chart" aria-label="Formation error and separation over time"></canvas>
<div class="legend"><span><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--s1)" stroke-width="2"/></svg> formation error [m]</span>
<span><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--s2)" stroke-width="2"/></svg> minimum separation [m]</span>
<span>dashed: collision (2 m) and safe margin (4 m); vertical bars: fault onsets</span></div></section>
</div><p class="note">Click or drag on the chart or slider to move through time.</p></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),RUNS=D.runs,MODES=D.modes;
const $=id=>document.getElementById(id),css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const scs=[...new Set(RUNS.map(r=>r.scenario))],cts=[...new Set(RUNS.map(r=>r.controller))];
const CN={leader_follower:'Leader-follower',consensus:'Consensus'};
$('sc').innerHTML=scs.map(s=>`<option value="${s}">${s.replace(/_/g,' ')}</option>`).join('');
$('ct').innerHTML=cts.map(c=>`<option value="${c}">${CN[c]||c}</option>`).join('');
let run=null,frame=0,playing=false,last=0,spd=2;
function pick(){run=RUNS.find(r=>r.scenario===$('sc').value&&r.controller===$('ct').value);frame=0;$('slider').max=run.pos.length-1;
 $('desc').textContent=run.description;fillCrit();fillLog();draw();}
function fillCrit(){const b=$('badge');b.textContent=run.passed?'PASS':'FAIL';b.className='badge '+(run.passed?'pass':'fail');
 $('crit').tBodies[0].innerHTML=run.criteria.map(c=>{const v=c.value===null?'n/a':(typeof c.value==='number'?(+c.value.toFixed(2)):c.value);
 const r=Object.entries(c.rule).map(([k,x])=>({min:'>= ',max:'<= ',equals:'= '}[k]+x)).join(' ');
 return `<tr><td>${c.name.replace(/_/g,' ')}</td><td class="num">${v}</td><td>${r}</td><td class="${c.passed?'ok':'no'}">${c.passed?'pass':'FAIL'}</td></tr>`}).join('');}
function fillLog(){const L=$('log');const items=[];
 run.faults.forEach(f=>items.push({t:f.t_on,txt:`FAULT ${f.type.replace(/_/g,' ')} on ${f.drones.length>2?'all drones':'drone '+f.drones.join(', ')}`}));
 run.events.forEach(e=>items.push({t:e.t,txt:e.kind==='MODE'?`drone ${e.obs}: ${e.detail.replace(/_/g,' ').replace('->',' → ')}`:`drone ${e.obs} sees leader ${e.subj}`}));
 items.sort((a,b)=>a.t-b.t);L.innerHTML=items.map(i=>`<div data-t="${i.t}"><b>${i.t.toFixed(1)} s</b><span>${i.txt}</span></div>`).join('')||'<div>No events</div>';
 L.querySelectorAll('div[data-t]').forEach(d=>d.onclick=()=>{frame=Math.min(run.pos.length-1,Math.round(+d.dataset.t/run.dt));draw();});}
const MC=['--s1','--s2','#eda100','#e87ba4','--muted','--bad'];
function mcol(m){const v=MC[m];return v.startsWith('--')?css(v):v}
function shape(ctx,x,y,m,r,col,bg,label){ctx.lineWidth=2;ctx.strokeStyle=col;ctx.fillStyle=col;ctx.beginPath();
 if(m===0){ctx.arc(x,y,r,0,7);ctx.fill();}
 else if(m===1){ctx.arc(x,y,r,0,7);ctx.fillStyle=bg;ctx.fill();ctx.stroke();}
 else if(m===2){ctx.moveTo(x,y-r-1);ctx.lineTo(x+r+1,y+r);ctx.lineTo(x-r-1,y+r);ctx.closePath();ctx.fill();}
 else if(m===3){ctx.moveTo(x,y+r+1);ctx.lineTo(x+r+1,y-r);ctx.lineTo(x-r-1,y-r);ctx.closePath();ctx.fill();}
 else if(m===4){ctx.rect(x-r,y-r,2*r,2*r);ctx.fill();}
 else{ctx.moveTo(x-r,y-r);ctx.lineTo(x+r,y+r);ctx.moveTo(x+r,y-r);ctx.lineTo(x-r,y+r);ctx.stroke();}
 if(label!==undefined){ctx.fillStyle=css('--ink');ctx.font='600 11px system-ui';ctx.textAlign='left';ctx.fillText(label,x+r+4,y-r-2);}}
function setup(c,h){const dpr=window.devicePixelRatio||1,w=c.clientWidth;c.width=w*dpr;c.height=h*dpr;c.style.height=h+'px';const x=c.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);return[x,w,h];}
function drawMap(){const c=$('map');const w0=c.clientWidth;const[ctx,w,h]=setup(c,Math.min(560,w0));
 const gf=run.geofence,pad=22,sx=(w-2*pad)/(gf[2]-gf[0]),sy=(h-2*pad)/(gf[3]-gf[1]),s=Math.min(sx,sy);
 const X=x=>pad+(x-gf[0])*s,Y=y=>h-pad-(y-gf[1])*s;ctx.clearRect(0,0,w,h);
 ctx.strokeStyle=css('--grid');ctx.lineWidth=1;for(let g=Math.ceil(gf[0]/50)*50;g<=gf[2];g+=50){ctx.beginPath();ctx.moveTo(X(g),Y(gf[1]));ctx.lineTo(X(g),Y(gf[3]));ctx.stroke();}
 for(let g=Math.ceil(gf[1]/50)*50;g<=gf[3];g+=50){ctx.beginPath();ctx.moveTo(X(gf[0]),Y(g));ctx.lineTo(X(gf[2]),Y(g));ctx.stroke();}
 ctx.setLineDash([6,5]);ctx.strokeStyle=css('--muted');ctx.strokeRect(X(gf[0]),Y(gf[3]),(gf[2]-gf[0])*s,(gf[3]-gf[1])*s);ctx.setLineDash([]);
 ctx.fillStyle=css('--muted');ctx.font='11px system-ui';ctx.textAlign='left';ctx.fillText('geofence',X(gf[0])+4,Y(gf[3])+13);
 ctx.strokeStyle=css('--axis');ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(X(0),Y(0));run.waypoints.forEach(p=>ctx.lineTo(X(p[0]),Y(p[1])));ctx.stroke();
 run.waypoints.forEach((p,i)=>{ctx.fillStyle=css('--muted');ctx.beginPath();ctx.arc(X(p[0]),Y(p[1]),4,0,7);ctx.fill();ctx.fillStyle=css('--ink2');ctx.font='11px system-ui';ctx.fillText('WP'+(i+1),X(p[0])+7,Y(p[1])+4);});
 const n=run.n;for(let i=0;i<n;i++){ctx.strokeStyle=css('--axis');ctx.lineWidth=1.2;ctx.beginPath();let st=Math.max(0,frame-120);
  for(let k=st;k<=frame;k++){const p=run.pos[k][i];if(k===st)ctx.moveTo(X(p[0]),Y(p[1]));else ctx.lineTo(X(p[0]),Y(p[1]));}ctx.stroke();}
 const bg=css('--surface');for(let i=0;i<n;i++){const p=run.pos[frame][i],m=run.mode[frame][i];shape(ctx,X(p[0]),Y(p[1]),m,7,mcol(m),bg,i);}}
function drawChart(){const c=$('chart');const[ctx,w,h]=setup(c,230);const L=44,R=12,T=10,B=26,T1=run.pos.length*run.dt;
 const X=t=>L+(t/T1)*(w-L-R);const vals=[...run.ferr,...run.sep].filter(v=>v!==null&&v<60);const ymax=Math.max(6,Math.ceil(Math.max(...vals,1)/2)*2);const Y=v=>T+(1-v/ymax)*(h-T-B);
 ctx.clearRect(0,0,w,h);ctx.font='11px system-ui';ctx.fillStyle=css('--muted');ctx.textAlign='right';ctx.strokeStyle=css('--grid');ctx.lineWidth=1;
 const step=ymax>14?5:2;for(let v=0;v<=ymax;v+=step){ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(w-R,Y(v));ctx.stroke();ctx.fillText(v,L-6,Y(v)+4);}
 ctx.textAlign='center';for(let t=0;t<=T1;t+=20){ctx.fillText(t+' s',X(t),h-8);}
 ctx.setLineDash([5,4]);ctx.strokeStyle=css('--ink2');[[2,'collision'],[4,'safe margin']].forEach(([v,l])=>{ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(w-R,Y(v));ctx.stroke();});ctx.setLineDash([]);
 run.faults.forEach(f=>{ctx.strokeStyle=css('--bad');ctx.globalAlpha=.55;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(X(f.t_on),T);ctx.lineTo(X(f.t_on),h-B);ctx.stroke();ctx.globalAlpha=1;});
 const line=(arr,col)=>{ctx.strokeStyle=col;ctx.lineWidth=2;ctx.lineJoin='round';ctx.beginPath();let pen=false;arr.forEach((v,k)=>{if(v===null||v>ymax){pen=false;return;}const x=X(k*run.dt),y=Y(v);if(!pen){ctx.moveTo(x,y);pen=true}else ctx.lineTo(x,y)});ctx.stroke();};
 line(run.ferr,css('--s1'));line(run.sep,css('--s2'));
 ctx.strokeStyle=css('--ink');ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(X(frame*run.dt),T);ctx.lineTo(X(frame*run.dt),h-B);ctx.stroke();}
function drawTable(){const tb=$('dt').tBodies[0];let h='';for(let i=0;i<run.n;i++){const m=run.mode[frame][i],p=run.pos[frame][i];
 h+=`<tr><td>${i}</td><td>${MODES[m].replace(/_/g,' ').toLowerCase()}</td><td class="num">${p[2].toFixed(1)}</td><td class="num">${run.bat[frame][i]}%</td><td class="num">${run.peers[frame][i]}</td><td class="num">${run.esterr[frame][i]}</td></tr>`}tb.innerHTML=h;}
function draw(){$('slider').value=frame;$('tl').textContent=(frame*run.dt).toFixed(1)+' / '+((run.pos.length-1)*run.dt).toFixed(0)+' s';drawMap();drawChart();drawTable();}
function tick(ts){if(playing){if(!last)last=ts;const adv=(ts-last)/1000*spd/run.dt;if(adv>=1){frame+=Math.floor(adv);last=ts;if(frame>=run.pos.length-1){frame=run.pos.length-1;playing=false;$('play').textContent='Play';}draw();}}else last=0;requestAnimationFrame(tick);}
$('play').onclick=()=>{if(frame>=run.pos.length-1)frame=0;playing=!playing;$('play').textContent=playing?'Pause':'Play';last=0;};
$('restart').onclick=()=>{frame=0;draw();};$('slider').oninput=e=>{frame=+e.target.value;draw();};$('spd').onchange=e=>spd=+e.target.value;
$('sc').onchange=pick;$('ct').onchange=pick;
$('theme').onclick=()=>{const r=document.documentElement,cur=r.dataset.theme||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');r.dataset.theme=cur==='dark'?'light':'dark';draw();};
function scrub(e){const c=$('chart'),b=c.getBoundingClientRect(),T1=run.pos.length*run.dt,t=((e.clientX-b.left-44)/(b.width-56))*T1;frame=Math.max(0,Math.min(run.pos.length-1,Math.round(t/run.dt)));draw();}
let drag=false;$('chart').onpointerdown=e=>{drag=true;scrub(e);};window.onpointerup=()=>drag=false;$('chart').onpointermove=e=>{if(drag)scrub(e)};
$('legend').innerHTML=[[0,'formation'],[1,'hold'],[2,'GPS failsafe'],[3,'landing'],[4,'landed'],[5,'failed']].map(([m,l])=>`<span><svg width="14" height="14" viewBox="-7 -7 14 14" data-m="${m}"></svg>${l}</span>`).join('');
function legendShapes(){document.querySelectorAll('#legend svg').forEach(s=>{const m=+s.dataset.m,col=mcol(m),bg=css('--surface');let d='';
 if(m===0)d=`<circle r="5" fill="${col}"/>`;else if(m===1)d=`<circle r="5" fill="${bg}" stroke="${col}" stroke-width="2"/>`;else if(m===2)d=`<path d="M0-6L6 5H-6Z" fill="${col}"/>`;else if(m===3)d=`<path d="M0 6L6-5H-6Z" fill="${col}"/>`;else if(m===4)d=`<rect x="-5" y="-5" width="10" height="10" fill="${col}"/>`;else d=`<path d="M-5-5L5 5M5-5L-5 5" stroke="${col}" stroke-width="2"/>`;s.innerHTML=d;});}
window.addEventListener('resize',()=>run&&draw());pick();legendShapes();requestAnimationFrame(tick);
const mo=new MutationObserver(legendShapes);mo.observe(document.documentElement,{attributes:true});
</script></body></html>
"""
