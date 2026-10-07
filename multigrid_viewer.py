# -*- coding: utf-8 -*-
"""
多格看圖器 MultiGrid Viewer  v1.0  (2026/10/8)
Copyright (c) 2026 Skypray Huang — MIT License

需求: Python 3.9+   ->   pip install -r requirements.txt
執行: python multigrid_viewer.py [圖片或資料夾 ...]

操作
  排列         工具列選 1×1、2×2、4×1… 或自行輸入 橫×直
  載入         拖「單張圖片」到某一格 -> 自動載入它所在資料夾的全部圖片，並停在這張
               拖「資料夾」到某一格   -> 載入資料夾(含子資料夾)全部圖片
               空白格雙擊 / 工具列「開啟資料夾」也可以
  選格         點一下某一格(金色框 = 已選取)
  上/下一張    滾輪、← → ↑ ↓、PageUp/PageDown、空白鍵、工具列按鈕 (只換已選格)
  第一/最後    Home / End
  縮放         每格右側 + / − / 1:1、Ctrl+滾輪(以游標為中心)、鍵盤 + -
  恢復填滿     /（或 0）= 已選格回到原本等比延伸畫面；* = 全部格子恢復
               縮放後切換上/下一張，倍率與位置會保留
  平移         按住左鍵拖曳；雙擊 = 放大 2 倍 / 還原
  工具列       H 或工具列按鈕隱藏；隱藏後按左上角「☰」或再按 H 叫回
  全螢幕       F 或 F11，Esc 離開
  關於         F1 或工具列「關於」
"""
import os
import re
import sys
from collections import OrderedDict

from PySide6.QtCore import Qt, QPointF, QRectF, QSettings, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QImageReader,
                           QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QSizePolicy, QSpinBox, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

# HEIC / HEIF (iPhone photos) via Pillow + pillow-heif:  pip install pillow pillow-heif
try:
    from PIL import Image, ImageOps
    PIL_OK = True
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        HEIF_OK = True
    except Exception:
        HEIF_OK = False
except Exception:
    PIL_OK = HEIF_OK = False

APP_NAME = "多格看圖器"
APP_NAME_EN = "MultiGrid Viewer"
__version__ = "1.0"
RELEASE_DATE = "2026/10/8"
AUTHOR = "Skypray Huang"
GITHUB_URL = ""          # 上傳後填入，例如 "https://github.com/帳號/MultiGridViewer"，關於頁就會顯示連結
IMG_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".webp", ".tif",
           ".tiff", ".ico", ".avif", ".heic", ".heif", ".jp2", ".tga"}
PRESETS = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 1), (4, 1), (3, 2), (3, 3)]
FIT_MODES = [("contain", "等比延伸（完整顯示）"),
             ("cover", "等比填滿（裁切邊緣）"),
             ("none", "原始大小")]

C_BG = QColor("#0c0e11")
C_PANEL = QColor("#14171b")
C_LINE = QColor("#272c34")
C_FG = QColor("#dde2e8")
C_MUTED = QColor("#8b939e")
C_ACCENT = QColor("#e6ad48")


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def is_img(path):
    return os.path.splitext(path)[1].lower() in IMG_EXT


