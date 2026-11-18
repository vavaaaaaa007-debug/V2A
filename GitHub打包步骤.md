# 用 GitHub 自动打包 Windows + Mac 版本

## 1. 建仓库
登录 github.com → 右上角「+」→ New repository → 名字填 `video2audio` → Create repository。

## 2. 上传文件
在新仓库页面点「uploading an existing file」，把本文件夹里的文件全部拖进去 → Commit changes。

> ⚠️ Mac 的访达默认看不到 `.github` 隐藏文件夹，拖的时候可能漏掉它。
> 上传后如果仓库里没有 `.github` 文件夹，就这样补上：
> 点「Add file」→「Create new file」→ 文件名输入 `.github/workflows/build.yml`
> → 把「build.yml（备用-复制到GitHub）.txt」里的内容全部粘贴进去 → Commit changes。

## 3. 等它打包
点仓库上方的「Actions」，会看到「打包 视频转音频」正在运行（第一次大约 5–10 分钟）。
如果没自动运行：点左侧「打包 视频转音频」→ 右侧「Run workflow」。

## 4. 下载
运行完成（绿色 ✓）后点进去，页面最下面 Artifacts 里有：
- **视频转音频-Windows** → 解压得到 `video2audio.exe`，双击就能用
- **视频转音频-Mac-Apple芯片** → M1/M2/M3/M4 等新款 Mac 用
- **视频转音频-Mac-Intel芯片** → 老款 Intel Mac 用

## 提示
- Windows 第一次打开如出现「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」。
- Mac 第一次打开如提示「无法验证开发者」：右键 App →「打开」。
- 下载的 Artifacts 默认保留 90 天，记得把软件存到自己电脑上。
