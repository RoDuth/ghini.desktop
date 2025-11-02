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
; /allusers or /currentuser
; /S        Silent install
; /C=[gJFA]  Install Components, where:
;    g = Unselect Ghini (used for component only installs)
;    J = select Java Runtime
;    F = select Apache FOP
;    A = select all components
; /D=PATH   Set $INSTDIR
;
; EXAMPLE:
; Ghini-?.?.?-setup.exe /S /AllUsers /C=A
; A silent, system wide install, in the default location, with all components
;

;---
; Generate a unicode installer, best set first
Unicode true

;---
; Plugins, required to compile:
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
!define PRODUCT_NAME "Ghini"
Name "${PRODUCT_NAME}"
!define VERSION "1.3.15" ; :bump
!define SRC_DIR "..\dist\ghini"
!define JRE_SRC_DIR "..\jre"
!define FOP_SRC_DIR "..\fop-$%fop_ver%"

Outfile "..\dist\${PRODUCT_NAME}-${VERSION}-setup.exe"
!define PROGEXE "ghini.exe"
!define LICENSE_FILE "LICENSE"
!define README "README.rst"
!define START_MENU_LINK "$SMPROGRAMS\${PRODUCT_NAME}.lnk"
!define UNINSTALL_KEY "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


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
!define MULTIUSER_INSTALLMODE_NO_HELP_DIALOG 1 # custom help dialog defined in .onInit

; Modern User Interface v2 Settings
!define MUI_ABORTWARNING
!define MUI_UNABORTWARNING
!define MUI_ICON "${SRC_DIR}\_internal\bauble\images\icon.ico"
!define MUI_UNICON "${SRC_DIR}\_internal\bauble\images\icon.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${SRC_DIR}\_internal\bauble\images\ghini_logo.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${SRC_DIR}\_internal\bauble\images\ghini_logo.bmp"
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
!insertmacro MUI_PAGE_LICENSE "${SRC_DIR}\_internal\share\ghini\${LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipFOPLicense
!define MUI_LICENSEPAGE_TEXT_TOP "Apache FOP License."
; TODO LIC_BOTTOM_* as LangString? (Currently can not as comes before MUI_LANGUAGE which must come after MUI_PAGE_*)
!define LIC_BOTTOM_FOP "If you accept the terms of agreement, click I Agree to continue. You must accept the agreement \
                        to install the optional Apache FOP component."
!define MUI_LICENSEPAGE_TEXT_BOTTOM "${LIC_BOTTOM_FOP}"
!insertmacro MUI_PAGE_LICENSE "${FOP_SRC_DIR}\${LICENSE_FILE}"
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipOpenJDKLicense
!define MUI_LICENSEPAGE_TEXT_TOP "OpenJDK JRE License."
!define LIC_BOTTOM_JRE "If you accept the terms of agreement, click I Agree to continue. You must accept the agreement \
                        to install the optional OpenJDK JRE component."
!define MUI_LICENSEPAGE_TEXT_BOTTOM "${LIC_BOTTOM_JRE}"
!insertmacro MUI_PAGE_LICENSE "${JRE_SRC_DIR}\legal\java.base\${LICENSE_FILE}"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller
!insertmacro MULTIUSER_UNPAGE_INSTALLMODE
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES


;------------------------------
;  LANGUAGES

; macros that must be after scripts and pages
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

Section "!ghini.desktop" SecMain

    SectionIN 1 2

    ; Uninstall any previous versions silently
    Call UninstallPrevious

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

    ; add menu shortcut
    CreateShortcut "${START_MENU_LINK}" "$INSTDIR\${PROGEXE}" \
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
    Delete "${START_MENU_LINK}"
    ; remove components, XXX if this changes will need to be updated
    Delete "$INSTDIR\ghini.exe"
    RMDir /r "$INSTDIR\_internal"
    SetOutPath $TEMP
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
SectionEnd

; should be the last section
; hidden section, write install size as the final step
; Section "-Write Install Size"
;     !insertmacro MULTIUSER_RegistryAddInstallSizeInfo
; SectionEnd


;------------------------------
;  SECTION DESCRIPTIONS

; Language Strings
LangString DESC_SecMain ${LANG_ENGLISH} "Ghini - biodiversity collection manager - this is the main component \
                                         (required)"