def load_pixmap(path):
    """Qt decoder first; Pillow (+pillow-heif) as fallback for HEIC and anything Qt can't read."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".heic", ".heif"):
        reader = QImageReader(path)
        reader.setAutoTransform(True)          # honour EXIF rotation
        img = reader.read()
        if not img.isNull():
            return QPixmap.fromImage(img)
    if PIL_OK:
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGBA")
                w, h = im.size
                data = im.tobytes("raw", "RGBA")
                qimg = QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()
                return QPixmap.fromImage(qimg)
        except Exception:
            pass
    return None


def list_folder(folder, recursive=False):
    out = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs.sort(key=natural_key)
            out += [os.path.join(root, f) for f in files if is_img(f)]
    else:
        try:
            out = [os.path.join(folder, f) for f in os.listdir(folder)
                   if is_img(f) and os.path.isfile(os.path.join(folder, f))]
        except OSError:
            out = []
    out.sort(key=lambda p: natural_key(os.path.relpath(p, folder)))
    return out


class PixCache:
    """LRU cache of decoded images, bounded by count and memory."""

    def __init__(self, max_items=24, max_bytes=900 * 1024 * 1024):
        self.d = OrderedDict()
        self.max_items, self.max_bytes, self.bytes = max_items, max_bytes, 0

    @staticmethod
    def _size(pm):
        return pm.width() * pm.height() * 4 if pm else 0

    def get(self, path):
        if path in self.d:
            self.d.move_to_end(path)
            return self.d[path]
        pm = load_pixmap(path)
        self.d[path] = pm
        self.bytes += self._size(pm)
        while len(self.d) > 1 and (len(self.d) > self.max_items or self.bytes > self.max_bytes):
            _, old = self.d.popitem(last=False)
            self.bytes -= self._size(old)
        return pm

    def clear(self):
        self.d.clear()
        self.bytes = 0


class Cell(QWidget):
    pressed = Signal(object)

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.items, self.idx = [], 0
        self.scale, self.off = 1.0, QPointF(0, 0)
        self.selected = False
        self.drop_hover = False
        self._drag = None
        self._wheel = 0
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(80, 80)

        # zoom rail on the right edge
        self.rail = QWidget(self)
        self.rail.setObjectName("rail")
        lay = QVBoxLayout(self.rail)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)
        self.b_in = self._zbtn("+", "放大", lambda: self.zoom_center(1.25))
        self.pct = QLabel("100%")
        self.pct.setAlignment(Qt.AlignCenter)
        self.pct.setObjectName("pct")
        self.b_out = self._zbtn("−", "縮小", lambda: self.zoom_center(1 / 1.25))
        self.b_reset = self._zbtn("1:1", "恢復原始填滿 ( / )", self.reset_zoom)
        for w in (self.b_in, self.pct, self.b_out, self.b_reset):
            lay.addWidget(w, 0, Qt.AlignHCenter)
        self.rail.adjustSize()

    def _zbtn(self, text, tip, fn):
        b = QPushButton(text)
        b.setObjectName("zbtn")
        b.setToolTip(tip)
        b.setFixedSize(32, 30)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(lambda *_: (self.pressed.emit(self), fn()))
        return b

    # ----- state -----
    def current(self):
        return self.items[self.idx] if self.items else None

    def set_items(self, items, idx=0):
        self.items, self.idx = items, max(0, min(idx, len(items) - 1)) if items else 0
        self.reset_zoom()

    def step(self, d):
        if not self.items:
            return
        self.idx = (self.idx + d) % len(self.items)
        self.update()
        self.preload()

    def jump(self, i):
        if self.items:
            self.idx = max(0, min(i, len(self.items) - 1))
            self.update()
            self.preload()

    def preload(self):
        if len(self.items) > 1:
            n = len(self.items)
            nxt, prv = self.items[(self.idx + 1) % n], self.items[(self.idx - 1) % n]
            QTimer.singleShot(30, lambda: (self.viewer.cache.get(nxt), self.viewer.cache.get(prv)))

    # ----- zoom / pan -----
    def zoom_at(self, factor, p):
        ns = max(0.1, min(30.0, self.scale * factor))
        r = ns / self.scale
        self.off = QPointF(p.x() - (p.x() - self.off.x()) * r, p.y() - (p.y() - self.off.y()) * r)
        self.scale = ns
        self.update()

    def zoom_center(self, factor):
        self.zoom_at(factor, QPointF(self.width() / 2, self.height() / 2))

    def reset_zoom(self):
        self.scale, self.off = 1.0, QPointF(0, 0)
        self.update()

    def base_rect(self, pm):
        W, H, w, h = self.width(), self.height(), pm.width(), pm.height()
        mode = self.viewer.fit
        if mode == "contain":
            s = min(W / w, H / h)
        elif mode == "cover":
            s = max(W / w, H / h)
        else:
            s = 1.0
        return QRectF((W - w * s) / 2, (H - h * s) / 2, w * s, h * s)

    # ----- painting -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        path = self.current()
        self.rail.setVisible(bool(path))
        self.pct.setText(f"{round(self.scale * 100)}%")

        if not path:
            p.setPen(C_MUTED)
            f = QFont(self.font()); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "把資料夾或圖片拖到這一格\n（或雙擊這裡開啟資料夾）")
        else:
            pm = self.viewer.cache.get(path)
            if pm is None:
                p.setPen(C_MUTED)
                p.drawText(self.rect().adjusted(20, 0, -60, 0), Qt.AlignCenter | Qt.TextWordWrap,
                           (f"無法顯示 HEIC：\n請在命令列執行  pip install pillow pillow-heif"
                            if path.lower().endswith((".heic", ".heif")) and not HEIF_OK
                            else f"無法顯示此檔案：\n{os.path.basename(path)}"))
            else:
                r = self.base_rect(pm)
                s, o = self.scale, self.off
                p.drawPixmap(QRectF(o.x() + r.x() * s, o.y() + r.y() * s, r.width() * s, r.height() * s),
                             pm, QRectF(pm.rect()))
            # caption
            f = QFont(self.font()); f.setPointSize(9); p.setFont(f)
            fm = QFontMetrics(f)
            folder = os.path.basename(os.path.dirname(path))
            num = f"{self.idx + 1}/{len(self.items)}"
            rest = f"   {os.path.basename(path)}   {folder}"
            maxw = max(40, self.width() - 70)
            rest = fm.elidedText(rest, Qt.ElideMiddle, maxw - fm.horizontalAdvance(num) - 20)
            tw = fm.horizontalAdvance(num + rest) + 20
            box = QRectF(0, self.height() - fm.height() - 8, tw, fm.height() + 8)
            p.fillRect(box, QColor(12, 14, 17, 190))
            p.setPen(C_ACCENT)
            p.drawText(box.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, num)
            p.setPen(C_FG)
            p.drawText(box.adjusted(10 + fm.horizontalAdvance(num), 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, rest)

        if self.selected and self.viewer.cell_count() > 1:
            p.setPen(QPen(C_ACCENT, 3))
            p.drawRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))
            f = QFont(self.font()); f.setPointSize(9); p.setFont(f)
            p.drawText(self.rect().adjusted(0, 6, -10, 0), Qt.AlignTop | Qt.AlignRight, "已選取")
        if self.drop_hover:
            p.fillRect(self.rect(), QColor(230, 173, 72, 45))
            p.setPen(QPen(C_ACCENT, 2, Qt.DashLine))
            p.drawRect(QRectF(self.rect()).adjusted(3, 3, -3, -3))
            f = QFont(self.font()); f.setPointSize(14); f.setBold(True); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "放到這一格")
        p.end()

    def resizeEvent(self, e):
        self.rail.adjustSize()
        self.rail.move(self.width() - self.rail.width() - 8, (self.height() - self.rail.height()) // 2)
        super().resizeEvent(e)

    # ----- mouse -----
    def mousePressEvent(self, e):
        self.pressed.emit(self)
        if e.button() == Qt.LeftButton:
            self._drag = (e.position(), QPointF(self.off))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag:
            start, off0 = self._drag
            self.off = off0 + (e.position() - start)
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e):
        if not self.items:
            self.viewer.open_folder(self)
            return
        if self.scale != 1.0 or self.off != QPointF(0, 0):
            self.reset_zoom()
        else:
            self.zoom_at(2.0, e.position())

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            self.pressed.emit(self)
            self.zoom_at(pow(1.0015, d), e.position())
            return
        self._wheel += d
        if abs(self._wheel) >= 60:                # one mouse notch = 120
            self.viewer.nav(-1 if self._wheel > 0 else 1)
            self._wheel = 0

    # ----- drag & drop -----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop_hover = True
            self.update()

    def dragLeaveEvent(self, e):
        self.drop_hover = False
        self.update()

    def dropEvent(self, e):
        self.drop_hover = False
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.viewer.load_paths(self, paths)
        e.acceptProposedAction()


class Viewer(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1600, scr.width() - 40), min(1000, scr.height() - 60))
        self.setAcceptDrops(True)
        self.settings = QSettings("Skypray", "MultiGridViewer")
        self.cache = PixCache()
        self.cols = int(self.settings.value("cols", 2))
        self.rows = int(self.settings.value("rows", 2))
        self.fit = self.settings.value("fit", "contain")
        if self.fit not in dict(FIT_MODES):
            self.fit = "contain"
        self.cells, self.active = [], 0

        central = QWidget()
        central.setObjectName("central")
        self.grid = QGridLayout(central)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        self.setCentralWidget(central)
        central.setFocusPolicy(Qt.StrongFocus)
        self.central = central

        self._build_toolbar()
        self.show_bar_btn = QPushButton("☰ 工具列", central)
        self.show_bar_btn.setObjectName("showbar")
        self.show_bar_btn.setFocusPolicy(Qt.NoFocus)
        self.show_bar_btn.clicked.connect(lambda: self.set_bar_hidden(False))
        self.show_bar_btn.move(8, 8)
        self.show_bar_btn.adjustSize()

        self.rebuild()
        self.set_bar_hidden(self.settings.value("barHidden", "false") == "true")

        for i, a in enumerate(args[:len(self.cells)]):
            self.load_paths(self.cells[i], [a])
        if args:
            self.select(self.cells[0])
        central.setFocus()

    # ---------- toolbar ----------
    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.tb = tb

        def lbl(t):
            w = QLabel(t); w.setObjectName("lbl"); tb.addWidget(w)

        def btn(t, fn, tip=None, primary=False):
            b = QPushButton(t)
            b.setFocusPolicy(Qt.NoFocus)
            if primary: b.setObjectName("primary")
            if tip: b.setToolTip(tip)
            b.clicked.connect(fn)
            tb.addWidget(b)
            return b

        lbl(" 排列 橫×直 ")
        self.preset_btns = []
        for c, r in PRESETS:
            b = QToolButton()
            b.setText(f"{c}×{r}")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(f"橫 {c} 格 × 直 {r} 格")
            b.clicked.connect(lambda _=False, c=c, r=r: self.set_layout(c, r))
            tb.addWidget(b)
            self.preset_btns.append((b, c, r))
        self.sp_cols, self.sp_rows = QSpinBox(), QSpinBox()
        for sp in (self.sp_cols, self.sp_rows):
            sp.setRange(1, 8)
            sp.setFocusPolicy(Qt.ClickFocus)
            sp.setKeyboardTracking(False)
        tb.addWidget(self.sp_cols); lbl("×"); tb.addWidget(self.sp_rows)
        self.sp_cols.valueChanged.connect(lambda v: self.set_layout(v, self.rows))
        self.sp_rows.valueChanged.connect(lambda v: self.set_layout(self.cols, v))

        tb.addSeparator()
        lbl(" 顯示 ")
        self.cb_fit = QComboBox()
        self.cb_fit.setFocusPolicy(Qt.NoFocus)
        for k, t in FIT_MODES:
            self.cb_fit.addItem(t, k)
        self.cb_fit.setCurrentIndex([k for k, _ in FIT_MODES].index(self.fit))
        self.cb_fit.currentIndexChanged.connect(self.set_fit)
        tb.addWidget(self.cb_fit)

        tb.addSeparator()
        lbl(" 已選格 ")
        btn("◀ 上一張", lambda: self.nav(-1))
        btn("下一張 ▶", lambda: self.nav(1))
        btn("開啟資料夾", lambda: self.open_folder(self.cells[self.active]), primary=True)
        btn("選擇圖片", lambda: self.open_files(self.cells[self.active]))
        btn("清空", self.clear_cell, "清空已選格")

        tb.addSeparator()
        btn("全部 1:1", lambda: [c.reset_zoom() for c in self.cells], "全部格子恢復原始填滿 ( * )")
        btn("全螢幕", self.toggle_fs, "F / F11")
        btn("隱藏工具列", lambda: self.set_bar_hidden(True), "H 鍵可切換")
        btn("關於", self.show_about, "版本與版權資訊 ( F1 )")

        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.status = QLabel(); self.status.setObjectName("status")
        tb.addWidget(self.status)

    def sync_controls(self):
        for sp, v in ((self.sp_cols, self.cols), (self.sp_rows, self.rows)):
            sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)
        for b, c, r in self.preset_btns:
            b.setChecked(c == self.cols and r == self.rows)

    def update_status(self):
        c = self.cells[self.active]
        if c.items:
            self.status.setText(f"第 {self.active + 1} 格 · {c.idx + 1} / {len(c.items)}  ")
        else:
            self.status.setText(f"第 {self.active + 1} 格 · 未載入  ")
        path = c.current()
        base = f"{APP_NAME} v{__version__}"
        self.setWindowTitle(f"{os.path.basename(path)} — {base}" if path else base)

    # ---------- grid ----------
    def cell_count(self):
        return self.cols * self.rows

    def rebuild(self):
        n = self.cell_count()
        while len(self.cells) < n:
            c = Cell(self)
            c.pressed.connect(self.select)
            self.cells.append(c)
        for c in self.cells[n:]:
            self.grid.removeWidget(c)
            c.deleteLater()
        self.cells = self.cells[:n]
        for i in range(self.grid.rowCount()):
            self.grid.setRowStretch(i, 0)
        for i in range(self.grid.columnCount()):
            self.grid.setColumnStretch(i, 0)
        for i, c in enumerate(self.cells):
            self.grid.addWidget(c, i // self.cols, i % self.cols)
            c.show()
        for r in range(self.rows):
            self.grid.setRowStretch(r, 1)
        for col in range(self.cols):
            self.grid.setColumnStretch(col, 1)
        if self.active >= n:
            self.active = 0
        for i, c in enumerate(self.cells):
            c.selected = i == self.active
            c.update()
        self.sync_controls()
        self.update_status()
        self.show_bar_btn.raise_()

    def set_layout(self, c, r):
        self.cols, self.rows = max(1, min(8, int(c))), max(1, min(8, int(r)))
        self.settings.setValue("cols", self.cols)
        self.settings.setValue("rows", self.rows)
        self.rebuild()
        self.central.setFocus()

    def set_fit(self, i):
        self.fit = self.cb_fit.itemData(i)
        self.settings.setValue("fit", self.fit)
        for c in self.cells:
            c.update()

    def select(self, cell):
        i = self.cells.index(cell)
        if i != self.active:
            self.active = i
            for j, c in enumerate(self.cells):
                c.selected = j == i
                c.update()
        self.update_status()

    # ---------- navigation ----------
    def nav(self, d):
        self.cells[self.active].step(d)
        self.update_status()

    # ---------- loading ----------
    def load_paths(self, cell, paths):
        paths = [p for p in paths if p and os.path.exists(p)]
        if not paths:
            return
        idx = 0
        if len(paths) == 1 and os.path.isdir(paths[0]):
            items = list_folder(paths[0], recursive=True)
        elif len(paths) == 1:
            # single image: load every image in the same folder and start at this one
            folder = os.path.dirname(os.path.abspath(paths[0]))
            items = list_folder(folder)
            target = os.path.normcase(os.path.abspath(paths[0]))
            norm = [os.path.normcase(os.path.abspath(p)) for p in items]
            if target in norm:
                idx = norm.index(target)
            elif is_img(paths[0]):
                items, idx = [paths[0]], 0
        else:
            items = []
            for p in paths:
                items += list_folder(p, recursive=True) if os.path.isdir(p) else ([p] if is_img(p) else [])
        if not items:
            return
        cell.set_items(items, idx)
        cell.preload()
        self.select(cell)
        self.update_status()

    def open_folder(self, cell):
        cur = cell.current()
        start = os.path.dirname(cur) if cur else self.settings.value("lastDir", os.path.expanduser("~"))
        d = QFileDialog.getExistingDirectory(self, "選擇資料夾", start)
        if d:
            self.settings.setValue("lastDir", d)
            self.load_paths(cell, [d])

    def open_files(self, cell):
        cur = cell.current()
        start = os.path.dirname(cur) if cur else self.settings.value("lastDir", os.path.expanduser("~"))
        exts = " ".join("*" + e for e in sorted(IMG_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "選擇圖片（只選一張 = 載入整個資料夾）", start,
                                                f"圖片 ({exts});;所有檔案 (*)")
        if files:
            self.settings.setValue("lastDir", os.path.dirname(files[0]))
            self.load_paths(cell, files)

    def clear_cell(self):
        c = self.cells[self.active]
        c.set_items([])
        self.update_status()

    # drops that land on the toolbar go to the selected cell
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.load_paths(self.cells[self.active], paths)

    # ---------- about ----------
    def show_about(self):
        AboutDialog(self).exec()
        self.central.setFocus()

    # ---------- window ----------
    def set_bar_hidden(self, hidden):
        self.tb.setVisible(not hidden)
        self.show_bar_btn.setVisible(hidden)
        self.show_bar_btn.raise_()
        self.settings.setValue("barHidden", "true" if hidden else "false")
        self.central.setFocus()

    def toggle_fs(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.central.setFocus()

    def keyPressEvent(self, e):
        k = e.key()
        c = self.cells[self.active]
        if k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp):
            self.nav(-1)
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_PageDown, Qt.Key_Space):
            self.nav(1)
        elif k == Qt.Key_Home:
            c.jump(0); self.update_status()
        elif k == Qt.Key_End:
            c.jump(len(c.items) - 1); self.update_status()
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            c.zoom_center(1.25)
        elif k in (Qt.Key_Minus, Qt.Key_Underscore):
            c.zoom_center(1 / 1.25)
        elif k in (Qt.Key_0, Qt.Key_Slash):
            c.reset_zoom()                       # back to the original fit-to-panel view
        elif k == Qt.Key_Asterisk:
            for x in self.cells:
                x.reset_zoom()
        elif k in (Qt.Key_F, Qt.Key_F11):
            self.toggle_fs()
        elif k == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fs()
        elif k == Qt.Key_F1:
            self.show_about()
        elif k == Qt.Key_H:
            self.set_bar_hidden(self.tb.isVisible())
        else:
            super().keyPressEvent(e)


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"關於 {APP_NAME}")
        self.setObjectName("about")
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(6)

        def add(text, name=None, rich=False):
            w = QLabel(text)
            w.setWordWrap(True)
            if name: w.setObjectName(name)
            if rich:
                w.setTextFormat(Qt.RichText)
                w.setOpenExternalLinks(True)
            lay.addWidget(w)
            return w

        add(APP_NAME, "aboutTitle")
        add(APP_NAME_EN, "aboutSub")
        add(f"版本 {__version__}　·　{RELEASE_DATE}", "aboutVer")
        lay.addSpacing(10)
        add("多格排列看圖程式：自訂 橫×直 版面，每格各自瀏覽資料夾、"
            "單格縮放與平移，支援 JPG / PNG / WebP / TIFF / HEIC。")
        lay.addSpacing(10)
        add(f"製作人　{AUTHOR}", "aboutKey")
        add(f"Copyright © 2026 {AUTHOR}. Released under the MIT License.", "aboutMuted")
        if GITHUB_URL:
            add(f'<a style="color:{C_ACCENT.name()}" href="{GITHUB_URL}">{GITHUB_URL}</a>', rich=True)
        lay.addSpacing(8)
        add("使用元件：Qt for Python (PySide6, LGPL-3.0)、Pillow (MIT-CMU)、pillow-heif (BSD-3-Clause)",
            "aboutMuted")
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("關閉")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)


STYLE = f"""
QMainWindow, #central {{ background: {C_LINE.name()}; }}
QToolBar::separator {{ background: {C_LINE.name()}; width: 1px; margin: 4px 6px; }}
QToolBar {{ background: {C_PANEL.name()}; border: 0; border-bottom: 1px solid {C_LINE.name()}; padding: 4px 6px; spacing: 4px; }}
QLabel {{ color: {C_FG.name()}; }}
#title {{ font-weight: 600; color: {C_ACCENT.name()}; }}
#lbl {{ color: {C_MUTED.name()}; }}
#status {{ color: {C_MUTED.name()}; font-family: Consolas, monospace; }}
QPushButton, QToolButton, QComboBox, QSpinBox {{
  color: {C_FG.name()}; background: transparent; border: 1px solid {C_LINE.name()};
  border-radius: 4px; padding: 3px 9px; min-height: 20px; }}
