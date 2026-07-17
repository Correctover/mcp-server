#!/usr/bin/env python3
"""
Correctover License Admin — 生成、验证、管理License Key

用法:
  python license_admin.py generate pro customer@example.com --days 365
  python license_admin.py generate trial tester@example.com --days 3
  python license_admin.py generate enterprise corp@company.com --days 365
  python license_admin.py verify "CV-PRO-xxxx.xxxx"
  python license_admin.py list
"""
import json, hmac, hashlib, base64, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

HMAC_SECRET = os.environ.get("CORRECTOVER_HMAC_SECRET", "correctover-mcp-hmac-v1-2026")
KEYS_FILE = Path(__file__).parent / ".license_keys.json"

PREFIXES = {
    "trial": "CV-TRL-", "pro": "CV-PRO-",
    "enterprise": "CV-ENT-", "lifetime": "CV-LTM-",
}

PLANS = {
    "trial": {"name": "Trial", "days": 3, "providers": 2},
    "pro": {"name": "Pro", "days": 365, "providers": 999},
    "enterprise": {"name": "Enterprise", "days": 365, "providers": 999},
    "lifetime": {"name": "Lifetime", "days": 36500, "providers": 999},
}

def load_keys():
    if KEYS_FILE.exists():
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    return {"keys": []}

def save_keys(keys):
    KEYS_FILE.write_text(json.dumps(keys, indent=2, ensure_ascii=False), encoding="utf-8")

def generate_key(plan: str, customer: str, days: int = None) -> dict:
    p = PLANS.get(plan)
    if not p:
        raise ValueError(f"Unknown plan: {plan}. Options: {list(PLANS.keys())}")
    prefix = PREFIXES[plan]
    if days is None:
        days = p["days"]
    expiry = int(time.time()) + days * 86400
    # Standard format: JSON payload + "." + full HMAC-SHA256 hex → base64
    payload = {"p": plan, "e": expiry, "c": customer, "v": 1}
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(HMAC_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    combined = f"{payload_str}.{sig}"
    b64 = base64.urlsafe_b64encode(combined.encode()).rstrip(b"=").decode()
    key = f"{prefix}{b64}"

    record = {
        "key": key,
        "plan": plan,
        "customer": customer,
        "created": datetime.now(timezone.utc).isoformat(),
        "expires": datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
        "days": days,
        "activated": False,
        "device": None,
    }
    db = load_keys()
    db["keys"].append(record)
    save_keys(db)
    return record

def verify_key(key: str) -> dict:
    for prefix, label in PREFIXES.items():
        if key.startswith(label):
            plan = prefix
            encoded = key[len(label):]
            break
    else:
        return {"valid": False, "error": "Unknown prefix"}

    try:
        decoded = base64.urlsafe_b64decode(encoded + "==").decode("utf-8")
    except Exception:
        return {"valid": False, "error": "Invalid key encoding"}

    if "." not in decoded:
        return {"valid": False, "error": "Invalid format (no signature)"}
    payload_str, sig = decoded.rsplit(".", 1)

    expected = hmac.new(HMAC_SECRET.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return {"valid": False, "error": "Invalid signature"}

    try:
        payload = json.loads(payload_str)
    except:
        return {"valid": False, "error": "Invalid payload encoding"}

    now = time.time()
    expired = payload.get("e", 0) < now
    remaining_days = max(0, int((payload["e"] - now) / 86400))

    return {
        "valid": True,
        "plan": payload.get("p"),
        "customer": payload.get("c"),
        "expired": expired,
        "remaining_days": remaining_days,
        "providers": PLANS.get(payload.get("p"), {}).get("providers", 0),
    }

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python license_admin.py generate <plan> <customer> [--days N]")
        print("  python license_admin.py verify <license-key>")
        print("  python license_admin.py list")
        plan_list = ', '.join(f'{k} ({v["name"]})' for k, v in PLANS.items())
        print(f"\nPlans: {plan_list}")
        return

    cmd = sys.argv[1]

    if cmd == "generate":
        plan = sys.argv[2]
        customer = sys.argv[3]
        days = None
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1])
        rec = generate_key(plan, customer, days)
        expiry = datetime.fromisoformat(rec["expires"]).strftime("%Y-%m-%d %H:%M UTC")
        p = PLANS[plan]
        print(f"\n✅ License Key Generated")
        print(f"   Key:      {rec['key']}")
        print(f"   Plan:     {p['name']} ({plan})")
        print(f"   Customer: {customer}")
        print(f"   Expires:  {expiry}")
        print(f"   Providers: {p['providers']}")
        print(f"\n   Set: export CORRECTOVER_LICENSE_KEY='{rec['key']}'")

    elif cmd == "verify":
        key = sys.argv[2]
        result = verify_key(key)
        if result["valid"]:
            status = "✅ VALID" if not result["expired"] else "❌ EXPIRED"
            print(f"\n{status} License Key")
            print(f"   Plan:      {result['plan']} ({result.get('providers', '?')} providers)")
            print(f"   Customer:  {result['customer']}")
            print(f"   Remaining: {result['remaining_days']} days")
        else:
            print(f"\n❌ INVALID: {result.get('error', 'Unknown')}")

    elif cmd == "list":
        db = load_keys()
        print(f"\n📋 License Keys ({len(db['keys'])} total)")
        for k in db["keys"]:
            status = "✅" if k.get("activated") else "⬜"
            print(f"   {status} {k['key'][:30]}... | {k['plan']:12s} | {k['customer']}")

if __name__ == "__main__":
    main()
