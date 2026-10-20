"""Focused account performance reports; no broker actions are exposed through HTTP."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .run_performance import run_reports

if TYPE_CHECKING:
    from ..broker import AccountSnapshot, PaperBroker


DOCUMENT = r"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PyIBQuant · Paper account</title><style>
:root{color-scheme:dark;font:15px system-ui;background:#111827;color:#e5e7eb}
body{max-width:1200px;margin:32px auto;padding:0 24px}h1{font-size:26px}
small,.muted{color:#9ca3af}header{display:flex;justify-content:space-between;gap:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card,section{background:#1f2937;border:1px solid #374151;border-radius:10px;padding:16px}
.card b{display:block;font-size:22px;margin-top:8px}section{margin-top:20px}
canvas{width:100%;height:220px;display:block}table{width:100%;border-collapse:collapse;
font-size:13px}td,th{text-align:left;padding:9px;border-bottom:1px solid #374151}
.scroll{overflow:auto}.warning{color:#fbbf24}button{color:inherit;background:#374151;
border:0;border-radius:6px;padding:8px 12px;cursor:pointer}#errors{white-space:pre-wrap}
select{max-width:100%;color:inherit;background:#374151;padding:10px;border:0;border-radius:6px}
</style><body><header><div><small>PYIBQUANT / PAPER TRADING</small>
<h1>Account performance</h1><p id="status"></p></div><div><button onclick="location.reload()">
Refresh</button><p id="mode" class="muted"></p></div></header><div id="cards" class="cards"></div>
<p class="muted">Account totals include existing and manual positions. Changes in account value
are not strategy profit. Broker daily P&amp;L resets; history begins at observation.
Gaps and session boundaries break lines. Times below use your browser timezone.</p>
<section><h2>Net liquidation value</h2><canvas id="value"></canvas></section>
<section><h2>Cash balance</h2><canvas id="cash"></canvas></section>
<section><h2>Broker P&amp;L · daily / unrealized / realized</h2>
<p><span style="color:#60a5fa">Daily</span> · <span style="color:#34d399">Unrealized</span> ·
<span style="color:#fbbf24">Realized</span></p><canvas id="pnl"></canvas></section>
<section><h2>Strategy runs</h2><p class="muted">Only tagged algorithmic fills belong to a run.
Manual positions and the starting-share close remain outside these results. FIFO costs include
known USD commissions. Open P&amp;L uses last observed portfolio marks, not current quotes.
Drawdown is in dollars over observed points; no return percentage or starting capital
is inferred.</p>
<div id="runs" class="scroll"></div><p><label for="run-select">Inspect run </label>
<select id="run-select"></select></p><p id="run-status" class="muted"></p>
<p id="run-config" class="muted"></p>
<div id="run-cards" class="cards"></div><h3>Run P&amp;L · net / realized</h3>
<canvas id="run-pnl"></canvas><h3>Owned gross exposure · last observed marks</h3>
<canvas id="run-exposure"></canvas><h3>Run orders</h3><div id="run-orders" class="scroll"></div>
<h3>Owned shares and observed marks</h3><div id="run-positions" class="scroll"></div>
<h3>Run executions and fees</h3><div id="run-fills" class="scroll"></div>
<p id="run-issues" class="warning"></p></section>
<section><h2>Positions</h2><div id="positions" class="scroll"></div></section>
<section><h2>Orders · observed clients only</h2><div id="orders" class="scroll"></div></section>
<section><h2>Executions and fees</h2><div id="executions" class="scroll"></div></section>
<section><h2>Data status</h2><p class="muted">Account fields update independently;
receipt time does not prove a fresh exchange price. Unavailable values remain blank.
Account-wide order snapshots do not grant control of other clients' orders.</p>
<div id="fields" class="scroll"></div><p id="errors" class="warning"></p></section>
<script>const initial=__DATA__;const live=__LIVE__;
const fmt=x=>x===null||x===undefined?'—':
Number(x).toLocaleString(undefined,{maximumFractionDigits:2});
function table(id,rows,keys){const el=document.getElementById(id);el.replaceChildren();
if(!rows.length){el.textContent='None observed';return}const t=document.createElement('table');
const head=t.createTHead().insertRow();keys.forEach(k=>{const c=document.createElement('th');
c.textContent=k.replaceAll('_',' ');head.append(c)});const body=t.createTBody();
rows.forEach(r=>{const tr=body.insertRow();keys.forEach(k=>{const td=tr.insertCell();
let v=r[k];if(v&&(k.endsWith('_at')||k==='mark_time')&&Number.isFinite(Date.parse(v)))
v=new Date(v).toLocaleString();td.textContent=v??'—'})});el.append(t)}
function chart(id,points,fields){const c=document.getElementById(id),ratio=devicePixelRatio||1;
c.width=c.clientWidth*ratio;c.height=220*ratio;const g=c.getContext('2d');g.scale(ratio,ratio);
const w=c.clientWidth,h=220,colors=['#60a5fa','#34d399','#fbbf24'];
const valid=points.flatMap(p=>fields.map(k=>p[k])).filter(x=>x!==null&&Number.isFinite(Number(x)));
if(!valid.length){g.fillStyle='#9ca3af';g.fillText('Waiting for broker observations',20,35);return}
let lo=Infinity,hi=-Infinity;
valid.forEach(v=>{lo=Math.min(lo,Number(v));hi=Math.max(hi,Number(v))});
if(lo===hi){lo-=1;hi+=1}const x0=Date.parse(points[0].time),x1=Date.parse(points.at(-1).time);
const X=p=>70+(Date.parse(p.time)-x0)/(x1-x0||1)*(w-90),Y=v=>180-(v-lo)/(hi-lo)*155;
g.font='12px system-ui';g.fillStyle='#9ca3af';g.fillText(fmt(hi),4,20);g.fillText(fmt(lo),4,180);
g.fillText(new Date(x0).toLocaleString(),70,210);
g.textAlign='right';g.fillText(new Date(x1).toLocaleTimeString(),w-10,210);g.textAlign='left';
fields.forEach((k,j)=>{g.strokeStyle=colors[j];g.lineWidth=1.6;g.beginPath();let prev=null;
points.forEach(p=>{if(p[k]===null||!Number.isFinite(Number(p[k]))){prev=null;return}
const x=X(p),y=Y(Number(p[k]));if(!prev||prev.session!==p.session||p.gap)g.moveTo(x,y);
else g.lineTo(x,y);prev=p});g.stroke();const last=points.findLast(p=>p[k]!==null);
if(last){g.fillStyle=colors[j];g.beginPath();g.arc(X(last),Y(Number(last[k])),3,0,7);g.fill()}})}
let selectedRun=null;
function drawRuns(d){const rows=d.runs??[],select=document.getElementById('run-select');
table('runs',rows,['run_id','symbol','mode','status','order_count','execution_count','realized_pnl',
'unrealized_pnl','net_pnl','commissions','observed_drawdown']);
if(!rows.some(r=>r.run_id===selectedRun))
selectedRun=(rows.findLast(r=>r.execution_count>0)??rows.at(-1))?.run_id??null;
select.replaceChildren();rows.forEach(r=>{const option=document.createElement('option');
option.value=r.run_id;option.textContent=
`${r.symbol} · ${new Date(r.started_at).toLocaleString()} · ${r.run_id.slice(0,10)}`;
option.selected=r.run_id===selectedRun;select.append(option)});
const r=rows.find(r=>r.run_id===selectedRun),cards=document.getElementById('run-cards');
cards.replaceChildren();document.getElementById('run-status').textContent=r?
`${r.status} · ${r.mark_status} · ${r.complete?'fills reconciled':'incomplete attribution'}`+
`${r.last_pause_reason?' · last pause: '+r.last_pause_reason:''}`:
'No algorithmic runs recorded';
document.getElementById('run-config').textContent=r?
`SMA window: ${r.config.window??'unknown'} · target shares: ${r.config.quantity??'unknown'} · `+
`order limit: ${r.config.max_orders??'unknown'} · account session-loss limit: `+
`${fmt(r.config.max_session_loss)} USD · `+
`${r.checkpoint_version?'checkpoint recorded':'legacy; reporting only'}`:'';
[['Net P&L',r?.net_pnl],['Realized P&L',r?.realized_pnl],['Unrealized P&L',r?.unrealized_pnl],
['Commissions',r?.commissions],['Gross exposure',r?.gross_exposure],
['Observed drawdown ($)',r?.observed_drawdown]].forEach(([label,value])=>{
const div=document.createElement('div');div.className='card';
const small=document.createElement('small');small.textContent=label;
const b=document.createElement('b');b.textContent=fmt(value);
div.append(small,b);cards.append(div)});
chart('run-pnl',r?.points??[],['net','realized']);
chart('run-exposure',r?.points??[],['exposure']);
table('run-orders',r?.orders??[],['order_id','client_id','symbol','side','quantity','status','filled']);
table('run-positions',r?.positions??[],['con_id','quantity','mark','mark_time']);
table('run-fills',r?.executions??[],['exec_id','side','quantity','price','commission','fee_currency']);
document.getElementById('run-issues').textContent=(r?.issues??[]).join('\n')}
let current=initial;function draw(d){current=d;const s=d.snapshot;
document.getElementById('status').textContent=`${s.account} · ${s.status} · `+
`${s.complete?'download complete':'incomplete/stale'} · ${d.currency??'unknown currency'}`;
document.getElementById('mode').textContent=live?
'Live observer · updates every 3 seconds':'Saved report';
const cards=document.getElementById('cards');cards.replaceChildren();
[['Net liquidation',d.latest.value],['Cash',d.latest.cash],['Settled cash',d.latest.settled],
['Unsettled cash (estimate)',d.funding.unsettled_estimate],
['Pending buys (estimate)',d.funding.pending_buy_estimate],
['Cash budget',d.funding.usable],
['Buying power',d.latest.buying_power],['Available funds',d.latest.available],
['Daily P&L',s.pnl.validated===false?null:s.pnl.daily]]
.forEach(([label,v])=>{const div=document.createElement('div');div.className='card';
const title=document.createElement('small');title.textContent=label;
const b=document.createElement('b');
b.textContent=fmt(v);div.append(title,b);cards.append(div)});
chart('value',d.points,['value']);chart('cash',d.points,['cash']);
chart('pnl',d.points,['daily','unrealized','realized']);
drawRuns(d);
table('positions',s.positions,['symbol','asset_type','quantity','average_cost','market_value',
'unrealized_pnl','currency']);table('orders',s.orders,['order_id','client_id','symbol','side',
'quantity','limit_price','status','filled','remaining','tag']);table('executions',s.executions,
['exec_id','symbol','side','quantity','price','commission','fee_currency','broker_time']);
table('fields',s.values.filter(v=>['NetLiquidation','TotalCashValue','SettledCash',
'BuyingPower','AvailableFunds','AccountType','SettledCashByDate'].includes(v.tag)),
['tag','currency','value','received_at','source']);document.getElementById('errors').textContent=s.errors.join('\n')}
draw(initial);document.getElementById('run-select').addEventListener('change',e=>{
selectedRun=e.target.value;drawRuns(current)});
addEventListener('resize',()=>draw(current));if(live)setInterval(async()=>{
try{const r=await fetch('/data',{cache:'no-store'});if(!r.ok)throw Error(r.status);
draw(await r.json())}
catch(e){document.getElementById('status').textContent=
'Observer unreachable · displayed data is stale'}
},3000);</script></body></html>"""


