#!/usr/bin/env python3
"""
Seraph Audit Viewer — full-featured web dashboard for monitoring LLM traffic.

Metrics tracked:
  - Request path, model name, streaming flag
  - All message segments (system, user, assistant, tool, tool_definition)
  - Scanner scores, violations, actions taken
  - Request duration (scan + upstream latency breakdown)
  - Upstream status codes
  - Tool calls detected in LLM responses
  - Token usage (prompt, completion, total)
  - Conversation turn counts by role
  - Near-miss scores (passed but high scanner scores)
  - Repeated violations per IP
"""
import json
import sqlite3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.environ.get("AUDIT_DB", "/data/seraph_audit.db")
PORT = int(os.environ.get("PORT", "8080"))


def _db():
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def get_logs(limit=50, direction=None, violations_only=False, near_misses=False):
    conn = _db()
    if not conn:
        return []
    try:
        query = "SELECT * FROM audit_logs"
        conds, params = [], []
        if direction:
            conds.append("direction = ?")
            params.append(direction)
        if violations_only:
            conds.append("is_valid = 0")
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        conn.close()

        if near_misses:
            filtered = []
            for row in rows:
                if row["is_valid"] == 0:
                    continue
                scores = json.loads(row.get("scanner_results") or "{}")
                max_score = max((v for v in scores.values() if v > 0), default=0)
                if max_score >= 0.4:
                    row["_near_miss_score"] = max_score
                    filtered.append(row)
            return filtered

        return rows
    except Exception as e:
        return [{"error": str(e)}]


