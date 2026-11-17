# PyInstaller spec for PokePilot Desktop.  Build with:  pyinstaller --noconfirm --clean pokepilot.spec
# Produces a one-folder build in dist/PokePilot/ (faster start-up and fewer antivirus false positives
# than --onefile).
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
ICON = str(ROOT / "assets" / "icons" / ("app.ico" if sys.platform == "win32" else "app.png"))

a = Analysis(
    [str(ROOT / "pokepilot.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Unused Qt modules: keeps the build smaller.
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning",
        "pytest", "pytestqt",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PokePilot",
    console=False,  # GUI application: no console window
    icon=ICON,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PokePilot")
