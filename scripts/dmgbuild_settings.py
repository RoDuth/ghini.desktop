# -*- coding: utf-8 -*-
# pylint: disable=missing-module-docstring,redefined-builtin
from pathlib import Path

version = "1.3.13"  # :bump

# Usage:
# dmgbuild -s scripts/dmg_create.py "", X

application = "./dist/Ghini.app"
appname = Path(application).name

# overide output file
filename = f"dist/Ghini-v{version}-installer.dmg"

# override the output volume name
volume_name = f"Ghini v{version} installer"

# Volume format
format = "UDBZ"

# Files to include
files = [application]

# Symlinks to create
symlinks = {"Applications": "/Applications"}

icon = "bauble/images/icon.ico"

# spacing
icon_locations = {appname: (140, 120), "Applications": (500, 120)}

# background image
background = "./bauble/images/dmg_background.png"

# Window position
window_rect = ((100, 100), (640, 360))

default_view = "icon-view"

# General view configuration
include_icon_view_settings = "auto"
include_list_view_settings = "auto"

# Icon view configuration
arrange_by = None
grid_offset = (0, 0)
grid_spacing = 90
scroll_position = (0, 0)
label_pos = "bottom"  # or 'right'
text_size = 16
icon_size = 128

# License
license = {
    "default-language": "en_US",
    "licenses": {"en_US": "./LICENSE"},
    "buttons": {
        "en_US": (
            b"English",
            b"Agree",
            b"Disagree",
            b"Print",
            b"Save",
            b'If you agree with the terms of this license, press "Agree" to '
            b'install the software.  If you do not agree, press "Disagree".',
        )
    },
}
