"""SMEG+ AUX patch tooling.

These are primarily scripts (run them by path, e.g. `python3 tools/patch_smeg.py`).
This file exists so the same modules can be installed as console scripts, which is
what makes `uvx` work:

    uvx --from git+https://github.com/KRoperUK/smeg-plus-patches smeg-patch-media --help
    uvx --from 'smeg-plus-patches[gui] @ git+https://github.com/KRoperUK/smeg-plus-patches' smeg-studio
"""
