# vim:ft=python
# pylint: disable=undefined-variable,missing-module-docstring
# -*- mode: python ; coding: utf-8 -*-

import os

glade_files = []
for root, _, files in os.walk('bauble'):
    if any(i.endswith('.glade') for i in files):
        glade_files.append((root + '/*.glade', root))
    if any(i.endswith('.ui') for i in files):
        glade_files.append((root + '/*.ui', root))

# effective_tld_names.dat.txt from tld
from tld.defaults import NAMES_LOCAL_PATH_PARENT
tld_names = [(os.path.join(NAMES_LOCAL_PATH_PARENT, 'res', '*.txt'),
             'tld/res')]

block_cipher = None


a = Analysis(['scripts/ghini'],
             pathex=['C:/msys64/home/rodem/ghini.desktop'],
             binaries=[],
             datas=[
                 ('LICENSE', 'share/ghini'),
                 ('bauble/utils/prj_crs.db', 'bauble/utils'),
                 ('bauble/images/*', 'bauble/images'),
                 ('bauble/plugins/plants/default/*.txt',
                  'bauble/plugins/plants/default'),
                 ('bauble/plugins/plants/default/wgsrpd/*.geojson',
                  'bauble/plugins/plants/default/wgsrpd/'),
                 ('bauble/plugins/abcd/abcd_2.06.xsd',
                  'bauble/plugins/abcd'),
                 ('bauble/plugins/report/mako/templates/*',
                  'bauble/plugins/report/mako/templates'),
                 ('bauble/plugins/report/xsl/stylesheets',
                  'bauble/plugins/report/xsl/stylesheets'),
                 ('C:/msys64/mingw64/share/proj', 'share/proj')
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
                            'pydoc',
                            'psycopg2',
                            'sysconfig._get_sysconfigdata_name()',
                            '_sysconfigdata__win32_',
                            'shapefile',
                            'polylabel',
                            'pyproj',
                            ],
             hookspath=[],
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
          [],
          exclude_binaries=True,
          name='ghini',
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          icon='bauble/images/icon.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='ghini')
