import * as ws from "ws";
import type {
  JsonRpcRequest,
  JsonRpcResponse,
  ToolDefinition,
  ToolResult,
} from "./types";
import { getToolDefinitions, handleToolCall } from "./tools";

const MCP_PROTOCOL_VERSION = "2024-11-05";
const SERVER_INFO = { name: "nexus3-ide", version: "0.1.0" };

export type AuthToken = string;

export interface MCPServer {
  server: ws.WebSocketServer;
  port: number;
  close: () => void;
}

export function createMCPServer(authToken: AuthToken): Promise<MCPServer> {
  return new Promise((resolve, reject) => {
    const server = new ws.WebSocketServer({ host: "127.0.0.1", port: 0 });

    server.on("listening", () => {
      const addr = server.address();
      if (typeof addr === "object" && addr !== null) {
        const port = addr.port;
        console.log(`NEXUS3 IDE MCP server listening on 127.0.0.1:${port}`);
        resolve({
          server,
          port,
          close: () => {
            for (const client of server.clients) {
              client.close();
            }
            server.close();
          },
        });
      } else {
        reject(new Error("Failed to get server address"));
      }
    });

    server.on("error", reject);

    server.on("connection", (socket, req) => {
      // Validate auth token
      const token = req.headers["x-nexus3-ide-authorization"];
      if (token !== authToken) {
        console.warn("Rejected connection: invalid auth token");
        socket.close(4001, "Unauthorized");
        return;
      }

      console.log("NEXUS3 client connected");
      handleConnection(socket);
    });
  });
}

function handleConnection(socket: ws.WebSocket): void {
  socket.on("message", async (data) => {
    let request: JsonRpcRequest;
    try {
      request = JSON.parse(data.toString());
    } catch {
      sendError(socket, null, -32700, "Parse error");
      return;
    }

    try {
      const response = await handleRequest(request);
      if (response) {
        socket.send(JSON.stringify(response));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Internal error";
      if (request.id !== undefined) {
        sendError(socket, request.id, -32603, message);
      }
    }
  });

  socket.on("close", () => {
    console.log("NEXUS3 client disconnected");
  });

  socket.on("error", (err) => {
    console.error("WebSocket error:", err.message);
  });
}

async function handleRequest(
  request: JsonRpcRequest
): Promise<JsonRpcResponse | null> {
  const { method, id } = request;

  // Notifications (no id) — don't send a response
  if (id === undefined) {
    // Handle notifications/initialized silently
    return null;
  }

  switch (method) {
    case "initialize":
      return {
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: { tools: {} },
          serverInfo: SERVER_INFO,
        },
      };

    case "tools/list":
      return {
        jsonrpc: "2.0",
        id,
        result: {
          tools: getToolDefinitions(),
        },
      };

    case "tools/call": {
      const params = request.params as
        | { name: string; arguments?: Record<string, unknown> }
        | undefined;
      if (!params?.name) {
        return {
          jsonrpc: "2.0",
          id,
          error: { code: -32602, message: "Missing tool name" },
        };
      }
      const result = await handleToolCall(
        params.name,
        (params.arguments as Record<string, unknown>) ?? {}
      );
      return {
        jsonrpc: "2.0",
        id,
        result,
      };
    }

    default:
      return {
        jsonrpc: "2.0",
        id,
        error: { code: -32601, message: `Method not found: ${method}` },
      };
  }
}

function sendError(
  socket: ws.WebSocket,
  id: number | string | null,
  code: number,
  message: string
): void {
  const response: JsonRpcResponse = {
    jsonrpc: "2.0",
    id: id ?? 0,
    error: { code, message },
  };
  socket.send(JSON.stringify(response));
}
