/**
 * Shared types for the NEXUS3 VS Code extension.
 */

/** MCP JSON-RPC request */
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: number | string;
  method: string;
  params?: Record<string, unknown>;
}

/** MCP JSON-RPC response */
export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number | string;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

/** MCP JSON-RPC notification (no id) */
export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

/** MCP tool definition for tools/list response */
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

/** MCP tool call result */
export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
}

/** Pending diff resolution callback */
export interface PendingDiff {
  resolve: (value: string) => void;
  filePath: string;
}

/** Lock file contents */
export interface LockFileData {
  pid: number;
  workspaceFolders: string[];
  ideName: string;
  transport: string;
  authToken: string;
}

/** Parameters for openDiff tool */
export interface OpenDiffParams {
  old_file_path: string;
  new_file_path: string;
  new_file_contents: string;
  tab_name: string;
}

/** Parameters for openFile tool */
export interface OpenFileParams {
  filePath: string;
  preview?: boolean;
}

/** Parameters for getDiagnostics tool */
export interface GetDiagnosticsParams {
  uri?: string;
}

/** Parameters for checkDocumentDirty tool */
export interface CheckDocumentDirtyParams {
  filePath: string;
}

/** Parameters for saveDocument tool */
export interface SaveDocumentParams {
  filePath: string;
}

/** Parameters for closeTab tool */
export interface CloseTabParams {
  tabName: string;
}
