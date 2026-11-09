# DSH 上游增量核对

## 2026-11-09：核对至 v2.5.3

上游是 [Sutera-Diffusus/dsh-whale-musume](https://github.com/Sutera-Diffusus/dsh-whale-musume)。截至本次核对，最新正式版为 [v2.5.3](https://github.com/Sutera-Diffusus/dsh-whale-musume/releases/tag/v2.5.3)，2026-11-08 发布。

| 基线 | 固定提交 |
| --- | --- |
| Codex v1.2.0 素材来源，对应上游 2.5.0 | `53551978177ce8ecb005ebef8b55395ffd0f172a` |
| 本次核对的 main，后续增量从此处继续 | `a0092b90c1343808bdf560f04b0d94b89444471f` |
| v2.5.3 发布标签 | `3928dfa` |

[完整差分](https://github.com/Sutera-Diffusus/dsh-whale-musume/compare/53551978177ce8ecb005ebef8b55395ffd0f172a...a0092b90c1343808bdf560f04b0d94b89444471f)包含 19 个提交。原始角色素材目录 `assets/generated` 的 Git tree 在两个基线均为 `578def74dc4dcb9c9d2ef5241007fb0e2ceb8503`，没有新增或修改立绘，原始 LICENSE 也未变。

## 逐项适配

| 上游增量 | Codex 官方 Pet 的处理 |
| --- | --- |
| [2.5.1](https://github.com/Sutera-Diffusus/dsh-whale-musume/blob/a0092b90c1343808bdf560f04b0d94b89444471f/docs/changelog-2.5.1.md)：关闭再打开、宿主重挂载时图片透明 | 修复对象是 DSH JavaScript 的 `layerState` 与新图片 DOM 不一致。Codex 版不使用该 DOM 或缓存；现有控制器在官方窗口不可见／客户端断开后清除几何和交互状态，恢复时重新注册 IPC 并刷新同一 Pet。无需复制 DSH 补丁。 |
| [2.5.2](https://github.com/Sutera-Diffusus/dsh-whale-musume/blob/a0092b90c1343808bdf560f04b0d94b89444471f/docs/changelog-2.5.2.md)：触屏拖拽、500ms 长按菜单、主指针及轻微移动判定 | 依赖 DSH 图片节点的 pointer 事件和自己的菜单。官方 Codex Pet 的事件由客户端管理，本项目未接入等价的触摸／菜单接口；本次不移植，也不将其标为 Codex 已支持。 |
| 2.5.2：80–240px 尺寸滑块、右键尺寸切换、窄屏默认大小 | 依赖 DSH 设置面板、右键菜单与 `localStorage`。Codex 版继续只读取官方 Pet 已保存的尺寸做定位，不写 DSH 尺寸、不增加另一套缩放设置，也不改客户端以加入滑块。 |
| 2.5.2：存储异常处理、菜单高度与触屏 CSS | 属于上述 DSH 界面实现。Codex 版不使用这些存储项、菜单或 CSS，无运行代码可合并。 |
| 2.5.1／[2.5.3](https://github.com/Sutera-Diffusus/dsh-whale-musume/blob/a0092b90c1343808bdf560f04b0d94b89444471f/docs/changelog-2.5.3.md)：放宽 DSH 安装版本线 | DSH 宿主门禁不适用于 Codex。Codex v1.1.0 起已按实际进程、窗口和 IPC 协议检查，不单凭版本号阻止启动；仍不把未验证版本当成已验证。 |
| README 动图、npm 发布说明、下载徽章及相关测试 | 保留上游自己的发布内容；不替换本项目的动作预览或安装说明。 |

本轮只同步核对记录。Codex 运行版保持 **v1.2.0**，17 个模式、15 张原 DSH 姿势、注视呼吸及小跳／挥手／吃饭保留；未发布新的运行包、未重启或更换已安装控制器。素材来源提交继续保留实际取材时的值，避免把“已核对新版本”误写成“重新取材”。

## 核对方法与后续增量

通过官方 Release、固定提交的发布说明和完整源码差分核对，另外比较角色素材目录的 Git tree，以及本项目引用的 15 张原图逐文件 SHA-256。当前源码运行原有测试与公开文件检查。运行日志用于检查进程和接口，不能代替人工画面验收。

下次从本次固定的 main 提交继续比较；只对实际变更的姿势或适用行为做增量，更新来源与验证记录。工作姿势的原始来源仍见 [素材注册表](../artwork/modes/registry.json)。
