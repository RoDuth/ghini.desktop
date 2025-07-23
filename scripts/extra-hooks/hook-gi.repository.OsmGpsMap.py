from PyInstaller.utils.hooks.gi import GiModuleInfo

module_info = GiModuleInfo("OsmGpsMap", "1.0")
if module_info.available:
    binaries, datas, hiddenimports = module_info.collect_typelib_data()
