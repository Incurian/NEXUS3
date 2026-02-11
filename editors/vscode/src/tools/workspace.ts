import * as vscode from "vscode";
import type { ToolResult } from "../types";

export async function handleGetWorkspaceFolders(): Promise<ToolResult> {
  const folders =
    vscode.workspace.workspaceFolders?.map((f) => f.uri.fsPath) ?? [];
  return { content: [{ type: "text", text: JSON.stringify(folders) }] };
}
