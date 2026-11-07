@echo off
rem Builds InputBridge.asi (32-bit, to match speed.exe) with Zig (https://ziglang.org).
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH)
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 InputBridge.cpp -ldinput8 -ldxguid -lxinput1_4 -lshlwapi -lgdi32 -luser32 -o InputBridge.asi -w || exit /b 1
del /q InputBridge.lib InputBridge.pdb 2>nul
