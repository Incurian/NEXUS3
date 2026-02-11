import * as vscode from "vscode";
import type {
  CheckDocumentDirtyParams,
  SaveDocumentParams,
  ToolResult,
} from "../types";

export async function handleCheckDocumentDirty(
  params: CheckDocumentDirtyParams
): Promise<ToolResult> {
  const uri = vscode.Uri.file(params.filePath);
  const doc = vscode.workspace.textDocuments.find(
    (d) => d.uri.fsPath === uri.fsPath
  );
  const dirty = doc?.isDirty ?? false;
  return { content: [{ type: "text", text: JSON.stringify({ dirty }) }] };
}

export async function handleSaveDocument(
  params: SaveDocumentParams
): Promise<ToolResult> {
  const uri = vscode.Uri.file(params.filePath);
  const doc = vscode.workspace.textDocuments.find(
    (d) => d.uri.fsPath === uri.fsPath
  );
  if (doc) {
    await doc.save();
  }
  return { content: [{ type: "text", text: "ok" }] };
}
