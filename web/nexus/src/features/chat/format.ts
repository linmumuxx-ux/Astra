export function renderMarkdown(value: string): string {
  const escaped = value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

export function isImage(type: string): boolean {
  return type.startsWith("image/");
}

export function formatSize(size: number): string {
  if (size < 1024) return "小于 1 KB";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1048576).toFixed(1)} MB`;
}

export interface ContactToolParsed {
  text: string;
  isJson: boolean;
  isError: boolean;
}

export function formatContactEmployeeTool(input: string, output: string): ContactToolParsed {
  let targetEmployee = "";
  if (input) {
    try {
      const parsedInput = JSON.parse(input);
      if (typeof parsedInput.employee_name === "string" && parsedInput.employee_name.trim()) {
        targetEmployee = parsedInput.employee_name.trim();
      }
    } catch {
      // Input is not valid JSON
    }
  }

  const trimmedOutput = output ? output.trim() : "";
  if (!trimmedOutput) {
    return {
      text: targetEmployee ? `正在联系 ${targetEmployee}` : "正在联系员工",
      isJson: true,
      isError: false,
    };
  }

  try {
    const parsedOutput = JSON.parse(trimmedOutput);
    if (typeof parsedOutput === "object" && parsedOutput !== null) {
      const emp = parsedOutput.employee || targetEmployee || "员工";
      if (parsedOutput.status === "failed") {
        const reason = parsedOutput.reason ? `：${parsedOutput.reason}` : "";
        return {
          text: `联系失败${reason}`,
          isJson: true,
          isError: true,
        };
      }
      return {
        text: `已联系 ${emp}`,
        isJson: true,
        isError: false,
      };
    }
  } catch {
    // Output is not JSON
  }

  return {
    text: "联系结果",
    isJson: false,
    isError: false,
  };
}
