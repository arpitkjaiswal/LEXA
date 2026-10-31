import plistlib

import pytest

from buddy.build_tools.verify_macos import is_macho, minimum_os, verify_bundle
from buddy.core.errors import ConfigurationError
from buddy.core.platform_support import host_support, require_apple_silicon


@pytest.mark.parametrize(
    "family,os_version",
    [
        ("M1", "14.0"),
        ("M2", "14.7.1"),
        ("M3", "15.0"),
        ("M4", "15.3"),
        ("M5", "26.0"),
        ("future arm64", "27.0"),
    ],
)
def test_native_abi_accepts_all_target_families_and_successors(family, os_version):
    assert host_support(system="darwin", machine="arm64", version=os_version).supported


@pytest.mark.parametrize(
    "system,machine,version",
    [
        ("darwin", "x86_64", "26.0"),
        ("darwin", "arm64", "13.7"),
        ("darwin", "arm64", ""),
        ("linux", "aarch64", "14.0"),
    ],
)
def test_unsupported_host_is_rejected(system, machine, version):
    assert not host_support(system=system, machine=machine, version=version).supported


def test_rosetta_diagnostic_prevents_wrong_python(monkeypatch):
    from buddy.core import platform_support

    monkeypatch.setattr(platform_support.sys, "platform", "darwin")
    monkeypatch.setattr(platform_support.platform, "machine", lambda: "x86_64")
    with pytest.raises(ConfigurationError, match="Rosetta"):
        require_apple_silicon()


def test_macho_deployment_parser_uses_minimum_not_sdk():
    commands = """Load command 0
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform macos
    minos 12.0
      sdk 26.1
Load command 1
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 13.3
      sdk 26.1
"""
    assert minimum_os(commands) == "13.3"
    with pytest.raises(ValueError, match="other than macOS"):
        minimum_os(commands.replace("platform macos", "platform ios"))
    with pytest.raises(ValueError, match="no verifiable"):
        minimum_os("no load commands")


def bundle(tmp_path):
    app = tmp_path / "BUDDY.app"
    executable = app / "Contents/MacOS/BUDDY"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 28)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "BUDDY",
                "LSMinimumSystemVersion": "14.0",
                "CFBundleShortVersionString": "0.2.0",
            }
        )
    )
    return app


def test_binary_audit_checks_transitive_libraries(tmp_path):
    app = bundle(tmp_path)
    library = app / "Contents/Frameworks/native.dylib"
    library.parent.mkdir()
    library.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 28)
    (app / "Contents/data.txt").write_text("regular data")

    def inspect(path):
        return {"architectures": ["arm64"], "minimum_macos": "11.0"}

    manifest = verify_bundle(app, inspector=inspect)
    assert manifest["verified_binary_count"] == 2
    assert manifest["architecture"] == "arm64"
    assert "M5" in manifest["target_families"]

    def wrong_arch(path):
        return {
            "architectures": ["x86_64"] if path == library else ["arm64"],
            "minimum_macos": "11.0",
        }

    with pytest.raises(ValueError, match="Missing arm64"):
        verify_bundle(app, inspector=wrong_arch)

    def wrong_os(path):
        return {"architectures": ["arm64"], "minimum_macos": "15.0" if path == library else "11.0"}

    with pytest.raises(ValueError, match="above the 14.0 baseline"):
        verify_bundle(app, inspector=wrong_os)


def test_entry_executable_cannot_accidentally_ship_universal_or_intel(tmp_path):
    app = bundle(tmp_path)
    with pytest.raises(ValueError, match="arm64 only"):
        verify_bundle(
            app, inspector=lambda _: {"architectures": ["arm64", "x86_64"], "minimum_macos": "11.0"}
        )
    java = tmp_path / "Example.class"
    java.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x3d")
    assert not is_macho(java)
