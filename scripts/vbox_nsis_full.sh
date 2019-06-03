#!/usr/bin/env bash
# shellcheck disable=SC1001

# prep:
#   from a base install generate a vbox_req.txt:
#     pip freeze > vbox_req.txt
#     edit as required for each branch (e.g. no pygtk is needed as it is
#     installed via this script.)
# manual steps:
#   install virtualbox and Extension Pack
#   for testing you may download a `IE8 - Win7.ova` vm image from MS to the
#   downloads folder of the host computer and this script will attempt to set
#   it up for you.
#   Otherwise create a VM install win7 into it and take a snapshot
#   Usage:
#     scripts/vbox_nsis_full.sh VIRTUALMACHINE SNAPSHOT USERNAME PASSWORD:
#     after the first run (when a snapshot for the branch has been made)
#     SNAPSHOT can be any random text (e.g. x) as it will not be used if there
#     is a snapshot with the same name as the current branch
#
# Assumes sharedfolder is E: drive in VM

[[ $# -eq 4 ]] || {
  echo "usage: $0 VIRTUALMACHINE SNAPSHOT USERNAME PASSWORD" \
  && exit 1
  }

vm=$1
snapshot=$2
username=$3
p_word=$4
branch=$(git rev-parse --abbrev-ref HEAD)
win_path="C:\\Python27\\;C:\\Python27\\Scripts;%PATH%"


# check if the command line is available
_cmdexe_available() {
  echo "waiting for cmd.exe to become available"
  local error="not ready"
  local wait_time=0
  while [ -n "$error" ] ; do
    error=$(VBoxManage guestcontrol "$vm" run \
              --exe cmd.exe \
              --username "$username" \
              --password  "$p_word" \
              --wait-stdout \
              --wait-stderr \
              -- cmd.exe/arg0 /C "echo %PATH%" \
              2>&1 | grep "not ready")
    echo -n "..$wait_time"
    wait_time=$((wait_time+5))
    sleep 5
  done
	echo
  echo "cmd.exe available, waiting a few more seconds to be certain"
  sleep 3
}
# if the provided vm doesn't exist create it. (requires having downloaded one
# of the test win7 vm images)
VBoxManage list vms | grep ^\""$vm"\" >/dev/null 2>&1 || {
  # create the vm
  msg="
  importing virtual machine failed.  You require an image named
  'IE8 - Win7.ova' in your 'Downloads' directory. For testing only, free images
  are avaiable from Microsoft at:
  https://developer.microsoft.com/en-us/microsoft-edge/tools/vms/"
  echo "virtual machine $vm not found attempting to make it"
  VBoxManage import ~/Downloads/IE8\ -\ Win7.ova \
    --vsys 0 \
    --vmname "$vm" \
    --memory 4096 || {
    echo "$msg"  && exit 1
  }

  echo "disable network and add this directory as a shared folder"
  VBoxManage modifyvm "$vm" --nic1 none

  VBoxManage sharedfolder add "$vm" \
    --name ghini.desktop \
    --hostpath "$(pwd)" \
    --automount

  # start the VM headless
  VBoxManage startvm "$vm" --type headless || {
    echo "unable to start the $vm" && exit 1
  }

  # wait for cmd.exe to become available
  _cmdexe_available

  echo "take snapshot $vm"
  VBoxManage snapshot "$vm" take "$snapshot" >/dev/null 2>&1 || {
    echo "failed to take snapshot $branch" && exit 1
  }
}

# ensure the VM is off first...
VBoxManage list runningvms | grep "$vm" >/dev/null 2>&1 && \
  VBoxManage controlvm "$vm" poweroff

