#!/usr/bin/env python3

# /// script
# requires-python = ">=3.10"
# dependencies = ["PySide6>=6.6"]
# ///

"""Ringtone Studio — a Qt front-end for SMEG+ ring tones and firmware patches.

**Ringtones tab.** Shows every replaceable tone in the media partition, with its
current state. Per row you can preview it, overwrite it with any audio file
(mp3/ogg/flac/m4a/wav — anything ffmpeg reads), or restore the original that came in the
package. "Extract from package…" pulls the partition out of a package and stores the
originals as a backup, so restore always has something to go back to.

Previewing uses QtMultimedia (QSoundEffect) when available, and otherwise falls back to a
system player (`afplay` on macOS, `paplay`/`aplay` on Linux).

**Pack & patch tab.** Tick the `patches/*.json` definitions you want, point it at a
package and a media tree, and it writes a patched package: the application patches first,
then the media partition rebuild (tar, gzip, `system_ctrl.bin`, `system.bin.inf`, the
module manifest and the root manifest).

Requirements:
    .venv/bin/python tools/ringtone_studio.py       # PySide6 + ffmpeg already present
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    from ringtones import (SLOTS, WAIT_DIR, RING_DIR, convert, describe,  # noqa: E402
                        ring_names, set_ring_name)  # noqa: E402
except ImportError:
    sys.exit("cannot import tools/ringtones.py — run this from the repository")

try:
    import splash as splashmod  # noqa: E402
except ImportError:
    splashmod = None

try:
    from PySide6.QtCore import Qt, QUrl  # noqa: E402
    from PySide6.QtGui import QFont, QImage, QPixmap  # noqa: E402
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,  # noqa: E402
                                   QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                                   QLineEdit,
                                   QMessageBox, QPlainTextEdit, QPushButton, QStyle,
                                   QTabWidget,
                                   QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
except ImportError:
    sys.exit("PySide6 is required:  pip install -r tools/requirements-gui.txt")

# QtMultimedia ships in pyside6-addons and may be absent; fall back to a system player.
try:
    from PySide6.QtMultimedia import QSoundEffect  # noqa: E402
    HAVE_SOUNDEFFECT = True
except ImportError:
    QSoundEffect = None
    HAVE_SOUNDEFFECT = False

AUDIO_FILTER = "Audio (*.wav *.mp3 *.ogg *.flac *.m4a *.aac *.wma *.opus);;All files (*)"
MODULES = ("NAV", "AUDIO_BT", "AUDIO_BT_256")
DEFAULT_BACKUP = os.path.expanduser("~/smeg-test/backups")
ACCENT = "#0A84FF"

# Two palettes, so the app can follow the desktop instead of guessing. Qt reports the system
# scheme through styleHints().colorScheme(), which means there is no preference of our own to
# store and the app matches whatever else on the machine is doing.
LIGHT = {
    "bg": "#F5F6F8", "bg2": "#E9ECF1", "fg": "#1D1D1F", "dim": "#6E6E73", "faint": "#B0B3B8",
    "card": "#FFFFFF", "line": "#E4E6EA", "line2": "#D9DCE1", "hover": "#F0F1F4",
    "press": "#E6E8EC", "sel": "#E8F1FF", "ok": "#34C759",
}
DARK = {
    "bg": "#191A1F", "bg2": "#101116", "fg": "#F2F3F5", "dim": "#9A9CA3", "faint": "#6A6D74",
    "card": "#212328", "line": "#2E3036", "line2": "#3A3D44", "hover": "#2A2C32",
    "press": "#34373E", "sel": "#1E3A5F", "ok": "#30D158",
}

STYLE = """
QWidget {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {bg}, stop:1 {bg2});
    color: {fg};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QLabel#Title    {{ font-size: 24px; font-weight: 700; }}
QLabel#Subtitle {{ color: {dim}; font-size: 12px; }}
QLabel#Muted    {{ color: {faint}; }}
QLabel#Modified {{ color: {accent}; font-weight: 600; }}
QLabel#Original {{ color: {ok}; font-weight: 600; }}

