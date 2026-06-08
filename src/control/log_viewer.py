"""GraphMCP Professional Dashboard"""
import asyncio, json, os, time
from collections import defaultdict, deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from src.shared.config import config

app = FastAPI(title="GraphMCP Dashboard")
LOG_FILE = config.log_file

class DashboardState:
    def __init__(self):
        self.level_counts = defaultdict(int)
        self.tool_counts  = defaultdict(int)
        self.tool_errors  = defaultdict(int)
        self.tool_durations = defaultdict(list)
        self.recent_calls  = deque(maxlen=100)
        self.recent_errors = deque(maxlen=20)
        self.latency_history = deque(maxlen=60)
        self.start_time = time.time()
        self.total_parsed = 0

    def ingest(self, e):
        self.total_parsed += 1
        lv = (e.get("level") or "INFO").upper()
        self.level_counts[lv] += 1
        tool = e.get("tool")
        if not tool: return
        msg, dur = e.get("msg",""), e.get("duration_ms")
        if "tamamlandı" in msg or "completed" in msg.lower():
            self.tool_counts[tool] += 1
            if dur:
                self.tool_durations[tool].append(int(dur))
                self.latency_history.append({"t": e.get("ts",""), "ms": int(dur), "tool": tool})
            self.recent_calls.appendleft({
                "tool": tool, "status": "ok",
                "duration_ms": dur,
                "collection": e.get("collection",""),
                "query": e.get("query",""),
                "ts": e.get("ts",""),
            })
        elif lv in ("ERROR","CRITICAL") or "hata" in msg.lower():
            self.tool_errors[tool] = self.tool_errors.get(tool,0) + 1
            self.recent_errors.appendleft({"tool":tool,"level":lv,"msg":msg[:120],"ts":e.get("ts","")})
            self.recent_calls.appendleft({
                "tool": tool, "status": "error",
                "level": lv,
                "duration_ms": dur,
                "collection": e.get("collection",""),
                "msg": msg[:100],
                "ts": e.get("ts",""),
            })

    def stats(self):
        tc = sum(self.tool_counts.values())
        te = sum(self.tool_errors.values())
        al = int(sum(e["ms"] for e in self.latency_history)/len(self.latency_history)) if self.latency_history else 0
        ts = sorted(self.tool_counts.items(), key=lambda x:x[1], reverse=True)[:12]
        tool_stats = [{"tool":t,"calls":c,"errors":self.tool_errors.get(t,0),
                       "avg_ms":int(sum(self.tool_durations[t])/len(self.tool_durations[t])) if self.tool_durations[t] else 0}
                      for t,c in ts]
        return {"uptime_seconds":int(time.time()-self.start_time),"total_calls":tc,"total_errors":te,
                "total_log_lines":self.total_parsed,"avg_latency_ms":al,
                "level_counts":dict(self.level_counts),"tool_stats":tool_stats,
                "latency_history":list(self.latency_history)[-30:],"recent_errors":list(self.recent_errors)[:10]}

state = DashboardState()

def _parse(line):
    line = line.strip()
    if not line: return None
    try: return json.loads(line)
    except: return {"msg":line,"level":"INFO","ts":datetime.now().isoformat()}

def _preload():
    if not os.path.exists(LOG_FILE): return
    try:
        with open(LOG_FILE) as f: lines = f.readlines()[-500:]
        for l in lines:
            e = _parse(l)
            if e: state.ingest(e)
    except: pass

_preload()

@app.get("/api/stats")
async def api_stats(): return JSONResponse(state.stats())

@app.get("/api/health")
async def api_health(): return JSONResponse({"status":"ok","ts":datetime.now().isoformat()})

@app.get("/api/calls")
async def api_calls():
    """Son tool çağrılarını döner — başarılı ve başarısız."""
    return JSONResponse({"calls": list(state.recent_calls)[:50]})

DOCKER_SOCK = "/var/run/docker.sock"

async def _docker_api(path: str) -> dict | list | None:
    """Docker unix socket üzerinden REST API çağrısı yapar."""
    import socket, urllib.parse
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(DOCKER_SOCK)
        sock.settimeout(5)
        request = f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n"
        sock.sendall(request.encode())
        response = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response += chunk
        sock.close()
        # HTTP response'u parse et
        header, _, body = response.partition(b"\r\n\r\n")
        return json.loads(body.decode(errors="replace"))
    except Exception as e:
        return {"error": str(e)}

async def _docker_logs_raw(name: str, tail: int = 300) -> str:
    """Container loglarını Docker API üzerinden çeker (timestamps dahil)."""
    import socket, struct
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(DOCKER_SOCK)
        sock.settimeout(10)
        path = f"/containers/{name}/logs?stdout=1&stderr=1&timestamps=1&tail={tail}"
        request = f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n"
        sock.sendall(request.encode())
        raw = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw += chunk
        sock.close()
        _, _, body = raw.partition(b"\r\n\r\n")
        # Docker multiplexed stream: 8-byte header + payload
        text = ""
        i = 0
        while i + 8 <= len(body):
            size = struct.unpack(">I", body[i+4:i+8])[0]
            payload = body[i+8:i+8+size]
            text += payload.decode(errors="replace")
            i += 8 + size
        return text if text.strip() else body.decode(errors="replace")
    except Exception as e:
        return f"error: {e}"

@app.get("/api/containers")
async def api_containers():
    """Çalışan container'ların listesini Docker socket üzerinden döner."""
    if not os.path.exists(DOCKER_SOCK):
        return JSONResponse({"containers": [], "error": "docker.sock bulunamadı"})
    data = await _docker_api("/containers/json?all=0")
    if isinstance(data, dict) and "error" in data:
        return JSONResponse({"containers": [], "error": data["error"]})
    containers = []
    for c in (data or []):
        name = (c.get("Names") or ["?"])[0].lstrip("/")
        status = c.get("Status", "")
        state  = c.get("State", "")
        image  = c.get("Image", "")
        healthy = "healthy" in status.lower()
        running = state.lower() == "running"
        containers.append({"name": name, "status": status, "image": image,
                           "healthy": healthy, "running": running})
    containers.sort(key=lambda x: x["name"])
    return JSONResponse({"containers": containers})

@app.get("/api/container-logs/{name}")
async def api_container_logs(name: str, lines: int = 300, level: str = ""):
    """Belirtilen container'ın loglarını Docker socket üzerinden döner."""
    safe = all(c.isalnum() or c in "-_." for c in name)
    if not safe:
        return JSONResponse({"error": "invalid container name"}, status_code=400)
    if not os.path.exists(DOCKER_SOCK):
        return JSONResponse({"name": name, "entries": [], "error": "docker.sock bulunamadı"})
    raw = await _docker_logs_raw(name, tail=lines)
    LO = {"DEBUG":0,"INFO":1,"WARNING":2,"ERROR":3,"CRITICAL":4}
    lf = level.upper() if level else ""
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Timestamp ayır: 2026-06-05T... <json veya plain>
        ts, _, rest = line.partition(" ")
        if not rest:
            rest, ts = ts, ""
        parsed = _parse(rest) or {"msg": rest, "level": "INFO"}
        if not parsed.get("ts"):
            parsed["ts"] = ts
        parsed["_container"] = name
        if lf:
            lv = (parsed.get("level") or "INFO").upper()
            if LO.get(lv,0) < LO.get(lf,0):
                continue
        entries.append(parsed)
    return JSONResponse({"name": name, "entries": entries})

@app.get("/api/logs")
async def api_logs(page: int = 1, per_page: int = 200, level: str = "", search: str = "", tool: str = ""):
    """Tüm log dosyasını sayfalandırılmış döner."""
    LO = {"DEBUG":0,"INFO":1,"WARNING":2,"ERROR":3,"CRITICAL":4}
    lf = level.upper() if level else ""
    sf = search.lower() if search else ""
    tf = tool.lower() if tool else ""
    entries = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                for line in f:
                    e = _parse(line)
                    if not e: continue
                    if lf and LO.get((e.get("level") or "INFO").upper(),0) < LO.get(lf,0): continue
                    if tf and tf not in (e.get("tool") or "").lower(): continue
                    if sf and sf not in json.dumps(e).lower(): continue
                    entries.append(e)
        except Exception: pass
    entries.reverse()  # Yeniden eskiye — en son log en üstte
    total = len(entries)
    start = (page - 1) * per_page
    return JSONResponse({
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "entries": entries[start:start + per_page],
    })

