#!/usr/bin/env python3
"""Headless ingest driver for LLM Wiki Web Edition 0.6.11.

The web edition runs ingest (LLM page generation) in the browser client, and the
server cannot push file-change events to it, so API-written sources are never
auto-ingested without an open UI. This keeps a headless Chrome on the Web UI
(through the box tunnel) and every POLL seconds enqueues raw/sources/**/*.md
files whose content hash changed since last enqueue (state in page localStorage).
"""
import json, os, subprocess, time, urllib.request
import websocket

UI = os.environ.get("LLM_WIKI_UI", "http://127.0.0.1:19828/")
PORT = int(os.environ.get("LLM_WIKI_CDP_PORT", "9333"))
POLL = int(os.environ.get("LLM_WIKI_PUMP_POLL", "30"))
PROFILE = os.path.expanduser("~/.llmwiki-chrome")

JS = r"""
(async()=>{
 const core=await import('/assets/tauri-core-CyFjBije.js'); const inv=core.n;
 const q=await import('/assets/ingest-queue-B-9X2158.js');
 const cur=await (await fetch('/api/v1/projects')).json();
 const P=cur.currentProject; if(!P) return 'no-project';
 const tree=await inv('list_directory',{path:P.path+'/raw/sources',includeHidden:false,maxDepth:8});
 const files=[]; const walk=n=>{for(const x of n){ if(x.is_dir) walk(x.children||[]); else if(/\.(md|txt)$/i.test(x.name)) files.push(x.path)}}; walk(tree);
 const key='astra-pump:'+P.id; const seen=JSON.parse(localStorage.getItem(key)||'{}'); const now={}; const todo=[];
 for(const f of files){ const c=await inv('read_file',{path:f}); const h=c.length+':'+[...c].reduce((a,ch)=>(a*31+ch.charCodeAt(0))|0,7);
   const rel=f.slice(P.path.length+1); now[rel]=h; if(seen[rel]!==h) todo.push({sourcePath:rel,folderContext:rel.split('/').slice(2,-1).join('/')}); }
 if(todo.length) await q.enqueueBatch(P.id,todo);
 { const st=q.getQueueSummary(); if(st.paused && !st.userPaused) q.resumeProcessing(); }
 localStorage.setItem(key,JSON.stringify(now));
 return JSON.stringify({files:files.length,enqueued:todo.map(t=>t.sourcePath),queue:q.getQueueSummary()});
})()
"""

def page_ws():
    for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5)):
        if t["type"] == "page" and t["url"].startswith(UI):
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("no page")

def ensure_chrome():
    try:
        return page_ws()
    except Exception:
        subprocess.Popen(["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
                          f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}", UI],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(20)
        return page_ws()

while True:
    try:
        ws = websocket.create_connection(ensure_chrome(), timeout=120, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": JS, "awaitPromise": True, "returnByValue": True}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                r = m.get("result", {})
                print(time.strftime("%F %T"), r.get("result", {}).get("value") or r.get("exceptionDetails", {}).get("text"), flush=True)
                break
        ws.close()
    except Exception as e:
        print(time.strftime("%F %T"), "pump error:", e, flush=True)
    time.sleep(POLL)
