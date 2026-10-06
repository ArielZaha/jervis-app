# PyInstaller recipe for Jarvis's engine (the Python backend), bundled inside the installer.
#
#     pip install -r requirements.txt pyinstaller && pyinstaller jarvis-backend.spec
#
# Output: dist/jarvis-backend/ (a folder, which starts much faster than a one-file build). electron-builder copies it
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
hiddenimports += ["tzdata", "forecast", "web_search"]
# The phone app the backend serves to a paired phone (phone_control.serve_static reads these via paths.resource)
datas += [(f, ".") for f in ("phone_client.html", "phone_sw.js", "confirm.html", "phone_manifest.webmanifest")]
datas += [("phone_icons", "phone_icons")]

if sys.platform == "win32":
    for package in ("uiautomation", "comtypes", "pycaw"):
        take_all(package)
    hiddenimports += ["screen_windows", "winctl"]
elif sys.platform == "darwin":
    hiddenimports += ["screen_mac", "Quartz", "AppKit", "ApplicationServices"]

# Jarvis's own modules that are only imported when needed
hiddenimports += ["selftest", "screen_vision", "computer_use", "stt_local", "local_ai"]

excludes = [
    # Local image generation (optional, installed separately with requirements-local-images.txt) and other large
    # packages that may be present on a developer's machine but are not part of Jarvis
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
# Leave out what Jarvis never uses: PocketSphinx's offline models, other systems' FLAC encoders, and the
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
    name="jarvis-backend",
    console=True,           # the window starts it hidden (windowsHide) and reads its output into the log
    disable_windowed_traceback=False,
    upx=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="jarvis-backend")
