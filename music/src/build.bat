@echo off
rem Builds MusicBridge.asi and MusicProbe.asi (32-bit, to match speed.exe) with Zig (https://ziglang.org).
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH)
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 MusicBridge.cpp Player.cpp -lmfplat -lmfreadwrite -lmfuuid -lole32 -o MusicBridge.asi -w || exit /b 1
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 MusicProbe.cpp -o MusicProbe.asi -w || exit /b 1
del /q MusicBridge.lib MusicBridge.pdb MusicProbe.lib MusicProbe.pdb 2>nul
