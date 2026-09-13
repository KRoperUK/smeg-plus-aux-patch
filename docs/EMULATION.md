# Running the firmware without a car

Every patch address in this project was found by reading disassembly, and every claim
about what a patch *does* was an inference from that reading. Inferences are where the car
trips came from.

`tools/ppcemu.py` executes the shipped image instead. It does not boot the unit — there is
no VxWorks, no display, no DBUS. It calls **one function at a time** on an emulated
PowerPC core, with a stack, a scratch region and stubs for whatever that function calls.
That is enough to answer the question a patch actually raises: *does control reach the
code I think it reaches, and under what conditions?*

Doing this to the AUX patches found that **one of the two edits in `aux-autoswitch` cannot
work, and never could**. The details are below.

## Why this is possible at all

The SoC is a **Freescale MPC5121e** — an e300 core, which is plain 32-bit big-endian
PowerPC. Unicorn's PowerPC backend runs it directly. There is no custom silicon to model
because we never execute anything that touches the peripherals: a function that would talk
to hardware is stubbed at its call site.

The application image is not encrypted either (see [Overview](ANALYSIS.md)), so
`tools/unpack.py` produces exactly the bytes the CPU would fetch, based at `0x01000000`.

```sh
python3 tools/unpack.py SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin app_nav.bin
uv run tools/ppcemu.py app_nav.bin --call 0x02247858 --arg 0x60000000 \
    --patches patches/aux-autoswitch.json --module NAV --trace
```

A whole comparison — six runs of a 39 MB image, stock against patched — takes well under a
second, so this belongs in the edit loop, not in a special session.

## What it can and cannot tell you

**Reachability is proof.** If the emulator shows a branch is taken, that branch is taken
for those register and memory values; the CPU has no opinion about where the values came
from.

**Behaviour is not.** A stub returning `0` is an assumption you wrote down, not something
observed on a car. The emulator makes assumptions *explicit and executable* — which is the
whole gain — but it cannot tell you whether the unit's real state matches them. Where a
finding below depends on a stub, it says so.

Unmapped memory is recorded rather than fatal: the emulator maps a zero page and notes the
access, so the list of "state this function expected to exist" falls out of a run.

## What it found

### 1. The `IsAUXSRCAvailable()` patch does what it claims

Stock, with a zeroed object, the function finds a null pointer at `this+0x50dfc` and takes
the failure path into the kernel. Patched, it returns `1` in two instructions. This one was
already confirmed on hardware; the emulator agrees.

### 2. The `+0x10c` early-exit patch is inert

This is the second half of `aux-autoswitch`, and it has never been observed doing anything
on a car. The emulator shows why — two independent reasons, either of which is sufficient.

**It patches a branch that is never taken.** The early exit fires when
`GetMediaDevice(mgr, AUX, &obj)` returns non-zero, and that call fails only when the AUX
media device is not registered. Registration was executed, not read:

```
C_HMI_MEDIA_APP_BASE init  @ 0x022bf934
  -> register devices      @ 0x022b833c        (unconditional; every early-out
                                                 branch in init rejoins before it)
       AddDevice(type 0) …(type 1)…(type 2)…(type 3)…(type 5)
       if (this->0x51450)  AddDevice(type 4)   <- the only conditional
```

Running that function fills the table with **types {0, 1, 2, 3, 5}** — AUX (type 5) among
them, unconditionally, with its source manager taken from `this+0x50e3c`, which is
allocated and stored unconditionally at `0x022bcac8`. So `GetMediaDevice(AUX)` succeeds,
the status is `0`, and the `beq` at `+0x10c` falls through with or without the patch.

**And if it were taken, the patch still would not help.** `GetMediaDevice` writes nothing
to its out-param on the failure path:

```c
int GetMediaDevice(mgr, type, out) {       // 0x022f3750
    status = -1;
    dev = FindDevice(mgr, type);           // 0x022f3608 — linear scan, count at mgr+0xc0
    if (dev == NULL) return status;        // -1, and *out is left exactly as it was
    out[0x00] = dev[0x00]; … out[0x10] = dev[0x10]; …
    return 0;
}
```

`out` is the local object the handler just zero-initialised, and `out[0x10]` is the source
manager the handler needs. Nopping the early exit lets execution continue with that field
still null — straight into the guard at `0x02303468`, which returns. The patch buys exactly
one extra call, `SetMediaDeviceState(AUX, 2)`, and then exits at the same place:

| AUX media device | stock | patched |
|---|---|---|
| absent | returns at `+0x10c` | returns at `+0x14c`, having called `SetMediaDeviceState` |
| present | reaches `ActivateSource` | reaches `ActivateSource` — identical |

The patch removes an early exit whose own precondition is what the following code depends
on. There is no configuration in which it reaches `ActivateSource` and stock does not.

!!! danger "Do not nop the source-manager guard as well"

    The obvious follow-up — also removing the `beq` at `0x02303468` — calls
    `ActivateSource` with a **null `this`**: `0x0230346c` loads that field straight into
    `r3`. On the HMI thread. Leave it alone.

### 3. The handler's real gates, in order

```c
void HandleAudioAuxInputStatusChnged(this) {       // 0x0230331c
    app = this->0x50df4;                           // 0x022ad2c0, a plain getter
    if (app == NULL) return;                       // gate 1  @ 0x02303358
    ctor(&obj);                                    // zeroes obj, obj[0x10] included
    GetAuxStatus(app, &signal);                    // 0x025cb258 — return value IGNORED
    state = (signal != 0);
    if (state == this->0x51449) return;            // gate 2  @ 0x023033d4  (change detector)
    this->0x51449 = state;
    if (GetMediaDevice(mgr, AUX, &obj)) return;    // gate 3  @ 0x02303428  (never taken)
    SetMediaDeviceState(mgr, AUX, 2);
    if (obj[0x10] == NULL) return;                 // gate 4  @ 0x02303468  (never taken
    ActivateSource(obj[0x10], true);               //          once gate 3 passes)
}
```

