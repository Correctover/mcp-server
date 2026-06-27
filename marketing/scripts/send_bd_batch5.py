#!/usr/bin/env python3
"""Correctover BD Batch 5 — AI Agent & Reliability Platforms
   Targets: CrewAI, Braintrust, Probably, Concentrate AI, Cognition(Devin)
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
    "crewai": {
        "name": "João",
        "full_name": "João Moura",
        "email": "joao@crewai.com",
        "company": "CrewAI",
        "subject": "Multi-agent reliability needs verified failover — Correctover x CrewAI",
        "body": """Hi João,

CrewAI is becoming the standard for multi-agent orchestration. As agents increasingly depend on LLM API calls in production, one question keeps coming up: what happens when the API provider fails?

Current failover switches on HTTP 200 alone — silent model substitution, semantic drift, and cost spikes go undetected. For an agent orchestrator like CrewAI, a wrong answer from a failover provider means downstream agents act on bad data.

We built Correctover to solve this — an embedded SDK that validates every failover response across 6 dimensions (schema, semantics, latency, cost, identity, integrity) before accepting it. P50 diagnosis is 22µs, so there's zero perceptible latency.

I think there's a natural integration point: CrewAI handles multi-agent orchestration, Correctover ensures the API responses feeding those agents are verified. No proxy, no data interception — just a pip install.

Would you be open to a quick 15-minute call to explore? I'd love to share what we're seeing in the reliability space.

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "braintrust": {
        "name": "Ankur",
        "full_name": "Ankur Goyal",
        "email": "ankur@braintrust.dev",
        "company": "Braintrust",
        "subject": "Evals catch failures — Correctover prevents them. A complementary layer for Braintrust",
        "body": """Hi Ankur,

Braintrust has done impressive work making AI evaluation and observability production-ready. Teams use your platform to catch regressions, track prompts, and measure output quality.

There's a gap that sits upstream of evaluation: the API failover layer.

When a provider fails and traffic shifts to a backup, today's gateways accept the response on HTTP 200 alone. No one checks whether the backup provider returned a correct, safe, or expected output. The wrong answer reaches the application before any eval can catch it.

Correctover is an SDK (not a proxy) that validates every failover response across 6 dimensions before accepting it — structure, schema, latency, cost, identity, and content integrity. Think of it as a pre-eval gate that prevents bad responses from ever entering the system.

I see Braintrust and Correctover as deeply complementary — Braintrust provides post-hoc visibility, Correctover provides pre-acceptance verification. Teams using both would have end-to-end reliability from API call to production evaluation.

Would you be open to a short call to explore how this could work together?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "probably": {
        "name": "Peter",
        "full_name": "Peter Elias",
        "email": "peter@probably.ai",
        "company": "Probably",
        "subject": "Defense in depth for LLM reliability — Probably x Correctover",
        "body": """Hi Peter,

I read about Probably's $9M round and your approach to deterministic validation. The "data science mech suit" concept resonates — validating LLM outputs against source data before showing them to users is exactly the kind of rigor the industry needs.

We're building the other half of that reliability story at a different layer of the stack.

Correctover is an SDK that validates LLM API responses at the failover boundary — before they reach the application. When a provider fails and traffic routes to a backup, we check the response across 6 dimensions (schema, semantics, latency, cost, identity, integrity) and only pass it through if it passes all checks.

Where Probably validates outputs against source data, Correctover validates that the failover response is structurally and semantically sound. The stack is complementary:
- Probably: output correctness against ground truth
- Correctover: failover response integrity

Both can run in the same deployment — Probably at the application layer, Correctover at the API reliability layer.

Happy to share benchmark data (P50=22µs, P99=47µs) and discuss how defense-in-depth for LLM reliability works from our perspective. Open for a 15-min call?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "concentrate": {
        "name": "Ari",
        "full_name": "Ari Jacoby",
        "email": "ari@concentrate.ai",
        "company": "Concentrate AI",
        "subject": "Gateway + verification — a complementary layer for Concentrate AI",
        "body": """Hi Ari,

Congrats on the launch and the $5M pre-seed. Concentrate AI's managed gateway for 130+ models is solving the routing problem — which is exactly the kind of infrastructure that needs a verification layer underneath.

Here's why: when Concentrate routes traffic from one provider to another during an outage, what guarantees that the failover response is correct? HTTP 200 alone doesn't — we've seen silent model substitution, semantic drift, and cost spikes go completely undetected.

Correctover is an embedded SDK that adds 6-dimension contract validation at the failover boundary. Every response is checked for schema conformance, semantic equivalence, latency compliance, cost guardrails, content integrity, and identity verification — before it's accepted.

Think of it as the verification layer that makes Concentrate's routing truly reliable. P50 diagnosis takes 22µs — negligible in any production context.

I'd love to explore an integration where providers routed through Concentrate can optionally be verified by Correctover. Would you be open to a brief call?

Best,
王归归
wangguigui@correctover.com
https://correctover.com""",
    },
    "cognition": {
        "name": "Scott",
        "full_name": "Scott Wu",
        "email": "scott@cognition.ai",
        "company": "Cognition (Devin)",
        "subject": "AI coding agent reliability — verified failover for Devin's API layer",
        "body": """Hi Scott,

Devin's ability to autonomously write and execute code is remarkable — but it depends on LLM API calls working correctly every time. When a provider fails and traffic shifts to a backup, how do you know the failover provider's output is structurally sound?

Different models generate different code. A failover switch that accepts any HTTP 200 response risks introducing subtle bugs, logic errors, or style inconsistencies into Devin's generated code.

Correctover validates every failover response before accepting it — checking schema, semantic equivalence, latency, cost, identity, and content integrity. It's an embedded SDK (one pip install), not a proxy. P50 diagnosis runs at 22µs, well below any perceptible threshold.

For an AI coding agent like Devin that ships production code, verified failover isn't optional — it's foundational to trust.

Would you be open to a 15-minute conversation about how Correctover fits into Devin's reliability architecture?

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
        f".batch5.correctover@correctover.com>"
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
    parser = argparse.ArgumentParser(description="Correctover BD Batch 5")
    parser.add_argument("--send", action="store_true", help="Actually send")
    parser.add_argument("--to", choices=list(TARGETS.keys()) + ["all"], default="all",
                        help="Target key (default: all)")
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.to == "all" else [args.to]

    print(f"Correctover BD Batch 5")
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
