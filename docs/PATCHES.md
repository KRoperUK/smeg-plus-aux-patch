# Patch definitions

Base address for the inflated application image is `0x01000000`. Offsets below are
absolute addresses in that image; the tool converts to a file offset with
`offset = addr - 0x01000000`.

## 1. `C_HMI_AUDIO_APP_BASE::IsAUXSRCAvailable()` — force available

Replaces the function prologue with `li r3,1 ; blr`, so AUX is reported available
regardless of vehicle config / signal. Consequence: the AUX source stays selectable and
no longer greys out when there is no signal.

| build | address | original | patched |
|---|---|---|---|
| `AUDIO_BT`, `AUDIO_BT_256` | `0x02247718` | `94 21 ff a0` (`stwu r1,-0x60(r1)`) | `38 60 00 01 4e 80 00 20` (`li r3,1 ; blr`) |
| `NAV` | `0x02247858` | `94 21 ff a0` | `38 60 00 01 4e 80 00 20` |

```
li   r3, 1        # 0x38600001
blr               # 0x4e800020
```

## 2. `C_HMI_MEDIA_APP_BASE::HandleAudioAuxInputStatusChnged()` — remove early exit

At `handler + 0x10c` the function bails out when `GetMediaDevice(AUX)` fails, before it
reaches `ActivateSource()`. Replace the conditional branch with `nop` so execution
continues into the `SetMediaDeviceState` / `ActivateSource` path.

| build | handler | branch address | original | patched |
|---|---|---|---|---|
| `AUDIO_BT`, `AUDIO_BT_256` | `0x023031dc` | `0x023032e8` | `41 9e 01 4c` (`beq cr7,+0x14c`) | `60 00 00 00` (`nop`) |
| `NAV` | `0x0230331c` | `0x02303428` | `41 9e 01 4c` | `60 00 00 00` (`nop`) |

The branch target (`handler + 0x258`) is the shared return path for the "nothing to do"
cases; the patched fall-through runs:

```
SetMediaDeviceState(AUX, state = 2)
if (this->srcMgr) C_HMI_SrcMgntBase::ActivateSource(true)
```

## Resulting file checksums

Because the compressed stream is rebuilt, the resulting `f_BigQuick.bin` CRCs depend on
the zlib implementation/level and are not stable values to match against. Recompute them
with the tooling and propagate through the cascade (the tool does this automatically).

## Adding your own patches

`patches/*.json` is data-driven:

```json
{
  "variants": {
    "NAV": {
      "app_image": "NAV/AppBin/f_BigQuick.bin",
      "inf": "NAV/AppBin/f_BigQuick.bin.inf",
      "smeg_inf": "NAV/smeg.inf",
      "ctrl": "NAV_ctrl.bin",
      "base": "0x01000000",
      "patches": [
        { "addr": "0x02247858", "expect": "9421ffa0", "bytes": "386000014e800020", "why": "..." }
      ]
    }
  }
}
```

`expect` is checked before writing, so a mismatched firmware build fails loudly instead of
being corrupted.