def payload(
    events: list[dict[str, Any]],
    snapshot: AccountSnapshot,
    *,
    funding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    currencies = {
        v.currency
        for v in snapshot.values
        if v.tag == "NetLiquidation"
        and v.source == "account_summary"
        and v.currency not in {"", "BASE"}
    }
    base = snapshot.value("BaseCurrency")
    currency = base.value if base else (next(iter(currencies)) if len(currencies) == 1 else None)
    state: dict[str, Any] = dict(
        value=None,
        cash=None,
        settled=None,
        buying_power=None,
        available=None,
        daily=None,
        unrealized=None,
        realized=None,
    )
    from ..broker import mask_account_data, money, settled_schedule

    tags = dict(
        NetLiquidation="value",
        TotalCashValue="cash",
        SettledCash="settled",
        BuyingPower="buying_power",
        AvailableFunds="available",
    )
    points = []
    session = None
    gap = True
    validated: set[tuple[str, Any]] = set()
    pending: dict[tuple[str, Any], dict[str, Any]] = {}
    guarded = {
        (e["session"], e["payload"].get("request_id"))
        for e in events
        if e["kind"] == "pnl_validated"
    }
    for e in events:
        p, kind = e["payload"], e["kind"]
        if e["session"] != session:
            session = e["session"]
            state = dict.fromkeys(state)
            gap = True
        if kind in {"disconnected", "closed"} or (kind == "error" and p.get("fatal")):
            gap = True
            continue
        if kind == "value" and p["tag"] in tags and p["currency"] in {"", "BASE", currency}:
            parsed = money(p["value"])
            state[tags[p["tag"]]] = str(parsed) if parsed is not None else None
        elif kind == "value" and p["tag"] == "SettledCashByDate" and p["currency"] == currency:
            day = (
                datetime.fromisoformat(e["received_at"])
                .astimezone(ZoneInfo("America/New_York"))
                .date()
            )
            settled = settled_schedule(p["value"], on_date=day)
            state["settled"] = str(settled) if settled is not None else None
        elif kind == "pnl":
            key = (e["session"], p.get("request_id"))
            pending[key] = p
            if key in guarded and key not in validated:
                continue
            state.update({k: p.get(k) for k in ("daily", "unrealized", "realized")})
        elif kind == "pnl_validated":
            key = (e["session"], p.get("request_id"))
            validated.add(key)
            state.update(
                {k: pending.get(key, {}).get(k) for k in ("daily", "unrealized", "realized")}
            )
        else:
            continue
        points.append(dict(time=e["received_at"], session=session, gap=gap, **state))
        gap = False
    return mask_account_data(
        dict(
            snapshot=snapshot.to_dict(),
            currency=currency,
            points=points,
            latest=state,
            funding=funding or {},
            runs=run_reports(events, snapshot),
        ),
        snapshot.account,
    )


def render(data: dict[str, Any], *, live: bool = False) -> str:
    encoded = json.dumps(data, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return DOCUMENT.replace("__DATA__", encoded).replace("__LIVE__", "true" if live else "false")


def write_report(
    events: list[dict[str, Any]],
    snapshot: AccountSnapshot,
    path: str | Path,
    *,
    funding: dict[str, Any] | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = payload(events, snapshot, funding=funding)
    target.write_text(render(data), encoding="utf-8")
    with target.with_suffix(".csv").open("w", newline="") as stream:
        fields = ["time", "session", "gap", *data["latest"]]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data["points"])
    summaries = [
        dict(
            run_id=r["run_id"],
            symbol=r["symbol"],
            status=r["status"],
            realized_pnl=r["realized_pnl"],
            unrealized_pnl=r["unrealized_pnl"],
            net_pnl=r["net_pnl"],
            commissions=r["commissions"],
            gross_exposure=r["gross_exposure"],
            observed_drawdown=r["observed_drawdown"],
            complete=r["complete"],
            issues="; ".join(r["issues"]),
        )
        for r in data["runs"]
    ]
    columns = [
        "run_id",
        "symbol",
        "status",
        "realized_pnl",
        "unrealized_pnl",
        "net_pnl",
        "commissions",
        "gross_exposure",
        "observed_drawdown",
        "complete",
        "issues",
    ]
    with target.with_name(target.stem + "-runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)
    with target.with_name(target.stem + "-run-points.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "run_id",
                "time",
                "session",
                "gap",
                "net",
                "realized",
                "exposure",
                "drawdown",
            ],
        )
        writer.writeheader()
        writer.writerows(
            dict(run_id=r["run_id"], **point) for r in data["runs"] for point in r["points"]
        )
    columns = [
        "run_id",
        "exec_id",
        "order_id",
        "client_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "commission",
        "fee_currency",
        "broker_time",
        "received_at",
    ]
    with target.with_name(target.stem + "-fills.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            dict(run_id=r["run_id"], **fill) for r in data["runs"] for fill in r["executions"]
        )
    return target.resolve()


def serve(broker: PaperBroker, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            # Local data must not become readable through a rebinding Host name.
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            if host not in {"127.0.0.1", "localhost"}:
                self.send_error(403)
                return
            route = urlsplit(self.path).path
            if route not in {"/", "/data"}:
                self.send_error(404)
                return
            data = payload(
                broker.journal.events(broker.account), broker.snapshot(), funding=broker.funding()
            )
            body = (
                json.dumps(data, allow_nan=False) if route == "/data" else render(data, live=True)
            ).encode()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json" if route == "/data" else "text/html; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
