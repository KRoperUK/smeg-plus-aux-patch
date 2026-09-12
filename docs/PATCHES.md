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

## Patch sets in this repository

| file | what it changes | status |
|---|---|---|
| `patches/aux-autoswitch.json` | `IsAUXSRCAvailable()` true **and** removes the `GetMediaDevice` bail-out | the combined build — flashed successfully, first patch confirmed on hardware |
| `patches/aux-always-available.json` | `IsAUXSRCAvailable()` true only — AUX stops greying out | behavioural, no switching |
| `patches/aux-sticky.json` | removes the bail-out **and** turns "signal absent" into a no-op | candidate, untested |
| `patches/diagnostic-logging.json` | redirects the logging stub to the real logger | diagnostic build, **not for driving** |

!!! note "Hardware status"

    The combined build has been flashed to a real unit and accepted by the media contract
    check. The `IsAUXSRCAvailable()` change is confirmed working: AUX no longer greys out
    and is back in the SRC cycle. The **auto-switch has not been observed working yet** —
    see [Hardware verification](VERIFICATION.md).

### `diagnostic-logging` — a diagnostic, not a fix

The application's logging is compiled in but stubbed out. Every log call site tests a global
and, when logging is off, calls `dummyLogMsg` instead of `Log_msg`. `dummyLogMsg` at
`0x010346d0` is literally:

```
010346d0  li  r3, 0
010346d4  blr
```

So replacing that one instruction with a branch to the real logger:

| build | address | original | patched |
|---|---|---|---|
| `NAV` | `0x010346d0` | `38 60 00 00` (`li r3,0`) | `49 70 de 88` (`b 0x02742558`) |

makes **every** gated log call in the image live. `Log_msg` (`0x02742558`) wants `r3` = level
and `r4` = format, and the caller has already set both before calling the stub, so the branch
passes them straight through. The two functions are 24 174 216 bytes apart, inside the 24-bit
branch range, so no code cave is needed.

**Use it to find out whether something is reaching the app** — for example whether DBUS
message `0xcb` (203), the AUX status trigger, arrives at the media app at all. Turn it on, and
expect a lot of output: **do not drive on this build**, and reflash a normal one afterwards.

Open question: `Log_msg` is the debug channel, so where its output actually lands — serial,
the spy ring buffer, or a file — decides whether this is readable without hardware attached.
Settle that before flashing it.


### `aux-always-available`

`li r3,1 ; blr` at the top of `C_HMI_AUDIO_APP_BASE::IsAUXSRCAvailable()`. AUX stays
selectable with no signal, so it is always in the SRC cycle. It does **not** cause the
unit to switch by itself.

### `aux-sticky`

Two edits in `HandleAudioAuxInputStatusChnged()`:

| offset | original | patched | effect |
|---|---|---|---|
| `+0x10c` (AUDIO_BT `0x023032e8`, NAV `0x02303428`) | `beq` | `nop` | drop the `GetMediaDevice` early exit so `ActivateSource()` is reachable |
| `+0x118` (AUDIO_BT `0x023032f4`, NAV `0x02303434`) | `beq cr7,+0x58` | `b +0x140` | when the AUX signal is absent, jump to the return path instead of the release branch |

The second edit means that once AUX has been activated it **stays** selected until the
user changes source — for intermittent CarPlay audio that otherwise flaps between AUX
and radio. It is a deliberate trade: AUX will no longer hand back to radio on its own.

Both offsets were verified against all three images (`AUDIO_BT`, `AUDIO_BT_256`, `NAV`).
