"""Does the live world-market picture predict the REST of NIFTY's day? Measured on Yahoo hourly data (last ~730 days) plus the NIFTY 1-minute DB.

For each cut time (10:15, 11:15, 12:15, 13:15): the implied NIFTY move from world markets since yesterday's 15:30 (rupee, dollar index, Brent,
S&P futures, Nikkei, Hang Seng, weighted by the same-day betas in docs/models/macro_model.json) versus NIFTY's move so far; hit rate of each
for the move from the cut to the close; and the hit rate when they agree or disagree.
Usage: python quant/run_macro_intraday.py <nifty50_1m.sqlite> <out.json>. Research only.
"""
import json, sqlite3, urllib.request, time, sys
from datetime import datetime, timezone, timedelta
import numpy as np
IST=timezone(timedelta(hours=5,minutes=30))
def hourly(sym):
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range=730d&interval=1h"
    r=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=40).read())["chart"]["result"][0]
    return [(t,c) for t,c in zip(r["timestamp"],r["indicators"]["quote"][0]["close"]) if c]
F={"usdinr":"INR=X","dxy":"DX-Y.NYB","brent":"BZ=F","es":"ES=F","n225":"^N225","hsi":"^HSI"}
H={k:hourly(s) for k,s in F.items()}
beta={"usdinr":-0.3471,"dxy":-0.1694,"brent":-0.0138,"es":0.1578,"n225":0.1359,"hsi":0.0949}
con=sqlite3.connect(sys.argv[1])
days=[r[0] for r in con.execute("select day from days where complete=1 and day>=? order by day",((datetime.now()-timedelta(days=720)).strftime('%Y-%m-%d'),))]
def px_at(series,ts):
    lo=[c for t,c in series if t<=ts]; return lo[-1] if lo else None
def nifty_at(day,hhmm):
    t0=int(datetime.fromisoformat(day+'T'+hhmm+':00+05:30').timestamp()); r=con.execute("select close from candles where ts<=? and ts>=? order by ts desc limit 1",(t0-60,t0-600)).fetchone(); return r[0] if r else None
out={}
for cut in ["10:15","11:15","12:15","13:15"]:
    X=[];Y=[];N=[]
    prevclose={}
    for i,d in enumerate(days[1:],1):
        pd=days[i-1]; pc=con.execute("select close from days where day=?",(pd,)).fetchone()[0]
        tcut=int(datetime.fromisoformat(d+'T'+cut+':00+05:30').timestamp()); tprev=int(datetime.fromisoformat(pd+'T15:30:00+05:30').timestamp())
        f={}
        for k,s in H.items():
            a,b=px_at(s,tprev),px_at(s,tcut)
            f[k]=(b/a-1)*100 if a and b else None
        if any(v is None for v in f.values()): continue
        nc=nifty_at(d,cut); close=con.execute("select close from days where day=?",(d,)).fetchone()[0]
        if not nc: continue
        imp=sum(beta[k]*f[k] for k in f)
        sofar=(nc/pc-1)*100; rest=(close/nc-1)*100
        X.append(imp);N.append(sofar);Y.append(rest)
    X,N,Y=np.array(X),np.array(N),np.array(Y)
    gap=X-N   # macro implies more (positive) than NIFTY has done so far
    hit=lambda s:round(100*np.mean((np.sign(s)==np.sign(Y))[np.abs(s)>0]),1)
    strong=np.abs(X)>=0.3
    agree=(np.sign(X)==np.sign(N))&(np.abs(X)>=0.2)&(np.abs(N)>=0.3)
    dis=(np.sign(X)!=np.sign(N))&(np.abs(X)>=0.2)&(np.abs(N)>=0.3)
    out_agree={"agree_days":int(agree.sum()),"agree_hit":round(100*np.mean(np.sign(X[agree])==np.sign(Y[agree])),1) if agree.any() else None,
               "disagree_days":int(dis.sum()),"disagree_macro_hit":round(100*np.mean(np.sign(X[dis])==np.sign(Y[dis])),1) if dis.any() else None}
    out[cut]={**out_agree,"days":len(Y),"macro_sign_hits_rest_of_day":hit(X),"macro_strong_days":int(strong.sum()),"macro_strong_hit":round(100*np.mean(np.sign(X[strong])==np.sign(Y[strong])),1) if strong.any() else None,
              "momentum_hit":hit(N),"gap_hit":hit(gap),"corr_macro_rest":round(float(np.corrcoef(X,Y)[0,1]),3),"corr_gap_rest":round(float(np.corrcoef(gap,Y)[0,1]),3),"corr_sofar_rest":round(float(np.corrcoef(N,Y)[0,1]),3),
              "up_base":round(100*np.mean(Y>0),1)}
    print(cut,out[cut],flush=True)
json.dump(out,open(sys.argv[2],'w'),indent=1)
