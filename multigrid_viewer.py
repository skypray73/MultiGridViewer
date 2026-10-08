# -*- coding: utf-8 -*-
"""
多格看圖器 MultiGrid Viewer  v1.1  (2026/10/8)
Copyright (c) 2026 Skypray Huang — MIT License

需求: Python 3.10+ (建議 3.13)   ->   pip install -r requirements.txt
執行: python multigrid_viewer.py [圖片或資料夾 ...]

操作
  排列         工具列選 1×1、2×2、4×1… 或自行輸入 橫×直
  載入         拖「單張圖片」到某一格 -> 自動載入它所在資料夾的全部圖片，並停在這張
               拖「資料夾」到某一格   -> 載入資料夾(含子資料夾)全部圖片
               空白格雙擊 / 工具列「開啟資料夾」也可以
  選格         點一下某一格(金色框 = 已選取)
  上/下一張    滾輪、← → ↑ ↓、PageUp/PageDown、空白鍵、工具列按鈕 (只換已選格)
  第一/最後    Home / End
  刪除圖片     Delete（會先跳出確認視窗，←/→ 或滑鼠選擇，Enter 確認，圖片移到資源回收筒）
  壓縮檔       可拖入 ZIP / RAR / 7Z（CBZ/CBR/CB7），自動讀取內部圖片
  模式         單張模式（每格各自瀏覽）/ 漫畫模式（所有格共用同一資料夾或壓縮檔，PageDown 翻整頁），M 鍵切換
  縮放         每格右側 + / − / 1:1、Ctrl+滾輪(以游標為中心)、鍵盤 + -
  恢復填滿     /（或 0）= 已選格回到原本等比延伸畫面；* = 全部格子恢復
               縮放後切換上/下一張，倍率與位置會保留
  平移         按住左鍵拖曳；雙擊 = 放大 2 倍 / 還原
  工具列       H 或工具列按鈕隱藏；隱藏後按左上角「☰」或再按 H 叫回
  全螢幕       F 或 F11，Esc 離開
  說明         最上方選單「幫助」或 F1
"""
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import OrderedDict

from PySide6.QtCore import QFile, Qt, QPointF, QRectF, QSettings, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QImageReader,
                           QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QTextBrowser, QToolBar, QToolButton,
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
__version__ = "1.1"
RELEASE_DATE = "2026/10/8"
AUTHOR = "Skypray Huang"
GITHUB_URL = "https://github.com/skypray73/MultiGridViewer"
IMG_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".webp", ".tif",
           ".tiff", ".ico", ".avif", ".heic", ".heif", ".jp2", ".tga"}
