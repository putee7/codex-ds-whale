# 第三方素材与运行时

## 鲸鱼娘角色与原始素材

- 来源：[Sutera-Diffusus/dsh-whale-musume](https://github.com/Sutera-Diffusus/dsh-whale-musume)
- 原作者：Sutera-Diffusus
- 许可：MIT，原文如下。

```text
MIT License

Copyright (c) 2026 Sutera-Diffusus

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

本项目以原角色素材为基础制作方向注视、呼吸和动作模板。新增动作使用 OpenAI ImageGen 制作，吃饭提示词见 [docs/prompts/eating.md](docs/prompts/eating.md)。生成工具的使用不改变原始素材必须保留的署名和许可。

交互设计参考了公开桌宠设计思路，未复制参考“大肥鱼”仓库的代码。本项目不是 OpenAI 或原角色作者的官方产品。

## CPython 嵌入式运行时

Release 随附来自 [python.org](https://www.python.org/downloads/windows/) 的官方 CPython 3.13.17 Windows x64 嵌入式运行时，源码包安装时也从该官方来源下载。该运行时仅在项目目录内使用，不安装到全局。

CPython 使用 PSF License Version 2，并含适用各自许可的组件。运行时内的原始 `LICENSE.txt` 和相关许可文件须随分发保留；本项目的 MIT 许可不替代这些条款。完整历史与许可见 [Python 官方许可说明](https://docs.python.org/3.13/license.html)。

本项目未修改 CPython 源码；项目启动和模块搜索配置只用于运行本项目。
