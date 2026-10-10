"""HandJob3000 — camera hand-gesture mouse control for Windows."""
__version__ = "2.4.5"
APP_NAME = "HandJob3000"

# mediapipe 1.x eagerly imports its audio stack -> sounddevice -> PortAudio,
# which raises on machines with no usable audio device (Session 0, headless).
# Hand tracking needs no audio: stub the module out if it can't initialize.
# Must happen here so ANY importer (engine, tests) is covered.
try:
    import sounddevice  # noqa: F401
except Exception:
    import sys as _sys
    import types as _types
    _sys.modules.setdefault("sounddevice", _types.ModuleType("sounddevice"))
