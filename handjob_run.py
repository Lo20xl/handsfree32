"""HandJob3000 — desktop entry point.

Dev:        python -m handjob --dev      (opens the UI in your browser)
Normal:     python handjob_run.py       (pywebview window)
Frozen:     HandJob3000.exe             (same as above, camera-permission friendly)
"""
import ctypes
import os
import sys


def main():
    # Windows shows a generic "Python" identity to the camera privacy API;
    # set an explicit AppUserModelID so the OS can attribute camera use.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HandJob3000.Desktop.1")
    except Exception:
        pass
    if os.path.basename(sys.executable).lower().startswith("python"):
        # camera permission prompts work better with a distinct process name cue
        pass
    from handjob.main import main as app_main
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
