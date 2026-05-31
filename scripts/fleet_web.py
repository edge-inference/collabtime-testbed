#!/usr/bin/env python3
"""
Live browser grid view of the Context-Fabric emulation.

Runs as a container on the `lf` network: subscribes to /agent_state and
/task_events, reads the warehouse graph, and serves an auto-refreshing HTML
canvas at http://localhost:<FLEET_WEB_PORT> (the host publishes the port).
Open it in a browser to watch robots claim → navigate → work → complete on the
grid in real time. Pure stdlib HTTP server + rclpy; no extra deps.
"""
import http.server
import json
import os
import socketserver
import threading
import time

import yaml
import rclpy
from rclpy.node import Node
from interfaces.msg import AgentState, TaskEvent

GRAPH_PATH = os.environ.get("GRAPH", "/ros2_ws/config/warehouse_graph.yaml")
PORT = int(os.environ.get("FLEET_WEB_PORT", "8089"))

_lock = threading.Lock()
_robots = {}                                  # id -> {node,state,task,ts}
_nodes = {}                                   # node_id -> {x,y,type}
_tasks = {"created": 0, "completed": 0, "failed": 0}
_start = time.time()


def load_nodes():
    with open(GRAPH_PATH) as f:
        g = yaml.safe_load(f)
    return {int(nid): {"x": int(m["x"]), "y": int(m["y"]), "type": m.get("type", "")}
            for nid, m in g.get("nodes", {}).items()}


class FleetNode(Node):
    def __init__(self):
        super().__init__("fleet_web")
        self.create_subscription(AgentState, "/agent_state", self._on_state, 50)
        self.create_subscription(TaskEvent, "/task_events", self._on_event, 50)

    def _on_state(self, msg):
        with _lock:
            _robots[int(msg.agent_id)] = {"node": int(msg.current_node), "state": msg.state,
                                          "task": int(msg.active_task_id), "ts": time.time()}

    def _on_event(self, msg):
        with _lock:
            if msg.event_type == "CREATED":
                _tasks["created"] += 1
            elif msg.event_type == "COMPLETED":
                _tasks["completed"] += 1
            elif msg.event_type == "FAILED":
                _tasks["failed"] += 1


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Context-Fabric fleet view</title>
<style>
 body{font-family:Helvetica,Arial,sans-serif;background:#0f1115;color:#e6e6e6;margin:0}
 #hud{padding:10px 14px;font-size:14px;line-height:1.9}
 .k{display:inline-block;margin-right:16px}
 .dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:middle}
 canvas{display:block;margin:4px auto 16px;background:#11151c;border:1px solid #2a2f3a;border-radius:6px}
 h3{margin:10px 14px 0}
</style></head><body>
<h3>Context-Fabric &mdash; live fleet view</h3>
<div id="hud">connecting&hellip;</div>
<canvas id="c" width="760" height="760"></canvas>
<script>
const COL={IDLE:'#9aa0a6',CLAIMING:'#fbc02d',NAVIGATING:'#42a5f5',WORKING:'#66bb6a',COMPLETING:'#ffa726'};
const c=document.getElementById('c'),ctx=c.getContext('2d');
let NODES=null,MX=1,MY=1;const PAD=26;
function bounds(n){let mx=0,my=0;for(const k in n){mx=Math.max(mx,n[k].x);my=Math.max(my,n[k].y);}return[mx||1,my||1];}
function X(x){return PAD+x*(c.width-2*PAD)/MX;}
function Y(y){return PAD+y*(c.height-2*PAD)/MY;}
function draw(d){
 if(!NODES){NODES=d.nodes;[MX,MY]=bounds(NODES);}
 ctx.clearRect(0,0,c.width,c.height);
 for(const k in NODES){const n=NODES[k];ctx.fillStyle=(n.type=='work')?'#1b2433':'#151a22';
   ctx.fillRect(X(n.x)-5,Y(n.y)-5,10,10);}
 const rs=d.robots,counts={};
 for(const id in rs){const r=rs[id],n=NODES[r.node];if(!n)continue;
   const col=COL[r.state]||'#888';counts[r.state]=(counts[r.state]||0)+1;
   ctx.beginPath();ctx.arc(X(n.x),Y(n.y),9,0,7);ctx.fillStyle=col;ctx.fill();
   ctx.fillStyle='#0b0d10';ctx.font='10px Helvetica';ctx.textAlign='center';ctx.fillText(id,X(n.x),Y(n.y)+3);}
 let h=`<span class="k"><b>${Object.keys(rs).length}</b> robots</span>`;
 h+=`<span class="k">created <b>${d.tasks.created}</b></span><span class="k">done <b>${d.tasks.completed}</b></span>`;
 h+=`<span class="k">failed <b>${d.tasks.failed}</b></span><span class="k">t=${d.elapsed}s</span><br>`;
 for(const s in COL){h+=`<span class="k"><span class="dot" style="background:${COL[s]}"></span>${s} ${counts[s]||0}</span>`;}
 document.getElementById('hud').innerHTML=h;
}
async function tick(){try{const r=await fetch('/state');draw(await r.json());}catch(e){}}
setInterval(tick,600);tick();
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/state"):
            with _lock:
                body = json.dumps({"robots": _robots, "nodes": _nodes, "tasks": _tasks,
                                   "elapsed": int(time.time() - _start)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode())

    def log_message(self, *a):
        pass


def main():
    global _nodes
    _nodes = load_nodes()
    rclpy.init()
    node = FleetNode()
    threading.Thread(target=lambda: rclpy.spin(node), daemon=True).start()
    httpd = socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler)
    httpd.daemon_threads = True
    print(f"[fleet_web] serving grid on :{PORT}  (graph nodes={len(_nodes)})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
