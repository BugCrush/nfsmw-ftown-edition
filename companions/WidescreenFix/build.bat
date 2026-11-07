@echo off
rem Builds NFSMostWanted.WidescreenFix.asi from ThirteenAG/WidescreenFixesPack the way its author does: the
rem repository's premake generates a Visual Studio 2026 project, MSBuild (VS Build Tools 2026, MSVC) builds it.
rem Needs: the clone in .superpowers\visual-research\repos\wfp at the commit below (sparse: source, data,
rem includes, Resources, textures\NFS, tools; submodules under external\ initialised recursively), VS Build
rem Tools 2026 with the C++ workload, the Windows SDK. Usage: build.bat
setlocal
cd /d "%~dp0"
set "WFP=..\..\.superpowers\visual-research\repos\wfp"
set "COMMIT=708f752"
for /f %%h in ('git -C "%WFP%" rev-parse HEAD') do set "HEAD=%%h"
if not "%HEAD:~0,7%"=="%COMMIT%" (echo clone is at %HEAD%, expected %COMMIT% & exit /b 1)
set "MSB=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not exist "%MSB%" set "MSB=C:\Program Files\Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if not exist "%MSB%" (echo MSBuild of VS Build Tools 2026 not found & exit /b 1)
pushd "%WFP%"
.\premake5.exe vs2026 || (popd & exit /b 1)
"%MSB%" build\NFSMostWanted.WidescreenFix.vcxproj /p:Configuration=Release /p:Platform=Win32 /v:minimal /nologo || (popd & exit /b 1)
popd
if not exist out mkdir out
copy /y "%WFP%\data\NFSMostWanted.WidescreenFix\scripts\NFSMostWanted.WidescreenFix.asi" out\ >nul || exit /b 1
copy /y "%WFP%\data\NFSMostWanted.WidescreenFix\scripts\NFSMostWanted.WidescreenFix.ini" out\ >nul || exit /b 1
echo built out\NFSMostWanted.WidescreenFix.asi