@app.get("/stream-logs")
async def stream_logs(request: Request, level: str = ""):
    LO = {"DEBUG":0,"INFO":1,"WARNING":2,"ERROR":3,"CRITICAL":4}
    lf = level.upper() if level else ""
    def ok(e):
        if lf and LO.get((e.get("level") or "INFO").upper(),0) < LO.get(lf,0): return False
        return True
    async def gen():
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f: lines = f.readlines()[-200:]
            for l in lines:
                e = _parse(l)
                if e and ok(e): yield f"data: {json.dumps(e)}\n\n"
        proc = await asyncio.create_subprocess_exec("tail","-F","-n","0",LOG_FILE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            while True:
                if await request.is_disconnected(): break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=15.0)
                    if line:
                        d = line.decode().strip()
                        if d:
                            e = _parse(d)
                            if e:
                                state.ingest(e)
                                if ok(e): yield f"data: {json.dumps(e)}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            try: proc.terminate()
            except: pass
    return StreamingResponse(gen(), media_type="text/event-stream")


HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GraphMCP</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
:root{--bg:#0d1117;--s1:#161b22;--s2:#21262d;--bd:#30363d;--tx:#c9d1d9;--mu:#8b949e;
  --blue:#58a6ff;--green:#3fb950;--yellow:#d29922;--orange:#f0883e;--red:#f85149;--purple:#bc8cff;--teal:#39d353;}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;overflow:hidden;}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:#484f58}
input{background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:6px 10px;font-size:12px;outline:none;width:100%}
input:focus{border-color:var(--blue)}
input::placeholder{color:#484f58}
button{cursor:pointer;}

/* Log level borders */
.LE-DEBUG{border-left:3px solid #2a2a2a;opacity:.75}
.LE-INFO{border-left:3px solid var(--blue)}
.LE-WARNING{border-left:3px solid var(--yellow)}
.LE-ERROR{border-left:3px solid var(--red);background:rgba(248,81,73,.04)}
.LE-CRITICAL{border-left:3px solid var(--red);background:rgba(248,81,73,.12);animation:cflash .5s}
@keyframes cflash{from{background:rgba(248,81,73,.4)}to{background:rgba(248,81,73,.12)}}

.LE-DEBUG .L-LV{color:#3a3a3a}
.LE-INFO .L-LV{color:var(--blue)}
.LE-WARNING .L-LV{color:var(--yellow)}
.LE-ERROR .L-LV,.LE-CRITICAL .L-LV{color:var(--red)}
.LE-WARNING .L-MSG{color:var(--orange)}
.LE-ERROR .L-MSG{color:#ffaaaa}
.LE-CRITICAL .L-MSG{color:#ff7070;font-weight:600}

/* Live pulse */
@keyframes lp{0%,100%{opacity:1}50%{opacity:.2}}
.live-pulse{animation:lp 2s infinite}

/* Pill */
.pill{padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid transparent;opacity:.55;transition:opacity .15s}
.pill:hover{opacity:.85}
.pill.on{opacity:1}

/* Tool row */
.tool-row{display:flex;align-items:center;gap:8px;padding:5px 12px;border-radius:5px;cursor:pointer;font-size:12px;color:var(--tx);transition:background .12s}
.tool-row:hover{background:var(--s2)}
.tool-row.sel{background:rgba(88,166,255,.1);color:var(--blue)}

/* Right panel sparkline */
.spark-wrap{background:var(--s2);border:1px solid var(--bd);border-radius:6px;padding:8px;height:72px;display:flex;align-items:center}

/* Overlay */
#drawer-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:40}
#drawer-bg.open{display:block}
#drawer{position:fixed;top:0;left:0;bottom:0;width:300px;background:var(--s1);border-right:1px solid var(--bd);z-index:41;display:flex;flex-direction:column;transform:translateX(-100%);transition:transform .25s}
#drawer.open{transform:translateX(0)}

/* Responsive hiding — pure CSS, no Tailwind responsive */
@media(max-width:767px){
  #left-panel{display:none!important}
  #right-panel{display:none!important}
  #mobile-topbar-btn{display:flex!important}
  #bottom-nav{display:flex!important}
  #desktop-tabs{display:none!important}
  #stats-bar{grid-template-columns:repeat(2,1fr)!important}
}
@media(min-width:768px) and (max-width:1199px){
  #right-panel{display:none!important}
}
@media(min-width:768px){
  #left-panel{display:flex!important}
  #mobile-topbar-btn{display:none!important}
  #bottom-nav{display:none!important}
  #desktop-tabs{display:flex!important}
}
</style>
</head>
<body style="display:flex;flex-direction:column;height:100vh;">

<!-- ████ TOPBAR ████ -->
<header style="flex-shrink:0;display:flex;align-items:center;gap:10px;padding:0 16px;height:50px;background:var(--s1);border-bottom:1px solid var(--bd);z-index:30;">

  <!-- Brand -->
  <div style="display:flex;align-items:center;gap:8px;margin-right:4px;flex-shrink:0;">
    <span id="dot" class="live-pulse" style="width:9px;height:9px;border-radius:50%;background:var(--red);display:inline-block;flex-shrink:0;"></span>
    <span style="font-size:15px;font-weight:700;color:#fff;letter-spacing:-.3px;">GraphMCP</span>
    <span style="font-size:12px;color:var(--mu);">Dashboard</span>
  </div>

  <!-- Desktop tabs -->
  <nav id="desktop-tabs" style="display:flex;gap:3px;">
    <button id="btn-logs" onclick="goTab('logs')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:var(--s2);color:#fff;font-weight:500;">📋 Logs</button>
    <button id="btn-metrics" onclick="goTab('metrics')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:transparent;color:var(--mu);font-weight:500;">📊 Metrics</button>
    <button id="btn-tools" onclick="goTab('tools')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:transparent;color:var(--mu);font-weight:500;">🔧 Tools</button>
    <button id="btn-allogs" onclick="goTab('allogs')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:transparent;color:var(--mu);font-weight:500;">📜 Tüm Loglar</button>
    <button id="btn-errors" onclick="goTab('errors')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:transparent;color:var(--red);font-weight:600;">🔴 Hatalar</button>
    <button id="btn-docker" onclick="goTab('docker')"
      style="font-size:12px;padding:5px 13px;border-radius:6px;border:none;background:transparent;color:var(--purple);font-weight:500;">🐳 Docker</button>
  </nav>

  <div style="flex:1;min-width:0;"></div>

  <!-- Quick search (desktop) -->
  <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
    <input id="top-search" oninput="refilter()" placeholder="🔍 hızlı ara..." style="width:180px;background:var(--s2);border:1px solid var(--bd);">
  </div>

  <!-- Clock -->
  <span id="clk" style="font-size:11px;color:var(--mu);font-family:monospace;font-variant-numeric:tabular-nums;white-space:nowrap;flex-shrink:0;"></span>

  <!-- Connection badge -->
  <span id="badge" style="font-size:11px;font-weight:700;padding:3px 11px;border-radius:20px;flex-shrink:0;background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3);">● OFFLINE</span>

  <!-- Mobile hamburger -->
  <button id="mobile-topbar-btn" onclick="openDrawer()" style="display:none;flex-shrink:0;padding:6px 9px;border-radius:6px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);font-size:15px;">☰</button>

</header>

<!-- ████ STAT CARDS ████ -->
<div id="stats-bar" style="flex-shrink:0;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:8px 12px;background:var(--bg);border-bottom:1px solid var(--bd);">
  <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:10px 14px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--mu);">Toplam Çağrı</div>
    <div id="sc-calls" style="font-size:24px;font-weight:800;color:var(--blue);font-variant-numeric:tabular-nums;line-height:1.2;">—</div>
    <div id="sc-calls-s" style="font-size:10px;color:var(--mu);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">yükleniyor...</div>
  </div>
  <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:10px 14px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--mu);">Hata</div>
    <div id="sc-err" style="font-size:24px;font-weight:800;color:var(--red);font-variant-numeric:tabular-nums;line-height:1.2;">—</div>
    <div id="sc-err-s" style="font-size:10px;color:var(--mu);margin-top:2px;">hata oranı</div>
  </div>
  <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:10px 14px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--mu);">Ort. Latency</div>
    <div id="sc-lat" style="font-size:24px;font-weight:800;color:var(--green);font-variant-numeric:tabular-nums;line-height:1.2;">—</div>
    <div style="font-size:10px;color:var(--mu);margin-top:2px;">ms</div>
  </div>
  <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:10px 14px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--mu);">Log Satırı</div>
    <div id="sc-lines" style="font-size:24px;font-weight:800;color:var(--orange);font-variant-numeric:tabular-nums;line-height:1.2;">—</div>
    <div id="sc-uptime" style="font-size:10px;color:var(--mu);margin-top:2px;">uptime</div>
  </div>
</div>

<!-- ████ MAIN ████ -->
<div style="flex:1;display:flex;overflow:hidden;">

  <!-- ▌LEFT PANEL ▌ -->
  <aside id="left-panel" style="width:210px;flex-shrink:0;flex-direction:column;background:var(--s1);border-right:1px solid var(--bd);overflow:hidden;">

    <!-- Level filter -->
    <div style="padding:11px 12px;border-bottom:1px solid var(--bd);">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:8px;">Log Seviyesi</div>
      <div id="pills" style="display:flex;flex-wrap:wrap;gap:5px;">
        <button class="pill" onclick="setLv('DEBUG',this)"    style="border-color:#333;color:#555;background:rgba(68,68,68,.1);">DEBUG</button>
        <button class="pill on" onclick="setLv('INFO',this)"  style="border-color:rgba(88,166,255,.45);color:var(--blue);background:rgba(88,166,255,.1);">INFO</button>
        <button class="pill" onclick="setLv('WARNING',this)"  style="border-color:rgba(210,153,34,.4);color:var(--yellow);background:rgba(210,153,34,.08);">WARN</button>
        <button class="pill" onclick="setLv('ERROR',this)"    style="border-color:rgba(248,81,73,.4);color:var(--red);background:rgba(248,81,73,.08);">ERROR</button>
        <button class="pill" onclick="setLv('CRITICAL',this)" style="border-color:var(--red);color:#ff7070;background:rgba(248,81,73,.15);">CRIT</button>
      </div>
    </div>

    <!-- Collection filter -->
    <div style="padding:10px 12px;border-bottom:1px solid var(--bd);">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:7px;">Collection Filtrele</div>
      <input id="coll-f" oninput="refilter()" placeholder="collection adı...">
    </div>

    <!-- Tool list -->
    <div style="padding:10px 12px 5px;flex-shrink:0;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);">Tool Aktivitesi</div>
    </div>
    <div id="tool-list" style="flex:1;overflow-y:auto;padding:0 4px 8px;"></div>

  </aside>

  <!-- ▌CENTER: TABS ▌ -->
  <div style="flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden;">

    <!-- ── LOGS TAB ── -->
    <div id="tab-logs" style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
      <!-- Log toolbar -->
      <div style="flex-shrink:0;display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:7px 12px;background:var(--s1);border-bottom:1px solid var(--bd);">
        <input id="srch" oninput="refilter()" placeholder="🔍 log içinde ara..." style="flex:1;min-width:100px;">
        <span id="lcnt" style="font-size:11px;color:var(--mu);white-space:nowrap;">0 satır</span>
        <label style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--mu);cursor:pointer;white-space:nowrap;">
          <input type="checkbox" id="asc" checked style="accent-color:var(--blue);width:auto;"> Kaydır
        </label>
        <button onclick="reconnect()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);" title="Yenile">↺ Yenile</button>
        <button onclick="exportLogs()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);" title="Export">⬇ Aktar</button>
        <button onclick="clrLogs()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);" title="Temizle">✕ Temizle</button>
      </div>
      <!-- Log stream -->
      <div id="logbox" style="flex:1;overflow-y:auto;font-family:'JetBrains Mono','Consolas',monospace;font-size:11.5px;line-height:1.7;"></div>
    </div>

    <!-- ── METRICS TAB ── -->
    <div id="tab-metrics" style="flex:1;display:none;overflow-y:auto;padding:14px;gap:14px;flex-direction:column;">

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;" id="tool-cards"></div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;flex-shrink:0;" class="charts-row">
        <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:14px;">
          <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:12px;">Log Dağılımı</div>
          <div id="lvbars-m"></div>
        </div>
        <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:14px;">
          <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:8px;">Latency Geçmişi</div>
          <canvas id="lat-canvas-m" style="display:block;width:100%;height:80px;"></canvas>
        </div>
      </div>

      <div style="background:var(--s1);border:1px solid var(--bd);border-radius:10px;padding:14px;">
        <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:10px;">Son Hatalar</div>
        <div id="errs-m"></div>
      </div>

    </div>

    <!-- ── TOOLS TAB ── -->
    <div id="tab-tools" style="flex:1;display:none;flex-direction:column;overflow:hidden;">
      <!-- Toolbar -->
      <div style="flex-shrink:0;display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--s1);border-bottom:1px solid var(--bd);flex-wrap:wrap;">
        <span style="font-size:12px;font-weight:600;color:#fff;">Son Tool Çağrıları</span>
        <div style="flex:1;"></div>
        <select id="tc-filter" onchange="fillTools()" style="background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 9px;font-size:12px;outline:none;cursor:pointer;">
          <option value="">Tümü</option>
          <option value="ok">✅ Başarılı</option>
          <option value="error">❌ Hatalı</option>
        </select>
        <button onclick="fillTools()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">↺ Yenile</button>
      </div>
      <!-- Table header -->
      <div style="flex-shrink:0;display:grid;grid-template-columns:24px 140px 1fr 110px 80px 64px;gap:0;padding:5px 12px;background:var(--s2);border-bottom:1px solid var(--bd);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--mu);">
        <span></span>
        <span>Tool</span>
        <span>Sorgu / Detay</span>
        <span>Collection</span>
        <span style="text-align:right;">Süre</span>
        <span style="text-align:right;">Saat</span>
      </div>
      <!-- Rows -->
      <div id="calls-list" style="flex:1;overflow-y:auto;"></div>
    </div>

    <!-- ── ALL LOGS TAB ── -->
    <div id="tab-allogs" style="flex:1;display:none;flex-direction:column;overflow:hidden;">
      <!-- Toolbar -->
      <div style="flex-shrink:0;display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:8px 12px;background:var(--s1);border-bottom:1px solid var(--bd);">
        <input id="al-search" oninput="alSearch()" placeholder="🔍 tüm loglarda ara..." style="flex:1;min-width:120px;">
        <select id="al-level" onchange="alSearch()" style="background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:6px 10px;font-size:12px;outline:none;cursor:pointer;">
          <option value="">Tüm Seviyeler</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
        <input id="al-tool" oninput="alSearch()" placeholder="tool adı..." style="width:130px;">
        <span id="al-info" style="font-size:11px;color:var(--mu);white-space:nowrap;"></span>
        <button onclick="alExport()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">⬇ Aktar</button>
        <button onclick="alRefresh()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">↺ Yenile</button>
      </div>
      <!-- Table header -->
      <div style="flex-shrink:0;display:grid;grid-template-columns:68px 56px 100px 1fr 110px 72px 60px;gap:0;padding:5px 12px;background:var(--s2);border-bottom:1px solid var(--bd);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--mu);">
        <span>Seviye</span>
        <span>Tarih/Saat</span>
        <span>Modül</span>
        <span>Mesaj</span>
        <span>Collection</span>
        <span style="text-align:right;">Süre</span>
        <span style="text-align:right;">Tool</span>
      </div>
      <!-- Rows -->
      <div id="al-box" style="flex:1;overflow-y:auto;"></div>
      <!-- Pagination -->
      <div style="flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px;background:var(--s1);border-top:1px solid var(--bd);">
        <button onclick="alPage(-1)" id="al-prev" style="padding:4px 12px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;font-size:12px;">← Önceki</button>
        <span id="al-pager" style="font-size:12px;color:var(--mu);min-width:100px;text-align:center;"></span>
        <button onclick="alPage(1)" id="al-next" style="padding:4px 12px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;font-size:12px;">Sonraki →</button>
      </div>
    </div>

    <!-- ── ERRORS TAB ── -->
    <div id="tab-errors" style="flex:1;display:none;flex-direction:column;overflow:hidden;">
      <!-- Toolbar -->
      <div style="flex-shrink:0;display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--s1);border-bottom:1px solid var(--bd);flex-wrap:wrap;">
        <span style="font-size:13px;font-weight:700;color:var(--red);">🔴 Sadece ERROR &amp; CRITICAL</span>
        <div style="flex:1;"></div>
        <input id="err-search" oninput="errSearch()" placeholder="🔍 hata içinde ara..."
          style="width:200px;background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 10px;font-size:12px;outline:none;">
        <select id="err-level" onchange="errSearch()" style="background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 9px;font-size:12px;outline:none;cursor:pointer;">
          <option value="">ERROR + CRITICAL</option>
          <option value="ERROR">Sadece ERROR</option>
          <option value="CRITICAL">Sadece CRITICAL</option>
        </select>
        <span id="err-count" style="font-size:11px;color:var(--red);font-weight:600;white-space:nowrap;"></span>
        <button onclick="errRefresh()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">↺ Yenile</button>
        <button onclick="errExport()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">⬇ Aktar</button>
      </div>
      <!-- Table header -->
      <div style="flex-shrink:0;display:grid;grid-template-columns:80px 56px 100px 1fr 110px 72px 60px;gap:0;padding:5px 12px;background:var(--s2);border-bottom:1px solid var(--bd);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--mu);">
        <span>Seviye</span>
        <span>Tarih/Saat</span>
        <span>Modül</span>
        <span>Mesaj / Hata Detayı</span>
        <span>Collection</span>
        <span style="text-align:right;">Süre</span>
        <span style="text-align:right;">Tool</span>
      </div>
      <!-- Rows -->
      <div id="err-box" style="flex:1;overflow-y:auto;"></div>
      <!-- Pagination -->
      <div style="flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:8px;padding:8px;background:var(--s1);border-top:1px solid var(--bd);">
        <button onclick="errPage(-1)" id="err-prev" style="padding:4px 12px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;font-size:12px;">← Önceki</button>
        <span id="err-pager" style="font-size:12px;color:var(--mu);min-width:100px;text-align:center;"></span>
        <button onclick="errPage(1)" id="err-next" style="padding:4px 12px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;font-size:12px;">Sonraki →</button>
      </div>
    </div>

    <!-- ── DOCKER TAB ── -->
    <div id="tab-docker" style="flex:1;display:none;flex-direction:column;overflow:hidden;">
      <!-- Container list toolbar -->
      <div style="flex-shrink:0;display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--s1);border-bottom:1px solid var(--bd);flex-wrap:wrap;">
        <span style="font-size:13px;font-weight:700;color:var(--purple);">🐳 Docker Container Logları</span>
        <div style="flex:1;"></div>
        <select id="dk-container" onchange="dkLoad()" style="background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 9px;font-size:12px;outline:none;cursor:pointer;min-width:180px;">
          <option value="">— Container seç —</option>
        </select>
        <select id="dk-level" onchange="dkLoad()" style="background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 9px;font-size:12px;outline:none;cursor:pointer;">
          <option value="">Tüm Seviyeler</option>
          <option value="WARNING">WARNING+</option>
          <option value="ERROR">ERROR+</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
        <input id="dk-lines" type="number" value="300" min="50" max="2000" style="width:70px;background:var(--s2);border:1px solid var(--bd);color:var(--tx);border-radius:6px;padding:5px 8px;font-size:12px;outline:none;" title="Satır sayısı">
        <button onclick="dkLoad()" style="font-size:11px;padding:4px 10px;border-radius:5px;background:var(--s2);border:1px solid var(--bd);color:var(--mu);cursor:pointer;">↺ Yükle</button>
      </div>
      <!-- Container health cards -->
      <div id="dk-cards" style="flex-shrink:0;display:flex;flex-wrap:wrap;gap:8px;padding:8px 12px;background:var(--bg);border-bottom:1px solid var(--bd);"></div>
      <!-- Table header -->
      <div id="dk-thead" style="flex-shrink:0;display:none;grid-template-columns:68px 56px 100px 1fr 110px 72px 60px;gap:0;padding:5px 12px;background:var(--s2);border-bottom:1px solid var(--bd);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--mu);">
        <span>Seviye</span><span>Tarih/Saat</span><span>Modül</span><span>Mesaj</span><span>Collection</span><span style="text-align:right;">Süre</span><span style="text-align:right;">Tool</span>
      </div>
      <!-- Log rows -->
      <div id="dk-box" style="flex:1;overflow-y:auto;"></div>
    </div>

  </div>

  <!-- ▌RIGHT PANEL ▌ -->
  <aside id="right-panel" style="width:210px;flex-shrink:0;flex-direction:column;background:var(--s1);border-left:1px solid var(--bd);overflow-y:auto;">

    <!-- Level distribution -->
    <div style="padding:11px 12px;border-bottom:1px solid var(--bd);">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:10px;">Dağılım</div>
      <div id="lvbars-r"></div>
    </div>

    <!-- Latency sparkline -->
    <div style="padding:11px 12px;border-bottom:1px solid var(--bd);">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:7px;">Latency</div>
      <div class="spark-wrap">
        <canvas id="lat-canvas-r" style="display:block;width:100%;height:52px;"></canvas>
      </div>
    </div>

    <!-- Recent errors -->
    <div style="padding:11px 12px;flex:1;">
      <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:8px;">Son Hatalar</div>
      <div id="errs-r"></div>
    </div>

  </aside>

</div><!-- /main -->

<!-- ████ MOBILE BOTTOM NAV ████ -->
<nav id="bottom-nav" style="display:none;flex-shrink:0;background:var(--s1);border-top:1px solid var(--bd);height:54px;">
  <div style="display:flex;height:100%;">
    <button id="mbn-logs" onclick="goTab('logs')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:600;color:var(--blue);">
      <span style="font-size:20px;">📋</span>Logs
    </button>
    <button id="mbn-metrics" onclick="goTab('metrics')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:500;color:var(--mu);">
      <span style="font-size:20px;">📊</span>Metrics
    </button>
    <button id="mbn-tools" onclick="goTab('tools')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:500;color:var(--mu);">
      <span style="font-size:20px;">🔧</span>Tools
    </button>
    <button id="mbn-allogs" onclick="goTab('allogs')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:500;color:var(--mu);">
      <span style="font-size:20px;">📜</span>Tümü
    </button>
    <button id="mbn-errors" onclick="goTab('errors')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:600;color:var(--red);">
      <span style="font-size:20px;">🔴</span>Hatalar
    </button>
    <button id="mbn-docker" onclick="goTab('docker')"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:500;color:var(--mu);">
      <span style="font-size:20px;">🐳</span>Docker
    </button>
    <button onclick="openDrawer()"
      style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:none;background:transparent;font-size:10px;font-weight:500;color:var(--mu);">
      <span style="font-size:20px;">☰</span>Filtre
    </button>
  </div>
</nav>

<!-- ████ MOBILE DRAWER OVERLAY ████ -->
<div id="drawer-bg" onclick="closeDrawer()"></div>
<div id="drawer">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--bd);flex-shrink:0;">
    <span style="font-size:13px;font-weight:700;color:#fff;">Filtreler & Araçlar</span>
    <button onclick="closeDrawer()" style="background:none;border:none;color:var(--mu);font-size:20px;line-height:1;">✕</button>
  </div>

  <div style="padding:12px 14px;border-bottom:1px solid var(--bd);">
    <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:8px;">Log Seviyesi</div>
    <div id="d-pills" style="display:flex;flex-wrap:wrap;gap:6px;">
      <button class="pill dpill" onclick="setLv('DEBUG',this,1)"    style="border-color:#333;color:#555;background:rgba(68,68,68,.1);padding:5px 12px;">DEBUG</button>
      <button class="pill dpill on" onclick="setLv('INFO',this,1)"  style="border-color:rgba(88,166,255,.45);color:var(--blue);background:rgba(88,166,255,.1);padding:5px 12px;">INFO</button>
      <button class="pill dpill" onclick="setLv('WARNING',this,1)"  style="border-color:rgba(210,153,34,.4);color:var(--yellow);background:rgba(210,153,34,.08);padding:5px 12px;">WARN</button>
      <button class="pill dpill" onclick="setLv('ERROR',this,1)"    style="border-color:rgba(248,81,73,.4);color:var(--red);background:rgba(248,81,73,.08);padding:5px 12px;">ERROR</button>
      <button class="pill dpill" onclick="setLv('CRITICAL',this,1)" style="border-color:var(--red);color:#ff7070;background:rgba(248,81,73,.15);padding:5px 12px;">CRIT</button>
    </div>
  </div>

  <div style="padding:12px 14px;border-bottom:1px solid var(--bd);">
    <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);margin-bottom:8px;">Collection</div>
    <input id="d-coll" oninput="syncColl(this)" placeholder="collection adı..." style="padding:8px 12px;">
  </div>

  <div style="padding:10px 14px 5px;flex-shrink:0;">
    <div style="font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mu);">Tool Aktivitesi</div>
  </div>
  <div id="d-tool-list" style="flex:1;overflow-y:auto;padding:0 6px 12px;"></div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────────
