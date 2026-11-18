# 视频转音频（Mac / Windows）

一键批量把视频（mp4、mov、mkv、avi、wmv、flv、webm、m4v、ts、3gp、mpg 等）转成音频。
**默认输出 MP3（320k）**，也可以选 WAV / M4A / FLAC。软件已内置 ffmpeg，不用另外安装。
界面有浅色（薄荷绿）和深色（黑色）两种，默认浅色，右上角一键切换。

## 使用
1. 打开「视频转音频」
2. 点「添加视频」或「添加文件夹」（会扫描子文件夹），也可以直接把文件拖进列表；软件会自动识别视频，跳过非视频文件
3. 选格式（默认 MP3）→ 点「▶ 一键开始转换」
4. 音频默认保存在原视频旁边，文件名相同；同名文件会自动加 (1)、(2)，不会覆盖

## 打包
- Mac：运行 `./build_mac.sh` → `dist/视频转音频.app`
- Windows：在 Windows 电脑上安装 Python 3.10+，双击 `build_win.bat` → `dist\视频转音频.exe`（单个 exe 文件，直接发给别人用）
- 或者把本文件夹推送到 GitHub，Actions 会同时自动打出 Windows 和 Mac 版本

## 命令行（可选）
`python video2audio.py --cli <文件或文件夹...> [--format mp3|wav|m4a|flac]`

> Mac 首次打开如提示「无法验证开发者」：右键 App →「打开」。

## 图标
`assets/` 里是软件图标（Mac 用 icon.icns，Windows 用 icon.ico），`make_icon.py` 可重新生成。
