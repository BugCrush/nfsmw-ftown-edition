"""Lettering for F-Town's drawn textures: text drawn by Windows' own GDI (ctypes), so Devanagari is shaped by the
system (matras placed, conjuncts joined, one head line), which Pillow here cannot do (no raqm). Fonts are the
machine's: "Nirmala UI" for Hindi, "Arial", "Georgia", "Impact", "Segoe Script" and the like for Latin.

- mask(text, font, px, weight, italic): the text's ink as float32 alpha 0..1, cropped to the ink, drawn at 4 x the size
  without anti-aliasing and box-filtered down (the same pixels every run).
- draw(img, text, box, rgb, ...): fits the text into a pixel box of an (h, w, 3) float image and blends it in.

Windows only (the city builder's machine).
"""
import ctypes
from ctypes import wintypes as W

import numpy as np

SS = 4  # supersampling
_gdi = ctypes.WinDLL("gdi32")
_user = ctypes.WinDLL("user32")
_gdi.CreateCompatibleDC.restype = W.HDC
_gdi.CreateCompatibleDC.argtypes = [W.HDC]
_gdi.CreateFontW.restype = W.HFONT
_gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]
_gdi.SelectObject.restype = W.HGDIOBJ
_gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
_gdi.CreateDIBSection.restype = W.HBITMAP
_gdi.CreateDIBSection.argtypes = [W.HDC, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p), W.HANDLE,
                                  W.DWORD]
_gdi.DeleteObject.argtypes = [W.HGDIOBJ]
_gdi.DeleteDC.argtypes = [W.HDC]
_gdi.SetTextColor.argtypes = [W.HDC, W.DWORD]
_gdi.SetBkMode.argtypes = [W.HDC, ctypes.c_int]
_user.DrawTextW.argtypes = [W.HDC, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT), W.UINT]
DT_SINGLELINE, DT_CALCRECT, DT_NOPREFIX = 0x20, 0x400, 0x800
NONANTIALIASED_QUALITY = 3


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class _LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", W.LONG), ("lfWidth", W.LONG), ("lfEscapement", W.LONG), ("lfOrientation", W.LONG),
                ("lfWeight", W.LONG), ("lfItalic", W.BYTE), ("lfUnderline", W.BYTE), ("lfStrikeOut", W.BYTE),
                ("lfCharSet", W.BYTE), ("lfOutPrecision", W.BYTE), ("lfClipPrecision", W.BYTE),
                ("lfQuality", W.BYTE), ("lfPitchAndFamily", W.BYTE), ("lfFaceName", W.WCHAR * 32)]


_ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, W.DWORD, W.LPARAM)
_gdi.EnumFontFamiliesExW.argtypes = [W.HDC, ctypes.POINTER(_LOGFONTW), _ENUMPROC, W.LPARAM, W.DWORD]
DEFAULT_CHARSET = 1
_cache = {}
_installed = {}


def installed(face):
    """True when a font family of this face name is installed (GDI's EnumFontFamiliesExW: exact family names; GDI
    itself would silently draw a missing face in a substitute)."""
    if face not in _installed:
        found = []
        lf = _LOGFONTW()
        lf.lfCharSet = DEFAULT_CHARSET
        lf.lfFaceName = face[:31]
        dc = _gdi.CreateCompatibleDC(None)
        cb = _ENUMPROC(lambda *_a: found.append(1) or 0)  # stop at the first match
        _gdi.EnumFontFamiliesExW(dc, ctypes.byref(lf), cb, 0, 0)
        _gdi.DeleteDC(dc)
        _installed[face] = bool(found)
    return _installed[face]


