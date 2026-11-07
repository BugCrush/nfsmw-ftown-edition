@echo off
rem Builds the NFSMW Unlimiter (nlgxzef/NFSMWUnlimiter, commit 7475f166a2 = release v4.1.0.400) from the clone in
rem .superpowers\downloads\unlimiter\src, unchanged, with MSBuild (its project uses MSVC inline assembly). The
rem project's post-build step copies to the author's own game folder (G:\...); it is switched off.
rem Output: companions\unlimiter\out\NFSMWUnlimiter.asi. Usage: build.bat
setlocal
set "HERE=%~dp0"
rem It needs the old DirectX SDK's D3DX headers and d3dx9.lib (links to d3dx9_43.dll, in Windows): taken from the
rem Widescreen Fixes Pack clone (external\minidx9, as for our Widescreen Fix build) through cl's and link's own
rem environment variables, so the project stays unchanged.
set "DX=%HERE%..\..\.superpowers\visual-research\repos\wfp\external\minidx9"
set "CL=/I"%DX%\Include""
set "LINK=/LIBPATH:"%DX%\Lib\x86""
call "%HERE%..\msbuild-companion.bat" "%HERE%..\..\.superpowers\downloads\unlimiter\src" NFSMWUnlimiter.vcxproj 7475f166a2 "%HERE%out" "/p:PostBuildEventUseInBuild=false" || exit /b 1
