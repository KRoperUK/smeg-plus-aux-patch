# Notice

This project is an independent reverse-engineering effort. It is **not affiliated
with, authorised by, or endorsed by** any vehicle or head-unit manufacturer.

* Peugeot, Citroën, DS, Stellantis, Magneti Marelli and SMEG are trademarks of
  their respective owners.
* **No vendor firmware, upgrade packages, symbol maps or other copyrighted
  binaries are included in or distributed with this repository.** The `.gitignore`
  is configured to keep them out.
* The tooling is intended to be used with firmware you have legally obtained for
  your own device. You are responsible for complying with the laws and licence
  terms that apply to your device and software, and for any consequences of
  modifying it.

## Prior work

Independent reverse-engineering of the same platform, which this project has drawn
on and which is worth reading alongside it:

* [bousqi/SMEG_PLUS](https://github.com/bousqi/SMEG_PLUS) — the U-Boot and VxWorks
  side, the TFFS partition layout, and the identification of the SoC as a Freescale
  MPC5121e. No code or content is copied from it here; where a fact came from there
  it is attributed at the point of use.

The MIT licence in [`LICENSE`](LICENSE) covers the original scripts and
documentation in this repository only. It grants no rights to any third-party
software or firmware.
