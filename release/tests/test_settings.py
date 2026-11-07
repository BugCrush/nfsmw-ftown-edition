"""settings.py: one value changed, everything else kept (spacing, comment column, line endings)."""
from ftedition import settings

WSF = (b"[MAIN]\r\nResX = 0                                 ; Use this option\r\nResY = 0\r\n"
       b"[GRAPHICS]\r\nShadowsRes = 2048                        ; Controls\r\n")


def test_value_replaced_comment_column_kept():
    out, ok = settings.set_value(WSF, "MAIN", "ResX", "1920")
    assert ok
    assert b"\r\nResX = 1920                              ; Use this option\r\n" in out, out
    assert out.replace(b"ResX = 1920                              ;", b"ResX = 0                                 ;") == WSF


def test_section_respected_and_lf_kept():
    lf = b"[A]\nKey = 1\n[B]\nKey = 1\n"
    out, ok = settings.set_value(lf, "B", "Key", "0.17")
    assert ok and out == b"[A]\nKey = 1\n[B]\nKey = 0.17\n", out


def test_missing_key_reported():
    out, missing = settings.apply(WSF, {"MAIN": {"Nope": "1", "ResY": "1080"}, "_default": "x"})
    assert missing == ["MAIN/Nope"] and b"ResY = 1080\r\n" in out

