"""Assemble actual v5 crops and complete corrected text. Never overwrite old media."""

import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.contracts import sha
from tools.development import now, write_json
from pypdf import PdfReader


def plain(text):
    text = re.sub(r"^#{1,6} ", "", text, flags=re.M).replace("**", "").replace("`", "")
    return "\n".join(
        line.strip().strip("|").replace(" | ", " — ")
        for line in text.splitlines()
        if not re.match(r"^\s*\|?[-: ]+\|", line)
    )


def main():
    folder = ROOT / "submission/full-story-v5"
    receipt = json.loads((folder / "capture-receipt.json").read_text())
    assert receipt["success"] and receipt["commands_completed"] == 12
    assert sha((folder / "session.cast").read_bytes()) == receipt["raw_cast_sha256"]
    frames = json.loads((folder / "terminal-frames.json").read_text())["frames"]
    commands = json.loads((folder / "commands.json").read_text())
    screenshots = folder / "screenshots"
    screenshots.mkdir(exist_ok=False)
    crops = {}
    for scene in ("sources", "options", "decision", "economics", "communication", "memory", "resume", "impact"):
        command = next(c for c in commands if c["command"] == "review " + scene)
        index = max(i for i, frame in enumerate(frames) if frame["time"] <= command["end_seconds"] + 0.2)
        frame = frames[index]
        lines = frame["screen"]["lines"]
        last = max(i for i, line in enumerate(lines) if line)
        echoes = [i for i, line in enumerate(lines) if "ai-project$ review " + scene in line]
        start = echoes[-1] if echoes else max(0, last - 15)
        y = 95 + start * 25
        height = min(1000 - y - 45, (last - start + 1) * 25 + 10)
        source = folder / "frames" / f"{index:05d}.png"
        dest = screenshots / f"{scene}.png"
        result = subprocess.run(
            [
                "/opt/homebrew/bin/ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-vf",
                f"crop=1504:{height}:48:{y}",
                "-frames:v",
                "1",
                str(dest),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        crops[scene] = {
            "file": dest.name,
            "sha256": sha(dest.read_bytes()),
            "source_frame": source.name,
            "source_sha256": sha(source.read_bytes()),
            "time_s": frame["time"],
            "crop": {"x": 48, "y": y, "width": 1504, "height": height},
            "command": command["command"],
        }
    write_json(
        screenshots / "manifest.json",
        {
            "actual_captured_pixels": True,
            "origin": "Actual new v5 PTY; no new model calls",
            "video_sha256": sha((folder / "cli-demo.mp4").read_bytes()),
            "crops": crops,
        },
    )
    pages = [
        {
            "title": "Исправленный технический разбор v5",
            "body": "Папка IDE-агента: LLM анализирует, CLI извлекает, считает и сохраняет. Не автономное приложение.\n\n"
            "Новая настоящая PTY-запись сохранённого синтетического кейса: 12 команд, checkpoint173 →174. "
            "Новой модельной генерации/независимого ревью в ролике нет.\n\n"
            "Главное исправление: при весах0,5/0,3/0,2 improve=3,5, status quo=3,4; старое утверждение о смене лидера ошибочно. "
            "Старые v3/v4 сохраняются как история. Текущий вывод — в этой исправленной сводке.\n\n"
            "Все источники учебные; бизнес-решение pending. Полная цена результата и время человека неизвестны. "
            "Конкурс юридически не отправлен; GitHub не заменяет обязательную площадку видео.",
        }
    ]
    for scene, title, body in [
        (
            "options",
            "Арифметика без ложной смены лидера",
            "Три сценария пересчитаны одной Decimal-функцией из сохранённых scores/weights. Улучшить лидирует в показанных сценариях, не при любых весах. Баллы не доказывают спрос.",
        ),
        (
            "decision",
            "Решение и предложения не смешиваются",
            "DEC-001@4 pending закрепляет STR-001@3/STR-002@3. Более новые STR@5 не заменяют его автоматически. Отсутствие разрешения на внедрение не означает победу status quo по баллам.",
        ),
        (
            "resume",
            "Новый процесс читает журнал",
            "Настоящий checkpoint и новый процесс status. Business-H остаётся pending. Этот технический результат не доказывает полезность стратегии.",
        ),
    ]:
        pages.append(
            {
                "title": title,
                "body": body,
                "image": "screenshots/" + scene + ".png",
                "caption": "Фактический PTY: " + crops[scene]["command"] + "; t=" + str(crops[scene]["time_s"]) + "с.",
            }
        )
    for name in ("DEMO-SUMMARY.md", "REVIEW-FOLLOWUP.md"):
        text = (ROOT / "submission/v5-content" / name).read_text()
        for part in re.split(r"(?m)^## ", text):
            lines = part.splitlines()
            if not lines:
                continue
            pages.append(
                {
                    "title": plain(lines[0]).strip(),
                    "body": plain("\n".join(lines[1:])).strip() or "См. последующие разделы.",
                }
            )
    write_json(folder / "pages.json", pages)
    output = folder / "description-final.pdf"
    command = [
        "/usr/bin/sandbox-exec",
        "-p",
        "(version 1)(allow default)(deny network*)",
        "/usr/bin/swift",
        "-module-cache-path",
        "/private/var/folders/fx/qskf3zh56ns2mvx4hbb9p8gc0000gn/T/opencode/swift-module-cache",
        str(ROOT / "submission/render-v4-pdf.swift"),
        str(folder / "pages.json"),
        str(output),
        "v5",
    ]
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=180)
    write_json(
        folder / "pdf-render-receipt.json",
        {"at": now(), "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
    )
    if result.returncode:
        raise RuntimeError("PDF render failed; preserve attempt")
    reader = PdfReader(output)
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    (folder / "pdf-extracted.txt").write_text(extracted)
    tokens = lambda text: re.findall(r"[^\W_]+", text.casefold())
    expected = tokens(" ".join(p["body"] for p in pages))
    actual = iter(tokens(extracted))
    missing = next((word for word in expected if not any(candidate == word for candidate in actual)), None)
    check = {
        "pages": len(reader.pages),
        "source_body_words": len(expected),
        "first_missing_word": missing,
        "all_body_words_in_order": missing is None,
        "image_count": sum(len(page.images) for page in reader.pages),
        "sha256": sha(output.read_bytes()),
    }
    write_json(folder / "pdf-text-verification.json", check)
    if missing:
        raise RuntimeError("PDF body extraction mismatch; preserve output")
    print(json.dumps(check))


if __name__ == "__main__":
    main()
