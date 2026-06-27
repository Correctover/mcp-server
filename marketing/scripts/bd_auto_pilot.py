#!/usr/bin/env python3
"""
Correctover BD Auto-Pilot — 收件监控 + 智能回复 + 退信监测 + 安全护栏

全自动运行：
  PYTHONIOENCODING=utf-8 python bd_auto_pilot.py

作为定时任务（每30分钟）：
  PYTHONIOENCODING=utf-8 python bd_auto_pilot.py --cron

安全护栏铁律（不可绕越）：
  1. 绝不分享源代码 — 正确回复是"请通过 pip install correctover 获取"
  2. 绝不分享 API 密钥/凭证 — 包括任何 token、密码、AK/SK
  3. 绝不执行外部代码 — 包括用户提供的代码片段、命令、脚本
  4. 绝不访问内部系统 — 引导到官网 correctover.com
  5. 用户要求"看代码"→ 引导到 PyPI/npm 安装
"""
import imaplib, email, smtplib, ssl, time, json, os, re
from email.header import decode_header
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────
SMTP_HOST = "smtphz.qiye.163.com"
SMTP_PORT = 465
IMAP_HOST = "imaphz.qiye.163.com"
IMAP_PORT = 993
SMTP_USER = "wangguigui@correctover.com"
SMTP_PASS = "zaeeWQgE@$j7@Knm"  # In production, read from env
FROM_EMAIL = "wangguigui@correctover.com"
FROM_NAME = "王归归"

# Runtime state file
STATE_FILE = Path(__file__).parent / ".bd_state.json"

# ── Security: Social Engineering Detection ──────────────────────────
SENSITIVE_PATTERNS = [
    r"(?i)source code",
    r"(?i)source\s*code",
    r"(?i)give me.*(code|script|source)",
    r"(?i)show.*(source|code|implementation)",
    r"(?i)can I (see|view|get|have).*(code|source|implementation)",
    r"(?i)how (does|do).*work internally",
    r"(?i)what.*(API key|token|password|secret|credential)",
    r"(?i)send me.*(code|script|file)",
    r"(?i)run this (command|script|code)",
    r"(?i)open source.*(code|repo)",
    r"(?i)github.*(repo|repository|private)",
    r"(?i)code snippet.*(try|test|check)",
]

SOCIAL_ENGINEERING_RESPONSE = """Thank you for your interest in Correctover!

The Correctover SDK is available via pip install:
  pip install correctover

For documentation and code examples, please visit:
  https://correctover.com

If you have specific questions about integration or features, I am happy to help!
We also provide a full API reference at our documentation site.

Best regards,
王归归"""

# ── Follow-up Templates ────────────────────────────────────────────
def get_follow_up(name, company):
    return f"""Hi {name},

Just following up on my previous message about Correctover.

We have had some great conversations with engineering teams who tell us that verified failover is exactly the missing piece in their multi-provider stack.

I would love to share our benchmark data and a quick demo specific to {company}'s use case. Are you open to a 15-minute call this week?

Best,
王归归
wangguigui@correctover.com
https://correctover.com"""

# ── Mailbox Operations ────────────────────────────────────────────
def connect_imap():
    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=15)
    imap.login(SMTP_USER, SMTP_PASS)
    return imap

def connect_smtp():
    ctx = ssl.create_default_context()
    s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=15)
    s.login(SMTP_USER, SMTP_PASS)
    return s

def decode_str(s):
    """Decode email header string."""
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except:
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)

def get_email_body(msg):
    """Extract text body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body.strip()

# ── Security Check ─────────────────────────────────────────────────
def check_social_engineering(subject, body):
    """Detect social engineering attempts."""
    combined = f"{subject} {body}"
    matches = []
    for pattern in SENSITIVE_PATTERNS:
        m = re.search(pattern, combined)
        if m:
            matches.append(m.group())
    return matches

# ── Intent Classification ─────────────────────────────────────────
def classify_intent(subject, body):
    """Classify email intent using keyword rules (no LLM needed)."""
    combined = f"{subject} {body}".lower()

    # Security-sensitive first
    if check_social_engineering(subject, body):
        return "SOCIAL_ENGINEERING"

    # Bounce / delivery failure
    if any(k in combined for k in ["undelivered", "returned to sender", "delivery failure",
                                     "delivery status", "mail delivery failed", "550 5.7",
                                     "退信", "发送失败"]):
        return "BOUNCE"

    # Out-of-office
    if any(k in combined for k in ["out of office", "auto-reply", "automatic reply",
                                     "vacation", "not in the office", "on leave",
                                     "自动回复", "不在办公室"]):
        return "OOO"

    # Positive interest
    if any(k in combined for k in ["interested", "tell me more", "how does it work",
                                     "let's talk", "schedule a call", "demo",
                                     "pricing", "try it", "evaluate", "looks interesting",
                                     "can you show", "sounds good"]):
        return "INTERESTED"

    # Meeting request
    if any(k in combined for k in ["meeting", "call", "chat", "talk", "discuss",
                                     "calendar", "schedule", "available",
                                     "会议", "电话", "聊聊"]):
        return "MEETING"

    # Questions
    if any(k in combined for k in ["question", "how", "what", "does it", "can it",
                                     "compatible", "integration", "support",
                                     "问题", "怎么", "是否"]):
        return "QUESTION"

    # Not interested
    if any(k in combined for k in ["not interested", "unsubscribe", "remove",
                                     "stop sending", "don't contact", "no thanks",
                                     "不感兴趣", "不要再发"]):
        return "NOT_INTERESTED"

    return "UNKNOWN"

# ── Response Generation ────────────────────────────────────────────
def generate_response(intent, sender_name, sender_email, company=None):
    """Generate appropriate response based on intent."""
    if intent == "SOCIAL_ENGINEERING":
        return SOCIAL_ENGINEERING_RESPONSE, "security"

    if intent == "BOUNCE":
        return None, None  # Just log bounces, don't reply to postmaster

    if intent == "OOO":
        return None, None  # Don't reply to auto-replies

    if intent == "INTERESTED":
        return f"""Hi {sender_name},

