# Build on macOS with: python -m PyInstaller --clean --noconfirm packaging/BUDDY.spec
from pathlib import Path
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from buddy.core.platform_support import MIN_MACOS_VERSION, require_apple_silicon

require_apple_silicon()
root = Path(SPECPATH).parent
hidden = collect_submodules("buddy.skills") + collect_submodules("pyttsx3.drivers")
hidden += collect_submodules("openwakeword")
data = collect_data_files("openwakeword")
binaries = []
if find_spec("ai_edge_litert") is not None:
    lite_data, lite_binaries, lite_hidden = collect_all("ai_edge_litert")
    data += lite_data
    binaries += lite_binaries
    hidden += lite_hidden
analysis = Analysis(
    [str(root / "packaging" / "desktop_entry.py")],
    pathex=[str(root)], binaries=binaries, datas=data, hiddenimports=hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["PyQt5", "PyQt6", "tkinter"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="BUDDY",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, argv_emulation=False, target_arch="arm64",
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, strip=False, upx=False, name="BUDDY")
application = BUNDLE(
    collection, name="BUDDY.app", bundle_identifier="io.lexa.buddy",
    info_plist={
        "CFBundleShortVersionString": "0.2.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": True,
        "LSMinimumSystemVersion": MIN_MACOS_VERSION,
        "LSArchitecturePriority": ["arm64"],
        "NSMicrophoneUsageDescription": "BUDDY records commands after push-to-talk or an enabled local wake word.",
        "NSAppleEventsUsageDescription": "BUDDY changes volume and opens allowlisted apps when you ask.",
    },
)
