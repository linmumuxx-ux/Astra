// ASTRA 任务工作区主题覆盖：用户消息在右、OpenCode 消息在左并明确身份，
// Tool / 文件修改 / 命令执行等系统事件弱化，不与正常对话抢视觉层级。
// 只依赖上游稳定的 data-component / data-slot 属性，不修改 upstream 源码。
export const ASTRA_THEME_CSS = `
[data-slot="session-turn-message-content"] { display: flex; flex-direction: column; }

[data-component="user-message"] {
  width: fit-content;
  max-width: min(760px, 84%);
  margin-left: auto;
  padding: 10px 14px;
  border: 1px solid #cbe7dc;
  border-radius: 14px 14px 4px 14px;
  background: #e7f7f0;
}
[data-component="user-message"]::before {
  content: "你";
  display: block;
  margin-bottom: 4px;
  color: #0c8a5b;
  font-size: 11px;
  font-weight: 600;
}
[data-component="user-message"] [data-slot="user-message-text"] { color: #123d31; }

[data-slot="session-turn-assistant-content"] {
  width: min(860px, 100%);
  margin-right: auto;
}
[data-slot="session-turn-assistant-content"]::before {
  content: "OpenCode";
  display: block;
  margin: 10px 0 6px;
  color: #5b7a70;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

[data-component="text-part"] { line-height: 1.72; }

/* 系统事件：工具调用、推理、压缩分隔、shell 输出等弱化显示。 */
[data-component="tool-part-wrapper"],
[data-component="reasoning-part"],
[data-component="compaction-part"],
[data-component="shell-submessage"] {
  opacity: 0.66;
}
[data-component="tool-part-wrapper"] { font-size: 12.5px; }
`