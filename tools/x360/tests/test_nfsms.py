import os
import tempfile

import nfsms

SCRIPT = """game MW
ui_text Hello
ui_control checkbox visuals true "1. Lighting"
ui_control checkbox music true "11. Music"
### Main
folder_create FX
file_copy ModData\\a.bin FX\\a.bin
ui_option visuals
script ModData\\sub.nfsms
update_field visuallook default 0x1d521c97 M[1,2] 0.34
ui_option visuals
ui_option music
file_copy ModData\\m.mus SOUND\\m.mus
ui_option music
"""
SUB = "update_field visuallook default BlackBloomCurve M[1,1] 0\nupdate_field visualrgbtweaker default blue M[1,1] 0.01\n"


def make_pack():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "ModData"))
    with open(os.path.join(root, "Install.nfsms"), "w") as f:
        f.write(SCRIPT)
    with open(os.path.join(root, "ModData", "sub.nfsms"), "w") as f:
        f.write(SUB)
    return root


def test_options_default_on():
    root = make_pack()
    db, actions, opts = nfsms.expand(os.path.join(root, "Install.nfsms"), root, {})
    assert opts == {"visuals": True, "music": True}
    assert db[0] == "game MW"
    assert "update_field visuallook default 0xAAACCDF3 M[1,1] 0" in db   # name -> hash, from the inlined script
    assert "update_field visuallook default 0x1D521C97 M[1,2] 0.34" in db  # lower-case hex -> upper
    assert actions == ["folder_create FX", "file_copy ModData\\a.bin FX\\a.bin", "file_copy ModData\\m.mus SOUND\\m.mus"]


def test_option_off_drops_its_lines():
    root = make_pack()
    db, actions, opts = nfsms.expand(os.path.join(root, "Install.nfsms"), root, {"music": False})
    assert opts["music"] is False
    assert "file_copy ModData\\m.mus SOUND\\m.mus" not in actions
    assert any("visuallook" in l for l in db)


def test_resolve_by_hash_and_drop_absent_class():
    lines = ["game MW",
             "update_field timeofdaylighting no_vt_overcast AmbientColour X 0",
             "update_field timeofdaylighting 0x919b6689 AmbientColour X 0",
             "update_field visualrgbtweaker default blue M[1,1] 0.01",
             "update_field visuallook default Desaturation 0.34"]
    cols = {"timeofdaylighting": {"0x94ABDFF0", "0x919B6689", "sunny"},
            "visualrgbtweaker": None,
            "visuallook": {"default"}}
    kept, dropped = nfsms.resolve(lines, cols)
    assert kept == ["game MW",
                    "update_field timeofdaylighting 0x94ABDFF0 AmbientColour X 0",
                    "update_field timeofdaylighting 0x919B6689 AmbientColour X 0",
                    "update_field visuallook default Desaturation 0.34"]
    assert dropped == {"visualrgbtweaker/default (no such class)": 1}


def test_resolve_keeps_missing_collection_count():
    kept, dropped = nfsms.resolve(["update_field visuallook nosuch X 1"], {"visuallook": {"default"}})
    assert kept == [] and dropped == {"visuallook/nosuch": 1}


def test_unclosed_option_is_an_error():
    root = make_pack()
    with open(os.path.join(root, "Bad.nfsms"), "w") as f:
        f.write('ui_control checkbox a true "A"\nui_option a\nupdate_field x y z 1\n')
    try:
        nfsms.expand(os.path.join(root, "Bad.nfsms"), root, {})
    except ValueError as e:
        assert "unclosed" in str(e)
    else:
        raise AssertionError("expected ValueError")


RADIO = """game MW
ui_control radiobutton performance install "Install"
ui_control radiobutton performance uninstall "Uninstall"
ui_option performance install
update_field pvehicle a MASS 1
ui_option performance install
ui_option performance uninstall
update_field pvehicle a MASS 2
ui_option performance uninstall
"""


