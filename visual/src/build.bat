@echo off
rem Builds VisualBridge.asi (32-bit, to match speed.exe) with Zig. Usage: build.bat [path\to\zig.exe]
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 VisualBridge.cpp -ld3d9 -luser32 -o VisualBridge.asi -w || exit /b 1
del /q VisualBridge.lib VisualBridge.pdb 2>nul
