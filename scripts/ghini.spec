# vim:ft=python
# pylint: disable=undefined-variable,missing-module-docstring

from pathlib import Path

import pyproj

version = "1.3.16"  # :bump

# this returns CWD.  Call script from repo root.
root = Path().absolute()
bauble_root = root / 'bauble'

glade_files = [(f'{i}/*.glade', f'{i.relative_to(root)}') for i in
               set(j.parent for j in bauble_root.glob('**/*.glade'))]
glade_files += [(f'{i}/*.ui', f'{i.relative_to(root)}') for i in
                set(j.parent for j in bauble_root.glob('**/*.ui'))]

# prefs config files
configs = [(f'{i}/*.cfg', f'{i.relative_to(root)}') for i in
           set(j.parent for j in bauble_root.glob('**/*.cfg'))]

block_cipher = None

binaries: list[str] = []

a = Analysis(['ghini'],
             pathex=[root],
             binaries=binaries,
             datas=[
                 ('../LICENSE', 'share/ghini'),
                 ('../bauble/utils/prj_crs.csv', 'bauble/utils'),
                 ('../bauble/images/*', 'bauble/images'),
                 ('../bauble/plugins/plants/default/*.csv',
                  'bauble/plugins/plants/default'),
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
             ] + glade_files + configs,  # noqa
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
                 'pyproj',
                 'pyodbc',
             ],   # noqa
             hookspath=['./scripts/extra-hooks/'],
             hooksconfig={"gi": {
                 "icons": ["Adwaita"],
                 "themes": ["Adwaita"],
                 "languages": ["en_GB", "en_AU", "en_US"]
             }},
             runtime_hooks=['./scripts/extra-hooks/pyi_rth_gspell.py'],
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
             version=version,
             info_plist={
                 'NSPrincipalClass': 'NSApplication',
                 'NSAppleScriptEnabled': False,
             })