def _write(text):
    root = tempfile.mkdtemp()
    with open(os.path.join(root, "r.nfsms"), "w") as f:
        f.write(text)
    return root


def test_radiobutton_runs_only_the_chosen_branch():
    root = _write(RADIO)
    db, _, opts = nfsms.expand(os.path.join(root, "r.nfsms"), root, {"performance": "install"})
    assert opts["performance"] == "install"
    assert "update_field pvehicle a MASS 1" in db and "update_field pvehicle a MASS 2" not in db
    db, _, _ = nfsms.expand(os.path.join(root, "r.nfsms"), root, {"performance": "uninstall"})
    assert "update_field pvehicle a MASS 2" in db and "update_field pvehicle a MASS 1" not in db


def test_radiobutton_defaults_to_the_first_choice():
    root = _write(RADIO)
    db, _, opts = nfsms.expand(os.path.join(root, "r.nfsms"), root, {})
    assert opts["performance"] == "install"
    assert "update_field pvehicle a MASS 2" not in db


def test_resolve_add_node_makes_the_new_collection_known():
    lines = ["add_node pvehicle racers newcar", "add_field pvehicle newcar brakes 2",
             "update_field pvehicle newcar MASS 1500", "update_field pvehicle racers MASS 1"]
    kept, dropped = nfsms.resolve(lines, {"pvehicle": {"racers"}})
    assert kept == lines and dropped == {}


def test_resolve_add_node_under_a_missing_parent_is_dropped():
    kept, dropped = nfsms.resolve(["add_node pvehicle nosuch newcar", "update_field pvehicle newcar MASS 1"],
                                  {"pvehicle": {"racers"}})
    assert kept == [] and dropped == {"pvehicle/nosuch": 1, "pvehicle/newcar": 1}


def test_load_collections_reads_every_vault():
    root = tempfile.mkdtemp()
    d = os.path.join(root, "main", "fe_attrib", "frontend")
    os.makedirs(d)
    with open(os.path.join(d, "frontend.yml"), "w") as f:
        f.write("- Name: viper\n  Data: {}\n- ParentName: viper\n  Name: 0x12AB\n  Data: {}\n")
    assert nfsms.load_collections(root, ["frontend"]) == {"frontend": {"viper", "0x000012AB"}}


def test_quoted_script_paths_relative_to_the_including_script():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "VLT", "Attributes"))
    with open(os.path.join(root, "main.nfsms"), "w") as f:
        f.write('game MW\nscript "VLT\install.nfsms"\n')
    with open(os.path.join(root, "VLT", "install.nfsms"), "w") as f:
        f.write('script "Attributes\car.nfsms"\n')
    with open(os.path.join(root, "VLT", "Attributes", "car.nfsms"), "w") as f:
        f.write("update_field pvehicle car MASS 1500\n")
    db, _, _ = nfsms.expand(os.path.join(root, "main.nfsms"), root, {})
    assert "update_field pvehicle car MASS 1500" in db


def test_double_slash_comments_are_left_out():
    root = _write("game MW\n// New\nupdate_field pvehicle a MASS 1\n")
    db, _, _ = nfsms.expand(os.path.join(root, "r.nfsms"), root, {})
    assert db == ["game MW", "update_field pvehicle a MASS 1"]


def test_resolve_copy_node_makes_the_new_collection_known():
    lines = ["copy_node frontend angle_decal_back angle_customizeparts angle_new",
             "update_field frontend angle_new cam_orbit_vertical 96"]
    kept, dropped = nfsms.resolve(lines, {"frontend": {"angle_decal_back", "angle_customizeparts"}})
    assert kept == lines and dropped == {}


def test_resolve_copy_node_from_a_missing_source_is_dropped():
    kept, dropped = nfsms.resolve(["copy_node frontend nosuch angle_customizeparts angle_new",
                                   "update_field frontend angle_new cam_fov 1"],
                                  {"frontend": {"angle_customizeparts"}})
    assert kept == [] and dropped == {"frontend/nosuch": 1, "frontend/angle_new": 1}


