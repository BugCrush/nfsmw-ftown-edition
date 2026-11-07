@echo off
rem Builds NFSMW_XenonEffects.asi (32-bit) from xan1242/NFSMW_XenonEffects at the commit prep.py checks.
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH). Needs .tools\pyenv for prep.py.
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"..\..\.tools\pyenv\Scripts\python.exe" -I prep.py || exit /b 1
if not exist out mkdir out
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 -std=c++20 -include cstddef -fms-extensions -fasm-blocks -fdeclspec -Isrc src\dllmain.cpp src\stdafx.cpp -ld3d9 -ld3dx9_26 -o out\NFSMW_XenonEffects.asi -w || exit /b 1
del /q out\NFSMW_XenonEffects.lib out\NFSMW_XenonEffects.pdb 2>nul
echo built out\NFSMW_XenonEffects.asi