let ALL=[], FIL=[], ES=null, RETRIES=0, LV_F='INFO', TOOL_F='';
const LO={DEBUG:0,INFO:1,WARNING:2,ERROR:3,CRITICAL:4};
let lastStats = null;

// ── Timestamp formatter — tarih + saat ────────────────────────────────────────
function fmtTs(ts){
  if(!ts) return '--:--';
  const d=new Date(ts);
  if(isNaN(d)) return ts.slice(0,19).replace('T',' ');
  const dd=String(d.getDate()).padStart(2,'0');
  const mo=String(d.getMonth()+1).padStart(2,'0');
  const HH=String(d.getHours()).padStart(2,'0');
  const MM=String(d.getMinutes()).padStart(2,'0');
  const SS=String(d.getSeconds()).padStart(2,'0');
  return `${dd}.${mo} ${HH}:${MM}:${SS}`;
}

// ── Flood/startup log deduplication ───────────────────────────────────────────
// Startup mesajları aynı oturumda 1 kez gösterilir, sonrasında bastırılır
const DEDUP_ONCE_MSGS = [
  'logging başlatıldı','logging configured',
  'opentelemetry başlatıldı','telemetry initialized',
  'mcp server başlatılıyor','mcp server started','application startup complete',
  'uvicorn running','started server process','waiting for application startup',
];
const DEDUP_WIN  = 300000; // 5 dk içinde aynı mesaj tekrarsa atla
const _dedupSeen = {};
function isDuplicate(d){
  const msg=(d.msg||'').toLowerCase();
  const key=(d.logger||'')+':'+msg;
  const now=Date.now();
  // Startup noise: ilk gösterimde kaydet, tekrarında bastır
  const isNoise = DEDUP_ONCE_MSGS.some(m=>msg.includes(m));
  const win = isNoise ? DEDUP_WIN : 0; // noise için 5dk, diğerleri için dedup yok
  if(win>0 && _dedupSeen[key] && (now-_dedupSeen[key])<win) return true;
  if(win>0) _dedupSeen[key]=now;
  return false;
}

