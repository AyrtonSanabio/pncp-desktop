from PyInstaller.utils.hooks import collect_submodules


hiddenimports = collect_submodules("pncp_sync") + collect_submodules("pypncp")

a = Analysis(
    ["src/pncp_desktop/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ConsultaPNCP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX pode corromper DLLs do Qt em algumas combinações de Python/PySide6.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
