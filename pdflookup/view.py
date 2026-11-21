from __future__ import annotations

from collections import OrderedDict

# Qt has to load before MuPDF. On Windows the two ship overlapping DLLs,
# and importing MuPDF first crashes the process.
import PySide6  # noqa: F401
import pymupdf as fitz
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from pdflookup.style import LIGHT, Theme

from pdflookup.model import Document

RENDER_BOOST = 2.0
_CACHE_LIMIT = 8


def make_logo(size: int = 32) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#3c6df0"))
    radius = size * 0.28
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.5, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    glass = size * 0.40
    origin_x = size * 0.22
    origin_y = size * 0.18
    painter.drawEllipse(QRectF(origin_x, origin_y, glass, glass))
    painter.drawLine(
        int(origin_x + glass * 0.76),
        int(origin_y + glass * 0.76),
        int(origin_x + glass * 1.28),
        int(origin_y + glass * 1.28),
    )
    painter.end()
    return pixmap


def empty_html(theme: Theme) -> str:
    return f"""
<div style="text-align:center; font-family:'Segoe UI',sans-serif;">
<p style="color:{theme.empty_title}; font-size:22px;">Drop PDFs here</p>
<p style="color:{theme.muted}; font-size:14px;">Textbook and slides. Search starts as soon as they index.</p>
<p style="color:{theme.muted}; font-size:13px;">
Up and Down move through hits<br>
Ctrl+O adds PDFs<br>
Ctrl+B switches Exact and Broad<br>
Ctrl+F focuses search
</p>
</div>
"""


def merge_hit_rects(rects: list[tuple[float, float, float, float]]):
    if not rects:
        return []
    ordered = sorted(rects, key=lambda rect: (round(rect[1], 1), rect[0]))
    merged = [list(ordered[0])]
    for x0, y0, x1, y1 in ordered[1:]:
        px0, py0, px1, py1 = merged[-1]
        same_line = abs(y0 - py0) < 3 and abs((y1 - y0) - (py1 - py0)) < 4
        close = x0 <= px1 + 8
        if same_line and close:
            merged[-1] = [min(px0, x0), min(py0, y0), max(px1, x1), max(py1, y1)]
        else:
            merged.append([x0, y0, x1, y1])
    return [tuple(rect) for rect in merged]


class ResultList(QListWidget):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.doItemsLayout()


class ResultDelegate(QStyledItemDelegate):
    def __init__(self, view: QListWidget):
        super().__init__(view)
        self.view = view
        self.theme = LIGHT

    def set_theme(self, theme: Theme):
        self.theme = theme
        self.view.viewport().update()

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = option.rect.adjusted(4, 2, -4, -2)
        if option.state & QStyle.State_Selected:
            painter.setBrush(QColor(self.theme.select))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
        elif option.state & QStyle.State_MouseOver:
            painter.setBrush(QColor(self.theme.hover))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
        title = index.data(Qt.UserRole + 1) or ""
        snippet = index.data(Qt.UserRole + 2) or ""
        text_rect = rect.adjusted(10, 8, -10, -8)
        title_font = QFont(painter.font())
        title_font.setPointSizeF(9)
        painter.setFont(title_font)
        painter.setPen(QColor(self.theme.title))
        painter.drawText(QRect(text_rect.left(), text_rect.top(), text_rect.width(), 16), Qt.AlignLeft | Qt.AlignVCenter, title)
        body_font = QFont(painter.font())
        body_font.setPointSizeF(10.5)
        painter.setFont(body_font)
        painter.setPen(QColor(self.theme.body))
        snippet_rect = QRect(text_rect.left(), text_rect.top() + 18, text_rect.width(), max(16, text_rect.height() - 18))
        painter.drawText(snippet_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, snippet)
        painter.restore()

    def sizeHint(self, option, index):
        snippet = index.data(Qt.UserRole + 2) or ""
        width = max(80, self.view.viewport().width() - 36)
        body = QFont(option.font)
        body.setPointSizeF(10.5)
        bounds = QFontMetrics(body).boundingRect(QRect(0, 0, width, 2000), Qt.TextWordWrap, snippet)
        return QSize(width, 18 + 16 + bounds.height() + 14)