// ── Clock ──────────────────────────────────────────────────────────────────────
setInterval(()=>{ const e=document.getElementById('clk'); if(e) e.textContent=fmtTs(new Date().toISOString()); },1000);

// ── Tab switch ─────────────────────────────────────────────────────────────────
const TAB_IDS = ['logs','metrics','tools','allogs','errors','docker'];
function goTab(name){
  TAB_IDS.forEach(t=>{
    const tab=document.getElementById('tab-'+t);
    if(tab) tab.style.display=(t===name)?'flex':'none';
    // desktop btns
    const b=document.getElementById('btn-'+t);
    if(b){ b.style.background=(t===name)?'var(--s2)':'transparent'; b.style.color=(t===name)?'#fff':'var(--mu)'; }
    // mobile btns
    const mb=document.getElementById('mbn-'+t);
    if(mb) mb.style.color=(t===name)?'var(--blue)':'var(--mu)';
  });
  if(name==='metrics') fillMetrics();
  if(name==='tools')   fillTools();
  if(name==='allogs')  alLoad();
  if(name==='errors')  errLoad();
  if(name==='docker')  dkInit();
  closeDrawer();
}

// ── Drawer ─────────────────────────────────────────────────────────────────────
function openDrawer(){
  document.getElementById('drawer-bg').classList.add('open');
  document.getElementById('drawer').classList.add('open');
  syncDrawerTools();
}
function closeDrawer(){
  document.getElementById('drawer-bg').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}
