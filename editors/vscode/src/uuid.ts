import * as crypto from "crypto";

/**
 * Generate a UUID v4 string using Node.js crypto.
 */
export function v4(): string {
  return crypto.randomUUID();
}
