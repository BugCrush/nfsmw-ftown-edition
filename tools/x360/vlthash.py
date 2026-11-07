"""The attribute database's 32-bit name hash (Bob Jenkins' lookup2, initial value 0xABCDEF00).

Usage: python vlthash.py <name> ...
"""
import sys

M = 0xFFFFFFFF


def mix(a, b, c):
    a = (a - b - c) & M; a ^= c >> 13
    b = (b - c - a) & M; b ^= (a << 8) & M
    c = (c - a - b) & M; c ^= b >> 13
    a = (a - b - c) & M; a ^= c >> 12
    b = (b - c - a) & M; b ^= (a << 16) & M
    c = (c - a - b) & M; c ^= b >> 5
    a = (a - b - c) & M; a ^= c >> 3
    b = (b - c - a) & M; b ^= (a << 10) & M
    c = (c - a - b) & M; c ^= b >> 15
    return a, b, c


def vlt32(text, init=0xABCDEF00):
    k = text.encode("ascii")
    a = b = 0x9E3779B9
    c = init
    i, n = 0, len(k)
    while n - i >= 12:
        a = (a + int.from_bytes(k[i:i + 4], "little")) & M
        b = (b + int.from_bytes(k[i + 4:i + 8], "little")) & M
        c = (c + int.from_bytes(k[i + 8:i + 12], "little")) & M
        a, b, c = mix(a, b, c)
        i += 12
    c = (c + len(k)) & M
    rest = k[i:]
    for j, byte in enumerate(rest):
        if j < 4:
            a = (a + (byte << (8 * j))) & M
        elif j < 8:
            b = (b + (byte << (8 * (j - 4)))) & M
        else:
            c = (c + (byte << (8 * (j - 8 + 1)))) & M
    a, b, c = mix(a, b, c)
    return c


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print("0x%08X %s" % (vlt32(name), name))
