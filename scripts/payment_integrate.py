#!/usr/bin/env python3
"""
Correctover License Key Generator

支付走阿里云市场 + 虎皮椒（XunhuPay），在 FC license-api 自动处理。
此脚本仅用于：
  1. 本地测试生成 License Key
  2. 手动补发 Key
  3. 验证 HMAC 签名一致性

用法:
  python payment_integrate.py generate <plan> <customer> [--days N]
  python payment_integrate.py test         # 生成测试 Key
"""
import json, hmac, hashlib, base64, os, sys, time

HMAC_SECRET = os.environ.get("CORRECTOVER_HMAC_SECRET", "correctover-mcp-hmac-v1-2026")

LICENSE_PREFIXES = {
    "trial": "CV-TRL-",
    "pro": "CV-PRO-",
    "enterprise": "CV-ENT-",
}


def generate_license_key(plan: str, customer: str, days: int = 365) -> str:
    """生成 HMAC-SHA256 签名的 License Key（与 FC / Go 端格式一致）"""
    prefix = LICENSE_PREFIXES.get(plan, "CV-PRO-")
    payload = {
        "p": plan,
        "e": int(time.time()) + days * 86400,
        "c": customer,
        "v": 1,
    }
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(
        HMAC_SECRET.encode(),
        payload_str.encode(),
        hashlib.sha256,
    ).hexdigest()
    combined = f"{payload_str}.{sig}"
    b64 = base64.urlsafe_b64encode(combined.encode()).rstrip(b"=").decode()
    return f"{prefix}{b64}"


def main():
    # --- 命令行模式 ---
    if len(sys.argv) >= 3 and sys.argv[1] == "generate":
        plan = sys.argv[2]
        customer = sys.argv[3] if len(sys.argv) > 3 else "test@example.com"
        days = 365
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1])
        key = generate_license_key(plan, customer, days)
        print(f"Key:   {key}")
        print(f"Plan:  {plan}")
        print(f"Cust:  {customer}")
        print(f"Days:  {days}")
        return

    # --- 默认：打印测试 Key ---
    print("=" * 60)
    print("Correctover License Key Generator")
    print("=" * 60)
    print("\n📋 Sample License Keys:")
    for plan in ["trial", "pro", "enterprise"]:
        key = generate_license_key(plan, "demo@example.com",
                                   days=3 if plan == "trial" else 365)
        print(f"  {plan.upper():12s}: {key}")

    print("""
✅ 支付系统已在 FC license-api 中运行：
   - 阿里云市场 SPI → 自动签发 + 发邮件
   - 虎皮椒 XunhuPay → 支付宝/微信扫码付款 → 自动签发 + 发邮件
   - 详见 fc-functions/license-api/index.py
""")


if __name__ == "__main__":
    main()
