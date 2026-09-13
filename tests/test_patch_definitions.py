"""The shipped patches/*.json must be well formed.

`tools/patch_smeg.py` reads these at flash-building time and a malformed one fails late,
against a real package, on a machine that has firmware. These checks need neither.
"""
import glob
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATCH_FILES = sorted(glob.glob(os.path.join(ROOT, "patches", "*.json")))
REQUIRED_VARIANT_KEYS = ("app_image", "inf", "smeg_inf", "ctrl", "base")


def load(path):
    with open(path) as fh:
        return json.load(fh)


def test_there_are_patch_definitions_to_check():
    assert PATCH_FILES, "no patches/*.json found"


@pytest.mark.parametrize("path", PATCH_FILES, ids=lambda p: os.path.basename(p))
def test_definition_has_a_name_and_description(path):
    spec = load(path)
    assert spec.get("name"), "every patch set needs a name"
    assert spec["name"] == os.path.basename(path)[:-len(".json")], \
        "the name should match the filename, so a build manifest reads unambiguously"
    assert len(spec.get("description", "")) > 40, \
        "the description is what tells a reader whether to flash this"


@pytest.mark.parametrize("path", PATCH_FILES, ids=lambda p: os.path.basename(p))
def test_every_variant_declares_the_files_its_cascade_touches(path):
    variants = load(path)["variants"]
    assert variants, "a patch set with no variants patches nothing"
    for module, variant in variants.items():
        for key in REQUIRED_VARIANT_KEYS:
            assert key in variant, "%s/%s is missing %r" % (path, module, key)
        assert variant["app_image"].startswith(module + "/"), \
            "%s: app_image should live under its own module directory" % module
        assert int(variant["base"], 16) == 0x01000000


@pytest.mark.parametrize("path", PATCH_FILES, ids=lambda p: os.path.basename(p))
def test_every_edit_is_hex_inside_the_image(path):
    for module, variant in load(path)["variants"].items():
        assert variant["patches"], "%s/%s has no edits" % (path, module)
        for edit in variant["patches"]:
            where = "%s/%s %s" % (os.path.basename(path), module, edit.get("addr"))
            addr = int(edit["addr"], 16)
            assert 0x01000000 <= addr < 0x04000000, "%s: outside the image" % where
            assert addr % 4 == 0, "%s: PowerPC instructions are 4-byte aligned" % where
            for field in ("expect", "bytes"):
                raw = edit[field]
                assert len(raw) % 2 == 0 and bytes.fromhex(raw), \
                    "%s: %s is not valid hex" % (where, field)
            assert len(edit["bytes"]) % 8 == 0, \
                "%s: replacement is not a whole number of instructions" % where


@pytest.mark.parametrize("path", PATCH_FILES, ids=lambda p: os.path.basename(p))
def test_edits_do_not_overlap_each_other(path):
    for module, variant in load(path)["variants"].items():
        written = {}
        for edit in variant["patches"]:
            addr = int(edit["addr"], 16)
            for offset in range(len(bytes.fromhex(edit["bytes"]))):
                byte = addr + offset
                assert byte not in written, \
                    "%s/%s: %08x is written by both %s and %s" % (
                        os.path.basename(path), module, byte, written[byte], edit["addr"])
                written[byte] = edit["addr"]


@pytest.mark.parametrize("path", PATCH_FILES, ids=lambda p: os.path.basename(p))
def test_diagnostic_sets_say_so_loudly(path):
    """A build that floods the log is not one to flash casually — the name must warn."""
    spec = load(path)
    if "diagnostic" not in spec["name"]:
        return
    assert "DIAGNOSTIC" in spec["description"], \
        "a diagnostic patch set must announce itself in its description"
