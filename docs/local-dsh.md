# DSH Q 版鲸鱼娘（Windows）

Q 版在同一个 Codex Mini 中统一了待机、转头、拖动、工作和悬停的外观。保留 16 向注视、轻呼吸、小跳、挥手和铁盆吃饭。长时间工作会按状态轮换动作；等待确认优先，闲置约 10 分钟会睡下。

克隆 [GitHub 源码](https://github.com/putee7/codex-ds-whale)，或下载 GitHub 的源码 ZIP；基础版 Windows 离线包不含补帧。准备 Windows x64、Python 3.13，以及 PATH 中的 FFmpeg（需含 `libvpx-vp9` 解码器）和 FFprobe，然后在源码目录运行：

```powershell
py -3.13 -m pip install -r requirements-build.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 prepare-runtime
py -3.13 tools/build_local_dsh.py build/dsh-sources build/dsh-union --fetch --appearance artwork/dsh-chibi
.\build\dsh-union\Install.cmd
```

`prepare-runtime` 只准备和校验嵌入式 Python。`--fetch` 只从 [PC2005-cloud/dsh-pet 的固定提交](https://github.com/PC2005-cloud/dsh-pet/tree/c25386848f70f6e40902e4376f6e7b1e196bc326) 下载缺失的源动画并校验哈希，原始视频和生成图集都留在 `build/`。已有缓存时可去掉 `--fetch` 离线构建；重建请选择新的输出目录。生成包的安装和使用不依赖 FFmpeg、Pillow 或全局 Python。

安装会更新当前 Codex home 里同一处鲸鱼娘安装。首次启用参照[主说明](../README.md)选择本地鲸鱼娘。基础离线包仍是原来的风格；已安装 Q 版时，后续用 Q 版构建包升级。

动画由 PC2005-cloud 项目制作，鲸鱼娘设计出自 ZipZipPipe、原型出自上善无形。上游的动画与衍生 Q 版素材沿用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，代码与基础版授权单独保留。见[补帧素材及署名](../artwork/dsh-chibi/LICENSE.md)。生成包附有 `pet/APPEARANCE-LICENSE.md`、`pet/APPEARANCE.json` 和 `pet/action-bank/PROVENANCE.json`。
