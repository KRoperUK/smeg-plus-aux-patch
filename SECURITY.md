# Security policy

## What this project is

Tooling that **edits a firmware update package you supply**. It contains no vendor
firmware, no exploit for a remote target, and nothing that runs on a network. The scope is
local: read a package, patch it, write a new package.

Two things are worth stating plainly:

- **Flashing is at your own risk.** A bad build can leave a head unit needing recovery or
  dealer service. Everything here is prepared and checksum-verified, but it has not been
  validated on hardware by the maintainer.
- **The patches are not security fixes.** This is not a jailbreak, an unlock, or a
  tamper-resistance bypass; it changes which audio source the unit selects.

## Reporting

If you find a vulnerability **in the tooling** — something that could corrupt a package
silently, write outside the output directory, execute unintended commands from a crafted
input, or mishandle untrusted files — please report it privately via
[GitHub Security Advisories](https://github.com/KRoperUK/smeg-plus-aux-patch/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a week.

Please include the command you ran, the input that triggered it, and what happened.

Vulnerabilities in the **head unit's own firmware** are out of scope here; the right
channel for those is the vendor.

## Supported versions

The latest release only. Fixes land on `main` and are released automatically.