QPushButton:hover, QToolButton:hover, QComboBox:hover {{ border-color: {C_MUTED.name()}; }}
QToolButton:checked, #primary {{ background: {C_ACCENT.name()}; color: #1a1407; border-color: {C_ACCENT.name()}; }}
#primary {{ font-weight: 600; }}
QComboBox QAbstractItemView {{ background: {C_PANEL.name()}; color: {C_FG.name()}; selection-background-color: {C_ACCENT.name()}; selection-color: #1a1407; }}
QSpinBox {{ padding: 2px 4px; min-width: 34px; }}
QToolButton {{ padding: 3px 6px; }}
#rail {{ background: rgba(12,14,17,190); border: 1px solid {C_LINE.name()}; border-radius: 6px; }}
#zbtn {{ background: {C_PANEL.name()}; padding: 0; font-size: 15px; }}
#zbtn:hover {{ border-color: {C_ACCENT.name()}; color: {C_ACCENT.name()}; }}
#pct {{ color: {C_MUTED.name()}; font-size: 10px; background: transparent; }}
#showbar {{ background: rgba(20,23,27,215); }}
#about {{ background: {C_PANEL.name()}; }}
#aboutTitle {{ font-size: 22px; font-weight: 600; color: {C_ACCENT.name()}; }}
#aboutSub {{ font-size: 13px; color: {C_MUTED.name()}; letter-spacing: 1px; }}
#aboutVer {{ font-family: Consolas, monospace; color: {C_FG.name()}; }}
#aboutKey {{ font-size: 14px; font-weight: 600; }}
#aboutMuted {{ color: {C_MUTED.name()}; font-size: 11px; }}
QToolTip {{ background: {C_PANEL.name()}; color: {C_FG.name()}; border: 1px solid {C_LINE.name()}; }}
"""


def main():
    QImageReader.setAllocationLimit(0)       # allow very large photos
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE)
    f = app.font()
    f.setFamilies(["Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", f.family()])
    app.setFont(f)
    w = Viewer([a for a in sys.argv[1:] if os.path.exists(a)])
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