QFrame#Card {{ background: {card}; border: 1px solid {line}; border-radius: 14px; }}

QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{ background: transparent; color: {dim}; padding: 9px 18px; margin-right: 4px;
               border: 0; border-bottom: 2px solid transparent; font-weight: 500; }}
QTabBar::tab:selected {{ color: {fg}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover:!selected {{ color: {fg}; }}

QPushButton {{ background: {card}; border: 1px solid {line2}; border-radius: 9px;
               padding: 6px 12px; min-height: 22px; }}
QPushButton:hover   {{ background: {hover}; }}
QPushButton:pressed {{ background: {press}; }}
QPushButton:disabled {{ color: {faint}; background: transparent; }}
QPushButton#Primary {{ background: {accent}; border: 1px solid {accent}; color: #FFFFFF;
                       font-weight: 600; }}
QPushButton#Primary:hover   {{ background: #0A78E8; border-color: #0A78E8; }}
QPushButton#Primary:pressed {{ background: #0968CC; border-color: #0968CC; }}
QPushButton#Primary:disabled {{ background: {line2}; border-color: {line2}; color: {faint}; }}

QLineEdit, QComboBox {{ background: {card}; border: 1px solid {line2}; border-radius: 9px;
                        padding: 7px 11px; color: {fg}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{ background: {card}; border: 1px solid {line};
                               selection-background-color: {sel}; selection-color: {fg}; }}

QTableWidget {{ background: {card}; border: 1px solid {line}; border-radius: 14px;
                gridline-color: transparent; selection-background-color: {sel};
                selection-color: {fg}; outline: 0; }}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {line}; }}
QHeaderView::section {{ background: {card}; color: {dim}; border: 0;
                        border-bottom: 1px solid {line}; padding: 9px; font-weight: 600;
                        font-size: 12px; }}

QPlainTextEdit {{ background: {card}; border: 1px solid {line}; border-radius: 14px;
                  padding: 9px; font-family: Menlo, monospace; font-size: 11px; color: {fg}; }}
QCheckBox {{ spacing: 8px; padding: 3px 0; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {line2}; border-radius: 5px;
                        background: {card}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {line2}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {card}; color: {fg}; border: 1px solid {line}; padding: 5px 8px; }}
