from PyInstaller.utils.hooks.gi import get_gi_typelibs

binaries, datas, hiddenimports = get_gi_typelibs("Soup", "2.4")
