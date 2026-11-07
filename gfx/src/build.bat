@echo off
rem Builds GfxProbe.asi (32-bit, to match speed.exe) with Zig (https://ziglang.org).
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH)
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
set "SOURCES=GfxProbe.cpp log.cpp hooks.cpp filtering.cpp capture.cpp frame.cpp resources.cpp effects.cpp watch.cpp dissect.cpp panel.cpp"
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 %SOURCES% -ld3d9 -ldxguid -lshlwapi -luser32 -lgdi32 -o GfxProbe.asi -w || exit /b 1
del /q GfxProbe.lib GfxProbe.pdb 2>nul
