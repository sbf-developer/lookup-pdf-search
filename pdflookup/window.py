from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStatusBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pdflookup.model import Document
from pdflookup.pdfio import index_pdf
from pdflookup.search import Match, Prepared, prepare, preview_text, search
from pdflookup.style import LIGHT, Theme, stylesheet, theme_for
from pdflookup.textutil import tokenize
from pdflookup.view import PageView, ResultDelegate, ResultList, make_logo


_ALL_DOCS = 10_000


def _session_file() -> Path:
    root = os.environ.get("PDFLOOKUP_SESSION_DIR")
    if root:
        return Path(root) / "session.json"
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    return base / "PdfLookup" / "session.json"


def _load_session() -> dict:
    path = _session_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_session(data: dict) -> None:
    path = _session_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _titlebar(widget, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4)
    except Exception:
        pass


class IndexThread(QThread):
    progress = Signal(str, int, int)
    file_ready = Signal(object)
    batch_done = Signal()

    def __init__(self, paths: list[str]):
        super().__init__()
        self.paths = paths
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for path in self.paths:
            if self._stop:
                break
            document = index_pdf(path, progress=self.progress.emit, should_stop=lambda: self._stop)
            if document is not None and not self._stop:
                self.file_ready.emit(document)
        self.batch_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lookup")
        self.setMinimumSize(960, 640)
        self.docs: list[Document] = []
        self.prepared: list[Prepared] = []
        self.known: set[str] = set()
        self.queue: list[str] = []
        self.active_path: str | None = None
        self.matches: list[Match] = []
        self._searched: list[Prepared] = []
        self.truncated = False
        self.last_ms = 0.0
        self.last_dir = ""
        self.thread: IndexThread | None = None
        self._closing = False
        self._shown = False
        self._had_geometry = False
        self._chip_group: QButtonGroup | None = None
        self.theme: Theme = LIGHT
        self.preview_chars = 220
        self.word_distance = 8
        self.show_results = True
        self.show_lookup = True
        self.results_side = "left"
        self.lookup_side = "right"
        self._widths = {"results": 420, "viewer": 620, "lookup": 380}

        self._build()
        self._shortcuts()
        self._restore()
        QApplication.instance().installEventFilter(self)

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QWidget()
        top.setObjectName("topBar")
        top.setFixedHeight(48)
        bar = QHBoxLayout(top)
        bar.setContentsMargins(12, 0, 12, 0)
        bar.setSpacing(8)
        self._logo = QIcon()
        for size in (16, 20, 24, 32, 48):
            self._logo.addPixmap(make_logo(size))
        self.setWindowIcon(self._logo)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("logo")
        self.logo_label.setFixedSize(20, 20)
        brand = QLabel("Lookup")
        brand.setObjectName("brand")
        identity = QWidget()
        identity.setObjectName("identity")
        identity_row = QHBoxLayout(identity)
        identity_row.setContentsMargins(0, 0, 0, 0)
        identity_row.setSpacing(7)
        identity_row.addWidget(self.logo_label)
        identity_row.addWidget(brand)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search words or a sentence")
        self.search.setClearButtonEnabled(True)
        mode = QFrame()
        mode.setObjectName("modeSwitch")
        mode_row = QHBoxLayout(mode)
        mode.setFixedHeight(32)
        mode_row.setContentsMargins(3, 3, 3, 3)
        mode_row.setSpacing(2)
        self.exact_btn = QPushButton("Exact")
        self.broad_btn = QPushButton("Broad")
        for button in (self.exact_btn, self.broad_btn):
            button.setCheckable(True)
            button.setFixedHeight(26)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            mode_row.addWidget(button)
        self.broad_btn.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.exact_btn, 0)
        self.mode_group.addButton(self.broad_btn, 1)
        self.mode_group.idClicked.connect(lambda _id: self._on_mode())
        self.add_btn = QPushButton("Add PDFs")
        self.add_btn.setObjectName("addButton")
        self.add_btn.setFixedHeight(32)
        self.add_btn.setFocusPolicy(Qt.NoFocus)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.open_files)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setFixedHeight(32)
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings)
        self.search.setFixedHeight(32)
        bar.addWidget(identity)
        bar.addSpacing(4)
        bar.addWidget(self.search, 1)
        bar.addWidget(mode)
        bar.addWidget(self.settings_btn)
        bar.addWidget(self.add_btn)
        root.addWidget(top)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        results_panel = QWidget()
        self.results_panel = results_panel
        results_panel.setObjectName("resultsPanel")
        results_panel.setMinimumWidth(300)
        left = QVBoxLayout(results_panel)
        left.setContentsMargins(12, 12, 8, 8)
        left.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("Results")
        title.setObjectName("panelTitle")
        self.count_label = QLabel("")
        self.count_label.setObjectName("count")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.count_label)
        left.addLayout(header)
        self.chip_host = QWidget()
        self.chip_host.setObjectName("chipHost")
        self.chip_row = QHBoxLayout(self.chip_host)
        self.chip_row.setContentsMargins(0, 0, 0, 0)
        self.chip_row.setSpacing(2)
        self.chip_scroll = QScrollArea()
        self.chip_scroll.setObjectName("chips")
        self.chip_scroll.setWidget(self.chip_host)
        self.chip_scroll.setWidgetResizable(False)
        self.chip_scroll.setFrameShape(QFrame.NoFrame)
        self.chip_scroll.setFixedHeight(36)
        self.chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chip_scroll.viewport().setAutoFillBackground(False)
        left.addWidget(self.chip_scroll)
        self.results = ResultList()
        self.results.setObjectName("results")
        self.delegate = ResultDelegate(self.results)
        self.results.setItemDelegate(self.delegate)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results.setVerticalScrollMode(ResultList.ScrollPerPixel)
        self.results.setUniformItemSizes(False)
        self.results.setMouseTracking(True)
        self.results.viewport().setMouseTracking(True)
        self.results.viewport().setAttribute(Qt.WA_Hover, True)
        self.results.setFocusPolicy(Qt.NoFocus)
        self.results.currentRowChanged.connect(self._show_current)
        left.addWidget(self.results, 1)

        self.viewer = PageView()
        self.viewer.setMinimumWidth(320)
        self.viewer.navigated.connect(self._on_page_nav)

        read_panel = QWidget()
        self.read_panel = read_panel
        read_panel.setObjectName("readPanel")
        read_panel.setMinimumWidth(280)
        right = QVBoxLayout(read_panel)
        right.setContentsMargins(18, 16, 16, 12)
        right.setSpacing(6)
        self.kicker = QLabel("LOOKUP")
        self.kicker.setObjectName("kicker")
        self.found_label = QLabel("Search")
        self.found_label.setObjectName("found")
        self.found_label.setWordWrap(True)
        self.found_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.echo_label = QLabel("A word, a sentence, or something you only half remember.")
        self.echo_label.setObjectName("echo")
        self.echo_label.setWordWrap(True)
        self.reader = QTextBrowser()
        self.reader.setObjectName("reader")
        self.reader.setOpenLinks(False)
        self.reader.setOpenExternalLinks(False)
        self.reader.setFrameShape(QFrame.NoFrame)
        self.reader.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reader.document().setDocumentMargin(2)
        self.source_label = QLabel("")
        self.source_label.setObjectName("source")
        self.source_label.setWordWrap(True)
        right.addWidget(self.kicker)
        right.addWidget(self.found_label)
        right.addWidget(self.echo_label)
        right.addSpacing(8)
        right.addWidget(self.reader, 1)
        right.addWidget(self.source_label)

        self.splitter.addWidget(results_panel)
        self.splitter.addWidget(self.viewer)
        self.splitter.addWidget(read_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([420, 620, 380])
        root.addWidget(self.splitter, 1)

        status = QStatusBar()
        self.setStatusBar(status)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(120)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status.addPermanentWidget(self.progress)
        status.showMessage("Add your textbook and slides")

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(40)
        self.search_timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        self.set_theme("light", save=False)
        self._idle_sidebar()
        self._enable_drops(self)

    def _shortcuts(self):
        bindings = (
            ("Ctrl+O", self.open_files),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+L", self._focus_search),
            ("Ctrl+B", self.toggle_mode),
            ("Ctrl+=", self.viewer.zoom_in),
            ("Ctrl++", self.viewer.zoom_in),
            ("Ctrl+-", self.viewer.zoom_out),
            ("Ctrl+0", self.viewer.fit_width),
            ("Ctrl+,", self.open_settings),
        )
        self._shortcut_objects = []
        for sequence, slot in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            self._shortcut_objects.append(shortcut)

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def toggle_mode(self):
        if self.broad_btn.isChecked():
            self.exact_btn.setChecked(True)
        else:
            self.broad_btn.setChecked(True)

    def _on_mode(self):
        if self.search.text().strip():
            self._run_search()
        else:
            self._idle_sidebar()
        self._save_session()

    def showEvent(self, event):
        super().showEvent(event)
        if self._shown:
            return
        self._shown = True
        _titlebar(self, self.theme.dark)
        if not self._had_geometry:
            self.resize(1280, 820)
            frame = self.frameGeometry()
            screen = self.screen().availableGeometry()
            frame.moveCenter(screen.center())
            self.move(frame.topLeft())
        self.search.setFocus()

    def closeEvent(self, event):
        self._closing = True
        self._save_session()
        if self.thread is not None and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(2000)
        self.viewer.close_all()
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type in (QEvent.DragEnter, QEvent.DragMove):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
        elif event_type == QEvent.Drop and event.mimeData().hasUrls():
            self.add_paths([url.toLocalFile() for url in event.mimeData().urls()])
            event.acceptProposedAction()
            return True
        if event_type != QEvent.KeyPress or QApplication.activeModalWidget() is not None:
            return super().eventFilter(obj, event)
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Up, Qt.Key_Down) and mods == Qt.NoModifier:
            self.move_result(-1 if key == Qt.Key_Up else 1)
            return True
        if key == Qt.Key_Escape and mods == Qt.NoModifier and self.search.text():
            self.search.clear()
            self.search.setFocus()
            return True
        text = event.text()
        if text and text.isprintable() and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            focus = QApplication.focusWidget()
            if focus is self.search or isinstance(focus, QLineEdit):
                return super().eventFilter(obj, event)
            self.search.setFocus()
            self.search.insert(text)
            return True
        return super().eventFilter(obj, event)

    def _enable_drops(self, widget: QWidget):
        widget.setAcceptDrops(True)
        for child in widget.findChildren(QWidget):
            child.setAcceptDrops(True)

    def open_files(self):
        start = self.last_dir or str(Path.home())
        paths, _selected = QFileDialog.getOpenFileNames(self, "Add PDFs", start, "PDF files (*.pdf)")
        if not paths:
            return
        self.last_dir = str(Path(paths[0]).parent)
        self.add_paths(paths)

    def add_paths(self, paths):
        if self._closing:
            return
        added = False
        capped = False
        for raw in paths:
            if not raw:
                continue
            path = Path(raw)
            files: list[Path] = []
            if path.is_dir():
                found = sorted(p for p in path.rglob("*") if p.suffix.lower() == ".pdf")
                if len(found) > 40:
                    capped = True
                    found = found[:40]
                files.extend(found)
            elif path.suffix.lower() == ".pdf" and path.is_file():
                files.append(path)
            for file_path in files:
                resolved = str(file_path.resolve())
                if resolved in self.known:
                    continue
                self.known.add(resolved)
                self.queue.append(resolved)
                added = True
        if capped:
            self.statusBar().showMessage("Opened the first 40 PDFs from that folder")
        if added:
            self._pump_queue()
            self._save_session()

    def remove_path(self, path: str):
        self.known.discard(path)
        self.queue = [item for item in self.queue if item != path]
        self.docs = [doc for doc in self.docs if doc.path != path]
        self.prepared = [item for item in self.prepared if item.doc.path != path]
        if self.active_path == path:
            self.active_path = None
        self.viewer.close_path(path)
        self._rebuild_chips()
        self._run_search()
        self._save_session()
        if not self.docs:
            self._set_status_idle()

    def _pump_queue(self):
        if self.thread is not None and self.thread.isRunning():
            return
        if not self.queue:
            return
        batch = self.queue
        self.queue = []
        self.progress.setRange(0, 0)
        self.progress.show()
        self.thread = IndexThread(batch)
        self.thread.progress.connect(self._on_progress)
        self.thread.file_ready.connect(self._on_file)
        self.thread.batch_done.connect(self._on_batch_done)
        self.thread.start()

    def _on_progress(self, name: str, page: int, total: int):
        if self._closing:
            return
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(page)
        self.statusBar().showMessage(f"Indexing {name}    {page} / {total}")

    def _on_file(self, doc: Document):
        if self._closing or doc.path not in self.known:
            return
        replaced = False
        for index, existing in enumerate(self.docs):
            if existing.path == doc.path:
                self.docs[index] = doc
                self.prepared[index] = prepare(doc)
                replaced = True
                break
        if not replaced:
            self.docs.append(doc)
            self.prepared.append(prepare(doc))
        self._rebuild_chips()
        if not self.viewer.path and doc.page_count:
            self.viewer.show_document(doc, 0, [], scroll=False)
        elif not doc.page_count:
            self.viewer.show_message(doc.error or "Couldn't open this PDF.")
        if self.search.text().strip():
            self._run_search()
        if not doc.has_text and doc.error:
            self.statusBar().showMessage(f"{doc.name}  —  {doc.error}")

    def _on_batch_done(self):
        self.thread = None
        if self._closing:
            return
        if self.queue:
            self._pump_queue()
            return
        self.progress.hide()
        if not self.search.text().strip():
            self._set_status_idle()

    def _rebuild_chips(self):
        while self.chip_row.count():
            item = self.chip_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._chip_group is not None:
            self._chip_group.deleteLater()
            self._chip_group = None
        if not self.docs:
            return
        group = QButtonGroup(self)
        group.setExclusive(True)
        self._chip_group = group
        all_btn = QPushButton("All")
        all_btn.setObjectName("chip")
        all_btn.setCheckable(True)
        all_btn.setFocusPolicy(Qt.NoFocus)
        all_btn.setCursor(Qt.PointingHandCursor)
        group.addButton(all_btn, _ALL_DOCS)
        self.chip_row.addWidget(all_btn)
        selected = all_btn
        for index, doc in enumerate(self.docs):
            label = doc.name if len(doc.name) <= 26 else doc.name[:24] + "…"
            if not doc.has_text:
                label += " · no text"
            button = QPushButton(label)
            button.setObjectName("chip")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(doc.error or doc.path)
            close = QPushButton("×")
            close.setObjectName("chipX")
            close.setFocusPolicy(Qt.NoFocus)
            close.setFixedSize(22, 28)
            close.setCursor(Qt.PointingHandCursor)
            close.setToolTip(f"Remove {doc.name}")
            close.clicked.connect(lambda _checked=False, path=doc.path: self.remove_path(path))
            group.addButton(button, index)
            self.chip_row.addWidget(button)
            self.chip_row.addWidget(close)
            if doc.path == self.active_path:
                selected = button
        if selected is all_btn:
            self.active_path = None
        group.blockSignals(True)
        selected.setChecked(True)
        group.blockSignals(False)
        group.idClicked.connect(self._on_chip)
        self.chip_row.addStretch(1)
        self.chip_host.adjustSize()
        self.chip_scroll.setWidget(self.chip_host)
        self._enable_drops(self)

    def _on_chip(self, button_id: int):
        if button_id == _ALL_DOCS:
            self.active_path = None
            self._run_search()
            return
        if button_id < 0 or button_id >= len(self.docs):
            return
        doc = self.docs[button_id]
        self.active_path = doc.path
        self._run_search()
        if self.search.text().strip() and self.matches:
            return
        if doc.page_count:
            self.viewer.show_document(doc, self.viewer.page if self.viewer.path == doc.path else 0, [], scroll=False)

    def _visible_prepared(self) -> list[Prepared]:
        if not self.active_path:
            return list(self.prepared)
        return [item for item in self.prepared if item.doc.path == self.active_path]

    def _run_search(self):
        if self._closing:
            return
        query = self.search.text().strip()
        prepared = self._visible_prepared()
        self._searched = prepared
        if not query:
            self.matches = []
            self.truncated = False
            self._fill_results()
            self._idle_sidebar()
            self.viewer.clear_highlights()
            self._set_status_idle()
            return
        if not prepared and self._indexing():
            self.matches = []
            self.truncated = False
            self._fill_results()
            self.found_label.setText(query)
            self.echo_label.setText("Indexing the PDFs.")
            self.reader.setHtml(_note("Search runs as soon as the text is ready.", self.theme))
            self.source_label.setText("")
            return
        if not prepared:
            self.matches = []
            self.truncated = False
            self._fill_results()
            self._show_match(None, 0)
            return
        mode = "broad" if self.broad_btn.isChecked() else "exact"
        result = search(prepared, query, mode, proximity=self.word_distance)
        self.matches = result.matches
        self.truncated = result.truncated
        self.last_ms = result.elapsed_ms
        self._fill_results()

    def _fill_results(self):
        self.results.blockSignals(True)
        self.results.clear()
        for index, match in enumerate(self.matches):
            doc = self._searched[match.doc_index].doc
            item = QListWidgetItem()
            item.setData(Qt.UserRole, index)
            item.setData(Qt.UserRole + 1, f"{doc.name}    ·    p. {match.page + 1}")
            item.setData(Qt.UserRole + 2, preview_text(doc, match, self.preview_chars))
            self.results.addItem(item)
        count = len(self.matches)
        if count:
            suffix = "+" if self.truncated else ""
            self.count_label.setText(f"1 / {count}{suffix}")
            self.results.setCurrentRow(0)
        elif self.search.text().strip() and self.docs and not self._indexing():
            self.count_label.setText("0")
        else:
            self.count_label.setText("")
        self.results.blockSignals(False)
        if count:
            self._show_current()
        elif self.search.text().strip():
            self._show_match(None, 0)

    def move_result(self, delta: int):
        count = self.results.count()
        if count <= 0:
            return
        row = self.results.currentRow()
        if row < 0:
            row = 0 if delta > 0 else count - 1
        else:
            row = min(count - 1, max(0, row + delta))
        self.results.setCurrentRow(row)
        item = self.results.item(row)
        if item is not None:
            self.results.scrollToItem(item)

    def _show_current(self, row: int | None = None):
        if row is None:
            row = self.results.currentRow()
        if row < 0 or row >= len(self.matches):
            return
        suffix = "+" if self.truncated else ""
        self.count_label.setText(f"{row + 1} / {len(self.matches)}{suffix}")
        self._show_match(self.matches[row], row)

    def _show_match(self, match: Match | None, row: int):
        query = self.search.text().strip()
        if match is None:
            self.viewer.clear_highlights()
            if not query:
                self._idle_sidebar()
                return
            if not self.docs:
                self.found_label.setText("No PDFs yet")
                self.echo_label.setText("Add the textbook and the slides first.")
                self.reader.setHtml(_note("Drop the files anywhere on the window, or use Add PDFs.", self.theme))
                self.source_label.setText("")
                return
            self.found_label.setText(query)
            if self.broad_btn.isChecked():
                self.echo_label.setText("Nothing in the open PDFs.")
                note = "Try fewer words. If the file says “no text”, it is a scan and cannot be searched."
            else:
                self.echo_label.setText("No exact match.")
                note = "Switch to Broad. A search for data mining will also find data mine."
            self.reader.setHtml(_note(note, self.theme))
            self.source_label.setText("")
            self.statusBar().showMessage("No matches")
            return
        doc = self._searched[match.doc_index].doc
        rects = [(doc.words[i].x0, doc.words[i].y0, doc.words[i].x1, doc.words[i].y1) for i in match.hits]
        self.viewer.show_document(doc, match.page, rects, scroll=True)
        found = _found_text(doc, match)
        self.found_label.setText(found)
        query_norm = " ".join(tokenize(query))
        found_norm = " ".join(tokenize(found))
        if query_norm and found_norm and query_norm != found_norm:
            self.echo_label.setText(f"Broad match for  {query}")
        elif self.broad_btn.isChecked():
            self.echo_label.setText("Broad search")
        else:
            self.echo_label.setText("Exact match")
        self.reader.setHtml(_sidebar_html(doc, match, self.theme, self.preview_chars))
        self.source_label.setText(f"{row + 1} of {len(self.matches)}     {doc.name}     p. {match.page + 1}")
        extra = "    showing the closest 200" if self.truncated else ""
        timing = "<1" if self.last_ms < 1 else f"{self.last_ms:.0f}"
        self.statusBar().showMessage(f"{len(self.matches)} matches    {timing} ms{extra}")

    def _on_page_nav(self, page: int):
        doc = self._doc_for_path(self.viewer.path)
        if doc is None or not doc.page_sizes:
            return
        rects = []
        row = self.results.currentRow()
        if 0 <= row < len(self.matches):
            match = self.matches[row]
            match_doc = self._searched[match.doc_index].doc
            if match_doc.path == doc.path and match.page == page:
                rects = [(match_doc.words[i].x0, match_doc.words[i].y0, match_doc.words[i].x1, match_doc.words[i].y1) for i in match.hits]
        self.viewer.show_document(doc, page, rects, scroll=bool(rects))

    def _doc_for_path(self, path: str) -> Document | None:
        for doc in self.docs:
            if doc.path == path:
                return doc
        return None

    def _idle_sidebar(self):
        self.kicker.setText("LOOKUP")
        self.found_label.setText("Search")
        self.echo_label.setText("A word, a sentence, or something you only half remember.")
        if self.broad_btn.isChecked():
            mode = "Broad is on. Words can sit near each other in either order, and close wordings count."
        else:
            mode = "Exact is on. The words must appear in the order you typed, within the distance set in Settings."
        self.reader.setHtml(
            _note(mode, self.theme)
            + f"<p style='color:{self.theme.muted}; font-size:13px;'>Quotes match that word only, so \"ERP\" does not match a longer word. Arrow keys move through hits. Each result shows a short preview, and this panel follows.</p>"
        )
        self.source_label.setText("")

    def _indexing(self) -> bool:
        running = self.thread is not None and self.thread.isRunning()
        return bool(self.queue) or running

    def _set_status_idle(self):
        if self.thread is not None and self.thread.isRunning():
            return
        count = len(self.docs)
        if count == 0:
            self.statusBar().showMessage("Add your textbook and slides")
            return
        words = sum(len(doc.words) for doc in self.docs)
        label = "PDF" if count == 1 else "PDFs"
        self.statusBar().showMessage(f"{count} {label}    {words:,} words    Up/Down hits    Ctrl+B mode    Ctrl+O add")

    def _apply_logo(self):
        mark = make_logo(40, on_dark=self.theme.dark)
        mark.setDevicePixelRatio(2)
        self.logo_label.setPixmap(mark)

    def set_theme(self, name: str, save: bool = True):
        self.theme = theme_for(name)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.theme)
            app.setWindowIcon(QIcon(self._logo))
        self.delegate.set_theme(self.theme)
        self.viewer.set_theme(self.theme)
        self._apply_logo()
        palette = self.reader.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(self.theme.reader_bg))
        palette.setColor(QPalette.ColorRole.Text, QColor(self.theme.text))
        self.reader.setPalette(palette)
        if self._shown:
            _titlebar(self, self.theme.dark)
        self._refresh_reading()
        if save:
            self._save_session()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def set_preview_chars(self, value: int, save: bool = True):
        self.preview_chars = max(80, min(480, int(value)))
        row = self.results.currentRow()
        self._fill_results()
        if row >= 0 and self.results.count():
            self.results.setCurrentRow(min(row, self.results.count() - 1))
        if save:
            self._save_session()

    def set_word_distance(self, value: int, save: bool = True):
        self.word_distance = max(0, min(20, int(value)))
        if self.search.text().strip():
            self._run_search()
        if save:
            self._save_session()

    def _refresh_reading(self):
        row = self.results.currentRow()
        if self.search.text().strip() and 0 <= row < len(self.matches):
            self._show_match(self.matches[row], row)
        elif self.search.text().strip():
            self._show_match(None, 0)
        else:
            self._idle_sidebar()

    def _capture_widths(self):
        names = {
            self.results_panel: "results",
            self.viewer: "viewer",
            self.read_panel: "lookup",
        }
        sizes = [int(value) for value in self.splitter.sizes()]
        for index, size in enumerate(sizes):
            widget = self.splitter.widget(index)
            if widget in names and size > 0 and widget.isVisible():
                self._widths[names[widget]] = size

    def _panel_order(self) -> list:
        left = []
        right = []
        (left if self.results_side == "left" else right).append(self.results_panel)
        (left if self.lookup_side == "left" else right).append(self.read_panel)
        if len(left) == 2:
            left = [self.results_panel, self.read_panel]
        if len(right) == 2:
            right = [self.read_panel, self.results_panel]
        return left + [self.viewer] + right

    def _apply_layout(self):
        order = self._panel_order()
        for index, widget in enumerate(order):
            self.splitter.insertWidget(index, widget)
            self.splitter.setStretchFactor(index, 1 if widget is self.viewer else 0)
        self.results_panel.setVisible(self.show_results)
        self.read_panel.setVisible(self.show_lookup)
        names = {
            self.results_panel: "results",
            self.viewer: "viewer",
            self.read_panel: "lookup",
        }
        viewer_width = self._widths["viewer"]
        if not self.show_results:
            viewer_width += self._widths["results"]
        if not self.show_lookup:
            viewer_width += self._widths["lookup"]
        sizes = []
        for widget in order:
            if widget is self.viewer:
                sizes.append(viewer_width)
            elif widget.isVisible():
                sizes.append(self._widths[names[widget]])
            else:
                sizes.append(0)
        self.splitter.setSizes(sizes)

    def set_panels(self, results: bool | None = None, lookup: bool | None = None, save: bool = True):
        self._capture_widths()
        if results is not None:
            self.show_results = bool(results)
        if lookup is not None:
            self.show_lookup = bool(lookup)
        self._apply_layout()
        if save:
            self._save_session()

    def set_sides(self, results: str | None = None, lookup: str | None = None, save: bool = True):
        self._capture_widths()
        if results in ("left", "right"):
            self.results_side = results
        if lookup in ("left", "right"):
            self.lookup_side = lookup
        self._apply_layout()
        if save:
            self._save_session()

    def _restore(self):
        data = _load_session()
        self.last_dir = data.get("directory") or ""
        if data.get("mode") == "exact":
            self.exact_btn.setChecked(True)
        else:
            self.broad_btn.setChecked(True)
        preview = data.get("preview_chars")
        if isinstance(preview, int):
            self.preview_chars = max(80, min(480, preview))
        distance = data.get("word_distance")
        if isinstance(distance, int):
            self.word_distance = max(0, min(20, distance))
        if isinstance(data.get("show_results"), bool):
            self.show_results = data["show_results"]
        if isinstance(data.get("show_lookup"), bool):
            self.show_lookup = data["show_lookup"]
        if data.get("results_side") in ("left", "right"):
            self.results_side = data["results_side"]
        if data.get("lookup_side") in ("left", "right"):
            self.lookup_side = data["lookup_side"]
        self.set_theme("dark" if data.get("theme") == "dark" else "light", save=False)
        widths = data.get("panel_widths")
        if isinstance(widths, dict):
            for key in ("results", "viewer", "lookup"):
                value = widths.get(key)
                if isinstance(value, int) and value > 0:
                    self._widths[key] = value
        else:
            sizes = data.get("splitter")
            if isinstance(sizes, list) and len(sizes) == 3 and all(isinstance(value, int) and value > 0 for value in sizes):
                self._widths = {"results": int(sizes[0]), "viewer": int(sizes[1]), "lookup": int(sizes[2])}
        self._apply_layout()
        geometry = data.get("geometry")
        if geometry:
            try:
                if self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii"))):
                    self._had_geometry = True
            except (ValueError, TypeError):
                self._had_geometry = False
        files = [path for path in data.get("files", []) if isinstance(path, str) and Path(path).is_file()]
        if files:
            self.add_paths(files)
        elif not self.search.text().strip():
            self._idle_sidebar()

    def _save_session(self):
        if self._closing and not self.known and not self.docs:
            return
        self._capture_widths()
        geometry = bytes(self.saveGeometry().toHex()).decode("ascii")
        _write_session(
            {
                "files": list(dict.fromkeys([doc.path for doc in self.docs] + list(self.known))),
                "mode": "broad" if self.broad_btn.isChecked() else "exact",
                "theme": self.theme.name,
                "preview_chars": self.preview_chars,
                "word_distance": self.word_distance,
                "show_results": self.show_results,
                "show_lookup": self.show_lookup,
                "results_side": self.results_side,
                "lookup_side": self.lookup_side,
                "panel_widths": dict(self._widths),
                "directory": self.last_dir,
                "geometry": geometry,
                "splitter": [self._widths["results"], self._widths["viewer"], self._widths["lookup"]],
            }
        )