def get_stats():
    conn = _db()
    if not conn:
        return {}
    try:
        c = conn.cursor()
        def q(sql):
            return c.execute(sql).fetchone()[0]
        stats = {
            "total": q("SELECT COUNT(*) FROM audit_logs"),
            "blocked": q("SELECT COUNT(*) FROM audit_logs WHERE is_valid = 0"),
            "allowed": q("SELECT COUNT(*) FROM audit_logs WHERE is_valid = 1 AND fix_applied = 0"),
            "fixed": q("SELECT COUNT(*) FROM audit_logs WHERE fix_applied = 1"),
            "input_scans": q("SELECT COUNT(*) FROM audit_logs WHERE direction = 'input'"),
            "output_scans": q("SELECT COUNT(*) FROM audit_logs WHERE direction = 'output'"),
        }

        # Aggregate token usage from metadata
        rows = c.execute("SELECT metadata FROM audit_logs WHERE metadata IS NOT NULL").fetchall()
        total_prompt = 0
        total_completion = 0
        total_duration = 0.0
        duration_count = 0
        for row in rows:
            try:
                m = json.loads(row[0])
                total_prompt += m.get("prompt_tokens", 0)
                total_completion += m.get("completion_tokens", 0)
                d = m.get("duration_ms") or m.get("scan_duration_ms")
                if d:
                    total_duration += d
                    duration_count += 1
            except Exception:
                pass
        stats["total_prompt_tokens"] = total_prompt
        stats["total_completion_tokens"] = total_completion
        stats["total_tokens"] = total_prompt + total_completion
        stats["avg_duration_ms"] = round(total_duration / duration_count, 1) if duration_count else 0

        # Violations per IP
        ip_rows = c.execute(
            "SELECT ip_address, COUNT(*) as cnt FROM audit_logs WHERE is_valid = 0 GROUP BY ip_address ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        stats["violations_by_ip"] = [{"ip": r[0] or "unknown", "count": r[1]} for r in ip_rows]

        conn.close()
        return stats
    except Exception as e:
        return {"error": str(e)}


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Seraph Audit Viewer</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'SF Mono','Fira Code','Consolas',monospace;background:#0a0a0a;color:#c0c0c0;padding:16px}
h1{color:#e67e22;font-size:20px;margin-bottom:4px}
.sub{color:#555;font-size:12px;margin-bottom:16px}

.stats{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.sc{background:#141414;border:1px solid #222;border-radius:6px;padding:12px 20px;min-width:100px}
.sc .n{font-size:24px;font-weight:bold}
.sc .l{font-size:10px;color:#555;text-transform:uppercase;margin-top:2px}
.sc.blocked .n{color:#e74c3c}.sc.allowed .n{color:#2ecc71}
.sc.fixed .n{color:#f39c12}.sc.total .n{color:#3498db}
.sc.tokens .n{color:#af7ac5}.sc.speed .n{color:#5dade2}

.controls{display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
.controls button{background:#1a1a1a;border:1px solid #333;color:#aaa;padding:5px 12px;border-radius:5px;font-size:11px;cursor:pointer;font-family:inherit}
.controls button:hover{border-color:#e67e22}.controls button.active{background:#e67e22;color:#000;border-color:#e67e22}
.auto{color:#555;font-size:10px;margin-left:auto}

.entry{background:#111;border:1px solid #222;border-radius:6px;margin-bottom:12px;overflow:hidden}
.entry.blocked{border-left:3px solid #e74c3c}.entry.allowed{border-left:3px solid #2ecc71}
.entry.fixed{border-left:3px solid #f39c12}

.hdr{display:flex;align-items:center;gap:8px;padding:10px 14px;background:#141414;border-bottom:1px solid #1a1a1a;flex-wrap:wrap}
.hdr .time{color:#555;font-size:10px}.hdr .path{color:#888;font-size:10px}

.badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:bold;text-transform:uppercase}
.badge.input{background:#1a3a5c;color:#5dade2}.badge.output{background:#1a4a3a;color:#58d68d}
.badge.blocked{background:#5c1a1a;color:#e74c3c}.badge.allowed{background:#1a3a1a;color:#2ecc71}
.badge.fixed{background:#4a3a1a;color:#f39c12}

.meta-row{display:flex;gap:8px;padding:6px 14px;background:#0e0e0e;border-bottom:1px solid #1a1a1a;flex-wrap:wrap;align-items:center}
.meta-chip{font-size:10px;padding:2px 8px;border-radius:3px;background:#1a1a1a;border:1px solid #2a2a2a;color:#999}
.meta-chip.model{border-color:#af7ac5;color:#af7ac5}
.meta-chip.tokens{border-color:#5dade2;color:#5dade2}
.meta-chip.duration{border-color:#f39c12;color:#f39c12}
.meta-chip.turns{border-color:#58d68d;color:#58d68d}

.tool-calls{padding:6px 14px;background:#0d1a0d;border-bottom:1px solid #1a1a1a}
.tool-call-item{display:flex;gap:8px;align-items:baseline;margin:3px 0}
.tool-name{color:#82e0aa;font-size:11px;font-weight:bold}
.tool-args{color:#666;font-size:10px;max-width:500px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.segments{padding:0}
.seg{padding:8px 14px;border-bottom:1px solid #1a1a1a}
.seg:last-child{border-bottom:none}
.seg-hdr{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.role{display:inline-block;padding:2px 7px;border-radius:3px;font-size:9px;font-weight:bold;text-transform:uppercase;min-width:60px;text-align:center}
.role.system{background:#3a2a1a;color:#e67e22}.role.user{background:#1a2a4a;color:#5dade2}
.role.assistant{background:#2a1a3a;color:#af7ac5}.role.tool{background:#1a3a2a;color:#58d68d}
.role.tool_call{background:#2a3a1a;color:#82e0aa}.role.tool_definition{background:#2a2a2a;color:#888}
.role.function{background:#1a3a2a;color:#58d68d}
.seg-src{color:#444;font-size:9px}
.seg-text{background:#0d0d0d;border:1px solid #1a1a1a;border-radius:3px;padding:6px 10px;font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-word;color:#ddd;max-height:200px;overflow-y:auto}
.seg-text.system{border-left:2px solid #e67e22}.seg-text.user{border-left:2px solid #5dade2}
.seg-text.assistant{border-left:2px solid #af7ac5}.seg-text.tool{border-left:2px solid #58d68d}
.seg-text.function{border-left:2px solid #58d68d}

.toggle{padding:6px 14px;background:#0e0e0e;border-top:1px solid #1a1a1a;cursor:pointer;font-size:10px;color:#555}
.toggle:hover{color:#999}
.details{display:none;padding:8px 14px;background:#0c0c0c;border-top:1px solid #1a1a1a}
.details.open{display:block}
.chip{display:inline-block;font-size:9px;padding:2px 5px;border-radius:3px;margin:1px;background:#1a1a1a;border:1px solid #2a2a2a}
.chip.hot{border-color:#e74c3c;color:#e74c3c}.chip.warm{border-color:#f39c12;color:#f39c12}.chip.cool{border-color:#2ecc71;color:#2ecc71}

.violations-inline{color:#e74c3c;font-size:10px;font-weight:bold}

.empty{text-align:center;padding:40px;color:#333}

.ip-table{margin-top:8px}
.ip-table td{padding:2px 10px;font-size:11px}
.ip-table .count{color:#e74c3c;font-weight:bold}

.legend{background:#111;border:1px solid #222;border-radius:6px;margin-bottom:16px;overflow:hidden}
.legend-toggle{padding:10px 14px;cursor:pointer;font-size:11px;color:#888;background:#141414;display:flex;align-items:center;gap:6px}
.legend-toggle:hover{color:#ccc}
.legend-body{display:none;padding:12px 14px}
.legend-body.open{display:block}
.legend-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:8px}
.legend-item{display:flex;gap:8px;align-items:flex-start;padding:6px 8px;background:#0d0d0d;border:1px solid #1a1a1a;border-radius:4px}
.legend-item .sname{color:#e67e22;font-size:11px;font-weight:bold;min-width:120px}
.legend-item .sdesc{color:#888;font-size:10px;line-height:1.4}
.legend-item .sdir{font-size:9px;padding:1px 5px;border-radius:2px;margin-left:auto}
.legend-item .sdir.inp{background:#1a3a5c;color:#5dade2}
.legend-item .sdir.out{background:#1a4a3a;color:#58d68d}
</style>
</head>
<body>
<h1>Seraph Audit Viewer</h1>
<p class="sub">Real-time monitoring of LLM traffic through Seraph guardrail proxy</p>

<div class="stats" id="stats"></div>

<div class="controls">
  <button id="btn-all" class="active" onclick="setFilter('')">All</button>
  <button id="btn-input" onclick="setFilter('input')">Input</button>
  <button id="btn-output" onclick="setFilter('output')">Output</button>
  <button id="btn-violations" onclick="toggleViolations()">Violations Only</button>
  <button id="btn-nearmiss" onclick="toggleNearMiss()">Near Misses</button>
  <span class="auto">Auto-refresh 3s</span>
</div>

<div class="legend">
  <div class="legend-toggle" onclick="document.getElementById('legend-body').classList.toggle('open')">
    <span>&#9662;</span> Scanner Legend — what each scanner does and when it triggers
  </div>
  <div class="legend-body" id="legend-body">
    <div class="legend-grid">
      <div class="legend-item"><span class="sname">NeMo Guardrails</span><span class="sdesc">Tier 1 — Semantic allow-list firewall using NVIDIA NeMo with Colang DSL. Matches user input against allowed intents via embedding similarity (threshold 0.85). Blocks anything that doesn't match known-safe categories.</span><span class="sdir inp">in+out</span></div>
      <div class="legend-item"><span class="sname">LLM-as-a-Judge</span><span class="sdesc">Tier 2 — LangGraph StateGraph evaluating: prompt injection, jailbreak attempts, harmful intent, data exfiltration, social engineering, policy violations, information leakage, harmful content generation.</span><span class="sdir inp">in+out</span></div>
    </div>
    <p style="color:#444;font-size:10px;margin-top:10px">Score interpretation: 0.0 = no risk detected | 0.0-0.3 = low risk | 0.3-0.7 = medium (near miss) | 0.7+ = high (violation triggered, blocked)</p>
  </div>
</div>

<div id="entries"></div>

<script>
let filter='',violOnly=false,nearMiss=false;
function setFilter(f){filter=f;violOnly=false;nearMiss=false;updBtns();refresh()}
function toggleViolations(){violOnly=!violOnly;nearMiss=false;updBtns();refresh()}
function toggleNearMiss(){nearMiss=!nearMiss;violOnly=false;updBtns();refresh()}
function updBtns(){
  document.querySelectorAll('.controls button').forEach(b=>b.classList.remove('active'));
  if(nearMiss)document.getElementById('btn-nearmiss').classList.add('active');
  else if(violOnly)document.getElementById('btn-violations').classList.add('active');
  else document.getElementById('btn-'+(filter||'all')).classList.add('active');
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function sc(v){return v>=0.7?'hot':v>=0.3?'warm':'cool'}
function tog(id){document.getElementById('det-'+id).classList.toggle('open')}

async function refresh(){
  try{
    const st=await(await fetch('/api/stats')).json();
    document.getElementById('stats').innerHTML=`
      <div class="sc total"><div class="n">${st.total||0}</div><div class="l">Total Scans</div></div>
      <div class="sc allowed"><div class="n">${st.allowed||0}</div><div class="l">Allowed</div></div>
      <div class="sc blocked"><div class="n">${st.blocked||0}</div><div class="l">Blocked</div></div>
      <div class="sc fixed"><div class="n">${st.fixed||0}</div><div class="l">Fixed</div></div>
      <div class="sc tokens"><div class="n">${((st.total_tokens||0)/1000).toFixed(1)}k</div><div class="l">Total Tokens</div></div>
      <div class="sc speed"><div class="n">${st.avg_duration_ms||0}ms</div><div class="l">Avg Duration</div></div>
      <div class="sc"><div class="n">${st.input_scans||0}/${st.output_scans||0}</div><div class="l">In / Out</div></div>
      ${(st.violations_by_ip||[]).length?`<div class="sc blocked"><div class="l">Violations by IP</div><table class="ip-table">${(st.violations_by_ip||[]).map(r=>`<tr><td>${esc(r.ip)}</td><td class="count">${r.count}</td></tr>`).join('')}</table></div>`:''}
    `;

    let url='/api/logs?limit=40';
    if(filter)url+='&direction='+filter;
    if(violOnly)url+='&violations_only=1';
    if(nearMiss)url+='&near_misses=1';
    const logs=await(await fetch(url)).json();

    if(!logs.length){document.getElementById('entries').innerHTML='<div class="empty">No logs yet. Send a message through level-4.</div>';return}

    let h='';
    for(const L of logs){
      const t=(L.timestamp||'').replace('T',' ').split('.')[0];
      const dir=L.direction||'?';
      const v=L.is_valid,fx=L.fix_applied;
      const id=L.id;
      let cls,badge;
      if(!v){cls='blocked';badge='<span class="badge blocked">Blocked</span>'}
      else if(fx){cls='fixed';badge='<span class="badge fixed">Fixed</span>'}
      else{cls='allowed';badge='<span class="badge allowed">Allowed</span>'}

      let viols=[];try{viols=JSON.parse(L.violations||'[]')}catch(e){}
      const violH=viols.length?`<span class="violations-inline">${viols.join(', ')}</span>`:'';

      // Metadata
      let meta={};try{meta=JSON.parse(L.metadata||'{}')}catch(e){}
      let metaH='';
      if(Object.keys(meta).length){
        metaH='<div class="meta-row">';
        if(meta.model)metaH+=`<span class="meta-chip model">${esc(meta.model)}</span>`;
        if(meta.request_path)metaH+=`<span class="meta-chip">${esc(meta.request_path)}</span>`;
        if(meta.message_count)metaH+=`<span class="meta-chip turns">${meta.message_count} msgs</span>`;
        if(meta.role_counts){
          const rc=meta.role_counts;
          const parts=Object.entries(rc).map(([r,c])=>`${r}:${c}`).join(' ');
          metaH+=`<span class="meta-chip turns">${parts}</span>`;
        }
        if(meta.total_tokens)metaH+=`<span class="meta-chip tokens">${meta.prompt_tokens||0}p + ${meta.completion_tokens||0}c = ${meta.total_tokens}t</span>`;
        if(meta.duration_ms)metaH+=`<span class="meta-chip duration">upstream: ${meta.duration_ms}ms</span>`;
        if(meta.scan_duration_ms)metaH+=`<span class="meta-chip duration">scan: ${meta.scan_duration_ms}ms</span>`;
        if(meta.upstream_status&&meta.upstream_status!==200)metaH+=`<span class="meta-chip" style="border-color:#e74c3c;color:#e74c3c">HTTP ${meta.upstream_status}</span>`;
        if(meta.finish_reason)metaH+=`<span class="meta-chip">${esc(meta.finish_reason)}</span>`;
        if(meta.tool_count)metaH+=`<span class="meta-chip">${meta.tool_count} tools</span>`;
        if(meta.streaming)metaH+=`<span class="meta-chip">streaming</span>`;
        metaH+='</div>';
      }

      // Tool calls
      let tcH='';
      if(meta.tool_calls&&meta.tool_calls.length){
        tcH='<div class="tool-calls">';
        for(const tc of meta.tool_calls){
          tcH+=`<div class="tool-call-item"><span class="tool-name">${esc(tc.name)}</span><span class="tool-args">${esc(tc.arguments||'')}</span></div>`;
        }
        tcH+='</div>';
      }

      // Segments
      let segs=[];try{segs=JSON.parse(L.segments||'[]')}catch(e){}
      let segH='';
      if(segs.length){
        segH='<div class="segments">';
        for(const s of segs){
          const r=s.role||'unknown';
          segH+=`<div class="seg"><div class="seg-hdr"><span class="role ${esc(r)}">${esc(r)}</span><span class="seg-src">${esc(s.source||'')}</span></div><div class="seg-text ${esc(r)}">${esc(s.text||'')}</div></div>`;
        }
        segH+='</div>';
      }

      // Scanner details
      let scores={};try{scores=JSON.parse(L.scanner_results||'{}')}catch(e){}
      let mainS='',fullS='';
      for(const[n,v]of Object.entries(scores)){
        if(v<0)continue;
        const c=sc(v);
        const chip=`<span class="chip ${c}">${esc(n)}: ${(v*100).toFixed(0)}%</span>`;
        fullS+=chip+' ';
        if(!n.includes('['))mainS+=chip;
      }

      h+=`<div class="entry ${cls}">
        <div class="hdr">
          <span class="time">${esc(t)}</span>
          <span class="badge ${dir}">${dir}</span>
          ${badge}
          <span style="color:#444;font-size:10px">${L.text_length||0} chars</span>
          ${violH} ${mainS}
        </div>
        ${metaH}${tcH}${segH}
        <div class="toggle" onclick="tog(${id})">Scanner details (${Object.keys(scores).length})</div>
        <div class="details" id="det-${id}">${fullS||'<span style="color:#444">-</span>'}</div>
      </div>`;
    }
    document.getElementById('entries').innerHTML=h;
  }catch(e){console.error(e)}
}
setInterval(refresh,3000);refresh();
</script>
</body>
</html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        p=urlparse(self.path);path=p.path;q=parse_qs(p.query)
        if path=="/api/logs":
            self._j(get_logs(
                limit=int(q.get("limit",[50])[0]),
                direction=q.get("direction",[None])[0],
                violations_only=q.get("violations_only",["0"])[0]=="1",
                near_misses=q.get("near_misses",["0"])[0]=="1",
            ))
        elif path=="/api/stats":
            self._j(get_stats())
        else:
            b=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def _j(self,d):
        b=json.dumps(d).encode();self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.send_header("Access-Control-Allow-Origin","*");self.end_headers();self.wfile.write(b)
    def log_message(self,*a):pass

if __name__=="__main__":
    print(f"Seraph Audit Viewer on port {PORT} — watching {DB_PATH}")
    HTTPServer(("0.0.0.0",PORT),H).serve_forever()
