"""Path helpers — PyInstaller-frozen and dev aware.

app_dir():    user-writable folder (beside the exe when frozen, repo root in dev).
assets_dir(): read-only bundled assets (hand_landmarker.task, sample image).
"""
import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def assets_dir():
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "assets")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


CONFIG_PATH = os.path.join(app_dir(), "settings.json")
LOG_PATH = os.path.join(app_dir(), "handjob.log")
