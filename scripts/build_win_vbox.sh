#!/usr/bin/env bash

# script to build windows installer in a VM from within a linux host.  (Output
# goes to host terminal)
# Developed against VirtualBox 5.2.8
# To use:
#   Install VirtualBox and Extension Pack
#   set up a windows VM (windows 7 or above)
#     recommended setting minimum base memory of 4096mb
#     set a shared folder
#       clone ghini.desktop in the shared folder
#       within the host, checkout the branch you wish to build against
#   in the windows VM install: NSIS v3, Python, PyGTK
#   run build_win.bat once:
#     e:
#     cd ghini.desktop
#     scripts\build_win.bat
#   take a snapshot and give it a simple name
#   from within the linux host run this script with arguments as below:
#     build_win_vbox <VM_name> <snapshot> <username> <password>
[[ $# -eq 4 ]] || {
  echo "usage: $0 VIRTUALMACHINE SNAPSHOT USERNAME PASSWORD" \
  && exit 1
  }

vm=$1
snapshot=$2
username=$3
p_word=$4

batch_file=e:\\ghini.desktop\\scripts\\build_win.bat
# branch=$(git rev-parse --abbrev-ref HEAD)
# venv="%HOMEDRIVE%%HOMEPATH%\\.virtualenvs\\$branch-2exe"

# ensure the VM is off first...
VBoxManage list runningvms | grep "$vm" >/dev/null 2>&1 && \
  VBoxManage controlvm "$vm" poweroff

# resore the snapshot
VBoxManage snapshot "$vm" restore "$snapshot"

# start the VM headless
VBoxManage startvm "$vm" --type headless

# run the build script
VBoxManage guestcontrol "$vm" run \
  --exe cmd.exe \
  --username "$username" \
  --password  "$p_word" \
  --wait-stdout \
  --wait-stderr \
  -- cmd.exe/arg0 /C "e: && cd ghini.desktop && $batch_file"
  # -- cmd.exe/arg0 /C "e: && cd ghini.desktop && $batch_file $venv"

# power off after all is finished.
VBoxManage controlvm "$vm" poweroff

# NOTE
# run the script without arguments (can take a while to complete)
# VBoxManage guestcontrol "$vm" run
#   --exe "$batch_file" \
#   --username "$username" \
#   --password  "$p_word" \
#   --wait-stdout \
#   --wait-stderr \
# run the script with arguments
# VBoxManage guestcontrol "$vm" run \
#   --exe "$batch_file" \
#   --username "$username" \
#   --password  "$p_word" \
#   --wait-stdout \
#   --wait-stderr \
#   -- build_win.bat/arg0 "$branch"
