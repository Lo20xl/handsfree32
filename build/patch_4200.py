"""4200 rename + settings patch — textual replacements with asserts (all-or-nothing per file)."""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (relative path, [(old, new, expected_count), ...])
EDITS = [
    ("handjob/settings.py", [
        ('"click_threshold": 0.42,', '"click_threshold": 0.30,', 1),
    ]),
    ("handjob/__init__.py", [
        ('HandJob4100 — camera hand-gesture mouse control for Windows.', 'HandJob4200 — camera hand-gesture mouse control for Windows.', 1),
        ('__version__ = "1.2.0"', '__version__ = "1.3.0"', 1),
        ('APP_NAME = "HandJob4100"', 'APP_NAME = "HandJob4200"', 1),
    ]),
    ("handjob/main.py", [
        ('"HandJob4100_SingleInstance"', '"HandJob4200_SingleInstance"', 1),
    ]),
    ("handjob/overlay.py", [
        ('HandJob4100 overlay cursor + trail', 'HandJob4200 overlay cursor + trail', 1),
        ('HandJob4100OverlayWnd', 'HandJob4200OverlayWnd', 2),
        ('"HandJob4100Overlay"', '"HandJob4200Overlay"', 1),
    ]),
    ("handjob_run.py", [
        ('HandJob4100 — desktop entry point.', 'HandJob4200 — desktop entry point.', 1),
        ('Frozen:     HandJob4100.exe', 'Frozen:     HandJob4200.exe', 1),
        ('"HandJob4100.Desktop.1"', '"HandJob4200.Desktop.1"', 1),
    ]),
    ("ui/index.html", [
        ('<title>HandJob4100</title>', '<title>HandJob4200</title>', 1),
        ('<h1>HandJob4100</h1>', '<h1>HandJob4200</h1>', 1),
        ('HandJob4100 v<span id="fVer">1.2.0</span>', 'HandJob4200 v<span id="fVer">1.3.0</span>', 1),
        ('version:"1.2.0"', 'version:"1.3.0"', 2),
        ('st.version || "1.2.0"', 'st.version || "1.3.0"', 1),
        ('click_threshold:0.42', 'click_threshold:0.30', 1),
        ('Move your hand to steer — pinch thumb&nbsp;+&nbsp;index to left-click. Hold and move to drag.',
         'Move your hand to steer — pinch thumb&nbsp;+&nbsp;middle to left-click. Hold and move to drag.', 1),
        ('hint.textContent = "Move your hand to steer — pinch thumb + index to left-click. Hold and move to drag.";',
         'hint.textContent = "Move your hand to steer — pinch thumb + middle to left-click. Hold and move to drag.";', 1),
        ('<div class="g-desc">Moves the cursor — tracked at the knuckles, so pinching never tugs it</div>',
         '<div class="g-desc">Moves the cursor — follows your index fingertip, so clicking never tugs it</div>', 1),
        ('<div class="g-name">Pinch thumb + index</div><div class="g-desc">Left click — hold &amp; move to drag, trails sparkle</div>',
         '<div class="g-name">Pinch thumb + middle</div><div class="g-desc">Left click — hold &amp; move to drag, trails sparkle</div>', 1),
        ('<div class="g-name">Pinch thumb + middle</div><div class="g-desc">Right click</div>',
         '<div class="g-name">Pinch thumb + ring</div><div class="g-desc">Right click</div>', 1),
        ('<div class="g-name">Closed fist, move up / down</div><div class="g-desc">Scroll</div>',
         '<div class="g-name">Peace sign, move up / down</div><div class="g-desc">Scroll</div>', 1),
        ('<div class="g-name">Open palm</div>', '<div class="g-name">Open palm or fist</div>', 1),
        ('How close thumb and finger must get to register a pinch. Raise it if clicks are hard; lower it if they fire by accident.',
         'How close thumb and finger must get to register a click. Raise it if clicks are hard to trigger; lower it if they fire by accident.', 1),
        ('Fist-scroll distance multiplier.', 'Scroll distance multiplier.', 1),
        ('Natural scrolling for fist gestures', 'Natural scrolling for the peace-sign gesture', 1),
    ]),
]


def main():
    only = set(sys.argv[1:])
    changed = 0
    for rel, ops in EDITS:
        if only and rel not in only:
            continue
        path = os.path.join(ROOT, rel)
        s = io.open(path, encoding="utf-8").read()
        already = all(new in s for _, new, _ in ops)
        if already and not all(old in s for old, _, _ in ops):
            print(f"skip  {rel} (already patched)")
            changed += 1
            continue
        problems = []
        for old, new, expect in ops:
            got = s.count(old)
            if got != expect:
                problems.append(f"{rel}: found {got}x (want {expect}): {old[:70]!r}")
        if problems:
            print("ABORT — no files written yet for this file:")
            for p in problems:
                print("  " + p)
            # do not write this file; continue to report others
            continue
        for old, new, _ in ops:
            s = s.replace(old, new)
        io.open(path, "w", encoding="utf-8").write(s)
        changed += 1
        print(f"patched {rel} ({len(ops)} edits)")
    print(f"DONE {changed}/{len(EDITS)} files")


if __name__ == "__main__":
    sys.exit(main())
