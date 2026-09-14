"""Helpers for building a synthetic SMEG+ package.

Everything here is generated from scratch — no vendor firmware is involved, which is
the point: the patch tools must be testable without any copyrighted files.
"""

import gzip
import io
import os
import re
import struct
import tarfile
import zlib
from pathlib import Path

BASE = 0x01000000
STREAM_OFFSET = 0x801  # where the zlib stream starts
HEADER_LEN = 0x800  # the byte at 0x800 is the 0x08 compression marker


def crc32(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def s32(v):
    return struct.unpack(">i", struct.pack(">I", v))[0]


def make_image(size=0x200000, fill=0xAA):
    """A fake application image, sized like a real one (>1 MB, which the tools require)."""
    img = bytearray([fill]) * size
    img[0x100:0x104] = bytes.fromhex("9421ffa0")  # stwu r1,-0x60(r1)
    img[0x104:0x108] = bytes.fromhex("7c0802a6")  # mflr r0
    return bytes(img)


def pack_bigquick(img, header_len=HEADER_LEN):
    """0x800-byte header + the 0x08 marker + a zlib stream starting at 0x801."""
    header = bytearray(header_len)
    header[0:4] = struct.pack(">I", 0x00010004)
    header[4:8] = struct.pack(">I", len(img))
    for off in (0x1C, 0x3C):
        header[off : off + 4] = b"\xde\xad\xbe\xef"
    return bytes(header) + b"\x08" + zlib.compress(img, 6)


def write_inf(path, crc):
    with open(path, "wb") as fh:
        fh.write(("CRC32: %d\r\n" % s32(crc)).encode())


def write_smeg_inf(path, bigquick_crc, ver="SMEG0.0.0.A.R0", gui_ver="00.00"):
    with open(path, "wb") as fh:
        fh.write(
            (
                "BSP_CRC32: 0 \r\n"
                "BIGQUICK_CRC32: %d \r\n"
                "VER: %s \r\n"
                "GUI_VER:%s \r\n" % (s32(bigquick_crc), ver, gui_ver)
            ).encode()
        )


def write_ctrl(path, entries):
    """entries: list of (check_type, crc32, path)."""
    out = bytearray()
    out += b"19/09/2017  2.1.0.0".ljust(0x30, b"\x00")
    out += bytes([len(entries)])
    for check, crc, rel in entries:
        out += bytes([check])
        out += struct.pack(">I", crc)
        out += rel.encode() + b"\x00"
        out += b"\x00" * ((-len(rel) - 1) % 8)  # pad to a stride
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def build_package(root, variant="NAV", patch_addr=0x100, img=None):
    """Create a minimal package containing one variant. Returns a dict of paths."""
    img = img if img is not None else make_image()
    mod = os.path.join(root, variant)
    appbin = os.path.join(mod, "AppBin")
    os.makedirs(appbin, exist_ok=True)

    bq = pack_bigquick(img)
    bq_path = os.path.join(appbin, "f_BigQuick.bin")
    inf_path = os.path.join(appbin, "f_BigQuick.bin.inf")
    smeg_path = os.path.join(mod, "smeg.inf")
    ctrl_path = os.path.join(root, "%s_ctrl.bin" % variant)

    Path(bq_path).write_bytes(bq)
    write_inf(inf_path, crc32(bq))
    write_smeg_inf(smeg_path, crc32(bq))

    write_ctrl(
        ctrl_path,
        [
            (1, crc32(bq), "/%s/AppBin/f_BigQuick.bin" % variant),
            (1, crc32(Path(inf_path).read_bytes()), "/%s/AppBin/f_BigQuick.bin.inf" % variant),
            (1, crc32(Path(smeg_path).read_bytes()), "/%s/smeg.inf" % variant),
        ],
    )
    write_ctrl(
        os.path.join(root, "ctrl.bin"),
        [
            (1, crc32(Path(ctrl_path).read_bytes()), "/%s_ctrl.bin" % variant),
        ],
    )

    return {
        "variant": variant,
        "app_image": bq_path,
        "inf": inf_path,
        "smeg_inf": smeg_path,
        "ctrl": ctrl_path,
        "image": img,
        "patch_addr": patch_addr,
    }


def set_root_ctrl(root, variants):
    """(Re)write the root manifest listing the given variants' module manifests."""
    entries = []
    for v in variants:
        p = os.path.join(root, "%s_ctrl.bin" % v)
        entries.append((1, crc32(Path(p).read_bytes()), "/%s_ctrl.bin" % v))
    write_ctrl(os.path.join(root, "ctrl.bin"), entries)


def make_image_with_build(version, size=0x200000):
    """A fake image carrying a vendor build path, as the real ones do.

    The version token is what patch_smeg.py's firmware guard looks for.
    """
    img = bytearray(make_image(size))
    token = ("E:/ccm_wa71/04_HMI_DEV-%s/04_HMI_DEV/MMI/" % version).encode("latin1")
    img[0x8000 : 0x8000 + len(token)] = token
    return bytes(img)


def patch_spec(
    variant="NAV", addr=0x100, base=0x0, expect="9421ffa0", new="386000014e800020", firmware=None
):
    spec = {
        "app_image": "%s/AppBin/f_BigQuick.bin" % variant,
        "inf": "%s/AppBin/f_BigQuick.bin.inf" % variant,
        "smeg_inf": "%s/smeg.inf" % variant,
        "ctrl": "%s_ctrl.bin" % variant,
        "base": hex(base),
        "patches": [{"addr": hex(addr), "expect": expect, "bytes": new}],
    }
    if firmware is not None:
        spec["firmware"] = firmware
    return {"name": "synthetic", "variants": {variant: spec}}


def inflate_container(raw):
    d = zlib.decompressobj()
    out = d.decompress(raw[STREAM_OFFSET:])
    return out + d.flush()


def read_crc_field(text, field="CRC32"):
    m = re.search((field + r": (-?\d+)").encode(), text)
    return int(m.group(1)) & 0xFFFFFFFF


# --- media partition helper (for the ringtone tool tests) -------------------


def build_media_tar(path, extra=None):
    """A tar shaped like the real media partition, with ring_tones/ populated."""
    import wave

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name in ("Data_base/media.inf", "Data_base/smeg.inf"):
            data = (
                b"00000000\nVER:0\n"
                if "media" in name
                else b"BSP_CRC32: 0 \r\nBIGQUICK_CRC32: 0 \r\nVER: X \r\nGUI_VER:00.00 \r\n"
            )
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for slot in ("ring1", "ring2"):
            w = io.BytesIO()
            with wave.open(w, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(b"\x00\x00" * 4410)
            data = w.getvalue()
            ti = tarfile.TarInfo("ring_tones/%sRT.wav" % slot)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    Path(path).write_bytes(gzip.compress(buf.getvalue()))
