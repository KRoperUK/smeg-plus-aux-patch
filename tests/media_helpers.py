import io
import os
import struct
import tarfile
import wave
import zlib

# --- media partition (for patch_media.py) ----------------------------------

CTRL_RECORD = 264          # system_ctrl.bin record stride
CTRL_CRC_OFF = 260
CTRL_HEADER = 0x30


def s32(v):
    return struct.unpack(">i", struct.pack(">I", v))[0]


def wav_bytes(channels=1, rate=44100, frames=441):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * frames)
    return buf.getvalue()


def roundup(v, b):
    return (v + b - 1) // b * b


def build_system_ctrl(files):
    """264-byte records: [path][pad][type][crc32], preceded by a 0x30-byte header."""
    out = bytearray(b"19/09/2017\x00\x002.1.0.0".ljust(CTRL_HEADER, b"\x00"))
    for name, data in files.items():
        rec = bytearray(CTRL_RECORD)
        path = ("/SYSTEM/" + name).encode()
        rec[0:len(path)] = path
        rec[259] = 2
        struct.pack_into(">I", rec, CTRL_CRC_OFF, zlib.crc32(data) & 0xFFFFFFFF)
        out += rec
    return bytes(out)


def build_media_package(root, module="NAV", extra_constant=True):
    """A minimal but structurally faithful media partition.

    `extra_constant` adds the same unexplained offset the vendor's SIZE_1/2/4 carry,
    so the tests prove the patcher preserves those values rather than recomputing them.
    """
    files = {
        "Data_base/media.inf": b"00000000\nVER:0\n",
        "Data_base/smeg.inf": b"BSP_CRC32: 0 \r\nVER: X \r\nGUI_VER:00.00 \r\n",
        "ring_tones/ring1RT.wav": wav_bytes(frames=441),
        "ring_tones/ring2RT.wav": wav_bytes(frames=882),
        "wait_tones/MM_HoldOn_ENG_8kHz.wav": wav_bytes(channels=2, rate=8000, frames=800),
    }

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
    tar_bytes = buf.getvalue()
    bin_bytes = __import__("gzip").compress(tar_bytes, 6)

    mod_dir = os.path.join(root, module)
    os.makedirs(mod_dir, exist_ok=True)
    open(os.path.join(mod_dir, "system.bin"), "wb").write(bin_bytes)

    sizes = {"SIZE": sum(len(v) for v in files.values())}
    for n in (1, 2, 4, 8, 16, 32):
        v = sum(roundup(len(x), n * 1024) for x in files.values())
        if extra_constant:
            v += {1: 29696, 2: 18432, 4: 8192}.get(n, 0)
        sizes["SIZE_%d" % n] = v
    lines = ["CRC32: %d" % s32(zlib.crc32(bin_bytes) & 0xFFFFFFFF)]
    lines += ["%s: %d" % (k, v) for k, v in sizes.items()]
    open(os.path.join(mod_dir, "system.bin.inf"), "wb").write(
        ("\r\n".join(lines) + "\r\n").encode())

    ctrl = build_system_ctrl(files)
    open(os.path.join(mod_dir, "system_ctrl.bin"), "wb").write(ctrl)

    # module + root manifests (same shape as ctrl.bin: header, count, records)
    def manifest(entries):
        out = bytearray(b"19/09/2017  2.1.0.0".ljust(CTRL_HEADER, b"\x00"))
        out += bytes([len(entries)])
        for check, crc, path in entries:
            out += bytes([check]) + struct.pack(">I", crc) + path.encode() + b"\x00"
        return bytes(out)

    mod_ctrl_path = os.path.join(root, "%s_ctrl.bin" % module)
    mod_ctrl = manifest([
        (1, zlib.crc32(bin_bytes) & 0xFFFFFFFF, "/%s/system.bin" % module),
        (1, zlib.crc32(open(os.path.join(mod_dir, "system.bin.inf"), "rb").read()) & 0xFFFFFFFF,
         "/%s/system.bin.inf" % module),
        (1, zlib.crc32(ctrl) & 0xFFFFFFFF, "/%s/system_ctrl.bin" % module),
    ])
    open(mod_ctrl_path, "wb").write(mod_ctrl)
    open(os.path.join(root, "ctrl.bin"), "wb").write(manifest([
        (1, zlib.crc32(mod_ctrl) & 0xFFFFFFFF, "/%s_ctrl.bin" % module),
    ]))

    return {"module": module, "files": files, "tar": tar_bytes, "bin": bin_bytes,
            "ctrl": ctrl, "sizes": sizes}
