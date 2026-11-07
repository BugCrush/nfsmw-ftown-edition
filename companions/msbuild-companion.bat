@echo off
rem Builds one companion's Visual Studio project (Release, Win32) from its clone at a checked commit, unchanged,
rem with MSBuild of VS Build Tools 2022 (toolset v143, Windows SDK 10.0.26100). Output goes to <out dir>.
rem Usage: msbuild-companion.bat <clone dir> <project file inside the clone> <commit, 7+ chars> <out dir> [extra /p: ...]
setlocal
set "CLONE=%~1"
set "PROJ=%~2"
set "COMMIT=%~3"
set "OUT=%~f4"
for /f %%h in ('git -C "%CLONE%" rev-parse HEAD') do set "HEAD=%%h"
call set "HEADCUT=%%HEAD:~0,7%%"
if not "%HEADCUT%"=="%COMMIT:~0,7%" (echo clone %CLONE% is at %HEAD%, expected %COMMIT% & exit /b 1)
set "MSB=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not exist "%MSB%" (echo MSBuild of VS Build Tools 2022 not found & exit /b 1)
if not exist "%OUT%" mkdir "%OUT%"
"%MSB%" "%CLONE%\%PROJ%" /p:Configuration=Release /p:Platform=Win32 /p:SolutionDir="%CLONE%\\" /p:OutDir="%OUT%\\" /p:IntDir="%OUT%\obj\\" %5 %6 %7 %8 /v:minimal /nologo || exit /b 1
echo built into %OUT%
