import * as vscode from "vscode";
import type {
  CheckDocumentDirtyParams,
  CloseTabParams,
  GetDiagnosticsParams,
  OpenDiffParams,
  OpenFileParams,
  SaveDocumentParams,
  ToolDefinition,
  ToolResult,
} from "../types";
import { handleOpenDiff } from "./openDiff";
import { handleOpenFile } from "./openFile";
import { handleGetDiagnostics } from "./diagnostics";
import {
  handleGetCurrentSelection,
  handleGetLatestSelection,
} from "./selection";
import { handleGetWorkspaceFolders } from "./workspace";
import { handleCheckDocumentDirty, handleSaveDocument } from "./document";
import { handleCloseTab, handleCloseAllDiffTabs } from "./tabs";

type ToolHandler = (args: Record<string, unknown>) => Promise<ToolResult>;

async function handleGetOpenEditors(): Promise<ToolResult> {
  const editors: Array<{
    filePath: string;
    isActive: boolean;
    isDirty: boolean;
    languageId: string | null;
  }> = [];

  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputText) {
        editors.push({
          filePath: tab.input.uri.fsPath,
          isActive: tab.isActive,
          isDirty: tab.isDirty,
          languageId: null, // Not available from tab API
        });
      }
    }
  }

  return { content: [{ type: "text", text: JSON.stringify(editors) }] };
}

const toolHandlers: Record<string, ToolHandler> = {
  openDiff: (args) => handleOpenDiff(args as unknown as OpenDiffParams),
  openFile: (args) => handleOpenFile(args as unknown as OpenFileParams),
  getDiagnostics: (args) =>
    handleGetDiagnostics(args as unknown as GetDiagnosticsParams),
  getCurrentSelection: () => handleGetCurrentSelection(),
  getLatestSelection: () => handleGetLatestSelection(),
  getOpenEditors: () => handleGetOpenEditors(),
  getWorkspaceFolders: () => handleGetWorkspaceFolders(),
  checkDocumentDirty: (args) =>
    handleCheckDocumentDirty(args as unknown as CheckDocumentDirtyParams),
  saveDocument: (args) =>
    handleSaveDocument(args as unknown as SaveDocumentParams),
  closeTab: (args) => handleCloseTab(args as unknown as CloseTabParams),
  closeAllDiffTabs: () => handleCloseAllDiffTabs(),
};

export function getToolDefinitions(): ToolDefinition[] {
  return [
    {
      name: "openDiff",
      description:
        "Show a diff in the editor for the user to accept or reject changes",
      inputSchema: {
        type: "object",
        properties: {
          old_file_path: { type: "string", description: "Path to the original file" },
          new_file_path: { type: "string", description: "Path for the modified file" },
          new_file_contents: { type: "string", description: "Proposed file contents" },
          tab_name: { type: "string", description: "Label for the diff tab" },
        },
        required: ["old_file_path", "new_file_path", "new_file_contents", "tab_name"],
      },
    },
    {
      name: "openFile",
      description: "Open a file in the editor",
      inputSchema: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "File path to open" },
          preview: { type: "boolean", description: "Open in preview mode" },
        },
        required: ["filePath"],
      },
    },
    {
      name: "getDiagnostics",
      description: "Get LSP diagnostics (errors, warnings) from the editor",
      inputSchema: {
        type: "object",
        properties: {
          uri: { type: "string", description: "File URI to get diagnostics for (all files if omitted)" },
        },
      },
    },
    {
      name: "getCurrentSelection",
      description: "Get the current text selection in the active editor",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "getLatestSelection",
      description: "Get the most recent text selection (persists across focus changes)",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "getOpenEditors",
      description: "List all open editor tabs",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "getWorkspaceFolders",
      description: "Get workspace folder paths",
      inputSchema: { type: "object", properties: {} },
    },
    {
      name: "checkDocumentDirty",
      description: "Check if a file has unsaved changes",
      inputSchema: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "File path to check" },
        },
        required: ["filePath"],
      },
    },
    {
      name: "saveDocument",
      description: "Save an open document",
      inputSchema: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "File path to save" },
        },
        required: ["filePath"],
      },
    },
    {
      name: "closeTab",
      description: "Close a specific editor tab by name",
      inputSchema: {
        type: "object",
        properties: {
          tabName: { type: "string", description: "Tab label to close" },
        },
        required: ["tabName"],
      },
    },
    {
      name: "closeAllDiffTabs",
      description: "Close all NEXUS3 diff tabs",
      inputSchema: { type: "object", properties: {} },
    },
  ];
}

export async function handleToolCall(
  name: string,
  args: Record<string, unknown>
): Promise<ToolResult> {
  const handler = toolHandlers[name];
  if (!handler) {
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
    };
  }
  return handler(args);
}