def _raw(text, font, px, weight, italic):
    """uint8 ink of the text at px pixels (GDI's em height), uncropped; ValueError when the font is not installed
    (the review: Devanagari in a substitute font is boxes)."""
    if not installed(font):
        raise ValueError("font not installed: %r (lettering for the drawn textures)" % font)
    dc = _gdi.CreateCompatibleDC(None)
    f = _gdi.CreateFontW(-px, 0, 0, 0, weight, int(italic), 0, 0, 1, 0, 0, NONANTIALIASED_QUALITY, 0, font)
    old_font = _gdi.SelectObject(dc, f)
    r = W.RECT(0, 0, 0, 0)
    _user.DrawTextW(dc, text, -1, ctypes.byref(r), DT_CALCRECT | DT_SINGLELINE | DT_NOPREFIX)
    pad = px // 2 + 4
    w, h = r.right + 2 * pad, r.bottom + 2 * pad
    bi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bm = _gdi.CreateDIBSection(dc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
    old = _gdi.SelectObject(dc, bm)
    ctypes.memset(bits, 0, w * h * 4)
    _gdi.SetBkMode(dc, 1)
    _gdi.SetTextColor(dc, 0xFFFFFF)
    rr = W.RECT(pad, pad, w - pad, h - pad)
    _user.DrawTextW(dc, text, -1, ctypes.byref(rr), DT_SINGLELINE | DT_NOPREFIX)
    buf = (ctypes.c_uint8 * (w * h * 4)).from_address(bits.value)
    a = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[..., 1].copy()
    _gdi.SelectObject(dc, old)
    _gdi.DeleteObject(bm)
    _gdi.SelectObject(dc, old_font)  # a font still selected into a DC is not deleted (one GDI handle leaked a text)
    _gdi.DeleteObject(f)
    _gdi.DeleteDC(dc)
    return a


def mask(text, font="Arial", px=64, weight=700, italic=False):
    """float32 alpha (h, w) of the text's ink, cropped to it (module doc)."""
    key = (text, font, px, weight, italic)
    if key in _cache:
        return _cache[key].copy()
    a = _raw(text, font, px * SS, weight, italic)
    ys, xs = np.nonzero(a)
    if not len(xs):
        out = np.zeros((1, 1), dtype=np.float32)
    else:
        y0, y1 = (ys.min() // SS) * SS, -(-(ys.max() + 1) // SS) * SS
        x0, x1 = (xs.min() // SS) * SS, -(-(xs.max() + 1) // SS) * SS
        c = (a[y0:y1, x0:x1] > 127).astype(np.float32)
        h, w = c.shape[0] // SS, c.shape[1] // SS
        out = c.reshape(h, SS, w, SS).mean((1, 3)).astype(np.float32)
    _cache[key] = out
    return out.copy()


def _resize(m, h, w):
    """Box/bilinear resize of a float mask (Pillow, mode F)."""
    from PIL import Image
    im = Image.fromarray(m, mode="F").resize((max(1, w), max(1, h)), Image.Resampling.BOX if
                                            (h < m.shape[0] and w < m.shape[1]) else Image.Resampling.BILINEAR)
    return np.clip(np.asarray(im, dtype=np.float32), 0.0, 1.0)


def draw(img, text, box, rgb, font="Arial", weight=700, italic=False, align="center", stretch=False):
    """Fits the text into box (x0, y0, x1, y1, pixels of img) at its height, shrunk to its width (or stretched to
    fill it), and blends rgb into img by the ink (img: (h, w, 3) float, changed in place)."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    bw, bh = x1 - x0, y1 - y0
    if bw <= 0 or bh <= 0:
        return
    m = mask(text, font, max(8, bh * 2), weight, italic)
    k = bh / m.shape[0]
    w = m.shape[1] * k
    h = bh
    if stretch or w > bw:
        if stretch:
            w = bw
        else:
            k2 = bw / w
            w, h = bw, max(1, int(round(bh * k2)))
    w, h = max(1, int(round(w))), max(1, int(round(h)))
    r = _resize(m, h, w)
    ox = x0 + (0 if align == "left" else (bw - w) if align == "right" else (bw - w) // 2)
    oy = y0 + (bh - h) // 2
    ys0, xs0 = max(0, oy), max(0, ox)
    ys1, xs1 = min(img.shape[0], oy + h, y1), min(img.shape[1], ox + w, x1)
    if ys1 <= ys0 or xs1 <= xs0:
        return
    a = r[ys0 - oy:ys1 - oy, xs0 - ox:xs1 - ox][..., None]
    img[ys0:ys1, xs0:xs1] = img[ys0:ys1, xs0:xs1] * (1 - a) + np.asarray(rgb, dtype=float)[None, None, :] * a
