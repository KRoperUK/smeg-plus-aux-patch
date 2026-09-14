# The AUX auto-switch, gate by gate

This is the single reference for what has to happen, in order, for the unit to select AUX
by itself when a signal appears — and what is known about each step. Everything with an
address was read out of the `NAV` image; everything marked **executed** was run under
[the emulator](EMULATION.md) rather than reasoned about.

If you only read one thing: the patch set does not fail at the step the project spent two
years assuming it did, and the one link that has never been checked is the first one.

## The chain

```
audio server
  --DBUS signal-->  C_BCM_HMI_AUDIO_CLIENT
                      if (client->0x50 == NULL) return;        <-- LINK A: no listener
                    post internal message 203 (0xcb)           @ 0x025cdefc
  --message 203-->  C_HMI_MEDIA_APP_BASE::HandleDBUSMessage    @ 0x02309398
                      case 0xcb                                @ 0x02309638 -> 0x02309fbc
  --direct call-->  HandleAudioAuxInputStatusChnged            @ 0x0230331c
                      gate 1  app = this->0x50df4, NULL?       @ 0x02303358
                      gate 2  state unchanged?                 @ 0x023033d4
                      gate 3  GetMediaDevice(AUX) failed?      @ 0x02303428
                      gate 4  source manager NULL?             @ 0x02303468
                    ActivateSource(srcMgr, true)               @ 0x02303484
```

## Link A — the listener

The client only posts message 203 if something registered for it:

```c
void OnAuxSignalStatusChanged(client) {     // 0x025c9e78
    if (client->0x50 == NULL) return;       // 0x025c9e9c
    Post203(client->0x50);                  // 0x025cdefc
}
```

`client->0x50` is written by one setter (`0x025c97f0`), called from two places, both of
which look like this:

```c
if (app->0xc == NULL) return;           // no proxy, no registration
SetListener(app->0xc, app);
```

So the listener exists only if `app->0xc` does. **That same `app->0xc` is what the AUX
status query dereferences** (`0x025cb280`), returning `-1` without touching its out-param
when it is null — and gate 2 discards that return value. One null pointer there would
produce exactly the symptom seen on the car: no switch, no error, nothing in the UI.

`app` itself is `mediaApp->0x50df4`, assigned at `0x022bc4e8` from a DBUS client factory
(`0x025fc3e8`) called as `Create(3, 0xc8, this)`. That factory is a lookup-or-create with
**several paths that return NULL** — it needs a DBUS connection at the moment the media
application initialises. Whether any of them is taken on a real unit is not knowable from
the image; it is the open question.

!!! question "This link has never been observed"

    Everything downstream of it has now been executed. Link A has not, because it depends
    on runtime state (a DBUS connection) that no static reading can settle.

## The four gates in the handler

Recovered by executing the function, not by reading it:

```c
void HandleAudioAuxInputStatusChnged(this) {       // 0x0230331c
    app = this->0x50df4;                           // 0x022ad2c0 — a plain getter
    if (app == NULL) return;                       // gate 1  @ 0x02303358
    ctor(&obj);                                    // 0x02368080 — zeroes obj entirely
    GetAuxStatus(app, &signal);                    // 0x025cb258 — RETURN VALUE DISCARDED
    state = (signal != 0);
    if (state == this->0x51449) return;            // gate 2  @ 0x023033d4
    this->0x51449 = state;
    if (GetMediaDevice(mgr, AUX, &obj)) return;    // gate 3  @ 0x02303428
    SetMediaDeviceState(mgr, AUX, 2);              // 0x022f388c
    if (obj[0x10] == NULL) return;                 // gate 4  @ 0x02303468
    ActivateSource(obj[0x10], true);               // 0x0273a248
}
```

| gate | tests | status |
|---|---|---|
| 1 | the audio client exists | **unknown** — the only untested link, see above |
| 2 | the AUX state actually changed | **a real gate** — only acts on a transition |
| 3 | `GetMediaDevice(AUX)` succeeded | **never fires** — executed; see below |
| 4 | the device carries a source manager | **never fires once gate 3 passes** |

**Gate 2 is a change detector.** A signal already present when the state is first recorded
produces no activation, because nothing changed. Worse, because the status query's return
value is thrown away, a *failed* query reads as "no signal" and lands here as "no change".
A broken link A and a genuinely silent AUX input are indistinguishable at this point.

