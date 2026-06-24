# -*- mode: python ; coding: utf-8 -*-
"""
MSDS Label Maker v2.0.0 - PyInstaller 패키징 설정
"""
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

APP_DIR   = os.path.dirname(os.path.abspath(SPEC))
FLET_DIR  = os.path.join(os.path.expanduser("~"), ".flet", "client",
                         "flet-desktop-full-0.85.2", "flet")

# ── 포함할 데이터 파일 ──────────────────────────────────────
datas = [
    # GHS 그림문자 이미지 → assets 서브폴더 (flet.exe 에 전달될 assets_dir)
    (os.path.join(APP_DIR, "ghs_images"), "assets/ghs_images"),
    (os.path.join(APP_DIR, "safety_signs"), "assets/safety_signs"),
    # 앱 아이콘 → assets 서브폴더
    (os.path.join(APP_DIR, "app_icon.png"), "assets"),
    # ICO 는 루트에도 복사 (EXE 아이콘용)
    (os.path.join(APP_DIR, "app_icon.ico"), "."),
    # Flet 데스크톱 클라이언트 (Flutter 렌더러)
    (FLET_DIR, "flet_client"),
]

# Flet 패키지 데이터 파일(icons.json 등) 포함 → ft.Icons 사용 시 런타임 오류 방지
datas += collect_data_files("flet")

# ── 숨겨진 임포트 ───────────────────────────────────────────
hiddenimports = [
    "flet",
    "flet_desktop",
    "fitz",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "asyncio",
    "concurrent.futures",
    "threading",
    "webbrowser",
    "re",
    "html",
    "base64",
]

block_cipher = None

a = Analysis(
    [os.path.join(APP_DIR, "main_flet.py")],
    pathex=[APP_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy"],
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
    name="MSDS_Label_Maker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(APP_DIR, "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MSDS_Label_Maker",
)
