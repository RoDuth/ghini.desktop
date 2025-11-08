import glob
import os

from PyInstaller.utils.hooks.gi import GiModuleInfo

module_info = GiModuleInfo("Gspell", "1")
binaries, datas, hiddenimports = module_info.collect_typelib_data()

root = os.path.dirname(module_info.get_libdir())

# Collect enchant providers (e.g. libenchant_aspell.dll)
enchant_plugin_dir = os.path.join(
    root,
    "lib",
    "enchant-2/",
)
for f in glob.glob(os.path.join(enchant_plugin_dir, "*.*")):
    binaries.append((f, "lib/enchant-2"))

# Collect config files
enchant_configs = os.path.join(
    root,
    "share",
    "enchant-2",
)
for f in glob.glob(os.path.join(enchant_configs, "*.*")):
    datas.append((f, "share/enchant-2"))

# Collect aspell dictionaries
aspell_data_path = os.path.join(root, "lib", "aspell-0.60")
for f in glob.glob(os.path.join(aspell_data_path, "*.*")):
    datas.append((f, "lib/aspell-0.60"))