**Gate 3 is what `aux-autoswitch` nops, and it never fires.** The AUX media device is
registered unconditionally at start-up, so `GetMediaDevice(AUX)` succeeds. **Executed:**
running the registration function fills the table with types `{0, 1, 2, 3, 5}`.

**Gate 4 is why nopping gate 3 would not have helped anyway.** `GetMediaDevice` writes
nothing to its out-param when it fails, so the field gate 4 tests is still the zero the
constructor left. See [Emulating the firmware](EMULATION.md) for the full truth table.

!!! danger "Do not nop gate 4"

    `0x0230346c` loads that field straight into `r3` as `ActivateSource`'s `this`. Removing
    the guard calls a C++ method on a null pointer, on the HMI thread.

## The media device table

`GetMediaDevice` and its neighbours operate on a fixed array hanging off the media app at
`this+0x50e60`:

```
mgr + 0x00 + n*0x20   device record n, 6 slots
mgr + 0xc0            how many are in use
```

Each 32-byte record holds its type at `+0x00` and its source manager at `+0x10`. Three
functions matter:

| function | address | behaviour |
|---|---|---|
| `FindDevice(mgr, type)` | `0x022f3608` | linear scan of the first `mgr[0xc0]` slots; returns the record or NULL |
| `GetMediaDevice(mgr, type, out)` | `0x022f3750` | `FindDevice`, then field-by-field copy into `out`; returns 0, or **-1 writing nothing** |
| `AddDevice(mgr, src)` | `0x022f3ad0` | append; refuses when `mgr[0xc0] > 5` |

Registration runs once, from media-app init (`0x022bf934` → `0x022b833c`), and is
unconditional — every early-out branch in the caller rejoins before the call. It registers
types 0, 1, 2, 3 and 5 outright, then type 4 only if the byte at `this+0x51450` is set.

### Which type is AUX

Type **5**. Two independent lines of evidence:

- Every `GetMediaDevice`/`SetMediaDeviceState` call site that passes type 5 — `0x02303404`,
  `0x02303450`, `0x02303564` — is **inside the AUX handler**, and no other function uses it.
- Type 4, the only other candidate, is used by unrelated call sites and is gated on a byte
  written in exactly **two places in the whole image, both constructors, both storing 0**.
  Nothing sets it, so type 4 can never be registered at all.

Note the trap: this is not the same enum as the **source** list recovered from the HMI
`OnEventSelect*` handlers. Two namespaces, overlapping numbers. Do not carry a value from
one into the other — and there are more than two.

### Four source numberings, and which one `Last_Source` uses

| numbering | where it comes from | AUX is |
|---|---|---|
| media device type | the table `GetMediaDevice` searches | **5** |
| HMI source | `OnEventSelect*` → `CreateNotificationCommand` | **7** |
| audio module `SRC_*` | the name table at `0x02f9d60c`, printed as `Current_source` | **5** |
| `C_MGR_SRC` position (`POS_*`) | the SPY dump's switch, `0x0169a2e4` | **7** |
| screen position | `GetSourceAtPosition`, 0-based | **4** |

The audio module's table is contiguous from `SRC_NO_SOURCE = 0`:

```
0 SRC_NO_SOURCE   1 SRC_TUNER   2 SRC_CD    3 SRC_MP3      4 SRC_CDC
5 SRC_AUX         6 SRC_PHONE   7 SRC_TTS   8 SRC_TA_PTY   9 SRC_TTS_ON_AUX
10 SRC_AUX_CONVERGENCE  11 SRC_BLUETOOTH  12 SRC_MTB  13 SRC_MLDIPO_RECO_PHONE
```

