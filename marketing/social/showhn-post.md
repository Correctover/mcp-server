# Show HN: Correctover – The first MCP server that verifies AI outputs in real-time

## Show HN: Correctover – The MCP Reliability Layer for AI (6-dim validation + auto self-healing)

Hi HN,

I built Correctover, an MCP server that sits between AI tools (Cursor, Claude Desktop, Windsurf) and LLM providers, and verifies every response before it reaches the user.

### The problem

Every MCP server today does: request → route → deliver. Nobody checks if the response is actually correct.

The worst LLM failures aren't HTTP errors — they're silent:
- Truncated JSON (finish_reason: "length" that nobody checks)
- Responses that look valid but contain hallucinated data
- Provider silently degrades output quality over time
- Token usage spikes without warning

Your MCP server just passes these through to your editor.

### The solution

Correctover adds a verification step: request → route → execute → **verify** → (fail?) self-heal → deliver.

Every response passes through 6-dimension contract validation:
- **Structure**: valid choices, non-empty content
- **Schema**: correct finish_reason, complete format
- **Latency**: response time within bounds
- **Cost**: token usage is reasonable
- **Identity**: response role is correct
- **Integrity**: no truncation, no broken JSON

If validation fails, it auto-retries with the same provider or fails over to another — then validates again.

### Key insight

**Failover ≠ Correctover.** Failover switches providers. Correctover switches AND verifies the output is correct. Every other tool stops at "did I get a response?" We ask "is the response actually good?"

### Technical details

- Written in Go, ~1500 lines, compiles to 7.9MB single binary
- 4 MCP tools: chat, verify, providers, health
- 9 providers: OpenAI, Anthropic, DeepSeek, Moonshot, Zhipu AI, Qwen, SiliconFlow, Groq, Together AI
- BYOK — API keys never leave your machine, direct connections to providers
- MCP protocol: JSON-RPC 2.0 over stdio
- License: Apache-2.0

### One-line install

```json
{
  "mcpServers": {
    "correctover": {
      "command": "npx",
      "args": ["-y", "correctover-mcp-server"]
    }
  }
}
```

### Links
- GitHub: https://github.com/Correctover/mcp-server
- Website: https://correctover.com

### Looking for
- Early testers and feedback
- Use cases where output validation matters most
- Ideas for custom validation rules

Ask me anything.

---

*Because failover switches. Correctover verifies.*