"""


def stylesheet():
    """The stylesheet for the desktop's current colour scheme.

    Falls back to light if the API is unavailable, so this cannot stop the app starting.
    """
    dark = False
    try:
        from PySide6.QtGui import QGuiApplication
        dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception as exc:
        print(f"warning: failed to detect system colour scheme, using light theme: {exc}",
              file=sys.stderr)
    return STYLE.format(accent=ACCENT, **(DARK if dark else LIGHT))



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
        self.setWindowTitle("SMEG+ Patch Studio")
        self.resize(1120, 720)
        self.setMinimumSize(940, 600)

        self.tree = ""
        self.backup = DEFAULT_BACKUP
        self.patch_boxes = {}

        # audio preview
        self._preview_btns = {}
        self._playing_slot = None
        self._player = None
        self._ext_proc = None
        if HAVE_SOUNDEFFECT:
            self._player = QSoundEffect(self)
            self._player.setVolume(0.8)
            self._player.playingChanged.connect(self._on_playing_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        t = QLabel("Patch Studio")
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
        tabs.addTab(self._splash_tab(), "Brand logos")
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
            self._btn("Extract from package…", self.extract_from_package, icon=QStyle.SP_DriveHDIcon),
            self._btn("Open media tree…", self.choose_tree, icon=QStyle.SP_DirOpenIcon),
            self._btn("Export tones…", self.export_tones, icon=QStyle.SP_DialogSaveButton),
            self._btn("Backup folder…", self.choose_backup, icon=QStyle.SP_FileDialogNewFolder),
            self.tree_label,
        ])))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["SLOT", "FILE IN THE PARTITION", "EXPECTED",
                                              "STATE", "NAME IN THE PHONE UI", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((70, 215, 150, 80, 165)):
            self.table.setColumnWidth(i, w)
        v.addWidget(self.table, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(96)
        self.log.setPlaceholderText("Conversion and restore results appear here.")
        v.addWidget(self.log)

        self.populate()
        return page

    def _icon(self, pixmap):
        """A built-in Qt icon, so the UI ships no icon assets of its own."""
        return self.style().standardIcon(pixmap)

    def _btn(self, text, slot, primary=False, icon=None):
        """A button whose face is an icon. The label becomes its tooltip.

        An icon on its own says nothing, so every button keeps its wording in a tooltip
        and in the accessibility tree — screen readers and hovering both still get it.
        """
        b = QPushButton()
        if icon is not None:
            b.setIcon(self._icon(icon))
        else:
            b.setText(text)
        b.setToolTip(text)
        b.setAccessibleName(text)
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
        same = Path(cur).read_bytes() == Path(bck).read_bytes()
        return ("original", "#34C759") if same else ("modified", ACCENT)

    def populate(self):
        names = ring_names(self.tree) if self.tree else []
        keys = sorted(SLOTS, key=lambda k: (k.startswith("wait"), k))
        self._preview_btns = {}
        self.table.setRowCount(len(keys))
        for r, slot in enumerate(keys):
            rel, ch, rate = SLOTS[slot]
            state, colour = self.state_of(rel)
            cur = self.tone_path(rel)
            current = describe(cur) if cur and os.path.exists(cur) else "—"

            ui_name = "—"
            if slot.startswith("ring") and slot[4:].isdigit():
                i = int(slot[4:]) - 1
                if i < len(names):
                    ui_name = names[i]

            for col, text, colour2 in ((0, slot, "#1D1D1F"), (1, rel, "#1D1D1F"),
                                       (2, "%d Hz · 16-bit · %s" % (rate, "mono" if ch == 1 else "stereo"),
                                        "#B0B3B8"), (3, state, colour),
                                       (4, ui_name, "#1D1D1F")):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                if colour2:
                    item.setForeground(Qt.gray if colour2 == "#B0B3B8" else Qt.black)
                self.table.setItem(r, col, item)

            preview = QPushButton()
            preview.setIcon(self._icon(QStyle.SP_MediaPlay))
            preview.setToolTip("Play this tone")
            preview.setAccessibleName("Play this tone")
            preview.setEnabled(bool(cur) and os.path.exists(cur))
            preview.clicked.connect(lambda _=False, s=slot: self.preview_tone(s))
            self._preview_btns[slot] = preview

            choose = QPushButton()
            choose.setIcon(self._icon(QStyle.SP_DialogOpenButton))
            choose.setToolTip("Convert and install a different audio file")
            choose.setAccessibleName("Replace this tone")
            choose.setEnabled(bool(self.tree))
            choose.clicked.connect(lambda _=False, s=slot: self.choose_file(s))
            name_btn = QPushButton()
            name_btn.setIcon(self._icon(QStyle.SP_FileDialogDetailedView))
            name_btn.setToolTip("Change what the phone UI calls this ringtone")
            name_btn.setAccessibleName("Rename this tone")
            name_btn.setEnabled(bool(self.tree) and ui_name != "—")
            name_btn.clicked.connect(lambda _=False, s=slot: self.rename_tone(s))
            restore = QPushButton()
            restore.setIcon(self._icon(QStyle.SP_BrowserReload))
            restore.setToolTip("Put the original from the package backup back")
            restore.setAccessibleName("Restore the original tone")
            restore.setEnabled(bool(self.tree) and os.path.exists(self.backup_path(rel)))
            restore.clicked.connect(lambda _=False, s=slot: self.restore(s))
            cur_lbl = QLabel(current)
            cur_lbl.setObjectName("Muted" if current == "—" else "Original")

            w = QWidget()
            w.setStyleSheet("background: transparent;")
            h = QHBoxLayout(w)
            h.setContentsMargins(6, 0, 6, 0)
            h.setSpacing(6)
            h.addWidget(preview)
            h.addWidget(choose)
            h.addWidget(name_btn)
            h.addWidget(restore)
            h.addWidget(cur_lbl, 1)
            self.table.setCellWidget(r, 5, w)

        self.tree_label.setText(self.tree)
        self.backup_label.setText(self.backup)

    # ------------------------------------------------------------------ preview

    def preview_tone(self, slot):
        """Play the tone currently in a slot, or stop it if it is already playing."""
        rel = SLOTS[slot][0]
        path = self.tone_path(rel)
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Nothing to preview",
                                    "There is no file in the tree for %s yet." % rel)
            return
        if self._playing_slot == slot:
            self.stop_preview()
            return
        self.stop_preview()
        if self._player is not None:
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
            self._playing_slot = slot
            self._refresh_preview_buttons()
        else:
            self._play_external(path, slot)

    def _play_external(self, path, slot):
        """Fallback for when QtMultimedia is not installed."""
        if sys.platform == "darwin":
            cmd = ["afplay", path]
        elif sys.platform.startswith("linux"):
            cmd = ["paplay", path] if shutil.which("paplay") else ["aplay", "-q", path]
        else:
            cmd = None
        if not cmd or not shutil.which(cmd[0]):
            QMessageBox.information(
                self, "Playback unavailable",
                "Previewing needs QtMultimedia (\"pip install PySide6\") or a system "
                "audio player such as afplay or paplay.")
            return
        self._ext_proc = subprocess.Popen(cmd)
        self._playing_slot = slot
        self._refresh_preview_buttons()

    def stop_preview(self):
        """Stop any preview that is in flight."""
        if self._player is not None:
            self._player.stop()
        if self._ext_proc is not None and self._ext_proc.poll() is None:
            self._ext_proc.terminate()
        self._ext_proc = None
        self._playing_slot = None
        self._refresh_preview_buttons()

    def _on_playing_changed(self):
        # QSoundEffect tells us when it finishes (or fails), so the button can revert.
        if self._player is not None and not self._player.isPlaying() and self._playing_slot:
            self._playing_slot = None
            self._refresh_preview_buttons()

    def _refresh_preview_buttons(self):
        for slot, btn in self._preview_btns.items():
            playing = slot == self._playing_slot
            btn.setIcon(self._icon(QStyle.SP_MediaStop if playing
                                   else QStyle.SP_MediaPlay))
            btn.setStyleSheet("font-weight: 600;" if playing else "")
            btn.setToolTip("Stop preview" if playing else "Play this tone")
            btn.setAccessibleName(btn.toolTip())

    def closeEvent(self, event):
        self.stop_preview()
        super().closeEvent(event)

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
                    Path(os.path.join(d, f)).write_bytes(Path(os.path.join(src, f)).read_bytes())
                    n += 1
        self.say("exported %d file(s) to %s" % (n, d))

    def choose_file(self, slot):
        self.stop_preview()
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
        self.stop_preview()
        rel, _ch, _rate = SLOTS[slot]
        bck = self.backup_path(rel)
        if not os.path.exists(bck):
            QMessageBox.warning(self, "No backup", "No stored original for %s." % rel)
            return
        dst = self.tone_path(rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        Path(dst).write_bytes(Path(bck).read_bytes())
        self.say("restored %s from the package backup" % rel)
        self.populate()

    def rename_tone(self, slot):
        """Change the name the phone UI shows. That is a row in up_common.sqlite, not the
        WAV — replacing a tone changes what you hear, renaming changes what you see."""
        if not (slot.startswith("ring") and slot[4:].isdigit()):
            return
        idx = int(slot[4:]) - 1
        names = ring_names(self.tree)
        if idx >= len(names):
            QMessageBox.information(self, "No name",
                                    "This media tree has no name for that slot.")
            return
        new, ok = QInputDialog.getText(
            self, "Rename %s" % slot, "Name shown in the phone UI:", text=names[idx])
        if not ok or not new.strip():
            return
        try:
            set_ring_name(self.tree, idx, new.strip())
        except SystemExit as e:
            QMessageBox.critical(self, "Could not rename", str(e))
            return
        self.say("%s is now shown as %r (was %r)" % (slot, new.strip(), names[idx]))
        self.say("  rebuild the package and re-seal for this to reach the car")
        self.populate()

    # --------------------------------------------------------------------- splash

    def _splash_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)

        self.splash_marque = QComboBox()
        self.splash_marque.addItems(list(splashmod.MARQUES) if splashmod else [])
        self.splash_marque.currentTextChanged.connect(lambda _: self.splash_load())
        self.splash_label = QLabel("")
        self.splash_label.setObjectName("Subtitle")

        v.addWidget(card(row([
            QLabel("Marque"), self.splash_marque,
            self._btn("Import image…", self.splash_import, primary=True, icon=QStyle.SP_DialogOpenButton),
            self._btn("Export as PNG…", self.splash_export, icon=QStyle.SP_DialogSaveButton),
            self._btn("Open media tree…", self.choose_tree, icon=QStyle.SP_DirOpenIcon),
            self.splash_label,
        ])))

        split = QHBoxLayout()
        split.setSpacing(12)

        self.splash_table = QTableWidget(0, 3)
        self.splash_table.setHorizontalHeaderLabels(["#", "FILE IN THE PARTITION", "STORED"])
        self.splash_table.verticalHeader().setVisible(False)
        self.splash_table.setShowGrid(False)
        self.splash_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.splash_table.setSelectionMode(QTableWidget.SingleSelection)
        self.splash_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.splash_table.verticalHeader().setDefaultSectionSize(34)
        self.splash_table.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((34, 250, 100)):
            self.splash_table.setColumnWidth(i, w)
        self.splash_table.itemSelectionChanged.connect(self.splash_select)
        split.addWidget(self.splash_table, 1)

        self.splash_view = QLabel("select an image to preview it")
        self.splash_view.setObjectName("Muted")
        self.splash_view.setAlignment(Qt.AlignCenter)
        self.splash_view.setMinimumSize(400, 240)
        self.splash_view.setStyleSheet(
            "background:#FFFFFF;border:1px solid #E4E6EA;border-radius:12px;")
        split.addWidget(self.splash_view, 1)
        v.addLayout(split, 1)

        note = QLabel("Stored images are vertically mirrored — the unit flips them when "
                      "rendering, so the preview is shown flipped back. "
                      "Note: these are marque artwork, not the boot splash — see the docs.")
        note.setObjectName("Subtitle")
        note.setWordWrap(True)
        v.addWidget(note)

        self.splash_log = QPlainTextEdit()
        self.splash_log.setReadOnly(True)
        self.splash_log.setFixedHeight(80)
        self.splash_log.setPlaceholderText("Splash results appear here.")
        v.addWidget(self.splash_log)

        if splashmod is None:
            self.splash_say("tools/splash.py could not be imported — tab disabled")
        self.splash_load()
        return page

    def splash_say(self, text):
        self.splash_log.appendPlainText(text)

    def splash_marque_name(self):
        return self.splash_marque.currentText() or "peugeot"

    def splash_path(self):
        return os.path.join(self.tree, splashmod.DIR,
                            self.splash_marque_name() + ".pkg") if self.tree and splashmod else ""

    def splash_pkg(self):
        p = self.splash_path()
        if not p or not os.path.exists(p):
            return None, None
        raw = Path(p).read_bytes()
        return p, splashmod.Pkg(raw)

    def splash_load(self):
        self.splash_table.setRowCount(0)
        self.splash_view.setPixmap(QPixmap())
        self.splash_view.setText("select an image to preview it")
        if splashmod is None:
            return
        p, pk = self.splash_pkg()
        if pk is None:
            self.splash_label.setText("no package — open a media tree first")
            return
        self.splash_label.setText("%s  ·  %d images  ·  %s" % (
            os.path.basename(p), len(pk.chunks),
            "directory hash ok" if pk.check_hash() else "directory hash MISMATCH"))

        self.splash_table.setRowCount(len(pk.chunks))
        for i, c in enumerate(pk.chunks):
            name = pk.records[i][1] if i < len(pk.records) else "image%d" % i
            for col, text in ((0, str(i + 1)), (1, name), (2, "%d B" % (c.length + 3))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.splash_table.setItem(i, col, item)
        if pk.chunks:
            self.splash_table.selectRow(0)

    def splash_selected(self):
        row = self.splash_table.currentRow()
        return row if row >= 0 else None

    def splash_select(self):
        idx = self.splash_selected()
        if idx is None or splashmod is None:
            return
        _, pk = self.splash_pkg()
        if pk is None or idx >= len(pk.chunks):
            return
        try:
            shown = splashmod.flip_bmp(pk.image(idx))       # undo the stored mirror
        except SystemExit:
            shown = pk.image(idx)
        img = QImage.fromData(shown, "BMP")
        if img.isNull():
            self.splash_view.setText("could not decode this image")
            return
        self._splash_pixmap = QPixmap.fromImage(img)
        self._rescale_splash()

    def _rescale_splash(self):
        pix = getattr(self, "_splash_pixmap", None)
        if pix is None or pix.isNull():
            return
        avail = self.splash_view.size()
        self.splash_view.setPixmap(pix.scaled(max(avail.width() - 16, 100),
                                              max(avail.height() - 16, 100),
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_splash()

    def splash_import(self):
        idx = self.splash_selected()
        if idx is None:
            QMessageBox.information(self, "Pick a row", "Select the image to replace first.")
            return
        path, pk = self.splash_pkg()
        if pk is None:
            QMessageBox.information(self, "No package", "Open a media tree first.")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Image to use (scaled to %dx%d)" % (splashmod.IMAGE_W, splashmod.IMAGE_H),
            "", "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
        if not src:
            return
        try:
            bmp = splashmod.flip_bmp(splashmod.to_bmp(src))
        except SystemExit as e:
            QMessageBox.critical(self, "Could not use that image", str(e))
            return
        new = {i: pk.image(i) for i in range(len(pk.chunks))}
        new[idx] = bmp
        out = splashmod.build(pk, new)
        open(path, "wb").write(out)
        self.splash_say("replaced image %d with %s (%d -> %d bytes)"
                        % (idx + 1, os.path.basename(src), len(pk.raw), len(out)))
        self.splash_say("  remember: the package still has to be rebuilt and re-sealed")
        self.splash_load()
        self.splash_table.selectRow(idx)

    def splash_export(self):
        idx = self.splash_selected()
        _, pk = self.splash_pkg()
        if idx is None or pk is None:
            return
        name = pk.records[idx][1] if idx < len(pk.records) else "image%d" % idx
        dest, _ = QFileDialog.getSaveFileName(self, "Export as PNG",
                                              os.path.splitext(name)[0] + ".png", "PNG (*.png)")
        if not dest:
            return
        shown = splashmod.flip_bmp(pk.image(idx))
        img = QImage.fromData(shown, "BMP")
        if img.save(dest):
            self.splash_say("exported image %d to %s" % (idx + 1, dest))
        else:
            self.splash_say("could not write %s" % dest)

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
                              self._btn("Browse…", lambda: self._pick(self.pkg_edit), icon=QStyle.SP_DirOpenIcon),
                              self.mod_combo], spacing=10)))

        self.tree_edit = QLineEdit()
        self.tree_edit.setPlaceholderText("media tree to pack (must contain ring_tones/) — optional")
        v.addWidget(card(row([QLabel("Media tree"), self.tree_edit,
                              self._btn("Browse…", lambda: self._pick(self.tree_edit), icon=QStyle.SP_DirOpenIcon),
                              self._btn("Use open tree", self._use_open_tree, icon=QStyle.SP_BrowserReload)], spacing=10)))

        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("where the changed files are written")
        v.addWidget(card(row([QLabel("Output folder"), self.out_edit,
                              self._btn("Browse…", lambda: self._pick(self.out_edit), icon=QStyle.SP_DirOpenIcon)], spacing=10)))

        v.addWidget(self._btn("Build patched package", self.build, primary=True,
                              icon=QStyle.SP_DialogApplyButton))

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
    app.setStyleSheet(stylesheet())
    app.setFont(QFont(".AppleSystemUIFont", 13))
    w = Studio()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
