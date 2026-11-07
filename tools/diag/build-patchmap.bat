@echo off
rem Builds PatchMap.asi (32-bit, diagnostic only). Usage: build-patchmap.bat [path\to\zig.exe]
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 PatchMap.cpp -o PatchMap.asi -w || exit /b 1
del /q PatchMap.lib PatchMap.pdb 2>nul
