#!/usr/bin/env python3
"""Correctover BD Email Sender — Batch 2: AI infrastructure companies.

Usage:
    PYTHONIOENCODING=utf-8 python bd_send_all.py --dry-run
    PYTHONIOENCODING=utf-8 python bd_send_all.py --send
    PYTHONIOENCODING=utf-8 python bd_send_all.py --send --target portkey
"""

import smtplib, ssl, argparse, textwrap, time, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime, timezone

# ── SMTP Config ──────────────────────────────────────────────────────
SMTP_HOST = "smtphz.qiye.163.com"
SMTP_PORT = 465
SMTP_USER = "wangguigui@correctover.com"
SMTP_PASS = "zaeeWQgE@$j7@Knm"
FROM_EMAIL = "wangguigui@correctover.com"
FROM_NAME = "王归归"

# ── All Targets ──────────────────────────────────────────────────────
TARGETS = {
    # ═══ Batch 1 — Already Sent ═══
    "chatsee": {
        "name": "Sekhar Sarukkai",
        "email": "sekhar@chatsee.ai",
        "company": "ChatSee.ai",
        "subject": "Agent fault detection needs a self-healing layer — complementary to ChatSee.ai",
        "status": "sent",
        "body": """Hi Sekhar,

I saw ChatSee.ai's recent round and your focus on agent failure intelligence. Great product — the observability angle is exactly what the market needs as agents move to production.

We're building Correctover at the layer below: verified failover for LLM API calls.

The problem we solve: every AI gateway today switches providers on HTTP 200 without verifying correctness. Silent model substitution, cost spikes, and semantic drift go undetected.

Correctover is an embedded SDK (not a proxy) that runs 6-dimension contract validation before accepting any failover response:
- Structure / Schema / Latency / Cost / Identity / Integrity

I think there's a natural complement — ChatSee detects agent-level failures, Correctover prevents/corrects API-level failures at the runtime layer. Potentially an integration play where Correctover provides the self-healing runtime and ChatSee provides the monitoring dashboard.

Would you be open to a quick call? We're considering an integration partnership.

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "engram": {
        "_sent": True,
        "name": "Dan Biderman",
        "email": "dan@engram.com",
        "company": "Engram",
        "subject": "API reliability for multi-provider agent platforms — Correctover x Engram",
        "status": "ready",
        "body": """Hi Dan,

Engram's vision of a unified agent API is ambitious — I imagine you're dealing with the full spectrum of provider failure modes across OpenAI, Anthropic, Google, and others.

I'm building Correctover, an embedded reliability runtime that gives multi-provider setups something they don't have today: verified failover.

The core insight: when Provider A fails and the system switches to Provider B, current gateways accept the response on HTTP 200 alone. That is not reliability — it's a false sense of security.

Correctover validates every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. Only verified responses pass through.

It's an SDK — one pip install, zero network overhead, your keys stay with you.

From your perspective as an agent API platform, this could be a value-add layer for Engram's own multi-provider routing. Happy to share our benchmark data (P50 diagnosis: 22µs, zero additional API latency).

Open to a brief conversation?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "pramaana": {
        "_sent": True,
        "name": "Ranjan Rajagopalan",
        "email": "ranjan@pramaanalabs.ai",
        "company": "Pramaana Labs",
        "subject": "From formal verification to verified failover — a kindred approach",
        "status": "ready",
        "body": """Hi Ranjan,

Pramaana's work in formal methods caught my attention — I come from a similar mindset.

We're building Correctover, and our core thesis is that LLM API reliability without verification is not reliability. The industry's approach to failover is still transport-level (HTTP 200 = success), which is decades behind the formal verification thinking that Pramaana applies to hardware.

Correctover introduces a 6-dimension contract validation engine (CANON) that verifies every failover response before accepting it — checking structure, schema, latency, cost, identity, and integrity.

It's an embedded SDK (not a proxy/gateway), so there's zero network overhead and zero data interception.

I see a natural alignment: Pramaana verifies hardware correctness, Correctover verifies API runtime correctness. If you're looking at the software reliability layer as a complementary investment thesis, I'd love to share what we're seeing in the market.

Open for a brief chat?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "harvey": {
        "_sent": True,
        "name": "Siva Gurumurthy",
        "email": "siva@harvey.ai",
        "company": "Harvey AI",
        "subject": "Verified failover for legal AI — why Harvey needs more than HTTP 200",
        "status": "ready",
        "body": """Hi Siva,

Harvey's work in legal AI means your users' tolerance for silent errors is zero. A wrong legal citation from a drifted model doesn't just cost money — it has real consequences.

Every major AI gateway today switches providers on HTTP 200 alone. Harvey runs on OpenAI currently, but as you explore multi-provider strategies for redundancy and cost optimization, the question becomes: how do you know the backup provider's output is correct?

Correctover answers that question.

We built an embedded SDK that validates every failover response across 6 dimensions — structure, schema, latency, cost, identity, and integrity — before accepting it. If a response fails validation, we roll back and try the next provider. Never a silent wrong answer.

From Harvey's perspective, this could be the reliability layer that lets you safely diversify provider risk without sacrificing output quality. Open to a 15-min call to explore?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    # ═══ Batch 2 — Ready to Send ═══
    "portkey": {
        "_sent": True,
        "batch": 2,
        "name": "Rohit Agarwal",
        "email": "rohit@portkey.ai",
        "company": "Portkey AI",
        "status": "ready",
        "subject": "Correctover x Portkey: Verified failover as a complement to AI gateway observability",
        "body": """Hi Rohit,

Portkey's observability-first approach to AI gateways is impressive — the control plane view is exactly what teams need as they scale.

I'm building Correctover at a complementary layer: verified failover.

Where Portkey excels at monitoring and managing provider traffic, Correctover adds contract validation before accepting any failover response. It checks structure, schema, latency, cost, identity, and integrity — not just HTTP 200.

The interesting part: Correctover is an embedded SDK (not a proxy), so it can layer on top of Portkey's gateway without data interception or architecture conflicts. Your users get Portkey's observability AND verified failover.

Would you be open to a quick call? I think there's a natural integration play here.

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "openrouter": {
        "_sent": True,
        "batch": 2,
        "name": "Alex Atallah",
        "email": "alex@openrouter.ai",
        "company": "OpenRouter",
        "status": "ready",
        "subject": "Beyond provider routing — verified failover for OpenRouter users",
        "body": """Hi Alex,

OpenRouter's provider routing has made multi-LLM access simple for thousands of developers. As you scale, I imagine response quality consistency across providers is becoming a harder problem.

I'm building Correctover — an embedded SDK for verified failover.

The core problem we solve: when a request fails over to a backup provider, current gateways accept the response on HTTP 200 alone. Correctover validates it across 6 dimensions before accepting (structure, schema, latency, cost, identity, integrity).

From OpenRouter's perspective, this could be a value-add layer — your users already route through OpenRouter; Correctover ensures the routed response is actually correct.

Happy to share benchmarks (P50 diagnosis: 22us, zero additional API latency). Open for a brief chat?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "langchain": {
        "_sent": True,
        "batch": 2,
        "name": "Harrison Chase",
        "email": "harrison@langchain.dev",
        "company": "LangChain",
        "status": "ready",
        "subject": "Verified failover for LangChain applications — a reliability layer for multi-provider chains",
        "body": """Hi Harrison,

LangChain has become the standard framework for LLM application development. As your users move from prototyping to production, provider reliability is becoming a critical concern — especially in multi-provider chains where a single silent failure cascades.

I'm building Correctover — an embedded SDK for verified LLM API failover.

It layers onto existing LangChain applications without architecture changes: Correctover wraps your LLM client and validates every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it.

The result: LangChain apps get verified failover without rewriting routing logic. Particularly valuable for chains that span multiple providers where a silent failure in one link breaks the whole pipeline.

Would you be open to a brief conversation about how this could fit the LangChain ecosystem?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "llamaindex": {
        "_sent": True,
        "batch": 2,
        "name": "Jerry Liu",
        "email": "jerry@llamaindex.ai",
        "company": "LlamaIndex",
        "status": "ready",
        "subject": "Reliable multi-provider RAG — verified failover for LlamaIndex pipelines",
        "body": """Hi Jerry,

LlamaIndex's data framework has made RAG accessible to a huge developer audience. As RAG pipelines grow more complex with multi-provider strategies, the reliability of each LLM call in the pipeline becomes critical.

I'm building Correctover — an embedded SDK for verified LLM API failover.

For LlamaIndex users running production RAG pipelines, Correctover adds contract validation before accepting any failover response: structure, schema, latency, cost, identity, and integrity checks. If a backup provider returns a wrong response, Correctover catches it before it reaches the pipeline.

It's a one-line integration, zero network overhead, and works with any provider.

I'd love to explore how this could benefit LlamaIndex's production users. Open for a quick call?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    # Batch 3 - New Targets
    "brightwave": {
        "_sent": True,
        "batch": 3,
        "name": "Mike Conover",
        "email": "mike@brightwave.io",
        "company": "Brightwave",
        "status": "ready",
        "subject": "Verified failover for financial AI - reliable multi-provider LLM for Brightwave",
        "body": """Hi Mike,

Brightwave's AI-powered investment research is impressive — financial AI is one of the highest-stakes domains for LLM reliability. A wrong model response in investment research doesn't just produce a bad UX; it has regulatory and fiduciary implications.

Correctover is the verified failover layer for LLM APIs. We validate every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it — not just HTTP 200.

Given Brightwave's use of multi-provider LLM strategies for research accuracy, I think there's a natural fit. Happy to share benchmarks and discuss.

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "assemblyai": {
        "_sent": True,
        "batch": 3,
        "name": "Dylan Fox",
        "email": "dylan@assemblyai.com",
        "company": "AssemblyAI",
        "status": "ready",
        "subject": "Multi-provider reliability for AI infrastructure - Correctover x AssemblyAI",
        "body": """Hi Dylan,

AssemblyAI's speech-to-text API is used by thousands of developers. As you expand your model offerings, multi-provider reliability becomes critical — when a backup ASR model returns a different transcription on HTTP 200, the end-user experiences silent degradation.

Correctover is an embedded SDK for verified LLM API failover. We validate every failover response across 6 dimensions before accepting it. One pip install, zero proxy overhead.

Open to a brief conversation about how this could benefit AssemblyAI's reliability architecture?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "traefik": {
        "_sent": True,
        "batch": 3,
        "name": "Sudeep Goswami",
        "email": "sudeep@traefik.io",
        "company": "Traefik Labs",
        "status": "ready",
        "subject": "Beyond reverse proxy - verified failover as a Traefik plugin layer",
        "body": """Hi Sudeep,

Traefik has become the de-facto edge router for modern infrastructure. As AI traffic grows, I imagine Traefik users are looking for more than just request routing — they need response validation.

Correctover is an embedded SDK for verified LLM failover. We validate every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. It layers on top of any proxy/gateway without architecture conflicts.

Could Correctover be a value-add plugin or integration for the Traefik ecosystem? Would love to explore.

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "atlan": {
        "_sent": True,
        "batch": 3,
        "name": "Prukalpa Sankar",
        "email": "prukalpa@atlan.com",
        "company": "Atlan",
        "status": "ready",
        "subject": "Multi-provider LLM needs verified failover - Correctover x Atlan",
        "body": """Hi Prukalpa,

Atlan's data collaboration platform sits at the center of enterprise data stacks. As AI-powered data workflows become standard, the reliability of each LLM call in the data pipeline matters — especially when using multiple LLM providers for different data tasks.

Correctover is an embedded SDK for verified LLM API failover. We validate every response across 6 dimensions before accepting it, catching silent failures that HTTP 200 alone misses.

I think there's an interesting angle for Atlan's AI features. Open for a quick call?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },

    # ═══ Batch 4 — New Targets ═══
    "nexos": {
        "_sent": True,
        "batch": 4,
        "name": "Tomas Okmanas",
        "email": "hello@nexos.ai",
        "company": "Nexos.ai",
        "status": "ready",
        "subject": "AI orchestration + verified failover — a complementary layer",
        "body": """Hi Tomas,

Nexos.ai's AI orchestration platform is tackling the right problem — intelligent routing across LLM providers. As you handle multi-provider traffic at scale, I imagine response quality consistency is a growing concern.

I'm building Correctover, an embedded SDK for verified failover. The core insight: when a request fails over to a backup provider, current gateways accept the response on HTTP 200 alone. Correctover validates it across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting.

It's not a proxy — it's an SDK that layers on top of your orchestration layer. Zero network overhead, your keys stay with you.

From Nexos.ai's perspective, this could be a value-add: your users get intelligent routing + verified responses. Would you be open to a brief conversation?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "requesty": {
        "_sent": True,
        "batch": 4,
        "name": "Thibault Jaigu",
        "email": "thibault@requesty.ai",
        "company": "Requesty",
        "status": "ready",
        "subject": "Gateway + verified failover — a complementary layer for Requesty",
        "body": """Hi Thibault,

Requesty's positioning as "Cloudflare for AI" is compelling — the AI API gateway space is consolidating, and a developer-first approach wins.

I'm building Correctover, an embedded SDK for verified failover. The gap we fill: every AI gateway today routes traffic intelligently but accepts failover responses on HTTP 200 alone.

Correctover adds a contract validation layer that checks structure, schema, latency, cost, identity, and integrity before accepting any failover response. It's an SDK (not a proxy), so it layers on top of Requesty's gateway without data interception or architecture conflicts.

I see a clear complement: Requesty handles the routing and observability, Correctover ensures the routed response is actually correct. Happy to share benchmarks (P50 diagnosis: 22µs, zero network overhead).

Open for a quick call?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "gradient": {
        "_sent": True,
        "batch": 4,
        "name": "Dimitri Masin",
        "email": "dimitri@gradient-labs.ai",
        "company": "Gradient Labs",
        "status": "ready",
        "subject": "Verified failover for regulated AI — Correctover x Gradient Labs",
        "body": """Hi Dimitri,

Gradient Labs' work automating customer support for regulated industries is exactly where LLM reliability matters most. A wrong response in financial services or healthcare isn't a nuisance — it's a compliance issue.

I'm building Correctover, an embedded SDK for verified failover. The problem: every AI gateway today switches providers on HTTP 200 without verifying the response is correct.

Correctover validates every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. For regulated AI workloads, this means zero tolerance for silent errors — if a backup provider returns a wrong output, Correctover catches it before it reaches the customer.

Given Gradient Labs' focus on regulated industries, I think there's a strong alignment. Would you be open to a brief conversation?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "writer": {
        "_sent": True,
        "batch": 4,
        "name": "May Habib",
        "email": "may@writer.com",
        "company": "Writer.com",
        "status": "ready",
        "subject": "Enterprise AI needs verified failover — Correctover x Writer",
        "body": """Hi May,

Writer's enterprise GenAI platform serves 250+ enterprise customers — Palantir, Salesforce, and others trust Writer for production AI. As you expand multi-provider capabilities for redundancy and cost optimization, response correctness across providers becomes critical.

I'm building Correctover, an embedded SDK for verified failover. We validate every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. It's not a proxy — it's an SDK that layers on top of any gateway, zero network overhead.

For Writer's enterprise customers, this means their AI-generated content isn't just fast and cost-effective — it's verified correct at the API layer.

Would you be open to a brief conversation about how this could integrate with Writer's platform?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "dust": {
        "_sent": True,
        "batch": 4,
        "name": "Gabriel Hubert",
        "email": "gabriel@dust.tt",
        "company": "Dust",
        "status": "ready",
        "subject": "Model-agnostic agents need verified failover — Correctover x Dust",
        "body": """Hi Gabriel,

Dust's model-agnostic approach to enterprise knowledge agents is the right architecture — the ability to use any provider without lock-in is table stakes for production AI. But model agnosticism creates a reliability challenge: when you switch providers mid-session, how do you know the response is correct?

I'm building Correctover, an embedded SDK for verified failover. We validate every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it.

The integration path is clean: one pip install wraps your LLM client, zero proxy overhead, your API keys stay with you. For Dust's agent platform, this means agents can safely use any provider without risking silent wrong answers.

Would you be open to a quick call? I think there's a strong product fit.

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "e2b": {
        "_sent": True,
        "batch": 4,
        "name": "Vasek Mlejnsky",
        "email": "vasek@e2b.dev",
        "company": "E2B",
        "status": "ready",
        "subject": "Secure agent sandboxes + verified API failover — Correctover x E2B",
        "body": """Hi Vasek,

E2B's secure sandboxes for AI agents solve a critical infrastructure problem — agent code execution needs isolation. I see a complementary problem: agent API calls need response verification.

I'm building Correctover, an embedded SDK for verified LLM failover. When a sandboxed agent calls an LLM and the request fails over to a backup provider, current infrastructure accepts the response on HTTP 200 alone. Correctover validates it across 6 dimensions before accepting.

From E2B's perspective, this could be a natural addition to your agent infrastructure stack: secure execution + verified API responses. The SDK is one pip install, zero proxy, works with any provider.

Open to a brief conversation?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "arcade": {
        "_sent": True,
        "batch": 4,
        "name": "Alex Salazar",
        "email": "alex@arcade.dev",
        "company": "Arcade",
        "status": "ready",
        "subject": "MCP auth + verified failover — a trust layer for AI agents",
        "body": """Hi Alex,

Arcade's MCP authentication and authorization work is timely — as AI agents interact with more external systems, the auth layer becomes critical. I'm building the verification layer at the API call level.

Correctover is an embedded SDK for verified LLM failover. We validate every failover response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. Not just HTTP 200 — we verify the response is actually correct.

Your auth layer controls which services agents can access. Our verification layer ensures the responses agents receive are correct. There's a natural trust-story alignment.

Would you be open to a quick call?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "complyadvantage": {
        "_sent": True,
        "batch": 4,
        "name": "Vatsa Narasimha",
        "email": "vatsa@complyadvantage.com",
        "company": "ComplyAdvantage",
        "status": "ready",
        "subject": "Zero tolerance for silent errors — verified failover for regulated AI",
        "body": """Hi Vatsa,

ComplyAdvantage's AML and financial crime compliance platform processes millions of risk decisions. As AI-powered compliance workflows adopt multi-provider LLM strategies, the cost of a silent wrong answer is measured in regulatory fines, not just bad UX.

I'm building Correctover, an embedded SDK for verified failover. We validate every LLM API response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it. If a backup provider returns a wrong output, we catch it before it reaches your compliance pipeline.

For ComplyAdvantage, this means your multi-provider AI strategy can prioritize redundancy without compromising on correctness — critical for regulated financial infrastructure.

Would you be open to a brief conversation?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "artisan": {
        "_sent": True,
        "batch": 4,
        "name": "Jaspar Carmichael-Jack",
        "email": "jaspar@artisan.co",
        "company": "Artisan",
        "status": "ready",
        "subject": "AI sales agents need verified API reliability",
        "body": """Hi Jaspar,

Artisan's AI BDRs (sales agents) represent a new category of production AI — autonomous agents that interact with customers on behalf of businesses. When an AI sales agent uses LLM APIs and the request fails over to a backup provider, a silent wrong response means a wrong message to a prospect.

I'm building Correctover, an embedded SDK for verified failover. We validate every LLM API response across 6 dimensions (structure, schema, latency, cost, identity, integrity) before accepting it.

For Artisan's AI agents, this ensures every API response that reaches a prospect interaction is verified correct — not just HTTP 200. One pip install, zero proxy, works with any provider.

Would you be open to a quick call to explore?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
    "modal": {
        "_sent": True,
        "batch": 4,
        "name": "Erik Bernhardsson",
        "email": "erik@modal.com",
        "company": "Modal",
        "status": "ready",
        "subject": "AI-native cloud needs verified failover — Correctover x Modal",
        "body": """Hi Erik,

Modal's AI-native cloud platform has redefined how developers think about serverless GPU compute. As Modal users run multi-provider LLM workloads on your platform, response reliability across providers becomes a platform concern.

I'm building Correctover, an embedded SDK for verified failover. We validate every LLM API response across 6 dimensions before accepting it — not just HTTP 200. It's a lightweight SDK (one pip install, ~375KB, zero external dependencies except httpx) that layers on top of any provider or gateway.

For Modal, this could be a native reliability layer for users running multi-provider AI workloads. Happy to share benchmarks and discuss integration ideas.

Open for a brief chat?

Best,
Wang Guigui
wangguigui@correctover.com
https://correctover.com""",
    },
}


def send_email(key: str, dry_run: bool = False) -> bool:
    target = TARGETS[key]
    if target.get("status") == "sent" or target.get("_sent"):
        print(f"  ⏭️  Already sent to {target['name']}, skipping")
        return True

    to_email = target["email"]
    subject = target["subject"]
    body = target.get("body", "")
    if not body:
        print(f"  ⏭️  {key} has no body (batch 1), skipping")
        return True

    msg = MIMEMultipart("alternative")
    now = datetime.now(timezone.utc)
    msg_id = f"<{now.strftime('%Y%m%d%H%M%S')}.{key}.correctover@correctover.com>"
    msg["From"] = formataddr((FROM_NAME, FROM_EMAIL))
    msg["To"] = formataddr((target['name'], to_email))
    msg["Subject"] = subject
    msg["Reply-To"] = FROM_EMAIL
    msg["Message-ID"] = msg_id

    body_text = textwrap.dedent(body).strip()
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    body_html = body_text.replace("\n", "<br>\n")
    html = f"""<html><body><pre style="font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; color: #333;">{body_html}</pre></body></html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    if dry_run:
        print(f"\n{'='*60}")
        print(f"TO: {target['name']} <{to_email}>")
        print(f"SUBJECT: {subject}")
        print(f"{'='*60}")
        print(body_text[:200] + "..." if len(body_text) > 200 else body_text)
        return True

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        print(f"  ✅ Sent to {target['name']} <{to_email}>")
        return True
    except Exception as e:
        print(f"  ❌ Failed ({to_email}): {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--target", default="all", help="Target key or 'all'")
    parser.add_argument("--batch", choices=["1", "2", "3", "4", "all"], default="all")
    args = parser.parse_args()

    if args.send:
        args.dry_run = False

    targets_to_send = list(TARGETS.keys()) if args.target == "all" else [args.target]

    # Filter by batch
    batch_keys = {"1": [], "2": [], "3": [], "4": []}
    for k, v in TARGETS.items():
        if v.get("_sent"):
            batch_keys["1"].append(k)
        elif v.get("batch") == 2:
            batch_keys["2"].append(k)
        elif v.get("batch") == 3:
            batch_keys["3"].append(k)
        elif v.get("batch") == 4:
            batch_keys["4"].append(k)

    if args.batch in batch_keys:
        targets_to_send = [k for k in targets_to_send if k in batch_keys[args.batch]]
    elif args.batch == "all":
        pass  # send all non-skipped

    print(f"Correctover BD Email Sender")
    print(f"  Mode: {'LIVE' if args.send else 'DRY-RUN'}")
    print(f"  Batch: {args.batch} ({len(targets_to_send)} targets)")
    print(f"  SMTP: {SMTP_HOST}:{SMTP_PORT}")
    print()

    if args.send and targets_to_send:
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASS)
            print("  SMTP connected & authenticated")
        except Exception as e:
            print(f"  SMTP connect failed: {e}")
            return

    ok, fail = 0, 0
    for key in targets_to_send:
        t = TARGETS[key]
        label = f"[{t.get('status','ready')}] {t['name']} -> {t['email']}"
        print(f"  {label}")
        if send_email(key, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1
        if args.send:
            time.sleep(2)

    print(f"\nResult: {ok} ok, {fail} failed")
    if args.dry_run:
        print("Pass --send to actually send")


if __name__ == "__main__":
    main()