LangString DESC_SecOPs ${LANG_ENGLISH} "Optional extras that you may need to get the most out of Ghini."
LangString DESC_SecFOP ${LANG_ENGLISH} "Apache FOP is required for XSL report templates. (Java RE is required to use)"
LangString DESC_SecJRE ${LANG_ENGLISH} "A minimal Java RE as required by FOP XSL report formatter. If you already have \
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

Function UninstallPrevious
    ; new
    ReadRegStr $R0 SHCTX "${UNINSTALL_KEY}\${PRODUCT_NAME}" "QuietUninstallString"
    ${IfNot} ${Errors}
        ReadRegStr $R1 SHCTX "${UNINSTALL_KEY}\${PRODUCT_NAME}" "InstallLocation"
        ${If} ${FileExists} "$R1\uninstall.exe"
            ExecWait '$R0 _?=$R1'
            Delete "$R1\uninstall.exe"
            RMDir "$R1"
            Sleep 100  ; wait for RMDir
        ${EndIf}
    ${EndIf}
    ; old
    ReadRegStr $R0 SHCTX "${UNINSTALL_KEY}\ghini.desktop" "QuietUninstallString"
    ${IfNot} ${Errors}
        ReadRegStr $R1 SHCTX "${UNINSTALL_KEY}\ghini.desktop" "InstallLocation"
        ${If} ${FileExists} "$R1\uninstall.exe"
            ExecWait '$R0 _?=$R1'
            Delete "$R1\uninstall.exe"
            RMDir "$R1"
        ${EndIf}
    ${EndIf}
FunctionEnd

;------------------------------
;  CALLBACK FUNCTIONS

; On Initializing
Function .onInit
    ; Initialize the NsisMultiUser plugin
    !insertmacro MULTIUSER_INIT
    ; Provide custom help /?
    ${GetOptions} $CMDLINE "/?" $R1
    ${ifnot} ${errors}
        MessageBox MB_ICONINFORMATION "Usage:$\r$\n\
            $\r$\n\
            /allusers$\t- (un)install for all users, case-insensitive$\r$\n\
            /currentuser - (un)install for current user only, case-insensitive$\r$\n\
            /uninstall - (installer only) run uninstaller,$\r$\n\
            .$\trequires /allusers or /currentuser, case-insensitive$\r$\n\
            /S$\t- silent mode,$\r$\n\
            .$\t requires /allusers or /currentuser, case-sensitive$\r$\n\
            /C=[gJFA] -  install components where:$\r$\n\
            .$\tg = unselect Ghini (components only)$\r$\n\
            .$\tJ = select OpenJDK JRE$\r$\n\
            .$\tF = select Apache FOP$\r$\n\
            .$\tA = select all components$\r$\n\
            /D$\t- (installer only) set install directory,$\r$\n\
            .$\t must be last parameter, without quotes,$\r$\n\
            .$\t case-sensitive$\r$\n\
            /?$\t- display this message$\r$\n\
            $\r$\n\
            $\r$\n\
            Return codes (decimal):$\r$\n\
            $\r$\n\
            0$\t- normal execution (no error)$\r$\n\
            1$\t- (un)installation aborted by user (Cancel button)$\r$\n\
            2$\t- (un)installation aborted by script$\r$\n\
            666660$\t- invalid command-line parameters$\r$\n\
            666661$\t- elevation is not allowed by defines$\r$\n\
            666662$\t- uninstaller detected there's no installed version$\r$\n\
            666663$\t- executing uninstaller from the installer failed$\r$\n\
            666666$\t- cannot start elevated instance$\r$\n\
            other$\t- Windows error code when trying to start elevated instance"
        SetErrorLevel 0
        Quit
    ${endif}
    ; Check the command line options for components
    ${GetOptions} $CMDLINE "/C=" $2
    CLLoop:
        StrCpy $1 $2 1 -1
        StrCpy $2 $2 -1
        StrCmp $1 "" CLDone
            StrCmp $1 "A" +1 +3
                SectionSetFlags ${SecFOP} 1
                SectionSetFlags ${SecJRE} 1
            StrCmp $1 "g" +1 +2
                SectionSetFlags ${SecMain} 0
            StrCmp $1 "J" +1 +2
                SectionSetFlags ${SecJRE} 1
            StrCmp $1 "F" +1 +2
                SectionSetFlags ${SecFOP} 1
        Goto CLLoop
    CLDone:
FunctionEnd

; On Initializing the uninstaller
Function un.onInit
    ; Initialize the NsisMultiUser plugin
    !insertmacro MULTIUSER_UNINIT
FunctionEnd
