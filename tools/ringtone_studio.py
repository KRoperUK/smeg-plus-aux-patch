#!/usr/bin/env python3
"""Ringtone Studio — a small Qt front-end for adapting SMEG+ ringtones and patches.

Two jobs in one window:

* **Ringtones** — point it at an extracted media partition, pick any audio file
  (mp3/ogg/flac/m4a/wav — anything ffmpeg reads) for a slot, and it converts it to
  exactly the format the head unit expects and drops it in place. Export the stock
  tones first if you want a backup.
* **Patches** — pick any of the bundled `patches/*.json` definitions (auto-switch,
  always-enable-AUX, sticky AUX, ...), tick the ones you want, and build a patched
  package copy. Multiple definitions are merged per variant; a conflicting address is
  reported rather than silently applied.

Requirements:
    pip install -r tools/requirements-gui.txt      # PySide6
    ffmpeg on PATH for non-WAV input (brew install ffmpeg)

Run:
    .venv/bin/python tools/ringtone_studio.py
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
    from PySide6.QtGui import QFont  # noqa: E402
    from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame,  # noqa: E402
                                   QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                                   QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
                                   QTableWidget, QTableWidgetItem, QTabWidget,
                                   QVBoxLayout, QWidget)
except ImportError:
    sys.exit("PySide6 is required:  pip install -r tools/requirements-gui.txt")

AUDIO_FILTER = "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma *.opus);;All files (*)"

ACCENT = "#0A84FF"
DANGER = "#FF453A"

STYLE = f"""
QWidget {{
    background: #F5F6F8;
    color: #1D1D1F;
    font-size: 13px;
}}
QLabel#Title    {{ font-size: 22px; font-weight: 600; }}
QLabel#Subtitle {{ color: #6E6E73; font-size: 12px; }}
QLabel#Section  {{ font-weight: 600; font-size: 12px; color: #6E6E73; }}

QFrame#Card {{
    background: #FFFFFF;
    border: 1px solid #E4E6EA;
    border-radius: 12px;
}}

QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{
    background: transparent;
    color: #6E6E73;
    padding: 8px 16px;
    margin-right: 4px;
    border: 0;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}
