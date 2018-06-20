@echo off
setlocal

rem process command line arguments (/e produces exe only not installer,
rem only other argument proccessed must be a pathname to a virtualenv)
:loop
if [%1]==[] goto continue
if "%1"=="/e" (
  set exeonly=y
) else (
  set venv="%~f1"
)
shift
goto loop
:continue

if defined exeonly echo "build exe only"
if defined venv (
  echo "using virtualenv %venv%"
) else (
  for /f %%i in ('git rev-parse --abbrev-ref HEAD') do (set branch=%%i)
  set venv="%HOMEDRIVE%%HOMEPATH%\.virtualenvs\%branch%"
)

if not exist %venv%\scripts\activate.bat (
  echo ""creating build environment""
  rem STEP 1 - install virtualenv and create a virtual environment
  C:\Python27\Scripts\pip install virtualenv
  C:\Python27\Scripts\virtualenv --system-site-packages %venv%
)

if "%VIRTUAL_ENV%"=="" (
  echo "Activating build environment"
  rem STEP 2 - activate the virtual environment
  call %venv%\Scripts\activate.bat
) else (
  echo "Current virtual environment: %VIRTUAL_ENV%"
  if not "%VIRTUAL_ENV%"==%venv% (
    echo "deactivating current virtual env and activating build environment"
    call deactivate
    call %venv%\Scripts\activate.bat
  )
)


echo "Installing dependencies"
rem STEP 3 - Install dependencies into the virtual environment
pip install py2exe_py2
pip install psycopg2
pip install Pygments

echo "cleaning up"
rem STEP 4 - clean up any previous builds
python setup.py clean
forfiles /P "%VIRTUAL_ENV%"\Lib\site-packages\ /M ghini.desktop-*.egg-info /C^
 "cmd /c if @ISDIR==TRUE rmdir /s /q @PATH && echo "removing @PATH" 2>NUL"

echo "installing without eggs"
rem STEP 5 - install ghini.desktop and it's dependencies into the virtual env
pip install .

echo "building executable"
rem STEP 6 - build the executable
python setup.py py2exe

rem executable only?
if defined exeonly goto skip_nsis

echo "building NSIS installer"
rem STEP 7 - build the installer
python setup.py nsis
goto :end

:skip_nsis
copy scripts\win_gtk.bat dist

:end
endlocal
