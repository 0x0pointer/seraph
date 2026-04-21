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
                max_score = max((v for v in scores.values() if isinstance(v, (int, float)) and v > 0), default=0)
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
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=Outfit:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --bg:            #13112e;
  --bg-card:       #1a1840;
  --bg-raised:     #2d2b55;
  --bg-deep:       #0d0b20;
  --text:          #e8e6f0;
  --text-muted:    #9b98b8;
  --text-dim:      #6b6890;
  --green:         #5bf29b;
  --purple:        #7b78ff;
  --border:        rgba(123,120,255,0.22);
  --border-subtle: rgba(123,120,255,0.1);
  --green-dim:     rgba(91,242,155,0.12);
  --purple-dim:    rgba(123,120,255,0.12);
  --green-glow:    rgba(91,242,155,0.15);
}

* { margin:0; padding:0; box-sizing:border-box }

body {
  font-family: 'Outfit', -apple-system, sans-serif;
  background-color: var(--bg);
  background-image: repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(91,242,155,0.008) 2px, rgba(91,242,155,0.008) 4px
  );
  color: var(--text);
  padding: 0 16px 16px;
  min-height: 100vh;
}

.header-brand { display:flex; align-items:center; gap:0.85rem; padding: 0 0 4px; }
.header-logo  { height:100px; width:auto; filter:drop-shadow(0 0 8px var(--green-glow)); }
h1 {
  font-family: 'Chakra Petch', sans-serif;
  font-size: 1.15rem; font-weight: 600; color: #fff; letter-spacing: 0.03em;
}
h1 .h1-accent { color: var(--green); }
.sub { color: var(--text-dim); font-size: 12px; margin-bottom: 16px; font-family:'IBM Plex Mono',monospace; }

