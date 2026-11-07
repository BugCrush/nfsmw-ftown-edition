@echo off
rem Builds the stand-in and its mod DLL, copies PatchMap.asi next to them, runs, checks the log.
rem Usage: run-patchmap.bat [path\to\zig.exe]
set "ZIG=%~1"
if "%ZIG%"=="" set "ZIG=zig"
cd /d "%~dp0"
if not exist out mkdir out
"%ZIG%" c++ -target x86-windows-gnu -O1 -shared -DMOD patchmap-standin.cpp -o out\patchmap-standin-mod.dll -w || exit /b 1
rem A fixed base, like speed.exe's: PatchMap compares only an image loaded where its file asks to be.
"%ZIG%" c++ -target x86-windows-gnu -O1 patchmap-standin.cpp -Wl,--no-dynamicbase -o out\patchmap-standin.exe -w || exit /b 1
if exist ..\PatchMap.asi (copy /y ..\PatchMap.asi out\ >nul) else (del /q out\PatchMap.asi 2>nul)
del /q out\PatchMap.log 2>nul
pushd out
.\patchmap-standin.exe
popd
"..\..\..\.tools\pyenv\Scripts\python.exe" -I check-patchmap.py out
