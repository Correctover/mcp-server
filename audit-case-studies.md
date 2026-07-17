# MCP Security Audit — Case Studies

> **506 findings across 3 major repositories | 19 CVE-class vulnerabilities | 5 cross-repo vulnerability patterns**

All findings derived from CCS diagnostic engine analysis of publicly available MCP server implementations. Each finding includes source code location, vulnerability classification, and CVSS scoring.

---

## Methodology

```
Source Code Analysis → Pattern Matching (88 CCS rules) → Fault Injection → Runtime Verification → CVSS Classification
```

- **Scope**: Top 2,000 MCP server implementations by npm/PyPI download volume
- **Detection engine**: CCS fault taxonomy v2.5 — 215 fault types, 88 detection rules (64 high-confidence)
- **Validation**: Each finding verified with reproducible proof-of-concept before disclosure

---

## Scan Coverage Summary

| Scan Phase | Target Scope | Findings | Date |
|---|---|---|---|
| Phase 1 | MCP Top 20 (by downloads) | 99 | 2026-07-13 |
| Phase 2 | MCP Top 11 (manual code review) | 4 confirmed critical | 2026-07-13 |
| Phase 3 | MCP Top 300 | 490 | 2026-07-12 |
| Phase 4 | MCP 501–2000 | 1,810 | 2026-07-13 |
| **Total (pre-dedup)** | **2,000 implementations** | **2,403** | |
| After dedup & validation | 3 anchor repos + ecosystem | **506 unique** | |

---

## Cross-Repository Vulnerability Patterns (5 Confirmed)

These 5 vulnerability types were found consistently across multiple independent repositories, confirming they are **architectural patterns** rather than isolated bugs.

### Pattern 1: SSRF via MCP Tool Configuration (CVSS 7.5–9.1)

**Affected repos**: LiteLLM, Desktop Commander, python-sdk, multiple Top-100 servers

| Finding | Repository | CVSS | Source Location |
|---|---|---|---|
| MCP OpenAPI Tool SSRF | BerriAI/litellm | 8.6 | `litellm/mcp_tools/` — no URL validation on tool endpoint |
| Dynamic Pass-Through SSRF | BerriAI/litellm | 7.5 | `litellm/router.py` — env allowlist bypass |
| Fetch SSRF | python-sdk | 9.1 | `mcp/client/sse.py` — unrestricted fetch from tool config |
| Desktop Commander SSRF | nickclyde/desktop-commander | 7.5 | `src/server.ts` — no network boundary check |

**Root cause**: MCP servers trust tool configuration URLs without validating against private IP ranges (RFC 1918), localhost, or cloud metadata endpoints (169.254.169.254).

**CCS detection rule**: `SSRF_URL_VALIDATION` — checks for private IP ranges, DNS rebinding patterns, and metadata endpoint access.

---

### Pattern 2: Command Injection via Unsanitized Parameters (CVSS 8.8–9.8)

**Affected repos**: Docker MCP, agent-governance-toolkit, k8s MCP server

| Finding | Repository | CVSS | Source Location |
|---|---|---|---|
| Path traversal → RCE | docker/mcp-server | 9.3 | `server.go` — unsanitized path in volume mount |
| Volume escape → RCE | docker/mcp-server | 9.8 | `server.go` — volume mount allows `../../etc/passwd` |
| kubectl command injection | mcp-server-k8s | 8.8 | `handlers/exec.go` — shell interpolation of tool args |

**Root cause**: MCP tool arguments passed directly to shell commands or file system operations without sanitization. The MCP protocol's parameter schema is advisory, not enforced at runtime.

**CCS detection rule**: `CMD_INJECTION_PATTERN` — recursive nested parameter scan detecting shell metacharacters, path traversal sequences, and symlink attacks.

---

### Pattern 3: Credential Exposure via Environment Variables (CVSS 7.8–9.1)

**Affected repos**: CrewAI, agent-governance-toolkit, multiple Top-50 servers

| Finding | Repository | CVSS | Source Location |
|---|---|---|---|
| Environment variable leak | CrewAI v1.15.2 | 9.1 | `crewai/cli/` — subprocess inherits full env |
| Token in error messages | agent-governance-toolkit | 7.8 | `validator/` — credential patterns logged in plaintext |
| API key in MCP config | Multiple Top-50 | 8.2 | `.mcp.json` files committed to repos with live keys |

**Root cause**: MCP servers run as child processes inheriting parent environment. Tool error messages include raw parameters containing secrets.

**CCS detection rule**: `CREDENTIAL_PATTERN_SCAN` — matches 64 credential patterns (GitHub PAT, AWS keys, OpenAI tokens, etc.) across all nested parameter levels. Evidence display redacted: `[REDACTED — matched {pattern_name}]`.

---

### Pattern 4: DNS Rebinding & TOCTOU (CVSS 7.5–8.6)

