#!/usr/bin/env node
const http = require("http");
const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StreamableHTTPServerTransport } = require("@modelcontextprotocol/sdk/server/streamableHttp.js");
const { z } = require("zod");

const PORT = parseInt(process.env.PORT || "8080");

function createServer() {
  const server = new McpServer({
    name: "correctover",
    version: "1.3.1",
  });

  // Tool: health
  server.tool("health", "Check server health status.", {},
    async () => {
      return { content: [{ type: "text", text: JSON.stringify({ status: "ok", version: "1.3.1", uptime: Math.round((Date.now() - startTime) / 1000) }) }] };
    }
  );

  // Tool: providers
  server.tool("providers", "List supported LLM providers and their status.", {},
    async () => {
      const providers = [
        { name: "anthropic", env: "ANTHROPIC_API_KEY", configured: !!process.env.ANTHROPIC_API_KEY },
        { name: "openai", env: "OPENAI_API_KEY", configured: !!process.env.OPENAI_API_KEY },
        { name: "deepseek", env: "DEEPSEEK_API_KEY", configured: !!process.env.DEEPSEEK_API_KEY },
        { name: "mistral", env: "MISTRAL_API_KEY", configured: !!process.env.MISTRAL_API_KEY },
        { name: "google", env: "GOOGLE_API_KEY", configured: !!process.env.GOOGLE_API_KEY },
      ];
      return { content: [{ type: "text", text: JSON.stringify(providers) }] };
    }
  );

  // Tool: stats
  server.tool("stats", "View session statistics.", {},
    async () => {
      return { content: [{ type: "text", text: JSON.stringify({ uptime: Math.round((Date.now() - startTime) / 1000), calls: 0 }) }] };
    }
  );

  return server;
}

const startTime = Date.now();

// HTTP server
const httpServer = http.createServer(async (req, res) => {
  // Server card for Smithery scanning
  if (req.url === "/.well-known/mcp/server-card.json") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      serverInfo: { name: "correctover", version: "1.3.1" },
      authentication: { required: false },
      tools: [
        { name: "health", description: "Check server health status.", inputSchema: { type: "object", properties: {} } },
        { name: "providers", description: "List supported LLM providers.", inputSchema: { type: "object", properties: {} } },
        { name: "stats", description: "View session statistics.", inputSchema: { type: "object", properties: {} } },
      ],
      resources: [],
      prompts: [],
    }));
    return;
  }

  // Health check
  if (req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
    return;
  }

  // MCP endpoint
  if (req.url === "/mcp" || req.url === "/mcp/") {
    // Create fresh transport per request (stateless mode)
    const mcpServer = createServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // stateless
    });

    await mcpServer.connect(transport);

    // Handle the request
    await transport.handleRequest(req, res);
    return;
  }

  // Root
  if (req.url === "/" || req.url === "") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      name: "correctover",
      version: "1.3.1",
      description: "MCP Runtime Security & Agent Fault Diagnosis",
      mcp_endpoint: "/mcp",
      homepage: "https://correctover.com",
    }));
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

httpServer.listen(PORT, () => {
  console.error(`[correctover] HTTP MCP server listening on port ${PORT}`);
});
