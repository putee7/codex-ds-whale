# 兼容性与排查

## 已验证范围

| 项目 | 范围 |
| --- | --- |
| 操作系统 | Windows 10/11 x64 |
| Codex 实测版本 | 26.1023.6621.0 |
| 客户端形态 | MSIX 安装，WindowsApps 内的 `ChatGPT.exe` |
| 显示方式 | Codex 官方 Mini 中的同一只鲸鱼娘 |
| Python | Release 内置 CPython 3.13.17 嵌入式运行时 |

鼠标方向、注视呼吸、持续随机悬停动作已在真实桌面窗口验收。表格不代表所有 Windows 构建、显示缩放、多屏组合和未来 Codex 版本均已验证。

macOS、Linux 和 Windows ARM64 不支持。

## 客户端更新

增强使用内部本机 IPC `query-cache-invalidate`，不是公开稳定的 Pet 扩展 API。客户端更新可能改变进程、窗口、素材加载或缓存刷新方式。

其他 Codex 版本默认拒绝增强模式。`--allow-untested` 仅供明确选择试运行，不能作为“兼容已验证”的依据。具体调用方式请查看 `python app/run.py --help` 及对应子命令帮助。遇到异常先运行 `Stop.cmd`，保留官方 Pet，再运行 `Doctor.cmd`。

## 常见情况

| 现象 | 操作 |
| --- | --- |
| 看不到鲸鱼娘 | 在 Codex 设置 → Mini 与虚拟宠物刷新、选择鲸鱼娘，并显示官方 Mini |
| 有宠物，没有增强 | 运行 `Start.cmd`；用 `Doctor.cmd` 检查版本和安装状态 |
| 关闭并重开 Codex 后尚未互动 | 控制器会等待选择和显示条件，再自动重连；确认 Mini 已显示且选中鲸鱼娘 |
| Windows 重启后没有增强 | 再运行 `Start.cmd`；本项目没有默认登录自启 |
| 源码 ZIP 无法离线安装 | 使用包含 Python 运行时的 Release 发布包 |
| 希望关闭方向和悬停增强 | 运行 `Stop.cmd`，保留官方 Pet 及基准呼吸 |

不要用静态母版手动覆盖控制器正在管理的素材。需要卸载时用 `Uninstall.cmd`，由安装备份决定恢复原先的同名 Pet，还是删除本项目安装的那个。

## 动画设置

注视呼吸由 WebP 容器内部动画播放，不会自动遵循 Codex 的“减少动态效果”开关。`Stop.cmd` 可关闭方向和悬停增强，官方 Pet 及基准呼吸仍保留，不会完全静止。

## 报告问题

提交 Codex 版本、Windows 版本、显示缩放、复现步骤，以及脱敏后的 `Doctor.cmd` 输出。不要上传全局状态 JSON、凭据、聊天、个人目录或完整用户配置。未验证版本请注明是否显式使用了 `--allow-untested`。
