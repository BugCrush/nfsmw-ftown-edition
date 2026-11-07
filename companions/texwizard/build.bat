@echo off
rem Builds TexWizard.asi (32-bit, Most Wanted addresses) from R-033/texwizard at the commit prep.py checks.
rem Usage: build.bat [path\to\zig.exe]   (defaults to zig on PATH). Needs .tools\pyenv for prep.py.
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
"..\..\.tools\pyenv\Scripts\python.exe" -I prep.py || exit /b 1
if not exist out mkdir out
"%ZIG%" c++ -target x86-windows-gnu -shared -O2 -std=c++17 -include cstddef -include sys/stat.h -DGAME_MW -D_CRT_SECURE_NO_WARNINGS -fms-extensions -fasm-blocks -fdeclspec -Isrc src\dllmain.cpp src\jsoncpp.cpp src\stdafx.cpp -o out\TexWizard.asi -w || exit /b 1
del /q out\TexWizard.lib out\TexWizard.pdb 2>nul
echo built out\TexWizard.asi