# restore the branch snapshot if its available, if not create it from the
# provided snapshot
echo "attempting to restore snapshot $branch"
VBoxManage snapshot "$vm" restore "$branch" >/dev/null 2>&1 || {
  echo "no $branch snapshot yet -- try making it from $snapshot"

  VBoxManage snapshot "$vm" restore "$snapshot" || {
    echo "unable to restore the snapshot provided: $snapshot" && exit 1
  }

  # start the VM headless
  VBoxManage startvm "$vm" --type headless || {
    echo "unable to start the $vm" && exit 1
  }

  # wait for cmd.exe to become available
  _cmdexe_available

  # download and install msi dependencies
  py27=https://www.python.org/ftp/python/2.7.15/python-2.7.15.msi
  pygtk=https://ftp.gnome.org/pub/GNOME/binaries/win32/pygtk/2.24
  pygtk+=/pygtk-all-in-one-2.24.2.win32-py2.7.msi
  installers=("$py27" "$pygtk")

  for i in "${installers[@]}"; do
    [ -f win_installers/"${i##*/}" ] || wget -P win_installers "$i"
    msi="E:\\win_installers\\${i##*/}"
    # msi+="TARGETDIR=C:\\Python27 ADDLOCAL=ALL ALLUSERS=\"\""
    echo "installing ${i##*/} from $msi"
    VBoxManage guestcontrol "$vm" run \
      --exe msiexec.exe \
      --username "$username" \
      --password  "$p_word" \
      --wait-stdout \
      --wait-stderr \
      -- msiexec.exe/arg0 /i "$msi" /qn /norestart TARGETDIR\=C:\\Python27 \
      ADDLOCAL\=ALL || {
        echo "failed to install ${i##*/}" && exit 1
      }
  done

  # download and unzip nsis
  # (can't find a way to get the installer to work silently and unattended)
  nsis=https://sourceforge.net/projects/nsis/files/NSIS%203/3.03/nsis-3.03.zip
  [ -f win_installers/"${nsis##*/}" ] || \
    wget -P win_installers --no-check-certificate "$nsis"
  echo "extracting ${nsis##*/}"
  [ -d win_installers/NSIS ] || \
    unzip win_installers/"${nsis##*/}" -d win_installers/NSIS || {
      echo "failed to download and extract nsis" && exit 1
    }

  # make array of pip packages required from vbox_req.txt.
  # shellcheck disable=SC2016
  IFS=$'\r\n' GLOBIGNORE='*' command eval  'pip_deps=($(cat scripts/vbox_req.txt))'
  # vbox_req.txt is a requirements.txt with anything not required removed,
  # i.e. PyGTK all-in-one installer provides: pycairo pygobject pygoocanvas
  # pygtk pygtksourceview. e.g.:
  # `pip freeze | grep -v -E \
  #   'ghini.desktop|pycairo|pygobject|pygoocanvas|pygtk|pygtksourceview' > \
  #   vbox_req.txt`

  # download and install pip dependencies
  # shellcheck disable=SC2154
  for dep in "${pip_deps[@]}"; do
    echo "try win_32 binary"
    pip2 download "$dep" \
      --no-deps \
      --only-binary=:all: \
      --platform=win_32 \
      --dest win_pip_pkgs \
      || \
    echo "try win32 binary"
    pip2 download "$dep" \
      --no-deps \
      --only-binary=:all: \
      --platform=win32 \
      --dest win_pip_pkgs \
      || \
    echo "try any win_32"
    pip2 download "$dep" \
      --no-deps \
      --platform=win_32 \
      --dest win_pip_pkgs \
      || \
    echo "try any win32"
    pip2 download "$dep" \
      --no-deps \
      --platform=win32 \
      --dest win_pip_pkgs \
      || { echo "failed to grab pip package $dep" && exit 1 ; }
  done

  # install a few requirements
  echo "installing dependencies"
  pip_inst=(install py2exe_py2 psycopg2 Pygments --no-index
            --find-links file://E:/win_pip_pkgs)
  VBoxManage guestcontrol "$vm" run \
    --exe C:\\Python27\\Scripts\\pip.exe \
    --username "$username" \
    --password  "$p_word" \
    --wait-stdout \
    --wait-stderr \
    -- pip.exe/arg0 "${pip_inst[@]}" || {
      echo "failed to install python dependencies" && exit 1
    }

  # take a snapshot if build succeeds
  VBoxManage snapshot "$vm" take "$branch" >/dev/null 2>&1 || {
    echo "failed to take snapshot $branch" && exit 1
  }
}

# if vm not running already (skipped setup steps above) start it.
VBoxManage list runningvms | grep "$vm" >/dev/null 2>&1 || \
  VBoxManage startvm "$vm" --type headless

cmd="set PATH=$win_path && e: && pip install . --no-index "
cmd+=" --find-links file://E:/win_pip_pkgs"
echo "$cmd"
VBoxManage guestcontrol "$vm" run \
  --exe cmd.exe \
  --username "$username" \
  --password  "$p_word" \
  --wait-stdout \
  --wait-stderr \
  -- cmd.exe/arg0 /C "$cmd"

steps=(clean py2exe)
for i in "${steps[@]}"; do
  cmd="set PATH=$win_path && e: && python setup.py $i"
  VBoxManage guestcontrol "$vm" run \
    --exe cmd.exe \
    --username "$username" \
    --password  "$p_word" \
    --wait-stdout \
    --wait-stderr \
    -- cmd.exe/arg0 /C "$cmd"
done

cmd="E:\\win_installers\\NSIS\\nsis-3.03\\makensis.exe "
cmd+="E:\\scripts\\build-multiuser.nsi"
echo "$cmd"
VBoxManage guestcontrol "$vm" run \
  --exe cmd.exe \
  --username "$username" \
  --password  "$p_word" \
  --wait-stdout \
  --wait-stderr \
  -- cmd.exe/arg0 /C "$cmd"
# power off after all is finished.
VBoxManage controlvm "$vm" poweroff
