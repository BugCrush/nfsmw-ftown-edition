@echo off
rem Builds NFSMWHUDAdapter.asi from ExOptsTeam/NFSMWHUDAdapter 4ccf92b (no licence: private use only), unchanged,
rem with the newer toolset and SDK in place of the project's v141 / 8.1 (not installed). The mod has no .ini.
rem Usage: build.bat
cd /d "%~dp0"
set "CLONE=%~dp0..\..\.superpowers\visual-research\repos\NFSMWHUDAdapter"
call ..\msbuild-companion.bat "%CLONE%" NFSMWHUDAdapter.vcxproj 4ccf92b out "/p:PlatformToolset=v143" "/p:WindowsTargetPlatformVersion=10.0" || exit /b 1
