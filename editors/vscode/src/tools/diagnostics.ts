import * as vscode from "vscode";
import type { GetDiagnosticsParams, ToolResult } from "../types";

export async function handleGetDiagnostics(
  params: GetDiagnosticsParams
): Promise<ToolResult> {
  let diagnostics: [vscode.Uri, readonly vscode.Diagnostic[]][];

  if (params.uri) {
    const uri = vscode.Uri.parse(params.uri);
    const fileDiags = vscode.languages.getDiagnostics(uri);
    diagnostics = [[uri, fileDiags]];
  } else {
    diagnostics = vscode.languages.getDiagnostics();
  }

  const result = diagnostics.flatMap(([uri, diags]) =>
    diags.map((d) => ({
      filePath: uri.fsPath,
      line: d.range.start.line + 1, // 1-indexed
      message: d.message,
      severity: severityToString(d.severity),
      source: d.source ?? undefined,
    }))
  );

  return { content: [{ type: "text", text: JSON.stringify(result) }] };
}

function severityToString(severity: vscode.DiagnosticSeverity): string {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return "error";
    case vscode.DiagnosticSeverity.Warning:
      return "warning";
    case vscode.DiagnosticSeverity.Information:
      return "info";
    case vscode.DiagnosticSeverity.Hint:
      return "hint";
    default:
      return "info";
  }
}
