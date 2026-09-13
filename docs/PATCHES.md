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

!!! failure "This edit is inert — keep it for reference, do not expect it to do anything"

    Emulating the function showed the branch is **never taken**: the AUX media device is
    registered unconditionally at start-up, so `GetMediaDevice(AUX)` returns success and
    the `beq` falls through with or without the patch. Forcing the failure case does not
    help either — `GetMediaDevice` writes nothing to its out-param when it fails, so the
    source-manager guard at `0x02303468` returns instead, one call later. The full
    reasoning, and the runs behind it, are in
    [Emulating the firmware](EMULATION.md).

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
| `patches/diagnostic-logmask.json` | forces the global trace mask, so the logging already in the image emits | diagnostic build, **not for driving** |
| `patches/diagnostic-logging.json` | redirects the logging stub to the real logger | diagnostic build, needs the mask patch too, **not for driving** |

!!! note "Hardware status"

    The combined build has been flashed to a real unit and accepted by the media contract
    check. The `IsAUXSRCAvailable()` change is confirmed working: AUX no longer greys out
    and is back in the SRC cycle. The **auto-switch has not been observed working yet** —
    see [Hardware verification](VERIFICATION.md).

### `diagnostic-logmask` — the one that actually makes logging appear

`Log_msg` at `0x02742558` does not write anything until it has cleared a gate:

```c
mask = GetLogMask();                 // 0x02742530 — reads one global
if ((mask & level) == 0) return;     // 0x027425e4
```

That global lives at `0x036d42a8`, which is **past the end of the image** (`0x03604450`) —
it is BSS, so it is zero when the unit boots. Exactly one instruction in the whole image
writes it, and it is reachable only through ten thin `SetTrace` wrappers that are vtable
entries, so nothing in the ordinary start-up path is known to turn logging on.

Replacing `GetLogMask` with a constant makes every level pass:

| build | address | original | patched |
|---|---|---|---|
| `NAV` | `0x02742530` | `94 21 ff f0 93 e1 00 0c` (prologue) | `38 60 ff ff 4e 80 00 20` (`li r3,-1 ; blr`) |

Same idiom as the `IsAUXSRCAvailable()` patch — overwrite a prologue with a constant
return, no code cave, trivially reversible.

This turns on the **~5900 call sites that already call `Log_msg` directly**. One of them is
the reason this patch exists:

```
0230331c  HandleAudioAuxInputStatusChnged()
  …
  02303574  li  r3, 1                 ; level
  0230357c  addi r4, r9, -0x2948      ; "HandleAudioAuxInputStatusChnged() -\n"
  02303590  bctrl Log_msg
```

The handler logs its own name at level 1 on its **shared return path**. Every one of its
four exit paths reaches that call, and so does the success path — checked by executing all
five. So the line appearing at all means the message arrived and the handler ran; its
absence means the event never got there. That is the standing question in
[Hardware verification](VERIFICATION.md) and [The AUX chain](AUX_CHAIN.md), answered while
changing no behaviour whatsoever. Verified in emulation: stock, the line is suppressed at
the mask test; patched, it is emitted. See [Emulating the firmware](EMULATION.md).

!!! warning "Where does it come out?"

    This makes the logging *happen*. It does not tell you where `Log_msg` sends it. Settle
    that before building a stick, or you will flash a diagnostic you cannot read.

### `diagnostic-logging` — the other half, and not the useful half alone

The application has a **second** logging mechanism: ~6700 call sites that are compiled out,
calling `dummyLogMsg` instead of `Log_msg`. `dummyLogMsg` at `0x010346d0` is literally:

```
010346d0  li  r3, 0
010346d4  blr
```

So replacing that one instruction with a branch to the real logger:

| build | address | original | patched |
|---|---|---|---|
| `NAV` | `0x010346d0` | `38 60 00 00` (`li r3,0`) | `49 70 de 88` (`b 0x02742558`) |

makes those stubbed call sites live. `Log_msg` (`0x02742558`) wants `r3` = level and `r4` =
format, and the caller has already set both before calling the stub, so the branch passes
them straight through. The two functions are 24 174 216 bytes apart, inside the 24-bit branch
range, so no code cave is needed.

!!! failure "On its own this emits nothing"

    The redirected sites land in `Log_msg`, which then tests the trace mask described above
    and returns. Flash `diagnostic-logmask` as well, or instead — the mask patch alone
    already covers the AUX question. Both together is roughly 12 600 live log sites, which
    is a flood rather than a diagnostic.

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
| `+0x10c` (AUDIO_BT `0x023032e8`, NAV `0x02303428`) | `beq` | `nop` | drop the `GetMediaDevice` early exit — **inert**, see [Emulating the firmware](EMULATION.md) |
| `+0x118` (AUDIO_BT `0x023032f4`, NAV `0x02303434`) | `beq cr7,+0x58` | `b +0x140` | when the AUX signal is absent, jump to the return path instead of the release branch |

The second edit means that once AUX has been activated it **stays** selected until the
user changes source — for intermittent CarPlay audio that otherwise flaps between AUX
and radio. It is a deliberate trade: AUX will no longer hand back to radio on its own.

Both offsets were verified against all three images (`AUDIO_BT`, `AUDIO_BT_256`, `NAV`).
