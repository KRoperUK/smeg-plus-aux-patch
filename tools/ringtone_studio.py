#!/usr/bin/env python3
"""Ringtone Studio — a small Qt front-end for adapting SMEG+ ringtones and patches.

Two jobs in one window:

* **Ringtones** — point it at an extracted media partition, pick any audio file
  (mp3/ogg/flac/m4a/wav — anything ffmpeg reads) for a slot, and it converts it to
  exactly the format the head unit expects and drops it in place. Preview before you
  commit, and export the stock tones first if you want a backup.
* **Patches** — pick any of the bundled `patches/*.json` definitions (auto-switch,
  always-enable-AUX, sticky AUX, ...), tick the ones you want, and build a patched
  package copy. Multiple definitions are merged per variant; a conflicting address is
  reported rather than silently applied.

Requirements:
    pip install -r tools/requirements-gui.txt      # PySide6
    ffmpeg on PATH for non-WAV input (brew install ffmpeg)

Run:
    python3 tools/ringtone_studio.py

NOTE: this GUI has not been exercised on a machine with Qt available, so treat it as
untested. `tools/ringtones.py` and `tools/patch_smeg.py` (which it drives) are tested
by `tests/`.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    from ringtones import SLOTS, WAIT_DIR, RING_DIR, convert, describe  # noqa: E402
except ImportError:
    sys.exit("cannot import tools/ringtones.py — run this from the repository")

try:
    from PySide6.QtCore import Qt  # noqa: E402
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,  # noqa: E402
                                   QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                                   QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                                   QTableWidget, QTableWidgetItem, QTabWidget,
                                   QVBoxLayout, QWidget)
except ImportError:
    sys.exit("PySide6 is required:  pip install -r tools/requirements-gui.txt")

AUDIO_FILTER = "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma *.opus);;All files (*)"


# --------------------------------------------------------------------------- window

class Studio(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SMEG+ Ringtone Studio")
        self.resize(980, 620)

        self.tree = ""
        self.pkg = ""
        self.out = ""
        self.patch_boxes = {}

        tabs = QTabWidget(self)
        tabs.addTab(self._build_ringtones_tab(), "Ringtones")
        tabs.addTab(self._build_patches_tab(), "Patches")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    # ---------------------------------------------------------------- ringtones

    def _build_ringtones_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)

        row = QHBoxLayout()
        self.tree_label = QLabel("media tree: (not set)")
        pick = QPushButton("Open extracted media partition…")
        pick.clicked.connect(self.choose_tree)
        dump = QPushButton("Export stock tones…")
        dump.clicked.connect(self.export_stock)
        row.addWidget(pick)
        row.addWidget(dump)
        row.addWidget(self.tree_label, 1)
        v.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Slot", "Target file", "Expected format", "Current"])
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 190)
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)

        self.preview_label = QLabel("")
        v.addWidget(self.preview_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        v.addWidget(self.log)

        self.populate()
        return page

    def populate(self):
        keys = sorted(SLOTS, key=lambda k: (k.startswith("wait"), k))
        self.table.setRowCount(len(keys))
        for r, slot in enumerate(keys):
            rel, ch, rate = SLOTS[slot]
            path = os.path.join(self.tree, rel) if self.tree else ""
            current = describe(path) if path and os.path.exists(path) else "—"
            self.table.setItem(r, 0, QTableWidgetItem(slot))
            self.table.setItem(r, 1, QTableWidgetItem(rel))
            self.table.setItem(r, 2, QTableWidgetItem(
                "%d Hz, 16-bit, %s" % (rate, "mono" if ch == 1 else "stereo")))
            self.table.setItem(r, 3, QTableWidgetItem(current))

            choose = QPushButton("Choose…")
            choose.clicked.connect(lambda _=False, s=slot: self.choose_file(s))
            self.table.setCellWidget(r, 3, self._wrap(choose, current))
        self.tree_label.setText("media tree: %s" % (self.tree or "(not set)"))

    @staticmethod
    def _wrap(button, text):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(button)
        h.addWidget(QLabel(text), 1)
        return w

    def choose_tree(self):
        d = QFileDialog.getExistingDirectory(self, "Extracted media partition (contains ring_tones/)")
        if d:
            self.tree = d
            self.populate()

    def export_stock(self):
        if not self.tree:
            QMessageBox.warning(self, "No media tree", "Open an extracted media partition first.")
            return
        d = QFileDialog.getExistingDirectory(self, "Export stock tones to…")
        if not d:
            return
        n = 0
        for sub in (RING_DIR, WAIT_DIR):
            src = os.path.join(self.tree, sub)
            if not os.path.isdir(src):
                continue
            for f in sorted(os.listdir(src)):
                if f.lower().endswith(".wav"):
                    src_f = os.path.join(src, f)
                    open(os.path.join(d, f), "wb").write(open(src_f, "rb").read())
                    n += 1
        self.say("exported %d stock file(s) to %s" % (n, d))

    def choose_file(self, slot):
        if not self.tree:
            QMessageBox.warning(self, "No media tree", "Open an extracted media partition first.")
            return
        src, _ = QFileDialog.getOpenFileName(self, "Audio for %s" % slot, "", AUDIO_FILTER)
        if not src:
            return
        rel, ch, rate = SLOTS[slot]
        dst = os.path.join(self.tree, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            how = convert(src, dst, ch, rate)
        except SystemExit as e:                      # ringtones.py exits with a message
            QMessageBox.critical(self, "Conversion failed", str(e))
            return
        self.say("%s: %s -> %s (%s)\n  now %s" % (slot, src, rel, how, describe(dst)))
        self.populate()

    # ------------------------------------------------------------------ patches

    def _build_patches_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)

        box = QGroupBox("Patch definitions (patches/*.json)")
        g = QGridLayout(box)
        patch_dir = os.path.join(ROOT, "patches")
        for i, f in enumerate(sorted(os.listdir(patch_dir)) if os.path.isdir(patch_dir) else []):
            if not f.endswith(".json"):
                continue
            spec = json.load(open(os.path.join(patch_dir, f)))
            cb = QCheckBox("%s — %s" % (spec.get("name", f), f))
            cb.setToolTip(spec.get("description", ""))
            self.patch_boxes[os.path.join(patch_dir, f)] = cb
            g.addWidget(cb, i, 0)
        v.addWidget(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Source package:"))
        self.pkg_edit = QLineEdit()
        row.addWidget(self.pkg_edit, 2)
        b1 = QPushButton("Browse…"); b1.clicked.connect(lambda: self._pick_dir(self.pkg_edit))
        row.addWidget(b1)
        v.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Output folder:"))
        self.out_edit = QLineEdit()
        row.addWidget(self.out_edit, 2)
        b2 = QPushButton("Browse…"); b2.clicked.connect(lambda: self._pick_dir(self.out_edit))
        row.addWidget(b2)
        v.addLayout(row)

        build = QPushButton("Build patched package")
        build.clicked.connect(self.build)
        v.addWidget(build)

        self.plog = QPlainTextEdit()
        self.plog.setReadOnly(True)
        v.addWidget(self.plog)
        return page

    def _pick_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Choose folder")
        if d:
            edit.setText(d)

    def merged_spec(self):
        """Merge the ticked patch definitions into one spec, refusing conflicts."""
        chosen = [p for p, cb in self.patch_boxes.items() if cb.isChecked()]
        if not chosen:
            raise SystemExit("tick at least one patch definition")
        merged = {"name": "studio-merge", "variants": {}}
        seen = {}
        for path in chosen:
            spec = json.load(open(path))
            for variant, vdef in spec["variants"].items():
                dst = merged["variants"].setdefault(variant, {k: vdef[k] for k in
                                                              ("app_image", "inf", "smeg_inf",
                                                               "ctrl", "base")})
                dst.setdefault("patches", [])
                for p in vdef["patches"]:
                    key = (variant, p["addr"])
                    if key in seen and seen[key] != p["bytes"]:
                        raise SystemExit("conflict at %s %s: %s vs %s"
                                         % (variant, p["addr"], seen[key], p["bytes"]))
                    if key not in seen:
                        seen[key] = p["bytes"]
                        dst["patches"].append(p)
        return merged

    def build(self):
        src, out = self.pkg_edit.text().strip(), self.out_edit.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, "No package", "Choose the original package folder.")
            return
        if not out:
            QMessageBox.warning(self, "No output", "Choose an output folder.")
            return
        try:
            spec = self.merged_spec()
        except SystemExit as e:
            QMessageBox.warning(self, "Nothing to build", str(e))
            return

        tmp = os.path.join(out, "_studio-spec.json")
        os.makedirs(out, exist_ok=True)
        open(tmp, "w").write(json.dumps(spec, indent=2))
        cmd = [sys.executable, os.path.join(HERE, "patch_smeg.py"),
               "--src", src, "--out", out, "--patches", tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.plog.setPlainText("$ %s\n\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))
        if r.returncode == 0:
            self.plog.appendPlainText("\nOK — changed files written to %s" % out)
        else:
            self.plog.appendPlainText("\nFAILED (exit %d)" % r.returncode)

    # -------------------------------------------------------------------- utils

    def say(self, text):
        self.log.appendPlainText(text)


def main():
    app = QApplication(sys.argv)
    w = Studio()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
