"""Offline playback regression tests. Requires a local FFmpeg executable for fixtures."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_MEDIA_BACKEND', 'ffmpeg')
os.environ.setdefault('QT_FFMPEG_DECODING_HW_DEVICE_TYPES', ',')
import subprocess
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtGui import QImage, QFont
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from multigrid_viewer import Viewer, STYLE, list_folder


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)
        cls.app.setFont(QFont('Microsoft JhengHei UI', 10))
        fixtures = Path(__file__).resolve().parent / 'build/test-fixtures'
        fixtures.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='mgv video 測試 ', dir=fixtures)
        cls.folder = Path(cls.temp.name)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cls.folder / 'settings'))
        ffmpeg = os.environ['MGV_TEST_FFMPEG']
        for name, color, size in [('01-wide.mp4', 'red', '320x180'),
                                   ('02-tall.mp4', 'green', '180x320')]:
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            f'color=c={color}:s={size}:r=10', '-t', '0.8', '-c:v', 'mpeg4',
                            str(cls.folder / name)], check=True)
        im = QImage(80, 40, QImage.Format_RGB32)
        im.fill(Qt.blue)
        im.save(str(cls.folder / 'image.png'))

    @classmethod
    def tearDownClass(cls):
        cls.app.processEvents()
        cls.temp.cleanup()

    def setUp(self):
        QSettings('Skypray', 'MultiGridViewer').clear()
        self.viewer = Viewer([])
        self.viewer.resize(1400, 800)
        self.viewer.set_layout(2, 1)
        self.viewer.show()
        self.app.processEvents()

    def tearDown(self):
        self.viewer.close()
        self.viewer.deleteLater()
        self.app.processEvents()

    def wait_for(self, predicate, timeout=8000):
        for _ in range(timeout // 20):
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(20)
        self.fail('Timed out waiting for playback: ' + repr([
            (c._video_error, c.player.mediaStatus() if c.player else None)
            for c in self.viewer.cells]))

    def load_video(self, index=0):
        cell = self.viewer.cells[index]
        self.viewer.load_paths(cell, [str(self.folder / '01-wide.mp4')])
        self.wait_for(lambda: not cell._video_image.isNull())
        return cell

    def test_filter_and_auto_mode(self):
        self.assertEqual(len(list_folder(str(self.folder), videos=True)), 2)
        self.assertEqual(len(list_folder(str(self.folder))), 1)
        cell = self.load_video()
        self.assertEqual(self.viewer.mode, 'video')
        self.assertEqual(len(cell.items), 2)
        self.assertEqual(cell.player.loops(), QMediaPlayer.Infinite)
        self.assertEqual(self.viewer.video_fit, 'cover')
        rect = cell.base_rect(cell._video_image)
        self.assertGreaterEqual(rect.width() + .01, cell.width())
        self.assertGreaterEqual(rect.height() + .01, cell.height())
        self.assertAlmostEqual(rect.width() / rect.height(), 320 / 180)

    def test_pause_resume_next_and_loop(self):
        cell = self.load_video()
        cell.pause_video()
        self.wait_for(lambda: cell.player.playbackState() == QMediaPlayer.PausedState)
        position = cell.player.position()
        QTest.qWait(180)
        self.assertEqual(cell.player.position(), position)
        QTest.keyClick(self.viewer, Qt.Key_Space)
        self.wait_for(lambda: cell.player.playbackState() == QMediaPlayer.PlayingState)
        self.assertEqual(cell.idx, 0)
        positions = []
        cell.player.positionChanged.connect(positions.append)
        QTest.qWait(2200)
        self.assertEqual(cell.idx, 0, 'Loop must replay this video, not advance the playlist')
        self.assertTrue(any(b < a for a, b in zip(positions, positions[1:])), positions)
        self.viewer.nav(1)
        self.wait_for(lambda: cell._video_image.width() == 180)
        self.assertEqual(cell.idx, 1)
        self.assertEqual(cell.player.playbackState(), QMediaPlayer.PlayingState)

    def test_selection_audio_and_clear(self):
        first = self.load_video()
        second = self.load_video(1)
        self.assertTrue(first.audio.isMuted())
        self.assertFalse(second.audio.isMuted())
        self.viewer.select(first)
        self.assertFalse(first.audio.isMuted())
        self.assertTrue(second.audio.isMuted())
        self.viewer.clear_cell()
        self.assertTrue(first.player.source().isEmpty())
        self.assertEqual(first.player.playbackState(), QMediaPlayer.StoppedState)
        self.viewer.set_layout(1, 1)
        self.assertTrue(second.player.source().isEmpty())

    def test_invalid_video_recovers(self):
        bad = self.folder / '00-broken.mp4'
        bad.write_bytes(b'not a video')
        try:
            cell = self.viewer.cells[0]
            self.viewer.load_paths(cell, [str(bad)])
            self.wait_for(lambda: bool(cell._video_error))
            self.viewer.nav(1)
            self.wait_for(lambda: not cell._video_image.isNull())
            self.assertFalse(cell._video_error)
        finally:
            for c in self.viewer.cells:
                c.stop_video()
            bad.unlink()

    def test_mode_restore_and_image_regression(self):
        cell = self.viewer.cells[0]
        self.viewer.load_paths(cell, [str(self.folder / 'image.png')])
        self.assertFalse(cell.rail.isVisible())
        self.load_video()
        self.viewer.set_mode('single')
        self.assertTrue(cell.current().endswith('image.png'))
        self.assertTrue(cell.player.source().isEmpty())
        self.viewer.set_mode('comic')
        self.assertTrue(cell.current().endswith('image.png'))
        self.viewer.set_mode('video')
        self.wait_for(lambda: not cell._video_image.isNull())
        self.assertTrue(cell.current().endswith('01-wide.mp4'))
        self.viewer.load_paths(cell, [str(self.folder / 'image.png')])
        self.assertEqual(self.viewer.mode, 'single')
        cell.zoom_center(1.25)
        self.assertEqual(cell.scale, 1.25)
        cell.reset_zoom()
        self.assertEqual(cell.scale, 1.0)

    def test_hover_controls_and_preview(self):
        cell = self.load_video()
        self.assertFalse(cell.rail.isVisible())
        cell._update_zoom_rail(QPoint(cell.width() - 1, cell.height() // 2))
        self.assertTrue(cell.rail.isVisible())
        self.assertTrue(all(b.isVisible() for b in cell.video_buttons))
        QTest.mouseClick(cell.video_buttons[1], Qt.LeftButton)
        self.assertEqual(cell.player.playbackState(), QMediaPlayer.PausedState)
        QTest.mouseClick(cell.video_buttons[0], Qt.LeftButton)
        self.assertEqual(cell.player.playbackState(), QMediaPlayer.PlayingState)
        QTest.mouseClick(cell.video_buttons[3], Qt.LeftButton)
        self.wait_for(lambda: cell._video_image.width() == 180)
        QTest.mouseClick(cell.video_buttons[2], Qt.LeftButton)
        self.wait_for(lambda: cell._video_image.width() == 320)
        QTest.keyClick(self.viewer, Qt.Key_PageDown)
        self.wait_for(lambda: cell._video_image.width() == 180)
        QTest.keyClick(self.viewer, Qt.Key_PageUp)
        self.wait_for(lambda: cell._video_image.width() == 320)
        second = self.viewer.cells[1]
        self.viewer.load_paths(second, [str(self.folder / '01-wide.mp4')])
        self.wait_for(lambda: not second._video_image.isNull())
        cell.pause_video()
        second.pause_video()
        output = os.environ.get('MGV_TEST_PREVIEW')
        if output:
            self.viewer.grab().save(output)
        cell._update_zoom_rail(QPoint(20, 20))
        self.assertFalse(cell.rail.isVisible())


if __name__ == '__main__':
    unittest.main(verbosity=2)
