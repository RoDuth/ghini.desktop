import glob
import os

from PyInstaller.utils.hooks.gi import GiModuleInfo

module_info = GiModuleInfo("Gspell", "1")
if module_info.available:
    binaries, datas, hiddenimports = module_info.collect_typelib_data()

    msystem_prefix = os.environ.get("MSYSTEM_PREFIX")
    if msystem_prefix:
        # Collect enchant providers (e.g. libenchant_aspell.dll) Enchant on
        # windows will look for providers in ../lib/enchant-2 relative to the
        # enchant library. Pyinstaller puts libs in the root of the bundle. So
        # we will need to move them manually later for this to work.
        # enchant_set_prefix_dir() is not working in the current mingw version.
        enchant_plugin_dir = os.path.join(msystem_prefix, "lib", "enchant-2")
        for f in glob.glob(os.path.join(enchant_plugin_dir, "*.dll")):
            binaries.append((f, "lib/enchant-2"))

        # collect the enchant.ordering file and place it within the plugin dir
        # Requires a runtime hook to set ENCHANT_CONFIG_DIR environment
        # variable
        enchant_ordering = os.path.join(
            msystem_prefix,
            "share",
            "enchant-2",
            "enchant.ordering",
        )
        if os.path.isfile(enchant_ordering):
            datas.append((enchant_ordering, "share/enchant-2"))

        # Collect aspell dictionaries
        aspell_data_path = os.path.join(msystem_prefix, "lib", "aspell-0.60")
        for f in glob.glob(os.path.join(aspell_data_path, "*.*")):
            datas.append((f, "lib/aspell-0.60"))
    else:
        # Collect enchant providers
        enchant_plugin_dir = os.path.join(
            module_info.get_libdir(),
            "enchant-2/",
        )
        for f in glob.glob(os.path.join(enchant_plugin_dir, "*.*")):
            binaries.append((f, "lib/enchant-2"))

        # Collect config files
        enchant_configs = os.path.join(
            module_info.get_libdir(),
            "..",
            "share",
            "enchant-2",
        )
        for f in glob.glob(os.path.join(enchant_configs, "*.*")):
            datas.append((f, "share/enchant-2"))

        # Collect aspell dictionaries
        aspell_data_path = os.path.join(
            module_info.get_libdir(), "aspell-0.60"
        )
        for f in glob.glob(os.path.join(aspell_data_path, "*.*")):
            datas.append((f, "lib/aspell-0.60"))
