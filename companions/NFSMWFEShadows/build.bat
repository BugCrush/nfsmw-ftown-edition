@echo off
rem Builds NFSMWFEShadows.asi from AeroWidescreen/NFSMWFEShadows 347b1d2 (GPL-3.0), unchanged, and copies the
rem author's .ini beside it. Usage: build.bat
cd /d "%~dp0"
set "CLONE=%~dp0..\..\.superpowers\visual-research\repos\NFSMWFEShadows"
call ..\msbuild-companion.bat "%CLONE%" NFSMWFEShadows\NFSMWFEShadows.vcxproj 347b1d2 out || exit /b 1
copy /y "%CLONE%\NFSMWFEShadows.ini" out\ >nul || exit /b 1
