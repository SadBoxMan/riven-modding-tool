# PyInstaller spec for RivenModTool — single-file Windows executable, NO bundled ffmpeg.
#
# Use this variant when the target machine already has ffmpeg on PATH
# (e.g. installed via winget, chocolatey, or another tool).
# The exe is ~10x smaller and works identically as long as ffmpeg is available.
#
# Build:
#   cd "C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
#   python -m PyInstaller RivenModTool-noffmpeg.spec
#
# The resulting RivenModTool.exe goes in dist\.

block_cipher = None

a = Analysis(
    ['riven_gui.py'],
    pathex=[],
    binaries=[],   # no bundled ffmpeg — must be on PATH
    datas=[
        ('cursors/*.cur', 'cursors'),
        ('cursors/*.ani', 'cursors'),
        ('realmyst.ico', '.'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'riven_img',
        'riven_snd',
        'riven_layers',
        'riven_help',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RivenModTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='realmyst.ico',
)
