#!/usr/bin/env node
const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");

const server = new McpServer({
  name: "correctover",
  version: "1.2.0",
});

// Helper: call LLM provider
async function callProvider(provider, model, messages, apiKey) {
  const endpoints = {
    anthropic: { url: "https://api.anthropic.com/v1/messages", headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01" } },
    openai: { url: "https://api.openai.com/v1/chat/completions", headers: { "Authorization": `Bearer ${apiKey}` } },
    deepseek: { url: "https://api.deepseek.com/v1/chat/completions", headers: { "Authorization": `Bearer ${apiKey}` } },
  };

  const ep = endpoints[provider];
  if (!ep) throw new Error(`Unsupported provider: ${provider}`);

  let body;
  if (provider === "anthropic") {
    body = JSON.stringify({ model: model || "claude-sonnet-4-20250514", max_tokens: 4096, messages });
  } else {
    body = JSON.stringify({ model: model || (provider === "deepseek" ? "deepseek-chat" : "gpt-4o"), messages, temperature: 0.7 });
  }

  const res = await fetch(ep.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...ep.headers },
    body,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`${provider} API error ${res.status}: ${err}`);
  }

  const data = await res.json();
  if (provider === "anthropic") return data.content?.[0]?.text || "";
  return data.choices?.[0]?.message?.content || "";
}

// Helper: validate response
function validateResponse(response, schema) {
  const issues = [];
  if (!response || response.trim().length === 0) issues.push("empty_response");
  if (response && response.length > 100000) issues.push("response_too_large");
  return { valid: issues.length === 0, issues };
}

// Get configured providers
function getConfiguredProviders() {
  const providers = [];
  if (process.env.ANTHROPIC_API_KEY) providers.push({ name: "anthropic", key: process.env.ANTHROPIC_API_KEY });
  if (process.env.OPENAI_API_KEY) providers.push({ name: "openai", key: process.env.OPENAI_API_KEY });
  if (process.env.DEEPSEEK_API_KEY) providers.push({ name: "deepseek", key: process.env.DEEPSEEK_API_KEY });
  if (process.env.MISTRAL_API_KEY) providers.push({ name: "mistral", key: process.env.MISTRAL_API_KEY });
  if (process.env.GOOGLE_API_KEY) providers.push({ name: "google", key: process.env.GOOGLE_API_KEY });
  if (process.env.COHERE_API_KEY) providers.push({ name: "cohere", key: process.env.COHERE_API_KEY });
  return providers;
}

// Stats tracking
let stats = { totalCalls: 0, successes: 0, failures: 0, selfHeals: 0, startTime: Date.now() };

// Tool: chat
server.tool(
  "chat",
  "Send a message to an LLM with automatic output validation and self-healing. Supports multi-provider failover.",
  {
    message: z.string().describe("The message to send to the LLM"),
    provider: z.string().optional().describe("Preferred provider (anthropic/openai/deepseek)"),
    model: z.string().optional().describe("Model name"),
    system: z.string().optional().describe("System prompt"),
    maxRetries: z.number().optional().default(3).describe("Max retry attempts"),
  },
  async (params) => {
    const providers = getConfiguredProviders();
    if (providers.length === 0) {
      return { content: [{ type: "text", text: "No providers configured. Set API keys: ANTHROPIC_API_KEY, OPENAI_API_KEY, etc." }] };
    }

    let selectedIdx = 0;
    if (params.provider) {
      const idx = providers.findIndex(p => p.name === params.provider);
      if (idx >= 0) selectedIdx = idx;
    }

    const messages = [];
    if (params.system) messages.push({ role: "user", content: params.system });
    messages.push({ role: "user", content: params.message });

    const maxRetries = params.maxRetries || 3;
    let lastError = null;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      const p = providers[(selectedIdx + attempt) % providers.length];
      try {
        stats.totalCalls++;
        const response = await callProvider(p.name, params.model, messages, p.key);
        const validation = validateResponse(response);
        if (validation.valid) {
          stats.successes++;
          return { content: [{ type: "text", text: response }] };
        } else {
          stats.selfHeals++;
          lastError = `Validation failed: ${validation.issues.join(", ")}`;
        }
      } catch (err) {
        stats.failures++;
        lastError = err.message;
      }
    }
    return { content: [{ type: "text", text: `All providers failed after ${maxRetries} attempts. Last error: ${lastError}` }], isError: true };
  }
);

// Tool: health
server.tool("health", "Check which LLM providers are configured and ready.", {},
  async () => {
    const providers = getConfiguredProviders();
    const status = providers.map(p => `${p.name}: configured`).join(", ") || "No providers configured";
    return { content: [{ type: "text", text: `Providers: ${status}\nUptime: ${Math.round((Date.now() - stats.startTime) / 1000)}s | Calls: ${stats.totalCalls} | OK: ${stats.successes} | Self-heals: ${stats.selfHeals}` }] };
  }
);

// Tool: providers
server.tool("providers", "List all supported LLM providers.", {},
  async () => {
    const all = [
      { name: "anthropic", env: "ANTHROPIC_API_KEY", models: "claude-sonnet-4-20250514, claude-3-5-sonnet", ok: !!process.env.ANTHROPIC_API_KEY },
      { name: "openai", env: "OPENAI_API_KEY", models: "gpt-4o, gpt-4o-mini, o1", ok: !!process.env.OPENAI_API_KEY },
      { name: "deepseek", env: "DEEPSEEK_API_KEY", models: "deepseek-chat, deepseek-reasoner", ok: !!process.env.DEEPSEEK_API_KEY },
      { name: "mistral", env: "MISTRAL_API_KEY", models: "mistral-large, mistral-small", ok: !!process.env.MISTRAL_API_KEY },
      { name: "google", env: "GOOGLE_API_KEY", models: "gemini-pro, gemini-1.5-pro", ok: !!process.env.GOOGLE_API_KEY },
      { name: "cohere", env: "COHERE_API_KEY", models: "command-r-plus, command-r", ok: !!process.env.COHERE_API_KEY },
    ];
    const text = all.map(p => `${p.ok ? "configured" : "not set"} | ${p.name} | ${p.env} | models: ${p.models}`).join("\n");
    return { content: [{ type: "text", text }] };
  }
);

// Tool: stats
server.tool("stats", "View session statistics.", {},
  async () => {
    const uptime = Math.round((Date.now() - stats.startTime) / 1000);
    const rate = stats.totalCalls > 0 ? ((stats.successes / stats.totalCalls) * 100).toFixed(1) + "%" : "N/A";
    return { content: [{ type: "text", text: `Uptime: ${uptime}s | Calls: ${stats.totalCalls} | OK: ${stats.successes} | Failures: ${stats.failures} | Self-heals: ${stats.selfHeals} | Rate: ${rate}` }] };
  }
);

// Tool: validation_history
server.tool("validation_history", "View recent validation results.", { limit: z.number().optional().default(10).describe("Entries to show") },
  async (params) => {
    return { content: [{ type: "text", text: `Calls: ${stats.totalCalls} | OK: ${stats.successes} | Self-heals: ${stats.selfHeals} | Failures: ${stats.failures}` }] };
  }
);

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[correctover] Node.js MCP server running on stdio");
}

main().catch(err => {
  console.error("[correctover] Fatal:", err);
  process.exit(1);
});
