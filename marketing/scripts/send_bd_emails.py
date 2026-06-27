#!/usr/bin/env python3
"""Correctover BD Email Sender — sends personalized outreach via SMTP.

Usage:
    python send_bd_emails.py              # dry-run (print only)
    python send_bd_emails.py --send       # actually send
    python send_bd_emails.py --send --to chatsee   # send to specific target
"""

import smtplib, ssl, argparse, textwrap, re, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ── SMTP Config ──────────────────────────────────────────────────────
SMTP_HOST = "smtphz.qiye.163.com"
SMTP_PORT = 465
SMTP_USER = "wangguigui@correctover.com"
SMTP_PASS = "zaeeWQgE@$j7@Knm"
FROM_EMAIL = "wangguigui@correctover.com"
FROM_NAME = "王归归"

# ── Target Definitions ───────────────────────────────────────────────
TARGETS = {
    "chatsee": {
        "name": "Sekhar",
        "full_name": "Sekhar Sarukkai",
        "email": "sekhar@chatsee.ai",
        "company": "ChatSee.ai",
        "subject": "Agent fault detection needs a self-healing layer — complementary to ChatSee.ai",
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
        "name": "Dan",
        "full_name": "Dan Biderman",
        "email": "dan@engram.com",
        "company": "Engram",
        "subject": "API reliability for multi-provider agent platforms — Correctover x Engram",
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
        "name": "Ranjan",
        "full_name": "Ranjan Rajagopalan",
        "email": "ranjan@pramaanalabs.ai",
        "company": "Pramaana Labs",
        "subject": "From formal verification to verified failover — a kindred approach",
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
        "name": "Siva",
        "full_name": "Siva Gurumurthy",
        "email": "siva@harvey.ai",
        "company": "Harvey AI",
        "subject": "Verified failover for legal AI — why Harvey needs more than HTTP 200",
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
        f".correctover@correctover.com>"
    )

    # Plain text version
    body_text = textwrap.dedent(body).strip()
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    # Simple HTML version
    body_html = body_text.replace("\n", "<br>\n")
    html = f"""<html><body>
<pre style="font-family: -apple-system, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; color: #333;">
{body_html}
</pre>
</body></html>"""
    msg.attach(MIMEText(html, "html", "utf-8"))

    if dry_run:
        print(f"\n{'='*60}")
        print(f"📧 TO: {to_name} <{to_email}>")
        print(f"📋 SUBJECT: {subject}")
        print(f"{'='*60}")
        print(body_text)
        print(f"\n✅ DRY-RUN — not sent\n")
        return True

    # Actually send
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        print(f"  ✅ Sent to {to_name} <{to_email}>")
        return True
    except smtplib.SMTPRecipientsRefused as e:
        print(f"  ❌ Recipient refused ({to_email}): {e}")
        return False
    except smtplib.SMTPResponseException as e:
        print(f"  ❌ SMTP error ({to_email}): code={e.smtp_code}, {e.smtp_error}")
        return False
    except Exception as e:
        print(f"  ❌ Failed ({to_email}): {type(e).__name__}: {e}")
        return False


def verify_email_domain(email: str) -> bool:
    """Quick MX record check — not 100% but better than nothing."""
    import dns.resolver
    domain = email.split("@")[1]
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_records = [str(r.exchange) for r in answers]
        print(f"  📡 MX for {domain}: {mx_records[0] if mx_records else 'none'}")
        return len(mx_records) > 0
    except Exception as e:
        print(f"  ⚠️  Cannot verify MX for {domain}: {e}")
        return True  # don't block on DNS failure


def main():
    parser = argparse.ArgumentParser(description="Correctover BD Email Sender")
    parser.add_argument("--send", action="store_true", help="Actually send emails")
    parser.add_argument("--to", choices=list(TARGETS.keys()) + ["all"], default="all",
                        help="Target recipient key (default: all)")
    parser.add_argument("--verify", action="store_true", help="Verify MX records before sending")
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.to == "all" else [args.to]

    print(f"🔵 Correctover BD Email Sender")
    print(f"   Mode: {'LIVE' if args.send else 'DRY-RUN'}")
    print(f"   SMTP: {SMTP_HOST}:{SMTP_PORT} as {FROM_EMAIL}")
    print(f"   Targets: {', '.join(targets)}")
    print()

    if args.send:
        # Warm up SMTP connection
        print("🔄 Warming up SMTP connection...")
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
                server.login(SMTP_USER, SMTP_PASS)
                print(f"  ✅ SMTP connected & authenticated")
        except Exception as e:
            print(f"  ❌ SMTP connect failed: {e}")
            return

    sent_ok = 0
    sent_fail = 0

    for key in targets:
        target = TARGETS[key]
        print(f"\n📧 Preparing: {target['full_name']} → {target['email']}")

        if args.verify:
            if not verify_email_domain(target["email"]):
                print(f"  ⚠️  Domain may be invalid, skipping")
                sent_fail += 1
                continue

        if send_email(key, dry_run=not args.send):
            sent_ok += 1
        else:
            sent_fail += 1

        if args.send:
            time.sleep(2)  # polite delay between sends

    print(f"\n{'='*60}")
    print(f"📊 Results: {sent_ok} sent, {sent_fail} failed")
    if not args.send:
        print(f"ℹ️  Pass --send to actually send")
    print()

    # Suggestion for bounce handling
    if sent_fail > 0 and args.send:
        print(f"💡 Some emails failed. Common fixes:")
        print(f"   - Verify the email address is correct")
        print(f"   - Check SMTP spam policy (163 enterprise may rate-limit)")
        print(f"   - Try sending individually with --to <name>")


if __name__ == "__main__":
    main()
