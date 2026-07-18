#!/usr/bin/env node
// CLI/std entry point: stdio transport for local use
const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");

const server = new McpServer({
  name: "correctover",
  version: "1.3.1",
});

server.tool("health", "Check server health.", {},
  async () => ({ content: [{ type: "text", text: "OK" }] })
);

server.tool("providers", "List supported LLM providers.", {},
  async () => ({ content: [{ type: "text", text: "anthropic, openai, deepseek, mistral, google supported" }] })
);

server.tool("stats", "View session statistics.", {},
  async () => ({ content: [{ type: "text", text: "Session active" }] })
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[correctover] stdio MCP server running");
}

main().catch(err => {
  console.error("[correctover] Fatal:", err);
  process.exit(1);
});
