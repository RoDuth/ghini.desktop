import os
import sys

# For gspell, we need to tell enchant where to find its enchant.ordering file
# NOTE we have to move lib/enchant-2 to beside _internal for the providers to
# be discovered (libenchant looks relative to its current position i.e.
# ../lib/enchant-2/)
if sys.platform == "win32":
    providers_dir = os.path.join(
        os.path.dirname(sys._MEIPASS),
        "lib",
        "enchant-2",
    )
    os.environ["ENCHANT_CONFIG_DIR"] = providers_dir
