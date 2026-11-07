@echo off
rem Builds NFSMWHDReflections.asi from AeroWidescreen/NFSHDReflections d9b8597 (GPL-3.0), unchanged, and copies the
rem author's release .ini beside it. Usage: build.bat
cd /d "%~dp0"
set "CLONE=%~dp0..\..\.superpowers\visual-research\repos\NFSHDReflections"
call ..\msbuild-companion.bat "%CLONE%" SOURCE\NFSMW\NFSMWHDReflections.vcxproj d9b8597 out || exit /b 1
copy /y "%CLONE%\SOURCE\RELEASE\NFSMWHDReflections\scripts\NFSMWHDReflections.ini" out\ >nul || exit /b 1
