HandJob3000 — hand-gesture mouse control for Windows
======================================================
Version 2.5.0  (x64, Windows 10/11)

INSTALL
  1. Double-click  HandJob3000-Setup-2.5.0.exe
  2. No administrator rights needed — it installs for the current user only
     (default: %LOCALAPPDATA%\Programs\HandJob3000, desktop shortcut optional).
  3. Launch HandJob3000 from the desktop or Start menu.

QUICK START
  1. Click "Start control".
  2. Point with your index finger — the cursor follows the fingertip,
     the point you actually aim with. Starting to point picks the cursor up
     exactly where it is, so there is never a jump.
  3. Pinch thumb + middle finger         -> left click
     (hold the pinch while moving        -> drag, with sparkle trail)
     A click lands where you were aiming a moment earlier, and the cursor
     stays put while you pinch — wobbles never smear a click.
  4. Pinch thumb + ring finger           -> right click
  5. Peace sign (index + middle up),
     move hand up / down                  -> scroll
  6. Open palm or fist, or pinky out     -> pause the cursor (rest your hand)
  7. Ctrl + Alt + H                      -> panic stop (instantly stops control)

  ONE HAND AT A TIME
  The app locks onto the first hand it sees and keeps it: if another hand or
  person enters the frame, they are ignored, until your hand has been gone for
  a moment. No cursor stealing.

  First time in front of the camera, tune the sliders until it feels right —
  the Tuning card has a live pinch meter: pinch slowly and watch a bar cross
  the line at the exact moment a click fires. Raise "Click pinch threshold"
  if clicks are hard, lower it if they fire early.

  The preview shows only the hand wireframe by default (no camera image).
  Switch it in the Camera card: Wireframe / Camera / Off.

WHAT'S NEW IN 2.5.0
  * GPU inference engine (experimental): a second inference backend runs the
    hand models on your graphics card via ONNX Runtime + DirectML — the
    landmark stage goes from ~7.5 ms to ~0.6 ms per frame on a modern GPU,
    cutting the app's CPU use dramatically and shaving latency. It turns on
    automatically (System card: "Inference engine"), falls back to the CPU
    engine if anything is unavailable, and can be forced off there too.
    Custom .task models and 2-hand mode keep using the CPU engine.

WHAT'S NEW IN 2.4.5
  * No more freezing on a stuck camera: camera reads now run on their own
    thread. Some virtual-camera drivers (seen with the NVIDIA Broadcast
    chain) accept a camera and then stop returning frames entirely — that
    used to freeze the app silently (frozen preview, UI alive). Now the app
    notices within ~4 s and reopens the camera itself; if the driver stays
    stuck it says exactly that instead of pretending everything is fine.

WHAT'S NEW IN 2.4.1 - 2.4.4
  * Smoothness pass (2.4.1): the cursor ring now redraws at the cursor's own
    rate with anti-aliased edges, the preview mirrors tracking 1:1, and frame
    timestamps are taken the moment the camera delivers a frame — a visibly
    steadier cursor and ring.
  * Rest-hold (2.4.2): a still hand is rock steady — sub-noise wobble never
    reaches the screen, and deliberate motion keeps zero added lag ("hold"
    slider in Advanced; 2.5 = balanced, 4 = max steadiness).
  * Frozen-camera watchdog (2.4.3): a virtual camera whose source died (Camo
    with the phone disconnected, NVIDIA Broadcast with a stopped capture) is
    detected in ~15 s, the cursor halts, and a message says exactly what to
    fix (unlike a dim physical camera, which gets different advice).
  * Repeat-frame fix + CPU cut (2.4.4) — the big one: virtual cameras
    (Camo / NVIDIA Broadcast / OBS) answer every read by repeating the last
    frame. Those repeats used to corrupt the motion timing and made the
    cursor lurch and lag. They are now dropped before tracking, so timing is
    honest, and ~80% of the CPU work is skipped on such cameras. The camera
    "re-measure" reopen no longer interrupts tracking repeatedly.

