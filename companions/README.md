# Companions we build ourselves

The Xbox 360 Stuff Pack's open-source companions, built with Zig 0.16.0 (`x86-windows-gnu`) from upstream
clones kept in `.superpowers/visual-research/repos/` (git-ignored). Each folder has a `build.bat` (run it from
PowerShell with the path to `zig.exe`) and, where the source needs mechanical changes for Clang, a `prep.py`
that copies the clone to `src/` (git-ignored) at a checked commit and makes the counted changes. Output goes to
`out/` (git-ignored). Shared helpers:

- `compare-build.py <ours> <author's> <author's .ini> <source dir> [author's .pdb]`: which `.ini` keys each
  binary contains, and which plugin-related names in the author's `.pdb` are missing from the source (a sign
  the author's binary is newer than the source).
- `test-load.cpp`: loads a plugin outside the game and reports OK, the Windows error, or a crash.

## NFSHDReflections and NFSMWFEShadows (GPL-3.0): built with MSBuild (2026-10-18)

- **Sources:** `AeroWidescreen/NFSHDReflections` `d9b8597` (2025-11-15; project `SOURCE/NFSMW/NFSMWHDReflections.vcxproj`)
  and `AeroWidescreen/NFSMWFEShadows` `347b1d2` (2025-11-14), unchanged. Both use MSVC inline assembly, so they
  build with Microsoft's compiler: `msbuild-companion.bat` runs MSBuild of VS Build Tools 2022 (toolset v143,
  Windows SDK 10.0.26100) with the output folder passed in (the projects write to `$(SolutionDir)` otherwise).
- **Results:** `NFSMWHDReflections.asi` 257,024 bytes, `NFSMWFEShadows.asi` 204,288 bytes, x86, importing only
  `KERNEL32.dll` and `USER32.dll`. Every key of the authors' `.ini` files (26 and 4) is read by our builds.
- **Not compared byte for byte with the authors' releases:** nfsmods.xyz (mods 3363, 3005) serves them behind a
  script/Cloudflare step. Their release dates (2025-11-15) equal the commits built.

## NFSMWHUDAdapter (no licence: private use only): built with MSBuild (2026-10-19); tried and not used

**Removed after one race (the user, 2026-10-19):** with X360Stuff's own widescreen HUD it moved the HUD about 30 px
inward (manifest, "Stage 3").

- **Source:** `ExOptsTeam/NFSMWHUDAdapter` `4ccf92b` ("v1.0.0.800 (BETA)", 2018), unchanged; `build.bat` runs
  `msbuild-companion.bat` with `/p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0` in place of the
  project's v141 / SDK 8.1 (not installed). Only warnings from its bundled ini parser.
- **Result:** `NFSMWHUDAdapter.asi` 88,064 bytes (sha256 `1f6dae30c1b0050b…`), x86, imports only `KERNEL32.dll`;
  no `.ini` (the ini reader is included but unused).
- **What it does (100 lines):** replaces the game's message calls at 0x5696F1 and 0x569712 (race HUD set-up)
  and moves the HUD's left group (minimap) left and its right group right by (width/height × 240 − 320) of the
  game's 640-wide UI, and widens the minimap's limits (0x5678AA–0x5678C6) to match. Nothing in our PatchMap log
  touches those places.
- **Release:** nfsmods.xyz mod 638 is the same version, v1.0.0.800, uploaded 2018-08-30, one changelog entry; not
  compared byte for byte (the download is behind a script step). Its page says it needs the Widescreen Fix's
  `HudWidescreenMode = 1`; X360Stuff exits unless that is 0, and has its own `WidescreenUIMode` (auto). Whether
  the two together put the HUD in the right place is for the race to show.

## WidescreenFix (MIT): built with Visual Studio Build Tools 2026

- **Built (2026-10-15)** by `WidescreenFix/build.bat`: the repository's premake (`premake5 vs2026`) and MSBuild
  from VS Build Tools 2026 (MSVC 14.51.36231, installed with `winget install Microsoft.VisualStudio.BuildTools
  --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`) plus Windows SDK 10.0.26100.
  No source changes. Output `out/NFSMostWanted.WidescreenFix.asi` (2,298,368 bytes, x86) and the upstream
  default `.ini`. It imports `d3dx9_43.dll` (present in `C:\Windows\SysWOW64`, DirectX June 2010 runtime).
