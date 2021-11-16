# vim:ft=python
# pylint: disable=undefined-variable,missing-module-docstring

from pathlib import Path
from tld.defaults import NAMES_LOCAL_PATH_PARENT
import pyproj
import bauble


root = Path(bauble.__file__).parent.parent

glade_files = [(f'{i}/*.glade', f'{i.relative_to(root)}') for i in
               set(i.parent for i in root.glob('**/*.glade'))]
glade_files += [(f'{i}/*.ui', f'{i.relative_to(root)}') for i in
                set(i.parent for i in root.glob('**/*.ui'))]

# effective_tld_names.dat.txt from tld
tld_names = [(str(Path(NAMES_LOCAL_PATH_PARENT, 'res', '*.txt')),
              'tld/res')]

block_cipher = None

a = Analysis(['ghini'],
             pathex=[root],
             binaries=[],
             datas=[
                 ('../LICENSE', 'share/ghini'),
                 ('../bauble/utils/prj_crs.db', 'bauble/utils'),
                 ('../bauble/images/*', 'bauble/images'),
                 ('../bauble/plugins/plants/default/*.csv',
                  'bauble/plugins/plants/default'),
                 ('../bauble/plugins/plants/default/wgsrpd/*.geojson',
                  'bauble/plugins/plants/default/wgsrpd/'),
                 ('../bauble/plugins/abcd/abcd_2.06.xsd',
                  'bauble/plugins/abcd'),
                 ('../bauble/plugins/report/mako/templates/*',
                  'bauble/plugins/report/mako/templates'),
                 ('../bauble/plugins/report/xsl/stylesheets',
                  'bauble/plugins/report/xsl/stylesheets'),
                 (pyproj.datadir.get_data_dir(), 'share/proj')
             ] + glade_files + tld_names,  # noqa
             hiddenimports=['sqlalchemy.dialects.sqlite',
                            'sqlalchemy.dialects.postgresql',
                            'bauble.plugins.abcd',
                            'bauble.plugins.report',
                            'bauble.plugins.report.xsl',
                            'bauble.plugins.report.mako',
                            'bauble.plugins.tag',
                            'bauble.plugins.users',
                            'xmlrpc.server.SimpleXMLRPCServer',
                            'xmlrpc.server.SimpleXMLRPCRequestHandler',
                            'psycopg2',
                            'sysconfig._get_sysconfigdata_name()',
                            '_sysconfigdata__win32_',
                            'shapefile',
                            'polylabel',
                            'pyproj',
                            ],
             hookspath=[],
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
          icon='../bauble/images/icon.ico')
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
