"""4250 rename + 2.0.0 version — textual replacements with asserts (all-or-nothing per file).

Source files use counted edits (precision); build scripts use a full HandJob4200->HandJob4250
sweep (every occurrence is a name reference). Also renames the probe scripts 4200->4250.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COUNTED = [
    ("handjob/__init__.py", [
        ('HandJob4200 — camera hand-gesture mouse control for Windows.', 'HandJob4250 — camera hand-gesture mouse control for Windows.', 1),
        ('__version__ = "1.4.0"', '__version__ = "2.0.0"', 1),
        ('APP_NAME = "HandJob4200"', 'APP_NAME = "HandJob4250"', 1),
    ]),
    ("handjob/main.py", [
        ('HandJob4200 entry point', 'HandJob4250 entry point', 1),
    ]),
    ("handjob/overlay.py", [
        ('HandJob4200 overlay cursor + trail', 'HandJob4250 overlay cursor + trail', 1),
        ('HandJob4200OverlayWnd', 'HandJob4250OverlayWnd', 2),
        ('"HandJob4200Overlay"', '"HandJob4250Overlay"', 1),
    ]),
    ("handjob/engine.py", [
        ('HandJob4200 engine: camera ->', 'HandJob4250 engine: camera ->', 1),
    ]),
    ("handjob/gestures.py", [
        ('HandJob4200 scheme', 'HandJob4250 scheme', 1),
    ]),
    ("handjob_run.py", [
        ('HandJob4200 — desktop entry point.', 'HandJob4250 — desktop entry point.', 1),
        ('Frozen:     HandJob4200.exe', 'Frozen:     HandJob4250.exe', 1),
        ('"HandJob4200.Desktop.1"', '"HandJob4250.Desktop.1"', 1),
    ]),
    ("tests/test_handjob.py", [
        ('HandJob4200 test suite', 'HandJob4250 test suite', 1),
        ('settings.get("click_threshold") == 0.20', 'settings.get("click_threshold") == 0.15', 1),
    ]),
]

SWEEP = [  # full name sweep; (path, extra_counted_edits)
    ("build_installer.sh", [('Setup-1.4.0.exe', 'Setup-2.0.0.exe', 2)]),
    ("build/installer.iss", [('#define AppVersion "1.4.0"', '#define AppVersion "2.0.0"', 1)]),
    ("build/deliver.sh", []),
    ("build/probe4200.cmd", [('probe4200_out.txt', 'probe4250_out.txt', 2), ('PROBE4200_EXIT', 'PROBE4250_EXIT', 1)]),
    ("build/frozen_probe.cmd", []),
    ("build/probe4200_run_as_user.ps1", [
        ('probe4200.cmd', 'probe4250.cmd', 1),
        ('probe4200_out.txt', 'probe4250_out.txt', 1),
        ('PROBE4200_EXIT', 'PROBE4250_EXIT', 1),
        ('FROZEN 4200 PROBE OUTPUT', 'FROZEN 4250 PROBE OUTPUT', 1),
    ]),
]

# delete stale spec so the build regenerates a 4250 one
DELETE = ["HandJob4200.spec"]


def apply_edits(rel, edits):
    path = os.path.join(ROOT, rel)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for old, new, count in edits:
        n = text.count(old)
        assert n == count, f"{rel}: expected {count}x {old!r}, found {n}"
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main():
    only = set(sys.argv[1:])

    for rel, edits in COUNTED:
        if only and rel not in only:
            continue
        apply_edits(rel, edits)
        print(f"ok {rel} (counted)")

    for rel, extra in SWEEP:
        if only and rel not in only:
            continue
        path = os.path.join(ROOT, rel)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        n = text.count("HandJob4200")
        assert n >= 1, f"{rel}: no HandJob4200 to sweep"
        text = text.replace("HandJob4200", "HandJob4250")
        for old, new, count in extra:
            c = text.count(old)
            assert c == count, f"{rel}: expected {count}x {old!r} after sweep, found {c}"
            text = text.replace(old, new)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"ok {rel} (swept {n})")

    # rename probe script files (if not already)
    for old, new in [("build/probe4200.cmd", "build/probe4250.cmd"),
                     ("build/probe4200_run_as_user.ps1", "build/probe4250_run_as_user.ps1")]:
        op, np_ = os.path.join(ROOT, old), os.path.join(ROOT, new)
        if os.path.exists(op):
            os.replace(op, np_)
            print(f"renamed {old} -> {new}")

    for rel in DELETE:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            os.remove(p)
            print(f"deleted {rel}")

    print("PATCH_4250_DONE")


if __name__ == "__main__":
    main()
