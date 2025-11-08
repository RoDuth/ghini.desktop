import ctypes
import os
import sys

# For gspell, we need to tell enchant where to find its enchant.ordering file
# NOTE we have to move lib/enchant-2 to beside _internal for the providers to
# be discovered (libenchant looks relative to its current position i.e.
# ../lib/enchant-2/)
lib_name = "libenchant-2.so.2"
if sys.platform == "win32":
    lib_name = "libenchant-2-2.dll"
elif sys.platform == "darwin":
    lib_name = "libenchant-2.2.dylib"

# relocate enchant
enchant_lib_path = os.path.join(sys._MEIPASS, lib_name)
enchant_lib = ctypes.cdll.LoadLibrary(enchant_lib_path)
enchant_lib.enchant_set_prefix_dir(sys._MEIPASS.encode())