function syncColl(el){
  document.getElementById('coll-f').value=el.value;
  refilter();
}

// ── SSE ────────────────────────────────────────────────────────────────────────
function connect(){
  if(ES) ES.close();
  setBadge('c');
  ES=new EventSource('/stream-logs');
  ES.onopen=()=>{ setBadge('l'); RETRIES=0; };
  ES.onmessage=ev=>{ try{ const d=JSON.parse(ev.data); if(d.type==='ping') return; push(d); }catch{} };
  ES.onerror=()=>{ setBadge('o'); ES.close(); setTimeout(connect,Math.min(1000*2**RETRIES++,10000)); };
}
function setBadge(s){
  const b=document.getElementById('badge'), d=document.getElementById('dot');
  const M={l:['● LIVE','rgba(63,185,80,.15)','var(--green)','rgba(63,185,80,.35)','var(--green)'],
           c:['● CONNECTING','rgba(210,153,34,.15)','var(--yellow)','rgba(210,153,34,.35)','var(--yellow)'],
           o:['○ OFFLINE','rgba(248,81,73,.15)','var(--red)','rgba(248,81,73,.35)','var(--red)']};
  const [txt,bg,col,bdr,dot]=M[s];
  b.textContent=txt;
  b.style.cssText=`font-size:11px;font-weight:700;padding:3px 11px;border-radius:20px;flex-shrink:0;background:${bg};color:${col};border:1px solid ${bdr};`;
  d.style.background=dot;
}
function reconnect(){
  ALL=[]; FIL=[];
  // Dedup cache'i temizle — yoksa replay edilen loglar hep bloklanır
  Object.keys(_dedupSeen).forEach(k=>delete _dedupSeen[k]);
  document.getElementById('logbox').innerHTML='';
  updCnt();
  connect();
}

// ── Entry push & render ────────────────────────────────────────────────────────
function push(d){
  ALL.push(d); if(ALL.length>3000) ALL.shift();
  if(ok(d)){ FIL.push(d); draw(d); updCnt(); }
}

function ok(d){
  const lv=(d.level||'INFO').toUpperCase();
  if((LO[lv]||0)<(LO[LV_F]||0)) return false;
  if(TOOL_F && (d.tool||'').toLowerCase()!==TOOL_F) return false;
  const cf=document.getElementById('coll-f').value.toLowerCase();
  if(cf && !(d.collection||'').toLowerCase().includes(cf)) return false;
  const sf=(document.getElementById('srch').value||document.getElementById('top-search').value||'').toLowerCase();
  if(sf && !JSON.stringify(d).toLowerCase().includes(sf)) return false;
  if(isDuplicate(d)) return false;
  return true;
}

