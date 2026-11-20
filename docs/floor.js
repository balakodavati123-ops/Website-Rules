/*! floor.js · Balaji Trading Desk · a live god's-eye view of the office floor.
 * Self-contained, dependency-free canvas component. Everything is drawn procedurally.
 *
 *   const f = Floor.mount(containerEl, {
 *     onSelect(entity) {},  // {type:'person'|'room'|'rack'|'dock'|'coo'|'ceo'|'flow', id, name, data}
 *     live: false,          // initial CEO presence light
 *     data: companyJson,    // optional first snapshot (same shape as update)
 *     height: 600           // optional px number or () => px; default is responsive
 *   });
 *   f.update(companyJson); f.setLive(true); f.destroy();
 *
 * DOM: one <div class="flr-root"> inside containerEl (canvas .flr-cv, buttons .flr-btn,
 * panel .flr-panel). The root also fires a bubbling 'floor:select' CustomEvent (detail = entity).
 */
(function(){
'use strict';
if(typeof window==='undefined'||window.Floor)return;

const FONT='ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace';
const BG='#060a13',LINE='#1c2c48',FG='#e8eef9',MUT='#8ea3c4',GREEN='#2de3a5',RED='#ff5f75',
 AMBER='#ffb64a',VIOLET='#a184ff',BLUE='#4f8cff',CYAN='#29d3ee',GOLD='#ffcf5a';
const KIND={data:CYAN,idea:AMBER,report:GREEN,order:VIOLET};
const TPAL=['#22d3ee','#f97316','#84cc16','#a78bfa','#f59e0b','#ec4899','#38bdf8','#10b981','#ef4444','#4f8cff','#facc15','#fb7185'];
const SKIN=['#f2c9a0','#dca67c','#c08a5e','#9a6a45','#e6b98f','#7d5236'];
const HAIR=['#17110d','#2a1b12','#3b2617','#0d0d12','#5b3a22','#26222e','#6b4a2a'];
const STC={active:GREEN,holding:BLUE,idle:MUT,alert:RED,vacant:'#5b6b88'};
const STT={active:'Working',holding:'In a trade',idle:'At the desk, nothing yet',alert:'Needs attention',vacant:'Empty seat'};
const SRCC={ok:GREEN,warn:AMBER,off:RED};
const SPR={
 star:['..#..','.###.','#####','.###.','.#.#.'],
 ring:['.###.','#...#','#...#','#...#','.###.'],
 dia:['..#..','.###.','##.##','.###.','..#..'],
 plant:['.g.G.','gG.Gg','.gGg.','..g..','.ppp.','.ppp.']
};

const clamp=(v,a,b)=>v<a?a:v>b?b:v;
const num=(v,d)=>{v=+v;return isFinite(v)?v:(d||0);};
const str=v=>v==null?'':String(v);
const arr=v=>Array.isArray(v)?v:[];
const obj=v=>v&&typeof v==='object'&&!Array.isArray(v)?v:{};
function hsh(s){s=str(s);let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return h>>>0;}
function h2(a,b){let h=(Math.imul(a|0,374761393)+Math.imul(b|0,668265263))|0;h=Math.imul(h^(h>>>13),1274126177);return((h^(h>>>16))>>>0)/4294967296;}
function rgb(c){c=str(c).trim();let m=/^#([0-9a-f]{3})$/i.exec(c);if(m)c='#'+m[1].split('').map(x=>x+x).join('');m=/^#([0-9a-f]{6})$/i.exec(c);if(!m)return null;const n=parseInt(m[1],16);return[n>>16,(n>>8)&255,n&255];}
const RC={};
function rgba(c,a){let v=RC[c];if(!v)v=RC[c]=rgb(c)||[142,163,196];return'rgba('+v[0]+','+v[1]+','+v[2]+','+a+')';}
function mix(c1,c2,t){const a=rgb(c1)||[0,0,0],b=rgb(c2)||[0,0,0];const f=i=>Math.round(a[i]+(b[i]-a[i])*t).toString(16).padStart(2,'0');return'#'+f(0)+f(1)+f(2);}
const esc=s=>str(s).replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');
function inr(v,sg){
 v=+v;if(!isFinite(v))return'—';
 const n=Math.round(Math.abs(v));let s=String(n);const l=s.slice(-3);let r=s.slice(0,-3);
 if(r)r=r.replace(/\B(?=(\d{2})+(?!\d))/g,',');
 return(v<0&&n?'−':sg&&n?'+':'')+'₹'+(r?r+',':'')+l;
}
const GL={};
function glowSpr(c){
 let s=GL[c];if(s)return s;
 s=document.createElement('canvas');s.width=s.height=48;
 const g=s.getContext('2d'),gr=g.createRadialGradient(24,24,0,24,24,24);
 gr.addColorStop(0,rgba(c,1));gr.addColorStop(0.3,rgba(c,0.42));gr.addColorStop(1,rgba(c,0));
 g.fillStyle=gr;g.fillRect(0,0,48,48);return(GL[c]=s);
}

/* ---------- data ---------- */
function normSt(s){s=str(s).toLowerCase();return STC[s]?s:s==='working'?'active':s==='empty'?'vacant':'idle';}
function norm(j){
 j=obj(j);
 const D={raw:j,upd:str(j.updated_at),ceo:obj(j.ceo),pnl:obj(j.pnl),coo:obj(j.coo),teams:[],staff:{},sources:[],flows:[],msgs:[]};
 arr(j.teams).forEach((t,i)=>{
  if(!t||typeof t!=='object')return;
  const id=str(t.id)||'team'+i,td=obj(t.today);
  const T={raw:t,id,name:str(t.name)||id,color:rgb(t.color)?str(t.color).trim():TPAL[i%TPAL.length],status:str(t.status)||'Active',
   paused:/paus/i.test(str(t.status)),staff:[],an:[],mgr:null,
   today:{trades:num(td.trades),open:num(td.open),pnl:num(td.pnl_rs!=null?td.pnl_rs:td.pnl),wins:num(td.wins)}};
  arr(t.staff).forEach((s,k)=>{
   if(!s||typeof s!=='object')return;
   const S={raw:s,id:str(s.id)||id+'-'+k,name:str(s.name),des:str(s.designation)||'Associate',role:str(s.role),
    kind:str(s.kind).toLowerCase()||'research',status:normSt(s.status),doing:str(s.doing),rec:obj(s.record),team:T};
   if(D.staff[S.id])S.id+='~'+i+'.'+k;
   T.staff.push(S);D.staff[S.id]=S;
  });
  const m=str(t.manager);
  T.mgr=T.staff.find(s=>s.id===m)||T.staff.find(s=>/manager/i.test(s.des))||T.staff.find(s=>s.kind==='trader')||null;
  T.an=T.staff.filter(s=>s!==T.mgr);
  D.teams.push(T);
 });
 arr(j.sources).forEach((s,i)=>{if(s&&typeof s==='object')D.sources.push({raw:s,id:str(s.id)||'src'+i,name:str(s.name)||str(s.id)||'Source',status:str(s.status).toLowerCase()||'idle',detail:str(s.detail)});});
 arr(j.flows).forEach(f=>{if(f&&typeof f==='object'&&f.from!=null&&f.to!=null)D.flows.push({raw:f,t:str(f.t),from:str(f.from),to:str(f.to),kind:str(f.kind).toLowerCase()||'data',text:str(f.text)});});
 arr(j.messages).forEach(m=>{if(m&&typeof m==='object')D.msgs.push({t:str(m.t),from:str(m.from),text:str(m.text),kind:str(m.kind)});});
 return D;
}
const sigOf=D=>D.teams.map(t=>t.id+'|'+t.color+'|'+(t.mgr?t.mgr.id:'')+'|'+t.an.map(s=>s.id).join(',')).join(';')+'#'+D.sources.map(s=>s.id).join(',');

/* ---------- layout: dock -> team rows -> COO -> CEO ---------- */
function build(D,o,C,R,K,ev){
 const RW=44+20*K,RH=46,G=14,nS=D.sources.length,slots=C*R,wide=ev==='w';
 const gridW=C*RW+(C+1)*G,gridH=R*RH+(R+1)*G,EX=wide?G/2+6+60+14+72+6:G/2+20+76+6,EH=wide?73:89;
 const L={o,C,R,K,RW,RH,G,ev,rooms:[],empty:[],nodes:[],lines:[],rails:[],nk:{},hits:[],seatBy:{},rackBy:{},roomBy:{},racks:[],rc:{}};
 const node=(x,y)=>{const k=Math.round(x*2)+','+Math.round(y*2);if(L.nk[k]!=null)return L.nk[k];L.nodes.push({x,y,n:[]});return(L.nk[k]=L.nodes.length-1);};
 const link=(a,b)=>{if(a!==b&&L.nodes[a].n.indexOf(b)<0){L.nodes[a].n.push(b);L.nodes[b].n.push(a);}};
 const chain=ps=>{let p=null;ps.forEach(q=>{const i=typeof q==='number'?q:node(q[0],q[1]);if(p!=null)link(p,i);p=i;});return p;};
 const line=(h,c,a,b,rail)=>{const l={h,c,a,b};L.lines.push(l);if(rail)L.rails.push(l);};
 let gx,gy,W,H,dk;
 if(o==='h'){
  const dh=gridH-2*G,slim=nS>0&&(dh-22)/nS>=32,rows=Math.max(1,Math.floor((dh-22)/18)),cols=slim?1:Math.max(1,Math.ceil(nS/rows)),DW=slim?62:4+cols*66+12;
  gy=Math.max(6,EH-gridH/2);gx=6+DW;
  dk={x:6,y:gy+G,w:DW,h:dh,cols,slim,per:Math.max(1,Math.ceil(nS/cols))};
  W=gx+gridW-G/2+EX;H=2*gy+gridH;
 }else{
  const dw=gridW-2*G,cf=Math.max(1,Math.floor((dw-8)/46)),rows=Math.max(1,Math.ceil(nS/cf)),DH=16+rows*30+12;
  gx=Math.max(6,EH-gridW/2);gy=6+DH;
  dk={x:gx+G,y:6,w:dw,h:DH,rows,per:Math.max(1,Math.ceil(nS/rows))};
  W=2*gx+gridW;H=gy+gridH-G/2+EX;
 }
 Object.assign(L,{W,H,gx,gy,gridW,gridH,dock:dk});
 const hy=r=>gy+G/2+r*(RH+G),vx=c=>gx+G/2+c*(RW+G);
 L.hy=hy;L.vx=vx;
 for(let r=0;r<=R;r++)line(1,hy(r),vx(0),vx(C),1);
 for(let c=0;c<=C;c++)line(0,vx(c),hy(0),hy(R),1);
 for(let r=0;r<=R;r++)for(let c=0;c<=C;c++)node(vx(c),hy(r));
 for(let i=0;i<slots;i++){
  const c=i%C,r=(i/C)|0,x=gx+G+c*(RW+G),y=gy+G+r*(RH+G),T=D.teams[i];
  if(!T){L.empty.push({x,y,w:RW,h:RH});continue;}
  const ay=y+37,room={T,x,y,w:RW,h:RH,ay,seats:[],doors:[]};
  line(1,ay,x+6,x+RW-6);
  for(let k=0;k<K;k++){
   const s=T.an[k]||null,sx=x+14+k*20,seat={s,x:sx,mgr:0,room,k};
   room.seats.push(seat);
   if(s){seat.spot=node(sx,ay);L.seatBy[s.id]=seat;seat.hit={type:'person',id:s.id,x:sx-9,y:y+11,w:18,h:25,p:3};L.hits.push(seat.hit);}
  }
  const mx=x+23+20*K,ms={s:T.mgr,x:mx,mgr:1,room,k:K,spot:node(mx,ay)};
  room.seats.push(ms);room.mgr=ms;
  if(T.mgr){L.seatBy[T.mgr.id]=ms;ms.hit={type:'person',id:T.mgr.id,x:mx-15,y:y+10,w:30,h:27,p:3};L.hits.push(ms.hit);}
  [x+12,mx].forEach(dx=>{room.doors.push(dx);link(node(dx,ay),node(dx,y+RH+G/2));});
  L.rooms.push(room);L.roomBy[T.id]=room;
  room.hit={type:'room',id:T.id,x,y,w:RW,h:RH,p:1};L.hits.push(room.hit);
 }
 if(!slots)L.empty.push({x:gx+G,y:gy+G,w:RW,h:RH});
 dk.doors=[];
 if(o==='h'){
  const ax=dk.x+dk.w-9,p=Math.min(dk.slim?44:30,(dk.h-22)/dk.per);dk.ax=ax;
  line(0,ax,dk.y+8,dk.y+dk.h-8);
  D.sources.forEach((S,i)=>{
   const col=(i/dk.per)|0,row=i%dk.per,rx=dk.slim?dk.x+20:dk.x+4+(dk.cols-1-col)*66,ry=dk.y+16+p*(row+0.5)-(dk.slim?12:8);
   const rk=dk.slim?{S,x:rx,y:ry,lx:rx+6,ly:ry+21,lw:46,v:1}:{S,x:rx,y:ry,lx:rx+16,ly:ry+8,lw:46};
   rk.spot=node(ax,ry+8);rk.cab=[rx+12,ry+8,ax-4-rx-12];
   rk.hit=dk.slim?{type:'rack',id:S.id,x:dk.x+2,y:ry-2,w:48,h:28,p:3}:{type:'rack',id:S.id,x:rx-2,y:ry-2,w:64,h:20,p:3};
   L.racks.push(rk);L.rackBy[S.id]=rk;L.hits.push(rk.hit);
  });
  for(let r=0;r<R;r++){const y=gy+G+r*(RH+G)+RH/2;dk.doors.push(y);link(node(ax,y),node(vx(0),y));}
  dk.def=node(ax,dk.doors[0]||dk.y+20);
 }else{
  const ay=dk.y+dk.h-8,pX=Math.min(60,(dk.w-8)/dk.per);dk.ay=ay;
  line(1,ay,dk.x+8,dk.x+dk.w-8);
  D.sources.forEach((S,i)=>{
   const row=(i/dk.per)|0,col=i%dk.per,rx=dk.x+4+pX*(col+0.5)-6,ry=dk.y+16+row*30;
   const rk={S,x:rx,y:ry,lx:rx+6,ly:ry+21,lw:pX-3,spot:node(rx+6,ay),v:1};
   rk.hit={type:'rack',id:S.id,x:rx+6-pX/2,y:ry-2,w:pX,h:28,p:3};
   L.racks.push(rk);L.rackBy[S.id]=rk;L.hits.push(rk.hit);
  });
  for(let c=0;c<C;c++){const x=gx+G+c*(RW+G)+RW/2;dk.doors.push(x);link(node(x,ay),node(x,hy(0)));}
  dk.def=node(dk.doors[0]||dk.x+20,ay);
 }
 L.hits.push({type:'dock',id:'dock',x:dk.x,y:dk.y,w:dk.w,h:dk.h,p:1});
 /* executive end */
 const A0=o==='h'?gx+gridW-G/2:gy+gridH-G/2,B0=o==='h'?gy+gridH/2:gx+gridW/2;
 const Pt=(a,b)=>o==='h'?[A0+a,B0+b]:[B0+b,A0+a];
 const Rc=(a,b,la,lb)=>o==='h'?{x:A0+a,y:B0+b,w:la,h:lb}:{x:B0+b,y:A0+a,w:lb,h:la};
 const SD=o==='h'?{amin:'l',bmin:'t',bmax:'b'}:{amin:'t',bmin:'l',bmax:'r'};
 const door=(side,n)=>[side,side==='l'||side==='r'?n.y:n.x];
 const office=(I,cx,cy,hw,sy)=>{const n=L.nodes[I];return Math.abs(n.x-cx)>hw+3||n.y>cy+6?chain([I,[n.x,sy],[cx,sy]]):chain([I,[cx-hw-10,n.y],[cx-hw-10,sy],[cx,sy]]);};
 node(...Pt(0,0));
 const ca=G/2+6+30,cooR=Rc(G/2+6,-G/2-60,60,60),cin=node(...Pt(ca,-G/2-8));
 link(cin,node(...Pt(ca,0)));
 const ccx=cooR.x+cooR.w/2,ccy=cooR.y+36;
 L.coo={r:cooR,cx:ccx,cy:ccy,spot:office(cin,ccx,ccy,14,ccy+12),door:door(SD.bmax,L.nodes[cin])};
 let ceoR,ein,eside,hall;
 if(wide){
  const ea=G/2+6+60+14;ceoR=Rc(ea,-38,72,76);ein=node(...Pt(ea+8,0));link(ein,node(...Pt(ea-4,0)));eside=SD.amin;hall=ea-4;
  L.holo=Rc(G/2+14,G/2+8,48,40);
 }else{
  const ea=G/2+20,da=ea+38;ceoR=Rc(ea,G/2,76,76);ein=node(...Pt(da,G/2+8));link(ein,node(...Pt(da,0)));eside=SD.bmin;hall=da;
  L.holo=(o==='h'?gy+gridH/2:gx+gridW/2)>=121?Rc(G/2+12,-G/2-68-40,48,40):null;
 }
 line(o==='h'?1:0,B0,A0,A0+hall,1);
 const ex=ceoR.x+ceoR.w/2,ey=ceoR.y+40;
 L.ceo={r:ceoR,cx:ex,cy:ey,door:door(eside,L.nodes[ein]),spot:office(ein,ex,ey,19,ey+13)};
 L.hits.push({type:'coo',id:'coo',x:cooR.x,y:cooR.y,w:cooR.w,h:cooR.h,p:2},{type:'ceo',id:'ceo',x:ceoR.x,y:ceoR.y,w:ceoR.w,h:ceoR.h,p:2});
 /* connect every node that sits on a corridor / aisle line */
 L.lines.forEach(ln=>{
  const on=[];
  L.nodes.forEach((n,i)=>{const c=ln.h?n.y:n.x,v=ln.h?n.x:n.y;if(Math.abs(c-ln.c)<0.3&&v>=ln.a-0.3&&v<=ln.b+0.3)on.push([v,i]);});
  on.sort((a,b)=>a[0]-b[0]);
  for(let j=1;j<on.length;j++)link(on[j-1][1],on[j][1]);
 });
 return L;
}
function makeLayout(D,vw,vh,top,bot){
 const n=Math.max(1,D.teams.length);let K=4;
 D.teams.forEach(t=>{K=Math.max(K,t.an.length);});K=Math.min(K,12);
 const aw=Math.max(60,vw-12),ah=Math.max(60,vh-top-bot);let best=null;
 ['h','v'].forEach(o=>{
  for(let C=1;C<=n;C++){
   const R=Math.ceil(n/C);if(C>1&&Math.ceil(n/(C-1))===R)continue;
   ['w','c'].forEach(ev=>{const L=build(D,o,C,R,K,ev);L.fz=Math.min(aw/L.W,ah/L.H);if(!best||L.fz>best.fz*1.03)best=L;});
  }
 });
 return best;
}
function route(L,a,b){
 const key=a+'>'+b;if(L.rc[key])return L.rc[key];
 const N=L.nodes.length,d=new Float64Array(N).fill(Infinity),pv=new Int32Array(N).fill(-1),done=new Uint8Array(N);
 d[a]=0;
 for(;;){
  let u=-1,m=Infinity;
  for(let i=0;i<N;i++)if(!done[i]&&d[i]<m){m=d[i];u=i;}
  if(u<0||u===b)break;
  done[u]=1;const U=L.nodes[u];
  U.n.forEach(v=>{const V=L.nodes[v],w=Math.abs(U.x-V.x)+Math.abs(U.y-V.y)+0.01;if(d[u]+w<d[v]){d[v]=d[u]+w;pv[v]=u;}});
 }
 if(!isFinite(d[b]))return null;
 const p=[];for(let u=b;u>=0;u=pv[u])p.unshift(L.nodes[u]);
 return(L.rc[key]=p);
}

/* ---------- styles (namespaced) ---------- */
const CSS=`.flr-root{position:relative;width:100%;height:520px;overflow:hidden;background:${BG};border:1px solid ${LINE};border-radius:12px;box-sizing:border-box;font-family:${FONT};color:${FG};-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}
.flr-cv{display:block;width:100%;height:100%;cursor:grab;outline:none;touch-action:none}
.flr-cv:focus-visible{box-shadow:inset 0 0 0 2px rgba(45,227,165,.55)}.flr-cv.flr-hot{cursor:pointer}.flr-cv.flr-drag{cursor:grabbing}
.flr-ctl{position:absolute;right:8px;bottom:30px;display:flex;gap:4px;z-index:2}
.flr-btn{font:700 13px/1 ${FONT};min-width:30px;height:30px;padding:0 8px;border-radius:4px;border:1px solid rgba(45,227,165,.45);background:rgba(6,10,19,.85);color:${GREEN};cursor:pointer;box-shadow:0 0 10px rgba(45,227,165,.12)}
.flr-btn:hover{background:rgba(45,227,165,.15)}.flr-btn:focus-visible,.flr-x:focus-visible,.flr-li:focus-visible{outline:2px solid ${GREEN};outline-offset:1px}
.flr-panel{position:absolute;z-index:3;top:52px;right:8px;width:330px;max-width:calc(100% - 16px);max-height:calc(100% - 92px);overflow:auto;background:rgba(6,11,21,.96);border:1px solid ${LINE};border-top:2px solid ${GREEN};border-radius:6px;box-shadow:0 12px 40px rgba(0,0,0,.65),0 0 26px rgba(45,227,165,.12);font:12px/1.5 ${FONT};color:${FG};-webkit-user-select:text;user-select:text}
.flr-panel[hidden]{display:none}.flr-panel.flr-l{right:auto;left:8px}.flr-narrow .flr-panel{top:auto;bottom:28px;left:6px;right:6px;width:auto;max-width:none;max-height:58%}
.flr-ph{position:sticky;top:0;display:flex;align-items:center;gap:8px;padding:6px 6px 6px 10px;background:#0a1322;border-bottom:1px solid ${LINE};color:${GREEN};font-size:10.5px;letter-spacing:.08em}
.flr-ph span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.flr-ph span::after{content:'\\2588';margin-left:3px;animation:flrb 1s steps(1) infinite}
@keyframes flrb{50%{opacity:0}}
.flr-x{flex:none;width:28px;height:26px;border:1px solid ${LINE};border-radius:4px;background:#0c1424;color:${MUT};font:700 13px/1 ${FONT};cursor:pointer}.flr-x:hover{color:${FG};border-color:${RED}}
.flr-pb{padding:10px 12px 12px}.flr-h{font-size:15px;font-weight:700;margin:0 0 1px;letter-spacing:.02em}.flr-s{color:${MUT};font-size:11px;margin-bottom:6px}
.flr-kv{display:grid;grid-template-columns:70px 1fr;gap:3px 8px;margin:8px 0}.flr-kv>span{color:#5b7093;font-size:10px;letter-spacing:.08em;padding-top:2px}
.flr-up{color:${GREEN}}.flr-dn{color:${RED}}.flr-mu{color:${MUT}}.flr-tag{display:inline-block;font-size:10px;padding:0 5px;border:1px solid currentColor;border-radius:3px;margin-left:6px;vertical-align:2px}
.flr-sec{margin:10px 0 2px;color:#5b7093;font-size:10px;letter-spacing:.1em}
.flr-li{display:flex;width:100%;gap:6px;align-items:baseline;text-align:left;background:none;border:0;border-top:1px dashed ${LINE};color:inherit;font:inherit;padding:5px 2px;cursor:pointer}
div.flr-li{cursor:default}.flr-li:hover{background:rgba(45,227,165,.06)}div.flr-li:hover{background:none}.flr-li .flr-r{margin-left:auto;white-space:nowrap;font-size:11px}
.flr-dot{flex:none;display:inline-block;width:7px;height:7px;margin-right:2px;align-self:center}`;

/* ---------- component ---------- */
function mount(el,opts){
 opts=opts||{};
 const noop={update(){},setLive(){},destroy(){}};
 if(!el||typeof el.appendChild!=='function')return noop;
 const root=document.createElement('div');root.className='flr-root';
 root.innerHTML='<style>'+CSS+'</style><canvas class="flr-cv" role="img" tabindex="0" aria-label="Office floor"></canvas>'+
  '<div class="flr-ctl"><button type="button" class="flr-btn" data-z="-1" aria-label="Zoom out" title="Zoom out">−</button>'+
  '<button type="button" class="flr-btn" data-z="1" aria-label="Zoom in" title="Zoom in">+</button>'+
  '<button type="button" class="flr-btn" data-z="0" aria-label="Fit the whole floor" title="Fit the whole floor">FIT</button></div>'+
  '<div class="flr-panel" role="dialog" aria-label="Details" hidden><div class="flr-ph"><span></span><button type="button" class="flr-x" aria-label="Close details">✕</button></div><div class="flr-pb" aria-live="polite"></div></div>';
 el.appendChild(root);
 const cv=root.querySelector('canvas'),ctx=cv.getContext('2d');
 if(!ctx){root.remove();return noop;}
 const panel=root.querySelector('.flr-panel'),pT=panel.querySelector('.flr-ph span'),pB=panel.querySelector('.flr-pb');
 const RM=!!(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches);
 const cache=document.createElement('canvas'),over=document.createElement('canvas');
 const P={g:ctx,k:1,bx:0,by:0},LK=new Map(),TC=new Map();
 let D=norm(opts.data),L=null,sig=null,vw=0,vh=0,dpr=1,z=1,ox=0,oy=0,fitZ=1,zMin=0.3,zMax=8,moved=false;
 let narrow=false,hudT=48,hudB=24,live=!!opts.live,T=0,raf=0,last=0,vis=true,dead=false,cacheS=0,lastZoom=0;
 let walkers=[],queue=[],seen=new Set(),first=true,spawnT=0,idleT=1.2,bubbles=[],flashes=[],recv={},rackBusy={};
 let sel=null,hov=null,mouse=null,tween=null,tickX=0,tick={items:[],w:0},drag=null,pinch=null;
 const pts=new Map();

 /* pixel painter: world rect -> snapped device rect */
 function F(x,y,w,h,c){
  const k=P.k,X0=Math.round(x*k+P.bx),Y0=Math.round(y*k+P.by);
  let X1=Math.round((x+w)*k+P.bx),Y1=Math.round((y+h)*k+P.by);
  if(X1<=X0)X1=X0+1;if(Y1<=Y0)Y1=Y0+1;
  if(c)P.g.fillStyle=c;P.g.fillRect(X0,Y0,X1-X0,Y1-Y0);
 }
 function ring(x,y,w,h,c){F(x,y,w,1,c);F(x,y+h-1,w,1);F(x,y,1,h);F(x+w-1,y,1,h);}
 function pat(rows,x,y,map){
  for(let i=0;i<rows.length;i++){
   const r=rows[i];let j=0;
   while(j<r.length){const ch=r[j];if(ch==='.'){j++;continue;}let e=j;while(e<r.length&&r[e]===ch)e++;F(x+j,y+i,e-j,1,map[ch]||map['#']);j=e;}
  }
 }
 function glow(x,y,r,c,a){
  if(a<=0.01)return;const g=P.g,k=P.k,R=r*k;
  g.globalCompositeOperation='lighter';g.globalAlpha=a;g.imageSmoothingEnabled=true;
  g.drawImage(glowSpr(c),x*k+P.bx-R,y*k+P.by-R,2*R,2*R);
  g.globalCompositeOperation='source-over';g.globalAlpha=1;g.imageSmoothingEnabled=false;
 }
 function look(id,col,kind){
  const key=id+col;let l=LK.get(key);if(l)return l;
  const h=hsh(id);
  l=kind==='bot'?{bot:1,body:'#56688a',hi:'#7488ad',dk:'#3b4a66',hair:'#9fb3d1',skin:'#9fb3d1'}
   :{body:col,hi:mix(col,'#ffffff',0.35),dk:mix(col,'#000000',0.4),hair:HAIR[h%HAIR.length],skin:SKIN[(h>>>4)%SKIN.length]};
  LK.set(key,l);return l;
 }
 const lookOf=id=>{
  if(id.slice(0,4)==='src:')return look('bot','','bot');
  if(id==='coo')return look('coo',CYAN);if(id==='ceo')return look('ceo',GOLD);
  const s=D.staff[id];return s?look(s.id,s.team.color):look(id,MUT);
 };

 /* ---------- static layer (floor, walls, desks) ---------- */
 function shell(r,col,doors,glass){
  const{x,y,w,h}=r;
  [0.05,0.1,0.2].forEach((a,i)=>ring(x-3+i,y-3+i,w+6-2*i,h+6-2*i,rgba(col,a)));
  const g=P.g;g.save();g.shadowColor=rgba(col,0.9);g.shadowBlur=Math.max(4,7*P.k);g.globalAlpha=glass?0.35:0.55;ring(x,y,w,h,col);g.restore();
  F(x,y,w,h,mix('#0a1222',col,0.05));
  for(let gx=x+8;gx<x+w-2;gx+=8)F(gx,y+2,0.01,h-4,rgba(col,0.06));
  for(let gy=y+8;gy<y+h-2;gy+=8)F(x+2,gy,w-4,0.01,rgba(col,0.06));
  ring(x,y,w,h,glass?'rgba(170,236,255,.75)':col);
  ring(x+1,y+1,w-2,h-2,glass?rgba(col,0.25):mix(col,'#000000',0.55));
  const cc=mix(col,'#ffffff',0.55);F(x,y,2,2,cc);F(x+w-2,y,2,2);F(x,y+h-2,2,2);F(x+w-2,y+h-2,2,2);
  if(glass)for(let i=x+8;i<x+w-6;i+=14){F(i,y+3,1,1,'rgba(255,255,255,.35)');F(i+1,y+4,1,1);F(i+2,y+5,1,1);}
  doors.forEach(([side,p])=>{
   const fl='#0a1424',pc=mix(col,'#ffffff',0.3);
   if(side==='b'||side==='t'){
    const yy=side==='b'?y+h-2:y;F(p-5,yy,10,2,fl);F(p-6,yy-1,1,4,pc);F(p+5,yy-1,1,4);
    for(let i=-4;i<4;i+=2)F(p+i,yy+(side==='b'?1:0),1,1,rgba(col,0.7));
   }else{
    const xx=side==='r'?x+w-2:x;F(xx,p-5,2,10,fl);F(xx-1,p-6,4,1,pc);F(xx-1,p+5,4,1);
    for(let i=-4;i<4;i+=2)F(xx+(side==='r'?1:0),p+i,1,1,rgba(col,0.7));
   }
  });
 }
 function header(r,col){F(r.x+2,r.y+2,r.w-4,10,rgba(col,0.1));F(r.x+2,r.y+12,r.w-4,0.01,rgba(col,0.35));F(r.x+2,r.y+2,2,10,col);}
 function plant(x,y){pat(SPR.plant,x-2,y,{g:'#1d8a58',G:'#2fc983',p:'#4a3326'});}
 function paintStatic(){
  const W=L.W,H=L.H,G=L.G,th=0.01;
  F(0,0,W,H,'#070c17');
  P.g.fillStyle='#09101d';for(let y=0;y<H;y+=8)for(let x=((y>>3)&1)*8;x<W;x+=16)F(x,y,8,8);
  for(let x=0;x<=W;x+=8)F(x,0,th,H,x%32?'rgba(79,140,255,.05)':'rgba(79,140,255,.1)');
  for(let y=0;y<=H;y+=8)F(0,y,W,th,y%32?'rgba(79,140,255,.05)':'rgba(79,140,255,.1)');
  P.g.fillStyle='rgba(41,211,238,.16)';for(let y=32;y<H;y+=32)for(let x=32;x<W;x+=32){F(x-1,y,3,th);F(x,y-1,th,3);}
  L.rails.forEach(r=>{const n=r.b-r.a;if(r.h)F(r.a-G/2,r.c-G/2,n+G,G,'#0a1424');else F(r.c-G/2,r.a-G/2,G,n+G,'#0a1424');});
  L.rails.forEach(r=>{
   const n=r.b-r.a;
   [-4,4].forEach(o=>{
    if(r.h){F(r.a,r.c+o-1,n,3,'rgba(41,211,238,.07)');F(r.a,r.c+o,n,1,'rgba(41,211,238,.34)');}
    else{F(r.c+o-1,r.a,3,n,'rgba(41,211,238,.07)');F(r.c+o,r.a,1,n,'rgba(41,211,238,.34)');}
   });
  });
  for(let r=0;r<=L.R;r++)for(let c=0;c<=L.C;c++){
   const x=L.vx(c),y=L.hy(r);F(x-5,y-5,10,10,'#0c1a33');ring(x-5,y-5,10,10,'rgba(41,211,238,.45)');F(x-1,y-1,2,2,CYAN);
  }
  L.empty.forEach(e=>{
   P.g.fillStyle='rgba(142,163,196,.22)';
   for(let i=0;i<e.w;i+=6){F(e.x+i,e.y,3,1);F(e.x+i,e.y+e.h-1,3,1);}
   for(let i=0;i<e.h;i+=6){F(e.x,e.y+i,1,3);F(e.x+e.w-1,e.y+i,1,3);}
   plant(e.x+12,e.y+8);plant(e.x+e.w-12,e.y+e.h-14);
  });
  L.rooms.forEach(rm=>{
   const col=rm.T.color,y0=rm.y;
   shell(rm,col,rm.doors.map(d=>['b',d]));header(rm,col);
   let pl=0;
   rm.seats.forEach(se=>{
    const x=se.x;
    if(se.mgr){
     F(x-15,y0+12,30,10,'#1a2336');F(x-15,y0+12,30,1,'#2a3852');F(x-15,y0+21,30,1,rgba(GOLD,0.6));
     [x-14,x+2].forEach(mx=>{F(mx,y0+10,12,7,'#080d16');F(mx,y0+10,12,1,'#33446a');F(mx+5,y0+17,2,1,'#2b3a57');});
     F(x-4,y0+19,8,2,'#243049');pat(SPR.star,x-2,y0+12,{'#':GOLD});
     F(x-5,y0+26,10,5,'#232e46');F(x-5,y0+26,10,1,'#34446a');F(x-1,y0+31,2,1,'#111827');F(x-4,y0+32,8,1,'#111827');
    }else if(se.s){
     F(x-8,y0+13,16,8,'#172133');F(x-8,y0+13,16,1,'#25324a');F(x-8,y0+20,16,1,'#0f1624');
     F(x-6,y0+11,12,7,'#080d16');F(x-6,y0+11,12,1,'#2b3a57');F(x-1,y0+18,2,1,'#2b3a57');
     F(x-4,y0+19,8,2,'#243049');
     F(x-4,y0+25,8,4,'#1b2539');F(x-4,y0+25,8,1,'#2a3753');F(x-1,y0+29,2,1,'#111827');F(x-3,y0+30,6,1,'#111827');
    }else if(pl++%3===0)plant(x,y0+18);
   });
  });
  const dk=L.dock;
  shell(dk,BLUE,dk.doors.map(p=>[L.o==='h'?'r':'b',p]));header(dk,BLUE);
  if(L.o==='h')F(dk.ax-5,dk.y+14,10,dk.h-18,rgba(BLUE,0.05));else F(dk.x+4,dk.ay-5,dk.w-8,10,rgba(BLUE,0.05));
  L.racks.forEach(rk=>{
   F(rk.x+1,rk.y+1,12,16,'rgba(0,0,0,.5)');F(rk.x,rk.y,12,16,'#0d1626');ring(rk.x,rk.y,12,16,'#2c3d62');
   for(let b=0;b<4;b++)F(rk.x+1,rk.y+4+b*3,10,2,'#142039');
   if(rk.cab){F(rk.cab[0],rk.cab[1],rk.cab[2],1,'rgba(41,211,238,.3)');F(rk.cab[0],rk.cab[1]-1,rk.cab[2],3,'rgba(41,211,238,.06)');}
  });
  const co=L.coo,cr=co.r,cx=co.cx,cy=co.cy;
  shell(cr,CYAN,[co.door],1);header(cr,CYAN);
  F(cx-5,cy-16,10,9,'#1d283d');F(cx-5,cy-16,10,1,'#2d3b58');
  F(cx-14,cy-4,28,8,'#182234');F(cx-14,cy-4,28,1,'#2a3852');F(cx-14,cy+3,28,1,rgba(CYAN,0.55));
  F(cx-13,cy-7,7,4,'#0e1524');F(cx+6,cy-7,7,4,'#0e1524');
  plant(cr.x+cr.w-9,cr.y+cr.h-10);
  const ce=L.ceo,er=ce.r,ex=ce.cx,ey=ce.cy;
  shell(er,GOLD,[ce.door]);header(er,GOLD);
  F(ex-26,ey-22,52,41,rgba(GOLD,0.04));ring(ex-26,ey-22,52,41,rgba(GOLD,0.16));ring(ex-24,ey-20,48,37,rgba(VIOLET,0.12));
  const sx=er.x+er.w-34,sy=er.y+3;F(sx,sy,28,10,'#070b14');ring(sx,sy,28,10,rgba(GOLD,0.55));
  F(ex-6,ey-18,12,11,'#2a2030');F(ex-6,ey-18,12,1,'#3d2f45');F(ex-7,ey-15,1,6,'#2a2030');F(ex+6,ey-15,1,6);
  F(ex-19,ey-4,38,9,'#1e2132');F(ex-19,ey-4,38,1,'#30364d');F(ex-19,ey+4,38,1,rgba(GOLD,0.75));
  F(ex-17,ey-7,8,4,'#0e1524');F(ex+7,ey-7,8,4,'#0e1524');F(ex+14,ey-1,4,3,'#0b0f18');
  plant(er.x+7,er.y+er.h-11);plant(er.x+er.w-9,er.y+er.h-11);
  const ho=L.holo;if(!ho)return;const hx=ho.x+ho.w/2,hy=ho.y+ho.h/2;
  F(ho.x,ho.y,ho.w,ho.h,'#0a1120');ring(ho.x,ho.y,ho.w,ho.h,rgba(VIOLET,0.5));ring(ho.x+2,ho.y+2,ho.w-4,ho.h-4,rgba(CYAN,0.18));
  F(hx-12,hy-3,24,12,'#0d1830');ring(hx-12,hy-3,24,12,rgba(CYAN,0.5));
 }
 function renderStatic(){
  if(!L)return;
  const s=Math.max(0.25,Math.min(z*dpr,Math.sqrt(7e6/(L.W*L.H)),8000/L.W,8000/L.H));
  cache.width=Math.max(1,Math.ceil(L.W*s));cache.height=Math.max(1,Math.ceil(L.H*s));cacheS=s;
  const g=cache.getContext('2d');g.imageSmoothingEnabled=false;
  P.g=g;P.k=s;P.bx=0;P.by=0;paintStatic();P.g=ctx;
 }
 function buildOver(){
  over.width=cv.width;over.height=cv.height;
  const g=over.getContext('2d'),W=over.width,H=over.height;
  g.fillStyle='rgba(0,0,0,.17)';const st=Math.max(3,Math.round(3*dpr)),th=Math.max(1,Math.round(dpr));
  for(let y=0;y<H;y+=st)g.fillRect(0,y,W,th);
  const gr=g.createRadialGradient(W/2,H/2,Math.min(W,H)*0.32,W/2,H/2,Math.hypot(W,H)*0.62);
  gr.addColorStop(0,'rgba(0,0,0,0)');gr.addColorStop(1,'rgba(0,0,0,.5)');g.fillStyle=gr;g.fillRect(0,0,W,H);
 }

 /* ---------- view ---------- */
 function fitView(anim){
  if(!L)return;
  const aw=vw-12,ah=vh-hudT-hudB;let nz=Math.min(aw/L.W,ah/L.H);
  const k=Math.floor(nz*dpr);if(k>=2&&k/dpr>=nz*0.92)nz=k/dpr;
  const nox=(vw-L.W*nz)/2,noy=hudT+(ah-L.H*nz)/2;
  fitZ=nz;zMin=nz*0.7;zMax=Math.max(nz*5,6);
  if(anim)tween={z0:z,x0:ox,y0:oy,z1:nz,x1:nox,y1:noy,t:0};else{z=nz;ox=nox;oy=noy;}
  moved=false;touchMode();
 }
 function clampView(){const W=L.W*z,H=L.H*z;ox=clamp(ox,vw*0.3-W,vw*0.7);oy=clamp(oy,vh*0.3-H,vh*0.7);}
 function zoomAt(px,py,f){
  if(!L)return;tween=null;
  const nz=clamp(z*f,zMin,zMax),wx=(px-ox)/z,wy=(py-oy)/z;
  z=nz;ox=px-wx*z;oy=py-wy*z;clampView();moved=true;lastZoom=T;touchMode();TC.clear();kick();
 }
 function zoomBy(f){
  if(!L)return;const bz=tween?tween.z1:z,bx=tween?tween.x1:ox,by=tween?tween.y1:oy;
  const nz=clamp(bz*f,zMin,zMax),cx=vw/2,cy=vh/2,wx=(cx-bx)/bz,wy=(cy-by)/bz;
  tween={z0:z,x0:ox,y0:oy,z1:nz,x1:cx-wx*nz,y1:cy-wy*nz,t:0};moved=true;kick();
 }
 function touchMode(){cv.style.touchAction=z<=fitZ*1.02?'pan-y':'none';}
 function computeH(){
  if(opts.height){const h=typeof opts.height==='function'?opts.height():opts.height;if(+h>0)return+h;}
  const ih=window.innerHeight||800,iw=window.innerWidth||1200;
  if(ih<500)return Math.max(220,ih-40);
  if(iw<700)return Math.round(ih*0.7);
  return Math.round(Math.min(ih*0.78,760));
 }
 function relayout(force){
  if(dead)return;
  const w=root.clientWidth,h=root.clientHeight;
  if(w<40||h<40)return;
  const nd=Math.min(2,window.devicePixelRatio||1);
  if(!force&&w===vw&&h===vh&&nd===dpr&&L)return;
  let keep=null;if(L&&moved)keep={cx:(vw/2-ox)/z,cy:(vh/2-oy)/z,zr:z/fitZ};
  vw=w;vh=h;dpr=nd;cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);
  narrow=w<600;root.classList.toggle('flr-narrow',narrow);hudT=h<420||w<600?40:50;hudB=24;
  const nl=makeLayout(D,w,h,hudT,hudB),same=L&&nl.o===L.o&&nl.C===L.C&&sig===L.sig;
  nl.sig=sig;
  if(!same){walkers=[];bubbles=[];flashes=[];}
  else nl.rc=L.rc;
  L=nl;fitView(false);
  if(same&&keep){z=clamp(fitZ*keep.zr,zMin,zMax);ox=w/2-keep.cx*z;oy=h/2-keep.cy*z;clampView();moved=true;touchMode();}
  renderStatic();buildOver();TC.clear();buildTicker();kick();
 }

 /* ---------- couriers ---------- */
 const keyOf=f=>f.t+'|'+f.from+'|'+f.to+'|'+f.kind;
 function ep(id){
  if(!L)return-1;
  if(id.slice(0,4)==='src:'){const r=L.rackBy[id.slice(4)];return r?r.spot:L.dock.def;}
  if(id==='coo')return L.coo.spot;if(id==='ceo')return L.ceo.spot;
  const s=L.seatBy[id];if(s&&s.spot!=null)return s.spot;
  const rm=L.roomBy[id];return rm?rm.mgr.spot:-1;
 }
 function nameOf(id){
  if(id.slice(0,4)==='src:'){const s=D.sources.find(x=>x.id===id.slice(4));return s?s.name:id.slice(4);}
  if(id==='coo')return str(D.coo.name)||'COO';if(id==='ceo')return str(D.ceo.name)||'CEO';
  const s=D.staff[id];if(s)return(s.name||s.role||id)+' ('+s.team.name+')';
  const t=D.teams.find(x=>x.id===id);return t?t.name:id;
 }
 function spawn(f,fresh){
  if(!L||!f||walkers.length>=30)return;
  const a=ep(f.from),b=ep(f.to),col=KIND[f.kind]||FG;if(a<0||b<0)return;
  if(f.from.slice(0,4)==='src:')rackBusy[f.from.slice(4)]=T;
  if(a===b){const n=L.nodes[b];flashes.push({x:n.x,y:n.y,c:col,t:T});recv[f.to]=T;if(fresh)bub(f,n,col);return;}
  const pth=route(L,a,b);if(!pth||pth.length<2)return;
  const lens=[];let tot=0;for(let i=1;i<pth.length;i++){const l=Math.abs(pth[i].x-pth[i-1].x)+Math.abs(pth[i].y-pth[i-1].y);lens.push(l);tot+=l;}
  walkers.push({f,pth,lens,seg:0,d:0,dist:0,v:clamp(tot/9,30,68)*(0.9+Math.random()*0.2),col,lk:lookOf(f.from),t0:T,done:0,
   lane:(Math.random()*5-2.5),fresh,px:pth[0].x,py:pth[0].y,dir:'d',tr:[],lt:0});
 }
 function bub(f,n,col){
  let t=f.text.replace(/^\(fixture\)\s*/i,'')||f.kind;if(t.length>30)t=t.slice(0,29)+'…';
  bubbles.push({x:n.x,y:n.y,s:t,c:col,t:T});if(bubbles.length>3)bubbles.shift();
 }
 function stepWalkers(dt){
  for(let i=walkers.length-1;i>=0;i--){
   const w=walkers[i];
   if(w.done){if(T-w.done>0.4)walkers.splice(i,1);continue;}
   w.d+=w.v*dt;w.dist+=w.v*dt;
   while(w.seg<w.lens.length&&w.d>=w.lens[w.seg]){w.d-=w.lens[w.seg];w.seg++;}
   if(w.seg>=w.lens.length){
    const n=w.pth[w.pth.length-1];w.px=n.x;w.py=n.y;w.done=T;
    flashes.push({x:n.x,y:n.y,c:w.col,t:T});recv[w.f.to]=T;
    if(w.fresh||Math.random()<0.2)bub(w.f,n,w.col);
    continue;
   }
   const a=w.pth[w.seg],b=w.pth[w.seg+1],l=w.lens[w.seg]||1,q=w.d/l,dx=b.x-a.x,dy=b.y-a.y;
   w.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?'r':'l'):(dy>0?'d':'u');
   w.px=a.x+dx*q+(dx?0:w.lane);w.py=a.y+dy*q+(dy?0:w.lane*0.6);
   if(w.dist-w.lt>2.5){w.tr.unshift(w.px,w.py);if(w.tr.length>12)w.tr.length=12;w.lt=w.dist;}
  }
  for(let i=flashes.length-1;i>=0;i--)if(T-flashes[i].t>0.7)flashes.splice(i,1);
  for(let i=bubbles.length-1;i>=0;i--)if(T-bubbles[i].t>3.4)bubbles.splice(i,1);
 }
 function ingest(){
  const fresh=[];
  D.flows.forEach(f=>{const k=keyOf(f);if(!seen.has(k)){seen.add(k);fresh.push(f);}});
  if(first&&D.flows.length){first=false;queue=fresh.slice(-5).map(f=>({f,n:1}));}
  else{fresh.forEach(f=>queue.push({f,n:1}));if(queue.length>40)queue=queue.slice(-40);}
  if(seen.size>5000)seen=new Set(D.flows.map(keyOf));
 }
 function step(dt){
  T+=dt;
  if(tween){
   tween.t=Math.min(1,tween.t+dt/0.28);const e=1-Math.pow(1-tween.t,3);
   z=tween.z0+(tween.z1-tween.z0)*e;ox=tween.x0+(tween.x1-tween.x0)*e;oy=tween.y0+(tween.y1-tween.y0)*e;
   lastZoom=T;if(tween.t>=1){tween=null;clampView();touchMode();TC.clear();}
  }
  spawnT-=dt;
  if(queue.length){if(spawnT<=0&&walkers.length<30){const q=queue.shift();spawn(q.f,q.n);spawnT=0.45;idleT=2.2;}}
  else if(D.flows.length&&!RM){
   idleT-=dt;
   if(idleT<=0){if(walkers.length<(narrow?7:11)){const pool=D.flows.slice(-60);spawn(pool[(Math.random()*pool.length)|0],0);}idleT=1.1+Math.random()*1.7;}
  }
  stepWalkers(dt);
  if(cacheS&&Math.abs(cacheS-Math.min(z*dpr,Math.sqrt(7e6/(L.W*L.H)),8000/L.W,8000/L.H))>0.002&&T-lastZoom>0.18&&!pinch)renderStatic();
 }

 /* ---------- dynamic world ---------- */
 function scr(x,y,st,kind,seed,col,up,fl){
  const w=10,h=5,t=T;
  if(st==='vacant'){F(x,y,w,h,'#03060b');return;}
  if(st==='idle'){F(x,y,w,h,'#081222');if(((t*0.9+seed)|0)%2===0)F(x+1,y+3,1,1,'#2b4a72');}
  else if(st==='alert'){
   const on=((t*2.6+seed*0.1)|0)%2===0;F(x,y,w,h,on?'#4a0c18':'#200810');
   F(x+4,y,2,3,on?'#ffd0d6':RED);F(x+4,y+4,2,1);glow(x+5,y+2.5,10,RED,on?0.5:0.15);
  }else if(st==='holding'||kind==='chart'){
   F(x,y,w,h,'#05141c');F(x,y+4,w,1,'#0b2733');const c=up?GREEN:RED;
   for(let i=0;i<w;i++){const v=Math.sin((i+seed+t*1.6)*0.8)*1.3+(up?-i:i)*0.12;F(x+i,y+clamp(Math.round(2+v),0,3),1,1,c);}
   glow(x+5,y+2.5,9,c,0.2);
  }else{
   F(x,y,w,h,'#061a26');const s=seed,k=kind;
   if(k==='quant'){for(let i=0;i<5;i++){const hh=1+((h2(s+i,(t*3)|0)*4)|0);F(x+1+i*2,y+h-hh,1,hh,i%2?col:'#9ff0ff');}}
   else if(k==='backtest'){const p=(t*0.22+s*0.013)%1,n=Math.max(1,(p*w)|0);for(let i=0;i<n;i++)F(x+i,y+clamp(3-((i*0.3+Math.sin(i*1.7+s)*0.7)|0),0,3),1,1,GREEN);F(x,y+4,n,1,AMBER);}
   else if(k==='audit'){const hl=((t*1.5)|0)%2;for(let r=0;r<2;r++){F(x+1,y+1+r*2,1,1,GREEN);F(x+3,y+1+r*2,3+((h2(s,r+((t*0.7)|0))*4)|0),1,r===hl?'#e8f6ff':'#4d6a8c');}}
   else if(k==='data'){for(let i=0;i<5;i++){const yy=((t*7+h2(s,i)*9)%(h+3))-1|0;F(x+1+i*2,y+clamp(yy,0,4),1,1,'#b5fbff');if(yy>0&&yy<6)F(x+1+i*2,y+clamp(yy-1,0,4),1,1,'#138597');}}
   else if(k==='trader'){for(let i=0;i<4;i++){const r=h2(s+i,((t*1.2)|0)+i),u=r>0.45,bh=1+((r*3)|0),by=1+((h2(s,i+((t*1.2)|0))*(4-bh))|0);F(x+1+i*2.5,y+by-1,1,bh+2,u?'#1d6b52':'#7a2a38');F(x+1+i*2.5,y+by,1,bh,u?GREEN:RED);}}
   else{
    const sc=(t*2.2)|0,cl=k==='implement'?[VIOLET,GREEN,AMBER]:['#d7f1ff',col,'#7fb3d9'];
    for(let r=0;r<2;r++){const ind=k==='implement'?((h2(s,r+sc)*3)|0):0;F(x+1+ind,y+1+r*2,2+((h2(s+7,r+sc)*6)|0),1,cl[(r+sc)%3]);}
    const tl=1+(((t*6)|0)%7);F(x+1,y+4-0,0.01,0.01);if((t*3|0)%2)F(x+1+tl,y+3,1,1,GREEN);
   }
   glow(x+5,y+2.5,10,col,0.32);
  }
  if(fl){F(x,y,w,h,'rgba(255,255,255,.45)');glow(x+5,y+2.5,12,'#ffffff',0.4);}
 }
 function back(x,top,lk,typing){
  const a=typing?((T*7+x*0.37)|0)&1:0;
  F(x-4,top+3,1,4,lk.dk);F(x+3,top+3,1,4);
  F(x-4,top+2-a,1,1,lk.skin);F(x+3,top+1+a,1,1);
  F(x-3,top+4,6,4,lk.body);F(x-3,top+4,6,1,lk.hi);
  F(x-2,top,4,4,lk.hair);F(x-3,top+2,1,1,lk.skin);F(x+2,top+2,1,1);
 }
 function front(x,top,lk){
  F(x-3,top+4,6,4,lk.body);F(x-3,top+4,6,1,lk.hi);F(x-4,top+5,1,3,lk.dk);F(x+3,top+5,1,3);
  F(x-3,top+8,1,1,lk.skin);F(x+3,top+8,1,1);
  F(x-2,top,4,4,lk.skin);F(x-2,top,4,1,lk.hair);F(x-3,top,1,3);F(x+2,top,1,3);
  if(((T*0.6+x*0.13)%4)>0.15){F(x-1,top+2,1,1,'#14161c');F(x+1,top+2,1,1);}
 }
 function drawSeat(se,rm){
  const s=se.s,Tm=rm.T,x=se.x,y0=rm.y;
  if(!s&&!se.mgr)return;
  const st=s?s.status:'vacant',pz=Tm.paused&&st!=='vacant',show=pz?'idle':st;
  const seed=s?hsh(s.id)%997:se.k*31,up=s?num(s.rec.pnl_rs!=null?s.rec.pnl_rs:s.rec.pnl)>=0:true;
  const fl=s&&recv[s.id]&&T-recv[s.id]<0.5,kind=s?s.kind:'trader';
  if(se.mgr){scr(x-13,y0+11,show,kind==='research'?'trader':kind,seed,Tm.color,up,fl);scr(x+3,y0+11,show,show==='active'?'chart':kind,seed+5,Tm.color,up,fl);}
  else scr(x-5,y0+12,show,kind,seed,Tm.color,up,fl);
  if(st==='vacant')return;
  const top=y0+(se.mgr?20:19)+(show==='idle'?1:0);
  back(x,top,look(s.id,Tm.color),show==='active');
  const iy=y0+(se.mgr?17:14)+(((T*2+seed)|0)%2);
  if(!pz&&st==='holding'){pat(SPR.ring,x+5,iy,{'#':AMBER});F(x+6,iy+1,3,3,'#2a1a04');F(x+7,iy+2,1,1,'#fff');const q=((T*1.5)|0)%4;F(x+7+(q===1)-(q===3),iy+2-(q===0)+(q===2),1,1,AMBER);}
  if(!pz&&st==='alert'&&((T*2.5)|0)%2===0){F(x+5,iy-1,4,7,'#2a0610');F(x+6,iy,2,3,RED);F(x+6,iy+4,2,1);glow(x+7,iy+2,7,RED,0.55);}
  if(se.mgr)pat(SPR.star,x-2,y0+33,{'#':GOLD});
  else if(/senior/i.test(s.des)){F(x-3,y0+32,2,2,'#d6ecff');F(x+1,y0+32,2,2);}
  else F(x-1,y0+32,2,2,'#9fb6d6');
 }
 function drawWalker(w){
  const lk=w.lk,x=w.px,fy=w.py+5,ph=((w.dist/3)|0)&1,d=w.dir,g=P.g;
  const al=w.done?Math.max(0,1-(T-w.done)/0.4):Math.min(1,(T-w.t0)/0.3);if(al<=0)return;
  g.globalAlpha=al;
  F(x-3,fy,6,1,'rgba(0,0,0,.45)');
  const pants=lk.bot?'#3b4a66':'#1a2233';
  F(x-2,fy-3,2,ph?3:2,pants);F(x,fy-3,2,ph?2:3);
  F(x-3,fy-7,6,4,lk.body);F(x-3,fy-7,6,1,lk.hi);
  F(x-4,fy-7+ph,1,3,lk.dk);F(x+3,fy-6-ph,1,3);
  if(lk.bot){F(x-2,fy-11,4,4,lk.hair);F(x-2,fy-9,4,1,CYAN);F(x,fy-13,1,2,lk.hair);}
  else{
   F(x-2,fy-11,4,4,d==='u'?lk.hair:lk.skin);F(x-2,fy-11,4,1,lk.hair);
   if(d==='d'){F(x-1,fy-9,1,1,'#14161c');F(x+1,fy-9,1,1);}
   else if(d==='l'){F(x,fy-10,2,2,lk.hair);F(x-2,fy-9,1,1,'#14161c');}
   else if(d==='r'){F(x-2,fy-10,2,2,lk.hair);F(x+1,fy-9,1,1,'#14161c');}
  }
  for(let i=2;i<w.tr.length;i+=2){g.globalAlpha=al*(0.75-i*0.06);F(w.tr[i]-0.5,w.tr[i+1]-10.5,i<6?2:1,i<6?2:1,w.col);}
  g.globalAlpha=al;
  const py=fy-17-(((w.dist/6)|0)&1);
  F(x-1.5,py,3,3,w.col);F(x-0.5,py+1,1,1,'#ffffff');
  g.globalAlpha=1;glow(x,py+1.5,7,w.col,0.8*al);
 }
 function drawWorld(){
  const k=z*dpr;P.g=ctx;P.k=k;P.bx=Math.round(ox*dpr);P.by=Math.round(oy*dpr);
  const x0=-ox/z-24,y0=-oy/z-24,x1=(vw-ox)/z+24,y1=(vh-oy)/z+24;
  const vis=(x,y,w,h)=>x+w>x0&&x<x1&&y+h>y0&&y<y1;
  if(!RM)L.rails.forEach((r,i)=>{
   const n=r.b-r.a,m=Math.max(1,Math.round(n/110));
   for(let j=0;j<m;j++)[-4,4].forEach((o,s)=>{
    let p=(T*(26+(i%3)*7)+(j+s*0.5)*n/m)%n;if(s)p=n-p;
    const x=r.h?r.a+p:r.c+o,y=r.h?r.c+o:r.a+p;if(!vis(x-4,y-4,8,8))return;
    F(r.h?x-2:x,r.h?y:y-2,r.h?4:1,r.h?1:4,'#c8faff');glow(x,y,5,CYAN,0.45);
   });
  });
  L.rooms.forEach(rm=>{if(vis(rm.x,rm.y,rm.w,rm.h))rm.seats.forEach(se=>drawSeat(se,rm));});
  L.racks.forEach((rk,i)=>{
   if(!vis(rk.x,rk.y,64,30))return;
   const st=rk.S.status,col=SRCC[st]||'#6b7a96',busy=rackBusy[rk.S.id]!=null&&T-rackBusy[rk.S.id]<1.6;
   const on=st==='warn'?((T*2)|0)%2:st==='off'?((T*0.8)|0)%2:1;
   F(rk.x+1,rk.y+1,4,2,on?col:mix(col,'#000000',0.6));glow(rk.x+3,rk.y+2,8,col,on?0.6:0.12);
   for(let b=0;b<4;b++)for(let j=0;j<3;j++){
    const lit=st!=='off'&&h2(i*16+b*4+j,(T*(busy?14:3.5))|0)>(st==='ok'?0.42:0.72);
    F(rk.x+2+j*3,rk.y+4+b*3,2,1,lit?(j===2?CYAN:st==='ok'?GREEN:AMBER):'#0f2230');
   }
   if(busy)glow(rk.x+6,rk.y+9,12,CYAN,0.25);
  });
  const co=L.coo,cx=co.cx,cy=co.cy;
  if(vis(co.r.x,co.r.y,co.r.w,co.r.h)){
   front(cx,cy-14,look('coo',CYAN));
   pat(SPR.dia,cx-2,cy-21-(((T*1.5)|0)%2),{'#':CYAN});glow(cx+0.5,cy-18.5,6,CYAN,0.5);
   const fl=recv.coo&&T-recv.coo<0.5;
   [[cx-13,cy-13],[cx+6,cy-13]].forEach((p,i)=>{const a=0.35+0.15*Math.sin(T*3+i);F(p[0],p[1],7,5,rgba(CYAN,fl?0.7:a*0.5));F(p[0]+1,p[1]+1+(((T*2+i)|0)%3),5,1,rgba('#d8fbff',0.8));glow(p[0]+3.5,p[1]+2.5,8,CYAN,0.25);});
   F(cx-10,cy-6,1,1,((T*2)|0)%2?GREEN:'#0c3a2c');F(cx+9,cy-6,1,1,((T*2+1)|0)%2?GREEN:'#0c3a2c');
   arr(D.coo.notes).slice(0,6).forEach((n,i)=>F(co.r.x+4+i*4,co.r.y+co.r.h-6,3,3,n&&/err|bad|crit/i.test(str(n.level))?RED:n&&/warn/i.test(str(n.level))?AMBER:CYAN));
  }
  const ce=L.ceo,ex=ce.cx,ey=ce.cy,pu=0.5+0.5*Math.sin(T*3.2);
  if(vis(ce.r.x,ce.r.y,ce.r.w,ce.r.h)){
   if(live){glow(ex,ey-4,34,GREEN,0.07+0.05*pu);front(ex,ey-15,look('ceo',GOLD));}
   F(ex+15,ey-3,3,3,live?mix(GREEN,'#ffffff',pu*0.5):'#3a4558');if(live)glow(ex+16.5,ey-1.5,9+5*pu,GREEN,0.45+0.35*pu);
   [[ex-17,ey-7],[ex+7,ey-7]].forEach(p=>F(p[0]+3,p[1]+1,2,1,live?CYAN:'#24324a'));
   const sx=ce.r.x+ce.r.w-33,sy=ce.r.y+4,up=num(D.pnl.today_rs)>=0;
   F(sx,sy,26,8,up?'#06231b':'#2a0a12');
   for(let i=0;i<26;i+=2)F(sx+i,sy+7,1,1,rgba(up?GREEN:RED,0.5));
   glow(sx+13,sy+4,16,up?GREEN:RED,0.22);
  }
  const ho=L.holo,hx=ho?ho.x+ho.w/2:0,hy=ho?ho.y+ho.h/2:0;
  if(ho&&vis(ho.x,ho.y,ho.w,ho.h)){
   const nT=D.teams.length||1;
   D.teams.forEach((t,i)=>{const v=t.today.trades+t.today.open,hh=2+Math.min(9,v)+Math.round(Math.sin(T*2+i)*0.6);F(hx-10+(i*20/nT),hy+6-hh,Math.max(1,20/nT-1),hh,rgba(t.color,0.7));});
   for(let i=0;i<14;i++){const a=T*0.9+i*Math.PI/7,s=Math.sin(a);F(hx+Math.cos(a)*16,hy-6+s*4,1,1,rgba(i%3?CYAN:VIOLET,s>0?0.95:0.35));}
   F(hx-0.5,hy-16,1,16,rgba(CYAN,0.18));glow(hx,hy-6,16,CYAN,0.18+0.06*Math.sin(T*2));
  }
  const ws=walkers.slice().sort((a,b)=>a.py-b.py);
  ws.forEach(w=>{if(vis(w.px-6,w.py-14,12,24))drawWalker(w);});
  flashes.forEach(f=>{const a=(T-f.t)/0.7,r=3+a*12;P.g.globalAlpha=Math.max(0,1-a);ring(f.x-r,f.y-r*0.6,2*r,1.2*r,f.c);P.g.globalAlpha=1;});
  L.rooms.forEach(rm=>{if(rm.T.paused)F(rm.x,rm.y,rm.w,rm.h,'rgba(4,7,14,.58)');});
  [hov,sel].forEach((h,i)=>{
   const r=h&&h.hit;if(!r)return;
   const X=Math.round(r.x*k+P.bx)-2,Y=Math.round(r.y*k+P.by)-2,Wd=Math.round(r.w*k)+4,Hd=Math.round(r.h*k)+4;
   ctx.save();ctx.lineWidth=Math.max(1,dpr*(i?1.5:1));ctx.strokeStyle=i?GREEN:'rgba(232,238,249,.35)';
   if(i){ctx.setLineDash([5*dpr,3*dpr]);ctx.lineDashOffset=-T*18*dpr;ctx.shadowColor=GREEN;ctx.shadowBlur=8*dpr;}
   ctx.strokeRect(X+0.5,Y+0.5,Wd,Hd);ctx.restore();
  });
 }

 /* ---------- text (screen space) ---------- */
 function fitTxt(s,max){
  const key=ctx.font+'|'+s+'|'+Math.round(max);let v=TC.get(key);if(v!=null)return v;
  v=s;if(max<8)v='';else if(ctx.measureText(s).width>max){while(v.length>1&&ctx.measureText(v+'…').width>max)v=v.slice(0,-1);v=v.length>1?v+'…':'';}
  if(TC.size>800)TC.clear();TC.set(key,v);return v;
 }
 const font=(s,w)=>{ctx.font=(w||'')+' '+s+'px '+FONT;};
 const SX=x=>x*z+ox,SY=y=>y*z+oy;
 function label(s,x,y,c,max,al){s=fitTxt(s,max);if(s){ctx.textAlign=al||'left';ctx.fillStyle=c;ctx.fillText(s,x,y);}return s;}
 function plate(s,x,y,c,fs){
  font(fs,700);const w=ctx.measureText(s).width+10,h=fs+6;
  ctx.fillStyle='rgba(6,10,19,.85)';ctx.fillRect(x-w/2,y-h/2,w,h);ctx.strokeStyle=c;ctx.lineWidth=1;ctx.strokeRect(Math.round(x-w/2)+0.5,Math.round(y-h/2)+0.5,Math.round(w),Math.round(h));
  ctx.textAlign='center';ctx.fillStyle=c;ctx.fillText(s,x,y+0.5);
 }
 function drawLabels(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.textBaseline='middle';
  const fs=clamp(Math.round(z*5.2),8,13),fn=clamp(Math.round(z*4.2),7,11),inView=(x,y,w)=>x+w>0&&x<vw&&y>-20&&y<vh+20;
  L.rooms.forEach(rm=>{
   const Tm=rm.T,X=SX(rm.x),Y=SY(rm.y+7),Wd=rm.w*z;if(!inView(X,Y,Wd))return;
   font(fs,700);const nm=label(Tm.name.toUpperCase(),X+6*z,Y,Tm.paused?MUT:Tm.color,Wd*0.55);const used=nm?ctx.measureText(nm).width:0;
   font(fs-1);const sub=(Tm.today.open?Tm.today.open+' open · ':'')+Tm.today.trades+' trades',mon=inr(Tm.today.pnl,1);
   const sw=ctx.measureText(sub).width,mw=ctx.measureText(mon).width,R=X+Wd-5*z,room=Wd-10*z-used-12;
   if(room>mw+sw+10){label(sub,R,Y,MUT,sw+2,'right');label(mon,R-sw-8,Y,Tm.today.pnl>0?GREEN:Tm.today.pnl<0?RED:FG,mw+2,'right');}
   else if(room>mw)label(mon,R,Y,Tm.today.pnl>0?GREEN:Tm.today.pnl<0?RED:FG,mw+2,'right');
   if(z*20>=30){
    font(fn);
    rm.seats.forEach(se=>{if(!se.s)return;const s=se.s,v=s.status==='vacant';label(v?'vacant':(s.name||s.role),SX(se.x),SY(rm.y+40.5),v?'#4d5d7a':sel&&sel.id===s.id?GREEN:se.mgr?GOLD:MUT,(se.mgr?28:19)*z,'center');});
   }
   if(Tm.paused)plate('PAUSED',X+Wd/2,SY(rm.y+27),AMBER,clamp(Math.round(z*7),9,16));
  });
  L.empty.forEach(e=>{font(fn);label('EXPANSION BAY',SX(e.x+e.w/2),SY(e.y+e.h/2),'#3f5072',e.w*z-10,'center');});
  const dk=L.dock;font(fs,700);const dn=label('DATA DOCK',SX(dk.x+6),SY(dk.y+7),BLUE,(dk.w-10)*z),dnw=dn?ctx.measureText(dn).width:0;
  const ok=D.sources.filter(s=>s.status==='ok').length,okS=ok+'/'+D.sources.length+' OK';font(fs-1);
  const okT=ctx.measureText(okS).width+dnw+10<(dk.w-11)*z?okS:ok+'/'+D.sources.length;
  if(ctx.measureText(okT).width+dnw+8<(dk.w-11)*z)label(okT,SX(dk.x+dk.w-5),SY(dk.y+7),ok===D.sources.length?GREEN:AMBER,dk.w*z,'right');
  const fr=clamp(Math.round(z*4.8),7,12);font(fr);
  L.racks.forEach(rk=>{const st=rk.S.status;label(rk.S.name,SX(rk.lx),SY(rk.ly),st==='ok'?FG:SRCC[st]||MUT,rk.lw*z,rk.v?'center':'left');});
  const co=L.coo,ce=L.ceo;font(fs,700);
  label('COO',SX(co.r.x+6),SY(co.r.y+7),CYAN,30*z);const cw=ctx.measureText('COO').width+6;font(fs-1);label(str(D.coo.name)||'—',SX(co.r.x+6)+cw,SY(co.r.y+7),FG,(co.r.w-10)*z-cw);
  font(fs,700);label('CEO',SX(ce.r.x+6),SY(ce.r.y+7),GOLD,30*z);
  font(fn);label((str(D.ceo.name)||'CEO')+(live?'':' · away'),SX(ce.r.x+6),SY(ce.r.y+17),live?FG:MUT,(ce.r.w-10)*z);
  font(clamp(Math.round(z*4.2),7,12),700);label(inr(D.pnl.today_rs,1),SX(ce.r.x+ce.r.w-20),SY(ce.r.y+8),num(D.pnl.today_rs)>=0?GREEN:RED,24*z,'center');
  const ho=L.holo;if(ho){font(fn);label('EQUITY '+inr(D.pnl.equity_rs),SX(ho.x+ho.w/2),SY(ho.y+ho.h-4),VIOLET,ho.w*z,'center');}
  const bf=narrow?9:10;
  bubbles.forEach(b=>{
   const age=T-b.t,a=age<0.2?age/0.2:age>3?Math.max(0,(3.4-age)/0.4):1;font(bf);
   const w=ctx.measureText(b.s).width+10,h=bf+7,X=clamp(SX(b.x)-w/2,4,vw-w-4),Y=clamp(SY(b.y)-22*z-h,hudT,vh-hudB-h);
   ctx.globalAlpha=a;ctx.fillStyle='rgba(6,10,19,.92)';ctx.fillRect(X,Y,w,h);ctx.strokeStyle=b.c;ctx.lineWidth=1;ctx.strokeRect(Math.round(X)+0.5,Math.round(Y)+0.5,Math.round(w),Math.round(h));
   ctx.fillStyle=b.c;ctx.fillRect(clamp(SX(b.x),X+3,X+w-5)-1,Y+h,3,3);
   ctx.textAlign='left';ctx.fillStyle=FG;ctx.fillText(b.s,X+5,Y+h/2+0.5);ctx.globalAlpha=1;
  });
 }
 function ist(){const d=new Date(Date.now()+19800000),p=n=>String(n).padStart(2,'0');return p(d.getUTCHours())+':'+p(d.getUTCMinutes())+':'+p(d.getUTCSeconds());}
 function buildTicker(){
  const it=[];
  D.msgs.slice(0,8).forEach(m=>it.push({c:AMBER,s:(m.t?m.t+'  ':'')+(m.from?m.from+': ':'')+m.text}));
  arr(D.coo.notes).slice(0,4).forEach(n=>n&&n.text&&it.push({c:CYAN,s:'COO NOTE  '+str(n.text)}));
  D.flows.slice(-8).reverse().forEach(f=>it.push({c:KIND[f.kind]||FG,s:(f.t?f.t.slice(0,5)+'  ':'')+nameOf(f.from)+' → '+nameOf(f.to)+(f.text?': '+f.text.replace(/^\(fixture\)\s*/i,''):'')}));
  if(!it.length)it.push({c:MUT,s:'Waiting for the floor feed…'});
  font(narrow?10:11);let w=0;it.forEach(i=>{i.w=ctx.measureText(i.s).width;w+=i.w+40;});tick={items:it,w};
 }
 function drawHud(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.textBaseline='middle';
  const p=D.pnl,td=num(p.today_rs),sm=narrow||vh<420,f1=sm?9:10,f2=sm?14:18,f3=sm?9.5:11;
  const s1='BALAJI TRADING DESK // FLOOR',s2=inr(td,1),s3='OPEN '+inr(p.open_rs,1)+' · '+num(p.trades)+' TRADES';
  font(f1,700);const w1=ctx.measureText(s1).width;font(f2,700);const w2=ctx.measureText(s2).width;font(f1);const wl=ctx.measureText('P&L TODAY ').width;font(f3);const w3=ctx.measureText(s3).width;
  const bw=Math.max(w1,w2+wl,w3)+18,bh=sm?34:44;
  ctx.fillStyle='rgba(6,10,19,.8)';ctx.fillRect(6,6,bw,bh);ctx.fillStyle=GREEN;ctx.fillRect(6,6,2,bh);ctx.strokeStyle='rgba(45,227,165,.22)';ctx.strokeRect(6.5,6.5,bw-1,bh-1);
  ctx.textAlign='left';font(f1,700);ctx.fillStyle=GREEN;ctx.fillText(s1,14,sm?12:13);
  font(f1);ctx.fillStyle=MUT;ctx.fillText('P&L TODAY',14,sm?24:28);font(f2,700);ctx.fillStyle=td>=0?GREEN:RED;
  ctx.shadowColor=ctx.fillStyle;ctx.shadowBlur=8;ctx.fillText(s2,14+wl,sm?24:28);ctx.shadowBlur=0;
  if(!sm){font(f3);ctx.fillStyle=MUT;ctx.fillText(s3,14,42);}else{font(8.5);ctx.fillStyle=MUT;ctx.fillText(s3,14,34);}
  const fc=sm?10:12,clk='IST '+ist(),pl=live?'● CEO LIVE':'○ CEO AWAY';
  font(fc,700);const cw=ctx.measureText(clk).width;font(sm?9:10,700);const pw=ctx.measureText(pl).width+14,ph=sm?18:20;
  const px=vw-8-pw,cx=px-10-cw;
  ctx.fillStyle='rgba(6,10,19,.8)';ctx.fillRect(cx-8,6,vw-cx,ph+4);
  ctx.fillStyle=live?'rgba(45,227,165,.16)':'rgba(142,163,196,.12)';ctx.fillRect(px,8,pw,ph);ctx.strokeStyle=live?GREEN:'#56657f';ctx.strokeRect(px+0.5,8.5,pw-1,ph-1);
  ctx.fillStyle=live?GREEN:MUT;if(live){ctx.shadowColor=GREEN;ctx.shadowBlur=6+4*Math.sin(T*3.2);}ctx.textAlign='center';ctx.fillText(pl,px+pw/2,8+ph/2+0.5);ctx.shadowBlur=0;
  font(fc,700);ctx.fillStyle=GREEN;ctx.textAlign='left';ctx.fillText(clk,cx,8+ph/2+0.5);
  if(D.upd&&!sm){font(9);ctx.fillStyle='#5b7093';ctx.textAlign='right';ctx.fillText('SYNC '+D.upd.slice(11,16),vw-8,8+ph+12);}
  const ty=vh-hudB;ctx.fillStyle='rgba(6,10,19,.9)';ctx.fillRect(0,ty,vw,hudB);ctx.fillStyle=LINE;ctx.fillRect(0,ty,vw,1);
  font(sm?9:10,700);const tag='▶ FEED',tw=ctx.measureText(tag).width+16;ctx.fillStyle=GREEN;ctx.textAlign='left';ctx.fillText(tag,8,ty+hudB/2+0.5);
  ctx.save();ctx.beginPath();ctx.rect(tw,ty,vw-tw,hudB);ctx.clip();font(sm?10:11);
  if(tick.w>0){let x=tw+tickX;while(x<vw){for(const i of tick.items){if(x+i.w>tw&&x<vw){ctx.fillStyle=i.c;ctx.fillText(i.s,x,ty+hudB/2+0.5);}x+=i.w+18;if(x<vw){ctx.fillStyle='#33456a';ctx.fillText('◆',x,ty+hudB/2+0.5);}x+=22;if(x>=vw)break;}}}
  ctx.restore();
  if(vw>=520){
   font(9);let x=10;const y=ty-11;
   [['data',CYAN],['idea',AMBER],['report',GREEN],['order',VIOLET]].forEach(([n,c])=>{ctx.fillStyle=c;ctx.shadowColor=c;ctx.shadowBlur=6;ctx.fillRect(x,y-3,6,6);ctx.shadowBlur=0;ctx.fillStyle=MUT;ctx.textAlign='left';ctx.fillText(n,x+9,y+0.5);x+=ctx.measureText(n).width+22;});
  }
  if(hov&&mouse&&!drag){
   const t=tipOf(hov);if(t){
    font(10.5);const w=ctx.measureText(t).width+12,X=clamp(mouse.x+14,4,vw-w-4),Y=clamp(mouse.y+14,4,vh-24);
    ctx.fillStyle='rgba(6,10,19,.94)';ctx.fillRect(X,Y,w,19);ctx.strokeStyle='rgba(45,227,165,.55)';ctx.strokeRect(Math.round(X)+0.5,Math.round(Y)+0.5,Math.round(w),19);
    ctx.fillStyle=FG;ctx.textAlign='left';ctx.fillText(t,X+6,Y+10);
   }
  }
 }
 function draw(){
  ctx.setTransform(1,0,0,1,0,0);ctx.imageSmoothingEnabled=false;
  ctx.fillStyle=BG;ctx.fillRect(0,0,cv.width,cv.height);
  const k=z*dpr,bx=Math.round(ox*dpr),by=Math.round(oy*dpr);
  if(Math.abs(cacheS-k)<0.001)ctx.drawImage(cache,bx,by);
  else ctx.drawImage(cache,0,0,cache.width,cache.height,bx,by,cache.width*k/cacheS,cache.height*k/cacheS);
  drawWorld();drawLabels();
  ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(over,0,0);
  if(!RM){const yy=((T*40)%(vh+160)-80)*dpr,gr=ctx.createLinearGradient(0,yy-40*dpr,0,yy+40*dpr);gr.addColorStop(0,'rgba(45,227,165,0)');gr.addColorStop(0.5,'rgba(45,227,165,.035)');gr.addColorStop(1,'rgba(45,227,165,0)');ctx.fillStyle=gr;ctx.fillRect(0,yy-40*dpr,cv.width,80*dpr);}
  drawHud();
 }
 function loop(ts){
  raf=0;if(dead||!vis||document.hidden||!L)return;
  raf=requestAnimationFrame(loop);
  if(last&&ts-last<31)return;
  const dt=last?Math.min(0.1,(ts-last)/1000):0.033;last=ts;
  tickX-=(narrow?32:40)*dt;if(tick.w&&-tickX>tick.w)tickX+=tick.w;
  try{step(dt);draw();}catch(e){if(window.console)console.warn('Floor draw',e);}
 }
 function kick(){if(!raf&&!dead&&vis&&!document.hidden&&L){last=0;raf=requestAnimationFrame(loop);}}

 /* ---------- picking + panel ---------- */
 function hitAt(px,py){
  if(!L)return null;const wx=(px-ox)/z,wy=(py-oy)/z,rr=Math.max(4,9/z);
  let bw=null,bd=rr;walkers.forEach(w=>{if(w.done)return;const d=Math.hypot(w.px-wx,w.py-4-wy);if(d<bd){bd=d;bw=w;}});
  let best=null;L.hits.forEach(h=>{if(wx>=h.x&&wx<=h.x+h.w&&wy>=h.y&&wy<=h.y+h.h&&(!best||h.p>best.p))best=h;});
  if(bw&&(!best||best.p<2||bd<Math.max(3,5/z)))return{type:'flow',id:keyOf(bw.f),f:bw.f,w:bw,get hit(){return{x:bw.px-5,y:bw.py-14,w:10,h:20};}};
  return best?{type:best.type,id:best.id,hit:best}:null;
 }
 function tipOf(h){
  if(h.type==='person'){const s=D.staff[h.id];return s?(s.name||'—')+' · '+s.des+(s.role?' · '+s.role:''):'';}
  if(h.type==='room'){const t=D.teams.find(x=>x.id===h.id);return t?t.name+' · '+t.staff.length+' staff'+(t.paused?' · PAUSED':''):'';}
  if(h.type==='rack'){const s=D.sources.find(x=>x.id===h.id);return s?s.name+' · '+s.status.toUpperCase():'';}
  if(h.type==='coo')return(str(D.coo.name)||'COO')+' · '+(str(D.coo.designation)||'COO');
  if(h.type==='ceo')return(str(D.ceo.name)||'CEO')+' · '+(str(D.ceo.title)||'CEO')+(live?' · live':' · away');
  if(h.type==='dock')return'Data dock · '+D.sources.length+' sources';
  if(h.type==='flow')return h.f.kind+' · '+nameOf(h.f.from)+' → '+nameOf(h.f.to);
  return'';
 }
 function hitFor(type,id){if(!L)return null;if(type==='person'){const s=L.seatBy[id];return s&&s.hit;}if(type==='room'){const r=L.roomBy[id];return r&&r.hit;}return L.hits.find(h=>h.type===type&&h.id===id)||null;}
 function entity(h){
  const id=h.id;
  if(h.type==='person'){const s=D.staff[id];return s&&{type:'person',id,name:s.name,data:s.raw};}
  if(h.type==='room'){const t=D.teams.find(x=>x.id===id);return t&&{type:'room',id,name:t.name,data:t.raw};}
  if(h.type==='rack'){const s=D.sources.find(x=>x.id===id);return s&&{type:'rack',id,name:s.name,data:s.raw};}
  if(h.type==='dock')return{type:'dock',id:'dock',name:'Data dock',data:arr(D.raw.sources)};
  if(h.type==='coo')return{type:'coo',id:'coo',name:str(D.coo.name)||'COO',data:obj(D.raw.coo)};
  if(h.type==='ceo')return{type:'ceo',id:'ceo',name:str(D.ceo.name)||'CEO',data:{ceo:obj(D.raw.ceo),pnl:obj(D.raw.pnl),live}};
  if(h.type==='flow')return{type:'flow',id,name:h.f.kind,data:h.f.raw};
  return null;
 }
 function select(h,quiet){
  if(!h){closePanel();return;}
  const e=entity(h);if(!e){closePanel();return;}
  sel=h.type==='flow'?{type:'flow',id:h.id,f:h.f,hit:null}:{type:h.type,id:h.id,hit:h.hit||hitFor(h.type,h.id)};
  const r=sel.hit||(h.w&&h.hit);if(r&&!narrow)panel.classList.toggle('flr-l',(r.x+r.w/2)*z+ox>vw*0.58);
  renderPanel();panel.hidden=false;
  if(!quiet){try{if(typeof opts.onSelect==='function')opts.onSelect(e);}catch(x){if(window.console)console.warn('Floor onSelect',x);}try{root.dispatchEvent(new CustomEvent('floor:select',{detail:e,bubbles:true}));}catch(x){}}
 }
 function closePanel(){panel.hidden=true;sel=null;}
 const kv=(k,v)=>'<span>'+esc(k)+'</span><div>'+v+'</div>';
 const money=v=>'<b class="'+(num(v)>=0?'flr-up':'flr-dn')+'">'+inr(v,1)+'</b>';
 const pip=d=>/coo/i.test(d)?'◆':/manager/i.test(d)?'★':/senior/i.test(d)?'●●':'●';
 const stH=s=>'<b style="color:'+(STC[s]||MUT)+'">■ '+esc(STT[s]||s)+'</b>';
 const pl=r=>num(r.pnl_rs!=null?r.pnl_rs:r.pnl);
 function staffRow(s){
  return'<button type="button" class="flr-li" data-sel="person:'+esc(s.id)+'"><span class="flr-dot" style="background:'+(STC[s.status]||MUT)+'"></span><b>'+esc(s.name||'—')+
   '</b><span class="flr-mu">'+pip(s.des)+' '+esc(s.role||s.des)+'</span><span class="flr-r" style="color:'+(STC[s.status]||MUT)+'">'+esc(s.status)+'</span></button>';
 }
 function renderPanel(){
  if(!sel)return;let hd='',b='';
  const ty=sel.type,id=sel.id;
  if(ty==='person'){
   const s=D.staff[id];if(!s){closePanel();return;}const t=s.team,r=s.rec,tr=num(r.trades),wn=num(r.wins);
   hd='> AGENT://'+id;
   b='<div class="flr-h" style="color:'+t.color+'">'+esc(s.name||'—')+' <span style="color:'+(/manager/i.test(s.des)?GOLD:FG)+'">'+pip(s.des)+'</span></div><div class="flr-s">'+esc(s.des)+' · '+esc(t.name)+(t.paused?' · PAUSED':'')+'</div><div class="flr-kv">'+
    kv('ROLE',esc(s.role||'—'))+kv('WORK',esc(s.kind))+kv('STATUS',stH(s.status))+kv('DOING',esc(s.doing||'—'))+
    kv('RECORD',tr+' trades · '+wn+' wins'+(tr&&wn<=tr?' ('+Math.round(wn/tr*100)+'%)':'')+'<br>'+money(pl(r)))+'</div>'+
    '<button type="button" class="flr-li" data-sel="room:'+esc(t.id)+'">↳ open '+esc(t.name)+'</button>';
  }else if(ty==='room'){
   const t=D.teams.find(x=>x.id===id);if(!t){closePanel();return;}const td=t.today;
   hd='> TEAM://'+id;
   b='<div class="flr-h" style="color:'+t.color+'">'+esc(t.name)+'<span class="flr-tag" style="color:'+(t.paused?AMBER:GREEN)+'">'+(t.paused?'PAUSED':esc(t.status.toUpperCase()))+'</span></div><div class="flr-kv">'+
    kv('TODAY',money(td.pnl)+' · '+td.trades+' trades')+kv('OPEN',td.open+' positions · '+td.wins+' wins')+'</div><div class="flr-sec">STAFF ('+t.staff.length+')</div>'+
    (t.mgr?staffRow(t.mgr):'')+t.an.map(staffRow).join('');
  }else if(ty==='rack'){
   const s=D.sources.find(x=>x.id===id);if(!s){closePanel();return;}
   const fl=D.flows.filter(f=>f.from==='src:'+id).slice(-4).reverse();
   hd='> FEED://'+id;
   b='<div class="flr-h">'+esc(s.name)+'<span class="flr-tag" style="color:'+(SRCC[s.status]||MUT)+'">'+esc(s.status.toUpperCase())+'</span></div><div class="flr-kv">'+kv('DETAIL',esc(s.detail||'—'))+'</div>'+
    (fl.length?'<div class="flr-sec">RECENT DELIVERIES</div>'+fl.map(f=>'<div class="flr-li"><span class="flr-mu">'+esc(f.t.slice(0,5))+'</span> → '+esc(nameOf(f.to))+'</div>').join(''):'');
  }else if(ty==='dock'){
   hd='> DOCK://sources';
   b='<div class="flr-h" style="color:'+BLUE+'">Data dock</div><div class="flr-s">'+D.sources.length+' sources feeding the floor</div>'+
    D.sources.map(s=>'<button type="button" class="flr-li" data-sel="rack:'+esc(s.id)+'"><span class="flr-dot" style="background:'+(SRCC[s.status]||MUT)+'"></span><b>'+esc(s.name)+'</b><span class="flr-r" style="color:'+(SRCC[s.status]||MUT)+'">'+esc(s.status)+'</span></button>').join('');
  }else if(ty==='coo'){
   const c=D.coo;
   hd='> OFFICE://coo';
   b='<div class="flr-h" style="color:'+CYAN+'">'+esc(str(c.name)||'COO')+' <span>◆</span></div><div class="flr-s">'+esc(str(c.designation)||'COO')+' · glass office</div><div class="flr-kv">'+kv('DOING',esc(str(c.doing)||'—'))+
    (arr(c.requests).length?kv('ASKS',arr(c.requests).length+' waiting for the CEO'):'')+'</div>'+
    (arr(c.notes).length?'<div class="flr-sec">NOTES</div>'+arr(c.notes).map(n=>{n=obj(n);const lv=str(n.level),col=/err|bad|crit/i.test(lv)?RED:/warn/i.test(lv)?AMBER:MUT;return'<div class="flr-li"><span class="flr-dot" style="background:'+col+'"></span><span>'+esc(n.text)+'</span></div>';}).join(''):'')+
    (arr(c.hires).length?'<div class="flr-sec">HIRES</div>'+arr(c.hires).map(h=>{h=obj(h);return'<div class="flr-li"><span class="flr-mu">'+esc(h.t)+'</span><span><b>'+esc(h.name)+'</b> · '+esc(h.designation)+', '+esc(h.role)+(h.team?' ('+esc(h.team)+')':'')+'<br><span class="flr-mu">'+esc(h.why)+'</span></span></div>';}).join(''):'');
  }else if(ty==='ceo'){
   const p=D.pnl;
   hd='> OFFICE://ceo';
   b='<div class="flr-h" style="color:'+GOLD+'">'+esc(str(D.ceo.name)||'CEO')+'</div><div class="flr-s">'+esc(str(D.ceo.title)||'CEO')+' · <b style="color:'+(live?GREEN:MUT)+'">'+(live?'● LIVE':'○ AWAY')+'</b></div><div class="flr-kv">'+
    kv('TODAY',money(p.today_rs))+kv('OPEN',money(p.open_rs))+kv('CLOSED',money(p.closed_rs))+kv('TRADES',esc(num(p.trades)))+kv('EQUITY','<b>'+inr(p.equity_rs)+'</b>')+(D.upd?kv('UPDATED',esc(D.upd.replace('T',' ').slice(0,19))):'')+'</div>';
  }else if(ty==='flow'){
   const f=sel.f,c=KIND[f.kind]||FG;
   hd='> PACKET://'+f.kind;
   b='<div class="flr-h" style="color:'+c+'">■ '+esc(f.kind.toUpperCase())+'</div><div class="flr-kv">'+kv('FROM',esc(nameOf(f.from)))+kv('TO',esc(nameOf(f.to)))+kv('TIME',esc(f.t||'—'))+kv('TEXT',esc(f.text||'—'))+'</div>';
  }
  pT.textContent=hd;pB.innerHTML=b;
 }
 pB.addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('[data-sel]');if(!b)return;
  const v=b.getAttribute('data-sel'),i=v.indexOf(':'),ty=v.slice(0,i),id=v.slice(i+1);
  select({type:ty,id,hit:hitFor(ty,id)});
 });
 panel.querySelector('.flr-x').addEventListener('click',()=>{closePanel();cv.focus({preventScroll:true});});
 root.querySelector('.flr-ctl').addEventListener('click',e=>{
  const b=e.target.closest&&e.target.closest('[data-z]');if(!b)return;
  const v=+b.getAttribute('data-z');if(v===0)fitView(true);else zoomBy(v>0?1.35:1/1.35);kick();
 });

 /* ---------- input ---------- */
 const loc=e=>{const r=cv.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top};};
 function onDown(e){
  if(e.pointerType==='mouse'&&e.button!==0)return;
  const p=loc(e);pts.set(e.pointerId,p);try{cv.setPointerCapture(e.pointerId);}catch(x){}
  tween=null;
  if(pts.size===1)drag={x:p.x,y:p.y,ox,oy,moved:false};
  else if(pts.size===2){const[a,b]=[...pts.values()];pinch={d:Math.hypot(a.x-b.x,a.y-b.y)||1,z,cx:(a.x+b.x)/2,cy:(a.y+b.y)/2,ox,oy};drag=null;}
  kick();
 }
 function onMove(e){
  const p=loc(e);
  if(pts.has(e.pointerId)){
   pts.set(e.pointerId,p);
   if(pinch&&pts.size>=2){
    const[a,b]=[...pts.values()],d=Math.hypot(a.x-b.x,a.y-b.y)||1,cx=(a.x+b.x)/2,cy=(a.y+b.y)/2;
    const nz=clamp(pinch.z*d/pinch.d,zMin,zMax),wx=(pinch.cx-pinch.ox)/pinch.z,wy=(pinch.cy-pinch.oy)/pinch.z;
    z=nz;ox=cx-wx*z;oy=cy-wy*z;clampView();moved=true;lastZoom=T;TC.clear();kick();return;
   }
   if(drag){
    const dx=p.x-drag.x,dy=p.y-drag.y;
    if(!drag.moved&&Math.hypot(dx,dy)>5){drag.moved=true;cv.classList.add('flr-drag');hov=null;}
    if(drag.moved){ox=drag.ox+dx;oy=drag.oy+dy;clampView();moved=true;kick();}
    return;
   }
  }
  if(e.pointerType==='mouse'){mouse=p;hov=hitAt(p.x,p.y);if(hov&&hov.type==='room'&&sel&&sel.type==='room'&&sel.id===hov.id)hov=null;cv.classList.toggle('flr-hot',!!hov);}
 }
 function onUp(e){
  const p=loc(e),had=pts.has(e.pointerId);pts.delete(e.pointerId);
  if(had&&e.type==='pointerup'&&drag&&!drag.moved&&!pinch)select(hitAt(p.x,p.y));
  if(pts.size<2){if(pinch)touchMode();pinch=null;}
  if(pts.size===1){const q=[...pts.values()][0];drag={x:q.x,y:q.y,ox,oy,moved:true};}else if(!pts.size){drag=null;cv.classList.remove('flr-drag');}
 }
 function onWheel(e){
  if(!L)return;e.preventDefault();
  const p=loc(e),d=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?400:1);
  zoomAt(p.x,p.y,Math.exp(-clamp(d,-300,300)*0.0018));
 }
 function onKey(e){
  if(e.key==='Escape'&&!panel.hidden){closePanel();e.preventDefault();return;}
  if(e.target!==cv||!L)return;
  const step=60,k=e.key;let used=true;
  if(k==='ArrowLeft')ox+=step;else if(k==='ArrowRight')ox-=step;else if(k==='ArrowUp')oy+=step;else if(k==='ArrowDown')oy-=step;
  else if(k==='+'||k==='=')zoomBy(1.25);else if(k==='-'||k==='_')zoomBy(0.8);else if(k==='0'||k==='f'||k==='F')fitView(true);
  else used=false;
  if(used){e.preventDefault();tween=tween&&k.indexOf('Arrow')===0?null:tween;clampView();moved=true;kick();}
 }
 cv.addEventListener('pointerdown',onDown);cv.addEventListener('pointermove',onMove);
 cv.addEventListener('pointerup',onUp);cv.addEventListener('pointercancel',onUp);
 cv.addEventListener('pointerleave',()=>{if(!pts.size){hov=null;mouse=null;cv.classList.remove('flr-hot');}});
 cv.addEventListener('wheel',onWheel,{passive:false});
 root.addEventListener('keydown',onKey);
 const onResize=()=>{root.style.height=computeH()+'px';relayout(false);};
 const onVis=()=>{if(!document.hidden)kick();};
 window.addEventListener('resize',onResize);document.addEventListener('visibilitychange',onVis);
 let ro=null,io=null;
 if(window.ResizeObserver){ro=new ResizeObserver(()=>relayout(false));ro.observe(root);}
 if(window.IntersectionObserver){io=new IntersectionObserver(es=>{vis=es[es.length-1].isIntersecting;if(vis){relayout(false);kick();}},{threshold:0});io.observe(root);}

 function aria(){
  const st=D.teams.reduce((a,t)=>a+t.staff.length,0),al=D.teams.reduce((a,t)=>a+t.staff.filter(s=>s.status==='alert').length,0),ok=D.sources.filter(s=>s.status==='ok').length;
  cv.setAttribute('aria-label','Balaji Trading Desk office floor: '+D.teams.length+' teams, '+st+' staff'+(al?' ('+al+' need attention)':'')+', '+ok+' of '+D.sources.length+
   ' data sources OK. Company P&L today '+inr(D.pnl.today_rs,1)+', open '+inr(D.pnl.open_rs,1)+', '+num(D.pnl.trades)+' trades. CEO '+(live?'live':'away')+'. Drag to pan, wheel or pinch to zoom, tap a desk for details.');
 }
 function update(j){
  if(dead)return;
  try{
   D=norm(j);LK.clear();const s=sigOf(D);
   if(s!==sig){sig=s;if(vw)relayout(true);}
   ingest();buildTicker();aria();if(sel){if(sel.type!=='flow')sel.hit=hitFor(sel.type,sel.id);renderPanel();}kick();
  }catch(e){if(window.console)console.warn('Floor.update',e);}
 }
 function setLive(b){live=!!b;aria();if(sel&&sel.type==='ceo')renderPanel();kick();}
 function destroy(){
  if(dead)return;dead=true;if(raf)cancelAnimationFrame(raf);raf=0;
  window.removeEventListener('resize',onResize);document.removeEventListener('visibilitychange',onVis);
  if(ro)ro.disconnect();if(io)io.disconnect();root.remove();walkers=[];queue=[];
 }
 root.style.height=computeH()+'px';
 sig=sigOf(D);ingest();aria();
 relayout(true);
 const api={update,setLive,destroy};
 if(opts.debug)api.debug=(type,id)=>{
  const h=type&&hitFor(type,id);
  if(type==='route')return route(L,id[0],id[1]);
  if(type==='L')return L;
  return{walkers:walkers.length,queued:queue.length,layout:L&&{o:L.o,C:L.C,ev:L.ev,W:L.W,H:L.H},z,fitZ,panel:!panel.hidden,
   at:h?{x:(h.x+h.w/2)*z+ox,y:(h.y+h.h/2)*z+oy}:null};
 };
 return api;
}

window.Floor={mount};
})();
