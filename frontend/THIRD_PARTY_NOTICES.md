# 首页办公室第三方代码与素材说明

首页工位的状态驱动工作动画适配自 [k1dav-c/agent-virtual-office](https://github.com/k1dav-c/agent-virtual-office/blob/08296c84283faef5a82390c48723ae1ee8b06710/frontend/src/App.css) 的 `agent-typing`、`agent-body-bob` 与 `monitor-flicker`。来源提交：`08296c84283faef5a82390c48723ae1ee8b06710`。

CSS 动画结构调整位移、速度与 Astra 真实状态门控。连续房间、桌椅及人物使用下面列出的 workbzw 原素材；Vue 展示适配、SSE 接入及业务跳转由 Astra 实现。

以下保留原项目 MIT 许可：

```text
MIT License

Copyright (c) 2025 k1dav Lab

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


## workbzw 连续办公室

来源：[workbzw/ai-office-react](https://github.com/workbzw/ai-office-react)，提交 `72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96`。

- 房间背景、桌面和椅子原样复制自 [public/assets/office](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/public/assets/office)，项目路径为 `public/assets/office/office.png`、`desk.png`、`chair.png`。
- 工位阵列、座位偏移、桌椅锚点与分层规则适配自 [officeLayout.ts](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/src/scene/layout/officeLayout.ts)、[DeskEntity.ts](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/src/scene/entities/DeskEntity.ts) 和 [deskDepthSort.ts](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/src/scene/systems/deskDepthSort.ts)。
- 人物来源为 [Chibi Stickers 原始 Spine 资源](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/public/assets/characters/chibi-stickers)，使用 [SpineCharacter.ts](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/src/scene/characters/SpineCharacter.ts) 的 `movement/idle-front`、`movement/idle-back` 姿势及 [chibiStickerSkins.ts](https://github.com/workbzw/ai-office-react/blob/72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96/src/scene/characters/chibiStickerSkins.ts) 的9套皮肤顺序。
- 原人物经官方 Spine Canvas 离线渲染为 `public/assets/office/characters/character-{index}-{front|back}.png`：固定256×320透明画布、同一缩放和足部基线，4倍分辨率抗锯齿采样。索引与可见边界记录在同目录 `manifest.json`。
- 离线脚本保存于 `evidence/digital-office-home-20261001/bake-open-source-characters.mjs`，依赖仅安装于临时制作目录；应用展示使用PNG和Vue，未添加 Pixi、Spine 或 React 运行时依赖。

上游仓库许可原文：

```text
MIT License

Copyright (c) 2026 teejoo

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

## 离线 Spine 素材工具

人物制作使用 `@esotericsoftware/spine-canvas@4.2.120` 与 `@napi-rs/canvas`。Spine工具仅在离线制作目录执行，以下保留其上游声明：

```text
Spine Runtimes License Agreement
Last updated April 5, 2025. Replaces all prior versions.

Copyright (c) 2013-2025, Esoteric Software LLC

Integration of the Spine Runtimes into software or otherwise creating
derivative works of the Spine Runtimes is permitted under the terms and
conditions of Section 2 of the Spine Editor License Agreement:
http://esotericsoftware.com/spine-editor-license

Otherwise, it is permitted to integrate the Spine Runtimes into software
or otherwise create derivative works of the Spine Runtimes (collectively,
"Products"), provided that each user of the Products must obtain their own
Spine Editor license and redistribution of the Products in any form must
include this license and copyright notice.

THE SPINE RUNTIMES ARE PROVIDED BY ESOTERIC SOFTWARE LLC "AS IS" AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL ESOTERIC SOFTWARE LLC BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES,
BUSINESS INTERRUPTION, OR LOSS OF USE, DATA, OR PROFITS) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
THE SPINE RUNTIMES, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
