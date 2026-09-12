# Media protection: the contract check

!!! danger "Modified firmware is blocked on tested hardware"

    On a Peugeot 208 with SMEG+ iV1 running `SMEG5.43.A.R2`, a package with a patched
    `AppBin/f_BigQuick.bin` is **rejected** with
    *"The update file is protected and cannot be copied."* (string id 2099).
    The unmodified package — which contained the `/contract.dat` below — was accepted.

    The device validates the media against a cryptographically signed contract, and that
    contract describes the *original* files. So the application patches in this
    repository **cannot currently be flashed**. See issue #51.

## Where the message comes from

String id **2099** in `gui_text_strings_GB.xml.bin` (media partition,
`Data_base/boardfs/GUI_STYLE/GUIS_RESSOURCES/gui_texts/`) reads:

> The update file is protected and cannot be copied.

It is emitted from the contract-validation path in the **application image**, not from a
file-copy failure:

```
C_BCM_UPGRADE::CheckTrustedSource(C_BCM_UPGRADE*)      @ 0x0187775c
```

The messages it logs name the mechanism exactly:

```
(C_BCM_UPGRADE) CheckTrustedSourcetype +
(C_BCM_UPGRADE) CheckTrustedSourcetype : File path is '%s'
(C_BCM_UPGRADE) CheckTrustedSourcetype : Offset is %lu
(C_BCM_UPGRADE) CheckTrustedSourcetype : Size is %lu
(C_BCM_UPGRADE) CheckTrustedSourcetype : value_to_check is %lu
(C_BCM_UPGRADE) CheckTrustedSourcetype open Crypto file Succed
(C_BCM_UPGRADE) CheckTrustedSourcetype : l_array_contract_data is null
(C_BCM_UPGRADE) CheckTrustedSourcetype : Send message MSG_BCM_UPGRADE_KNOWN_KEY_INSERTED
(C_BCM_UPGRADE) CheckTrustedSourcetype : Send message MSG_BCM_UPGRADE_ILLEGAL_MEDIA
```

## What it does

```
CheckTrustedSource()
  m_abort_contract_checking = 0                       # this+0x1d3
  path = m_media_path + "/contract.dat"               # read from the MEDIA, not the unit
  open it                                            # "open Crypto file Succed"
  RsaHeaderDecrypt(buf, 0x100)      -> 152 bytes (0x98) into this+0x22c
  RsaReadDataBlockDecrypt(...)      -> 212 bytes (0xd4) records into this+0x2c4
  compare  File path / Offset / Size / value_to_check  -> l_array_contract_data
  pass  -> MSG_BCM_UPGRADE_KNOWN_KEY_INSERTED
  fail  -> MSG_BCM_UPGRADE_ILLEGAL_MEDIA   (the user sees 2099)
```

So the **media supplies the contract**, the unit decrypts it locally, and validates some
set of files against it. The `(path, offset, size, value)` tuple strongly implies a
per-file list with hashes — but see "What is not known" below.

There is also an abort path: if `m_abort_contract_checking` (this+`0x1d3`) is non-zero,
the check logs
`*** (C_BCM_UPGRADE) CheckTrustedSourcetype -> false == p_Instance->m_abort_contract_checking ***`
and treats the media as trusted. That flag is only ever set to 1 from
`C_BCM_UPGRADE::HandlePrivateMessage`, gated on a dynamic context value
(`C_CONTEXT_DYNAMIC_DATA::Get(0x4651, ...)` compared against 4/2/5/8) — internal phase
state, not a user-visible switch.

## The key material

`C_ENG_CRYPTO` (`C1(const char*, ...)` taking five strings) is constructed from literals
embedded in the application image as **plain decimal integers**. Two complete RSA-2048
key pairs are present:

```
n  2048-bit   (617 decimal digits)
e  65537
d  2046-bit   (616 decimal digits)
p  1024-bit   (309 decimal digits)
q  1024-bit   (309 decimal digits)

n == p * q verified;  d * e == 1 mod lambda(n) verified
```

Addresses (application image, `AUDIO_BT`; the NAV build has its own copies).

!!! warning "Not reproduced here"

    The key values are deliberately **not** included in this repository or in this
    document — only their location and structure. They are the vendor's signing key
    material; publishing them would enable forgery against any device using the same
    key, which is not a call this project should make on the owner's behalf.

`C_ENG_CRYPTO` also exposes `RsaEncrypt` / `RsaDecrypt` (string-based) alongside the
buffer forms used above, so both directions are implemented on the device.

## Why a patched package fails

- The stock package was accepted on this unit, so the contract was present, decrypted and
  validated successfully for the *original* content.
- Our patch changes 4 bytes in `AppBin/f_BigQuick.bin` and therefore its crc32, its
  `.inf`, `smeg.inf`, `<module>_ctrl.bin` and the root `ctrl.bin`.
- Any binding that covers the application image — or the package by digest — no longer
  matches, and the check returns illegal media.

The unit is behaving exactly as designed: it refuses to flash firmware it cannot verify.

## What is not known

- **The contract's internal format.** Both keys, both exponents, big- and little-endian
  framing and every output window were tried against `contract.dat`
  (29 696 bytes = 116 × 256, and also a multiple of 128); decryption produced no PKCS#1
  padding in either direction and no structured plaintext. It is therefore most likely
  **hybrid** (RSA-wrapped key plus a symmetric payload) — the layout is not yet reversed.
- **Which files the contract covers.** The decrypted header is only 152 bytes, so it is
  metadata rather than a file list; the 212-byte records look like the per-file entries,
  but their contents have not been read.
- **Whether the check runs before or after the package is copied to the unit.** The
  strings suggest validation precedes copying, which creates a chicken-and-egg for any
  attempt to patch the check out.
- **The `CheckType` byte (0–3)** in the `*_ctrl.bin` manifests remains unexplained, as
  elsewhere in these notes.

## Options, in order of promise

1. **Reverse the contract format** so a modified package can be re-signed. Needs
   `C_ENG_CRYPTO::RsaDecrypt` and the 152-byte header layout worked out. Open-ended;
   no guarantee.
2. **Find a route that does not run the check.** The updater mentions
   *"BSP Not compatible. Please use the loader button..."* — a loader/recovery mode that
   may accept media through a different path. Also note the check requires
   `m_abort_contract_checking` to be *set*, and the check runs before any copy, so a
   media-side bypass is unlikely.
3. **Accept it**: the application patches are not flashable on this unit as things stand,
   and the AUX source must be changed manually.

Related: issue #51.