function drawTo(box,d){
  const lv=(d.level||'INFO').toUpperCase();
  const ts=fmtTs(d.ts);
  const lg=d.logger?d.logger.split('.').pop().slice(0,14):'';
  const msg=(d.msg||'').replace(/</g,'&lt;');

  let tags='';
  if(d.collection) tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid rgba(57,211,83,.22);color:var(--teal);margin-right:3px;">${d.collection}</span>`;
  if(d.query)      tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid rgba(220,205,170,.2);color:#dcdcaa;margin-right:3px;max-width:130px;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;">🔍 ${String(d.query).slice(0,32)}</span>`;
  if(d.model){
    const mn=String(d.model).split('/').pop().replace(':free','').slice(0,22);
    tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid rgba(139,92,246,.3);color:#a78bfa;margin-right:3px;">🤖 ${mn}</span>`;
  }
  if(d.pct!=null){
    const pct=Number(d.pct);
    const clr=pct>=100?'var(--green)':pct>=50?'var(--blue)':'var(--yellow)';
    tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid rgba(255,255,255,.12);color:${clr};margin-right:3px;">📦 ${d.indexed_files||'?'}/${d.total_files||'?'} dosya %${pct}</span>`;
  }
  if(d.eta){
    tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid rgba(255,255,255,.1);color:var(--mu);margin-right:3px;">⏳ ${d.eta}</span>`;
  }
  if(d.duration_ms){ const slow=+d.duration_ms>2000; tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid ${slow?'rgba(240,136,62,.3)':'rgba(63,185,80,.2)'};color:${slow?'var(--orange)':'var(--green)'};margin-right:3px;">⏱ ${d.duration_ms}ms</span>`; }
  if(d.project_path){ const sh=String(d.project_path).split('/').pop(); tags+=`<span style="display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid var(--bd);color:var(--mu);margin-right:3px;">${sh}</span>`; }

  let exc='';
  if(d.exc){ const lines=String(d.exc).split('\n').slice(-5).join('\n'); exc=`<div style="font-size:10px;color:var(--red);background:rgba(248,81,73,.07);border-radius:4px;padding:4px 8px;margin-top:4px;white-space:pre-wrap;max-height:60px;overflow:hidden;cursor:pointer;border:1px solid rgba(248,81,73,.15);" onclick="this.style.maxHeight=this.style.maxHeight?null:'60px'">${lines.replace(/</g,'&lt;')}</div>`; }

  const el=document.createElement('div');
  el.className=`LE-${lv}`;
  el.style.cssText='display:flex;align-items:flex-start;gap:8px;padding:3px 12px;transition:background .1s;';
  el.onmouseenter=function(){this.style.background='rgba(255,255,255,.03)'};
  el.onmouseleave=function(){this.style.background=''};
  el.innerHTML=`
    <span class="L-LV" style="font-size:10px;font-weight:700;min-width:50px;flex-shrink:0;padding-top:2px;font-variant-numeric:tabular-nums;">${lv}</span>
    <span style="font-size:10px;color:var(--mu);min-width:54px;flex-shrink:0;font-variant-numeric:tabular-nums;padding-top:2px;">${ts}</span>
    <span style="font-size:10px;color:#4ec9b0;opacity:.7;min-width:90px;max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;padding-top:2px;">${lg}</span>
    <div style="flex:1;min-width:0;">
      <div class="L-MSG">${d.tool?`<span style="color:#569cd6;font-weight:700;margin-right:6px;font-size:12px;">${d.tool}</span>`:''}<span style="word-break:break-word;">${msg}</span></div>
      ${tags?`<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:3px;">${tags}</div>`:''}
      ${exc}
    </div>`;
  box.appendChild(el);
  if(box.children.length>2500) box.removeChild(box.firstChild);
  if(box.id==='logbox' && document.getElementById('asc').checked) box.scrollTop=box.scrollHeight;
}

function draw(d){ drawTo(document.getElementById('logbox'),d); }

function updCnt(){ document.getElementById('lcnt').textContent=FIL.length+' satır'; }

// ── Filters ────────────────────────────────────────────────────────────────────
function setLv(lv,btn,drawer){
  LV_F=lv;
  const sel=drawer?'.dpill':'.pill:not(.dpill)';
  document.querySelectorAll(sel).forEach(p=>{ p.classList.remove('on'); p.style.opacity='.55'; p.style.fontWeight='600'; });
  btn.classList.add('on'); btn.style.opacity='1'; btn.style.fontWeight='700';
  refilter();
}

function refilter(){
  const s=(document.getElementById('srch').value||document.getElementById('top-search').value||'').toLowerCase();
  FIL=ALL.filter(d=>ok(d));
  const box=document.getElementById('logbox');
  box.innerHTML='';
  FIL.slice(-500).forEach(draw);
  updCnt();
}

function setTool(name,fromDrawer){
  TOOL_F=TOOL_F===name?'':name;
  document.querySelectorAll('.tool-row').forEach(r=>{r.classList.remove('sel');});
  if(TOOL_F){ document.querySelectorAll(`.tool-row[data-t="${name}"]`).forEach(r=>r.classList.add('sel')); }
  refilter();
  if(fromDrawer) closeDrawer();
}

// ── Actions ────────────────────────────────────────────────────────────────────
function clrLogs(){ ALL=[]; FIL=[]; document.getElementById('logbox').innerHTML=''; updCnt(); }
function exportLogs(){ const b=new Blob([ALL.map(e=>JSON.stringify(e)).join('\n')],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download='graphmcp-'+Date.now()+'.jsonl'; a.click(); }

// ── Stats polling ──────────────────────────────────────────────────────────────
async function fetchStats(){
  try{
    const s=await(await fetch('/api/stats')).json();
    lastStats=s;
    document.getElementById('sc-calls').textContent=s.total_calls.toLocaleString();
    document.getElementById('sc-err').textContent=s.total_errors.toLocaleString();
    document.getElementById('sc-lat').textContent=s.avg_latency_ms;
    document.getElementById('sc-lines').textContent=s.total_log_lines.toLocaleString();
    const h=s.uptime_seconds,hh=Math.floor(h/3600),mm=Math.floor((h%3600)/60);
    document.getElementById('sc-uptime').textContent=`${hh}s ${mm}dk çalışıyor`;
    const r=s.total_calls>0?((s.total_errors/s.total_calls)*100).toFixed(1):'0.0';
    document.getElementById('sc-err-s').textContent=r+'% hata oranı';
    document.getElementById('sc-calls-s').textContent=(s.tool_stats||[]).length+' farklı tool';
    fillToolList(s.tool_stats||[]);
    fillLvBars(s.level_counts||{}, 'lvbars-r');
    fillSparkline(s.latency_history||[], 'lat-canvas-r');
    fillErrors(s.recent_errors||[], 'errs-r');
  }catch{}
}

function fillToolList(tools){
  const mk=(id,drawer)=>tools.map(t=>`
    <div class="tool-row" data-t="${t.tool}" onclick="setTool('${t.tool}'${drawer?',true':''})" style="display:flex;align-items:center;gap:8px;padding:5px 12px;border-radius:5px;cursor:pointer;font-size:12px;color:var(--tx);">
      <span style="width:6px;height:6px;border-radius:50%;flex-shrink:0;background:${t.errors>0?'var(--red)':'var(--green)'}"></span>
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${t.tool}">${t.tool}</span>
      <span style="color:var(--mu);font-size:11px;font-variant-numeric:tabular-nums;">${t.calls}</span>
    </div>`).join('');
  document.getElementById('tool-list').innerHTML=mk('tool-list',false);
  document.getElementById('d-tool-list').innerHTML=mk('d-tool-list',true);
  if(TOOL_F) document.querySelectorAll(`.tool-row[data-t="${TOOL_F}"]`).forEach(r=>r.classList.add('sel'));
}

function syncDrawerTools(){ /* already synced in fillToolList */ }

function fillLvBars(counts, id){
  const el=document.getElementById(id); if(!el) return;
  const levs=[{k:'INFO',c:'var(--blue)'},{k:'WARNING',c:'var(--yellow)'},{k:'ERROR',c:'var(--red)'},{k:'CRITICAL',c:'#ff4040'},{k:'DEBUG',c:'#2a2a2a'}];
  const tot=Math.max(Object.values(counts).reduce((a,b)=>a+b,0),1);
  el.innerHTML=levs.map(({k,c})=>{
    const n=counts[k]||0, p=Math.round((n/tot)*100);
    return `<div style="display:flex;align-items:center;gap:7px;margin-bottom:7px;">
      <span style="font-size:10px;font-weight:700;min-width:50px;color:${c};">${k}</span>
      <div style="flex:1;height:5px;background:var(--s2);border-radius:3px;overflow:hidden;">
        <div style="width:${p}%;height:100%;background:${c};border-radius:3px;transition:width .5s;"></div>
      </div>
      <span style="font-size:10px;color:var(--mu);min-width:28px;text-align:right;font-variant-numeric:tabular-nums;">${n}</span>
    </div>`;
  }).join('');
}

function fillSparkline(hist, id){
  const c=document.getElementById(id); if(!c||!hist.length) return;
  const W=c.parentElement.clientWidth-2, H=parseInt(c.style.height)||52;
  c.width=W; c.height=H;
  const ctx=c.getContext('2d');
  ctx.clearRect(0,0,W,H);
  const vals=hist.map(e=>e.ms), max=Math.max(...vals,100);
  ctx.strokeStyle='var(--blue)'; ctx.lineWidth=1.5; ctx.beginPath();
  vals.forEach((v,i)=>{ const x=(i/(vals.length-1))*W, y=H-(v/max)*(H-4)-2; i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); });
  ctx.stroke();
  ctx.lineTo(W,H); ctx.lineTo(0,H); ctx.closePath();
  ctx.fillStyle='rgba(88,166,255,.08)'; ctx.fill();
}

function fillErrors(errs, id){
  const el=document.getElementById(id); if(!el) return;
  if(!errs.length){ el.innerHTML='<div style="font-size:11px;color:var(--mu);text-align:center;padding:8px 0;">✓ Hata yok</div>'; return; }
  el.innerHTML=errs.map(e=>`
    <div style="padding:6px 0;border-bottom:1px solid var(--bd);">
      <div style="font-size:11px;font-weight:700;color:var(--red);">${e.level} · ${e.tool||'?'}</div>
      <div style="font-size:11px;color:var(--mu);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${(e.msg||'').replace(/</g,'&lt;')}</div>
      <div style="font-size:10px;color:#444;">${e.ts?fmtTs(e.ts):''}</div>
    </div>`).join('');
}

// ── Metrics tab ────────────────────────────────────────────────────────────────
function fillMetrics(){
  if(!lastStats) return;
  const s=lastStats;
  fillLvBars(s.level_counts||{}, 'lvbars-m');
  fillSparkline(s.latency_history||[], 'lat-canvas-m');
  fillErrors(s.recent_errors||[], 'errs-m');
  document.getElementById('tool-cards').innerHTML=(s.tool_stats||[]).map(t=>`
    <div style="background:var(--s2);border:1px solid var(--bd);border-radius:10px;padding:14px;">
      <div style="font-weight:700;color:#fff;font-size:13px;margin-bottom:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${t.tool}">⚡ ${t.tool}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;">
        <div>
          <div style="font-size:9px;text-transform:uppercase;color:var(--mu);letter-spacing:.5px;margin-bottom:2px;">Çağrı</div>
          <div style="font-size:22px;font-weight:800;color:var(--blue);font-variant-numeric:tabular-nums;">${t.calls}</div>
        </div>
        <div>
          <div style="font-size:9px;text-transform:uppercase;color:var(--mu);letter-spacing:.5px;margin-bottom:2px;">Hata</div>
          <div style="font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;color:${t.errors>0?'var(--red)':'var(--green)'};">${t.errors}</div>
        </div>
        <div>
          <div style="font-size:9px;text-transform:uppercase;color:var(--mu);letter-spacing:.5px;margin-bottom:2px;">ms</div>
          <div style="font-size:22px;font-weight:800;color:var(--orange);font-variant-numeric:tabular-nums;">${t.avg_ms}</div>
        </div>
      </div>
      <div style="margin-top:10px;height:4px;background:var(--s1);border-radius:2px;overflow:hidden;">
        <div style="height:100%;border-radius:2px;background:${t.errors>0?'var(--red)':'var(--blue)'};width:${Math.min(100,t.calls*2)}%;transition:width .5s;"></div>
      </div>
    </div>`).join('');
}

// ── Tools tab ──────────────────────────────────────────────────────────────────
async function fillTools(){
  const el=document.getElementById('calls-list');
  try{
    const r=await fetch('/api/calls');
    const d=await r.json();
    let calls=d.calls||[];
    const f=document.getElementById('tc-filter').value;
    if(f) calls=calls.filter(c=>c.status===f);
    if(!calls.length){
      el.innerHTML='<div style="color:var(--mu);font-size:12px;text-align:center;padding:30px;">Henüz kayıt yok — bir tool çağrısı bekleniyor</div>';
      return;
    }
    el.innerHTML=calls.map(c=>{
      const ok=c.status==='ok';
      const icon=ok?'<span style="color:var(--green);font-size:14px;">✓</span>':'<span style="color:var(--red);font-size:14px;">✕</span>';
      const detail=ok?(c.query?`<span style="color:#dcdcaa;">🔍 ${String(c.query).slice(0,60)}</span>`:'<span style="color:var(--mu);">—</span>')
                     :`<span style="color:var(--red);">${(c.msg||'hata').replace(/</g,'&lt;').slice(0,70)}</span>`;
      const dur=c.duration_ms?`<span style="${+c.duration_ms>2000?'color:var(--orange)':'color:var(--green)'}">${c.duration_ms}ms</span>`:'<span style="color:#444;">—</span>';
      const ts=c.ts?new Date(c.ts).toLocaleTimeString('tr-TR'):'';
      return `<div style="display:grid;grid-template-columns:24px 140px 1fr 110px 80px 64px;gap:0;align-items:center;padding:7px 12px;border-bottom:1px solid rgba(48,54,61,.6);font-size:12px;transition:background .1s;" onmouseenter="this.style.background='rgba(255,255,255,.03)'" onmouseleave="this.style.background=''">
        <span>${icon}</span>
        <span style="color:var(--blue);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${c.tool}">${c.tool||'?'}</span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:12px;">${detail}</span>
        <span style="color:var(--teal);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${c.collection||'—'}</span>
        <span style="text-align:right;font-variant-numeric:tabular-nums;">${dur}</span>
        <span style="text-align:right;color:var(--mu);font-size:11px;font-variant-numeric:tabular-nums;">${ts}</span>
      </div>`;
    }).join('');
  }catch(e){
    el.innerHTML='<div style="color:var(--red);font-size:12px;text-align:center;padding:20px;">Veriler yüklenemedi</div>';
  }
}

// ── All Logs Tab ───────────────────────────────────────────────────────────────
let AL_PAGE=1, AL_TOTAL=0, AL_PAGES=1, AL_DATA=[];

// Tablo satırı — Tüm Loglar ve Hatalar tabları için ortak renderer
const AL_COLS = '68px 104px 100px 1fr 110px 72px 60px';

function drawTableRow(box, d, cols){
  const lv  = (d.level||'INFO').toUpperCase();
  const ts  = fmtTs(d.ts);
  const lg  = d.logger ? d.logger.split('.').pop().slice(0,14) : '';
  const msg = (d.msg||'').replace(/</g,'&lt;');
  const col = d.collection || '';
  const dur = d.duration_ms;
  const tool= d.tool || '';

  const lvCfg = {
    DEBUG:    'color:#555;background:rgba(68,68,68,.2)',
    INFO:     'color:var(--blue);background:rgba(88,166,255,.12)',
    WARNING:  'color:var(--yellow);background:rgba(210,153,34,.12)',
    ERROR:    'color:var(--red);background:rgba(248,81,73,.15)',
    CRITICAL: 'color:#ff4040;background:rgba(248,81,73,.25)',
  }[lv] || 'color:var(--mu);background:rgba(68,68,68,.1)';

  const durHtml = dur
    ? `<span style="font-variant-numeric:tabular-nums;${+dur>2000?'color:var(--orange)':'color:var(--green)'}">${dur}ms</span>`
    : '<span style="color:#333;">—</span>';

  let excHtml = '';
  if(d.exc){
    const lines = String(d.exc).split('\n').slice(-3).join(' ↵ ').slice(0,120);
    excHtml = `<span style="display:block;font-size:10px;color:var(--red);opacity:.75;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${lines.replace(/"/g,"'")}">${lines.replace(/</g,'&lt;')}</span>`;
  }

  const rowBg = lv==='CRITICAL'?'rgba(248,81,73,.07)' : lv==='ERROR'?'rgba(248,81,73,.03)' : '';
  const msgColor = lv==='CRITICAL'?'color:#ff8080;font-weight:600' : lv==='ERROR'?'color:#ffaaaa' : lv==='WARNING'?'color:var(--orange)' : 'color:var(--tx)';

  const row = document.createElement('div');
  row.style.cssText = `display:grid;grid-template-columns:${cols};gap:0;align-items:start;padding:6px 12px;border-bottom:1px solid rgba(48,54,61,.5);font-size:12px;cursor:default;transition:background .1s;background:${rowBg};`;
  row.onmouseenter = function(){ this.style.background='rgba(255,255,255,.04)'; };
  row.onmouseleave = function(){ this.style.background=rowBg; };
  row.innerHTML = `
    <span style="padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;${lvCfg};white-space:nowrap;display:inline-block;line-height:1.4;">${lv}</span>
    <span style="color:var(--mu);font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap;padding-top:2px;">${ts}</span>
    <span style="color:#4ec9b0;font-size:11px;opacity:.7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-top:2px;" title="${lg}">${lg||'—'}</span>
    <span style="overflow:hidden;padding-right:10px;min-width:0;">
      <span style="${msgColor};word-break:break-word;">${msg}</span>${excHtml}
    </span>
    <span style="color:var(--teal);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-top:2px;" title="${col}">${col||'—'}</span>
    <span style="text-align:right;padding-top:2px;">${durHtml}</span>
    <span style="text-align:right;color:var(--blue);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-top:2px;" title="${tool}">${tool||'—'}</span>`;
  box.appendChild(row);
}