**Two of these put AUX at `7`, and one of the two is `C_MGR_SRC`'s own enum** — the object that
owns `+0xb4` in the first place. That is the strongest evidence available short of a run, and it
is why
[`aux-default-retry.json`](https://github.com/KRoperUK/smeg-plus-patches/blob/main/builds/aux-default-retry.json)
spends its flash on `7`. The factory value `1` does not discriminate on its own: it is the radio
in the HMI numbering, `SRC_TUNER` in the audio one, and `POS_TUNER` in this one.

`4` and `7` have both been flashed without the unit starting on AUX — but see
[Flashing](FLASHING.md): a `USER_DATA` payload in a folder not named `SMEG_PLUS_UPG` is skipped
silently, so neither of those flashes is yet known to have applied at all, and **no value for
`Last_Source` has actually been tested yet**.

### The key belongs to `C_MGR_SRC`, and the value must match a live source request

The key is read and written through the generic config loader in the core middleware — read
at `0x01699390`, written at `0x01695e2c` from the field at `+0xb4` of the object. That object
is `C_MGR_SRC`: its `UP_Keys` names (`Last_Source`, `Last_Source_Priority`,
`Src_Radio_SchedPos`, `Src_Media_SchedPos`, `Src_Radio_Priority`, `Src_Media_Priority`) sit
contiguously at `0x0300a578`, immediately ahead of the class's own log strings at
`0x0300a6a4`.

Following `+0xb4` gives the shape of the value. In the NAV build:

| address | what it does |
|---|---|
| `0x01699490` | boot restore: the value read back from `Last_Source` is **stored straight to `+0xb4`** and mirrored to the global `0x035e4cd0`, with no validation at all |
| `0x016995b4` | constructor: `+0xb4` and `0x035e4cd0` are both initialised to `1` — the same value the factory database ships |
| `0x0169c6ac` | reads `0x035e4cd0` and passes it as the source argument to `0x016977d0` |
| `0x016977d0` | the setter — walks the request lists and writes `+0xb4` only on a match; a miss leaves `+0xb4` alone |
| `0x016957ec` | the scheduler — **selects the source to restore** by matching `node+0x18` against `+0xb4` |
| `0x0169815c` | `C_MGR_SRC::AddRequest` — the site that populates `node+0x18` |
| `0x0169c51c` | the `C_MGR_SRC` message dispatcher (message id `0x62d5`): case 0 → `AddRequest`, case 1 → `RemoveRequest` at `0x01697d60`, case 2 → re-apply `Last_Source` |
| `0x0169bf74` | `C_MGR_SRC::AllocateSource` — the client entry that packages a request and sends it into the dispatcher |
| `0x0169a2e4` | the `MGR_SRC SPY` dump — swallows the `SrcId` switch that names each position (`POS_*`) |

`0x016977d0` walks the first request list, anchored at `this+0xd4` (`next` at `+0x3c`),
comparing its source argument against each node's `+0x18` field, and writes `+0xb4` on a
match. An id that matches nothing falls straight out to the return path **without touching
`+0xb4`**:

```
016977dc  lwz    r9, 0xd4(r3)     ; head of the first request list
016977e0  cmpwi  cr7, r9, 0
016977e4  bne    cr7, 0x16977f8
016977e8  b      0x1697854        ; empty list -> give up
016977ec  lwz    r9, 0x3c(r9)     ; node = node->next
016977f0  cmpwi  cr7, r9, 0
016977f4  beq    cr7, 0x1697854   ; ran off the end -> give up
016977f8  lwz    r0, 0x18(r9)     ; node->source_id
016977fc  cmpw   cr7, r4, r0
01697800  bne    cr7, 0x16977ec   ; no match -> keep walking
01697804  ...                     ; matched: commit to +0xb4
```

!!! warning "The setter cannot reject the flashed value"

    Because the miss path leaves `+0xb4` untouched, the setter is not a validator for what the
    database ships. Boot restore has already written `+0xb4` unconditionally, and the
    message-2 path only re-affirms it from `0x035e4cd0`. **A value written into the database
    always takes effect as far as `+0xb4` is concerned** — the question is only whether
    anything downstream does anything with it.

The consumer that gives the value its meaning is the scheduler at `0x016957ec`. It walks the
same lists and, in the mode where the stored source is being restored, picks the node whose
`+0x18` equals `+0xb4`:

```c
iVar7 = DAT_035e4cd0;                                       // the mirrored Last_Source
...
do {
    if (*(int *)(iVar6 + 0x18) == *(int *)(param_1 + 0xb4)) {   // node SrcId == Last_Source
        ... remember this node as the source to restore ...
    }
    iVar6 = *(int *)(iVar6 + 0x3c);
} while (iVar6 != 0);
```

So `Last_Source` must equal the **`SrcId` the source itself registered**, or nothing matches
and no source is restored — the unit falls back to its default. That is the real gate, and it
is downstream of the value, not a check on it.

#### What a request node is, and who writes `+0x18`

`C_MGR_SRC::AddRequest` (`0x0169815c`) is the registration site this page previously listed as
unfound. It logs under the `C_MGR_SRC` / `AddRequest` strings (`0x0300a6a4` / `0x0300a6b0`)
and is reached from the class's message dispatcher, keyed on **message id `0x62d5`**:

```
source module
  -> send(object, 0x62d5, opcode, flags)      common helper 0x014da78c
  -> C_MGR_SRC dispatch  FUN_0169c51c         (0x62d5 matched at 0x1698e18)
       case 0 -> FUN_0169815c  AddRequest
       case 1 -> FUN_01697d60  RemoveRequest
       case 2 -> FUN_016977d0(this, DAT_035e4cd0, 0, 0)
```

The message body is a 0x6a-byte payload; the request is the 0x2c-byte struct at `+0xc` of it
(`FUN_0169c71c` is a plain `memcpy`). `AddRequest` copies that struct into a freshly allocated
node, links it, and commits:

```c
node = SUB_01695590(this, idx * 4 + this + 0xc4);
if (*(int *)(idx * 4 + this + 0xd4) == 0) *(int *)(idx * 4 + this + 0xd4) = node;
*(short *)(node + 0x00) = req.MsgSrc;
*(int *)  (node + 0x14) = req.Type;
*(int *)  (node + 0x18) = req.SrcId;      // <-- the field the setter and the scheduler compare
...
FUN_016977d0(this, req.SrcId, 1, 1);
```

Two corrections to the earlier reading on this page:

* `this+0xd4` is **not a single list of registered sources**. It is the first of four list
  heads in an array (`+0xd4`, `+0xd8`, `+0xdc`, `+0xe0`) selected by a mapping of the request
  `Type`. The nodes are **pending requests**, not a registry.
* The setter's "must match a node" condition is satisfied trivially here: `AddRequest` inserts
  the node and then immediately calls the setter with the same id. It was never the gate it
  looked like.

`SrcId` therefore travels on the wire at `request + 0x18`, i.e. **byte `0x24` of the message
payload**. Which value a given source sends is the remaining unknown.

Requests reach the dispatcher through the client entry `C_MGR_SRC::AllocateSource`
(`0x0169bf74`), which copies the 0x2c-byte request and sends it. `AllocateSource` is reached
from the client wrapper `0x016bc1dc` — not `0x016bc1f0`, which an earlier pass took for the
function start and which is really four instructions inside it — and that wrapper resolves the
service directly with `FUN_0103155c(0x62d4, 0)`.

The ~30 `0x62d5` sites are not that table. Eighteen of them sit at
`0x014dc1a8`–`0x014dd358`, but their common helper `0x014da78c` emits a **0x14-byte** control
body, not the 0x6a-byte request, so they are short notifications that reuse the same message
id rather than source registration.

The client API is a fixed cluster, and it is worth knowing its shape before hunting in it. Eight
wrappers sit at `0x016bbec4`–`0x016bc2ac`, each with exactly one caller; those callers are the
public API at `0x016c09bc`–`0x016c0d3c`; and the public entries are exported through a **service
API table** at `0x0307aedc`–`0x0307af00` (C_MGR_SRC's slots — the table itself runs well beyond
them). Nothing references that table by literal address or by `lis/addi`, because it is reached
through the dynamic service registry (`FUN_0103155c(0x62d4, …)`, `FUN_01001178()`).

That is the wall for static tracing, and it is worth stating plainly: **the per-source callers of
`AllocateSource` cannot be found by xref.** `AllocateSource` has one caller, that caller has
none, and the entry above it is indexed at run time. Finding which module allocates AUX's
request needs the registry resolved, not another xref sweep.

!!! warning "Provenance"

    Everything in this subsection is **read from decompiled code**, not executed — the
    corrected mechanism included. The project's rule applies: reachability is proof, and a
    reading is not. The part corroborated by execution is the setter's own shape, which was
    confirmed by disassembly when this page was first written.

The `SrcId` space is `C_MGR_SRC`'s own **position** enum, readable from the SPY dump at
`0x0169a2e4`, which switches on a per-source field at `+0x370` and names it:

| value | name | value | name |
|---|---|---|---|
| `0` | `POS_NULL` | `6` | `POS_VIDEO` |
| `1` | `POS_TUNER` | `7` | `POS_AUX` |
| `2` | `POS_1CD` | `8` | `POS_BT` |
| `3` | `POS_MP3` | `9` | `POS_USB` |
| `4` | `POS_CDC` | `10` | `POS_IPOD` |
| `5` | `POS_JBX` | `0xff` | `POS_NOT_SCHEDULED` |
|  |  | other | `POS_MGR_SCR_NOT_SCHEDULED` |

**AUX is `7` here, and `5` is the Jukebox** — so the value
[`aux-default-retry.json`](https://github.com/KRoperUK/smeg-plus-patches/blob/main/builds/aux-default-retry.json)
ships has `C_MGR_SRC`'s own naming behind it, not only the HMI numbering's.

Read that mapping from the switch, not from the string literals. `POS_AUX` sits between
`POS_MP3` and `POS_BT` in the literal table but is `7` in the enum; an earlier version of this
page assumed the literals were in value order and concluded `5`. They are not in value order.

Two enums describe sources and they agree at `1` — the factory `Last_Source`, `POS_TUNER`, and
the audio module's `SRC_TUNER` all coincide — but they disagree at AUX: the audio module's
`SRC_*` table has `SRC_AUX = 5`. Since `+0xb4` belongs to `C_MGR_SRC`, its own enum is the one
that should apply, which is a second independent line of evidence for `7` beside the HMI
numbering.

### Make the next flash answer two questions

Because no `USER_DATA` flash has yet been confirmed to apply, a unit that still starts on
radio is ambiguous — wrong value, or payload skipped again? Ship a **beacon** alongside the
change: a second, unrelated key whose effect is visible and trivially reversible.
`aux-default-retry.json` moves `clock.Time_Zone` from `16` to `0`. After the flash, read the
configured time zone in the settings menu — not the clock face, which a GPS-slaved clock
corrects regardless:

| time zone | source | conclusion |
|---|---|---|
| changed | AUX | the value is right and the mechanism works |
| changed | radio | payload applied and `+0xb4` holds `7`, which the enum says is AUX — so suspect the path (registration or scheduling), not the number |
| unchanged | either | payload was skipped again; the source result means nothing |

## What to do next

Two things are open, in order of value.

**Confirm AUX's `SrcId` end to end.** The enum is now known — `POS_AUX = 7` — so this is no
longer a guess, but it is still *read* rather than executed. The per-source caller that allocates
AUX's request sits behind the service API table (`0x0307aedc`), which has no static references,
so closing this means resolving the service registry (`FUN_0103155c` / `FUN_01001178`) rather
than another xref sweep. The 0x2c-byte request that `AllocateSource` (`0x0169bf74`) takes carries
the `SrcId` at `+0x18`, so the caller that builds AUX's request is the thing to find.

**Give the firmware a log to write to.** The handler logs its own name at level 1 on its
**shared return path** — and **executed**: every one of the four exit paths, plus the success
path, reaches that log call. So the line `HandleAudioAuxInputStatusChnged() -` appearing at
all means the message arrived and the handler ran; its absence means link A is broken.

That would be one flash — except that this build has **no log output path**. `Log_msg`'s
sink is stubbed, so forcing the trace mask formats the message and then discards it, and
flashing both diagnostic patches makes the logger and the sink call each other. See
[Patch reference](PATCHES.md).

The sink now has a candidate destination: VxWorks `logMsg` at `0x00484a94`, recovered from
the symbol table inside the BSP image, with `patches/diagnostic-logsink.json` to point it
there. What is still unknown is where `logMsg`'s output physically surfaces on this unit,
which is issue #94. Until that is settled the diagnostic build is buildable but not
readable.

## Status of each claim

| claim | how it is known |
|---|---|
| the chain's addresses and dispatch | read from the image |
| gates 1–4 and their order | **executed** |
| gate 3 never fires; the registered types | **executed** |
| gate 4 blocks a nopped gate 3 | **executed** |
| every exit path logs | **executed** |
| `Log_msg` is gated by a BSS mask | **executed** |
| type 5 is AUX | inferred from call sites, strongly |
| `aux-sticky`'s second edit does what it says | **executed on all three builds** — after being corrected; it shipped unconditional |
| link A's state on a real unit | **not known** — needs the car |
| `AddRequest` writes `node+0x18`; the lists at `+0xd4` are requests, not a registry | **read from decompiled code** — not executed |
| the scheduler matches `node+0x18` against `+0xb4` | **read from decompiled code** — not executed |
| boot restore writes `+0xb4` with no validation | **read from decompiled code** — not executed |
| `POS_AUX = 7`, `POS_JBX = 5`, `POS_TUNER = 1` | **read from the SPY dump's switch** at `0x0169a2e4` — not executed |
| `AllocateSource` is the client entry that feeds `AddRequest` | **read from decompiled code** — not executed |
| `7` is the value the unit needs | **not known** — the enum says `7`; only the car settles it |