.stats { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.sc {
  background: linear-gradient(135deg, rgba(45,43,85,0.55), rgba(26,24,64,0.9));
  border: 1px solid var(--border); border-radius:6px; padding:12px 20px; min-width:100px;
  position:relative; overflow:hidden;
}
.sc::before {
  content:''; position:absolute; inset:0 0 auto 0; height:1px;
  background: linear-gradient(90deg, transparent, var(--purple) 100%);
}
.sc .n { font-size:24px; font-weight:bold; font-family:'IBM Plex Mono',monospace; }
.sc .l { font-size:10px; color:var(--text-dim); text-transform:uppercase; margin-top:2px; font-family:'IBM Plex Mono',monospace; letter-spacing:.05em; }
.sc.blocked .n { color:#ff4d4f }
.sc.allowed .n { color:var(--green) }
.sc.fixed   .n { color:#faad14 }
.sc.total   .n { color:var(--purple) }
.sc.tokens  .n { color:var(--purple) }
.sc.speed   .n { color:var(--green) }

.controls { display:flex; gap:8px; margin-bottom:12px; align-items:center; flex-wrap:wrap; }
.controls button {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-muted);
  padding:5px 12px; border-radius:5px; font-size:11px; cursor:pointer;
  font-family:'IBM Plex Mono',monospace; transition: border-color .15s, color .15s;
}
.controls button:hover  { border-color:var(--green); color:var(--green); }
.controls button.active { background:var(--green); color:var(--bg-deep); border-color:var(--green); font-weight:600; }
.auto { color:var(--text-dim); font-size:10px; margin-left:auto; font-family:'IBM Plex Mono',monospace; }

.entry {
  background: linear-gradient(135deg, rgba(45,43,85,0.5), rgba(26,24,64,0.85));
  border: 1px solid var(--border); border-radius:6px; margin-bottom:12px; overflow:hidden;
  position:relative;
}
.entry::before {
  content:''; position:absolute; inset:0 0 auto 0; height:1px;
  background: linear-gradient(90deg, transparent, var(--green) 30%, var(--purple) 70%, transparent);
}
.entry.blocked { border-left:3px solid #ff4d4f; }
.entry.allowed { border-left:3px solid var(--green); }
.entry.fixed   { border-left:3px solid #faad14; }

.hdr { display:flex; align-items:center; gap:8px; padding:10px 14px; background:rgba(26,24,64,0.6); border-bottom:1px solid var(--border-subtle); flex-wrap:wrap; }
.hdr .time { color:var(--text-dim); font-size:10px; font-family:'IBM Plex Mono',monospace; }
.hdr .path { color:var(--text-muted); font-size:10px; font-family:'IBM Plex Mono',monospace; }

.badge { display:inline-block; padding:2px 7px; border-radius:3px; font-size:9px; font-weight:bold; text-transform:uppercase; font-family:'IBM Plex Mono',monospace; }
.badge.input   { background:var(--purple-dim); color:var(--purple); }
.badge.output  { background:var(--green-dim);  color:var(--green); }
.badge.blocked { background:rgba(255,77,79,.2);  color:#ff4d4f; }
.badge.allowed { background:var(--green-dim);    color:var(--green); }
.badge.fixed   { background:rgba(250,173,20,.2); color:#faad14; }

.meta-row { display:flex; gap:8px; padding:6px 14px; background:rgba(13,11,32,0.5); border-bottom:1px solid var(--border-subtle); flex-wrap:wrap; align-items:center; }
.meta-chip { font-size:10px; padding:2px 8px; border-radius:3px; background:var(--bg-raised); border:1px solid var(--border); color:var(--text-muted); font-family:'IBM Plex Mono',monospace; }
.meta-chip.model    { border-color:var(--purple); color:var(--purple); }
.meta-chip.tokens   { border-color:var(--green);  color:var(--green); }
.meta-chip.duration { border-color:#faad14; color:#faad14; }
.meta-chip.turns    { border-color:var(--green);  color:var(--green); }

.tool-calls { padding:6px 14px; background:rgba(91,242,155,0.04); border-bottom:1px solid var(--border-subtle); }
.tool-call-item { display:flex; gap:8px; align-items:baseline; margin:3px 0; }
.tool-name { color:var(--green); font-size:11px; font-weight:bold; font-family:'IBM Plex Mono',monospace; }
.tool-args { color:var(--text-dim); font-size:10px; max-width:500px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:'IBM Plex Mono',monospace; }

.segments { padding:0; }
.seg { padding:8px 14px; border-bottom:1px solid var(--border-subtle); }
.seg:last-child { border-bottom:none; }
.seg-hdr { display:flex; align-items:center; gap:6px; margin-bottom:4px; }
.role { display:inline-block; padding:2px 7px; border-radius:3px; font-size:9px; font-weight:bold; text-transform:uppercase; min-width:60px; text-align:center; font-family:'IBM Plex Mono',monospace; }
.role.system          { background:rgba(91,242,155,0.12); color:var(--green); }
.role.user            { background:var(--purple-dim); color:var(--purple); }
.role.assistant       { background:rgba(91,242,155,0.08); color:var(--green); }
.role.tool            { background:rgba(123,120,255,0.15); color:var(--purple); }
.role.tool_call       { background:var(--green-dim); color:var(--green); }
.role.tool_definition { background:var(--bg-raised); color:var(--text-muted); }
.role.function        { background:rgba(123,120,255,0.15); color:var(--purple); }
.seg-src  { color:var(--text-dim); font-size:9px; font-family:'IBM Plex Mono',monospace; }
.seg-text {
  background:var(--bg-deep); border:1px solid var(--border-subtle); border-radius:3px;
  padding:6px 10px; font-size:11px; line-height:1.5; white-space:pre-wrap; word-break:break-word;
  color:var(--text); max-height:200px; overflow-y:auto; font-family:'IBM Plex Mono',monospace;
}
.seg-text.system    { border-left:2px solid var(--green); }
.seg-text.user      { border-left:2px solid var(--purple); }
.seg-text.assistant { border-left:2px solid var(--green); }
.seg-text.tool      { border-left:2px solid var(--purple); }
.seg-text.function  { border-left:2px solid var(--purple); }

.toggle { padding:6px 14px; background:rgba(13,11,32,0.4); border-top:1px solid var(--border-subtle); cursor:pointer; font-size:10px; color:var(--text-dim); font-family:'IBM Plex Mono',monospace; }
.toggle:hover { color:var(--text-muted); }
.details { display:none; padding:8px 14px; background:var(--bg-deep); border-top:1px solid var(--border-subtle); }
.details.open { display:block; }
.chip { display:inline-block; font-size:9px; padding:2px 5px; border-radius:3px; margin:1px; background:var(--bg-raised); border:1px solid var(--border); font-family:'IBM Plex Mono',monospace; }
.chip.hot  { border-color:#ff4d4f; color:#ff4d4f; }
.chip.warm { border-color:#faad14; color:#faad14; }
.chip.cool { border-color:var(--green); color:var(--green); }

.violations-inline { color:#ff4d4f; font-size:10px; font-weight:bold; font-family:'IBM Plex Mono',monospace; }

.empty { text-align:center; padding:40px; color:var(--text-dim); border:1px dashed var(--border); border-radius:6px; }

.ip-table { margin-top:8px; }
.ip-table td { padding:2px 10px; font-size:11px; font-family:'IBM Plex Mono',monospace; }
.ip-table .count { color:#ff4d4f; font-weight:bold; }

.legend {
  background: linear-gradient(135deg, rgba(45,43,85,0.5), rgba(26,24,64,0.85));
  border:1px solid var(--border); border-radius:6px; margin-bottom:16px; overflow:hidden;
  position:relative;
}
.legend::before {
  content:''; position:absolute; inset:0 0 auto 0; height:1px;
  background: linear-gradient(90deg, transparent, var(--green) 30%, var(--purple) 70%, transparent);
}
.legend-toggle { padding:10px 14px; cursor:pointer; font-size:11px; color:var(--text-muted); background:rgba(26,24,64,0.6); display:flex; align-items:center; gap:6px; font-family:'IBM Plex Mono',monospace; }
.legend-toggle:hover { color:var(--text); }
.legend-body { display:none; padding:12px 14px; }
.legend-body.open { display:block; }
.legend-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:8px; }
.legend-item { display:flex; gap:8px; align-items:flex-start; padding:6px 8px; background:var(--bg-deep); border:1px solid var(--border-subtle); border-radius:4px; }
.legend-item .sname { color:var(--green); font-size:11px; font-weight:bold; min-width:120px; font-family:'IBM Plex Mono',monospace; }
.legend-item .sdesc { color:var(--text-muted); font-size:10px; line-height:1.4; }
.legend-item .sdir  { font-size:9px; padding:1px 5px; border-radius:2px; margin-left:auto; font-family:'IBM Plex Mono',monospace; }
.legend-item .sdir.inp { background:var(--purple-dim); color:var(--purple); }
.legend-item .sdir.out { background:var(--green-dim);  color:var(--green); }
</style>
</head>
<body>
<div class="header-brand">
  <img class="header-logo" src="https://nullpointer.studio/design/FullLogo_Transparent.png" alt="NullPointer Studio" onerror="this.style.display='none'">
  <div>
    <h1>Seraph <span class="h1-accent">Audit Viewer</span></h1>
    <p class="sub">Real-time monitoring of LLM traffic through Seraph guardrail proxy</p>
  </div>
</div>

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
    <p style="color:var(--text-dim);font-size:10px;margin-top:10px;font-family:'IBM Plex Mono',monospace">Score interpretation: -1.0 = passed cleanly (no risk detected) | 0.0-0.3 = low risk | 0.3-0.7 = medium (near miss) | 0.7+ = high (violation triggered)</p>
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
      const coreKeys=['NeMoGuardrails','LLMJudge'];
      for(const[n,v]of Object.entries(scores)){
        if(typeof v!=='number'||v<0)continue;
        if(n.includes('_'))continue;
        const c=sc(v);
        const chip=`<span class="chip ${c}">${esc(n)}: ${(v*100).toFixed(0)}%</span>`;
        fullS+=chip+' ';
        if(coreKeys.includes(n))mainS+=chip;
      }

      // Flow visualization
      const nemoRan='NeMoGuardrails' in scores && typeof scores.NeMoGuardrails==='number';
      const judgeRan='LLMJudge' in scores && typeof scores.LLMJudge==='number';
      const nemoPassed=scores.NeMoGuardrails_passed===1.0;
      const judgePassed=scores.LLMJudge_passed===1.0;
      const nemoMs=scores.NeMoGuardrails_latency_ms;
      const judgeMs=scores.LLMJudge_latency_ms;
      const nemoScore=scores.NeMoGuardrails;
      const judgeScore=scores.LLMJudge;
      const nemoIntent=scores.NeMoGuardrails_intent||'';
      const judgeReason=scores.LLMJudge_reasoning||'';
      const totalMs=(nemoMs||0)+(judgeMs||0);

      let flowH='<div class="flow"><div class="flow-pipeline">';
      // Source node
      const srcLabel=dir==='input'?'User':'LLM';
      flowH+=`<div class="flow-node passed"><div class="fn-name">${srcLabel}</div><div class="fn-latency" style="color:#888">start</div></div>`;

      // NeMo node
      if(nemoRan){
        const nc=nemoPassed?'passed':'blocked';
        const arrow=`<span class="flow-arrow ${nemoPassed?'ok':'fail'}">&rarr;</span>`;
        flowH+=arrow;
        flowH+=`<div class="flow-node ${nc}"><div class="fn-name">NeMo</div><div class="fn-latency">${nemoMs?nemoMs.toFixed(0)+'ms':'?'}</div><div class="fn-score">score: ${typeof nemoScore==='number'?(nemoScore*100).toFixed(0)+'%':'?'}</div>${nemoIntent?`<div class="fn-detail" title="${esc(nemoIntent)}">${esc(nemoIntent)}</div>`:''}</div>`;
      } else {
        flowH+=`<span class="flow-arrow">&rarr;</span><div class="flow-node skipped"><div class="fn-name">NeMo</div><div class="fn-latency">skipped</div></div>`;
      }

      // Judge node
      if(judgeRan){
        const jc=judgePassed?'passed':'blocked';
        const arrow=nemoRan&&!nemoPassed?`<span class="flow-arrow fail">&cross;</span>`:`<span class="flow-arrow ${judgePassed?'ok':'fail'}">&rarr;</span>`;
        flowH+=arrow;
        flowH+=`<div class="flow-node ${jc}"><div class="fn-name">Judge</div><div class="fn-latency">${judgeMs?judgeMs.toFixed(0)+'ms':'?'}</div><div class="fn-score">score: ${typeof judgeScore==='number'?(judgeScore*100).toFixed(0)+'%':'?'}</div>${judgeReason?`<div class="fn-detail" title="${esc(judgeReason)}">${esc(judgeReason.substring(0,40))}</div>`:''}</div>`;
      } else if(nemoRan&&nemoPassed) {
        flowH+=`<span class="flow-arrow">&rarr;</span><div class="flow-node skipped"><div class="fn-name">Judge</div><div class="fn-latency">skipped</div></div>`;
      }

      // Result node
      const resultOk=v===1;
      flowH+=`<span class="flow-arrow ${resultOk?'ok':'fail'}">&rarr;</span>`;
      flowH+=`<div class="flow-node ${resultOk?'passed':'blocked'}"><div class="fn-name">${resultOk?'Passed':'Blocked'}</div><div class="fn-latency" style="color:${resultOk?'#2ecc71':'#e74c3c'}">${resultOk?'&#10003;':'&#10007;'}</div></div>`;

      // Total time
      if(totalMs>0){
        flowH+=`<div class="flow-total"><div class="ft-label">scan total</div><div class="ft-time">${totalMs.toFixed(0)}ms</div></div>`;
      }
      flowH+='</div></div>';

      h+=`<div class="entry ${cls}">
        <div class="hdr">
          <span class="time">${esc(t)}</span>
          <span class="badge ${dir}">${dir}</span>
          ${badge}
          <span style="color:#444;font-size:10px">${L.text_length||0} chars</span>
          ${violH} ${mainS}
        </div>
        ${metaH}${flowH}${tcH}${segH}
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
