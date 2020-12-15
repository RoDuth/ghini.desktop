::Copyright (c) 2020 Ross Demuth <rossdemuth123@gmail.com>
::
::This file is part of ghini.desktop.
::
::ghini.desktop is free software: you can redistribute it and/or modify
::it under the terms of the GNU General Public License as published by
::the Free Software Foundation, either version 3 of the License, or
::(at your option) any later version.
::
::ghini.desktop is distributed in the hope that it will be useful,
::but WITHOUT ANY WARRANTY; without even the implied warranty of
::MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
::GNU General Public License for more details.
::
::You should have received a copy of the GNU General Public License
::along with ghini.desktop. If not, see <http://www.gnu.org/licenses/>.
::
::Run this from within a powershell after installing NSIS and MSYS2

C:\msys64\usr\bin\bash -lc "pacman --noconfirm -Syuu"
C:\msys64\usr\bin\bash -lc "pacman --noconfirm -Syuu"

$env:CHERE_INVOKING = 1
$env:MSYSTEM = 'MINGW64'
C:\msys64\usr\bin\bash -lc "pacman --noconfirm -S - < ./scripts/mingw64_pkglist.txt"
C:\msys64\usr\bin\bash -lc "pip install ."
C:\msys64\usr\bin\bash -lc "pip install pyinstaller"
C:\msys64\usr\bin\bash -lc "python -m PyInstaller --clean -w --noconfirm ghini.spec"

$env:PATH += ";C:\Program Files (x86)\NSIS\Bin"
makensis scripts\build-multiuser.nsi

