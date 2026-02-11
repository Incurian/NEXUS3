import * as vscode from "vscode";
import type { OpenDiffParams, PendingDiff, ToolResult } from "../types";

/** Map of tab_name → proposed file content */
const proposedContent = new Map<string, string>();

/** Map of tab_name → pending resolution callback */
const pendingDiffs = new Map<string, PendingDiff>();

/**
 * TextDocumentContentProvider for the nexus3-diff scheme.
 * Serves proposed file content for the right side of the diff editor.
 */
class DiffContentProvider implements vscode.TextDocumentContentProvider {
  private _onDidChange = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this._onDidChange.event;

  provideTextDocumentContent(uri: vscode.Uri): string {
    return proposedContent.get(uri.query) ?? "";
  }

  update(uri: vscode.Uri): void {
    this._onDidChange.fire(uri);
  }
}

const diffProvider = new DiffContentProvider();

/**
 * Handle the openDiff tool call.
 * Opens VS Code's diff editor and returns a Promise that resolves
 * when the user clicks Accept or Reject (or closes the tab).
 */
export async function handleOpenDiff(
  params: OpenDiffParams
): Promise<ToolResult> {
  const { old_file_path, new_file_path, new_file_contents, tab_name } = params;

  // Store proposed content for the content provider
  proposedContent.set(tab_name, new_file_contents);

  // Create URIs
  const originalUri = vscode.Uri.file(old_file_path);
  const proposedUri = vscode.Uri.from({
    scheme: "nexus3-diff",
    path: new_file_path,
    query: tab_name,
  });

  // Refresh content provider
  diffProvider.update(proposedUri);

  // Open VS Code's native diff editor
  await vscode.commands.executeCommand(
    "vscode.diff",
    originalUri,
    proposedUri,
    `NEXUS3: ${tab_name}`
  );

  // Return a Promise that resolves when user clicks Accept or Reject
  const result = await new Promise<string>((resolve) => {
    pendingDiffs.set(tab_name, { resolve, filePath: new_file_path });
  });

  return { content: [{ type: "text", text: result }] };
}

/**
 * Register diff-related commands and content provider.
 * Must be called during extension activation.
 */
export function registerDiffCommands(
  context: vscode.ExtensionContext
): void {
  // Register content provider for nexus3-diff scheme
  context.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(
      "nexus3-diff",
      diffProvider
    )
  );

  // Accept command — write file and resolve promise
  context.subscriptions.push(
    vscode.commands.registerCommand("nexus3.diffAccept", async () => {
      const tabName = getActiveDiffTabName();
      if (!tabName || !pendingDiffs.has(tabName)) {
        return;
      }

      const pending = pendingDiffs.get(tabName)!;
      const content = proposedContent.get(tabName);
      if (content !== undefined) {
        // Write the proposed content to disk
        await vscode.workspace.fs.writeFile(
          vscode.Uri.file(pending.filePath),
          Buffer.from(content, "utf-8")
        );
      }

      // Resolve the pending promise → sends JSON-RPC response
      pending.resolve("FILE_SAVED");
      cleanup(tabName);

      // Close the diff tab
      await vscode.commands.executeCommand(
        "workbench.action.closeActiveEditor"
      );
    })
  );

  // Reject command — resolve promise without writing
  context.subscriptions.push(
    vscode.commands.registerCommand("nexus3.diffReject", async () => {
      const tabName = getActiveDiffTabName();
      if (!tabName || !pendingDiffs.has(tabName)) {
        return;
      }

      pendingDiffs.get(tabName)!.resolve("DIFF_REJECTED");
      cleanup(tabName);

      await vscode.commands.executeCommand(
        "workbench.action.closeActiveEditor"
      );
    })
  );

  // Safety net — if user closes diff tab without clicking either button
  context.subscriptions.push(
    vscode.window.tabGroups.onDidChangeTabs((event) => {
      for (const closed of event.closed) {
        if (closed.input instanceof vscode.TabInputTextDiff) {
          const uri = closed.input.modified;
          if (uri.scheme === "nexus3-diff") {
            const tabName = uri.query;
            if (pendingDiffs.has(tabName)) {
              pendingDiffs.get(tabName)!.resolve("DIFF_REJECTED");
              cleanup(tabName);
            }
          }
        }
      }
    })
  );
}

/**
 * Extract the tab name from the currently active diff tab.
 */
function getActiveDiffTabName(): string | undefined {
  const activeTab = vscode.window.tabGroups.activeTabGroup.activeTab;
  if (!activeTab) {
    return undefined;
  }
  if (activeTab.input instanceof vscode.TabInputTextDiff) {
    const uri = activeTab.input.modified;
    if (uri.scheme === "nexus3-diff") {
      return uri.query;
    }
  }
  return undefined;
}

/**
 * Clean up state for a resolved diff.
 */
function cleanup(tabName: string): void {
  pendingDiffs.delete(tabName);
  proposedContent.delete(tabName);
}
