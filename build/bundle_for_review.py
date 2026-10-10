"""Bundle HandJob3000 source into a review package for Claude.

Produces two files in build/out/:
  - HandJob3000-review-bundle.md   every source file, concatenated with headers
                                    (paste straight into a Claude chat)
  - HandJob3000-src.zip            the raw tree (for Claude Code / local review)

Includes: handjob/ package, tests, ui/index.html, docs (ARCHITECTURE/README/
HANDJOB_REPORT), build_installer.sh, spec files, live settings + runtime logs
(crash.log/handjob.log are the bug evidence — camera-repeat frames etc).
Excludes: .venv, dist, dist-installer, models (binary .task), backups.

Run:  .venv/Scripts/python.exe build/bundle_for_review.py
"""
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")

# bundle-order: entry first, then engine core, then peripherals
CODE = [
    "handjob/__init__.py",
    "handjob/main.py",
    "handjob/paths.py",
    "handjob/settings.py",
    "handjob/engine.py",
    "handjob/motion.py",
    "handjob/click_refiner.py",
    "handjob/gestures.py",
    "handjob/hand3d.py",
    "handjob/lmsmooth.py",
    "handjob/smoothing.py",
    "handjob/overlay.py",
    "handjob/input_win32.py",
    "handjob/sonar.py",
    "tests/test_handjob.py",
    "ui/index.html",
]
DOCS = ["ARCHITECTURE.md", "README.md", "HANDJOB_REPORT.md"]
MISC = ["build_installer.sh", "HandJob3000.spec", "build/installer.iss", "settings.json"]
LIVE = [  # runtime evidence from the installed app
    os.path.join(os.environ["LOCALAPPDATA"], "Programs", "HandJob3000", "handjob.log"),
    os.path.join(os.environ["LOCALAPPDATA"], "Programs", "HandJob3000", "crash.log"),
    os.path.join(os.environ["LOCALAPPDATA"], "Programs", "HandJob3000", "settings.json"),
]


def head(path):
    ext = os.path.splitext(path)[1]
    lang = {".py": "python", ".html": "html", ".js": "javascript",
            ".sh": "bash", ".json": "json", ".iss": "ini", ".log": "text",
            ".md": "markdown", ".spec": "python"}.get(ext, "")
    n = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
    return f"## `{path}` ({n} lines)\n\n```{lang}\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    md_path = os.path.join(OUT, "HandJob3000-review-bundle.md")
    zip_path = os.path.join(OUT, "HandJob3000-src.zip")

    parts = ["# HandJob3000 — full source bundle for Claude review\n",
             "Python + webview app: webcam hand tracking (MediaPipe) → Windows "
             "mouse control. v2.4.0, build line 3000.\n",
             "Known-problem areas for the reviewer: cursor jitter at frame "
             "edges, camera downscaling behavior, latency budget "
             "(emitter 144Hz / model ~4-8ms), sonar (experimental), "
             "camera-repeat-frame reopen loop.\n",
             "---\n"]
    n = 0
    for group, paths in [("CODE", CODE), ("DOCS", DOCS), ("BUILD/CONFIG", MISC)]:
        for p in paths:
            fp = os.path.join(REPO, p.replace("/", os.sep))
            if not os.path.exists(fp):
                continue
            txt = open(fp, encoding="utf-8", errors="replace").read()
            parts.append(head(p) + txt.rstrip("\n") + "\n```\n\n")
            n += 1
    parts.append("---\n\n## RUNTIME LOGS (from installed app — bug evidence)\n\n")
    for p in LIVE:
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8", errors="replace").read()
        name = os.path.basename(p)
        # keep tails — full logs are huge and old
        lines = txt.splitlines()
        tail = "\n".join(lines[-120:]) if len(lines) > 120 else txt
        parts.append(f"### `{name}` (last {min(len(lines),120)} lines)\n\n```\n{tail}\n```\n\n")
        n += 1
    bundle = "".join(parts)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(bundle)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in CODE + DOCS + MISC:
            fp = os.path.join(REPO, p.replace("/", os.sep))
            if os.path.exists(fp):
                z.write(fp, p)

    chars = len(bundle)
    print(f"files bundled : {n}")
    print(f"markdown      : {md_path}  ({chars:,} chars ≈ {chars//4:,} tokens)")
    print(f"zip           : {zip_path}  ({os.path.getsize(zip_path):,} bytes)")
    if chars > 200_000:
        print("NOTE: over ~200k chars — paste per-file or upload the zip instead")


if __name__ == "__main__":
    main()