WHAT'S NEW IN 2.4.0
  * Hand model selection: a model picker in the System card. Choose the
    bundled model or import any MediaPipe .task hand model (validated by a
    test-load before it is accepted). Switching is live — no restart.
  * Camera picker now shows real device names (Camo, NVIDIA Broadcast, the
    real webcam…) instead of bare index numbers.
  * Fixed a crash: refreshing the camera list could take the whole app down
    (a driver-level access violation when probing cameras). Cameras are now
    enumerated without opening them, and the open-time quality probe runs in
    an isolated subprocess that can crash without killing the app.
  * The preview now mirrors tracking 1:1 (was throttled to ~12 fps, which
    read as lag) and the status strip shows the camera's NEW-frames rate
    ("cam") — virtual cams and low-light auto-exposure repeat frames; that
    repeated rate is what actually limits how smooth the cursor can feel.
  * Watchdog: a camera that repeats frames (full read rate, low unique rate)
    is detected and re-measured automatically.

WHAT'S NEW IN 2.3.1
  * Fixed: a hand that changes its apparent size mid-session (leaning toward
    or away from the camera, rotating toward it) could freeze the cursor
    permanently — the stabilizer now re-locks onto the new size within a
    frame instead of holding the old one forever.
  * Fixed: re-engaging with a pinch already closed (after a clutch
    reposition) could land the click at stale coordinates, yanking the
    cursor backwards; clicks now always land at the re-anchor point.

WHAT'S NEW IN 2.3.0
  * Cursor highlight now disappears the moment your hand leaves the camera
    view (and comes back with it) — no more ghost orb sitting on screen.
  * Camera auto-fallback: some laptop cams answer a 720p request with a
    ~10 fps trickle. The app now MEASURES the delivered rate when opening
    and automatically drops to 640x480 (solid 30 fps on every webcam), plus
    a watchdog that re-measures if the feed degrades while running.
  * Prediction now scales with the camera rate — on a 10 fps feed the
    cursor interpolates across the full gap instead of jumping between
    samples. At 30+ fps nothing changes.
  * Note on GPU: the hand model runs on CPU by design — MediaPipe's Windows
    Python build ships with GPU disabled (not a driver problem). The app
    keeps CPU load low instead: 1-hand tracking, 480p processing, 60 fps
    option. That's why you see ~0% GPU.

WHAT'S NEW IN 2.2.0
  * New landmark stabilizer — the pose "freakouts" are gone. Every frame's
    hand skeleton now passes through an adaptive filter (heavy smoothing at
    rest, effectively raw during fast moves) with a teleport/spike gate, so
    a single noisy frame can no longer flip your pose or fire a phantom
    pinch. The wireframe preview shows the cleaned skeleton too.
  * Sonar v2 — the experimental speaker+mic sensing now reports REAL motion
    velocity in m/s (Doppler centroid), with a steadier power-based motion
    score and a baseline that can't get stuck (median-seeded). The Sonar
    card shows "v +0.42 m/s" style readouts.
  * Fixes: pose classifier no longer flips on tracker z-glitches (palm-scale
    guard); sonar direction now comes from the measured velocity instead of
    a noisy max-bin comparison.

WHAT'S NEW IN 2.1.0
  * 60 fps capture + tracking (System card, "Capture rate"): halves the
    camera latency and makes fast moves noticeably smoother — needs a camera
    that supports 720p60; otherwise the app stays at 30 fps automatically.
  * Much lighter tracking load: the model now tracks exactly one hand by
    default ("Hands to track" in the System card), which cuts per-frame work
    to a third — the biggest speedup in this release.
  * Edge hold: when your hand nears the border of the camera view — where
    tracking gets noisy — the cursor now holds still instead of shaking.
    Adjustable in Advanced ("Edge hold margin"); 0 disables it.
  * Fixed camera handling: the app no longer requests odd internal sizes
    (which some camera drivers answer with a cropped or slow feed). The
    camera runs in its native 720p mode, and the tracking size is scaled down
    cleanly in software. The preview no longer crops the picture either
    ("Processing size" in the System card picks the analysis size).
  * Sonar (experimental, off by default): uses the laptop speakers + mic as
    a tiny sonar — an inaudible tone, and the echo shifts when your hand
    moves. See the Sonar card. Sensing only, it never moves the cursor.

