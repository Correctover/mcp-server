#!/usr/bin/env python3
"""Correctover 支付系统集成 — Lemon Squeezy + License Key 自动生成"""
import json, hmac, hashlib, base64, os, sys, time
from pathlib import Path

CONFIG = {
    "store_url": "https://correctover.lemonsqueezy.com",
    "plans": {
        "pro_monthly": {"product_id": None, "variant_id": None, "price": 99, "plan": "pro", "days": 30},
        "pro_yearly": {"product_id": None, "variant_id": None, "price": 699, "plan": "pro", "days": 365},
        "enterprise": {"product_id": None, "variant_id": None, "price": 1499, "plan": "enterprise", "days": 365},
    },
    "hmac_secret": os.environ.get("CORRECTOVER_HMAC_SECRET", "correctover-mcp-hmac-v1-2026"),
    "license_api_url": "https://api.correctover.cn/api/v1/license"
}

LICENSE_PREFIXES = {
    "trial": "CV-TRL-",
    "pro": "CV-PRO-",
    "enterprise": "CV-ENT-",
}

def generate_license_key(plan: str, customer: str, days: int = 365) -> str:
    """Generate HMAC-signed license key (standard FC-compatible format)"""
    prefix = LICENSE_PREFIXES.get(plan, "CV-PRO-")
    # Standard format: JSON payload + "." + full HMAC-SHA256 hex → base64
    payload = {
        "p": plan,
        "e": int(time.time()) + days * 86400,
        "c": customer,
        "v": 1,
    }
    payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    sig = hmac.new(
        CONFIG["hmac_secret"].encode(),
        payload_str.encode(),
        hashlib.sha256
    ).hexdigest()
    combined = f"{payload_str}.{sig}"
    b64 = base64.urlsafe_b64encode(combined.encode()).rstrip(b'=').decode()
    return f"{prefix}{b64}"


def generate_payment_links(plan: str) -> dict:
    """Generate Lemon Squeezy payment links (placeholder - user fills in product/variant IDs)"""
    links = {
        "pro_monthly": f"{CONFIG['store_url']}/buy/{CONFIG['plans']['pro_monthly']['product_id']}",
        "pro_yearly": f"{CONFIG['store_url']}/buy/{CONFIG['plans']['pro_yearly']['product_id']}",
        "enterprise": f"{CONFIG['store_url']}/buy/{CONFIG['plans']['enterprise']['product_id']}",
    }
    return links


