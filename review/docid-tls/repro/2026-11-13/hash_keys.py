#!/usr/bin/env python3
"""Extract real docstore block offsets and add structured integer-key controls."""
import argparse
from pathlib import Path
import struct


def offsets(data):
    version, blocksize = struct.unpack_from("<II", data)
    assert version == 1 and blocksize > 0
    pos = 9
    fields, = struct.unpack_from("<I", data, pos)
    pos += 4
    for _ in range(fields):
        pos += 1
        length, = struct.unpack_from("<I", data, pos)
        pos += 4 + length
        assert pos <= len(data)
    count, footer = struct.unpack_from("<IQ", data, pos)
    header_end = pos + 12
    assert header_end <= footer <= len(data)
    pos = footer

    def varint():
        nonlocal pos
        value = 0
        for _ in range(10):
            b = data[pos]
            pos += 1
            value = (value << 7) | (b & 127)
            if b < 128:
                return value
        raise ValueError("docstore footer varint exceeds 10 bytes")

    row, offset, result = 0, 0, []
    for _ in range(count):
        row += varint()
        kind = data[pos]
        pos += 1
        assert kind in (0, 1)
        offset += varint()
        if kind == 1:
            varint()
        assert header_end <= offset < footer
        assert not result or offset > result[-1][1]
        result.append((row, offset))
    assert pos == len(data)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        header = struct.pack("<IIBIBI4sIQ", 1, 16384, 1, 1, 0, 4, b"body", 2, 100)
        assert offsets(header + bytes(100-len(header)) + bytes([0, 0, 40, 2, 0, 20])) == [(0, 40), (2, 60)]
        print("docstore offset parser selfcheck passed")
        return
    assert args.fixtures and args.output
    with args.output.open("w") as out:
        for n in (20000, 1000000, 5000000):
            files = sorted((args.fixtures / f"fixture-{n}" / "data").rglob("*.spds"))
            assert files
            for index, file in enumerate(files, 1):
                for _, offset in offsets(file.read_bytes()):
                    out.write(f"fixture-{n} {index} {offset}\n")
        for n, stride, label in [(8192, 16384, "aligned-16k"), (64, 16384, "hot64-aligned-16k"), (8192, 512, "stride-512")]:
            for i in range(n):
                out.write(f"{label} 1 {i*stride}\n")


if __name__ == "__main__":
    main()
