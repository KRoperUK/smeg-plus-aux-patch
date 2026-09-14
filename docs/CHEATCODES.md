# Cheatcodes and the spy/diagnostics system

## The cheatcode list is data

The codes are not compiled in. They live in the media partition at
`Data_base/sqlite/cheatcodes.sqlite`, table `cheatcodes`:

```sql
CREATE TABLE cheatcodes (
  name VARCHAR(50) PRIMARY KEY,
  is_displayable INT DEFAULT 0,
  is_configurable INT DEFAULT 0,
  max_params_number INT DEFAULT 0,
  is_official INT DEFAULT 0,
  is_synchronous INT DEFAULT 0,
  is_available_in_release INT DEFAULT 1,
  CCOD_PATH TEXT
);
```

| name | displayable | params | CCOD_PATH | purpose |
|---|---|---|---|---|
| `SPYSTORE` | no | 0 | NAND | copy spy traces + spy dir out to removable storage |
| `SPYTAKE` | no | 0 | NAND | audio long-event spy hook |
| `SPYCLN` | no | 0 | NAND | clean spy buffers |
| `REBOOT` | no | 0 | NAND | reboot the unit |
| `HWINFO` | yes | 0 | NAND | hardware info |
| `SWINFO` | yes | 0 | NAND | software info |
| `AUDIOINFO` | yes | 0 | NAND | audio diagnostics |
| `TUNERINFO` | yes | 0 | NAND | tuner diagnostics |
| `BTINFO` | yes | 0 | NAND | Bluetooth info |
| `NETINFO` | yes | 1 | NAND | network info |
| `GPSINFO` | yes | 0 | MICRO_SD | GPS info |
| `SYSMON` | yes | 0 | NAND | system monitor |
| `MMIMON` | yes | 0 | NAND | MMI monitor |
| `GUIDBG` | yes | 0 | NAND | GUI debug |
| `ZAINFO` | yes | 0 | NAND | zone/area info |
| `MSDREFRESH` | yes | 1 | NAND | refresh SD contents |
| `PING` | yes | 1 | NAND | ping |
| `AFTT` | no | 0 | NAND | AF tracking tool |
| `ARKBYP` | no | 0 | NAND | Arkamys bypass |
| `FPS` | no | 0 | NAND | frame rate |
| `ECSAVE` | no | 1 | NAND | save EC |
| `CATCLN` | no | 0 | NAND | catalogue clean |
| `BT` | no | 2 | NAND | Bluetooth command |
| `BT0DB` | no | 0 | NAND | Bluetooth 0 dB |
| `BTADC` | no | 2 | NAND | Bluetooth ADC |
| `BTSTARTER` | no | 1 | NAND | Bluetooth starter |
| `MIRE` | no | 1 | NAND | MIRE test |
| `SIMSPEED` | no | 1 | MICRO_SD | simulated speed |
| `MAPSPEED` | no | 1 | MICRO_SD | map speed |

`is_displayable = 0` only means it is not listed on the entry screen — it can still be
typed. The libraries themselves are in the media partition under `/CCOD/`, named
`libcheatcode_<NAME>.out` (with `.out.inf` and a `.out.txt.gz` symbol map).

## How you get to the entry screen

- The screen is `C_HMI_CONFIG_EngineModeCheatCode_VKB_Z1` (a virtual keyboard) plus
  `C_HMI_CONFIG_CheatcodeFormat_MNU_Z1`.
- The Config app registers it at runtime:
  `C_HMI_CONFIG_EngineModeCheatCode_VKB_Z1::C1(...)` then
  `C_HMI_MENU_MGR::RegisterScreen(0x5601, state)` — `0x5601` = screen id **22017**.
- The menu tree (`desktopServices.sqlite` -> `current_menu`) has item **22017
  'Cheat Code'**, but it is a *root* item (`parent_item_ID = 65535`) with
  `key_event_keycode = 0`, and it is **not** a child of **22000 'Config Sec View'**
  (what the carrousel "Config" entry opens). So it never appears in Settings, and it
  has no shortcut key.
