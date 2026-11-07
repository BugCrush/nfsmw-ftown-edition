NFSMW F-Town Edition 1.0.0
==========================

A mod for Need for Speed Most Wanted (2005, PC) that adds:

- F-Town: a new map, built from OpenStreetMap, reached from Quick Race > Bonus Maps (Free Roam, Time Attack and
  three events: a drag, a speed trap and a sector sprint), with traffic, an evening look, and a road with a jump that
  joins it to Rockport.
- The Mahindra Thar, plus five add-on cars by other authors (1971 Dodge Challenger, Fast & Furious Flip Car,
  Bugatti Chiron, Ford F-150 SVT Raptor, Longnose Cab semi truck).
- The Xbox 360 look (the Xbox 360 Stuff Pack, its cutscenes, music and engine sounds, 1024x vinyls, ReTex 2.02
  textures) with picture effects on top: ambient occlusion, light shafts, distance haze, wet roads, edge smoothing,
  world shadows back on.
- Controller support with separate triggers and rumble (Xbox controllers), and your own songs in the game's playlist.

Only our own work is in this download. The other authors' mods are downloaded by you from their own pages, and the
installer applies them.


What you need
-------------

- Need for Speed Most Wanted (2005) for PC, version 1.3, Black Edition files, unmodded. The installer checks this and
  stops with a message if your game is different. Other versions and languages other than English are untested.
- About 7 GB of free space on the game's drive (the mod adds about 4 GB, and the installer keeps a 2 GB backup of
  every file it changes), and about 2 GB on the system drive while it installs.
- Windows 10 or 11 and a graphics card with Vulkan (the package includes DXVK).


Step 1: download the other mods
-------------------------------

Put every download in one folder, for example C:\NFSMW downloads. Extract .rar and .7z archives with 7-Zip into that
folder (any sub-folder name is fine). Leave .zip files as they are: the installer reads them. The installer checks
each file against the exact version it was tested with and tells you if one is missing or different.

  1. Xbox 360 Stuff Pack 4.2, "Complex Installation" folder ......... https://nfsmods.xyz/mod/1200
  2. Xbox 360 Stuff Pack 4.2, "Easy Installation" folder (only its GLOBAL\GlobalMemoryFile.bin is used)
                                                                       https://nfsmods.xyz/mod/1200
  3. Xbox 360 converted movies ........................................ https://nfsmods.xyz/mod/3006
  4. Recompiled Vinyls 1024x Simple Installation (NFSMWRV-1024x.7z) ... https://nfsmods.xyz/mod/629
  5. ReTex 2.02 (NFSMW_ReTex_2.02.rar) ...... https://www.nfsaddons.com/downloads/nfsmw/tools/10723/need-for-speed-most-wanted-retex-202.html
  6. NFSMW Unlimiter 4.1.0.400 (NFSMW-ULv4.1.0.400.zip) . https://github.com/nlgxzef/NFSMWUnlimiter/releases/tag/v4.1.0.0400
  7. 1971 Dodge Challenger R/T 440 ...................................... https://nfsmods.xyz/mod/754
  8. Fast & Furious Flip Car 1.04 ....................................... https://nfsmods.xyz/mod/5194
  9. Bugatti Chiron ...................................................... https://nfsmods.xyz/mod/697
 10. Ford F-150 SVT Raptor 1.2.3 ......................................... https://nfsmods.xyz/mod/1696
 11. Longnose Cab Semi Truck ............................................. https://nfsmods.xyz/mod/3803
 12. Dodge Tomahawk 1.0.1 (used as a template for the Thar) .............. https://nfsmods.xyz/mod/5882
 13. Attribulator 2.0.0 (release_windows.zip) ............ https://github.com/NFSTools/Attribulator/releases/tag/v2.0.0
 14. Binarius 2.10.4 (Binarius.v2.10.4.2.zip) .................. https://github.com/nlgxzef/Binarius/releases/tag/v2.10.4
 15. .NET 8.0.32 for 32-bit Windows, both zips:
       https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.32/dotnet-runtime-8.0.32-win-x86.zip
       https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/8.0.32/windowsdesktop-runtime-8.0.32-win-x86.zip