async function alLoad(){
  const search = document.getElementById('al-search').value;
  const level  = document.getElementById('al-level').value;
  const tool   = document.getElementById('al-tool').value;
  const params = new URLSearchParams({page:AL_PAGE,per_page:200});
  if(level)  params.set('level',level);
  if(search) params.set('search',search);
  if(tool)   params.set('tool',tool);
  try{
    const r = await fetch('/api/logs?'+params);
    const d = await r.json();
    AL_TOTAL=d.total; AL_PAGES=d.pages; AL_DATA=d.entries||[];
    const box=document.getElementById('al-box');
    box.innerHTML='';
    if(!AL_DATA.length){
      box.innerHTML='<div style="color:var(--mu);font-size:12px;text-align:center;padding:30px;">Kayıt bulunamadı</div>';
    } else {
      AL_DATA.forEach(e=>drawTableRow(box,e,AL_COLS));
      box.scrollTop=0;
    }
    document.getElementById('al-info').textContent=`${AL_TOTAL.toLocaleString()} kayıt`;
    document.getElementById('al-pager').textContent=`Sayfa ${AL_PAGE} / ${AL_PAGES}`;
    document.getElementById('al-prev').style.opacity=AL_PAGE<=1?'.4':'1';
    document.getElementById('al-next').style.opacity=AL_PAGE>=AL_PAGES?'.4':'1';
  }catch(e){ console.error(e); }
}