def _note(text: str, theme: Theme) -> str:
    return f"<p style='color:{theme.soft}; font-size:14px;'>{html.escape(text)}</p>"


def _found_text(doc: Document, match: Match) -> str:
    words = [_plain(doc.words[index].text) for index in match.hits]
    if len(words) > 14:
        return " ".join(words[:14]) + " …"
    return " ".join(words)


def _plain(text: str) -> str:
    return text.rstrip(".!?")


def _snippet(doc: Document, match: Match) -> str:
    if match.sentence_index < 0 or match.sentence_index >= len(doc.sentences):
        return _found_text(doc, match)
    sentence = doc.sentences[match.sentence_index]
    words = [doc.words[index].text for index in range(sentence.word_start, sentence.word_end)]
    if len(words) <= 18:
        return " ".join(words)
    relative = match.hits[0] - sentence.word_start
    start = max(0, relative - 5)
    end = min(len(words), relative + 10)
    text = " ".join(words[start:end])
    if start:
        text = "… " + text
    if end < len(words):
        text += " …"
    return text


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") or text[:limit].rstrip()
    return clipped + "…"


def _sidebar_html(doc: Document, match: Match, theme: Theme, limit: int) -> str:
    hits = set(match.hits)
    if match.sentence_index < 0 or match.sentence_index >= len(doc.sentences):
        return _note("No surrounding text on this page.", theme)
    sentence = doc.sentences[match.sentence_index]
    shown, lead, trail = _focus_words(doc, sentence.word_start, sentence.word_end, hits, limit)
    sentence_html = _span(doc, shown, hits, theme, lead, trail)
    parts = [
        f"<p style='color:{theme.muted}; font-size:11px; margin:0 0 6px 0;'>IN THE TEXT</p>",
        f"<p style='font-size:16px; color:{theme.found}; margin:0 0 16px 0;'>{sentence_html}</p>",
    ]
    used = _words_width(doc, shown)
    remaining = limit - used
    following = []
    if match.sentence_index + 1 < len(doc.sentences) and remaining > 24:
        nxt = doc.sentences[match.sentence_index + 1]
        page_bit = ""
        if nxt.page != match.page:
            page_bit = f"<span style='color:{theme.muted};'>p. {nxt.page + 1}&nbsp;&nbsp;</span>"
        following.append(
            f"<p style='font-size:15px; color:{theme.soft}; margin:0 0 10px 0;'>{page_bit}{html.escape(_clip(nxt.text, remaining))}</p>"
        )
    if following:
        parts.append(f"<p style='color:{theme.muted}; font-size:11px; margin:0 0 6px 0;'>FOLLOWING</p>")
        parts.extend(following)
    else:
        parts.append(f"<p style='font-size:14px; color:{theme.muted};'>Nothing after this.</p>")
    return "".join(parts)


