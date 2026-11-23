"""Offline inspection of recorded observations and private application traces."""

import json
from pathlib import Path

from factw.env.core.recording import Episode
from factw.env.core.recording.jsonio import read_json


def inspection(run):
    run = Path(run)
    if (native := run / "play-report.json").is_file():
        return {"native_game": read_json(native)}
    episode = Episode(run / "episode")
    return {
        "report": read_json(run / "report.json"),
        "episode": {
            "id": episode.metadata["episode_id"],
            "task": episode.metadata["task_id"],
            "steps": episode.metadata["steps"],
            "status": episode.metadata["status"],
            "duration_seconds": episode.metadata["duration_seconds"],
        },
        "assistance": episode.metadata.get("application", {}),
    }


def write_viewer(run):
    run = Path(run).resolve(strict=True)
    if (run / "play-report.json").is_file():
        raise ValueError("Native human runs use fw-doom-world replay for their recorded demos")
    episode = Episode(run / "episode")
    initial_path = run / "privileged/initial-inspection.json"
    initial = read_json(initial_path) if initial_path.is_file() else {}
    frames = []

    def append_frame(index, observation, feedback):
        trace = initial if index == 0 else read_json(run / "privileged" / f"step-{index:06d}.json")
        frames.append(
            {
                "step": index,
                "tics": observation.structured.get("episode_tics"),
                "rgb": f"../episode/observations/{index:06d}/rgb.png"
                if observation.rgb is not None
                else None,
                "frame_status": trace.get("frame_status"),
                "trace": trace,
                "feedback": feedback,
            }
        )

    append_frame(0, episode.initial_observation(), None)
    for index, row in enumerate(episode.transitions(), 1):
        append_frame(
            index,
            row.result.observation,
            {
                "command": row.action["command"],
                "reward": row.result.reward,
                "outcome": row.result.outcome,
                "elapsed_seconds": row.result.elapsed_seconds,
                "terminated": row.result.terminated,
                "truncated": row.result.truncated,
            },
        )
    payload = json.dumps({"summary": inspection(run), "frames": frames}, allow_nan=False)
    # Observation text is data even when the viewer is opened as a local file.
    payload = payload.replace("<", "\\u003c").replace("&", "\\u0026")
    target = run / "privileged/viewer.html"
    target.write_text(HTML.replace("__RUN_DATA__", payload), encoding="utf-8")
    return target


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doom · State Language run</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101719;color:#e8f0e9}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0 auto;padding:24px;max-width:1500px}
header{display:flex;justify-content:space-between;gap:20px;align-items:start}
h1{font-size:26px;margin:0 0 8px}h2{font-size:16px;margin:0 0 14px;color:#9fd3b3}
p{margin:6px 0;color:#a8b8b0;font-size:14px;line-height:1.5}
.tag{border:1px solid #537e65;padding:7px 12px;border-radius:20px;font-size:13px}
.controls{display:flex;align-items:center;gap:14px;margin:22px 0}
button{border:1px solid #42614e;background:#243b2e;color:inherit;padding:8px 15px;
border-radius:7px;cursor:pointer}input{flex:1;accent-color:#9fd3b3;min-width:80px}
#position{font-variant-numeric:tabular-nums;white-space:nowrap;min-width:160px}
.grid{display:grid;grid-template-columns:minmax(300px,1.2fr) minmax(280px,1fr);gap:16px}
section{background:#182326;border:1px solid #2c3c3e;border-radius:12px;padding:18px;
min-width:0}img{display:block;width:100%;height:auto;image-rendering:pixelated;
background:#0c1113;border-radius:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere;
font:13px/1.6 ui-monospace,monospace;margin:0;max-height:430px;overflow:auto}
#missing{min-height:240px;display:flex;align-items:center;justify-content:center;
border:1px dashed #60736a;color:#b6c8bb}.hint{margin:18px 0}
details{margin-top:20px}summary{cursor:pointer;color:#9fd3b3;margin-bottom:10px}
@media(max-width:700px){body{padding:15px}.grid{grid-template-columns:1fr}
header{display:block}.tag{display:inline-block;margin-top:12px}.controls{flex-wrap:wrap}}
</style></head><body>
<header><div><h1>Doom · State Language</h1>
<p>Recorded observation → grounded facts → plan → bounded skill → observed result</p>
</div><span class="tag" id="status"></span></header>
<p class="hint">Reference-assisted run. Pose, resource and mission signals, optional native visible
labels and declared map topology
are supplied inputs. Null facts mean unknown. This viewer contains private application traces.</p>
<div class="controls"><button id="play" type="button">Play</button>
<input id="timeline" type="range" min="0" value="0" aria-label="Recorded step">
<span id="position" aria-live="polite"></span></div>
<main class="grid"><section><h2>Game observation</h2><img id="frame" alt="Recorded Doom view">
<div id="missing">No fresh image at this simulator boundary</div></section>
<section><h2>Resources, grounded scene and task facts</h2><pre id="facts"></pre></section>
<section><h2>Plan, active skill and confirmation</h2><pre id="decision"></pre></section>
<section><h2>Command and native feedback</h2><pre id="feedback"></pre></section></main>
<details><summary>Run report and declared assistance</summary><pre id="report"></pre></details>
<details><summary>Provider and execution trace</summary><pre id="trace"></pre></details>
<script id="run-data" type="application/json">__RUN_DATA__</script>
<script>
const data=JSON.parse(document.getElementById('run-data').textContent);
const byId=id=>document.getElementById(id), pretty=value=>JSON.stringify(value,null,2);
const slider=byId('timeline');slider.max=data.frames.length-1;
byId('report').textContent=pretty(data.summary);
byId('status').textContent=data.summary.report.success?
 'Observed success':data.summary.episode.status;
function show(){
 const item=data.frames[Number(slider.value)], trace=item.trace;
 const state=trace.inspection||trace.after||trace;
 byId('position').textContent=`Step ${item.step} / ${data.frames.length-1} · tic ${item.tics}`;
 byId('frame').hidden=!item.rgb;byId('missing').hidden=Boolean(item.rgb);
 byId('missing').textContent={
   recorder_overload:'Frame dropped while the recorder was busy',
   capture_queue_overload:'Frame dropped while the controller was behind'
 }[item.frame_status]||'No fresh image at this simulator boundary';
 if(item.rgb)byId('frame').src=item.rgb;else byId('frame').removeAttribute('src');
 byId('facts').textContent=pretty({resources:state.estimate?.measurements||null,
   facts:state.facts||trace.facts_after||{},fireballs:state.fireballs});
 byId('decision').textContent=pretty({plan:state.plan||trace.plan||null,
   skill:state.skill||state.active_skill||trace.skill||null,
   outcome:state.last_outcome||trace.last_outcome||null,
   stop_reason:state.stop_reason||null});
 byId('feedback').textContent=pretty(item.feedback);
 byId('trace').textContent=pretty(trace);
}
let timer=null;
function stop(){clearInterval(timer);timer=null;byId('play').textContent='Play';}
byId('play').addEventListener('click',()=>{
 if(timer){stop();return;}if(Number(slider.value)===Number(slider.max))slider.value=0;
 byId('play').textContent='Pause';timer=setInterval(()=>{
  slider.value=Number(slider.value)+1;show();
  if(Number(slider.value)===Number(slider.max))stop();
 },180);
});
slider.addEventListener('input',()=>{stop();show();});show();
</script></body></html>
"""