def test_hashed_field_with_an_index_keeps_the_index():
    root = _write("update_field frontend rims feCarPartInfo[1] Cost 500\n")
    db, _, _ = nfsms.expand(os.path.join(root, "r.nfsms"), root, {})
    assert db == ["update_field frontend rims 0x1002EA65[1] Cost 500"]


def test_resolve_writes_hash_only_fields_as_their_hash():
    lines = ["add_field ecar car CameraInfo_Hood", "update_field ecar car CameraInfo_Hood Collection x",
             "update_field ecar car TireOffsets[0] 1"]
    kept, _ = nfsms.resolve(lines, {"ecar": {"car"}}, {"ecar": {"0xD74C1435"}})
    assert kept == ["add_field ecar car 0xD74C1435", "update_field ecar car 0xD74C1435 Collection x",
                    "update_field ecar car TireOffsets[0] 1"]


def test_load_hashed_fields_reads_hex_keys_of_a_class():
    root = tempfile.mkdtemp()
    d = os.path.join(root, "main", "attributes", "db")
    os.makedirs(d)
    with open(os.path.join(d, "ecar.yml"), "w") as f:
        f.write("- Name: car\n  Data:\n    TireOffsets: 1\n    0xD74C1435:\n      ClassKey: ''\n")
    assert nfsms.load_hashed_fields(root, ["ecar"]) == {"ecar": {"0xD74C1435"}}


SHAPES = {"pvehicle": {"MODEL": "scalar", "ShiftSND": {"ReferencedRow", "UpgradeLevel"},
                       "TurboSND": {"ReferencedRow", "UpgradeLevel"}, "brakes": {"ClassKey", "CollectionKey"}},
          "ecar": {"BodyDive": {"DegPerG", "MaxGs", "DegPerSec"}}}


def test_translate_vlted_paths_to_attribulator():
    lines = ["update_field pvehicle c MODEL Collision64 CHALLENGER71",
             "update_field pvehicle c MODEL Visual CHALLENGER71",
             "update_field pvehicle c ShiftSND[0] Collection 0x1e6e67d8",
             "update_field pvehicle c TurboSND[2] Level 1",
             "update_field pvehicle c TurboSND[2] Class turbosfx",
             "update_field pvehicle c brakes[0] Collection challenger71",
             "update_field ecar c BodyDive MaxG 0.5",
             "update_field ecar c BodyDive DegPerG 2",
             "add_field pvehicle c TurboSND 3"]
    assert nfsms.translate(lines, SHAPES) == [
        "update_field pvehicle c MODEL CHALLENGER71",
        "update_field pvehicle c ShiftSND[0] ReferencedRow Collection 0x1e6e67d8",
        "update_field pvehicle c TurboSND[2] UpgradeLevel 1",
        "update_field pvehicle c TurboSND[2] ReferencedRow Class turbosfx",
        "update_field pvehicle c brakes[0] Collection challenger71",
        "update_field ecar c BodyDive MaxGs 0.5",
        "update_field ecar c BodyDive DegPerG 2",
        "add_field pvehicle c TurboSND 3"]


def test_load_field_shapes_reads_scalars_structs_and_arrays():
    root = tempfile.mkdtemp()
    d = os.path.join(root, "main", "attributes", "db")
    os.makedirs(d)
    with open(os.path.join(d, "pvehicle.yml"), "w") as f:
        f.write("- Name: a\n  Data:\n    MODEL: ''\n    TurboSND:\n      Capacity: 1\n      Data:\n"
                "      - ReferencedRow: {ClassKey: turbosfx, CollectionKey: default}\n        UpgradeLevel: 0\n"
                "    TENSOR_SCALE: {X: 1, Y: 1, Z: 1, W: 0}\n")
    assert nfsms.load_field_shapes(root, ["pvehicle"]) == {"pvehicle": {
        "MODEL": "scalar", "TurboSND": {"ReferencedRow", "UpgradeLevel"}, "TENSOR_SCALE": {"X", "Y", "Z", "W"}}}


