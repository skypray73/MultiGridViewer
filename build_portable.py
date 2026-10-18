"""Build a portable folder; keep Python, Qt and FFmpeg DLLs outside the launcher."""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent


def repair_icu(folder):
    """Do not ship a Python-runtime ICU that shadows Windows' Qt-compatible ICU."""
    import pefile
    internal = folder / '_internal'
    bundled = internal / 'icuuc.dll'
    qtcore = internal / 'PySide6/Qt6Core.dll'
    if os.name != 'nt' or not bundled.exists():
        return
    qt_pe = pefile.PE(str(qtcore))
    required = {i.name for dep in qt_pe.DIRECTORY_ENTRY_IMPORT if dep.dll.lower() == b'icuuc.dll'
                for i in dep.imports if i.name}
    qt_pe.close()
    def exports(path):
        pe = pefile.PE(str(path))
        result = {symbol.name for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols if symbol.name}
        pe.close()
        return result
    if not required or required <= exports(bundled):
        return
    system_icu = Path(os.environ['SystemRoot']) / 'System32/icuuc.dll'
    if not required <= exports(system_icu):
        raise RuntimeError('Neither bundled nor system ICU satisfies QtCore imports')
    pe = pefile.PE(str(bundled))
    data_dlls = [dep.dll.decode() for dep in pe.DIRECTORY_ENTRY_IMPORT
                 if dep.dll.lower().startswith(b'icudt')]
    pe.close()
    bundled.unlink()
    # The rejected ICU is the only consumer of its versioned data library.
    for name in data_dlls:
        consumers = []
        for path in internal.rglob('*.dll'):
            candidate = pefile.PE(str(path), fast_load=True)
            candidate.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            if any(dep.dll.decode().lower() == name.lower()
                   for dep in getattr(candidate, 'DIRECTORY_ENTRY_IMPORT', [])):
                consumers.append(path)
            candidate.close()
        if not consumers and (internal / name).is_file():
            (internal / name).unlink()
    print('Removed incompatible bundled ICU; Qt will use the matching Windows system ICU.')


def package():
    folder = ROOT / 'dist/MultiGridViewer'
    if not (folder / 'MultiGridViewer.exe').is_file():
        raise RuntimeError('Build the portable folder first')
    repair_icu(folder)
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, folder / name)
    if (ROOT / 'licenses').is_dir():
        shutil.copytree(ROOT / 'licenses', folder / 'licenses', dirs_exist_ok=True)
    for name in ('Qt-LGPL-3.0.txt', 'FFmpeg-LGPL-2.1.txt', 'FFmpeg-LICENSE.md'):
        (folder / 'licenses').mkdir(exist_ok=True)
        shutil.copy2(ROOT / name, folder / 'licenses' / name)
    versions = []
    for name in ('PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'Pillow', 'pillow-heif'):
        dist = importlib.metadata.distribution(name)
        versions.append(f'{name}: {dist.version}')
        for rel in dist.files or []:
            if 'licenses' in rel.parts or Path(str(rel)).name.upper().startswith(('LICENSE', 'COPYING')):
                source = Path(dist.locate_file(rel))
                if source.is_file():
                    target = folder / 'licenses' / name / Path(*rel.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (folder / 'VERSIONS.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
    (folder / '使用說明.txt').write_text(
        '請完整解壓縮 ZIP，再執行 MultiGridViewer.exe。\n'
        '保留 _internal 資料夾，內含 Python、Qt、FFmpeg DLL 與圖片解碼元件。\n'
        '影片模式：每格單部循環；右側邊緣浮出播放／暫停／上一部／下一部；PageUp 上一部、PageDown 下一部；←／→ 前後 10 秒。\n'
        '同列時間軸可點擊或拖曳；每格 🔊／🔇 可獨立切換聲音。\n新開影片預設只有最後一部發聲，其他格可手動開啟。\n預設等比填滿（邊緣裁切）；顯示選單可切換完整顯示。\n', encoding='utf-8')
    archive = Path(shutil.make_archive(str(ROOT / 'dist/MultiGridViewer-Portable-v1.3.0'),
                                      'zip', folder.parent, folder.name))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    source_zip = ROOT / 'dist/MultiGridViewer-Source-v1.3.0.zip'
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).decode().split('\0')
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for rel in sorted(set(paths) - {''}):
            path = ROOT / rel
            if path.is_file():
                bundle.write(path, 'MultiGridViewer/' + rel)
    print('Ready:', archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-only', action='store_true', help='ZIP an existing (optionally signed) build')
    args = parser.parse_args()
    if not args.package_only:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--windowed', '--onedir', '--collect-all', 'pillow_heif',
                        '--version-file', str(ROOT / 'version_info.txt'), '--name', 'MultiGridViewer',
                        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
                        '--specpath', str(ROOT / 'build'), str(ROOT / 'multigrid_viewer.py')],
                       cwd=ROOT, check=True)
    package()