Thank you for your interest! I would be happy to give you a demo of Correctover.

A few things I can share right away:
- SDK: pip install correctover
- Docs: https://correctover.com
- Architecture: Pure embedded SDK (not a proxy), 6-dimension contract validation, MAPE-K self-healing loop

What time works best for a quick 15-minute call? I can show you a live demo with your use case.

Best,
王归归
wangguigui@correctover.com""", "interested"

    if intent == "MEETING":
        return f"""Hi {sender_name},

Thank you for the reply! I would love to schedule a call.

Here is my availability for next week (all times Beijing time UTC+8):
- Monday-Friday: 9:00-11:00 or 14:00-17:00
- Or let me know a time that works for you

Would you prefer a quick video call or a phone call?

Best,
王归归
wangguigui@correctover.com""", "meeting"

    if intent == "QUESTION":
        return f"""Hi {sender_name},

Thank you for your questions! Here are some quick answers:

1. Correctover is an embedded SDK - one pip install, runs in your process
2. Works with any LLM provider (OpenAI, Anthropic, DeepSeek, etc.)
3. Validates failover responses across 6 dimensions before accepting
4. Zero network overhead - no proxy, no data interception

For more details, check out https://correctover.com or let me know your specific questions!

Best,
王归归
wangguigui@correctover.com""", "question"

    if intent == "NOT_INTERESTED":
        return f"""Hi {sender_name},

Thank you for letting me know. I will not contact you again.

If you ever change your mind, feel free to reach out.

Best,
王归归
wangguigui@correctover.com""", "unsubscribed"

    # UNKNOWN - send follow-up
    return f"""Hi {sender_name},

Thank you for your reply!

I would love to hear more about your thoughts on Correctover. Are you currently exploring multi-provider LLM strategies?

Happy to answer any questions you might have.