def test_arrays_of_a_new_collection_are_sized_before_first_use():
    lines = ["add_node engine default car",
             "update_field engine car ENGINE_BRAKING[0] 0.7",
             "update_field engine car ENGINE_BRAKING[2] 0.9",
             "update_field engine car RED_LINE 6000",
             "add_field engine car TORQUE 9",
             "update_field engine car TORQUE[8] 295",
             "update_field engine default ENGINE_BRAKING[1] 0.8"]
    assert nfsms.size_new_arrays(lines, {"engine": {"ENGINE_BRAKING": True, "TORQUE": False}}) == [
        "add_node engine default car",
        "resize_field engine car ENGINE_BRAKING 3",
        "update_field engine car ENGINE_BRAKING[0] 0.7",
        "update_field engine car ENGINE_BRAKING[2] 0.9",
        "update_field engine car RED_LINE 6000",
        "add_field engine car TORQUE 9",
        "update_field engine car TORQUE[8] 295",
        "update_field engine default ENGINE_BRAKING[1] 0.8"]


def test_add_field_of_a_base_field_becomes_a_resize():
    lines = ["add_field ecar car KitWheelOffsetFront 4", "add_field ecar car WheelWell", "add_field ecar car SlipFX",
             "add_field ecar car CamberFront"]
    layout = {"ecar": {"KitWheelOffsetFront": True, "WheelWell": False, "SlipFX": False, "CamberFront": True}}
    assert nfsms.base_fields(lines, layout) == [
        "resize_field ecar car KitWheelOffsetFront 4", "add_field ecar car WheelWell", "add_field ecar car SlipFX"]


def test_load_layout_reads_the_inlayout_flag():
    root = tempfile.mkdtemp()
    with open(os.path.join(root, "info.yml"), "w") as f:
        f.write("Classes:\n- Name: ecar\n  Fields:\n  - Name: CamberFront\n    Flags: InLayout, IsBound\n"
                "  - Name: WheelWell\n    Flags: IsBound\n")
    assert nfsms.load_layout(root) == {"ecar": {"CamberFront": True, "WheelWell": False}}


def test_a_resize_after_the_writes_does_not_count_as_sizing():
    lines = ["add_node engine default car", "update_field engine car ENGINE_BRAKING[2] 0.9",
             "resize_field engine car ENGINE_BRAKING 3"]
    assert nfsms.size_new_arrays(lines, {"engine": {"ENGINE_BRAKING": True}}) == [
        "add_node engine default car", "resize_field engine car ENGINE_BRAKING 3",
        "update_field engine car ENGINE_BRAKING[2] 0.9", "resize_field engine car ENGINE_BRAKING 3"]


def test_a_sized_add_field_is_followed_by_a_resize():
    # Attribulator's add_node copies the parent's fields, so add_field finds the field there and keeps its old size
    lines = ["add_field pvehicle car brakes 2", "add_field pvehicle car CameraInfo_Hood"]
    assert nfsms.base_fields(lines, {"pvehicle": {"brakes": False}}) == [
        "add_field pvehicle car brakes 2", "resize_field pvehicle car brakes 2", "add_field pvehicle car CameraInfo_Hood"]


def test_installer_display_lines_are_left_out():
    root = _write("game MW\nui_image VLTFiles\a.png\nui_text# hello\nupdate_field pvehicle a MASS 1\n")
    db, _, _ = nfsms.expand(os.path.join(root, "r.nfsms"), root, {})
    assert db == ["game MW", "update_field pvehicle a MASS 1"]


