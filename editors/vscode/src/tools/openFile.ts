import * as vscode from "vscode";
import type { OpenFileParams, ToolResult } from "../types";

export async function handleOpenFile(
  params: OpenFileParams
): Promise<ToolResult> {
  const uri = vscode.Uri.file(params.filePath);
  const options: vscode.TextDocumentShowOptions = {
    preview: params.preview ?? false,
  };
  await vscode.window.showTextDocument(uri, options);
  return { content: [{ type: "text", text: "ok" }] };
}
