#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = ["PySide6>=6.6"]
# ///

"""Ringtone Studio — a Qt front-end for SMEG+ ring tones and firmware patches.

**Ringtones tab.** Shows every replaceable tone in the media partition, with its
current state. Per row you can overwrite it with any audio file (mp3/ogg/flac/m4a/wav —
anything ffmpeg reads), or restore the original that came in the package. "Extract from
package…" pulls the partition out of a package and stores the originals as a backup, so
restore always has something to go back to.

**Pack & patch tab.** Tick the `patches/*.json` definitions you want, point it at a
package and a media tree, and it writes a patched package: the application patches first,
then the media partition rebuild (tar, gzip, `system_ctrl.bin`, `system.bin.inf`, the
module manifest and the root manifest).

Requirements:
    .venv/bin/python tools/ringtone_studio.py       # PySide6 + ffmpeg already present
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
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,  # noqa: E402
                                   QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                                   QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
                                   QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
except ImportError:
    sys.exit("PySide6 is required:  pip install -r tools/requirements-gui.txt")

AUDIO_FILTER = "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma *.opus);;All files (*)"
MODULES = ("NAV", "AUDIO_BT", "AUDIO_BT_256")
DEFAULT_BACKUP = os.path.expanduser("~/smeg-test/backups")
ACCENT = "#0A84FF"

STYLE = f"""
QWidget {{ background: #F5F6F8; color: #1D1D1F; font-size: 13px; }}
QLabel {{ background: transparent; }}
QLabel#Title    {{ font-size: 22px; font-weight: 600; }}
QLabel#Subtitle {{ color: #6E6E73; font-size: 12px; }}
QLabel#Muted    {{ color: #B0B3B8; }}
QLabel#Modified {{ color: {ACCENT}; font-weight: 600; }}
QLabel#Original {{ color: #34C759; font-weight: 600; }}

QFrame#Card {{ background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 12px; }}

QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; color: #6E6E73; padding: 8px 16px; margin-right: 4px;
               border: 0; border-bottom: 2px solid transparent; font-weight: 500; }}
