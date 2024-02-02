; Copyright (c) 2016-2024 Ross Demuth <rossdemuth123@gmail.com>
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
; FileFunc.nsh (included in NSIS v3.0) for command line options
; LogicLib (included in NSIS v3.0)
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
!define JRE_SRC_DIR "..\jre"
!define FOP_SRC_DIR "..\fop-$%fop_ver%"

!define PRODUCT_NAME "ghini.desktop"
Outfile "..\dist\${PRODUCT_NAME}-${VERSION}-setup.exe"
!define PROGEXE "ghini.exe"
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


;------------------------------
;  SETTINGS

; Multi User Settings (must come before the NsisMultiUser script)
!define MULTIUSER_INSTALLMODE_DEFAULT_ALLUSERS 1
!define MULTIUSER_INSTALLMODE_64_BIT 1

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
!define MUI_FINISHPAGE_LINK "Visit the code repository"
!define MUI_FINISHPAGE_LINK_LOCATION https://github.com/RoDuth/ghini.desktop


;------------------------------
;  SCRIPTS

!include NsisMultiUser.nsh
!include UAC.nsh
!include MUI2.nsh
!include FileFunc.nsh
!include LogicLib.nsh


;------------------------------
;  PAGES

; Installer
!insertmacro MULTIUSER_PAGE_INSTALLMODE ; if elevated will not show - install for all users
!insertmacro MUI_PAGE_LICENSE "${SRC_DIR}\share\ghini\${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipFOPLicense
!define MUI_LICENSEPAGE_TEXT_TOP "Apache FOP License."
!define MUI_LICENSEPAGE_TEXT_BOTTOM "If you accept the terms of agreement, click I Agree to continue. You must accept the agreement to install the optional Apache FOP component."
!insertmacro MUI_PAGE_LICENSE "${FOP_SRC_DIR}\${LICENSE_FILE}"
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipOpenJDKLicense
!define MUI_LICENSEPAGE_TEXT_TOP "OpenJDK JRE License."
!define MUI_LICENSEPAGE_TEXT_BOTTOM "If you accept the terms of agreement, click I Agree to continue. You must accept the agreement to install the optional OpenJDK JRE component."
!insertmacro MUI_PAGE_LICENSE "${JRE_SRC_DIR}\legal\java.base\${LICENSE_FILE}"
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
InstType "Full"
; Custom is included by default

;----------------
; Main Section

Section "!Ghini.desktop" SecMain

    SectionIN RO

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
; +Components Group

SectionGroup /e "Extras" SecOPs

;----------------
; --Apache FOP

Section /o "Apache FOP" SecFOP

    SectionIN 2

    ; Install Files
    SetOutPath "$INSTDIR\fop"
    SetOverwrite on

    ; package all files, recursively, preserving attributes
    ; assume files are in the correct places
    File /a /r "${FOP_SRC_DIR}\*.*"

SectionEnd

;----------------
; --OpenJDK java RE

Section /o "OpenJDK JRE" SecJRE

    SectionIN 2

    ; Install Files
    SetOutPath "$INSTDIR\jre"
    SetOverwrite on

    ; package all files, recursively, preserving attributes
    ; assume files are in the correct places
    File /a /r "${JRE_SRC_DIR}\*.*"

SectionEnd

SectionGroupEnd


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

; should be the last section
; hidden section, write install size as the final step
; Section "-Write Install Size"
;     !insertmacro MULTIUSER_RegistryAddInstallSizeInfo
; SectionEnd


;------------------------------
;  SECTION DESCRIPTIONS

; Language Strings
LangString DESC_SecMain ${LANG_ENGLISH} "Ghini.desktop - biodiversity collection manager - this is the main component \
                                        (required)"
LangString DESC_SecOPs ${LANG_ENGLISH} "Optional extras that you may need to get the most out of ghini.desktop."
LangString DESC_SecFOP ${LANG_ENGLISH} "Apache FOP is required for XSL report templates. (Java RE is required to use)"
LangString DESC_SecJRE ${LANG_ENGLISH} "A minimal Java RE as required by FOP XSL report formatter.  If you already have \
                                        java installed you do not need this."

; Initialise Language Strings (must come after the sections)
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_SecMain)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecOPs} $(DESC_SecOPs)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecFOP} $(DESC_SecFOP)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecJRE} $(DESC_SecJRE)
!insertmacro MUI_FUNCTION_DESCRIPTION_END


;------------------------------
; CUSTOM FUNCTIONS

Function SkipOpenJDKLicense
    ${IfNot} ${SectionIsSelected} ${SecJRE}
        Abort ;skip license if JRE not selected
    ${EndIf}
FunctionEnd

Function SkipFOPLicense
    ${IfNot} ${SectionIsSelected} ${SecFOP}
        Abort ;skip license if FOP not selected
    ${EndIf}
FunctionEnd

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
