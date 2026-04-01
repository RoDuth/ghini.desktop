# vim:ft=python
# pylint: disable=undefined-variable,missing-module-docstring
from pathlib import Path

import pyproj
from PyInstaller.building.api import COLLECT
from PyInstaller.building.api import EXE
from PyInstaller.building.api import PYZ
from PyInstaller.building.build_main import Analysis

version = "1.3.16"  # :bump

# this returns CWD.  Call script from repo root.
root = Path().absolute()
bauble_root = root / "bauble"

block_cipher = None

binaries: list[tuple[str, str]] = []

datas = [
    ("../LICENSE", "share/ghini"),
    ("../bauble/utils/prj_crs.csv", "bauble/utils"),
    ("../bauble/images/*", "bauble/images"),
    (
        "../bauble/plugins/plants/default/*.csv",
        "bauble/plugins/plants/default",
    ),
    ("../bauble/plugins/plants/ui/*.kml", "bauble/plugins/plants/ui/"),
    ("../bauble/plugins/garden/*.kml", "bauble/plugins/garden/"),
    ("../bauble/plugins/abcd/abcd_2.06.xsd", "bauble/plugins/abcd"),
    (
        "../bauble/plugins/report/mako/templates/*",
        "bauble/plugins/report/mako/templates/",
    ),
    (
        "../bauble/plugins/report/xsl/stylesheets",
        "bauble/plugins/report/xsl/stylesheets",
    ),
    (pyproj.datadir.get_data_dir(), "share/proj"),
]

# glade files
for i in set(j.parent for j in bauble_root.glob("**/*.glade")):
    datas.append((f"{i}/*.glade", f"{i.relative_to(root)}"))

for i in set(j.parent for j in bauble_root.glob("**/*.ui")):
    datas.append((f"{i}/*.ui", f"{i.relative_to(root)}"))

# prefs config files
for i in set(j.parent for j in bauble_root.glob("**/*.cfg")):
    datas.append((f"{i}/*.cfg", f"{i.relative_to(root)}"))

hiddenimports = [
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "bauble.plugins.abcd",
    "bauble.plugins.report",
    "bauble.plugins.report.xsl",
    "bauble.plugins.report.mako",
    "bauble.plugins.tag",
    "bauble.plugins.users",
    "bauble.plugins.synclone",
    "psycopg2",
    "sysconfig._get_sysconfigdata_name()",
    "_sysconfigdata__win32_",
    "shapefile",
    "pyproj",
    "pyodbc",
]

a = Analysis(
    ["ghini"],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["./scripts/extra-hooks/"],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "languages": ["en_GB", "en_AU", "en_US"],
        }
    },
    runtime_hooks=["./scripts/extra-hooks/pyi_rth_gspell.py"],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ghini",
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=bauble_root / "images/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ghini",
)
app = BUNDLE(  # type: ignore [name-defined]
    coll,
    name="Ghini.app",
    icon="../bauble/images/icon.ico",
    bundle_identifier=None,
    version=version,
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSAppleScriptEnabled": False,
    },
)
