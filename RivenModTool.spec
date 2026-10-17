# PyInstaller spec for RivenModTool — single-file Windows executable.
#
# Build:
#   cd "C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
#   python -m PyInstaller RivenModTool.spec
#
# The resulting RivenModTool.exe goes in dist\.
# Place it inside your Riven game folder (next to a_data.mhk), or run it from
# anywhere and it will ask you to choose the game folder on first launch.

block_cipher = None

_FFMPEG = r'C:\Users\lukea\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe'

a = Analysis(
    ['riven_gui.py'],
    pathex=[],
    binaries=[
        (_FFMPEG, '.'),   # bundled as ffmpeg.exe at the root of the package
    ],
    datas=[
        # Cursor set — bundled so the custom cursor works without the game folder
        ('cursors/*.cur', 'cursors'),
        ('cursors/*.ani', 'cursors'),
        # App icon
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
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='realmyst.ico',    # taskbar + Explorer icon
)