- The only hard-coded trigger is `C_HMI_CONFIG_APP_BASE::HandleKeyboardMessage`, which
  calls `StartCheatCodeSession()` on virtual key **`0x54`** while the Config app has
  focus. That constant is firmware-only; it maps to no DB entry.
- Launch path: `CheckCheatCode()` -> `C_BCM_HMI_CHEAT_CODE_CLIENT::exists()` /
  `is_displayable()` -> `LaunchCheatCode()` -> `activate()`, over DBUS
  `com/MM/BCM_CHEAT_CODE` (`BCM_cheatcode_SERVER`).

!!! success "There is a way in — observed on a car, 2026-09-14"

    **Holding the RADIO / MEDIA button opens the entry screen.** This section previously
    concluded there was no user-facing route, and that was wrong. The hard-coded trigger is
    virtual key `0x54` while the Config app has focus, so the RADIO/MEDIA long-press is very
    likely what that key is — which is direct evidence for issue **#23**, and means the codes
    are reachable today without the #22 menu work.

    Practical consequence: `SPYSTORE` can be run without patching anything, and it copies the
    spy directory out to removable storage. What lands there is more than logs:

    - the updater's `/SYSTEM_TMP_DATA/spy/UPG/UPG_log.txt` (rotated) — see
      [Hardware verification](VERIFICATION.md)
    - **`abs_symbols_base.txt.gz`** (98 365 lines) and **`symbols_bsp.txt.gz`** (22 497) — the
      application and BSP symbol tables that `tools/ppcdis.py`, `xref.py` and `callers.py`
      resolve names from. They are what `AGENTS.md` means by "patch by symbol, not by pattern",
      and `SPYSTORE` is a way to obtain them.
    - a task/exception capture from the last boot, which is how the unit's own settings
      (`CMMUPKeys::ShowStatus`, 271 keys) can be read without the UI.

Net: the entry screen is reachable by holding **RADIO / MEDIA**; the menu path is still
absent, so see issue **#22** if that should be fixed properly, and **#23** for confirming that
virtual key `0x54` is this button.

## The spy system

`C_BCM_SPY` / `C_BCM_SPY_List` / `C_BCM_SPY_Elem` implement per-module ring buffers of
text lines, registered at runtime:

```
C_BCM_SPY::SetConfiguration(id, name, t_SpyBufferType, size, n, m, enable)
C_BCM_SPY::WriteData(id, ptr, len)
```

Compiled flags: `__HIFI_SPY_TO_DISK__ = YES`, `__HIFI_SPY_MEMORIZED_ENABLED__ = NO`,
`__HIFI_SPY_NEW_SETCONF_API__ = NO`.

Spy output lives on the unit under `/SYSTEM_TMP_DATA/SPY/` — e.g.
`spyAudio_%lu.bin.gz`, tuner-DAB dumps (`DmpEvn_*.dat`, `DmpFic_*.dat`,
`EPG_*.bin`), `log_error.txt`.

What `SPYSTORE` actually does:

```
libcheatcode_SPYSTORE.out : Activate()
  -> C_BCM_SPY::DirectCallCopy(std::string const&)     # empty string in practice
     -> C_BCM_SPY::CallBackCopy(std::string const&)    # NAV 0x01273734
        -> C_FS_STORAGE_CTRL_PATH::GetUnknownDir()      # removable media target
        -> Mkdir + GetSpyFolderName                     # dest = <stick>/SPY/<timestamp>
        -> Copy (GetTracesFile)                         # traces.bin
        -> Xcopy (GetSpyDir)                            # /SYSTEM_TMP_DATA/SPY ring buffers
        -> Xcopy (GetApplicationDir + "/PKG/*.*")       # the abs_symbols_*.gz maps
        -> Xcopy (GetCalibrationDataDir + "*.log")      # calibration logs
        -> Xcopy (GetCalibrationDataDir + "*regen*")    # SD-regen files
```

`C_BCM_SPY::CopyTraces(t_bcm_spy_files)` is the sibling entry point. Each copy step is the
same shape — a `Get<X>Dir` source getter, an optional `AddName` glob, then
`C_FS_STORAGE_CTRL_IO::Xcopy(source, dest)` (`0x010554f4`) into the timestamped stick
folder. Verified by disassembly (`tools/ppcdis.py`) against the 5.43.A.R2 NAV image.