- **Settings that changed since our old author build:** gone: `ResX`, `ResY`, `HUDWidescreenMode`,
  `FixResolutionText` (the resolution now comes from the game's own Video menu, falling back to the desktop
  resolution); new: `HudAspectRatioConstraint`, `RightStickDeadzone`, `[GRAPHICS] ConsoleGamma, SMAA,
  HideAABug`, `[LANGUAGE]`, `[CAMERA]`. `tools/x360/stage1.py` keeps every value of ours and sets the new
  picture-changing keys to "off" (`ConsoleGamma = 0`, `SMAA = 0`, `HideAABug = 0`, `[CAMERA] Enable = 0`).

### How we got there

- **Source:** `ThirteenAG/WidescreenFixesPack` `708f752` (2026-10-09), project `NFSMostWanted.WidescreenFix`:
  `dllmain.cpp` and 13 C++20 module files (`*.ixx`), the shared `includes/` folder (`stdafx`, `postfx/postfxcore.ixx`),
  and the submodules `external/injector` (with its own `safetyhook`, `minhook`, `kananlib`, `bddisasm`; it also
  needs `zydis`), `inireader`, `hooking`, `spdlog`, `filewatch`, `modutils`, `minidx9`. Built upstream with
  Visual Studio (`cppdialect C++latest`, `/Zc:__cplusplus /utf-8`, static runtime, Unicode), an effect file
  compiled by `fxc /T fx_2_0` (the compiled `.fxo` is in the repository) and resource files.
- **Time-boxed attempt with Zig (2026-10-15), stopped at the shared header** (`includes/stdafx.cpp`), before any
  module, with errors of three kinds that need code changes, not settings:
  - `<stacktrace>` (C++23) is used by `includes/stdafx.cpp` and two of the game's modules (`Registry.ixx`,
    `Windowed.ixx`); Zig's C++ library (LLVM's libc++) does not provide it. Microsoft's library does.
  - `std::basic_string<unsigned char>` (via `std::char_traits<unsigned char>`): accepted by Microsoft's library,
    removed from recent libc++ (10 errors).
  - functions with a deduced return type used before their definition (`includes/callbacks.h`, 15 errors), which
    Microsoft's compiler tolerates and Clang does not.
