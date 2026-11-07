@echo off
rem Builds DisplayModes.asi (32-bit, to match speed.exe) with Zig. Usage: build.bat [path\to\zig.exe]
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 DisplayModes.cpp -luser32 -o DisplayModes.asi -w || exit /b 1
del /q DisplayModes.lib DisplayModes.pdb 2>nul