class PageView(QWidget):
    navigated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("viewerPanel")
        self.path = ""
        self.page = 0
        self.page_count = 0
        self.page_sizes: list[tuple[float, float]] = []
        self._rects: list[tuple[float, float, float, float]] = []
        self._scroll_to_hit = False
        self.fit = True
        self.user_scale = 1.35
        self._render_scale = 1.35
        self._last_key = None
        self._cache: OrderedDict = OrderedDict()
        self._docs: dict = {}

        self._theme = LIGHT
        self.empty = QLabel()
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setTextFormat(Qt.RichText)
        self.empty.setText(empty_html(self._theme))
        self.empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignCenter)
        self.holder = QWidget()
        self.holder.setObjectName("viewerPanel")
        holder_layout = QVBoxLayout(self.holder)
        holder_layout.setContentsMargins(28, 22, 28, 28)
        holder_layout.addWidget(self.canvas, 0, Qt.AlignHCenter | Qt.AlignTop)
        holder_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.scroll.setWidget(self.holder)
        self.scroll.viewport().installEventFilter(self)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.scroll)
        self.stack.setObjectName("viewerPanel")

        self.footer = QFrame()
        self.footer.setObjectName("footer")
        self.footer.setFixedHeight(40)
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(8, 0, 8, 0)
        footer.setSpacing(2)
        self.prev_btn = self._tool("‹", "Previous page")
        self.next_btn = self._tool("›", "Next page")
        self.page_label = QLabel("No page")
        self.page_label.setObjectName("pageLabel")
        self.zoom_out_btn = self._tool("−", "Zoom out")
        self.fit_btn = self._tool("Fit", "Fit width")
        self.fit_btn.setCheckable(True)
        self.fit_btn.setChecked(True)
        self.zoom_in_btn = self._tool("+", "Zoom in")
        footer.addWidget(self.prev_btn)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next_btn)
        footer.addStretch(1)
        footer.addWidget(self.zoom_out_btn)
        footer.addWidget(self.fit_btn)
        footer.addWidget(self.zoom_in_btn)

        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.fit_btn.clicked.connect(self.fit_width)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.stack, 1)
        root.addWidget(self.footer)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._rerender)
        self._update_footer()

    def _tool(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tool")
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_theme(self, theme: Theme):
        self._theme = theme
        if not self.path:
            self.empty.setText(empty_html(theme))

    def show_message(self, text: str):
        self.path = ""
        self.page_count = 0
        self.page_sizes = []
        self._rects = []
        safe = (
            "<div style='text-align:center; font-family:Segoe UI,sans-serif;'>"
            f"<p style='color:{self._theme.soft}; font-size:15px;'>{_escape(text)}</p></div>"
        )
        self.empty.setText(safe)
        self.stack.setCurrentWidget(self.empty)
        self._update_footer()

    def show_empty(self):
        self.path = ""
        self.page_count = 0
        self.page_sizes = []
        self._rects = []
        self.empty.setText(empty_html(self._theme))
        self.stack.setCurrentWidget(self.empty)
        self._update_footer()

    def show_document(self, doc: Document, page: int, rects, scroll: bool):
        if doc.page_count <= 0:
            self.show_message(doc.error or "Couldn't open this PDF.")
            return
        self.path = doc.path
        self.page_sizes = list(doc.page_sizes)
        self.page_count = doc.page_count
        self.page = max(0, min(page, self.page_count - 1))
        self._rects = merge_hit_rects(list(rects))
        self._scroll_to_hit = bool(scroll and self._rects)
        self.stack.setCurrentWidget(self.scroll)
        self._update_footer()
        self._rerender()

    def clear_highlights(self):
        self._rects = []
        self._scroll_to_hit = False
        if self.path:
            self._rerender()

    def close_path(self, path: str):
        source = self._docs.pop(path, None)
        if source is not None:
            source.close()
        self._cache = OrderedDict(item for item in self._cache.items() if item[0][0] != path)
        if self.path == path:
            self.show_empty()

    def close_all(self):
        for source in self._docs.values():
            source.close()
        self._docs.clear()
        self._cache.clear()

    def zoom_in(self):
        self._set_user_scale(self._render_scale * 1.12)

    def zoom_out(self):
        self._set_user_scale(self._render_scale / 1.12)

    def fit_width(self):
        self.fit = True
        self.fit_btn.setChecked(True)
        self._last_key = None
        self._rerender()

    def _set_user_scale(self, scale: float):
        self.fit = False
        self.fit_btn.setChecked(False)
        self.user_scale = min(3.2, max(0.45, scale))
        self._last_key = None
        self._rerender()

    def _step(self, delta: int):
        if not self.page_count:
            return
        target = min(self.page_count - 1, max(0, self.page + delta))
        if target != self.page:
            self.navigated.emit(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit and self.path:
            self._fit_timer.start(40)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            return True
        return super().eventFilter(obj, event)

    def _current_scale(self) -> float:
        if not self.page_sizes:
            return 1.0
        width = self.page_sizes[self.page][0] or 612
        if self.fit:
            available = max(240, self.scroll.viewport().width() - 56)
            scale = available / width
        else:
            scale = self.user_scale
        return min(3.2, max(0.45, scale))

    def _rerender(self):
        if not self.path or not self.page_sizes:
            return
        scale = self._current_scale()
        key = (self.path, self.page, round(scale, 3), tuple(self._rects))
        if key == self._last_key:
            if self._scroll_to_hit:
                QTimer.singleShot(0, self._scroll_hit)
            return
        try:
            base = self._base_image(self.path, self.page, scale)
            if base.isNull():
                self.show_message("Couldn't draw this page.")
                return
            image = self._paint_highlights(base, self._rects, scale)
        except Exception as exc:
            self.show_message(f"Couldn't draw this page.\n{exc}")
            return
        self._render_scale = scale
        self._last_key = key
        dpr = image.devicePixelRatio() or 1
        self.canvas.setPixmap(QPixmap.fromImage(image))
        self.canvas.setFixedSize(int(image.width() / dpr), int(image.height() / dpr))
        self._update_footer()
        if self._scroll_to_hit:
            QTimer.singleShot(0, self._scroll_hit)

    def _scroll_hit(self):
        if not self._rects:
            return
        origin = self.canvas.pos()
        y = origin.y() + self._rects[0][1] * self._render_scale
        x = origin.x() + self._rects[0][0] * self._render_scale
        viewport = self.scroll.viewport()
        self.scroll.verticalScrollBar().setValue(max(0, int(y - viewport.height() * 0.22)))
        self.scroll.horizontalScrollBar().setValue(max(0, int(x - 40)))

    def _base_image(self, path: str, page: int, scale: float) -> QImage:
        key = (path, page, round(scale, 3))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        source = self._docs.get(path)
        if source is None:
            source = fitz.open(path)
            self._docs[path] = source
        pdf_page = source.load_page(page)
        matrix = fitz.Matrix(scale * RENDER_BOOST, scale * RENDER_BOOST)
        pix = pdf_page.get_pixmap(matrix=matrix, alpha=False)
        if pix.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if pix.width <= 0 or pix.height <= 0:
            return QImage()
        data = bytes(pix.samples)
        image = QImage(data, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        image.setDevicePixelRatio(RENDER_BOOST)
        self._cache[key] = image
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return image

    def _paint_highlights(self, base: QImage, rects, scale: float) -> QImage:
        if not rects:
            return base
        image = base.copy()
        # QPainter uses logical pixels when a device pixel ratio is set, which
        # would push the highlight off the words. Paint in real pixels instead.
        dpr = image.devicePixelRatio() or 1
        image.setDevicePixelRatio(1)
        painter = QPainter(image)
        fill = QColor(255, 196, 70, 120)
        pen = QPen(QColor(214, 150, 30, 220))
        pen.setWidth(max(1, int(round(dpr))))
        painter.setPen(pen)
        seen = set()
        for x0, y0, x1, y1 in rects:
            rx0 = int(round(x0 * scale * dpr))
            ry0 = int(round(y0 * scale * dpr))
            rx1 = int(round(x1 * scale * dpr))
            ry1 = int(round(y1 * scale * dpr))
            key = (rx0, ry0, rx1, ry1)
            if key in seen:
                continue
            seen.add(key)
            rect = QRect(rx0, ry0, max(1, rx1 - rx0), max(1, ry1 - ry0))
            painter.fillRect(rect, fill)
            painter.drawRect(rect)
        painter.end()
        image.setDevicePixelRatio(dpr)
        return image

    def _update_footer(self):
        has_page = bool(self.path and self.page_count)
        for button in (self.prev_btn, self.next_btn, self.zoom_in_btn, self.zoom_out_btn, self.fit_btn):
            button.setEnabled(has_page)
        if not has_page:
            self.page_label.setText("No page")
            return
        self.page_label.setText(f"{self.page + 1}  /  {self.page_count}")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page < self.page_count - 1)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