def _words_width(doc: Document, indices: list[int]) -> int:
    if not indices:
        return 0
    return sum(len(doc.words[index].text) for index in indices) + len(indices) - 1


def _focus_words(doc: Document, start: int, end: int, hits: set[int], limit: int) -> tuple[list[int], bool, bool]:
    indices = list(range(start, end))
    if not indices:
        return [], False, False
    if _words_width(doc, indices) <= limit:
        return indices, False, False
    if hits:
        shown = list(range(min(hits), max(hits) + 1))
    else:
        shown = [indices[0]]
    while _words_width(doc, shown) > limit and len(shown) > 1:
        if shown[0] not in hits:
            shown.pop(0)
        elif shown[-1] not in hits:
            shown.pop()
        else:
            shown.pop()
    for _ in range(end - start):
        grew = False
        if shown[0] > start:
            trial = [shown[0] - 1, *shown]
            if _words_width(doc, trial) <= limit:
                shown = trial
                grew = True
        if shown[-1] + 1 < end:
            trial = [*shown, shown[-1] + 1]
            if _words_width(doc, trial) <= limit:
                shown = trial
                grew = True
        if not grew:
            break
    return shown, shown[0] > start, shown[-1] < end - 1


def _span(doc: Document, indices: list[int], hits: set[int], theme: Theme, lead: bool, trail: bool) -> str:
    bits = ["…"] if lead else []
    for index in indices:
        text = html.escape(doc.words[index].text)
        if index in hits:
            text = f"<span style='background-color:{theme.hit_bg}; color:{theme.hit_fg};'>{text}</span>"
        bits.append(text)
    if trail:
        bits.append("…")
    return " ".join(bits)


class SettingsDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.setObjectName("settings")
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(8)
        title = QLabel("Settings")
        title.setObjectName("found")
        root.addWidget(title)

        appearance = QLabel("APPEARANCE")
        appearance.setObjectName("kicker")
        root.addSpacing(8)
        root.addWidget(appearance)
        switch = QFrame()
        switch.setObjectName("modeSwitch")
        switch.setFixedHeight(32)
        row = QHBoxLayout(switch)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.light_btn = QPushButton("Light")
        self.dark_btn = QPushButton("Dark")
        for button in (self.light_btn, self.dark_btn):
            button.setCheckable(True)
            button.setFixedHeight(26)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
        self.light_btn.setChecked(not window.theme.dark)
        self.dark_btn.setChecked(window.theme.dark)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.light_btn, 0)
        group.addButton(self.dark_btn, 1)
        group.idClicked.connect(self._on_theme)
        root.addWidget(switch)

        panels = QLabel("PANELS")
        panels.setObjectName("kicker")
        root.addSpacing(14)
        root.addWidget(panels)
        self.results_box = QCheckBox("Results")
        self.lookup_box = QCheckBox("Lookup")
        self.results_box.setChecked(window.show_results)
        self.lookup_box.setChecked(window.show_lookup)
        self.results_box.toggled.connect(lambda on: self.window.set_panels(results=on))
        self.lookup_box.toggled.connect(lambda on: self.window.set_panels(lookup=on))
        self.results_side = self._side_switch(window.results_side, lambda side: self.window.set_sides(results=side))
        self.lookup_side = self._side_switch(window.lookup_side, lambda side: self.window.set_sides(lookup=side))
        root.addLayout(self._panel_row(self.results_box, self.results_side))
        root.addLayout(self._panel_row(self.lookup_box, self.lookup_side))
        panels_hint = QLabel("Show each panel, and choose which side of the page it sits on.")
        panels_hint.setObjectName("muted")
        panels_hint.setWordWrap(True)
        root.addWidget(panels_hint)

        preview_kicker = QLabel("RESULT PREVIEW")
        preview_kicker.setObjectName("kicker")
        root.addSpacing(14)
        root.addWidget(preview_kicker)
        self.preview_value = QLabel()
        self.preview_value.setObjectName("muted")
        self.preview = QSlider(Qt.Horizontal)
        self.preview.setRange(80, 480)
        self.preview.setSingleStep(10)
        self.preview.setPageStep(20)
        self.preview.setValue(window.preview_chars)
        self.preview.setFixedHeight(28)
        self.preview.valueChanged.connect(self._on_preview)
        root.addWidget(self.preview)
        root.addWidget(self.preview_value)
        hint = QLabel("How much of the hit, and the sentence after it, shows in each result and in the lookup panel.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        distance_kicker = QLabel("WORD DISTANCE")
        distance_kicker.setObjectName("kicker")
        root.addSpacing(14)
        root.addWidget(distance_kicker)
        self.distance_value = QLabel()
        self.distance_value.setObjectName("muted")
        self.distance = QSlider(Qt.Horizontal)
        self.distance.setRange(0, 20)
        self.distance.setValue(window.word_distance)
        self.distance.setFixedHeight(28)
        self.distance.valueChanged.connect(self._on_distance)
        root.addWidget(self.distance)
        root.addWidget(self.distance_value)
        distance_hint = QLabel(
            "Exact keeps the order you typed. Broad also matches the other way around, and close wordings, as long as the words sit this close in one sentence."
        )
        distance_hint.setObjectName("muted")
        distance_hint.setWordWrap(True)
        root.addWidget(distance_hint)
        self._sync_labels()

    def _panel_row(self, box: QCheckBox, switch: QFrame) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(box, 1)
        row.addWidget(switch)
        return row

    def _side_switch(self, side: str, on_side) -> QFrame:
        switch = QFrame()
        switch.setObjectName("modeSwitch")
        switch.setFixedSize(148, 32)
        row = QHBoxLayout(switch)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        left = QPushButton("Left")
        right = QPushButton("Right")
        for button in (left, right):
            button.setCheckable(True)
            button.setFixedHeight(26)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
        left.setChecked(side != "right")
        right.setChecked(side == "right")
        group = QButtonGroup(switch)
        group.setExclusive(True)
        group.addButton(left, 0)
        group.addButton(right, 1)
        group.idClicked.connect(lambda button_id: on_side("right" if button_id == 1 else "left"))
        return switch

    def _sync_labels(self):
        chars = self.preview.value()
        words = self.distance.value()
        self.preview_value.setText(f"{chars} characters")
        if words == 0:
            self.distance_value.setText("Words must be next to each other")
        else:
            self.distance_value.setText(f"Up to {words} words between them")

    def _on_theme(self, button_id: int):
        self.window.set_theme("dark" if button_id == 1 else "light")

    def _on_preview(self, value: int):
        self._sync_labels()
        self.window.set_preview_chars(value)

    def _on_distance(self, value: int):
        self._sync_labels()
        self.window.set_word_distance(value)


def apply_theme(app: QApplication, theme: Theme | None = None) -> None:
    chosen = theme or LIGHT
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(stylesheet(chosen))
    app.setPalette(_palette(chosen))


def _palette(theme: Theme) -> QPalette:
    palette = QPalette()
    text = QColor(theme.text)
    muted = QColor(theme.muted)
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.bg))
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.search_bg))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.panel))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.button))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2f4f86"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.panel))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.placeholder))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
    return palette


def run():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Lookup")
    window = MainWindow()
    window.show()
    return app.exec()


def install_excepthook():
    def hook(exc_type, value, traceback_obj):
        import traceback

        text = "".join(traceback.format_exception(exc_type, value, traceback_obj))
        try:
            log = _session_file().parent / "error.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(text, encoding="utf-8")
        except OSError:
            pass
        app = QApplication.instance()
        if app is not None and exc_type is not KeyboardInterrupt:
            QMessageBox.critical(None, "Lookup", f"Something went wrong.\n\n{value}")
        sys.__excepthook__(exc_type, value, traceback_obj)

    sys.excepthook = hook
