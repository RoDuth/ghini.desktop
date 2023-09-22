; Copyright (c) 2016-2021 Ross Demuth <rossdemuth123@gmail.com>
;
; This file is part of ghini.desktop.
;
; ghini.desktop is free software: you can redistribute it and/or modify
; it under the terms of the GNU General Public License as published by
; the Free Software Foundation, either version 3 of the License, or
; (at your option) any later version.
;
; ghini.desktop is distributed in the hope that it will be useful,
; but WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
; GNU General Public License for more details.
;
; You should have received a copy of the GNU General Public License
; along with ghini.desktop. If not, see <http://www.gnu.org/licenses/>.

;
; NSIS Install Script for Ghini
;

; Command line options:
;
; /AllUsers or /CurrentUser
; /S        Silent install
; /D=PATH   Set $INSTDIR
;

;---
; Generate a unicode installer, best set first
Unicode true

;---
; Plugins, required to compile: (included in data\nsis)
; -
; nsExec (included in NSIS v3.0) for executing commands
; WordFunc.nsh (included in NSIS v3.0) for comparing versions
; FileFunc.nsh (included in NSIS v3.0) for command line options
; MUI2 (included in NSIS v3.0)
; UAC (included in NsisMultiUser)
; NsisMultiUser (https://github.com/Drizin/NsisMultiUser)
;---
!addplugindir /x86-unicode "..\nsis\Plugins\x86-unicode\"
!addincludedir "..\nsis\Include\"


;------------------------------
;  GENERAL

; Global
Name "ghini.desktop"
!define VERSION "1.3.5" ; :bump
!define SRC_DIR "..\dist\ghini"
!define PRODUCT_NAME "ghini.desktop"
Outfile "..\dist\${PRODUCT_NAME}-${VERSION}-setup.exe"
!define PROGEXE "ghini.exe"
; !define COMPANY_NAME ""  ; no longer required
!define LICENSE_FILE "LICENSE"
!define README "README.rst"
!define START_MENU "$SMPROGRAMS\${PRODUCT_NAME}"
; !define UNINSTALL_FILENAME "uninstall.exe"  ; is default value


;------------------------------
;  COMPRESSION SETTINGS

; Compression
SetCompressor /FINAL /SOLID lzma
; default is 8mb, setting to 64mb reduced installer size by 1+mb
SetCompressorDictSize 64

; Other
SetDateSave on
SetDatablockOptimize on
CRCCheck on


;------------------------------
;  SETTINGS

; Multi User Settings (must come before the NsisMultiUser script)
!define MULTIUSER_INSTALLMODE_DEFAULT_ALLUSERS 1

; Modern User Interface v2 Settings
!define MUI_ABORTWARNING
!define MUI_UNABORTWARNING
!define MUI_ICON "${SRC_DIR}\bauble\images\icon.ico"
!define MUI_UNICON "${SRC_DIR}\bauble\images\icon.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${SRC_DIR}\bauble\images\ghini_logo.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${SRC_DIR}\bauble\images\ghini_logo.bmp"
!define MUI_HEADERIMAGE_RIGHT
;!define MUI_FINISHPAGE_NOAUTOCLOSE  ;allows users to check install log before continuing
!define MUI_FINISHPAGE_RUN_TEXT "Start ${PRODUCT_NAME}"
!define MUI_FINISHPAGE_RUN $INSTDIR\${PROGEXE}
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!define MUI_FINISHPAGE_LINK "Visit the Ghini home page"
!define MUI_FINISHPAGE_LINK_LOCATION http://ghini.github.io/


;------------------------------
;  SCRIPTS

; NsisMultiUser - all settings need to be set before including the NsisMultiUser.nsh header file.
; thanks to Richard Drizin https://github.com/Drizin/NsisMultiUser
!include ..\nsis\Include\NsisMultiUser.nsh
!include ..\nsis\Include\UAC.nsh
!include MUI2.nsh
!include WordFunc.nsh
!include FileFunc.nsh


;------------------------------
;  PAGES

; Installer
!insertmacro MUI_PAGE_LICENSE "${SRC_DIR}\share\ghini\${LICENSE_FILE}"
!insertmacro MULTIUSER_PAGE_INSTALLMODE
; this will show the 2 install options, unless it's an elevated inner process
; (in that case we know we should install for all users)
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller
!insertmacro MULTIUSER_UNPAGE_INSTALLMODE
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES


;------------------------------
;  LANGUAGES

; MUIv2 macros (must be after scripts and pages)
!insertmacro MUI_LANGUAGE "English"
!insertmacro MULTIUSER_LANGUAGE_INIT


;------------------------------
;  INSTALLER SECTIONS

; Install Types
InstType "Base"
; Custom is included by default

;----------------
; Main Section

Section "!Ghini.desktop" SecMain

    SectionIN 1

    ; Install Files
    SetOutPath "$INSTDIR"
    SetOverwrite on
    ; package all files, recursively, preserving attributes
    ; assume files are in the correct places
    File /a /r "${SRC_DIR}\*.*"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\${UNINSTALL_FILENAME}"

    ; add registry keys
    !insertmacro MULTIUSER_RegistryAddInstallInfo
    ; create shortcuts
    CreateDirectory "${START_MENU}"
    CreateShortcut "${START_MENU}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PROGEXE}" \
        "" "$INSTDIR\${PROGEXE}" "" SW_SHOWNORMAL \
        "" "Ghini biodiversity collection manager"
    ; desktop shortcut
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PROGEXE}" \
        "" "$INSTDIR\${PROGEXE}" "" SW_SHOWNORMAL \
        "" "Ghini biodiversity collection manager"

SectionEnd


;------------------------------
;  UNINSTALLER SECTIONS
;
; All section names prefixed by "Un" will be in the uninstaller

; Settings
UninstallText "This will uninstall ${PRODUCT_NAME}."

; Main Uninstall Section

Section "Uninstall" SecUnMain
    ; Remove registry keys
    !insertmacro MULTIUSER_RegistryRemoveInstallInfo
    Delete "${START_MENU}\*.*"
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    SetOutPath $TEMP
    RMDir /r "$INSTDIR"
    RMDir /r "${START_MENU}"
SectionEnd


;------------------------------
;  CALLBACK FUNCTIONS

; On Initializing
Function .onInit
    ; Initialize the NsisMultiUser plugin
    !insertmacro MULTIUSER_INIT
FunctionEnd

; On Initializing the uninstaller
Function un.onInit
    ; Initialize the NsisMultiUser plugin
    !insertmacro MULTIUSER_UNINIT
FunctionEnd
