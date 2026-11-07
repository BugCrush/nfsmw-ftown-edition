"""Tests for tools/cars/endscript.py. Run: python tools/cars/tests/test_endscript.py"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("endscript", os.path.join(HERE, "..", "endscript.py"))
endscript = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endscript)

MAIN = """[VERSN2]

version 2.8.3
watermark ""

combobox "Install" "Uninstall" "Pick one."

"Install"
append _Menu\\_Install.end
append _Menu\\VinylRes.end

"Uninstall"
append _Menu\\_Uninstall.end

end
"""
INSTALL = """[VERSN2]
// Unlock Memory Files
unlock_memory all
if directory_exists absolute "CARS\\X"
do // nothing
else
create_folder absolute "CARS\\X"
end
import override Global\\GlobalB.lzc DBModelParts CarPart\\X.BIN
"""
VINYL = """[VERSN2]

combobox "512x" "1024x" "Choose your vinyls resolution."

"512x"
move_file override relative absolute "512x\\X\\VINYLS.BIN" "CARS\\X\\VINYLS.BIN"

"1024x"
move_file override relative absolute "1024x\\X\\VINYLS.BIN" "CARS\\X\\VINYLS.BIN"

end
"""


class Flatten(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "_Menu"))
        for rel, text in (("Main.end", MAIN), ("_Menu/_Install.end", INSTALL), ("_Menu/VinylRes.end", VINYL),
                          ("_Menu/_Uninstall.end", "[VERSN2]\nremove_collection GLOBAL\\GLOBALB.LZC X\n")):
            with open(os.path.join(self.root, rel), "w") as f:
                f.write(text)

    def flat(self, choices, drop=()):
        return endscript.flatten(os.path.join(self.root, "Main.end"), self.root, choices, drop)

    def test_chosen_branches_inlined_in_order(self):
        lines = self.flat({"Pick one.": "Install", "Choose your vinyls resolution.": "512x"})
        self.assertEqual(lines[0], "[VERSN2]")
        self.assertIn("import override Global\\GlobalB.lzc DBModelParts CarPart\\X.BIN", lines)
        self.assertIn('move_file override relative absolute "512x\\X\\VINYLS.BIN" "CARS\\X\\VINYLS.BIN"', lines)
        self.assertFalse(any("1024x" in l or "remove_collection" in l for l in lines))
        self.assertLess(lines.index("unlock_memory all"), [i for i, l in enumerate(lines) if "512x" in l][0])

    def test_if_end_inside_an_appended_file_is_kept_whole(self):
        lines = self.flat({"Pick one.": "Install", "Choose your vinyls resolution.": "512x"})
        i = lines.index('if directory_exists absolute "CARS\\X"')
        self.assertEqual(lines[i + 1:i + 5], ["do // nothing", "else", 'create_folder absolute "CARS\\X"', "end"])

    def test_no_version_watermark_or_menus_left(self):
        lines = self.flat({"Pick one.": "Install", "Choose your vinyls resolution.": "512x"})
        for l in lines:
            self.assertFalse(l.startswith(("version", "watermark", "combobox", "append", "[VERSN")) and l != "[VERSN2]")
        self.assertEqual(lines.count("[VERSN2]"), 1)

    def test_missing_choice_is_an_error(self):
        with self.assertRaises(ValueError):
            self.flat({"Pick one.": "Install"})

    def test_unknown_label_is_an_error(self):
        with self.assertRaises(ValueError):
            self.flat({"Pick one.": "Install", "Choose your vinyls resolution.": "2048x"})

    def test_drop_lines_by_prefix(self):
        lines = self.flat({"Pick one.": "Install", "Choose your vinyls resolution.": "512x"}, drop=("unlock_memory",))
        self.assertNotIn("unlock_memory all", lines)


if __name__ == "__main__":
    sys.exit(unittest.main())
