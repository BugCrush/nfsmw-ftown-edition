"""Where the reused repo tools live, and pointing them at the player's .NET tools.

From source, tools/x360, tools/cars, tools/textures, tools/carbuild and the Thar package folder are put on sys.path.
In the frozen installer PyInstaller has bundled the same modules (release/installer/ftedition.spec lists the folders), so
the imports work the same way.

The repo tools keep their tool locations in module constants (part1.ATTRIBULATOR, part2.BINARIUS_DIR, ...), set for
the developer's .tools folder. configure() sets them to the folders the installer extracted from the player's downloads.
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)
REPO = None if FROZEN else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TOOL_DIRS = [("tools", "x360"), ("tools", "cars"), ("tools", "textures"), ("tools", "carbuild"),
             ("tools", "cars", "packages", "thar"), ("tools", "cars", "packages", "longnosecab")]

if not FROZEN:
    for parts in TOOL_DIRS:
        p = os.path.join(REPO, *parts)
        if p not in sys.path:
            sys.path.append(p)


def configure(attribulator_dir, binarius_dir, dotnet_dir):
    """Points every reused module at the given tool folders (absolute paths)."""
    import part1
    import part2
    import install as cars_install
    part1.ATTRIBULATOR = os.path.join(attribulator_dir, "Attribulator.CLI.dll")
    part1.DOTNET_X86 = os.path.join(dotnet_dir, "dotnet.exe")
    part2.BINARIUS_DIR = binarius_dir
    part2.DOTNET_X86 = dotnet_dir
    cars_install.BINARIUS_DIR = binarius_dir
    cars_install.DOTNET_X86 = dotnet_dir
    return {"attribulator": part1.ATTRIBULATOR, "dotnet": part1.DOTNET_X86, "binarius": part2.BINARIUS_DIR}
