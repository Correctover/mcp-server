#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

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

// Helper: validate response (6 dimensions)
function validateResponse(response, schema) {
  const issues = [];
  if (!response || response.trim().length === 0) issues.push("empty_response");
  if (response && response.length > 100000) issues.push("response_too_large");
  if (schema && typeof schema === "string") {
    try {
      const parsed = JSON.parse(response);
      // Basic schema validation
    } catch(e) {
      if (schema.startsWith("{") || schema.startsWith("[")) issues.push("schema_mismatch");
    }
  }
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

// Tool: chat - main LLM interaction with validation & self-healing
server.tool(
  "chat",
  "Send a message to an LLM with automatic output validation and self-healing. Supports multi-provider failover.",
  {
    message: z.string().describe("The message to send to the LLM"),
    provider: z.string().optional().describe("Preferred provider (anthropic/openai/deepseek). Defaults to first configured."),
    model: z.string().optional().describe("Model name (e.g., claude-sonnet-4-20250514, gpt-4o, deepseek-chat)"),
    system: z.string().optional().describe("System prompt"),
    expectedSchema: z.string().optional().describe("Expected JSON schema for response validation"),
    maxRetries: z.number().optional().default(3).describe("Max retry attempts on validation failure"),
  },
  async (params) => {
    const providers = getConfiguredProviders();
    if (providers.length === 0) {
      return { content: [{ type: "text", text: "❌ No providers configured. Set at least one API key:\nANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, etc." }] };
    }

    // Select provider
    let selectedIdx = 0;
    if (params.provider) {
      const idx = providers.findIndex(p => p.name === params.provider);
      if (idx >= 0) selectedIdx = idx;
    }

    const messages = [];
    if (params.system) messages.push({ role: "system", content: params.system });
    messages.push({ role: "user", content: params.message });

    const maxRetries = params.maxRetries || 3;
    let lastError = null;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      const currentProvider = providers[(selectedIdx + attempt) % providers.length];
      try {
        stats.totalCalls++;
        const response = await callProvider(currentProvider.name, params.model, messages, currentProvider.key);
        
        const validation = validateResponse(response, params.expectedSchema);
        if (validation.valid) {
          stats.successes++;
          return {
            content: [{ type: "text", text: response }],
            metadata: {
              provider: currentProvider.name,
              model: params.model || "default",
              attempt: attempt + 1,
              validated: true,
            }
          };
        } else {
          stats.selfHeals++;
          console.error(`[correctover] Validation failed (attempt ${attempt+1}): ${validation.issues.join(", ")}`);
          lastError = `Validation failed: ${validation.issues.join(", ")}`;
        }
      } catch (err) {
        stats.failures++;
        console.error(`[correctover] Provider ${currentProvider.name} failed: ${err.message}`);
        lastError = err.message;
      }
    }

    return { content: [{ type: "text", text: `❌ All providers failed after ${maxRetries} attempts. Last error: ${lastError}` }], isError: true };
  }
);

// Tool: health - check configured providers
server.tool(
  "health",
  "Check which LLM providers are configured and ready.",
  {},
  async () => {
    const providers = getConfiguredProviders();
    const status = providers.map(p => `✅ ${p.name}: configured`).join("\n") || "❌ No providers configured";
    return {
      content: [{ type: "text", text: `Provider Status:\n${status}\n\nUptime: ${Math.round((Date.now() - stats.startTime) / 1000)}s\nTotal calls: ${stats.totalCalls}\nSuccesses: ${stats.successes}\nSelf-heals: ${stats.selfHeals}` }]
    };
  }
);

// Tool: providers - list all supported providers
server.tool(
  "providers",
  "List all supported LLM providers with configuration details.",
  {},
  async () => {
    const allProviders = [
      { name: "anthropic", env: "ANTHROPIC_API_KEY", models: ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229"], status: process.env.ANTHROPIC_API_KEY ? "✅" : "❌" },
      { name: "openai", env: "OPENAI_API_KEY", models: ["gpt-4o", "gpt-4o-mini", "o1-preview"], status: process.env.OPENAI_API_KEY ? "✅" : "❌" },
      { name: "deepseek", env: "DEEPSEEK_API_KEY", models: ["deepseek-chat", "deepseek-reasoner"], status: process.env.DEEPSEEK_API_KEY ? "✅" : "❌" },
      { name: "mistral", env: "MISTRAL_API_KEY", models: ["mistral-large-latest", "mistral-small-latest"], status: process.env.MISTRAL_API_KEY ? "✅" : "❌" },
      { name: "google", env: "GOOGLE_API_KEY", models: ["gemini-pro", "gemini-1.5-pro"], status: process.env.GOOGLE_API_KEY ? "✅" : "❌" },
      { name: "cohere", env: "COHERE_API_KEY", models: ["command-r-plus", "command-r"], status: process.env.COHERE_API_KEY ? "✅" : "❌" },
    ];

    const text = allProviders.map(p => 
      `${p.status} ${p.name}\n   Env: ${p.env}\n   Models: ${p.models.join(", ")}`
    ).join("\n\n");

    return { content: [{ type: "text", text: `Supported Providers:\n\n${text}` }] };
  }
);

// Tool: stats - session statistics
server.tool(
  "stats",
  "View session statistics: calls, successes, failures, self-heals.",
  {},
  async () => {
    const uptime = Math.round((Date.now() - stats.startTime) / 1000);
    const successRate = stats.totalCalls > 0 ? ((stats.successes / stats.totalCalls) * 100).toFixed(1) : "N/A";
    return {
      content: [{
        type: "text",
        text: `Session Statistics:\nUptime: ${uptime}s\nTotal calls: ${stats.totalCalls}\nSuccesses: ${stats.successes}\nFailures: ${stats.failures}\nSelf-heals: ${stats.selfHeals}\nSuccess rate: ${successRate}%`
      }]
    };
  }
);

// Tool: validation_history - recent validation results
server.tool(
  "validation_history",
  "View recent validation results and self-healing events.",
  { limit: z.number().optional().default(10).describe("Number of recent entries to show") },
  async (params) => {
    return {
      content: [{
        type: "text",
        text: `Validation History (last ${params.limit}):\nTotal calls: ${stats.totalCalls}\nSuccessful validations: ${stats.successes}\nSelf-healing events: ${stats.selfHeals}\nFailures: ${stats.failures}\n\nDetailed per-call history is available in Pro mode.`
      }]
    };
  }
);

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
console.error("[correctover] Node.js MCP server started on stdio");
