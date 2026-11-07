@echo off
rem Builds and runs the native tests of cars\src\stable.h (32-bit, like the game). Usage: run-stable-tests.bat
cd /d "%~dp0"
"%~dp0..\..\.tools\zig\zig.exe" c++ -target x86-windows-gnu -O1 stable_tests.cpp -o stable_tests.exe || exit /b 1
del /q stable_tests.pdb 2>nul
.\stable_tests.exe