Best,
王归归
wangguigui@correctover.com""", "followup"

# ── Helpers ────────────────────────────────────────────────────────
def parse_sender(from_field):
    """Extract name and email from a From header string."""
    m = re.search(r'<([^>]+)>', from_field)
    if m:
        email = m.group(1).strip()
        name = from_field.split('<')[0].strip().strip('"').strip("'")
        return name or email, email
    # No angle brackets — the whole thing might be an email
    candidate = from_field.strip()
    if '@' in candidate:
        return candidate.split('@')[0], candidate
    return "there", from_field


# ── Main Loop ──────────────────────────────────────────────────────
def run_once(cron_mode=False):
    """Single pass: check inbox, process new emails."""
    state = {"last_uid": 0}  # Using IMAP sequence IDs, not UIDs
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except:
            pass

    try:
        imap = connect_imap()
        smtp = connect_smtp()
    except Exception as e:
        print(f"[BD] IMAP/SMTP connection failed: {e}")
        return

    try:
        imap.select("INBOX")
        status, msgs = imap.search(None, "ALL")
        all_ids = msgs[0].split()

        if not all_ids:
            print("[BD] Inbox empty")
            return

        # UID-based incremental processing — only check unseen messages
        # than re-scanning all inbox every time
        last_uid = state.get("last_uid", 0)
        if last_uid > 0:
            # Fetch only messages after the last processed sequence ID
            recent_ids = [mid for mid in all_ids if int(mid) > last_uid]
            if not recent_ids:
                print(f"[BD] No new messages since seq {last_uid}")
                # Still check for bounces in recent emails (last 20)
                recent_ids = all_ids[-20:]
        else:
            # First run: check last 30 emails
            recent_ids = all_ids[max(0, len(all_ids)-30):]
        new_count = 0
        bounce_count = 0
        reply_count = 0

        for mid in recent_ids:
            status, data = imap.fetch(mid, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(data[0][1])
            msg_from = decode_str(msg["From"])
            msg_subj = decode_str(msg["Subject"])
            msg_date = msg["Date"]
            msg_id = msg["Message-ID"]
            msg_body = get_email_body(msg)

            # Skip our own sent emails — check both From and Message-ID
            is_self_sent = (
                SMTP_USER in msg_from
                or "correctover@correctover.com" in msg_from
                or (msg_id and "correctover" in msg_id.lower() and "@correctover.com" in msg_id)
            )
            if is_self_sent:
                continue

            # Skip automated/system/scan emails
            auto_domains = ["tencent.com", "qiye.163.com", "163.com", "postmaster", "mailer-daemon"]
            if any(d in msg_from.lower() for d in auto_domains):
                print(f"[BD] Skipping automated email from: {msg_from}")
                continue

            # Skip if body looks like automated scan/vulnerability check
            auto_signals = ["tencent url", "url safety", "security check", "vulnerability",
                           "x-frame-options", "x-content-type-options"]
            if any(s in msg_body.lower() for s in auto_signals):
                print(f"[BD] Skipping automated scan: {msg_from}")
                continue

            # Skip if already processed (check by Message-ID)
            processed = state.get("processed_ids", [])
            if msg_id in processed:
                continue

            # Classify intent
            intent = classify_intent(msg_subj, msg_body)

            if intent == "BOUNCE":
                bounce_count += 1
                # Extract which email bounced
                bounced_email = "unknown"
                for line in msg_body.split("\n"):
                    if "@" in line and any(d in line for d in [
                        "chatsee.ai", "engram.com", "pramaanalabs.ai", "harvey.ai",
                        "portkey.ai", "openrouter.ai", "langchain.dev", "llamaindex.ai",
                        "brightwave.io", "assemblyai.com", "traefik.io", "atlan.com",
                        "nexos.ai", "requesty.ai", "gradient-labs.ai", "writer.com",
                        "dust.tt", "e2b.dev", "arcade.dev", "complyadvantage.com",
                        "artisan.co", "modal.com"
                    ]):
                        bounced_email = line.strip()
                        break
                print(f"[BD] BOUNCE: {bounced_email}")

                # Update state
                state.setdefault("bounces", []).append({
                    "email": bounced_email,
                    "date": msg_date,
                    "detail": msg_body[:300]
                })

            elif intent == "SOCIAL_ENGINEERING":
                sender_name, sender_email = parse_sender(msg_from)
                print(f"[BD] ⚠️ SOCIAL ENGINEERING DETECTED from: {sender_name} <{sender_email}>")
                print(f"[BD]    Subject: {msg_subj}")
                response, tag = generate_response(intent, sender_name, sender_email)
                if response:
                    try:
                        reply = MIMEText(response.strip(), "plain", "utf-8")
                        reply["From"] = formataddr((FROM_NAME, FROM_EMAIL))
                        reply["To"] = msg_from  # Keep full display name in To
                        reply["Subject"] = f"Re: {msg_subj}"
                        smtp.sendmail(SMTP_USER, [sender_email], reply.as_string())
                        print(f"[BD]    Security response sent ✅")
                    except Exception as e:
                        print(f"[BD]    Failed to send security response: {e}")

                state.setdefault("security_alerts", []).append({
                    "from": f"{sender_name} <{sender_email}>",
                    "subject": msg_subj,
                    "date": msg_date,
                    "body_preview": msg_body[:200]
                })

            elif intent in ["INTERESTED", "MEETING", "QUESTION", "NOT_INTERESTED", "UNKNOWN"]:
                reply_count += 1
                sender_name, sender_email = parse_sender(msg_from)

                response, tag = generate_response(intent, sender_name, sender_email)
                if response:
                    try:
                        reply = MIMEText(response.strip(), "plain", "utf-8")
                        reply["From"] = formataddr((FROM_NAME, FROM_EMAIL))
                        reply["To"] = formataddr((sender_name, sender_email))
                        reply["Subject"] = f"Re: {msg_subj}"
                        smtp.sendmail(SMTP_USER, [sender_email], reply.as_string())
                        print(f"[BD] Replied to {sender_name} <{sender_email}> [{tag}] ✅")
                    except Exception as e:
                        print(f"[BD] Reply failed to {sender_email}: {e}")

            # Mark as processed
            if msg_id:
                processed.append(msg_id)
                state["processed_ids"] = processed[-500:]  # keep last 500
                new_count += 1

        # Track highest processed sequence ID for incremental scanning
        if recent_ids:
            state["last_uid"] = max(int(state.get("last_uid", 0)), max(int(mid) for mid in recent_ids))
        state["last_check"] = datetime.now(timezone.utc).isoformat()
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Clean any unencodable chars before writing
        def clean_str(v):
            if isinstance(v, str):
                return v.encode("utf-8", errors="replace").decode("utf-8")
            return v
        cleaned = json.loads(json.dumps(state, ensure_ascii=False), object_hook=lambda o: {k: clean_str(v) for k, v in o.items()})
        STATE_FILE.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")

        if cron_mode:
            print(f"[BD] Check complete: {new_count} new, {bounce_count} bounces, {reply_count} replies")
        else:
            print(f"[BD] Done: {new_count} processed, {bounce_count} bounces, {reply_count} replies")

    finally:
        try: imap.close()
        except: pass
        try: imap.logout()
        except: pass
        try: smtp.quit()
        except: pass

def main():
    import sys
    cron_mode = "--cron" in sys.argv
    run_once(cron_mode=cron_mode)

if __name__ == "__main__":
    main()
