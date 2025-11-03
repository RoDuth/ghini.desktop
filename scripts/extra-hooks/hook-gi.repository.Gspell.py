from PyInstaller.utils.hooks.gi import GiModuleInfo

module_info = GiModuleInfo("Gspell", "1")
if module_info.available:
    binaries, datas, hiddenimports = module_info.collect_typelib_data()
