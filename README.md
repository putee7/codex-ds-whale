# Codex 鲸鱼娘 · Windows

让 Codex 官方 Mini 里的同一只鲸鱼娘看向鼠标、轻轻呼吸，并在悬停时随机小跳、挥手、拿铁盆吃白米饭。

这是社区项目。无需修改 Codex 客户端，不创建第二个桌宠窗口。角色源自 [Sutera-Diffusus/dsh-whale-musume](https://github.com/Sutera-Diffusus/dsh-whale-musume)，沿用其 MIT 许可；新增动作使用 ImageGen 制作。

| 小跳 | 挥手 | 吃饭 |
| --- | --- | --- |
| ![小跳预览](docs/previews/hop.gif) | ![挥手预览](docs/previews/waving.gif) | ![铁盆吃白米饭预览](docs/previews/eating.gif) |

预览展示单个动作；桌面上的随机顺序由控制器决定。

## 使用前

- 仅支持 **Windows 10/11 x64**。
- 已在 **Codex 26.1023.6621.0** 的 MSIX WindowsApps `ChatGPT.exe` 上实测。其他版本默认拒绝增强模式；`--allow-untested` 是明确选择试运行，不代表兼容性已验证。
- 增强依赖内部本机 IPC `query-cache-invalidate`，不是公开稳定的 Pet 扩展 API。Codex 更新后可能需要适配。详见[兼容性](docs/compatibility.md)。

## 安装和启动

1. 从 [Releases](https://github.com/putee7/codex-whale-musume/releases) 下载发布包，解压后运行 `Install.cmd`。发布包包含项目专用的 CPython 3.13.17，无需另装 Python，也不安装到全局。
2. 打开 Codex，在 **设置 → Mini 与虚拟宠物** 刷新并选择“鲸鱼娘”，显示官方 Mini。
3. 运行 `Start.cmd`，启动后台控制器。它会等待 Codex 打开、鲸鱼娘被选中及 Mini 显示，条件满足后自动连接。

从 GitHub 下载的源码 ZIP 不含 Python 运行时，首次运行 `Install.cmd` 会从 `python.org` 的固定地址下载并核对 SHA-256。离线安装请用 Release 发布包。

默认程序安装到 `%LOCALAPPDATA%\CodexWhaleMusume`，宠物安装到 `%CODEX_HOME%\pets\whale-musume`；未设置 `CODEX_HOME` 时采用 Codex 默认目录。支持 `--home` 和 `--install-dir` 指定测试或自定义位置，参数位置以 `python app/run.py --help` 及其子命令帮助为准。

## 怎么互动

- 鼠标进入角色中心约 **500 DIP** 范围，空闲时按 **16 个方向**注视，并以 **3.2 秒**一轮、不超过 **1 像素**的幅度轻呼吸。DIP 是 Windows 的逻辑像素，显示缩放会影响对应的屏幕像素数。
- 离开 **550 DIP** 范围，或鼠标静止 **4 秒**，回到普通待机。进入与退出范围留有余量，减少边界抖动。
- 鼠标停在角色身上，随机轮换小跳、挥手、吃饭，每轮覆盖三种，不连续重复，动作之间约 **0.7 秒**停顿。悬停属于持续互动，不会因静止四秒中断。
- 拖动、工作、等待等官方动作仍保留；拖动优先于鼠标互动。

## 停止、排查、卸载

| 入口 | 用途 |
| --- | --- |
| `Start.cmd` | 启动增强控制器；关闭并重开 Codex 后，后台控制器会自动重连 |
| `Stop.cmd` | 停止增强，保留官方宠物及基准呼吸 |
| `Doctor.cmd` | 检查环境、安装和兼容性 |
| `Uninstall.cmd` | 卸载本项目，恢复安装前已存在的同名宠物备份，或删除本项目安装的宠物 |

没有默认登录自启；**Windows 重启后需再运行 `Start.cmd`**。安装不会替你修改 `config.toml` 的宠物选择，请在官方设置里选中鲸鱼娘。卸载保留其他宠物、Codex 配置和登录状态。

若没有出现增强动作，先检查官方 Mini 是否显示、当前选择是否为鲸鱼娘，再运行 `Doctor.cmd`。遇到版本不支持，先停止增强并查看[兼容性说明](docs/compatibility.md)，不要把跳过版本检查当作修复。

## 数据和实现

控制器读取本机鼠标位置、宠物窗口几何、`config.toml` 中的宠物选择和全局状态 JSON 中两个 Pet 设置键。它会解析这些设置文件，只使用指定字段，不访问会话文件或 `auth.json`，不使用或输出无关字段。IPC 使用自己的新本机身份，不注入客户端，不发送遥测；安装源码包时下载 Python 是单独的安装步骤。

增强通过更新同一宠物目录里的素材并通知官方窗口刷新实现。运行 `Stop.cmd` 可停止方向和悬停增强，基准呼吸仍保留；内部 WebP 动画不会自动遵循 Codex 的“减少动态效果”设置。[架构说明](docs/architecture.md)列出了读取、写入和退出行为。

## 开发与许可

开发入口为 `python app/run.py`，测试命令：

```text
python -m unittest discover -s tests
```

请使用明确的 Python 3.13 环境。贡献要求见 [CONTRIBUTING.md](CONTRIBUTING.md)，吃饭动作提示词见 [docs/prompts/eating.md](docs/prompts/eating.md)。

预构建素材已随仓库提供，部署不需要 Pillow。若要从批准母版与吃饭帧重新编码素材，安装 `requirements-build.txt` 后运行 `python tools/rebuild_assets.py --output build/pet`；它只写指定构建目录，不操作本机 Codex。离线发布包可在准备好固定运行时并暂存 Git 文件后，用 `python scripts/build_release.py` 构建。

本项目代码采用 [MIT](LICENSE)。角色及原始素材版权归原作者，完整原始许可和 Python 运行时说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
