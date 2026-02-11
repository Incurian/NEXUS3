import * as vscode from "vscode";
import type { ToolResult } from "../types";

/** Persisted last selection — survives focus changes */
let lastSelection: SelectionData | null = null;

interface SelectionData {
  filePath: string;
  text: string;
  startLine: number;
  startCharacter: number;
  endLine: number;
  endCharacter: number;
}

/**
 * Track selection changes. Call during activation.
 */
export function trackSelections(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.window.onDidChangeTextEditorSelection((event) => {
      const editor = event.textEditor;
      const sel = event.selections[0];
      if (!sel || sel.isEmpty) {
        return;
      }
      lastSelection = {
        filePath: editor.document.uri.fsPath,
        text: editor.document.getText(sel),
        startLine: sel.start.line + 1,
        startCharacter: sel.start.character,
        endLine: sel.end.line + 1,
        endCharacter: sel.end.character,
      };
    })
  );
}

export async function handleGetCurrentSelection(): Promise<ToolResult> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.selection.isEmpty) {
    return { content: [{ type: "text", text: "null" }] };
  }

  const sel = editor.selection;
  const data: SelectionData = {
    filePath: editor.document.uri.fsPath,
    text: editor.document.getText(sel),
    startLine: sel.start.line + 1,
    startCharacter: sel.start.character,
    endLine: sel.end.line + 1,
    endCharacter: sel.end.character,
  };

  return { content: [{ type: "text", text: JSON.stringify(data) }] };
}

export async function handleGetLatestSelection(): Promise<ToolResult> {
  if (!lastSelection) {
    return { content: [{ type: "text", text: "null" }] };
  }
  return { content: [{ type: "text", text: JSON.stringify(lastSelection) }] };
}