Items 13 to 15 are tools the installer runs on your machine; nothing of them is copied into the game. A missing item
skips only the parts that need it (for example, without the movies everything else is still installed).


Step 2: check, then install
---------------------------

Close the game. Open a command prompt in this folder and run:

  FTownEditionInstaller.exe check   --game "C:\Games\Need for Speed Most Wanted" --downloads "C:\NFSMW downloads"
  FTownEditionInstaller.exe install --game "C:\Games\Need for Speed Most Wanted" --downloads "C:\NFSMW downloads"

(or double-click FTownEditionInstaller.exe and answer its questions). The install takes about 5 to 15 minutes and prints each
part as it goes.

Controller layout: a new profile starts with the mod's layout for an Xbox controller (RT accelerate, LT brake, left
stick steer, right stick up/down to shift, A nitrous, B handbrake, X speedbreaker, Y pull camera back, LB look behind,
RB change camera, Back reset car, Start pause, D-pad events/blacklist/map/messages, right stick click next song).
The installer asks whether to put the same layout into your existing profiles (default yes; --profiles no on the
command line to leave them). It changes only their controller bindings and keeps a copy of each. In any profile,
Restore Defaults on the Controls menu's controller page also gives this layout (the game's own defaults put
accelerate and brake on the A and X buttons).

Some antivirus programs distrust installers made from Python programs. The installer's source is public (link below);
every file this package contains is listed with its SHA-256 in payload-manifest.json.

Saves: with this mod the game keeps profiles in its own folder (SAVE). To keep an existing profile, copy it from
Documents\NFS Most Wanted into the game folder's SAVE\NFS Most Wanted. A profile that has owned an add-on car needs the
mod (CarStable) to load: keep the mod installed while you use that profile.


Your own songs
--------------

Make a folder "CUSTOM SONGS" in the game folder and put MP3 files named Title_Artist.mp3 in it. They play in the
game's playlist. The right stick click skips to the next song during races.


Slower computers
----------------

The look was tuned on a GTX 1650 Ti laptop (about 65 to 95 frames per second in races at 1920x1080). If your game
runs slowly, edit these files in the game's scripts folder (Notepad is fine), most effective first:

- In the game's Video options: Shadow Detail one step lower (the world shadows cost the most).
- VisualBridge.ini: under [Wet] set Strength = 0 (wet roads); under [Shafts] set Strength = 0 (light shafts);
  under [AO] set Enabled = 0 (ambient occlusion).
- dxvk.conf: delete the line starting with dxvk.hud to hide the frame-rate counter.


Uninstall
---------

  FTownEditionInstaller.exe uninstall --game "C:\Games\Need for Speed Most Wanted"

puts back every game file exactly as it was before the install (checked by SHA-256) and removes everything the
install added. Saves, logs and race times the game wrote afterwards stay. A profile the installer gave the mod's
controller layout gets its old bindings back if you have not played it since; a profile you have played keeps the
mod's layout (Restore Defaults on its Controls menu's controller page then gives the game's own).


Known limits
------------

- Tested on one machine and one copy of the game (the Black Edition); a plain retail 1.3 is refused until tested.
- English game text only. Other languages show the new cars' names in English or not at all.
- F-Town has no opponents in races yet (Time Attack and the events are against the clock).
- If a part fails, the installer says so; run uninstall and then install again. The file
  FTownEdition-backup\install.log in the game folder says what happened.


Credits and licence
-------------------

Every author and licence is in CREDITS.txt. Our own work is under the MIT licence (LICENSE). Source code:
https://github.com/BugCrush/nfsmw-ftown-edition (to be published with this release).

Map data (c) OpenStreetMap contributors, available under the Open Database License (ODbL).