TROUBLESHOOTING
  * Anything looks stuck or frozen -> click "Refresh app" (System card);
    it restarts the camera, model and overlay in place.
  * Cursor does not move
    - Make sure "Start control" is on (top right).
    - Point your index finger at the camera; the status pill should say
      "Active".
    - Check the preview in the app — if it is black, the camera is in use by
      another app (Teams, Zoom, camera app). Close it and reopen HandJob3000.
  * Feels laggy or choppy        -> System card: keep "Hands to track" at 1,
    set "Capture rate" to 60 fps if your camera supports it, and try
    "Processing size" 480p. Check fps on the Camera card stats. The app
    already auto-falls-back to 640x480 if your camera trickles at 720p.
  * Cursor jitters near the screen/camera edges -> that is the edge hold
    doing its job (it pauses instead of shaking). Reduce "Edge hold margin"
    in Advanced if you want the cursor to keep moving closer to the border.
  * Clicks fire by accident         -> lower "Click pinch threshold"
  * Clicks are hard to trigger      -> raise "Click pinch threshold"
  * Cursor jitters                  -> raise "Smoothing"
  * Cursor cannot reach screen edge -> raise "Sensitivity"
  * Cursor overshoots a stop        -> lower "Prediction" (Advanced card)
  * Drags start by accident         -> raise "Drag threshold"
  * Scrolls on its own              -> raise "Scroll dead-zone"
  * Cursor freezes when a second hand appears -> that is by design; the first
    hand keeps control. Leave the frame for a second to hand over.
  * Sonar meter never lights up
    - Use the built-in speakers + mic (headphones never reflect the tone).
    - Try the 17 kHz tone — some speakers roll off hard above it.
    - Pick the explicit built-in devices in the two dropdowns, not "System
      default", and make sure the mic isn't muted in Windows Sound settings.
  * Nothing opens / white window    -> install the Microsoft Edge WebView2
    runtime (comes with Windows 11; on Windows 10 get it from Microsoft).
  * Still stuck                     -> click "Open log" and read handjob.log.

UNINSTALL
  Settings > Apps > HandJob3000 > Uninstall.
  Your settings.json and handjob.log stay in the install folder only.

PRIVACY
  Everything runs locally. Camera frames are processed in memory and are
  never recorded, stored, or sent anywhere. The sonar tone is sound only —
  nothing is recorded from the microphone and nothing leaves the app.
  No account, no telemetry.

NOTES
  * Hand tracking sees your hand best at arm's length, palm toward the camera,
    with decent room light.
  * The gesture cursor replaces your mouse cursor while the app is armed; the
    real cursor returns the moment you click "Stop control".
  * 60 fps helps most on fast moves; if the laptop runs warm or the fan spins
    up, drop back to 30 fps — tracking quality is unaffected.

VERSION HISTORY
  2.4.0  Model picker + validated custom .task imports; named camera list; crash-proof camera enumeration + subprocess quality probe; preview at tracking rate; camera unique-frames stat + repeat-frame watchdog.
  2.3.1  Stabilizer recovers from persistent palm-scale changes (no more frozen cursor after leaning in/out); click anchor can no longer be stale across a re-anchor.
  2.3.0  Orb hides when no hand is detected; camera rate auto-fallback (720p->640x480 on trickle cams) + delivered-rate watchdog; dt-scaled prediction for low-fps feeds.
  2.2.0  Landmark stabilizer (adaptive filter + spike gate — no more pose freakouts or phantom pinches); sonar v2 (Doppler velocity in m/s, power-based score, median-seeded baseline); palm-scale glitch guard.
  2.1.0  60 fps capture option; one-hand default (3x lighter inference);
         edge-hold anti-jitter near frame borders; correct software
         downscaling (no driver crops, preview no longer cropped); fixed
         capture-rate/resolution switching; experimental speaker+mic sonar
         sensing with live echo meter (sonar.py).
  2.0.0  Named HandJob3000. 3D pinch measurement (no more hover-clicks);
         live pinch meter; prediction / drag / dead-zone sliders; debounced
         pose (drop-proof drags); diagnostics readout; cleaner interface.
  1.4.0  Feel rebuild: 144 Hz motion engine (interpolated + predicted cursor
         stream — smooth between camera frames, never overshoots a stop);
         crisper clicks (2-frame confirm + velocity tie-break, ~100 ms faster);
         cursor freezes on the aim point the moment a pinch starts; adaptive
         drag radius (steady taps, sensitive drags); double-click magnet;
         steadier at rest (rest jitter halved).
  1.3.0  Fingertip aiming; left click moved to thumb+middle (right click to
         thumb+ring) so clicking never disturbs the aim; click-lock + 0.12 s
         lookback for wobble-free clicks; peace-sign scroll; sticky primary
         hand (first hand seen keeps control); stronger jitter filter.
  1.2.0  Custom cursor (sky orb) rendering fixed on Windows 11.
  1.1.0  Freeze fixes, wireframe preview, refresh button, resolution setting.
