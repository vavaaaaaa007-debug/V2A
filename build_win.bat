@echo off
chcp 65001 >nul
REM Windows 打包：安装 Python 3.10+ 后双击运行，生成 dist\视频转音频.exe
cd /d "%~dp0"
python -m venv .venv
.venv\Scripts\pip install -q -r requirements.txt
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name "视频转音频" ^
  --icon assets\icon.ico --add-data "assets\icon.png;assets" ^
  --collect-all imageio_ffmpeg --collect-all tkinterdnd2 --collect-all customtkinter video2audio.py
echo 完成：dist\视频转音频.exe
pause
