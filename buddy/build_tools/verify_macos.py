"""Audit a real app's Mach-O slices and deployment targets using Apple's build tools."""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import struct
import subprocess
from pathlib import Path

from buddy.core.errors import BuddyError
from buddy.core.platform_support import MIN_MACOS_VERSION, require_apple_silicon, version_tuple

THIN_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce"}
FAT_MAGICS = {
    b"\xca\xfe\xba\xbe": ">",
    b"\xbe\xba\xfe\xca": "<",
    b"\xca\xfe\xba\xbf": ">",
    b"\xbf\xba\xfe\xca": "<",
}


def is_macho(path: Path) -> bool:
    with path.open("rb") as file:
        header = file.read(8)
    if header[:4] in THIN_MAGICS:
        return True
    if header[:4] in FAT_MAGICS and len(header) == 8:
        # Java class files share one magic number, but not the bounded slice count.
        return 1 <= struct.unpack(FAT_MAGICS[header[:4]] + "I", header[4:])[0] <= 32
    return False


def minimum_os(load_commands: str) -> str:
    versions = []
    for block in re.split(r"Load command \d+\s*\n", load_commands):
        if re.search(r"\bcmd LC_BUILD_VERSION\b", block):
            platform = re.search(r"\bplatform\s+(\S+)", block)
            if platform is None or platform.group(1).lower() not in {"1", "macos"}:
                raise ValueError("A bundled Mach-O targets a platform other than macOS.")
            version = re.search(r"\bminos\s+([0-9.]+)", block)
        elif re.search(r"\bcmd LC_VERSION_MIN_MACOSX\b", block):
            version = re.search(r"\bversion\s+([0-9.]+)", block)
        else:
            continue
        if version is None or not version_tuple(version.group(1)):
            raise ValueError("A bundled Mach-O has an invalid deployment target.")
        versions.append(version.group(1))
    if not versions:
        raise ValueError("A bundled Mach-O has no verifiable macOS deployment target.")
    return max(versions, key=lambda value: (version_tuple(value) + (0, 0, 0))[:3])


def inspect_binary(path: Path) -> dict:
    def command(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout

    architectures = command("/usr/bin/lipo", "-archs", str(path)).strip().split()
    if "arm64" not in architectures:
        raise ValueError(f"Missing arm64 slice: {path.name}")
    deployment = minimum_os(command("/usr/bin/otool", "-arch", "arm64", "-l", str(path)))
    return {"architectures": architectures, "minimum_macos": deployment}


def verify_bundle(app: Path, *, inspector=inspect_binary) -> dict:
    app = app.resolve()
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    declared = info.get("LSMinimumSystemVersion")
    if declared != MIN_MACOS_VERSION:
        raise ValueError(f"The app must declare macOS {MIN_MACOS_VERSION} as its baseline.")
    name = info.get("CFBundleExecutable", "")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("Invalid app executable name.")
    executable = app / "Contents/MacOS" / name
    if not executable.is_file() or not is_macho(executable):
        raise ValueError("The app has no Mach-O entry executable.")
    baseline = (version_tuple(MIN_MACOS_VERSION) + (0, 0, 0))[:3]
    binaries = []
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file() or not is_macho(path):
            continue
        details = inspector(path)
        architectures = details["architectures"]
        if "arm64" not in architectures:
            raise ValueError(f"Missing arm64 slice: {path.relative_to(app)}")
        if path == executable and architectures != ["arm64"]:
            raise ValueError("The app entry executable must be arm64 only.")
        if (version_tuple(details["minimum_macos"]) + (0, 0, 0))[:3] > baseline:
            raise ValueError(
                f"{path.relative_to(app)} needs macOS {details['minimum_macos']}, "
                f"above the {MIN_MACOS_VERSION} baseline."
            )
        binaries.append({"path": str(path.relative_to(app)), **details})
    return {
        "app": app.name,
        "version": info.get("CFBundleShortVersionString", ""),
        "architecture": "arm64",
        "minimum_macos": MIN_MACOS_VERSION,
        "target_families": ["M1", "M2", "M3", "M4", "M5"],
        "compatibility_basis": (
            "Native arm64 ABI and binary audit; no per-chip physical certification."
        ),
        "verified_binary_count": len(binaries),
        "binaries": binaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        require_apple_silicon()
        manifest = verify_bundle(args.app)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Verified {manifest['verified_binary_count']} arm64 binaries; macOS 14+ baseline.")
        return 0
    except (BuddyError, ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Apple Silicon bundle verification failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