QTabBar::tab:selected {{ color: #1D1D1F; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: #1D1D1F; }}

QPushButton {{ background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 8px;
               padding: 5px 12px; min-height: 20px; }}
QPushButton:hover   {{ background: #F0F1F4; }}
QPushButton:pressed {{ background: #E6E8EC; }}
QPushButton:disabled {{ color: #B0B3B8; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: #FFFFFF;
                       font-weight: 600; }}
QPushButton#Primary:hover   {{ background: #0A78E8; border-color: #0A78E8; }}
QPushButton#Primary:pressed {{ background: #0968CC; border-color: #0968CC; }}

QLineEdit, QComboBox {{ background: #FFFFFF; border: 1px solid #D9DCE1; border-radius: 8px;
                        padding: 6px 10px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}

QTableWidget {{ background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 12px;
                gridline-color: transparent; selection-background-color: #E8F1FF;
                selection-color: #1D1D1F; outline: 0; }}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid #F0F1F4; }}
QHeaderView::section {{ background: #FFFFFF; color: #6E6E73; border: 0;
                        border-bottom: 1px solid #E4E6EA; padding: 8px; font-weight: 600;
                        font-size: 12px; }}

QPlainTextEdit {{ background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 12px;
                  padding: 8px; font-family: Menlo, monospace; font-size: 11px; }}
QCheckBox {{ spacing: 8px; padding: 3px 0; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #C7CBD1; border-radius: 5px;
                        background: #FFFFFF; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #D2D5DA; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def card(inner, spacing=10, margins=(16, 14, 16, 16)):
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


def row(items, spacing=8):
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in items:
        h.addWidget(w) if isinstance(w, QWidget) else h.addLayout(w)
    return h


class Studio(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SMEG+ Ringtone Studio")
        self.resize(1120, 720)
        self.setMinimumSize(940, 600)

        self.tree = ""
        self.backup = DEFAULT_BACKUP
        self.patch_boxes = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        t = QLabel("Ringtone Studio")
        t.setObjectName("Title")
        s = QLabel("Custom ring tones for a PSA/Stellantis SMEG+ head unit, and the patch builder.")
        s.setObjectName("Subtitle")
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        tabs = QTabWidget()
        tabs.addTab(self._ringtones_tab(), "Ringtones")
        tabs.addTab(self._pack_tab(), "Pack & patch")
        root.addWidget(tabs, 1)

    # ------------------------------------------------------------------ ringtones

    def _ringtones_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)

        self.tree_label = QLineEdit()
        self.tree_label.setReadOnly(True)
        self.tree_label.setPlaceholderText("no media tree — use “Extract from package…”")
        self.backup_label = QLabel("")
        self.backup_label.setObjectName("Subtitle")

        v.addWidget(card(row([
            self._btn("Extract from package…", self.extract_from_package),
            self._btn("Open media tree…", self.choose_tree),
            self._btn("Export tones…", self.export_tones),
            self._btn("Backup folder…", self.choose_backup),
            self.tree_label,
        ])))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["SLOT", "FILE IN THE PARTITION", "EXPECTED", "STATE", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((100, 300, 180, 90)):
            self.table.setColumnWidth(i, w)
        v.addWidget(self.table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(96)
        self.log.setPlaceholderText("Conversion and restore results appear here.")
        v.addWidget(self.log)

        self.populate()
        return page

    def _btn(self, text, slot, primary=False):
        b = QPushButton(text)
        if primary:
            b.setObjectName("Primary")
        b.clicked.connect(slot)
        return b

    def tone_path(self, rel):
        return os.path.join(self.tree, rel) if self.tree else ""

    def backup_path(self, rel):
        return os.path.join(self.backup, self.module(), rel) if self.backup else ""

    def module(self):
        for mod in MODULES:
            if os.path.isdir(os.path.join(self.tree, RING_DIR)) or \
               os.path.isdir(os.path.join(self.backup, mod)):
                return mod
        return "NAV"

    def state_of(self, rel):
        """original / modified / no backup, by comparing the tree with the backup."""
        cur = self.tone_path(rel)
        if not cur or not os.path.exists(cur):
            return "no file", "#B0B3B8"
        bck = self.backup_path(rel)
        if not (bck and os.path.exists(bck)):
            return "no backup", "#B0B3B8"
        same = open(cur, "rb").read() == open(bck, "rb").read()
        return ("original", "#34C759") if same else ("modified", ACCENT)

    def populate(self):
        keys = sorted(SLOTS, key=lambda k: (k.startswith("wait"), k))
        self.table.setRowCount(len(keys))
        for r, slot in enumerate(keys):
            rel, ch, rate = SLOTS[slot]
            state, colour = self.state_of(rel)
            cur = self.tone_path(rel)
            current = describe(cur) if cur and os.path.exists(cur) else "—"

            for col, text, colour2 in ((0, slot, "#1D1D1F"), (1, rel, "#1D1D1F"),
                                       (2, "%d Hz · 16-bit · %s" % (rate, "mono" if ch == 1 else "stereo"),
                                        "#B0B3B8"), (3, state, colour)):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                if colour2:
                    item.setForeground(Qt.gray if colour2 == "#B0B3B8" else Qt.black)
                self.table.setItem(r, col, item)

            choose = QPushButton("Overwrite…")
            choose.setEnabled(bool(self.tree))
            choose.clicked.connect(lambda _=False, s=slot: self.choose_file(s))
            restore = QPushButton("Restore")
            restore.setEnabled(bool(self.tree) and os.path.exists(self.backup_path(rel)))
            restore.clicked.connect(lambda _=False, s=slot: self.restore(s))
            cur_lbl = QLabel(current)
            cur_lbl.setObjectName("Muted" if current == "—" else "Original")

            w = QWidget()
            w.setStyleSheet("background: transparent;")
            h = QHBoxLayout(w)
            h.setContentsMargins(6, 0, 6, 0)
            h.setSpacing(6)
            h.addWidget(choose)
            h.addWidget(restore)
            h.addWidget(cur_lbl, 1)
            self.table.setCellWidget(r, 4, w)

        self.tree_label.setText(self.tree)
        self.backup_label.setText(self.backup)

    # -------------------------------------------------------------- tree actions

    def extract_from_package(self):
        pkg = QFileDialog.getExistingDirectory(self, "Package root (contains NAV/ AUDIO_BT/)")
        if not pkg:
            return
        mod, ok = self._ask_module()
        if not ok:
            return
        tree = QFileDialog.getExistingDirectory(self, "Where should the media tree go?")
        if not tree:
            return
        backup = self.backup or DEFAULT_BACKUP
        cmd = [sys.executable, os.path.join(HERE, "patch_media.py"), "extract",
               "--package", pkg, "--module", mod, "--tree", tree, "--backup", backup]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.log.setPlainText("$ %s\n\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))
        if r.returncode != 0:
            QMessageBox.critical(self, "Extract failed", r.stderr or r.stdout)
            return
        self.tree = tree
        self.populate()

    def _ask_module(self):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getItem(self, "Module", "Which build from the package?", MODULES, 0, False)

    def choose_tree(self):
        d = QFileDialog.getExistingDirectory(self, "Media tree (contains ring_tones/)")
        if d:
            self.tree = d
            self.populate()

    def choose_backup(self):
        d = QFileDialog.getExistingDirectory(self, "Where the originals are kept")
        if d:
            self.backup = d
            self.populate()

    def export_tones(self):
        if not self.tree:
            QMessageBox.warning(self, "No media tree", "Extract or open one first.")
            return
        d = QFileDialog.getExistingDirectory(self, "Export the tones to…")
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
        self.say("exported %d file(s) to %s" % (n, d))

    def choose_file(self, slot):
        src, _ = QFileDialog.getOpenFileName(self, "Audio for %s" % slot, "", AUDIO_FILTER)
        if not src:
            return
        rel, ch, rate = SLOTS[slot]
        dst = self.tone_path(rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            how = convert(src, dst, ch, rate)
        except SystemExit as e:
            QMessageBox.critical(self, "Conversion failed", str(e))
            return
        self.say("%s → %s  (%s)\n  now %s" % (slot, rel, how, describe(dst)))
        self.populate()

    def restore(self, slot):
        rel, _ch, _rate = SLOTS[slot]
        bck = self.backup_path(rel)
        if not os.path.exists(bck):
            QMessageBox.warning(self, "No backup", "No stored original for %s." % rel)
            return
        dst = self.tone_path(rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(open(bck, "rb").read())
        self.say("restored %s from the package backup" % rel)
        self.populate()

    # ---------------------------------------------------------------------- pack

    def _pack_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)

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

        self.pkg_edit = QLineEdit()
        self.pkg_edit.setPlaceholderText("package root, e.g. ~/Downloads/SMEG_PLUS_UPG")
        self.mod_combo = QComboBox()
        self.mod_combo.addItems(MODULES)
        v.addWidget(card(row([QLabel("Source package"), self.pkg_edit,
                              self._btn("Browse…", lambda: self._pick(self.pkg_edit)),
                              self.mod_combo], spacing=10)))

        self.tree_edit = QLineEdit()
        self.tree_edit.setPlaceholderText("media tree to pack (must contain ring_tones/) — optional")
        v.addWidget(card(row([QLabel("Media tree"), self.tree_edit,
                              self._btn("Browse…", lambda: self._pick(self.tree_edit)),
                              self._btn("Use open tree", self._use_open_tree)], spacing=10)))

        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("where the changed files are written")
        v.addWidget(card(row([QLabel("Output folder"), self.out_edit,
                              self._btn("Browse…", lambda: self._pick(self.out_edit))], spacing=10)))

        v.addWidget(self._btn("Build patched package", self.build, primary=True))

        self.plog = QPlainTextEdit()
        self.plog.setReadOnly(True)
        self.plog.setPlaceholderText("Build output appears here.")
        v.addWidget(self.plog, 1)
        return page

    def _pick(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Choose folder")
        if d:
            edit.setText(d)

    def _use_open_tree(self):
        if self.tree:
            self.tree_edit.setText(self.tree)
            self.mod_combo.setCurrentText(self.module())

    def merged_spec(self):
        chosen = [p for p, cb in self.patch_boxes.items() if cb.isChecked()]
        if not chosen:
            return None
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
            QMessageBox.warning(self, "No package", "Choose the source package folder.")
            return
        if not out:
            QMessageBox.warning(self, "No output", "Choose an output folder.")
            return
        try:
            spec = self.merged_spec()
        except SystemExit as e:
            QMessageBox.warning(self, "Conflicting patches", str(e))
            return

        os.makedirs(out, exist_ok=True)
        log = []
        if spec:
            tmp = os.path.join(out, "_studio-spec.json")
            open(tmp, "w").write(json.dumps(spec, indent=2))
            log.append(self._run([sys.executable, os.path.join(HERE, "patch_smeg.py"),
                                  "--src", src, "--out", out, "--patches", tmp],
                                 "application patches"))
        tree = self.tree_edit.text().strip()
        if tree:
            log.append(self._run([sys.executable, os.path.join(HERE, "patch_media.py"), "apply",
                                  "--package", src, "--module", self.mod_combo.currentText(),
                                  "--tree", tree, "--out", out, "--ctrl-from", out],
                                 "media partition"))
        if not log:
            QMessageBox.information(self, "Nothing selected",
                                    "Tick a patch definition, or choose a media tree.")
            return
        self.plog.setPlainText("\n\n".join(log))

    def _run(self, cmd, title):
        r = subprocess.run(cmd, capture_output=True, text=True)
        head = "=== %s ===\n$ %s\n" % (title, " ".join(cmd))
        body = r.stdout + r.stderr
        return head + body + ("\nOK\n" if r.returncode == 0 else "\nFAILED (exit %d)\n" % r.returncode)

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
