#!/usr/bin/env bash

# NOTE should work on a physical machine but not in CI as needs to applescript
# finder.
# skip-jenkins should get it to work in CI but results are very minimal
#   --skip-jenkins \

version=$(python -c 'import bauble; print(bauble.version)')
instlr_name="dist/Ghini-$version-installer.dmg"

[[ -f "$instlr_name" ]] && rm "$instlr_name"

create-dmg \
  --volname "Ghini v$version installer" \
  --background "bauble/images/dmg_background.png" \
  --window-pos 200 120 \
  --window-size 640 400 \
  --icon-size 128 \
  --icon "Ghini.app" 140 120 \
  --hide-extension "Ghini.app" \
  --app-drop-link 500 120 \
  --eula LICENSE \
  "$instlr_name" \
  "dist/Ghini.app"