### Adding /USER_DATA to the dump (`spy-dump-userdata`)

The one thing the collect does **not** capture is the live settings partition. There is no
removable card to image, and the ring buffers above are not the settings databases — so a
stock `SPYSTORE` cannot back up your paired phones, navigation destinations or presets.

`patches/spy-dump-userdata.json` adds that. The firmware already ships the exact primitive:
`C_FS_STORAGE_CTRL_PATH::GetUserDataDir` (`0x0105ae44`) resolves to `/USER_DATA/user_data/`
— the tree holding `sqlite/up_common.sqlite`, `sqlite/connectivity.sqlite`,
`sqlite/nav_dest.sqlite`, `Audio/Tuner.dat` and the rest. `CallBackCopy` has no spare room
and there is no usable code cave inside `.text`, so the patch is **cave-free**: it
overwrites the least-valuable existing copy block — the `*regen*` calibration copy — with

```
GetUserDataDir(entity)     ; source = /USER_DATA/user_data/
Xcopy(entity, dest)        ; dest = <stick>/SPY/<timestamp>, Xcopy addr reused from r26
```

Trade-off: the dump no longer contains the `*regen*` calibration files. Exact addresses
and bytes are in [Patch reference](PATCHES.md).

!!! success "Confirmed on hardware — 2026-09-14 (NAV)"

    Flashed and run: `SPYSTORE` produced a dump containing the whole `/USER_DATA/user_data/`
    tree — 14 `sqlite/` databases with `.inf` sidecars, `Audio/` presets, and `Nav`/`TTS`/`T2BF`.
    The DBs are the genuine live copies (`nav_dest.sqlite` is valid SQLite; `up_common` and
    `up_user` come out **gzip'd**, as the unit stores them — the boot log's `gzUnixRead`).
    **`connectivity.sqlite` is not among them** — it is imported from the system partition
    rather than kept under `/USER_DATA`, so paired phones are out of scope; nav destinations,
    presets and general settings are captured. NAV only until the `AUDIO_BT`/`AUDIO_BT_256`
    addresses are re-derived.

**Do not confuse this with** `C_BCM_SPY_System_Shot::SpyFiles()` — despite the name it is
a diagnostic snapshot that writes `diag_zi.sqlite`, not the debug spy logs. Ruled out as
a hook.

### A module dump reaches the spy, not the dead log sink

A module's SPY dump is a live caller of this system, and it is worth knowing that it does **not**
go through `Log_msg`'s stubbed sink (see [Patch reference](PATCHES.md) and issue **#94**).
`C_MGR_SRC`'s dump at `0x0169a2e4` builds its lines with the string-buffer helpers and then
emits them through a service, not the logger:

```
0x0169a2e4   MGR_SRC SPY dump  (one block per scheduled slot)
  -> 0x01695c30
       -> FUN_0103155c(0x52d0, 0)   look up service 0x52d0
       -> 0x012753c0                C_BCM_SPY::WriteData(id = 0x62d4, ptr, len)
```

`0x012753c0` is `C_BCM_SPY::WriteData`: it logs under the `BCM_SPY` / `WriteData` strings, and
the only stubbed sink it touches, `0x010346d0`, is reached on its **error** path
(`m_pListSpy isn't init`). Spy data therefore has its own route to `/SYSTEM_TMP_DATA/SPY/`, and
observing a module dump does not depend on the log sink being given a destination.

That is why issue **#24** is worth attempting first: a boot-time dump of this kind would show, at
runtime, which sources `C_MGR_SRC` has registered requests for and under which `POS_*` id — the
empirical form of the enum the [AUX chain](AUX_CHAIN.md) derives statically.

Relevant to this project: running `SPYSTORE` with a USB inserted would show whether HMI
event `0x613dc` actually reaches `HandleAudioAuxInputStatusChnged()`, which is the open
question behind the AUX auto-switch patch. See issue **#24**.
