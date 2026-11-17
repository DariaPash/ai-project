"""Render the completed real PTY capture; never execute its commands again."""

import hashlib
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.development import now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default="submission/cli-recording")
    args = parser.parse_args()
    folder = ROOT / args.folder
    receipt = json.loads((folder / "capture-receipt.json").read_text())
    commands = json.loads((folder / "commands.json").read_text())
    data = json.loads((folder / "terminal-frames.json").read_text())
    if not receipt["success"] or any(c["shell_exit"] != 0 for c in commands):
        raise SystemExit("Capture did not finish successfully; reconcile, do not replay mutations")
    cast_hash = hashlib.sha256((folder / "session.cast").read_bytes()).hexdigest()
    if cast_hash != receipt["raw_cast_sha256"]:
        raise SystemExit("Raw capture changed; stop")
    # Keep all captured screen states and actual delays; omit only post-capture
    # shell cleanup, where no terminal I/O or command execution occurred.
    end = data["frames"][-1]["time"]
    video = folder / "cli-demo.mp4"
    if video.exists():
        raise SystemExit("Video exists; preserve it and choose a new explicit revision")
    render = [
        "/usr/bin/sandbox-exec",
        "-p",
        "(version 1)(allow default)(deny network*)",
        "/usr/bin/swift",
        "-module-cache-path",
        "/private/var/folders/fx/qskf3zh56ns2mvx4hbb9p8gc0000gn/T/opencode/swift-module-cache",
        str(ROOT / "submission/render-terminal.swift"),
        str(folder / "terminal-frames.json"),
        str(folder / "frames"),
    ]
    r = subprocess.run(render, capture_output=True, text=True, timeout=180)
    write_json(
        folder / "render-receipt.json", {"at": now(), "exit": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    )
    if r.returncode:
        raise SystemExit("Terminal rendering failed; see receipt")
    frames = data["frames"]
    # Prepend a hold of the first captured state for its initial timestamp.
    timeline = ["ffconcat version 1.0"]
    for i, frame in enumerate(frames):
        start = 0 if i == 0 else frame["time"]
        finish = frames[i + 1]["time"] if i + 1 < len(frames) else end + 0.04
        if finish <= start:
            continue
        timeline += [f"file 'frames/{i:05d}.png'", f"duration {finish - start:.6f}"]
    timeline.append(f"file 'frames/{len(frames) - 1:05d}.png'")
    (folder / "timeline.ffconcat").write_text("\n".join(timeline) + "\n")
    encode = [
        "/opt/homebrew/bin/ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        str(folder / "timeline.ffconcat"),
        "-t",
        str(end + 0.04),
        "-vf",
        "fps=25,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(video),
    ]
    r = subprocess.run(encode, capture_output=True, text=True, timeout=180)
    write_json(
        folder / "encode-receipt.json",
        {
            "at": now(),
            "exit": r.returncode,
            "stderr": r.stderr,
            "speed": 1,
            "captured_screen_seconds": end,
            "recorder_wall_seconds": receipt["seconds"],
            "edit": "Only idle shell-cleanup after final captured frame omitted; no command/output/active wait cut",
        },
    )
    if r.returncode:
        raise SystemExit("Video encoding failed; see receipt")
    replay_data = json.dumps({"frames": frames, "duration": end, "commands": commands}, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    page = """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Настоящая CLI-сессия</title>
<style>body{background:#090c11;color:#eee;font:16px system-ui;margin:24px}main{max-width:1450px;margin:auto}h1{font-size:23px;color:#4dd8c2}pre{font:clamp(9px,1.06vw,20px)/1.25 ui-monospace,Menlo,monospace;white-space:pre;background:#0b1018;padding:20px;min-height:42.5em;overflow:auto}button,select{font:inherit;padding:8px;background:#213142;color:white;border:1px solid #456;border-radius:5px}input{width:65%}p{color:#aab4c0}small{display:block;margin:12px 0}</style>
<main><h1>Настоящая запись CLI — ввод, выполнение, вывод</h1><p>PTY-сессия · 1× · учебный synthetic_fixture · без сети и слайдов</p>
<button id="play">▶ Воспроизвести</button> <input id="seek" type="range" min="0" step="0.05" value="0"> <span id="clock"></span>
<small><select id="chapter"><option value="0">Начало записи</option></select> · Пробел — пауза, ←/→ — 5 секунд</small>
<pre id="screen"></pre><p>Импорт и индекс действительно изменили кейс: 102 → 105. H остаётся pending. Это воспроизведение записанного терминала, не запись рабочего стола. Команды не исполняются при просмотре.</p></main>
<script id="recording" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('recording').textContent),frames=data.frames;
const slider=document.getElementById('seek'),screen=document.getElementById('screen'),clock=document.getElementById('clock'),play=document.getElementById('play');
slider.max=data.duration;let position=0,playing=false,last=0;
function show(t){position=Math.max(0,Math.min(data.duration,t));slider.value=position;let lo=0,hi=frames.length-1;while(lo<hi){let mid=Math.ceil((lo+hi)/2);if(frames[mid].time<=position)lo=mid;else hi=mid-1;}screen.textContent=frames[lo].screen.lines.join('\\n');clock.textContent=position.toFixed(1)+' / '+data.duration.toFixed(1)+' с';}
function toggle(){playing=!playing;play.textContent=playing?'❚❚ Пауза':'▶ Воспроизвести';last=performance.now();}
play.onclick=toggle;slider.oninput=()=>show(Number(slider.value));
document.getElementById('chapter').onchange=e=>show(Number(e.target.value));
for(const c of data.commands){let option=document.createElement('option');option.value=c.start_seconds;option.textContent=c.start_seconds.toFixed(1)+'с — '+c.command;document.getElementById('chapter').append(option);}
document.onkeydown=e=>{if(e.target.tagName==='SELECT')return;if(e.code==='Space'){e.preventDefault();toggle();}if(e.code==='ArrowLeft')show(position-5);if(e.code==='ArrowRight')show(position+5);};
function tick(t){if(playing){show(position+(t-last)/1000);if(position>=data.duration){playing=false;play.textContent='▶ Воспроизвести';}}last=t;requestAnimationFrame(tick);}show(0);requestAnimationFrame(tick);
</script></html>""".replace("PAYLOAD", replay_data)
    page = page.replace(
        "Импорт и индекс действительно изменили кейс: 102 → 105.",
        f"Фактическая case revision: {receipt['before_revision']} → {receipt['after_revision']}.",
    )
    capture_plan = json.loads((folder / "capture-plan.json").read_text())
    if capture_plan.get("no_provider_calls") is False:
        page = page.replace(
            "без сети и слайдов",
            "без слайдов · новый host-контекст через существующее OpenAI-подключение",
        )
    (folder / "replay.html").write_text(page)
    probe = subprocess.run(
        [
            "/opt/homebrew/bin/ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name,codec_type,width,height",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    metadata = json.loads(probe.stdout)
    assets = {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in (video, folder / "replay.html", folder / "session.cast", folder / "commands.json")
    }
    write_json(
        folder / "video-manifest.json",
        {
            "at": now(),
            "actual": True,
            "capture": "genuine_PTY",
            "screen_capture": False,
            "slides": False,
            "speed": 1,
            "audio": False,
            "published": False,
            "submitted": False,
            "capture_receipt": "capture-receipt.json",
            "commands_completed": len(commands),
            "metadata": metadata,
            "assets": assets,
            "trim": "No active execution removed; idle post-recording shell cleanup omitted",
            "browser_replay_execution_checked": False,
            "reason": "HTML created locally; browser runtime not yet inspected",
        },
    )
    print(
        json.dumps(
            {"video": str(video), "replay": str(folder / "replay.html"), "metadata": metadata, "frames": len(frames)}
        )
    )


if __name__ == "__main__":
    main()