Two things in there matter beyond the patch:

**Gate 2 means the handler only acts on a transition.** An AUX signal that is already
present when the state is first recorded produces no activation, because nothing changed.

**`GetAuxStatus`'s return value is discarded.** It returns `-1` without touching the
out-param if its proxy (`obj->0xc`) is null — and the handler reads the untouched local as
"no signal". A failed query is indistinguishable from a genuine absence of signal, and
lands in gate 2 as "no change". That is a silent failure mode, and it is the shape of
failure that matches the symptom.

### 4. The logging is gated by one global, and it is zero

`Log_msg` begins `if ((GetLogMask() & level) == 0) return;`. `GetLogMask` reads a single
global at `0x036d42a8` — past the end of the image, so BSS, so **zero at boot** — and
exactly one instruction anywhere in the image writes it, through ten `SetTrace` wrappers
that are vtable entries only.

Emulating `Log_msg` directly: with the mask at 0, it bails after 47 instructions and never
reaches the formatting code; with the mask forced, it runs 277. Running the AUX handler end
to end with the real `Log_msg` in the loop shows the same thing at the level that matters —
stock, the handler's own log line is suppressed; with `diagnostic-logmask` applied, it is
emitted.

That has a direct consequence for `diagnostic-logging`, which redirects the ~6700
compiled-out call sites to the real logger: **on its own it emits nothing**, because every
redirected site lands in `Log_msg` and hits the same gate. The image has two logging
mechanisms and this one only unblocks the wrong half.

The useful half is the other ~5900 sites that call `Log_msg` directly and are gated only by
the mask — including `HandleAudioAuxInputStatusChnged()`, which logs its own name at level 1
on its shared return path. Forcing the mask answers whether that handler is entered without
changing any behaviour.

### 5. One device type is unreachable firmware-wide

Device **type 4** is registered only when the byte at `this+0x51450` is non-zero. That byte
is written in exactly **two places in the entire 39 MB image** — both constructors, both
storing `0`. Nothing anywhere sets it. Whatever type 4 is (the surrounding evidence points
at Jukebox), the firmware as shipped can never register it.

This is worth knowing mainly as a warning: a device type being absent from the table is not
evidence about AUX, because at least one type is absent by construction.

## What this changes

The conclusion in [Overview](ANALYSIS.md) — that the patch is not the problem and the DBUS
message is not arriving — **still stands, and is now better supported**. What changes is
the standing of the second edit: it is not "a fix that has not been confirmed", it is a fix
that provably cannot fire. Effort spent flashing it is spent.

The open question is upstream of this function entirely: is `HandleAudioAuxInputStatusChnged`
ever entered, and if it is, does the status query return a signal? The first half is now
directly answerable — the handler logs its own name on every exit, and
`patches/diagnostic-logmask.json` makes that line appear. See
[Patch reference](PATCHES.md).

The whole chain, gate by gate, with the state of each link, is in
[The AUX chain](AUX_CHAIN.md). The short version: every link is a null check, the four
inside the handler have now been executed, and the one that has never been observed is the
first — whether the audio client's listener was ever registered. A single null pointer
there explains every symptom at once, which makes it the first thing to look for in the
log.

## Reproducing this

The tests in `tests/test_ppcemu.py` cover the emulator itself against assembled-in-test
images, so they run without any firmware. The findings above need your own package:

```sh
python3 tools/unpack.py SMEG_PLUS_UPG/NAV/AppBin/f_BigQuick.bin app_nav.bin

# 1. the IsAUXSRCAvailable patch, stock vs patched
uv run tools/ppcemu.py app_nav.bin --call 0x02247858 --arg 0x60000000
uv run tools/ppcemu.py app_nav.bin --call 0x02247858 --arg 0x60000000 \
    --patches patches/aux-autoswitch.json --module NAV

# 2. the device table — types registered, with the type-4 flag clear
uv run tools/ppcemu.py app_nav.bin --call 0x022b833c --arg 0x60000000
```

The handler comparison needs two stubs, so it is a short script rather than a command:

```python
import struct, sys
sys.path.insert(0, "tools")
from ppcemu import Emulator, SCRATCH
from unicorn.ppc_const import UC_PPC_REG_4

IMG  = open("app_nav.bin", "rb").read()
DEV  = SCRATCH + 0x9000
REAL = {0x022f3750, 0x02368080, 0x022f3608}      # GetMediaDevice, ctor, FindDevice

def run(patched, device_found):
    e = Emulator(IMG)
    if patched:
        e.apply_patch_file("patches/aux-autoswitch.json", "NAV")
    e.stub_all, e.stub_default, e.run_for_real = True, 0x60002000, REAL
    e.stub(0x025cb258, lambda uc: uc.mem_write(          # the AUX signal appears
        uc.reg_read(UC_PPC_REG_4), struct.pack(">I", 1)))
    e.stub(0x022f3608, DEV if device_found else 0)       # FindDevice
    e.write(DEV, b"\x00" * 0x20)
    e.write_u32(DEV + 0x10, 0xC0FFEE00)                  # the device's source manager
    e.call(0x0230331c, [SCRATCH])
    return e.reached(0x0273a248), e.call_sequence()      # ActivateSource?

for patched in (False, True):
    for found in (False, True):
        print(patched, found, run(patched, found)[0])
```