- **The user chose (2026-10-15) to install the Windows SDK and build it with Microsoft's compiler.** Installed:
  Windows SDK 10.0.26100 (`winget install Microsoft.WindowsSDK.10.0.26100`). The repository's own premake
  (`premake5.exe vs2022`, after adding `tools/` to the sparse checkout) generates
  `build/NFSMostWanted.WidescreenFix.vcxproj`; MSBuild from VS Build Tools 2022 (MSVC 14.43.34808) then
  compiles every module except `Frontend.ixx`, where **the compiler itself crashes** ("C1001: Internal compiler
  error", `msc1.cpp` line 1533, at the file's last line), with or without optimisation and also built one file at
  a time (a parallel build additionally crashed on `Rendering.ixx`). Upstream builds with Visual Studio 2026
  (its `premake5.bat` runs `premake5 vs2026`), i.e. a newer compiler. Next step pending with the user: a newer
  compiler (Build Tools 2022 updated to 17.14, or Build Tools 2026).

## texwizard (GPL-3.0)

- **Source built:** `R-033/texwizard` `51e7d29` (2026-04-08), unchanged (`prep.py` only checks the commit
  and copies).
- **Flags:** `-std=c++17 -include cstddef -include sys/stat.h -DGAME_MW -D_CRT_SECURE_NO_WARNINGS
  -fms-extensions -fasm-blocks -fdeclspec`; sources `dllmain.cpp jsoncpp.cpp stdafx.cpp`. `GAME_MW` selects
  Most Wanted's addresses (`MW_Address.h`), as the project's `Release_MW` configuration does.
- **Result:** 1,124,352 bytes (the author's is 323,072). Compared with the build the pack bundles: the one key
  of `TexWizard.json` (`packs`) and the one key of the pack's `meta.json` (`textures`) are in both, and the
  author's binary has no TexWizard-specific text that ours lacks (only Windows function names from Microsoft's
  runtime, which ours does not use). Nothing suggests the bundled build is newer than this source.
- **Load test outside the game:** it checks that the host is Most Wanted (by its entry point) and, when it is
  not, shows an error box ("TexWizard") and refuses to load. Seen on 2026-10-15; that check works.

## NFSMW_XenonEffects (MIT)

- **Source built:** `xan1242/NFSMW_XenonEffects` `b507008` (2023-02-23, the repository's latest), submodule
  `includes/mINI` `a1ff72e`.
- **Flags:** `-std=c++20 -include cstddef -fms-extensions -fasm-blocks -fdeclspec`, libraries `d3d9`,
  `d3dx9_26`. (`cstddef` is included by MSVC's headers implicitly; `std::lerp` needs C++20.)
- **Mechanical changes (prep.py):** 78 comment lines with arrow characters made ASCII; 45 `ds : name` memory
  operands written `name` (two more written `ds:[x]` are accepted by Clang and left alone). `test-ds.cpp`
  shows the encoding is identical (`D8 0D …`, `D8 1D …`, `A1 …` with and without the prefix).
- **Result:** 905,728 bytes (the author's is 72,192: ours carries the C++ runtime inside instead of needing
  `MSVCP140.dll`). Neither imports Direct3D directly. Outside the game it fails to load (error 1114): its
  start-up patches game addresses, which a test program does not have. Expected; only the game can test it.
- **Not the build the pack bundles.** The bundled `NFSMW_XenonEffects.asi` reads three settings this source
  lacks (`BounceParticles`, `FadeOutParticles`, `CGIntensityBehavior`) and its `.pdb` names about 90
  functions and types the source does not have (`AddSpark`, `XSpark`, `EarlyRenderHook`, `XenonEffectList`, …).
  Its source is public: the fork `TorutheRedFox/NFSMW_XenonEffects` `37c7676` (2025-07-28, MIT), offered
  upstream as pull request 7 ("Rewrite in C++ based on console NFS MW implementations"), whose `.ini` has
  exactly those three settings. **That fork cannot be built as published:** its standard Visual Studio
  `.gitignore` kept its `Packages` folder (EA's EASTL, EABase and EAAssert, plus injector and mINI) out of git.
  Injector and mINI can be taken from the fork's own history (`45c98cd`); the EA libraries would have to be
  guessed (the project file's header list mixes files from different EASTL releases), and one EASTL vector in
  it shares its layout with the game's memory. A throwaway attempt with `paulhodge/EASTL` 6fb0f1a got to four
  error kinds before it was stopped.
- **Decision (the user, 2026-10-15): install the pack's bundled `NFSMW_XenonEffects.asi` as an exception**
  (option "1c"): its source is public but incomplete, and it is the version the pack is designed around. Our
  build of the older source stays here, unused.

## NFSMW Unlimiter (source public, no licence file): built with MSBuild (2026-10-31), for the add-on cars

- **Source:** `nlgxzef/NFSMWUnlimiter` `7475f166a2` (= release v4.1.0.400 [BETA 1], 2026-10-11), cloned to
  `.superpowers/downloads/unlimiter/src`, unchanged. `unlimiter/build.bat` runs `msbuild-companion.bat` with the
  project's post-build copy switched off and the D3DX headers and library of the Widescreen Fixes Pack's
  `external/minidx9` passed through `CL` and `LINK`.
- **Result:** `NFSMWUnlimiter.asi` 741,888 bytes (release: 738,816), x86, imports `KERNEL32`, `USER32`, `d3dx9_43`
  like the release; reads every key of the release's `.ini`. Checked beside our stack on the test copy
  (`docs/cars-notes.md`, "The Unlimiter beside our stack").
