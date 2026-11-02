# Codex 鲸鱼娘 · Windows

让 Codex 官方 Mini 里的同一只鲸鱼娘看向鼠标、轻轻呼吸，并在悬停时随机小跳、挥手、拿铁盆吃白米饭。

这是社区项目。无需修改 Codex 客户端，不创建第二个桌宠窗口。角色源自 [Sutera-Diffusus/dsh-whale-musume](https://github.com/Sutera-Diffusus/dsh-whale-musume)，沿用其 MIT 许可；新增动作使用 ImageGen 制作。

当前版本 **v1.1.0**。升级用户直接运行新版 `Install.cmd`，程序迁移到唯一目录；下载统一使用[最新 Windows 离线包](https://github.com/putee7/codex-ds-whale/releases/latest)，变更见 [CHANGELOG](CHANGELOG.md)。

| 小跳 | 挥手 | 吃饭 |
| --- | --- | --- |
| ![小跳预览](docs/previews/hop.gif) | ![挥手预览](docs/previews/waving.gif) | ![铁盆吃白米饭预览](docs/previews/eating.gif) |

预览展示单个动作；桌面上的随机顺序由控制器决定。

## 使用前

- 仅支持 **Windows 10/11 x64**。
- 已在 **Codex 26.1023.6621.0、26.1027.3384.0** 实测；新版重开后，转头、注视呼吸及三种悬停动作均获用户确认恢复。v1.1.0 起按实际接口检查后尝试恢复，版本号变化不再单独阻止启动；未来版本不因此被标记为已验证。
- 增强依赖内部本机 IPC `query-cache-invalidate`，不是公开稳定的 Pet 扩展 API。Codex 更新后可能需要适配。详见[兼容性](docs/compatibility.md)。

## 安装和启动

1. 从[最新 Release](https://github.com/putee7/codex-ds-whale/releases/latest) 下载 Windows x64 ZIP，解压后运行 `Install.cmd`。发布包包含项目专用的 CPython 3.13.17，无需另装 Python，也不安装到全局。
2. 如果安装时 Codex 正在运行，请**完全退出 Codex，等约 5 秒再打开**。后台控制器会在客户端关闭后设置本地素材模式，避免自动迁到无法持续读取本地动态图集的云端副本。
3. 在 **设置 → Mini 与虚拟宠物** 选择本地“鲸鱼娘”，显示官方 Mini。安装会通过当前用户的计划任务运行唯一后台控制器，不依赖 Codex 父进程存活。`--no-start` 安装不会启动、注册任务或排队修改偏好。

从 GitHub 下载的源码 ZIP 不含 Python 运行时，首次运行 `Install.cmd` 会从 `python.org` 的固定地址下载并核对 SHA-256。离线安装请用 Release 发布包。

程序统一安装到 Codex home 下 `pet-tools\codex-whale-runtime`，宠物位于 `pets\whale-musume`。不依赖 MSIX 可能重定向的 `%LOCALAPPDATA%`。升级会移动原有项目安装，保留一套运行文件；维护入口通过同一安装记录转发，并核对实际路径、版本和代码摘要。支持 `--home`、`--install-dir`，同一 home 拒绝绑定第二处安装，旧包拒绝覆盖新版。

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
| `Repair.cmd` | 排队修复本地鲸鱼娘；完全退出 Codex 后应用，再打开 |
| `EnableRecovery.cmd` | 启用登录及每分钟检查的自动恢复任务 |
| `DisableRecovery.cmd` | 移除自动恢复任务，当前增强控制器可继续运行 |
| `Uninstall.cmd` | 卸载本项目，恢复安装前已存在的同名宠物备份，或删除本项目安装的宠物 |

v1.1.0 的自动恢复任务仅在当前用户登录会话运行，不提权、不保存密码；控制器意外退出或 Windows 重新登录后，通常在一分钟内重新启动。`Stop.cmd` 设置持久暂停，任务不会把你主动停止的控制器重新拉起；运行 `Start.cmd` 才解除暂停。卸载会移除本项目的任务。

新版 Codex 会自动将 `custom:whale-musume` 迁到 `pet_…` 云端 ID，并隐藏已迁移的本地条目。云端图片不会读取本地转头/悬停素材。v1.1.0 在 Codex **全部进程退出后**，只清理该鲸鱼娘的迁移映射，并用内部 `pending-cloud-pet-migrations-v1` 的 `failedPermanently` 记录阻止其再次上传；不删除云端宠物、不更改账号的云端选择、不影响其他宠物。该处理是内部偏好兼容方式，格式变化会明确报错，并非官方公开的开关。

修复会备份本地偏好，并仅在选择仍等于排队修复时的值时恢复本地鲸鱼娘；期间手动改选其他 Pet 会被保留。运行中不直接改选择配置，因为那不会更新客户端内存缓存。卸载前需关闭 Codex，以恢复本项目改动的迁移偏好。

若没有出现增强动作，先检查官方 Mini 是否显示、当前选择是否为鲸鱼娘，再运行 `Doctor.cmd`。自检会核对控制器互斥状态，进程消失时不会把旧日志误报为运行中。接口检查失败会明确报错，请查看[兼容性说明](docs/compatibility.md)。

v1.0.2起，Windows暂时拒绝鼠标位置读取时，状态会显示 `waiting_for_desktop`，回到正常可访问桌面后自动继续。控制器不会尝试切换到安全桌面，也不要求管理员权限；文件权限错误及其他未知接口错误仍会明确报错。

## 数据和实现

控制器读取本机鼠标位置、Codex 进程及窗口几何、宠物选择、位置/大小与宠物迁移偏好。关闭客户端后，只改动鲸鱼娘对应的本地迁移条目与已授权的选择项，其他状态值保持不变；本机备份可能含个人设置，请勿上传。它不访问会话文件或 `auth.json`，不使用或输出无关字段。IPC 使用自己的新本机身份，不注入客户端，不发送遥测；安装源码包时下载 Python 是单独的安装步骤。

增强通过更新同一宠物目录里的素材并通知官方窗口刷新实现。运行 `Stop.cmd` 可停止方向和悬停增强，基准呼吸仍保留；内部 WebP 动画不会自动遵循 Codex 的“减少动态效果”设置。[架构说明](docs/architecture.md)列出了读取、写入和退出行为。

## 开发与许可

开发入口为 `python app/run.py`，测试命令：

```text
python -m unittest discover -s tests
```

请使用明确的 Python 3.13 环境。贡献要求见 [CONTRIBUTING.md](CONTRIBUTING.md)，吃饭动作提示词见 [docs/prompts/eating.md](docs/prompts/eating.md)。

预构建素材已随仓库提供，部署不需要 Pillow。若要从批准母版与吃饭帧重新编码素材，安装 `requirements-build.txt` 后运行 `python tools/rebuild_assets.py --output build/pet`；它只写指定构建目录，不操作本机 Codex。离线发布包可在准备好固定运行时并暂存 Git 文件后，用 `python scripts/build_release.py` 构建。

本项目代码采用 [MIT](LICENSE)。角色及原始素材版权归原作者，完整原始许可和 Python 运行时说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