QTabBar::tab:selected {{ color: #1D1D1F; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: #1D1D1F; }}

QPushButton {{
    background: #FFFFFF;
    border: 1px solid #D9DCE1;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 20px;
}}
QPushButton:hover   {{ background: #F0F1F4; }}
QPushButton:pressed {{ background: #E6E8EC; }}
QPushButton:disabled {{ color: #B0B3B8; }}

QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#Primary:hover   {{ background: #0A78E8; border-color: #0A78E8; }}
QPushButton#Primary:pressed {{ background: #0968CC; border-color: #0968CC; }}

QLineEdit {{
    background: #FFFFFF;
    border: 1px solid #D9DCE1;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QTableWidget {{
    background: #FFFFFF;
    border: 1px solid #E4E6EA;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: #E8F1FF;
    selection-color: #1D1D1F;
    outline: 0;
}}
QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #F0F1F4; }}
QHeaderView::section {{
    background: #FFFFFF;
    color: #6E6E73;
    border: 0;
    border-bottom: 1px solid #E4E6EA;
    padding: 8px;
    font-weight: 600;
    font-size: 12px;
}}
QTableCornerButton::section {{ background: #FFFFFF; border: 0; }}

QPlainTextEdit {{
    background: #FFFFFF;
    border: 1px solid #E4E6EA;
    border-radius: 12px;
    padding: 8px;
    font-family: "SF Mono", Menlo, monospace;
    font-size: 11px;
}}

QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #C7CBD1;
    border-radius: 5px;
    background: #FFFFFF;
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #D2D5DA; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #B9BDC4; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def card(inner, spacing=10, margins=(16, 14, 16, 16)):
    """Wrap a widget or a layout in a rounded white card."""
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    if isinstance(inner, QWidget):
        lay.addWidget(inner)
    else:
        lay.addLayout(inner)
    return f


def hline(inner=None, spacing=8):
    h = QHBoxLayout()
    h.setSpacing(spacing)
    if inner:
        for w in inner:
            h.addWidget(w)
    return h


class Studio(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SMEG+ Ringtone Studio")
        self.resize(1040, 680)
        self.setMinimumSize(900, 560)

        self.tree = ""
        self.patch_boxes = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("Ringtone Studio")
        title.setObjectName("Title")
        sub = QLabel("Custom ring tones for a PSA/Stellantis SMEG+ head unit, and the patch builder.")
        sub.setObjectName("Subtitle")
        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(title)
        header.addWidget(sub)
        root.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._ringtones_tab(), "Ringtones")
        tabs.addTab(self._patches_tab(), "Patches")
        root.addWidget(tabs, 1)

    # ------------------------------------------------------------------ ringtones

    def _ringtones_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)

        pick = QPushButton("Open extracted media partition…")
        pick.clicked.connect(self.choose_tree)
        dump = QPushButton("Export stock tones…")
        dump.clicked.connect(self.export_stock)
        self.tree_label = QLabel("no media tree selected")
        self.tree_label.setObjectName("Subtitle")
        row = hline([pick, dump])
        row.addStretch(1)
        row.addWidget(self.tree_label)
        v.addWidget(card(row))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["SLOT", "TARGET FILE", "EXPECTED", "CURRENT"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((110, 250, 190)):
            self.table.setColumnWidth(i, w)
        v.addWidget(self.table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        self.log.setPlaceholderText("Conversion results will appear here.")
        v.addWidget(self.log)

        self.populate()
        return page

    def populate(self):
        keys = sorted(SLOTS, key=lambda k: (k.startswith("wait"), k))
        self.table.setRowCount(len(keys))
        for r, slot in enumerate(keys):
            rel, ch, rate = SLOTS[slot]
            path = os.path.join(self.tree, rel) if self.tree else ""
            present = bool(path) and os.path.exists(path)
            current = describe(path) if present else "—"

            for col, text in ((0, slot), (1, rel),
                              (2, "%d Hz · 16-bit · %s" % (rate, "mono" if ch == 1 else "stereo"))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                if col == 2:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, col, item)

            btn = QPushButton("Choose…")
            btn.setEnabled(bool(self.tree))
            btn.clicked.connect(lambda _=False, s=slot: self.choose_file(s))
            lbl = QLabel(current)
            if present:
                lbl.setStyleSheet("color:#1D1D1F;")
            else:
                lbl.setStyleSheet("color:#B0B3B8;")
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 0, 8, 0)
            h.setSpacing(10)
            h.addWidget(btn)
            h.addWidget(lbl, 1)
            self.table.setCellWidget(r, 3, w)

        self.tree_label.setText(self.tree or "no media tree selected")

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
                    open(os.path.join(d, f), "wb").write(open(os.path.join(src, f), "rb").read())
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
        self.say("%s → %s  (%s)\n  now %s" % (slot, rel, how, describe(dst)))
        self.populate()

    # -------------------------------------------------------------------- patches

    def _patches_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)

        self.patch_boxes = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        patch_dir = os.path.join(ROOT, "patches")
        files = sorted(f for f in os.listdir(patch_dir) if f.endswith(".json")) \
            if os.path.isdir(patch_dir) else []
        for i, f in enumerate(files):
            spec = json.load(open(os.path.join(patch_dir, f)))
            cb = QCheckBox(spec.get("name", f))
            cb.setToolTip(spec.get("description", ""))
            name = QLabel(f)
            name.setObjectName("Subtitle")
            grid.addWidget(cb, i, 0)
            grid.addWidget(name, i, 1)
            self.patch_boxes[os.path.join(patch_dir, f)] = cb
        grid.setColumnStretch(1, 1)
        v.addWidget(card(grid))

        def picker(edit):
            b = QPushButton("Browse…")
            b.clicked.connect(lambda: self._pick_dir(edit))
            return b

        self.pkg_edit = QLineEdit()
        self.pkg_edit.setPlaceholderText("original package folder, e.g. ~/Downloads/SMEG_PLUS_UPG")
        v.addWidget(card(hline([QLabel("Source package"), self.pkg_edit, picker(self.pkg_edit)],
                              spacing=10)))

        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("where the changed files should be written")
        v.addWidget(card(hline([QLabel("Output folder"), self.out_edit, picker(self.out_edit)],
                              spacing=10)))

        build = QPushButton("Build patched package")
        build.setObjectName("Primary")
        build.clicked.connect(self.build)
        v.addWidget(build)

        self.plog = QPlainTextEdit()
        self.plog.setReadOnly(True)
        self.plog.setPlaceholderText("Build output will appear here.")
        v.addWidget(self.plog, 1)
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
                dst = merged["variants"].setdefault(variant, {
                    k: vdef[k] for k in ("app_image", "inf", "smeg_inf", "ctrl", "base")})
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

        os.makedirs(out, exist_ok=True)
        tmp = os.path.join(out, "_studio-spec.json")
        open(tmp, "w").write(json.dumps(spec, indent=2))
        cmd = [sys.executable, os.path.join(HERE, "patch_smeg.py"),
               "--src", src, "--out", out, "--patches", tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.plog.setPlainText("$ %s\n\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))
        self.plog.appendPlainText("\nOK — changed files written to %s" % out
                                  if r.returncode == 0 else
                                  "\nFAILED (exit %d)" % r.returncode)

    def say(self, text):
        self.log.appendPlainText(text)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont(".AppleSystemUIFont", 13))
    w = Studio()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
