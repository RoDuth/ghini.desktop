# vim:ft=python
# pylint: disable=undefined-variable,missing-module-docstring

import sysconfig
from pathlib import Path

import pyproj
from tld.defaults import NAMES_LOCAL_PATH_PARENT

import bauble

# this returns CWD.  Call script from repo root.
root = Path().absolute()
bauble_root = root / 'bauble'

glade_files = [(f'{i}/*.glade', f'{i.relative_to(root)}') for i in
               set(j.parent for j in bauble_root.glob('**/*.glade'))]
glade_files += [(f'{i}/*.ui', f'{i.relative_to(root)}') for i in
                set(j.parent for j in bauble_root.glob('**/*.ui'))]

# effective_tld_names.dat.txt from tld
tld_names = [(str(Path(NAMES_LOCAL_PATH_PARENT, 'res', '*.txt')),
              'tld/res')]

# prefs config files
configs = [(f'{i}/*.cfg', f'{i.relative_to(root)}') for i in
           set(j.parent for j in bauble_root.glob('**/*.cfg'))]

block_cipher = None

binaries = []
gio_modules = []

if 'mingw' in sysconfig.get_platform():
    binaries = [
        ('C:/msys64/mingw64/lib/gio/modules/libgiognomeproxy.dll',
         'lib/gio/modules'),
        ('C:/msys64/mingw64/lib/gio/modules/libgiolibproxy.dll',
         'lib/gio/modules'),
        ('C:/msys64/mingw64/lib/gio/modules/libgiognutls.dll',
         'lib/gio/modules'),
        ('C:/msys64/mingw64/lib/gio/modules/libgioopenssl.dll',
         'lib/gio/modules'),
        ('C:/msys64/mingw64/bin/libgnutls-30.dll', '.'),
        ('C:/msys64/mingw64/bin/libintl-8.dll', '.'),
        ('C:/msys64/mingw64/bin/libproxy-1.dll', '.'),
    ]
    gio_modules = [
        ('C:/msys64/mingw64/lib/gio/modules/giomodule.cache',
         'lib/gio/modules'),
    ]

a = Analysis(['ghini'],
             pathex=[root],
             binaries=binaries,
             datas=[
                 ('../LICENSE', 'share/ghini'),
                 ('../bauble/utils/prj_crs.csv', 'bauble/utils'),
                 ('../bauble/images/*', 'bauble/images'),
                 ('../bauble/plugins/plants/default/*.csv',
                  'bauble/plugins/plants/default'),
                 ('../bauble/plugins/plants/default/wgsrpd/*.geojson',
                  'bauble/plugins/plants/default/wgsrpd/'),
                 ('../bauble/plugins/plants/*.kml',
                  'bauble/plugins/plants/'),
                 ('../bauble/plugins/garden/*.kml',
                  'bauble/plugins/garden/'),
                 ('../bauble/plugins/abcd/abcd_2.06.xsd',
                  'bauble/plugins/abcd'),
                 ('../bauble/plugins/report/mako/templates/*',
                  'bauble/plugins/report/mako/templates'),
                 ('../bauble/plugins/report/xsl/stylesheets',
                  'bauble/plugins/report/xsl/stylesheets'),
                 (pyproj.datadir.get_data_dir(), 'share/proj'),
             ] + glade_files + tld_names + configs + gio_modules,  # noqa
             hiddenimports=[
                 'sqlalchemy.dialects.sqlite',
                 'sqlalchemy.dialects.postgresql',
                 'bauble.plugins.abcd',
                 'bauble.plugins.report',
                 'bauble.plugins.report.xsl',
                 'bauble.plugins.report.mako',
                 'bauble.plugins.tag',
                 'bauble.plugins.users',
                 'bauble.plugins.synclone',
                 'psycopg2',
                 'sysconfig._get_sysconfigdata_name()',
                 '_sysconfigdata__win32_',
                 'shapefile',
                 'polylabel',
                 'pyproj',
                 'pyodbc',
             ],   # noqa
             hookspath=['./scripts/extra-hooks/'],
             hooksconfig={"gi": {
                 "icons": ["Adwaita"],
                 "themes": ["Adwaita"],
                 "languages": ["en_GB", "en_AU", "en_US"]
             }},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=True)
pyz = PYZ(a.pure, a.zipped_data,
          cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='ghini',
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          # icon='../bauble/images/icon.ico')
          # NOTE fix for:
          # https://github.com/pyinstaller/pyinstaller/issues/6759
          icon=str(bauble_root / 'images/icon.ico'))
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='ghini')
app = BUNDLE(coll,
             name='Ghini.app',
             icon='../bauble/images/icon.ico',
             bundle_identifier=None,
             version=bauble.version,
             info_plist={
                 'NSPrincipalClass': 'NSApplication',
                 'NSAppleScriptEnabled': False,
             })