def test_copy_fields_keeps_the_targets_own_collection_name():
    # Attribulator's copy_fields ... base copies the CollectionName field too; the game builds SECONDARY_LOGO_<name>
    # from it, so the Flip Car showed the Clio's logo. VltEd leaves the target's own name.
    lines = ["copy_fields frontend clio flipcar base", "update_field frontend flipcar Cost 1"]
    assert nfsms.keep_collection_names(lines) == [
        "copy_fields frontend clio flipcar base", "update_field frontend flipcar CollectionName flipcar",
        "update_field frontend flipcar Cost 1"]


def test_a_link_set_by_collection_alone_gets_its_class():
    # VltEd knows which class a link field points to; Attribulator keeps the class per value and leaves it empty, and
    # the game then finds nothing (the Challenger's frontend link: the car went to the debug list, hidden from menus)
    lines = ["update_field pvehicle c frontend Collection c",
             "update_field ecar c 0xD74C1435 Collection c_hood",
             "update_field pvehicle c brakes[0] Class brakes", "update_field pvehicle c brakes[0] Collection c"]
    classes = {"pvehicle": {"frontend": "frontend", "brakes": "brakes"}, "ecar": {"0xD74C1435": "camerainfo"}}
    assert nfsms.link_classes(lines, classes) == [
        "update_field pvehicle c frontend Collection c", "update_field pvehicle c frontend Class frontend",
        "update_field ecar c 0xD74C1435 Collection c_hood", "update_field ecar c 0xD74C1435 Class camerainfo",
        "update_field pvehicle c brakes[0] Class brakes", "update_field pvehicle c brakes[0] Collection c"]


def test_load_link_classes_reads_the_class_stock_data_uses():
    root = tempfile.mkdtemp()
    d = os.path.join(root, "main", "attributes", "db")
    os.makedirs(d)
    with open(os.path.join(d, "pvehicle.yml"), "w") as f:
        f.write("- Name: a\n  Data:\n    frontend: {ClassKey: frontend, CollectionKey: a}\n"
                "    brakes:\n      Capacity: 1\n      Data:\n      - {ClassKey: brakes, CollectionKey: a}\n"
                "- Name: b\n  Data:\n    frontend: {ClassKey: '', CollectionKey: ''}\n")
    assert nfsms.load_link_classes(root, ["pvehicle"]) == {"pvehicle": {"frontend": "frontend", "brakes": "brakes"}}


def test_model_takes_the_visual_name_not_the_collision_one():
    # The Chiron's script: Visual CHIRON, then Collision MURCIELAGO, then Collision FORDGT. Attribulator holds one name
    # (StringKey64): the car showed the Ford GT's model. The visual name wins; the collision ones are dropped.
    lines = ["update_field pvehicle c MODEL Visual CHIRON", "update_field pvehicle c MODEL Collision64 MURCIELAGO",
             "update_field pvehicle c MODEL Collision FORDGT"]
    assert nfsms.translate(lines, SHAPES) == ["update_field pvehicle c MODEL CHIRON"]
    assert nfsms.model_collisions(lines) == {("pvehicle", "c"): ("CHIRON", "FORDGT")}


def test_model_without_a_visual_line_takes_the_collision_name():
    lines = ["update_field pvehicle c MODEL Collision X"]
    assert nfsms.translate(lines, SHAPES) == ["update_field pvehicle c MODEL X"]


def test_writes_past_a_shrunk_array_are_left_out():
    # The Tomahawk shrinks GEAR_RATIO to 4 (a 2-speed bike) and then zeroes entries 4-7 that no longer exist; VltEd
    # ignores those, Attribulator stops ("out of bounds")
    lines = ["resize_field transmission t GEAR_RATIO 4", "update_field transmission t GEAR_RATIO[3] 1.3",
             "update_field transmission t GEAR_RATIO[4] 0", "update_field transmission t GEAR_RATIO[7] 0",
             "update_field transmission u GEAR_RATIO[7] 0"]
    assert nfsms.drop_past_resized(lines) == [
        "resize_field transmission t GEAR_RATIO 4", "update_field transmission t GEAR_RATIO[3] 1.3",
        "update_field transmission u GEAR_RATIO[7] 0"]
