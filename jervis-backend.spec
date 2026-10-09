# PyInstaller recipe for Jervis's engine (the Python backend), bundled inside the installer.
#
#     pip install -r requirements.txt pyinstaller && pyinstaller jervis-backend.spec
#
# Output: dist/jervis-backend/ (a folder, which starts much faster than a one-file build). electron-builder copies it
# into the app's resources as backend/ (see package.json), where backend.js starts it. Build it in a clean environment
# with only requirements.txt installed: whatever else is installed may be pulled in.
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []


def take_all(package):
    d, b, h = collect_all(package)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Offline speech recognition: native libraries plus the voice-activity model file
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers"):
    take_all(package)
# FLAC encoders that speech_recognition runs for online recognition
datas += collect_data_files("speech_recognition")
binaries += collect_dynamic_libs("av")
datas += collect_data_files("certifi")
datas += collect_data_files("googleapiclient")
datas += collect_data_files("tzdata")   # zoneinfo's time zones (forecast.py)
datas += collect_data_files("phonikud")   # its pronunciation tables (hebrew_voice.py)
hiddenimports += ["tzdata", "forecast", "web_search"]

if sys.platform == "win32":
    for package in ("uiautomation", "comtypes", "pycaw"):
        take_all(package)
    hiddenimports += ["screen_windows", "winctl"]
elif sys.platform == "darwin":
    hiddenimports += ["screen_mac", "Quartz", "AppKit", "ApplicationServices"]

# Jervis's own modules that are only imported when needed
hiddenimports += ["selftest", "screen_vision", "computer_use", "stt_local", "local_ai", "agent_core", "agent_blender",
                  "agent_minecraft", "agent_memory", "blender_kit", "blender_assets", "spatial", "cinema", "blender_motion", "blender_places", "blender_props", "blender_world", "blender_bridge", "reasoning",
                  "vision", "image_analysis", "visual_scene", "semantics", "scene_state", "scene_edit", "reconstruct",
                  "visual_critique", "environment", "blender_nature", "spotify_match",
                  "microphones", "pointer_motion", "hebrew_voice", "phonikud", "phonikud_onnx", "num2words"]
# Scripts that run inside Blender itself, so they ship as plain source files (see blender_control / agent_blender)
datas += [("blender_bridge.py", "."), ("blender_kit.py", "."), ("blender_assets.py", "."), ("spatial.py", "."), ("cinema.py", "."), ("blender_motion.py", "."),
          ("blender_places.py", "."), ("blender_nature.py", "."), ("blender_props.py", "."), ("blender_world.py", ".")]
# The pages the engine serves to a phone itself (phone_control.serve_static). Without them, an installed copy
# answered every phone with "The phone page couldn't be loaded" (running from source has them next to app.py).
datas += [("phone_client.html", "."), ("phone_sw.js", "."), ("confirm.html", ".")]

excludes = [
    # Local image generation (optional, installed separately with requirements-local-images.txt) and other large
    # packages that may be present on a developer's machine but are not part of Jervis
    "torch", "torchvision", "torchaudio", "diffusers", "transformers", "accelerate", "safetensors",
    "livekit", "playwright", "tkinter", "matplotlib", "IPython", "pytest", "sympy",
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
# Leave out what Jervis never uses: PocketSphinx's offline models, other systems' FLAC encoders, and the
# descriptions of hundreds of Google APIs (only Calendar is used).
FLAC = {"win32": "flac-win32.exe", "darwin": "flac-mac"}.get(sys.platform, "flac-linux-x86_64")


def wanted(dest):
    d = dest.replace("\\", "/")
    if "speech_recognition/pocketsphinx-data/" in d:
        return False
    if d.startswith("speech_recognition/flac-") and not d.endswith(FLAC):
        return False
    if "googleapiclient/discovery_cache/documents/" in d and not d.endswith("/calendar.v3.json"):
        return False
    return True


a.datas = [entry for entry in a.datas if wanted(entry[0])]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jervis-backend",
    console=True,           # the window starts it hidden (windowsHide) and reads its output into the log
    disable_windowed_traceback=False,
    upx=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="jervis-backend")
