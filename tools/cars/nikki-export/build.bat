@echo off
rem Builds NikkiExport.dll (x86, .NET 8) with the C# compiler of VS Build Tools 2022, against .NET 8's own assemblies
rem (.tools\dotnet-x86, no SDK needed) and Binarius 2.10.4's Nikki.dll. Run it with .tools\dotnet-x86\dotnet.exe exec.
setlocal
set "HERE=%~dp0"
set "ROOT=%HERE%..\..\.."
set "CSC=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\Roslyn\csc.exe"
set "NET=%ROOT%\.tools\dotnet-x86\shared\Microsoft.NETCore.App\8.0.32"
set "BIN=%ROOT%\.tools\binarius-2.10.4"
if not exist "%HERE%out" mkdir "%HERE%out"
"%CSC%" /nologo /noconfig /nostdlib+ /target:exe /platform:x86 /langversion:latest /out:"%HERE%out\NikkiExport.dll" ^
  /r:"%NET%\System.Private.CoreLib.dll" /r:"%NET%\System.Runtime.dll" /r:"%NET%\System.Console.dll" ^
  /r:"%NET%\System.Collections.dll" /r:"%NET%\netstandard.dll" /r:"%BIN%\Nikki.dll" /r:"%BIN%\CoreExtensions.dll" ^
  "%HERE%NikkiExport.cs" || exit /b 1
copy /y "%BIN%\Nikki.dll" "%HERE%out\" >nul
copy /y "%BIN%\CoreExtensions.dll" "%HERE%out\" >nul
copy /y "%BIN%\LZCompressLib.dll" "%HERE%out\" >nul
> "%HERE%out\NikkiExport.runtimeconfig.json" echo {"runtimeOptions": {"tfm": "net8.0", "framework": {"name": "Microsoft.NETCore.App", "version": "8.0.0"}, "rollForward": "Major"}}
echo built %HERE%out\NikkiExport.dll
