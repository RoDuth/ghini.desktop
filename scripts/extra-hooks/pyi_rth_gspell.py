import ctypes
import os
import sys

# For gspell, we need to tell enchant where to find its enchant.ordering file
# NOTE we have to move lib/enchant-2 to beside _internal for the providers to
# be discovered (libenchant looks relative to its current position i.e.
# ../lib/enchant-2/)
if sys.platform == "win32":
    config_dir = os.path.join(
        os.path.dirname(sys._MEIPASS),
        "share",
        "enchant-2",
    )
    os.environ["ENCHANT_CONFIG_DIR"] = config_dir
else:
    # relocate
    enchant_lib_path = os.path.join(sys._MEIPASS, "libenchant-2.2.dylib")
    enchant_lib = ctypes.cdll.LoadLibrary(enchant_lib_path)
    enchant_lib.enchant_set_prefix_dir(sys._MEIPASS.encode())
