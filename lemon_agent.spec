# -*- mode: python ; coding: utf-8 -*-
"""
Lemon Agent PyInstaller 打包配置
================================
用法:
    pip install pyinstaller
    pyinstaller lemon_agent.spec

产出:
    dist/lemon_agent/          — 单目录分发
    dist/lemon_agent.exe       — 单文件模式（可选）
"""

import os
import sys

block_cipher = None

PROJECT_ROOT = os.path.abspath('.')

datas = [
    ('bridge', 'bridge'),
    ('shared', 'shared'),
    ('config', 'config'),
    ('data', 'data'),
    ('standard_mode/ui', 'standard_mode/ui'),
    ('standard_mode/core', 'standard_mode/core'),
    ('standard_mode/run.bat', 'standard_mode'),
    # v5.0.0: hybrid mode + HTML panel + formation config
    ('hybrid_mode', 'hybrid_mode'),
    ('hybrid_mode_wireframe.html', '.'),
    ('config/hybrid_formation.json', 'config'),
]

_stdio_src = os.path.join(os.path.dirname(os.path.abspath('.')), '小米AI', 'mimo-gui', 'electron-stdio.js')
if not os.path.exists(_stdio_src):
    _stdio_src = r'D:\xiaomi_temp\小米AI\mimo-gui\electron-stdio.js'
if os.path.exists(_stdio_src):
    datas.append((_stdio_src, 'mimo-gui'))

excluded_dirs = {
    '__pycache__', '.pytest_cache', '.mypy_cache',
    'node_modules', '.git', '.venv', '_py312',
    'tools', 'scripts', 'outputs', 'tests',
    '.hvigor', 'build', 'hap',
}

binaries = []
hiddenimports = [
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebChannel',
    'PyQt5.QtWebSockets',
    'PyQt5.QtNetwork',
    'winpty',
    'pygments',
    'markdown',
    'yaml',
    # v5.0.0 hybrid mode
    'hybrid_mode.core.hybrid_mode_bridge',
    'hybrid_mode.core.commander_server',
    'hybrid_mode.core.company_runtime',
    'hybrid_mode.server',
    'shared.multi_instance_manager',
    'shared.sub_agent',
    'shared.role_system',
]

a = Analysis(
    ['bin/mimo_serve.py'],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(excluded_dirs) + ['tkinter', 'unittest', 'xmlrpc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lemon_agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lemon_agent',
)
