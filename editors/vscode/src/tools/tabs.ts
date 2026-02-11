import * as vscode from "vscode";
import type { CloseTabParams, ToolResult } from "../types";

export async function handleCloseTab(
  params: CloseTabParams
): Promise<ToolResult> {
  // Find tab by label matching
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.label === params.tabName) {
        await vscode.window.tabGroups.close(tab);
        return { content: [{ type: "text", text: "ok" }] };
      }
    }
  }
  return { content: [{ type: "text", text: "ok" }] };
}

export async function handleCloseAllDiffTabs(): Promise<ToolResult> {
  const tabsToClose: vscode.Tab[] = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputTextDiff) {
        const uri = tab.input.modified;
        if (uri.scheme === "nexus3-diff") {
          tabsToClose.push(tab);
        }
      }
    }
  }
  for (const tab of tabsToClose) {
    await vscode.window.tabGroups.close(tab);
  }
  return { content: [{ type: "text", text: "ok" }] };
}