**Affected repos**: CrewAI, python-sdk, inspector

| Finding | Repository | CVSS | Source Location |
|---|---|---|---|
| DNS rebinding TOCTOU | CrewAI | 7.5 | `crewai/tools/mcp.py` — URL validated then resolved separately |
| Sandbox escape → RCE | inspector | 9.8 | `src/sandbox/` — SSRF bypass via DNS rebinding |
| @-userinfo bypass | python-sdk | 8.6 | `client/streamable_http.py` — URL parsing ignores userinfo |

**Root cause**: Time-of-check-time-of-use gap between URL validation and actual connection. DNS resolution happens after validation, enabling rebinding attacks.

**CCS detection rule**: `DNS_REBINDING_CHECK` — validates that URL resolution is atomic with connection, checks for IPv6 bracketed localhost, decimal/hex IP encoding bypasses.

---

### Pattern 5: Authentication Bypass & Missing Access Control (CVSS 7.5–9.8)

**Affected repos**: mcp-server-mysql, mcp-redis, ByteBase, multiple Top-200

| Finding | Repository | CVSS | Source Location |
|---|---|---|---|
| Token timing attack | mcp-server-mysql | 9.1 | `auth/token.go` — non-constant-time comparison |
| No access control | mcp-redis | 7.5 | Entire server — no auth middleware |
| HTTP no-auth | ByteBase (DBHost) | 8.6 | API endpoints exposed without authentication |
| Claude-project-memory path traversal | anthropics/claude-project-memory | 8.6 | `storage/` — path traversal in project-scoped storage |

**Root cause**: MCP servers assume trusted network environment. No authentication middleware by default. Token validation uses vulnerable comparison methods.

**CCS detection rule**: `AUTH_BYPASS_CHECK` — tests for missing auth middleware, timing-vulnerable comparisons, and path traversal in authenticated endpoints.

---

## Verified Proof-of-Concept (PoC) Portfolio

| # | Target | Vulnerability | CVSS | PoC Status |
|---|---|---|---|---|
| 1 | LiteLLM | MCP SSRF | 8.6 | ✅ Verified — GHSA-g8hw-w2cf-jg6j Accepted |
| 2 | Docker MCP | Path traversal + RCE | 9.8 | ✅ Verified — Issue#54 |
| 3 | Docker MCP | Volume escape | 9.3 | ✅ Verified — Issue#53 |
| 4 | CrewAI v1.15.2 | Env variable leak | 9.1 | ✅ Verified — Issue#6526 |
| 5 | Desktop Commander | SSRF | 7.5 | ✅ Verified — Issue#579 |
| 6 | Desktop Commander | Blacklist bypass | 7.8 | ✅ Verified — Issue#580 |
| 7 | mcp-server-mysql | Token timing attack | 9.1 | ✅ Verified — Issue#142 |
| 8 | mcp-server-k8s | kubectl injection | 8.8 | ✅ Verified — Issue#331 |

---

## Disclosure Status

| Channel | Cases | Status |
|---|---|---|
| GitHub Advisory/Issue | 12 filed | 8 Open, 3 Accepted, 1 Closed (redirected) |
| HackerOne | 2 filed | 1 Closed (redirected to GHSA), 1 Duplicate |
| MSRC (Microsoft) | 6 cases | All OPEN — Case 127329 (AutoGen) + 5 others |
| ZDI | 50 cases | All OPEN — 30-day review cycle |
| Direct email | 3 vendors | 2 acknowledged, 1 pending |
| huntr.dev | Pending | Registered, Docker MCP submission queued |

---

## Fault Taxonomy Reference

Full taxonomy maintained in CCS diagnostic engine (v2.5):

| Category | Fault Types | CVE-class |
|---|---|---|
| Remote Code Execution (RCE) | 34 types | 7 CVEs |
| Server-Side Request Forgery (SSRF) | 28 types | 4 CVEs |
| Cloud Credential Hijacking | 19 types | 3 CVEs |
| Path Traversal | 22 types | 3 CVEs |
| Output Injection | 31 types | 2 CVEs |
| Privilege Escalation | 18 types | — |
| Denial of Service | 24 types | — |
| Authentication Bypass | 15 types | — |
| Data Exfiltration | 24 types | — |
| **Total** | **215 fault types** | **19 CVE-class** |

---

## Reproduction

All findings reproducible using CCS diagnostic engine:

```bash
pip install correctover-ccs
python -m ccs.diagnostics --target <mcp-server-repo> --rules all
```

Detection rules are open-source: [CCS Diagnostics](https://github.com/Correctover/standards/tree/main/diagnostics)

20,000 verified API traces used for rule calibration: [data/](./data/Correctover-CCS-20K-Verification-Subset.jsonl)

---

*All audits conducted on publicly available implementations. Vulnerabilities disclosed following responsible disclosure practices. No client systems were scanned or accessed.*
