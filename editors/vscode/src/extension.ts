import * as vscode from "vscode";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { createMCPServer, type MCPServer } from "./server";
import { registerDiffCommands } from "./tools/openDiff";
import { trackSelections } from "./tools/selection";
import { v4 as uuidv4 } from "./uuid";

let mcpServer: MCPServer | undefined;
let lockFilePath: string | undefined;

export async function activate(
  context: vscode.ExtensionContext
): Promise<void> {
  console.log("NEXUS3 IDE integration activating...");

  // Generate auth token
  const authToken = uuidv4();

  // Ensure lock directory exists
  const lockDir = path.join(os.homedir(), ".nexus3", "ide");
  fs.mkdirSync(lockDir, { recursive: true });

  try {
    // Start MCP server
    mcpServer = await createMCPServer(authToken);

    // Write lock file
    const lockData = {
      pid: process.pid,
      workspaceFolders: vscode.workspace.workspaceFolders?.map(
        (f) => f.uri.fsPath
      ) ?? [],
      ideName: "VS Code",
      transport: "ws",
      authToken,
    };

    lockFilePath = path.join(lockDir, `${mcpServer.port}.lock`);
    fs.writeFileSync(lockFilePath, JSON.stringify(lockData, null, 2), {
      encoding: "utf-8",
      mode: 0o600,
    });

    console.log(
      `NEXUS3 IDE: server on port ${mcpServer.port}, lock file: ${lockFilePath}`
    );

    // Register diff accept/reject commands and selection tracking
    registerDiffCommands(context);
    trackSelections(context);

    // Update lock file when workspace folders change
    context.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        if (lockFilePath) {
          const updatedData = {
            ...lockData,
            workspaceFolders: vscode.workspace.workspaceFolders?.map(
              (f) => f.uri.fsPath
            ) ?? [],
          };
          try {
            fs.writeFileSync(
              lockFilePath,
              JSON.stringify(updatedData, null, 2),
              { encoding: "utf-8", mode: 0o600 }
            );
          } catch {
            // Non-fatal
          }
        }
      })
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`NEXUS3 IDE: failed to start: ${message}`);
    vscode.window.showErrorMessage(
      `NEXUS3 IDE integration failed to start: ${message}`
    );
  }
}

export function deactivate(): void {
  // Delete lock file
  if (lockFilePath) {
    try {
      fs.unlinkSync(lockFilePath);
    } catch {
      // File may already be gone
    }
    lockFilePath = undefined;
  }

  // Close server
  if (mcpServer) {
    mcpServer.close();
    mcpServer = undefined;
  }

  console.log("NEXUS3 IDE integration deactivated");
}