def create_buy_page():
    """Generate a working buy.html with Lemon Squeezy embed"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Buy Correctover Pro · LLM Reliability SDK</title>
<script src="https://app.lemonsqueezy.com/lemon.js" defer></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; background: #08080f; color: #e8e8f0; line-height: 1.5; }
.container { max-width: 1000px; margin: 0 auto; padding: 40px 24px; }
h1 { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
.sub { color: #606080; margin-bottom: 40px; font-size: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.card { background: #0d0d1a; border: 1px solid #1a1a2e; border-radius: 10px; padding: 32px; display: flex; flex-direction: column; }
.card.featured { border-color: #00d4b0; box-shadow: 0 0 20px rgba(0,212,176,0.1); }
.card h2 { font-size: 22px; font-weight: 700; margin-bottom: 8px; }
.price { font-size: 42px; font-weight: 750; color: #00d4b0; margin: 16px 0; }
.price span { font-size: 16px; color: #606080; font-weight: 400; }
.desc { color: #606080; font-size: 14px; margin-bottom: 24px; min-height: 40px; }
.features { list-style: none; padding: 0; margin-bottom: 32px; flex: 1; }
.features li { padding: 8px 0; font-size: 14px; color: #b0b0c0; border-bottom: 1px solid #1a1a2e; }
.features li:last-child { border-bottom: none; }
.features li::before { content: "✓ "; color: #00d4b0; font-weight: 700; }
.btn { display: block; text-align: center; padding: 14px; border-radius: 6px; font-size: 16px; font-weight: 700; text-decoration: none; transition: opacity .15s; }
.btn-primary { background: #00d4b0; color: #08080f; }
.btn-outline { background: transparent; color: #e8e8f0; border: 1px solid #1a1a2e; }
.btn:hover { opacity: .85; }
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(0,212,176,0.15); color: #00d4b0; margin-bottom: 8px; }
.footer { margin-top: 48px; text-align: center; font-size: 13px; color: #404060; }
.footer a { color: #00d4b0; text-decoration: none; }
.muted { color: #606080; font-size: 13px; }
</style>
</head>
<body>
<div class="container">
  <h1>Buy Correctover</h1>
  <p class="sub">Choose the plan that fits your scale. All plans include the full reliability stack.</p>

  <div class="grid">
    <!-- Free -->
    <div class="card">
      <h2>Free</h2>
      <div class="price">$0<span>/mo</span></div>
      <p class="desc">Try the full stack, limited to 2 providers.</p>
      <ul class="features">
        <li>6-dimension contract validation</li>
        <li>MAPE-K self-healing loop</li>
        <li>Up to 2 providers</li>
        <li>Community support</li>
        <li>pip install correctover</li>
      </ul>
      <a href="https://github.com/Correctover/mcp-server" class="btn btn-outline">Get Started Free →</a>
    </div>

    <!-- Pro -->
    <div class="card featured">
      <span class="badge">Most Popular</span>
      <h2>Pro</h2>
      <div class="price">$99<span>/yr</span></div>
      <p class="desc">For professional developers building production AI agents.</p>
      <ul class="features">
        <li>Unlimited providers</li>
        <li>6-dimension contract validation</li>
        <li>MAPE-K self-healing (L1-L4)</li>
        <li>Custom validation rules</li>
        <li>Validation audit log</li>
        <li>Priority support</li>
      </ul>
      <a href="#" class="btn btn-primary lemon-button" data-product="pro">Buy Pro $99/yr →</a>
    </div>

    <!-- Enterprise -->
    <div class="card">
      <h2>Enterprise</h2>
      <div class="price">$1,499<span>/mo</span></div>
      <p class="desc">For organizations requiring SLA guarantees and private deployment.</p>
      <ul class="features">
        <li>Everything in Pro</li>
        <li>Private deployment (BYOK)</li>
        <li>RBAC & audit logging</li>
        <li>SLA 99.9%</li>
        <li>Dedicated support engineer</li>
      </ul>
      <a href="mailto:team@correctover.com?subject=Enterprise%20Plan%20Inquiry" class="btn btn-outline">Contact Sales →</a>
    </div>
  </div>

  <div class="footer">
    <p>All plans include a 7-day free trial. No credit card required to start.</p>
    <p>Questions? <a href="mailto:team@correctover.com">team@correctover.com</a></p>
    <p style="margin-top:12px">🔒 All transactions processed securely via Lemon Squeezy</p>
  </div>
</div>
</body>
</html>"""
    out_path = Path("C:/d/workspace/correctover/web/buy.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
    print(f"✅ Buy page created: {out_path}")
    return str(out_path)


def main():
    print("=" * 60)
    print("Correctover Payment System Integration")
    print("=" * 60)

    # 1. Generate sample license keys
    print("\n📋 Sample License Keys:")
    for plan in ["trial", "pro", "enterprise"]:
        key = generate_license_key(plan, "demo@example.com",
                                   days=3 if plan == "trial" else 365)
        print(f"  {plan.upper():12s}: {key}")

    # 2. Generate payment links
    print("\n🔗 Payment Links (configure Lemon Squeezy first):")
    links = generate_payment_links("pro")
    for k, v in links.items():
        print(f"  {k:15s}: {v}")

    # 3. Create buy page
    print()
    path = create_buy_page()
    print(f"\n📄 Buy page: {path}")

    # 4. Save license generator for admin use
    print("\n✅ Payment system ready.")
    print("   ⚠️  Before going live, configure Lemon Squeezy:")
    print("      1. Create products at https://app.lemonsqueezy.com/products")
    print("      2. Set CORRECTOVER_HMAC_SECRET env var")
    print("      3. Update product/variant IDs in this script")
    print("      4. Deploy buy.html to correctover.com/buy")


if __name__ == "__main__":
    main()
