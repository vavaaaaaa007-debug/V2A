#!/bin/bash
# Mac 打包：双击或在终端运行 ./build_mac.sh，生成 dist/视频转音频.app
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pyinstaller --noconfirm --windowed --name "视频转音频" \
  --osx-bundle-identifier com.local.video2audio \
  --icon assets/icon.icns --add-data "assets/icon.png:assets" \
  --collect-all imageio_ffmpeg --collect-all tkinterdnd2 --collect-all customtkinter video2audio.py
echo "完成：dist/视频转音频.app"
