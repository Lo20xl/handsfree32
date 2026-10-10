"""3000 rename sweep (4250 -> 3000) — user asked the app be named HandJob3000.

Full-name replace per file (every occurrence is a name reference), with a
must-have refs assertion on the source files. Also renames probe scripts and
deletes stale old-generation build artifacts that would collide with the
fresh build (old HandJob3000.spec / build dir / 7z from the ancient 3000 era).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# full sweep files; must_have=True -> assert at least 1 occurrence pre-replace
SWEEP = [
    ("build_installer.sh", True),
    ("build/installer.iss", True),
    ("build/deliver.sh", True),
    ("build/frozen_probe.cmd", True),
    ("build/probe4250.cmd", True),
    ("build/probe4250_run_as_user.ps1", True),
    ("build/dev_probe.cmd", False),
    ("build/dev_probe_run_as_user.ps1", False),
    ("build/frozen_probe_run_as_user.ps1", False),
    ("handjob/__init__.py", True),
    ("handjob/main.py", True),
    ("handjob/overlay.py", True),
    ("handjob/engine.py", True),
    ("handjob/gestures.py", True),
    ("handjob_run.py", True),
    ("tests/test_handjob.py", True),
    ("ui/index.html", True),
]

RENAME_FILES = [
    ("build/probe4250.cmd", "build/probe3000.cmd"),
    ("build/probe4250_run_as_user.ps1", "build/probe3000_run_as_user.ps1"),
]

# stale artifacts from the ANCIENT 3000-era build — must go before the new
# HandJob3000 build or PyInstaller/spec generation collides with old content
STALE = ["HandJob3000.spec", "build/HandJob3000.7z"]


def main():
    total = 0
    for rel, must in SWEEP:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"skip (missing) {rel}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        n = text.count("HandJob4250")
        if must:
            assert n >= 1, f"{rel}: no HandJob4250 refs found"
        if n:
            text = text.replace("HandJob4250", "HandJob3000")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        total += n
        print(f"ok {rel} ({n} refs)")

    for old, new in RENAME_FILES:
        op, np_ = os.path.join(ROOT, old), os.path.join(ROOT, new)
        if os.path.exists(op):
            os.replace(op, np_)
            print(f"renamed {old} -> {new}")

    for rel in STALE:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            os.remove(p)
            print(f"deleted {rel}")

    print(f"PATCH_3000_DONE {total} refs swept")


if __name__ == "__main__":
    main()
