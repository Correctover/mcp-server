#!/usr/bin/env python3
"""Correctover BD Batch 6 — Desktop AI Tools & Developer Platforms
   Targets: Windsurf/Codeium, Continue.dev, Phind, Aider, Cline
   Angle: LocalGateway as entry point → Correctover as commercial layer
"""

import smtplib, ssl, argparse, textwrap, re, time, sys
sys.stdout.reconfigure(encoding='utf-8')
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── SMTP Config ──
SMTP_HOST = "smtphz.qiye.163.com"
SMTP_PORT = 465
SMTP_USER = "wangguigui@correctover.com"
SMTP_PASS = "zaeeWQgE@$j7@Knm"
FROM_EMAIL = "wangguigui@correctover.com"
FROM_NAME = "王归归"

TARGETS = {
    "windsurf": {
        "name": "Varun",
        "full_name": "Varun Mohan",
        "email": "varun.mohan@codeium.com",
        "company": "Windsurf (Codeium)",
        "subject": "Multi-provider reliability for 1M+ Windsurf users — Correctover x Windsurf",
        "body": """Hi Varun,

Windsurf's growth — 1M+ developers in four months — is remarkable. As you scale, one challenge becomes harder: LLM API availability. Every outage at a single provider affects millions of users.

We've seen this pattern with desktop AI tools. Users configure one provider, that provider goes down, and their productivity stops. Some tools are adding multi-provider failover, but switching on HTTP 200 alone is risky — models differ across providers, and silent errors propagate.

We build Correctover — an embedded SDK that validates every failover response across 6 dimensions (schema, semantics, latency, cost, identity, integrity) before accepting it. P50=22µs. It's a pip install, not a proxy.

We also released LocalGateway (github.com/Correctover/local-gateway) — an open-source desktop LLM proxy with sequential failover and model name mapping. It's already getting traction as a companion tool for Windsurf/Cursor users who want provider redundancy.

There's a natural integration: LocalGateway as the routing layer Windsurf can recommend to self-hosted users, Correctover as the verification layer for enterprise deployments.

Would you be open to a 15-minute call? I'd love to share what we're seeing in the reliability space and explore how this fits Windsurf's architecture.

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "continue": {
        "name": "Ty",
        "full_name": "Ty Dunn",
        "email": "ty@continue.dev",
        "company": "Continue.dev",
        "subject": "Open source AI coding + multi-provider reliability — Correctover x Continue",
        "body": """Hi Ty,

Continue has done something important — made AI code assistance truly open and configurable. Your users bring their own API keys and choose their own models. That freedom comes with a reliability problem: every provider goes down, and when it does, users hit an error wall.

We built LocalGateway (github.com/Correctover/local-gateway) — an open-source desktop LLM proxy that gives Continue users automatic multi-provider failover with model name mapping. One command: local-gateway --providers deepseek,kimi,openai

The broader vision is Correctover — the same failover engine with 6-dimension contract validation (schema, semantics, latency, cost, identity, integrity). It's an embedded SDK (pip install, zero deps, P50=22µs).

For Continue's user base of developer-tinkerers, LocalGateway is the natural companion. For Continue's enterprise customers, Correctover adds a verification layer that makes multi-provider setups production-safe.

I'd love to explore adding LocalGateway to Continue's docs or recommendations. Would a 15-minute call work?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "aider": {
        "name": "Paul",
        "full_name": "Paul Gauthier",
        "email": "paul@aider.chat",
        "company": "Aider",
        "subject": "Terminal AI pair programming + multi-provider failover — Correctover x Aider",
        "body": """Hi Paul,

Aider is unique in the AI coding space — deeply integrated into the terminal workflow, using Git as a safety net, and supporting multiple LLM providers. That last feature is where I think we can help.

Aider users who switch between models or providers hit the same problem: model names aren't portable, and different providers produce different quality outputs. When a provider fails mid-session, the coding flow breaks entirely.

We built Correctover — an SDK that validates every failover response before accepting it (6-dimension check at P50=22µs). And its open-source sibling LocalGateway (github.com/Correctover/local-gateway) is a zero-dependency desktop proxy that gives Aider users seamless multi-provider failover with model name mapping built in.

I see a natural fit: Aider handles the agentic coding loop, LocalGateway/Correctover handles the reliability layer underneath. No proxy config needed — just pip install and point Aider at localhost.

Would you be open to a quick call to explore?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "cline": {
        "name": "Saoud",
        "full_name": "Saoud Rizwan",
        "email": "hello@cline.bot",
        "company": "Cline",
        "subject": "Multi-provider reliability for Cline's agentic workflows",
        "body": """Hi Saoud,

Cline's agentic approach to VS Code AI — autonomous planning, tool use, and file operations — depends entirely on LLM API calls being reliable. One provider outage can break an entire multi-step workflow.

This is the problem we solve. Correctover is an SDK that gives you verified multi-provider failover with 6-dimension contract validation. When a provider fails and traffic shifts to a backup, we check schema, semantics, latency, cost, identity, and content integrity before accepting the response. P50=22µs, zero perceptible latency.

We also built LocalGateway (github.com/Correctover/local-gateway) — an open-source desktop LLM proxy for users who want provider redundancy without SDK integration. It already handles model name mapping across 9 providers.

For Cline, an integration could mean:
- Cline users get automatic failover when their primary provider is down
- Enterprise Cline deployments get verified responses, not just HTTP 200
- The LocalGateway config pattern is trivial (one command)

Would you be open to a 15-minute conversation about how Correctover fits into Cline's architecture?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "jan": {
        "name": "Josh",
        "full_name": "Joshua Bleecher Snyder",
        "email": "hello@jan.ai",
        "company": "Jan.ai",
        "subject": "Desktop AI + multi-provider reliability — Correctover x Jan",
        "body": """Hi Josh,

Jan's vision of an open, offline-first AI desktop app is compelling. Your users value control — they bring their own models, their own API keys, their own infra. With that control comes a reliability burden.

We built LocalGateway (github.com/Correctover/local-gateway) — an open-source desktop LLM proxy that drops into Jan's workflow effortlessly. It gives Jan users automatic multi-provider failover with model name mapping across 9 providers. When DeepSeek goes down, Jan keeps working via KIMI or OpenAI — transparently.

The commercial layer is Correctover — the same failover engine with 6-dimension contract validation (schema, semantics, latency, cost, identity, integrity). For Jan's enterprise users who need guaranteed correctness, not just failover.

Jan provides the UI and local inference. LocalGateway provides the API reliability layer. Correctover provides the verification layer. It's a natural stack.

Would you be open to exploring this? A short call would be great.

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
}


def send_email(target_key: str, dry_run: bool = False) -> bool:
    target = TARGETS[target_key]
    to_email = target["email"]
    to_name = target["full_name"]
    subject = target["subject"]
    body = target["body"]

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = f"{to_name} <{to_email}>"
    msg["Subject"] = subject
    msg["Reply-To"] = FROM_EMAIL
    msg["Message-ID"] = (
        f"<{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{hash(target_key)}"
        f".batch6.correctover@correctover.com>"
    )

    body_text = textwrap.dedent(body).strip()
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    body_html = body_text.replace("\n", "<br>\n")
    html = f"""<html><body>
<pre style="font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; color: #333;">
{body_html}
</pre>
</body></html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    if dry_run:
        print(f"\n{'='*60}")
        print(f"TO: {to_name} <{to_email}>")
        print(f"SUBJECT: {subject}")
        print(f"{'='*60}")
        print(body_text)
        print(f"\n[[ DRY-RUN — NOT SENT ]]\n")
        return True

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        print(f"  SENT to {to_email}")
        return True
    except smtplib.SMTPRecipientsRefused as e:
        print(f"  REFUSED ({to_email}): {e}")
        return False
    except smtplib.SMTPResponseException as e:
        print(f"  SMTP ERROR ({to_email}): code={e.smtp_code}, {e.smtp_error}")
        return False
    except Exception as e:
        print(f"  FAILED ({to_email}): {type(e).__name__}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Correctover BD Batch 6")
    parser.add_argument("--send", action="store_true", help="Actually send")
    parser.add_argument("--to", choices=list(TARGETS.keys()) + ["all"], default="all",
                        help="Target key (default: all)")
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.to == "all" else [args.to]

    print(f"Correctover BD Batch 6 — Desktop AI Tools & Developer Platforms")
    print(f"Mode: {'LIVE' if args.send else 'DRY-RUN'}")
    print(f"Targets: {', '.join(targets)}")
    print()

    if args.send:
        print("Connecting to SMTP...")
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASS)
                print("  SMTP connected")
        except Exception as e:
            print(f"  SMTP CONNECT FAILED: {e}")
            return

    ok = 0
    fail = 0
    for key in targets:
        target = TARGETS[key]
        print(f"\nPreparing: {target['full_name']} -> {target['email']}")
        if send_email(key, dry_run=not args.send):
            ok += 1
        else:
            fail += 1
        if args.send:
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Results: {ok} OK, {fail} failed")
    if not args.send:
        print("Pass --send to actually send")


if __name__ == "__main__":
    main()