ARC_EXT = {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"}
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


def is_archive(path):
    return os.path.splitext(path)[1].lower() in ARC_EXT and os.path.isfile(path)


_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_7z():
    exe = shutil.which("7z") or shutil.which("7zz")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and os.path.isfile(os.path.join(base, "7-Zip", "7z.exe")):
            return os.path.join(base, "7-Zip", "7z.exe")
    return None


def _extract_zip(path, dest):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if not info.flag_bits & 0x800:           # not UTF-8: Windows zips are usually Big5
                try:
                    name = name.encode("cp437").decode("cp950")
                except Exception:
                    pass
            if not is_img(name):
                continue
            parts = [x for x in re.split(r"[\\/]+", name) if x not in ("", ".", "..") and ":" not in x]
            if not parts:
                continue
            out = os.path.join(dest, *parts)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def extract_archive(path, dest):
    """Extract the images of a ZIP/RAR/7Z archive into dest. Raises RuntimeError with a readable message."""
    os.makedirs(dest, exist_ok=True)
    if os.path.splitext(path)[1].lower() in (".zip", ".cbz"):
        try:
            _extract_zip(path, dest)
            return
        except Exception as e:                      # encrypted / unusual compression -> try external tools
            if isinstance(e, RuntimeError) and "password" in str(e).lower():
                raise RuntimeError("壓縮檔有密碼保護，無法讀取")
    exe = find_7z()
    if exe:
        cmd = [exe, "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{dest}", path]
    else:
        tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")   # bsdtar reads RAR / 7Z
        if not os.path.isfile(tar):
            tar = shutil.which("tar")
        if not tar:
            raise RuntimeError("找不到解壓縮工具。請安裝 7-Zip（https://www.7-zip.org）後重試")
        cmd = [tar, "-xf", path, "-C", dest]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=_NOWIN)
    if r.returncode != 0 and not list_folder(dest, recursive=True):
        detail = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("解壓縮失敗" + (f"：{detail[-1]}" if detail else "")
                           + ("" if exe else "\n（RAR / 7Z 建議安裝 7-Zip：https://www.7-zip.org）"))


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

    def __init__(self, max_items=96, max_bytes=900 * 1024 * 1024):
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

    def pop(self, path):
        pm = self.d.pop(path, None)
        self.bytes -= self._size(pm)

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
        return self.items[self.idx] if 0 <= self.idx < len(self.items) else None

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
        if self.viewer.mode == "single" and len(self.items) > 1:
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
                       "— 沒有更多圖片了 —" if self.items else
                       "把資料夾、壓縮檔或圖片拖到這一格\n（或雙擊這裡開啟資料夾）" if self.viewer.mode == "single" else
                       "把資料夾、壓縮檔或圖片拖進來\n（或雙擊這裡開啟資料夾）")
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
        self.mode = self.settings.value("mode", "single")
        if self.mode not in ("single", "comic"):
            self.mode = "single"
        self.comic_items, self.comic_pos = [], 0
        self.tmp_root = None
        atexit.register(self.cleanup_tmp)

        central = QWidget()
        central.setObjectName("central")
        self.grid = QGridLayout(central)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        self.setCentralWidget(central)
        central.setFocusPolicy(Qt.StrongFocus)
        self.central = central

        self._build_menu()
        self._build_toolbar()
        self.show_bar_btn = QPushButton("☰ 工具列", central)
        self.show_bar_btn.setObjectName("showbar")
        self.show_bar_btn.setFocusPolicy(Qt.NoFocus)
        self.show_bar_btn.clicked.connect(lambda: self.set_bar_hidden(False))
        self.show_bar_btn.move(8, 8)
        self.show_bar_btn.adjustSize()

        self.rebuild()
        self.set_bar_hidden(self.settings.value("barHidden", "false") == "true")

        for i, a in enumerate(args[:1] if self.mode == "comic" else args[:len(self.cells)]):
            self.load_paths(self.cells[i], [a])
        if args:
            self.select(self.cells[0])
        central.setFocus()

    # ---------- menu ----------
    def _build_menu(self):
        m = self.menuBar().addMenu("幫助")
        m.addAction("使用說明\tF1", self.show_help)
        m.addAction("關於", self.show_about)

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
        lbl(" 模式 ")
        self.mode_btns = []
        for key, text, tip in (("single", "單張模式", "每格各自瀏覽自己的資料夾 ( M 切換 )"),
                               ("comic", "漫畫模式", "所有格共用同一資料夾/壓縮檔，PageDown 翻整頁 ( M 切換 )")):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            tb.addWidget(b)
            self.mode_btns.append((b, key))

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
        btn("刪除圖片", self.delete_current, "刪除目前圖片（先確認，移到資源回收筒）( Delete )")

        tb.addSeparator()
        btn("全部 1:1", lambda: [c.reset_zoom() for c in self.cells], "全部格子恢復原始填滿 ( * )")
        btn("全螢幕", self.toggle_fs, "F / F11")
        btn("隱藏工具列", lambda: self.set_bar_hidden(True), "H 鍵可切換")

        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.status = QLabel(); self.status.setObjectName("status")
        tb.addWidget(self.status)

    def sync_controls(self):
        for sp, v in ((self.sp_cols, self.cols), (self.sp_rows, self.rows)):
            sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)
        for b, c, r in self.preset_btns:
            b.setChecked(c == self.cols and r == self.rows)
        for b, k in self.mode_btns:
            b.setChecked(k == self.mode)

    def update_status(self):
        c = self.cells[self.active]
        if self.mode == "comic":
            n, total = self.cell_count(), len(self.comic_items)
            if total:
                self.status.setText(f"漫畫 · {self.comic_pos + 1}–{min(self.comic_pos + n, total)} / {total}  ")
            else:
                self.status.setText("漫畫 · 未載入  ")
        elif c.items:
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
            c.hide()
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
        if self.mode == "comic":
            self.comic_refresh()
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
    def nav(self, d, unit=False):
        """single mode: step the selected cell.  comic mode: turn a whole page (unit=True: one image)."""
        if self.mode == "comic":
            self.comic_move(d if unit else d * self.cell_count())
        else:
            self.cells[self.active].step(d)
        self.update_status()

    def go_edge(self, last):
        if self.mode == "comic":
            n = len(self.comic_items)
            self.comic_goto(max(0, n - self.cell_count()) if last else 0)
        else:
            c = self.cells[self.active]
            c.jump(len(c.items) - 1 if last else 0)
        self.update_status()

    # ---------- comic mode ----------
    def comic_refresh(self, reset=True):
        for i, c in enumerate(self.cells):
            c.items, c.idx = self.comic_items, self.comic_pos + i
            if reset:
                c.reset_zoom()
            else:
                c.update()
        self.update_status()
        n = self.cell_count()
        nxt = self.comic_items[self.comic_pos + n:self.comic_pos + 2 * n]
        if nxt:
            QTimer.singleShot(30, lambda: [self.cache.get(x) for x in nxt])

    def comic_goto(self, pos):
        if not self.comic_items:
            return
        pos = max(0, min(pos, len(self.comic_items) - 1))
        if pos != self.comic_pos:
            self.comic_pos = pos
            self.comic_refresh()

    def comic_move(self, delta):
        new = self.comic_pos + delta
        if delta > 0 and new >= len(self.comic_items):
            return                                  # already at the end
        self.comic_goto(new)

    def set_mode(self, mode):
        if mode == self.mode:
            self.sync_controls()
            return
        if mode == "comic":
            cur = self.cells[self.active]
            src = cur if cur.items else next((c for c in self.cells if c.items), None)
            self.comic_items = list(src.items) if src else []
            self.comic_pos = src.idx if src else 0
            self.mode = "comic"
            self.comic_refresh()
        else:
            items, pos = self.comic_items, self.comic_pos
            self.mode = "single"
            for i, c in enumerate(self.cells):
                if pos + i < len(items):
                    c.set_items(list(items), pos + i)
                else:
                    c.set_items([])
        self.settings.setValue("mode", self.mode)
        self.sync_controls()
        self.update_status()
        self.central.setFocus()

    # ---------- delete ----------
    def is_temp(self, path):
        return bool(self.tmp_root) and os.path.normcase(os.path.abspath(path)).startswith(
            os.path.normcase(os.path.abspath(self.tmp_root)))

    def delete_current(self):
        c = self.cells[self.active]
        path = c.current()
        if not path:
            return
        temp = self.is_temp(path)
        name = os.path.basename(path)
        text = (f"要把這張圖從清單移除嗎？\n\n{name}\n\n（來自壓縮檔，原壓縮檔不會被修改）" if temp
                else f"要刪除這張圖片嗎？\n\n{name}\n\n（會移到資源回收筒）")
        ok = ConfirmDialog(self, "確認刪除", text, "移除" if temp else "刪除").exec() == QDialog.Accepted
        self.central.setFocus()
        if not ok:
            return
        if not temp:
            r = QFile.moveToTrash(path)
            if not (r[0] if isinstance(r, tuple) else r):
                QMessageBox.warning(self, APP_NAME, f"無法刪除這個檔案：\n{path}")
                return
        self.cache.pop(path)
        if self.mode == "comic":
            if c.idx < len(self.comic_items):
                del self.comic_items[c.idx]
            if self.comic_pos >= len(self.comic_items):
                self.comic_pos = max(0, len(self.comic_items) - self.cell_count())
            self.comic_refresh(reset=False)
        else:
            for x in self.cells:
                while path in x.items:
                    i = x.items.index(path)
                    del x.items[i]
                    if i < x.idx:
                        x.idx -= 1
                x.idx = max(0, min(x.idx, len(x.items) - 1))
                x.update()
            c.preload()
        self.update_status()

    # ---------- archives ----------
    def cleanup_tmp(self):
        if self.tmp_root:
            shutil.rmtree(self.tmp_root, ignore_errors=True)
            self.tmp_root = None

    def expand_archive(self, path):
        """Extract an archive into the temp folder; returns the folder, or None on failure."""
        if not self.tmp_root:
            self.tmp_root = tempfile.mkdtemp(prefix="mgv_")
        n = len(os.listdir(self.tmp_root))
        stem = os.path.splitext(os.path.basename(path))[0] or "archive"
        dest = os.path.join(self.tmp_root, str(n), stem)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.setWindowTitle(f"正在讀取壓縮檔… {os.path.basename(path)}")
        QApplication.processEvents()
        try:
            extract_archive(path, dest)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"{os.path.basename(path)}\n\n{e}")
            return None
        QApplication.restoreOverrideCursor()
        if not list_folder(dest, recursive=True):
            QMessageBox.information(self, APP_NAME, f"{os.path.basename(path)}\n\n壓縮檔內找不到圖片。")
            return None
        return dest

    # ---------- loading ----------
    def load_paths(self, cell, paths):
        paths = [p for p in paths if p and os.path.exists(p)]
        paths = [self.expand_archive(p) if is_archive(p) else p for p in paths]
        paths = [p for p in paths if p]
        if not paths:
            self.update_status()
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
            self.update_status()
            return
        if self.mode == "comic":
            self.comic_items, self.comic_pos = items, idx
            self.comic_refresh()
            self.select(cell)
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
        exts = " ".join("*" + e for e in sorted(IMG_EXT | ARC_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "選擇圖片或壓縮檔（只選一張 = 載入整個資料夾）", start,
                                                f"圖片與壓縮檔 ({exts});;所有檔案 (*)")
        if files:
            self.settings.setValue("lastDir", os.path.dirname(files[0]))
            self.load_paths(cell, files)

    def clear_cell(self):
        if self.mode == "comic":
            self.comic_items, self.comic_pos = [], 0
            self.comic_refresh()
            return
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

    # ---------- help / about ----------
    def show_help(self):
        HelpDialog(self).exec()
        self.central.setFocus()

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
        if k in (Qt.Key_Left, Qt.Key_Up):
            self.nav(-1, unit=True)
        elif k in (Qt.Key_Right, Qt.Key_Down):
            self.nav(1, unit=True)
        elif k == Qt.Key_PageUp:
            self.nav(-1)
        elif k in (Qt.Key_PageDown, Qt.Key_Space):
            self.nav(1)
        elif k == Qt.Key_Home:
            self.go_edge(False)
        elif k == Qt.Key_End:
            self.go_edge(True)
        elif k == Qt.Key_Delete:
            self.delete_current()
        elif k == Qt.Key_M:
            self.set_mode("single" if self.mode == "comic" else "comic")
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
            self.show_help()
        elif k == Qt.Key_H:
            self.set_bar_hidden(self.tb.isVisible())
        else:
            super().keyPressEvent(e)


class ConfirmDialog(QDialog):
    """Yes/No box: click a button, or press Left/Right to choose and Enter to confirm. Defaults to the safe choice."""

    def __init__(self, parent, title, text, yes_text, no_text="取消"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("about")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        msg = QLabel(text)
        msg.setWordWrap(True)
        lay.addWidget(msg)
        hint = QLabel("← → 選擇，Enter 確認，Esc 取消")
        hint.setObjectName("aboutMuted")
        lay.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btns = []
        for t, fn in ((yes_text, self.accept), (no_text, self.reject)):
            b = QPushButton(t)
            b.setMinimumWidth(90)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.btns.append(b)
        lay.addLayout(row)
        self.sel = 1                                # cancel is preselected
        self._mark()

    def _mark(self):
        for i, b in enumerate(self.btns):
            b.setObjectName("primary" if i == self.sel else "")
            b.style().unpolish(b)
            b.style().polish(b)
        self.btns[self.sel].setFocus()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Left, Qt.Key_Up):
            self.sel = 0
            self._mark()
        elif k in (Qt.Key_Right, Qt.Key_Down):
            self.sel = 1
            self._mark()
        elif k in (Qt.Key_Tab, Qt.Key_Backtab):
            self.sel = 1 - self.sel
            self._mark()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.btns[self.sel].click()
        else:
            super().keyPressEvent(e)


HELP_HTML = f"""
<h2 style="color:{C_ACCENT.name()}">{APP_NAME} 使用說明</h2>
<h3>載入圖片</h3>
<ul>
<li>把<b>圖片、資料夾、壓縮檔（ZIP / RAR / 7Z / CBZ / CBR / CB7）</b>拖到程式視窗。</li>
<li>拖<b>單張圖片</b>：載入它所在資料夾的全部圖片，並停在這一張。</li>
<li>拖<b>資料夾</b>：載入資料夾內（含子資料夾）全部圖片。</li>
<li>拖<b>壓縮檔</b>：自動讀取裡面的圖片，從第一張開始，可用上下鍵切換。壓縮檔不會被修改。</li>
<li>空白格雙擊，或工具列「開啟資料夾」「選擇圖片」也可以。</li>
<li>RAR / 7Z 需要 Windows 內建的 tar 或已安裝的 <a style="color:{C_ACCENT.name()}" href="https://www.7-zip.org">7-Zip</a>；有密碼的壓縮檔無法讀取。</li>
</ul>
<h3>兩種模式（工具列「模式」或按 <b>M</b>）</h3>
<ul>
<li><b>單張模式</b>：每一格各自載入並瀏覽自己的資料夾，各自縮放；操作只影響「已選取」的格子（金色框）。</li>
<li><b>漫畫模式</b>：所有格子共用同一個資料夾或壓縮檔，像看漫畫一樣依序排列。
例如選 2×1，按 <b>PageDown</b> 就換成接下來的 2 張；<b>PageUp</b> 回上一頁。在漫畫模式拖入資料夾/壓縮檔會一併取代所有格。</li>
</ul>
<h3>排列</h3>
<p>工具列選 1×1、2×1、2×2… 或自行輸入 橫×直（最多 8×8）。「顯示」可選等比延伸、等比填滿、原始大小。</p>
<h3>翻頁與跳轉</h3>
<table cellpadding="3">
<tr><td><b>← ↑ / → ↓</b></td><td>上一張 / 下一張（漫畫模式：移動 1 張）</td></tr>
<tr><td><b>PageUp / PageDown / 空白鍵 / 滾輪</b></td><td>單張模式：上/下一張；漫畫模式：上/下一整頁</td></tr>
<tr><td><b>Home / End</b></td><td>資料夾（或壓縮檔）的第一張 / 最後一張</td></tr>
</table>
<h3>刪除圖片</h3>
<p>按 <b>Delete</b>（或工具列「刪除圖片」）刪除目前選取格的圖片。會先跳出確認視窗：
用滑鼠點按鈕，或按 <b>←</b> <b>→</b> 選擇後按 <b>Enter</b> 確認，<b>Esc</b> 取消。預設選中「取消」。
圖片會移到<b>資源回收筒</b>，可以還原。壓縮檔內的圖片只會從清單移除，不會修改壓縮檔。</p>
<h3>縮放與平移</h3>
<ul>
<li>每格右側的 <b>＋ / － / 1:1</b>，或 Ctrl＋滾輪（以游標為中心）、鍵盤 <b>+ -</b>。</li>
<li><b>/</b> 或 <b>0</b>：已選格恢復原本的填滿畫面；<b>*</b>：全部格子恢復。</li>
<li>按住左鍵拖曳平移；雙擊放大 2 倍，再雙擊還原。</li>
</ul>
<h3>其他</h3>
<ul>
<li><b>H</b>：隱藏／顯示工具列（隱藏後按左上角「☰ 工具列」叫回）。</li>
<li><b>F</b> 或 <b>F11</b>：全螢幕，<b>Esc</b> 離開。</li>
<li><b>F1</b>：這份說明。支援 JPG、PNG、GIF、BMP、WebP、TIFF、HEIC / HEIF（iPhone）等，並依 EXIF 自動轉正。</li>
</ul>
"""


class HelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"使用說明 — {APP_NAME}")
        self.setObjectName("about")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        tbw = QTextBrowser()
        tbw.setOpenExternalLinks(True)
        tbw.setHtml(HELP_HTML)
        lay.addWidget(tbw)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("關閉")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)


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
        add("多格排列看圖程式：自訂 橫×直 版面，單張模式每格各自瀏覽、漫畫模式連續翻頁，"
            "支援資料夾與 ZIP / RAR / 7Z 壓縮檔，以及 JPG / PNG / WebP / TIFF / HEIC。")
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
QMenuBar {{ background: {C_PANEL.name()}; color: {C_FG.name()}; border-bottom: 1px solid {C_LINE.name()}; }}
QMenuBar::item {{ padding: 4px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: {C_LINE.name()}; }}
QMenu {{ background: {C_PANEL.name()}; color: {C_FG.name()}; border: 1px solid {C_LINE.name()}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px; }}
QMenu::item:selected {{ background: {C_ACCENT.name()}; color: #1a1407; }}
QDialog, QMessageBox {{ background: {C_PANEL.name()}; }}
QTextBrowser {{ background: {C_BG.name()}; color: {C_FG.name()}; border: 1px solid {C_LINE.name()}; padding: 6px; }}
QPushButton:focus {{ border: 2px solid {C_ACCENT.name()}; }}
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
