import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "tools", "fix_userdata_case.py")


def lfn(name):
    chars = [ord(c) for c in name] + [0] + [0xFFFF] * (12 - len(name))
    entry = bytearray(32)
    entry[0] = 0x41
    entry[11] = 0x0F
    entry[13] = 0
    entry[1:11] = b"".join(struct.pack("<H", c) for c in chars[:5])
    entry[14:26] = b"".join(struct.pack("<H", c) for c in chars[5:11])
    entry[28:32] = b"".join(struct.pack("<H", c) for c in chars[11:13])
    return bytes(entry)


def directory(short, cluster, name=None, nt=0):
    entry = bytearray(32)
    entry[:11] = short.ljust(11).encode()
    entry[11] = 0x10
    entry[12] = nt
    entry[20:22] = struct.pack("<H", cluster >> 16)
    entry[26:28] = struct.pack("<H", cluster & 0xFFFF)
    return (lfn(name) if name else b"") + bytes(entry) + bytes(32)


def fat32(path, sqlite_name=None, lowercase_short=False):
    data = bytearray(7 * 512)
    boot = memoryview(data)[:512]
    boot[0x0B:0x0D] = struct.pack("<H", 512)
    boot[0x0D] = 1
    boot[0x0E:0x10] = struct.pack("<H", 1)
    boot[0x10] = 1
    boot[0x24:0x28] = struct.pack("<I", 1)
    boot[0x2C:0x30] = struct.pack("<I", 2)
    boot[0x52:0x5A] = b"FAT32   "
    boot[510:512] = b"\x55\xaa"
    for cluster in range(2, 7):
        data[512 + cluster * 4 : 512 + cluster * 4 + 4] = struct.pack("<I", 0x0FFFFFFF)
    data[1024:1536] = directory("SMEG_P~1", 3, "SMEG_PLUS_UPG").ljust(512, b"\0")
    data[1536:2048] = directory("NAV", 4).ljust(512, b"\0")
    data[2048:2560] = directory("USER_D~1", 5, "USER_DATA").ljust(512, b"\0")
    data[2560:3072] = directory("USER_D~1", 6, "user_data").ljust(512, b"\0")
    if sqlite_name:
        item = directory("SQLITE~1", 7, sqlite_name)
    else:
        item = directory("SQLITE", 7, nt=0x08 if lowercase_short else 0)
    data[3072:3584] = item.ljust(512, b"\0")
    path.write_bytes(data)


def run(path, *flags):
    return subprocess.run(
        [sys.executable, TOOL, *flags, str(path)], capture_output=True, text=True
    )


def test_check_accepts_exact_lowercase_long_filename(tmp_path):
    image = tmp_path / "fat.img"
    fat32(image, sqlite_name="sqlite")

    result = run(image, "--check")

    assert result.returncode == 0, result.stderr
    assert "OK: FAT long-filename entry is exactly 'sqlite'" in result.stdout


def test_check_rejects_short_name_even_with_lowercase_flag(tmp_path):
    image = tmp_path / "fat.img"
    fat32(image, lowercase_short=True)

    result = run(image, "--check")

    assert result.returncode != 0
    assert "NOT SAFE" in result.stderr
    assert "SQLITE" in result.stdout


def test_rewrite_changes_only_the_long_filename(tmp_path):
    image = tmp_path / "fat.img"
    fat32(image, sqlite_name="sqlite_dat")
    before = image.read_bytes()

    result = run(image)

    assert result.returncode == 0, result.stderr
    after = image.read_bytes()
    changed = [i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    assert changed
    assert max(changed) - min(changed) < 32
    assert run(image, "--check").returncode == 0


def test_dry_run_writes_nothing(tmp_path):
    image = tmp_path / "fat.img"
    fat32(image, sqlite_name="sqlite_dat")
    before = image.read_bytes()

    result = run(image, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert image.read_bytes() == before
    assert "dry run: nothing written" in result.stdout