function alSearch(){ AL_PAGE=1; alLoad(); }
function alRefresh(){ alLoad(); }
function alPage(dir){ AL_PAGE=Math.max(1,Math.min(AL_PAGES,AL_PAGE+dir)); alLoad(); }
function alExport(){
  const blob=new Blob([AL_DATA.map(e=>JSON.stringify(e)).join('\n')],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='graphmcp-alllogs-p'+AL_PAGE+'-'+Date.now()+'.jsonl'; a.click();
}

// ── Errors Tab ─────────────────────────────────────────────────────────────────
let ERR_PAGE=1, ERR_PAGES=1, ERR_DATA=[];

async function errLoad(){
  const search = document.getElementById('err-search').value;
  const lvSel  = document.getElementById('err-level').value;
  // level parametresi: seçili seviyeye göre ya ERROR ya CRITICAL ya ikisi de
  const levelParam = lvSel || 'ERROR';
  const params = new URLSearchParams({page:ERR_PAGE, per_page:200, level:levelParam});
  if(search) params.set('search', search);
  try{
    const r = await fetch('/api/logs?' + params);
    const d = await r.json();
    // Eğer sadece ERROR seçildiyse CRITICAL'i çıkar, sadece CRITICAL seçildiyse ERROR'ı çıkar
    let entries = d.entries || [];
    if(lvSel === 'ERROR')    entries = entries.filter(e=>(e.level||'').toUpperCase()==='ERROR');
    if(lvSel === 'CRITICAL') entries = entries.filter(e=>(e.level||'').toUpperCase()==='CRITICAL');
    // Sadece ERROR ve CRITICAL göster
    else entries = entries.filter(e=>['ERROR','CRITICAL'].includes((e.level||'').toUpperCase()));

    ERR_DATA = entries;
    ERR_PAGES = Math.max(1, Math.ceil(d.total / 200));

    const box = document.getElementById('err-box');
    box.innerHTML = '';
    if(!entries.length){
      box.innerHTML = '<div style="color:var(--green);font-size:13px;font-weight:600;text-align:center;padding:40px;">✅ Bu aralıkta hata bulunamadı</div>';
    } else {
      entries.forEach(e => drawTableRow(box, e, AL_COLS));
      box.scrollTop = 0;
    }

    const total = entries.length;
    document.getElementById('err-count').textContent = total ? `${total} hata` : '';
    document.getElementById('err-pager').textContent = `Sayfa ${ERR_PAGE} / ${ERR_PAGES}`;
    document.getElementById('err-prev').style.opacity = ERR_PAGE <= 1 ? '.4':'1';
    document.getElementById('err-next').style.opacity = ERR_PAGE >= ERR_PAGES ? '.4':'1';
  } catch(e){ console.error(e); }
}

function errSearch(){ ERR_PAGE=1; errLoad(); }
function errRefresh(){ errLoad(); }
function errPage(dir){ ERR_PAGE=Math.max(1,Math.min(ERR_PAGES,ERR_PAGE+dir)); errLoad(); }
function errExport(){
  const blob=new Blob([ERR_DATA.map(e=>JSON.stringify(e)).join('\n')],{type:'application/json'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='graphmcp-errors-'+Date.now()+'.jsonl'; a.click();
}

// ── Docker Tab ─────────────────────────────────────────────────────────────────
async function dkInit(){
  // Container listesini yükle
  try{
    const r = await fetch('/api/containers');
    const d = await r.json();
    // Sadece graph-mcp ile başlayan container'ları göster
    const containers = (d.containers || []).filter(c=>c.name.startsWith('graph-mcp'));

    // Health cards
    const cards = document.getElementById('dk-cards');
    cards.innerHTML = containers.map(c=>{
      const ok = c.healthy;
      const bg = ok ? 'rgba(63,185,80,.1)' : c.running ? 'rgba(210,153,34,.1)' : 'rgba(248,81,73,.1)';
      const dot = ok ? 'var(--green)' : c.running ? 'var(--yellow)' : 'var(--red)';
      const label = ok ? 'healthy' : c.running ? 'running' : 'stopped';
      return `<div onclick="dkSelect('${c.name}')"
        style="display:flex;align-items:center;gap:7px;padding:5px 10px;border-radius:7px;background:${bg};border:1px solid rgba(255,255,255,.08);cursor:pointer;transition:opacity .15s;font-size:11px;"
        onmouseenter="this.style.opacity='.7'" onmouseleave="this.style.opacity='1'">
        <span style="width:7px;height:7px;border-radius:50%;background:${dot};flex-shrink:0;"></span>
        <span style="font-weight:600;color:#fff;">${c.name.replace('graph-mcp-','').replace('graph-mcp','mcp')}</span>
        <span style="color:var(--mu);font-size:10px;">${label}</span>
      </div>`;
    }).join('');

    // Select dropdown
    const sel = document.getElementById('dk-container');
    const cur = sel.value;
    sel.innerHTML = '<option value="">— Container seç —</option>' +
      containers.map(c=>`<option value="${c.name}"${c.name===cur?' selected':''}>${c.name}</option>`).join('');

    if(!sel.value && containers.length) {
      // graph-mcp'yi varsayılan seç
      const main = containers.find(c=>c.name==='graph-mcp');
      if(main) { sel.value = main.name; dkLoad(); }
    }
  }catch(e){ document.getElementById('dk-cards').innerHTML='<span style="color:var(--red);font-size:12px;">Docker bağlantısı kurulamadı — /var/run/docker.sock erişimi gerekli</span>'; }
}

function dkSelect(name){
  document.getElementById('dk-container').value = name;
  dkLoad();
}

async function dkLoad(){
  const name  = document.getElementById('dk-container').value;
  const level = document.getElementById('dk-level').value;
  const lines = document.getElementById('dk-lines').value || 300;
  const box   = document.getElementById('dk-box');
  const thead = document.getElementById('dk-thead');

  if(!name){
    box.innerHTML = '<div style="color:var(--mu);font-size:12px;text-align:center;padding:30px;">Üstten bir container seçin</div>';
    thead.style.display = 'none';
    return;
  }

  box.innerHTML = '<div style="color:var(--mu);font-size:12px;text-align:center;padding:20px;">Yükleniyor...</div>';

  try{
    const params = new URLSearchParams({lines, level});
    const r = await fetch(`/api/container-logs/${encodeURIComponent(name)}?${params}`);
    const d = await r.json();
    const entries = d.entries || [];

    box.innerHTML = '';
    if(!entries.length){
      box.innerHTML = '<div style="color:var(--mu);font-size:12px;text-align:center;padding:30px;">Log bulunamadı</div>';
      thead.style.display = 'none';
      return;
    }

    thead.style.display = 'grid';
    entries.forEach(e => drawTableRow(box, e, AL_COLS));
    box.scrollTop = box.scrollHeight;
  }catch(e){
    box.innerHTML = `<div style="color:var(--red);font-size:12px;padding:20px;">Hata: ${e.message}</div>`;
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────────
connect();
fetchStats();
setInterval(fetchStats, 5000);
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTML

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
