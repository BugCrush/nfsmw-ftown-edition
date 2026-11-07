@echo off
rem Builds FpsRecorder.asi (32-bit, to match speed.exe) with Zig (https://ziglang.org).
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH)
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 -DUNICODE -D_UNICODE FpsRecorder.cpp -lshlwapi FpsRecorder.def -o FpsRecorder.asi -w || exit /b 1
del /q FpsRecorder.lib FpsRecorder.pdb 2>nul
