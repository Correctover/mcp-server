# Correctover License API — 阿里云 FC 版
# HTTP 触发器入口
# 含：License 管理 + 邮件自动发送 + 阿里云市场 SPI + 虎皮椒支付回调

import base64
import hashlib
import hmac as hmac_mod
import json
import os
import smtplib
import time
import uuid
from email.mime.text import MIMEText
from urllib.parse import parse_qs, urlencode

# ── Config ───────────────────────────────────────────────────────

HMAC_SECRET = os.environ.get("NB_HMAC_SECRET", "").encode()
ADMIN_TOKEN = os.environ.get("NB_ADMIN_TOKEN", "")
NOTIFY_EMAIL = os.environ.get("NB_NOTIFY_EMAIL", "wangguigui@correctover.com")

# SMTP — 网易企业邮
SMTP_HOST = os.environ.get("NB_SMTP_HOST", "smtphz.qiye.163.com")
SMTP_PORT = int(os.environ.get("NB_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("NB_SMTP_USER", "wangguigui@correctover.com")
SMTP_PASS = os.environ.get("NB_SMTP_PASS", "")
SMTP_FROM = os.environ.get("NB_SMTP_FROM", "wangguigui@correctover.com")

# 阿里云市场 SPI 安全密钥（在 msp.aliyun.com 概览页获取）
MKT_SPI_KEY = os.environ.get("NB_MKT_SPI_KEY", "")

# 虎皮椒支付（XunhuPay）
XUNHU_APPID = os.environ.get("NB_XUNHU_APPID", "")
XUNHU_SECRET = os.environ.get("NB_XUNHU_SECRET", "")

# SKU → Plan 映射（在云市场商品管理-销售信息中查看 skuId）
# 格式: "skuId1:plan1,skuId2:plan2,..."
MKT_SKU_MAP_STR = os.environ.get("NB_MKT_SKU_MAP", "")
MKT_SKU_MAP = {}
if MKT_SKU_MAP_STR:
    for pair in MKT_SKU_MAP_STR.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            MKT_SKU_MAP[k.strip()] = v.strip()

# IMAP — 邮件自动回复（网易企业邮）
IMAP_HOST = os.environ.get("NB_IMAP_HOST", "imaphz.qiye.163.com")
IMAP_PORT = int(os.environ.get("NB_IMAP_PORT", "993"))
IMAP_USER = os.environ.get("NB_IMAP_USER", "wangguigui@correctover.com")
IMAP_PASS = os.environ.get("NB_IMAP_PASS", "v4Hs#@EfkJZ7qgL7")
# 邮件自动回复默认签发的套餐
IMAP_DEFAULT_PLAN = os.environ.get("NB_IMAP_DEFAULT_PLAN", "trial")
# 邮件关键词触发（匹配主题或正文）
IMAP_KEYWORDS = ["license", "key", "授权", "激活", "试用", "trial", "pro", "购买", "buy"]

PLANS = {
    # 新3档 — CV- 前缀（Correctover 品牌）
    "pro":        {"prefix": "CV-PRO-", "days": 365,   "label": "Pro专业版",     "en": "Pro",              "price": 699,  "price_label": "¥699/年", "max_devices": 1},
    "enterprise": {"prefix": "CV-ENT-", "days": 365,   "label": "Enterprise企业版", "en": "Enterprise",    "price": 2999, "price_label": "¥2,999/年", "max_devices": 10},
    # Legacy（兼容旧key，保留 NB- 和 CV- 双前缀）
    "trial":      {"prefix": "CV-TRL-", "days": 7,     "label": "试用版(7天)",   "en": "Trial (7 Days)",   "price": 0,    "price_label": "免费", "max_devices": 1},
    "monthly":    {"prefix": "CV-MON-", "days": 30,    "label": "月卡(30天)",    "en": "Monthly",          "price": 29,   "price_label": "¥29/月", "max_devices": 1},
    "annual":     {"prefix": "CV-ANN-", "days": 365,   "label": "年卡(365天)",   "en": "Annual",           "price": 699,  "price_label": "¥699/年", "max_devices": 1},
    "lifetime":   {"prefix": "CV-LTM-", "days": 36500, "label": "永久授权",      "en": "Lifetime",         "price": 299,  "price_label": "¥299", "max_devices": 1},
}

# 使用 OSS 存储 license 数据（FC 无本地持久化）
import oss2

OSS_AK = os.environ.get("NB_OSS_AK", "")
OSS_SK = os.environ.get("NB_OSS_SK", "")
OSS_BUCKET = os.environ.get("NB_OSS_BUCKET", "correctover-cn")
OSS_ENDPOINT = "https://oss-cn-hangzhou.aliyuncs.com"

# ── OSS Storage ──────────────────────────────────────────────────

def _get_oss_bucket():
    auth = oss2.Auth(OSS_AK, OSS_SK)
    return oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)

def _db_load(name="issued.json"):
    bucket = _get_oss_bucket()
    try:
        data = bucket.get_object(f"license-db/{name}").read()
        return json.loads(data)
    except Exception:
        return []

def _db_save(name, data):
    bucket = _get_oss_bucket()
    bucket.put_object(f"license-db/{name}", json.dumps(data, ensure_ascii=False).encode())

def _db_append(entry):
    db = _db_load("issued.json")
    db.append(entry)
    _db_save("issued.json", db)

def _is_revoked(issue_id):
    try:
        return issue_id in _db_load("revoked.json")
    except Exception:
        return False

def _db_find_instance(instance_id):
    """查找 mkt_instance_id 对应的记录"""
    db = _db_load("issued.json")
    for e in db:
        if e.get("mkt_instance_id") == instance_id:
            return e
    return None

def _db_update_instance(instance_id, updates):
    """更新指定 instance 的字段"""
    db = _db_load("issued.json")
    changed = False
    for e in db:
        if e.get("mkt_instance_id") == instance_id:
            e.update(updates)
            changed = True
            break
    if changed:
        _db_save("issued.json", db)
    return changed

# ── User Database ─────────────────────────────────────────────────

USER_SALT = os.environ.get("NB_USER_SALT", "correctover-user-salt-2026").encode()

def _user_hash_password(pwd):
    return hashlib.sha256(pwd.encode("utf-8") + USER_SALT).hexdigest()

def _user_sign_token(email):
    payload = {"e": email, "t": int(time.time()), "i": str(uuid.uuid4())[:8]}
    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac_mod.new(HMAC_SECRET, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
    combined = f"{payload_str}.{sig}"
    return base64.urlsafe_b64encode(combined.encode("utf-8")).rstrip(b"=").decode("utf-8")

def _user_verify_token(token):
    try:
        decoded = base64.urlsafe_b64decode(token + "==").decode("utf-8")
        if "." not in decoded:
            return None
        payload_str, sig_hex = decoded.rsplit(".", 1)
        expected = hmac_mod.new(HMAC_SECRET, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac_mod.compare_digest(sig_hex, expected):
            return None
        return json.loads(payload_str)
    except Exception:
        return None

def _db_load_users():
    bucket = _get_oss_bucket()
    try:
        data = bucket.get_object("user-db/users.json").read()
        return json.loads(data)
    except Exception:
        return []

def _db_save_users(users):
    bucket = _get_oss_bucket()
    bucket.put_object("user-db/users.json", json.dumps(users, ensure_ascii=False).encode())

def _db_find_user(email):
    users = _db_load_users()
    for u in users:
        if u.get("email", "").lower() == email.lower():
            return u
    return None

def _db_upsert_user(email, updates):
    users = _db_load_users()
    for u in users:
        if u.get("email", "").lower() == email.lower():
            u.update(updates)
            _db_save_users(users)
            return u
    new_user = {"email": email, "created_at": int(time.time())}
    new_user.update(updates)
    users.append(new_user)
    _db_save_users(users)
    return new_user

# ── Email ────────────────────────────────────────────────────────

def _send_email(to, subject, body_html):
    """通过网易企业邮 SMTP 发送邮件"""
    if not SMTP_PASS:
        print("[WARN] SMTP password not configured, skip email")
        return False
    try:
        msg = MIMEText(body_html, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"[WARN] Email send failed: {e}")
        return False


def _send_license_email(customer_email, result):
    """给客户发 License Key 邮件 + 给自己发通知"""
    plan_label = result.get("plan_label", result["plan"])
    plan_en = PLANS.get(result["plan"], {}).get("en", result["plan"])
    exp_str = result.get("expires_date", "")

    # ── 客户邮件 ──
    customer_body = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#6c5ce7;">🔑 Correctover License Key</h2>
<p>感谢购买 Correctover！以下是您的授权信息：</p>
<table style="border:1px solid #ddd;border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Plan</td>
    <td style="padding:8px;border:1px solid #ddd;">{plan_label} / {plan_en}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">License Key</td>
    <td style="padding:8px;border:1px solid #ddd;font-family:monospace;font-size:12px;word-break:break-all;">{result['key']}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Valid Until</td>
    <td style="padding:8px;border:1px solid #ddd;">{exp_str}</td></tr>
</table>
<h3 style="color:#6c5ce7;">Getting Started</h3>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">pip install correctover</pre>
<p>Option 1 — Environment Variable:</p>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">export CORRECTOVER_LICENSE_KEY={result['key']}</pre>
<p>Option 2 — In Code:</p>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">from correctover import run
engine = run(license_key="{result['key']}")</pre>
<p>Docs: <a href="https://github.com/hhhfs9s7y9-code/correctover">GitHub</a></p>
<p style="color:#888;font-size:12px;">After expiration, SDK automatically downgrades to Community Edition (L1+L2, 3 providers).</p>
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#888;font-size:12px;">Correctover Team — <a href="https://correctover.com">correctover.com</a></p>
</body></html>"""
    _send_email(customer_email, f"Your Correctover {plan_en} License Key", customer_body)

    # ── 管理员通知邮件 ──
    notify_body = f"""<html><body>
<h3>📋 新 License 签发通知</h3>
<table style="border:1px solid #ddd;border-collapse:collapse;">
<tr><td style="padding:4px 8px;font-weight:bold;">客户邮箱</td><td style="padding:4px 8px;">{customer_email}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">方案</td><td style="padding:4px 8px;">{plan_label}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">License Key</td><td style="padding:4px 8px;font-family:monospace;font-size:11px;word-break:break-all;">{result['key']}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">到期</td><td style="padding:4px 8px;">{exp_str}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">流水号</td><td style="padding:4px 8px;">{result['issue_id']}</td></tr>
</table>
</body></html>"""
    _send_email(NOTIFY_EMAIL, f"[CV] 新签发 {plan_label} — {customer_email}", notify_body)


def _send_renew_email(customer_email, result):
    """续费通知邮件"""
    plan_label = result.get("plan_label", result["plan"])
    exp_str = result.get("expires_date", "")
    body = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#6c5ce7;">🔄 Correctover License 续费成功</h2>
<p>您的 Correctover License 已成功续费：</p>
<table style="border:1px solid #ddd;border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">方案</td>
    <td style="padding:8px;border:1px solid #ddd;">{plan_label}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">新到期日</td>
    <td style="padding:8px;border:1px solid #ddd;">{exp_str}</td></tr>
</table>
<p>SDK 会自动更新，无需更换 License Key。</p>
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#888;font-size:12px;">Correctover Team — correctover.com</p>
</body></html>"""
    _send_email(customer_email, f"Correctover {plan_label} 续费成功", body)
    _send_email(NOTIFY_EMAIL, f"[CV] 续费 {plan_label} — {customer_email}", f"<p>客户 {customer_email} 已续费 {plan_label}，新到期日 {exp_str}</p>")


def _send_expired_email(customer_email, plan_label):
    """过期通知邮件"""
    body = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#e17055;">⚠️ Correctover License 已过期</h2>
<p>您的 Correctover {plan_label} License 已过期。</p>
<p>SDK 已自动降级为 Community Edition（L1+L2，3 providers）。</p>
<p>如需续费，请前往 <a href="https://market.aliyun.com">阿里云市场</a> 续订。</p>
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#888;font-size:12px;">Correctover Team — correctover.com</p>
</body></html>"""
    _send_email(customer_email, f"Correctover {plan_label} License 已过期", body)


# ── SPI Token 验证 ──────────────────────────────────────────────

def _verify_spi_token(params):
    """验证阿里云市场 SPI 的安全令牌"""
    if not MKT_SPI_KEY:
        print("[WARN] MKT_SPI_KEY not configured, skip SPI token verification")
        return True  # 未配置密钥时跳过验证（仅用于调试）

    received_token = params.get("token", "")
    if not received_token:
        return False

    # 排除 token，对其余参数按 key 字典排序
    filtered = {k: v for k, v in params.items() if k != "token"}
    sorted_keys = sorted(filtered.keys())

    # 拼接: key1=value1&key2=value2&key=密钥
    parts = [f"{k}={filtered[k]}" for k in sorted_keys]
    parts.append(f"key={MKT_SPI_KEY}")
    sign_str = "&".join(parts)

    # MD5
    expected_token = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
    return expected_token == received_token


# ── Core License ─────────────────────────────────────────────────

def _hmac_sign(payload_str):
    return hmac_mod.new(HMAC_SECRET, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

def issue_key(plan, customer, days=None, note="", mkt_instance_id=None, mkt_order_id=None):
    if plan not in PLANS:
        return {"error": f"Invalid plan: {plan}"}
    cfg = PLANS[plan]
    if days is None:
        days = cfg["days"]
    now = int(time.time())
    expires = now + days * 86400 if plan != "lifetime" else 0
    payload = {"p": plan, "e": expires, "c": customer, "i": str(uuid.uuid4())[:8]}
    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = _hmac_sign(payload_str)
    combined = f"{payload_str}.{sig}"
    encoded = base64.urlsafe_b64encode(combined.encode("utf-8")).rstrip(b"=").decode("utf-8")
    key = f"{cfg['prefix']}{encoded}"

    entry = {
        "issue_id": payload["i"],
        "plan": plan,
        "customer": customer,
        "days": days,
        "issued_at": now,
        "expires_at": expires,
        "key": key,
        "note": note,
    }
    if mkt_instance_id:
        entry["mkt_instance_id"] = mkt_instance_id
    if mkt_order_id:
        entry["mkt_order_id"] = mkt_order_id

    _db_append(entry)
    exp_str = "永久" if plan == "lifetime" else time.strftime("%Y-%m-%d", time.gmtime(expires))
    result = {
        "key": key, "plan": plan, "plan_label": cfg["label"],
        "customer": customer, "expires_at": expires,
        "expires_date": exp_str, "issue_id": payload["i"],
    }
    if mkt_instance_id:
        result["mkt_instance_id"] = mkt_instance_id
    return result

def verify_key(key, device_id=None):
    if not key or not isinstance(key, str):
        return {"valid": False, "plan": "community", "message": "No key provided"}
    key = key.strip()
    prefix_map = [("CV-PRO-","pro"),("CV-ENT-","enterprise"),("CV-TRL-","trial"),("CV-MON-","monthly"),("CV-ANN-","annual"),("CV-LTM-","lifetime"),("NB-PRO-","pro"),("NB-ENT-","enterprise"),("NB-TRL-","trial"),("NB-MON-","monthly"),("NB-ANN-","annual"),("NB-LTM-","lifetime")]
    declared_plan = None
    encoded = None
    for p, n in prefix_map:
        if key.startswith(p):
            declared_plan = n
            encoded = key[len(p):]
            break
    if not declared_plan:
        return {"valid": False, "plan": "community", "message": "Invalid key prefix"}
    try:
        decoded = base64.urlsafe_b64decode(encoded + "==").decode("utf-8")
    except:
        return {"valid": False, "plan": "community", "message": "Invalid key data"}
    if "." not in decoded:
        return {"valid": False, "plan": "community", "message": "Invalid key format"}
    payload_str, sig_hex = decoded.rsplit(".", 1)
    try:
        payload = json.loads(payload_str)
    except:
        return {"valid": False, "plan": "community", "message": "Corrupted payload"}
    for f in ("p","e","c"):
        if f not in payload:
            return {"valid": False, "plan": "community", "message": f"Missing field {f}"}
    if not hmac_mod.compare_digest(sig_hex, _hmac_sign(payload_str)):
        return {"valid": False, "plan": "community", "message": "Invalid signature"}
    if payload["p"] != declared_plan:
        return {"valid": False, "plan": "community", "message": "Plan mismatch"}
    if _is_revoked(payload["i"]):
        return {"valid": False, "plan": "community", "message": "Key revoked"}
    if payload["e"] != 0 and int(time.time()) > payload["e"]:
        return {"valid": False, "plan": "community", "customer": payload.get("c",""), "message": "Expired"}

    result = {"valid": True, "plan": payload["p"], "customer": payload.get("c",""), "expires_at": payload["e"], "issue_id": payload.get("i",""), "message": f"Valid {payload['p']} license"}

    # device_id 设备绑定检查
    if device_id:
        db = _db_load("issued.json")
        for e in db:
            if e.get("issue_id") == payload.get("i", ""):
                bound_device = e.get("device_id")
                if bound_device and bound_device != device_id:
                    return {"valid": False, "plan": "community", "customer": payload.get("c",""), "message": "Device mismatch: key is bound to another device"}
                result["device_id"] = bound_device or device_id
                break

    return result


# ── SPI Handlers ─────────────────────────────────────────────────

def _spi_create_instance(params):
    """云市场新购 → 签发 License + 发邮件"""
    if not _verify_spi_token(params):
        return {"instanceId": "0"}, False

    action = params.get("action", "")
    if action != "createInstance":
        return {"instanceId": "0"}, False

    ali_uid = params.get("aliUid", "")
    order_biz_id = params.get("orderBizId", "")
    order_id = params.get("orderId", "")
    sku_id = params.get("skuId", "")
    email = params.get("email", "")
    mobile = params.get("mobile", "")
    expired_on = params.get("expiredOn", "")
    is_trial = params.get("trial", "false").lower() == "true"

    # SKU → Plan 映射
    plan = MKT_SKU_MAP.get(sku_id)
    if not plan:
        # 回退：根据 trial 标记判断
        plan = "trial" if is_trial else "annual"

    if plan not in PLANS:
        plan = "annual"

    # 客户标识优先用 email，其次 aliUid
    customer = email or f"aliyun-{ali_uid}"

    # 幂等检查：是否已处理过此 orderBizId
    existing = _db_find_instance(order_biz_id)
    if existing:
        # 已存在，返回已有 instanceId
        return {
            "instanceId": order_biz_id,
            "appInfo": {
                "frontEndUrl": "https://correctover.com",
                "adminUrl": "https://correctover.com",
                "username": customer,
                "licenseId": existing.get("key", ""),
                "licenseValidPeriod": existing.get("expires_date", ""),
            },
            "info": {
                "licenseKey": existing.get("key", ""),
                "instructions": "pip install correctover && export CORRECTOVER_LICENSE_KEY=" + existing.get("key", ""),
            }
        }, True

    # 签发新 Key
    result = issue_key(plan, customer, note=f"Aliyun Market order={order_id}", mkt_instance_id=order_biz_id, mkt_order_id=order_id)

    if "error" in result:
        return {"instanceId": "0"}, False

    # 发邮件
    if email:
        _send_license_email(email, result)

    return {
        "instanceId": order_biz_id,
        "appInfo": {
            "frontEndUrl": "https://correctover.com",
            "adminUrl": "https://correctover.com",
            "username": customer,
            "licenseId": result["key"],
            "licenseValidPeriod": result["expires_date"],
        },
        "info": {
            "licenseKey": result["key"],
            "instructions": "pip install correctover && export CORRECTOVER_LICENSE_KEY=" + result["key"],
        }
    }, True


def _spi_renew_instance(params):
    """云市场续费 → 更新到期日 + 发邮件"""
    if not _verify_spi_token(params):
        return {"success": "false"}, False

    instance_id = params.get("instanceId", "")
    expired_on = params.get("expiredOn", "")

    if not instance_id:
        return {"success": "false"}, False

    # 查找实例
    record = _db_find_instance(instance_id)
    if not record:
        return {"success": "false"}, False

    # 解析新到期时间
    try:
        new_exp = int(time.mktime(time.strptime(expired_on, "%Y-%m-%d %H:%M:%S")))
    except:
        try:
            new_exp = int(time.mktime(time.strptime(expired_on, "%Y-%m-%d")))
        except:
            return {"success": "false"}, False

    # 重新签发 Key（更新过期时间）
    old_key = record.get("key", "")
    old_customer = record.get("customer", "")
    old_plan = record.get("plan", "annual")

    # 签发新 Key（续费本质上是新的 key）
    result = issue_key(old_plan, old_customer, note=f"Renew from {instance_id}", mkt_instance_id=instance_id, mkt_order_id=record.get("mkt_order_id", ""))

    if "error" in result:
        return {"success": "false"}, False

    # 更新旧记录状态
    _db_update_instance(instance_id, {"status": "renewed", "new_key": result["key"], "new_expires_at": result["expires_at"]})

    # 发续费邮件
    if old_customer and "@" in old_customer:
        _send_renew_email(old_customer, result)

    return {"success": "true"}, True


def _spi_expired_instance(params):
    """云市场过期 → 冻结（标记 revoked）+ 发邮件"""
    if not _verify_spi_token(params):
        return {"success": "false"}, False

    instance_id = params.get("instanceId", "")

    record = _db_find_instance(instance_id)
    if not record:
        return {"success": "true"}, True  # 没找到也算成功（幂等）

    # 标记过期（不吊销 Key，SDK 会自动根据时间降级）
    _db_update_instance(instance_id, {"status": "expired"})

    # 发过期邮件
    customer = record.get("customer", "")
    plan = record.get("plan", "annual")
    plan_label = PLANS.get(plan, {}).get("label", plan)
    if customer and "@" in customer:
        _send_expired_email(customer, plan_label)

    return {"success": "true"}, True


def _spi_release_instance(params):
    """云市场释放 → 吊销 Key"""
    if not _verify_spi_token(params):
        return {"success": "false"}, False

    instance_id = params.get("instanceId", "")

    record = _db_find_instance(instance_id)
    if not record:
        return {"success": "true"}, True

    # 吊销 Key
    issue_id = record.get("issue_id", "")
    if issue_id:
        revoked = _db_load("revoked.json")
        if issue_id not in revoked:
            revoked.append(issue_id)
            _db_save("revoked.json", revoked)

    _db_update_instance(instance_id, {"status": "released"})

    return {"success": "true"}, True


def _spi_bind_domain(params):
    """云市场绑定域名（Correctover SaaS 不需要，直接返回成功）"""
    if not _verify_spi_token(params):
        return {"success": "false"}, False
    return {"success": "true"}, True


def _spi_verify(params):
    """云市场免登验证"""
    if not _verify_spi_token(params):
        return {"success": "false"}, False
    return {"success": "true"}, True


# ── 虎皮椒支付回调 ──────────────────────────────────────────────

def _xunhu_verify_hash(params):
    """验证虎皮椒回调签名"""
    if not XUNHU_SECRET:
        print("[WARN] XUNHU_SECRET not configured, skip hash verification")
        return True

    received_hash = params.get("hash", "")
    if not received_hash:
        return False

    # 按 key 字典序排序，跳过 hash 和空值，拼接 key=value&... + SECRET
    filtered = {}
    for k, v in params.items():
        if k == "hash" or v is None or v == "":
            continue
        filtered[k] = v

    sorted_keys = sorted(filtered.keys())
    string_a = "&".join(f"{k}={filtered[k]}" for k in sorted_keys)
    string_sign_temp = string_a + XUNHU_SECRET
    expected_hash = hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest()

    return expected_hash == received_hash


def _xunhu_notify(params):
    """虎皮椒支付成功回调处理"""
    if not _xunhu_verify_hash(params):
        return "hash verify failed", False

    status = params.get("status", "")
    if status != "OD":
        # OD=已支付, CD=已退款, RD=退款中, UD=退款失败
        return "success", True  # 非支付成功状态，直接返回 success 不处理

    trade_order_id = params.get("trade_order_id", "")
    total_fee = params.get("total_fee", "")
    order_title = params.get("order_title", "")
    attach = params.get("attach", "")  # 自定义备注，可用于传 plan

    # 根据 attach 或 order_title 决定 plan
    plan = "annual"  # 默认
    customer_email = ""
    if attach:
        # attach 格式: "plan" 或 "plan:email"
        if ":" in attach:
            parts = attach.split(":", 1)
            plan = parts[0] if parts[0] in PLANS else "annual"
            customer_email = parts[1]
        elif attach in PLANS:
            plan = attach
    if plan == "annual":  # 如果 attach 没匹配到，尝试从标题匹配
        title_lower = (order_title or "").lower()
        if "trial" in title_lower or "试用" in title_lower:
            plan = "trial"
        elif "month" in title_lower or "月" in title_lower:
            plan = "monthly"
        elif "lifetime" in title_lower or "永久" in title_lower:
            plan = "lifetime"

    # 幂等检查
    existing = None
    db = _db_load("issued.json")
    for e in db:
        if e.get("xunhu_order_id") == trade_order_id:
            existing = e
            break

    if existing:
        return "success", True  # 已处理过

    # 客户标识
    customer = customer_email or f"xunhu-{trade_order_id}"

    # 签发 Key
    result = issue_key(plan, customer, note=f"XunhuPay order={trade_order_id} fee={total_fee}")

    if "error" in result:
        return "fail", False

    # 更新记录加上虎皮椒订单号
    _db_update_instance(None, {})  # 不需要更新 instance
    # 直接在 append 时已包含，我们额外更新 xunhu_order_id
    db2 = _db_load("issued.json")
    for e in db2:
        if e.get("issue_id") == result["issue_id"]:
            e["xunhu_order_id"] = trade_order_id
            e["payment_amount"] = total_fee
            break
    _db_save("issued.json", db2)

    # 发邮件
    if customer_email and "@" in customer_email:
        # 有客户邮箱，直接发给客户
        _send_license_email(customer_email, result)
        _send_email(NOTIFY_EMAIL, f"[CV] 💰 虎皮椒收款 ¥{total_fee} — {result['plan_label']}",
            f"<p>客户 {customer_email} 付款 ¥{total_fee}，已自动签发并邮件发送。</p>"
            f"<p>方案: {result['plan_label']} | Key: {result['key']}</p>")
    else:
        # 没有客户邮箱，只通知管理员
        notify_body = f"""<html><body>
<h3>💰 虎皮椒支付成功 — 需手动发送 License Key</h3>
<table style="border:1px solid #ddd;border-collapse:collapse;">
<tr><td style="padding:4px 8px;font-weight:bold;">订单号</td><td style="padding:4px 8px;">{trade_order_id}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">金额</td><td style="padding:4px 8px;">¥{total_fee}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">方案</td><td style="padding:4px 8px;">{result['plan_label']}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">License Key</td><td style="padding:4px 8px;font-family:monospace;font-size:11px;word-break:break-all;">{result['key']}</td></tr>
<tr><td style="padding:4px 8px;font-weight:bold;">到期</td><td style="padding:4px 8px;">{result['expires_date']}</td></tr>
</table>
<p>⚠️ 虎皮椒回调无客户邮箱，请手动发送 License Key 给客户。</p>
</body></html>"""
        _send_email(NOTIFY_EMAIL, f"[CV] 💰 虎皮椒收款 ¥{total_fee} — {result['plan_label']}", notify_body)

    return "success", True


# ── IMAP 邮件自动回复 ──────────────────────────────────────────

def _check_and_reply_emails():
    """检查收件箱，对含关键词的邮件自动签发 Key 并回复"""
    import imaplib
    import email
    from email.header import decode_header
    from email.utils import parseaddr

    results = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select('INBOX')

        # 搜索未读邮件
        status, data = mail.search(None, 'UNSEEN')
        if status != 'OK':
            mail.logout()
            return {"checked": 0, "replied": 0, "error": "search failed"}

        msg_ids = data[0].split()
        if not msg_ids:
            mail.logout()
            return {"checked": 0, "replied": 0, "messages": []}

        replied = 0
        for mid in msg_ids[-20:]:  # 最多处理20封，防超时
            try:
                status, msg_data = mail.fetch(mid, '(RFC822)')
                if status != 'OK':
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # 解码主题
                subject = ""
                for part, charset in decode_header(msg.get("Subject", "")):
                    if isinstance(part, bytes):
                        subject += part.decode(charset or "utf-8", errors="ignore")
                    else:
                        subject += part

                # 解码发件人
                from_name, from_addr = parseaddr(msg.get("From", ""))
                for part, charset in decode_header(from_name):
                    if isinstance(part, bytes):
                        from_name = part.decode(charset or "utf-8", errors="ignore")
                    else:
                        from_name += part

                # 提取正文
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or "utf-8"
                                body_text += payload.decode(charset, errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        body_text = payload.decode(charset, errors="ignore")

                # 检查是否匹配关键词
                search_text = (subject + " " + body_text).lower()
                matched = any(kw in search_text for kw in IMAP_KEYWORDS)

                if not matched:
                    results.append({"from": from_addr, "subject": subject, "action": "skipped"})
                    continue

                # 排除自己发的邮件，防死循环
                if from_addr.lower() == IMAP_USER.lower():
                    results.append({"from": from_addr, "subject": subject, "action": "skipped_self"})
                    continue

                # 根据邮件内容决定套餐
                plan = IMAP_DEFAULT_PLAN  # 默认试用版
                text_lower = search_text
                if "annual" in text_lower or "年" in text_lower or "year" in text_lower:
                    plan = "annual"
                elif "monthly" in text_lower or "月" in text_lower or "month" in text_lower:
                    plan = "monthly"
                elif "lifetime" in text_lower or "永久" in text_lower:
                    plan = "lifetime"

                # 签发 Key
                result = issue_key(plan, from_addr, note=f"Email auto-reply from {from_addr}")

                if "error" in result:
                    results.append({"from": from_addr, "subject": subject, "action": "error", "error": result["error"]})
                    continue

                # 构建回复邮件
                plan_label = result["plan_label"]
                plan_en = PLANS.get(plan, {}).get("en", plan)
                exp_str = result["expires_date"]

                reply_body = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
<p>{from_name or '您好'}，</p>
<p>感谢您对 Correctover 的关注！以下是您的授权信息：</p>
<table style="border:1px solid #ddd;border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Plan</td>
    <td style="padding:8px;border:1px solid #ddd;">{plan_label} / {plan_en}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">License Key</td>
    <td style="padding:8px;border:1px solid #ddd;font-family:monospace;font-size:12px;word-break:break-all;">{result['key']}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">Valid Until</td>
    <td style="padding:8px;border:1px solid #ddd;">{exp_str}</td></tr>
</table>
<h3 style="color:#6c5ce7;">Getting Started</h3>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">pip install correctover</pre>
<p>Option 1 — Environment Variable:</p>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">export CORRECTOVER_LICENSE_KEY={result['key']}</pre>
<p>Option 2 — In Code:</p>
<pre style="background:#f5f5f5;padding:12px;border-radius:4px;">from correctover import run
engine = run(license_key="{result['key']}")</pre>
<p>Docs: <a href="https://github.com/hhhfs9s7y9-code/correctover">GitHub</a> | <a href="https://correctover.com">correctover.com</a></p>
<p style="color:#888;font-size:12px;">到期后 SDK 自动降级为 Community 版。如需升级请回复此邮件。</p>
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#888;font-size:12px;">Correctover Team — 此邮件由系统自动回复</p>
</body></html>"""

                # 发送回复
                reply_subject = f"Re: {subject}"
                ok = _send_email(from_addr, reply_subject, reply_body)

                # 同时通知管理员
                _send_email(NOTIFY_EMAIL, f"[CV] 📧 邮件自动签发 {plan_label} → {from_addr}",
                    f"<p>收到来自 {from_name} &lt;{from_addr}&gt; 的邮件，已自动签发：</p>"
                    f"<p>主题: {subject}</p>"
                    f"<p>套餐: {plan_label}</p>"
                    f"<p>Key: {result['key']}</p>")

                # 标记为已读
                mail.store(mid, '+FLAGS', '\\Seen')

                results.append({
                    "from": from_addr,
                    "subject": subject,
                    "action": "replied",
                    "plan": plan,
                    "key": result["key"],
                    "email_sent": ok,
                })
                replied += 1

            except Exception as e:
                results.append({"action": "error", "error": str(e)})
                continue

        mail.logout()
    except Exception as e:
        return {"checked": len(msg_ids) if 'msg_ids' in dir() else 0, "replied": replied if 'replied' in dir() else 0, "error": str(e)}

    return {"checked": len(msg_ids), "replied": replied, "messages": results}


# ── HTTP Handler ─────────────────────────────────────────────────

def handler(environ, start_response):
    """FC HTTP 触发器入口"""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")

    # 解析 query string（SPI 用 GET 参数）
    query_string = environ.get("QUERY_STRING", "")
    get_params = {}
    if query_string:
        for pair in query_string.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                get_params[k] = v

    # 读取 POST body（保存原始数据用于 form 解析）
    raw_body = b""
    try:
        length = int(environ.get("CONTENT_LENGTH", 0))
        if length > 0:
            raw_body = environ["wsgi.input"].read(length)
            body = json.loads(raw_body)
        else:
            body = {}
    except:
        body = {}

    # ── SPI 路由（云市场 GET 请求，action 参数区分） ──
    action = get_params.get("action", "")
    if action and path in ("/spi", "/api/v1/spi", "/"):
        spi_handlers = {
            "createInstance":  _spi_create_instance,
            "renewInstance":   _spi_renew_instance,
            "expiredInstance": _spi_expired_instance,
            "releaseInstance": _spi_release_instance,
            "bindDomain":      _spi_bind_domain,
            "verify":          _spi_verify,
        }
        handler_fn = spi_handlers.get(action)
        if handler_fn:
            result, ok = handler_fn(get_params)
            status = "200 OK"
            body_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
            start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body_bytes)))])
            return [body_bytes]

    # ── License API 路由 ──
    if path == "/health":
        smtp_ok = "✅" if SMTP_PASS else "❌"
        mkt_ok = "✅" if MKT_SPI_KEY else "❌"
        result = {
            "status": "ok", "time": int(time.time()),
            "service": "correctover-license-api",
            "smtp": smtp_ok,
            "mkt_spi": mkt_ok,
            "sku_map": len(MKT_SKU_MAP),
        }
        status = "200 OK"
    elif path == "/api/v1/license/verify" and method == "POST":
        result = verify_key(body.get("key", ""), device_id=body.get("device_id"))
        status = "200 OK"
    elif path == "/api/v1/license/activate" and method == "POST":
        key = body.get("key", "")
        device_id = body.get("device_id", "")
        device_info = body.get("device_info", "")
        plan = body.get("plan", "")
        customer = body.get("customer", "")
        if not key or not device_id:
            result = {"error": "key and device_id required"}
            status = "400 Bad Request"
        else:
            verify_result = verify_key(key)
            if not verify_result.get("valid"):
                result = {"error": verify_result.get("message", "Invalid key")}
                status = "400 Bad Request"
            else:
                issue_id = verify_result.get("issue_id", "")
                db = _db_load("issued.json")
                record = None
                for e in db:
                    if e.get("issue_id") == issue_id:
                        record = e
                        break
                if not record:
                    result = {"error": "License record not found"}
                    status = "404 Not Found"
                else:
                    bound_device = record.get("device_id")
                    if bound_device and bound_device != device_id:
                        result = {"error": "Key already bound to another device", "bound_device_id": bound_device}
                        status = "409 Conflict"
                    else:
                        # 绑定当前设备
                        record["device_id"] = device_id
                        if device_info:
                            record["device_info"] = device_info
                        if not record.get("activated_at"):
                            record["activated_at"] = int(time.time())
                        _db_save("issued.json", db)
                        result = {"activated": True, "device_id": device_id}
                        status = "200 OK"
    elif path == "/api/v1/license/unbind" and method == "POST":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            key = body.get("key", "")
            if not key:
                result = {"error": "key required"}
                status = "400 Bad Request"
            else:
                verify_result = verify_key(key)
                if not verify_result.get("valid"):
                    result = {"error": verify_result.get("message", "Invalid key")}
                    status = "400 Bad Request"
                else:
                    issue_id = verify_result.get("issue_id", "")
                    db = _db_load("issued.json")
                    record = None
                    for e in db:
                        if e.get("issue_id") == issue_id:
                            record = e
                            break
                    if not record:
                        result = {"error": "License record not found"}
                        status = "404 Not Found"
                    else:
                        now_ts = int(time.time())
                        unbind_count = record.get("unbind_count", 0)
                        last_unbind_at = record.get("last_unbind_at", 0)
                        # 每月最多解绑1次
                        if last_unbind_at > 0:
                            last_month = time.strftime("%Y-%m", time.gmtime(last_unbind_at))
                            cur_month = time.strftime("%Y-%m", time.gmtime(now_ts))
                            if last_month == cur_month:
                                result = {"error": "Monthly unbind limit reached (max 1 per month)", "unbind_count": unbind_count, "last_unbind_at": last_unbind_at}
                                status = "429 Too Many Requests"
                                # skip to response
                                record = None
                        if record is not None:
                            record["device_id"] = ""
                            record["unbind_count"] = unbind_count + 1
                            record["last_unbind_at"] = now_ts
                            _db_save("issued.json", db)
                            result = {"unbound": True, "unbind_count": unbind_count + 1}
                            status = "200 OK"
    elif path == "/api/v1/license/issue" and method == "POST":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            plan = body.get("plan", "annual")
            customer = body.get("customer", "unknown")
            days = body.get("days")
            note = body.get("note", "")
            send_email = body.get("send_email", False)
            customer_email = body.get("email", customer)
            result = issue_key(plan, customer, days, note)
            if "error" not in result and send_email:
                _send_license_email(customer_email, result)
            status = "200 OK" if "error" not in result else "400 Bad Request"
    elif path == "/api/v1/license/payhip" and method == "POST":
        email = body.get("email", body.get("customer_email", ""))
        product_name = body.get("product_name", "")
        order_id = body.get("order_id", str(uuid.uuid4())[:8])
        product_id = body.get("product_id", "")
        plan = "annual"
        nl = product_name.lower()
        if "trial" in nl: plan = "trial"
        elif "month" in nl: plan = "monthly"
        elif "lifetime" in nl: plan = "lifetime"
        elif "annual" in nl or "year" in nl: plan = "annual"
        pid_map = os.environ.get("NB_PAYHIP_PLAN_MAP", "")
        if pid_map:
            for mapping in pid_map.split(","):
                if ":" in mapping:
                    pid, p = mapping.split(":", 1)
                    if product_id == pid:
                        plan = p
                        break
        if not email: email = f"order-{order_id}@unknown"
        result = issue_key(plan, email, note=f"Payhip {order_id}")
        if "error" not in result:
            _send_license_email(email, result)
            result = {"license_key": result["key"], "plan": result["plan"], "customer": result["customer"], "expires_at": result["expires_at"]}
        status = "200 OK" if "error" not in result else "400 Bad Request"
    elif path == "/api/v1/license/stats" and method == "GET":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            db = _db_load("issued.json")
            now = int(time.time())
            plans = {}
            active = expired = 0
            for e in db:
                p = e.get("plan", "unknown")
                plans[p] = plans.get(p, 0) + 1
                if e.get("expires_at") == 0 or e.get("expires_at", 0) > now:
                    active += 1
                else:
                    expired += 1
            result = {"total": len(db), "plans": plans, "active": active, "expired": expired}
            status = "200 OK"
    elif path == "/api/v1/license/test-email" and method == "POST":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            to = body.get("to", NOTIFY_EMAIL)
            db = _db_load("issued.json")
            now = int(time.time())
            total_keys = len(db)
            active_keys = sum(1 for e in db if e.get("expires_at") == 0 or e.get("expires_at", 0) > now)
            plan_counts = {}
            for e in db:
                p = e.get("plan", "unknown")
                plan_counts[p] = plan_counts.get(p, 0) + 1
            plans_summary = ", ".join(f"{p}={c}" for p, c in sorted(plan_counts.items()))
            ok = _send_email(to, f"✅ Correctover 邮件系统测试 — {total_keys} Keys", f"""<html><body style="font-family:Arial,sans-serif;">
<h2 style="color:#6c5ce7;">✅ 邮件系统 — 实时数据测试</h2>
<p>以下数据直接从 OSS 数据库读取，全部为 <strong>动态真实数据</strong>：</p>
<table style="border:1px solid #ddd;border-collapse:collapse;width:100%;">
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">数据库时间</td>
    <td style="padding:8px;border:1px solid #ddd;">{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(now))}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">总签发 Key 数</td>
    <td style="padding:8px;border:1px solid #ddd;">{total_keys}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">当前有效</td>
    <td style="padding:8px;border:1px solid #ddd;">{active_keys}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">按套餐分布</td>
    <td style="padding:8px;border:1px solid #ddd;">{plans_summary}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">SMTP 状态</td>
    <td style="padding:8px;border:1px solid #ddd;">{'✅ 已配置' if SMTP_PASS else '❌ 未配置'}</td></tr>
<tr><td style="padding:8px;border:1px solid #ddd;font-weight:bold;">接收时间</td>
    <td style="padding:8px;border:1px solid #ddd;">{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</td></tr>
</table>
<p style="color:#888;font-size:12px;margin-top:16px;">此邮件内容全部来自实时数据库查询，非静态模板。</p>
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#888;font-size:12px;">Correctover License System — correctover.com</p>
</body></html>""")
            result = {"sent": ok, "to": to, "smtp_configured": bool(SMTP_PASS), "total_keys": total_keys, "active_keys": active_keys}
            status = "200 OK"
    elif path == "/api/v1/license/resend" and method == "POST":
        """重新发送 License Key 邮件 — 需 admin token"""
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            issue_id = body.get("issue_id", "")
            email = body.get("email", "")
            if not issue_id:
                result = {"error": "issue_id required"}
                status = "400 Bad Request"
            elif not email or "@" not in email:
                result = {"error": "valid email required"}
                status = "400 Bad Request"
            else:
                # 查找 license 记录
                db = _db_load("issued.json")
                record = None
                for e in db:
                    if e.get("issue_id") == issue_id:
                        record = e
                        break
                if not record:
                    result = {"error": "license not found"}
                    status = "404 Not Found"
                else:
                    plan = record.get("plan", "annual")
                    exp_str = "永久" if record.get("expires_at") == 0 else time.strftime("%Y-%m-%d", time.gmtime(record.get("expires_at", 0)))
                    result_data = {
                        "key": record.get("key", ""),
                        "plan": plan,
                        "plan_label": PLANS.get(plan, {}).get("label", plan),
                        "customer": record.get("customer", ""),
                        "expires_at": record.get("expires_at", 0),
                        "expires_date": exp_str,
                        "issue_id": issue_id,
                    }
                    _send_license_email(email, result_data)
                    # 更新记录中的邮箱
                    for e in db:
                        if e.get("issue_id") == issue_id:
                            e["email"] = email
                            break
                    _db_save("issued.json", db)
                    result = {"sent": True, "to": email, "key": record.get("key", "")}
                    status = "200 OK"
    elif path == "/spi" and method == "GET":
        """SPI 调试 — 列出支持的 action"""
        result = {
            "service": "correctover-spi",
            "actions": ["createInstance", "renewInstance", "expiredInstance", "releaseInstance", "bindDomain", "verify"],
            "spi_key_configured": bool(MKT_SPI_KEY),
            "sku_map": MKT_SKU_MAP,
        }
        status = "200 OK"
    elif path == "/api/v1/payment/create" and method == "POST":
        """创建虎皮椒支付订单 — 公开接口，无需 admin token"""
        plan = body.get("plan", "annual")
        email = body.get("email", "")
        if plan not in PLANS:
            result = {"error": "Invalid plan"}
            status = "400 Bad Request"
        elif plan == "trial":
            # 试用版免费，直接签发
            if not email or "@" not in email:
                result = {"error": "Email required for trial"}
                status = "400 Bad Request"
            else:
                res = issue_key("trial", email, note="Free trial")
                if "error" not in res:
                    _send_license_email(email, res)
                result = {"free": True, "plan": "trial", "key": res.get("key", ""), "email_sent": True}
                status = "200 OK"
        elif not XUNHU_APPID or not XUNHU_SECRET:
            result = {"error": "Payment not configured"}
            status = "503 Service Unavailable"
        else:
            # 构建虎皮椒支付请求
            import random
            cfg = PLANS[plan]
            trade_order_id = f"NB-{int(time.time())}-{random.randint(1000,9999)}"
            nonce_str = f"{random.randint(100000,999999)}"
            total_fee = str(cfg["price"])
            title = f"Correctover {cfg['label']} / {cfg['en']}"
            notify_url = f"https://license-api-neuralbridge-edouhcvhbo.cn-hangzhou.fcapp.run/api/v1/payment/xunhu"
            return_url = "https://correctover.com/buy.html?success=1"

            params = {
                "version": "1.1",
                "appid": XUNHU_APPID,
                "trade_order_id": trade_order_id,
                "total_fee": total_fee,
                "title": title,
                "time": str(int(time.time())),
                "notify_url": notify_url,
                "return_url": return_url,
                "nonce_str": nonce_str,
                "attach": plan,  # 传 plan 给回调
                "plugins": "neuralbridge",
            }
            if email:
                params["attach"] = f"{plan}:{email}"

            # 签名：参数按 key 字典排序，拼 key=value&... + SECRET，MD5
            sorted_keys = sorted(params.keys())
            string_a = "&".join(f"{k}={params[k]}" for k in sorted_keys)
            string_sign_temp = string_a + XUNHU_SECRET
            hash_val = hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest()
            params["hash"] = hash_val

            # 调虎皮椒 API
            try:
                import urllib.request
                req_data = json.dumps(params).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.xunhupay.com/payment/do.html",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    xunhu_resp = json.loads(resp.read().decode("utf-8"))

                if xunhu_resp.get("errcode") == 0:
                    result = {
                        "payment_url": xunhu_resp.get("url", ""),
                        "qr_url": xunhu_resp.get("url_qrcode", ""),
                        "order_id": trade_order_id,
                        "plan": plan,
                        "price": cfg["price"],
                    }
                    status = "200 OK"
                else:
                    result = {"error": xunhu_resp.get("errmsg", "Payment failed"), "detail": xunhu_resp}
                    status = "400 Bad Request"
            except Exception as e:
                result = {"error": f"Payment gateway error: {str(e)}"}
                status = "502 Bad Gateway"
    elif path == "/api/v1/payment/xunhu" and method == "POST":
        """虎皮椒支付成功回调"""
        content_type = environ.get("CONTENT_TYPE", "")
        if "application/json" in content_type:
            xunhu_params = body
        else:
            # form 表单格式
            try:
                raw = raw_body.decode("utf-8") if raw_body else ""
                xunhu_params = {}
                for pair in raw.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        xunhu_params[unquote_plus(k)] = unquote_plus(v)
            except:
                xunhu_params = body

        result_str, ok = _xunhu_notify(xunhu_params)
        status = "200 OK"
        # 虎皮椒要求返回纯文本 "success"
        body_bytes = result_str.encode("utf-8")
        start_response(status, [("Content-Type", "text/plain"), ("Content-Length", str(len(body_bytes)))])
        return [body_bytes]
    elif path == "/admin" and method == "GET":
        """管理后台页面"""
        html = _admin_page()
        body_bytes = html.encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body_bytes)))])
        return [body_bytes]
    elif path == "/api/v1/license/list" and method == "GET":
        """列出已签发的 license — 需 admin token"""
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            db = _db_load("issued.json")
            now = int(time.time())
            entries = []
            for e in db[-100:]:  # 最近100条
                exp = e.get("expires_at", 0)
                state = "active" if (exp == 0 or exp > now) else "expired"
                if e.get("status") == "revoked":
                    state = "revoked"
                entries.append({
                    "issue_id": e.get("issue_id", ""),
                    "plan": e.get("plan", ""),
                    "customer": e.get("customer", ""),
                    "key": e.get("key", ""),
                    "expires_at": exp,
                    "expires_date": "永久" if exp == 0 else time.strftime("%Y-%m-%d", time.gmtime(exp)) if exp else "",
                    "state": state,
                    "note": e.get("note", ""),
                })
            result = {"licenses": entries, "total": len(db)}
            status = "200 OK"
    elif path == "/api/v1/ping" and method == "POST":
        """SDK心跳 — 接收并存储遥测数据到OSS ping-db/"""
        try:
            data = body if body else {}
            bucket = _get_oss_bucket()
            now_str = time.strftime("%Y-%m-%d", time.gmtime())

            # 1. 写入当日心跳日志 (append模式)
            daily_key = f"ping-db/daily/{now_str}.jsonl"
            try:
                existing = bucket.get_object(daily_key).read().decode('utf-8')
            except Exception:
                existing = ""
            data["_received_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            data["_source_ip"] = environ.get("HTTP_X_FORWARDED_FOR", environ.get("REMOTE_ADDR", ""))
            existing += json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"
            bucket.put_object(daily_key, existing.encode('utf-8'))

            # 2. 更新用户档案 (按device_id)
            dev_id = data.get("dev", "")
            if dev_id:
                user_key = f"ping-db/users/{dev_id}.json"
                try:
                    profile = json.loads(bucket.get_object(user_key).read().decode('utf-8'))
                except Exception:
                    profile = {"device_id": dev_id, "first_seen": now_str, "pings": 0}
                profile.update({
                    "last_seen": now_str,
                    "last_ping_at": data["_received_at"],
                    "sdk_version": data.get("v", ""),
                    "python": data.get("py", ""),
                    "os": data.get("os", ""),
                    "plan": data.get("plan", "free"),
                    "pings": profile.get("pings", 0) + 1,
                    "total_calls": max(profile.get("total_calls", 0), data.get("calls", 0)),
                    "total_protections": max(profile.get("total_protections", 0), data.get("protects", 0)),
                })
                # 更新故障统计
                if data.get("faults"):
                    profile["faults"] = data["faults"]
                if data.get("last_fault"):
                    profile["last_fault"] = data["last_fault"]
                bucket.put_object(user_key, json.dumps(profile, ensure_ascii=False, indent=2).encode('utf-8'))

            result = {"ok": True}
            status = "200 OK"
        except Exception as e:
            import traceback
            result = {"ok": True, "_error": str(e), "_trace": traceback.format_exc()[-300:]}
            status = "200 OK"

    elif path == "/api/v1/telemetry" and method == "POST":
        """SDK遥测事件 — 接收并存储到OSS telemetry-db/"""
        try:
            data = body if body else {}
            events = data.get("events", [])
            if not events:
                result = {"ok": True, "received": 0}
                status = "200 OK"
            else:
                bucket = _get_oss_bucket()
                now_str = time.strftime("%Y-%m-%d", time.gmtime())
                tel_key = f"telemetry-db/daily/{now_str}.jsonl"
                try:
                    existing = bucket.get_object(tel_key).read().decode('utf-8')
                except Exception:
                    existing = ""
                for evt in events:
                    evt["_received_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    existing += json.dumps(evt, separators=(",", ":"), ensure_ascii=False) + "\n"
                bucket.put_object(tel_key, existing.encode('utf-8'))
                result = {"ok": True, "received": len(events)}
                status = "200 OK"
        except Exception as e:
            import traceback
            result = {"ok": True, "received": 0, "_error": str(e), "_trace": traceback.format_exc()[-300:]}
            status = "200 OK"

    elif path == "/api/v1/license/check-email" and method == "POST":
        """检查收件箱，自动签发+回复 — 需 admin token，可配定时触发器"""
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        if token != ADMIN_TOKEN:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            result = _check_and_reply_emails()
            status = "200 OK"
    # ── User API Routes ──
    elif path == "/api/v1/user/register" and method == "POST":
        email = body.get("email", "").strip().lower()
        pwd = body.get("pwd", "")
        plan = body.get("plan", "personal")
        if not email or "@" not in email:
            result = {"error": "请输入有效邮箱"}
            status = "400 Bad Request"
        elif not pwd or len(pwd) < 6:
            result = {"error": "密码至少6位"}
            status = "400 Bad Request"
        elif _db_find_user(email):
            result = {"error": "该邮箱已注册，请直接登录"}
            status = "409 Conflict"
        else:
            user = _db_upsert_user(email, {
                "pwd": _user_hash_password(pwd),
                "plan": plan,
                "balance": 0,
                "total_topup": 0,
                "tokens_used": 0,
                "calls_made": 0,
                "updated_at": int(time.time()),
            })
            token = _user_sign_token(email)
            result = {"ok": True, "token": token, "user": {"email": email, "plan": plan, "balance": 0}}
            status = "200 OK"

    elif path == "/api/v1/user/login" and method == "POST":
        email = body.get("email", "").strip().lower()
        pwd = body.get("pwd", "")
        if not email or not pwd:
            result = {"error": "请输入邮箱和密码"}
            status = "400 Bad Request"
        else:
            user = _db_find_user(email)
            if not user:
                result = {"error": "账户不存在，请先注册"}
                status = "404 Not Found"
            elif user.get("pwd") != _user_hash_password(pwd):
                result = {"error": "密码错误"}
                status = "401 Unauthorized"
            else:
                token = _user_sign_token(email)
                result = {"ok": True, "token": token, "user": {
                    "email": email,
                    "plan": user.get("plan", "personal"),
                    "balance": user.get("balance", 0),
                    "created_at": user.get("created_at", 0),
                }}
                status = "200 OK"

    elif path == "/api/v1/user/profile" and method == "GET":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        payload = _user_verify_token(token)
        if not payload:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            user = _db_find_user(payload.get("e", ""))
            if not user:
                result = {"error": "User not found"}
                status = "404 Not Found"
            else:
                result = {
                    "email": user["email"],
                    "plan": user.get("plan", "personal"),
                    "balance": user.get("balance", 0),
                    "created_at": user.get("created_at", 0),
                    "tokens_used": user.get("tokens_used", 0),
                    "calls_made": user.get("calls_made", 0),
                }
                status = "200 OK"

    elif path == "/api/v1/user/topup" and method == "POST":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        payload = _user_verify_token(token)
        if not payload:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            email = payload.get("e", "")
            amount = body.get("amount", 0)
            try:
                amount = int(amount)
            except:
                amount = 0
            if amount < 1:
                result = {"error": "充值金额至少 ¥1"}
                status = "400 Bad Request"
            elif not XUNHU_APPID or not XUNHU_SECRET:
                result = {"error": "Payment not configured"}
                status = "503 Service Unavailable"
            else:
                import random
                trade_order_id = f"CV-TOPUP-{int(time.time())}-{random.randint(1000,9999)}"
                nonce_str = f"{random.randint(100000,999999)}"
                notify_url = f"https://license-api-neuralbridge-edouhcvhbo.cn-hangzhou.fcapp.run/api/v1/user/topup/callback"
                return_url = "https://correctover.com/dashboard?topup=1"
                params = {
                    "version": "1.1", "appid": XUNHU_APPID,
                    "trade_order_id": trade_order_id, "total_fee": str(amount),
                    "title": f"Correctover 账户充值 ¥{amount}",
                    "time": str(int(time.time())),
                    "notify_url": notify_url, "return_url": return_url,
                    "nonce_str": nonce_str,
                    "attach": f"topup:{email}:{amount}",
                    "plugins": "neuralbridge",
                }
                sorted_keys = sorted(params.keys())
                string_a = "&".join(f"{k}={params[k]}" for k in sorted_keys)
                params["hash"] = hashlib.md5((string_a + XUNHU_SECRET).encode("utf-8")).hexdigest()
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        "https://api.xunhupay.com/payment/do.html",
                        data=json.dumps(params).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        xr = json.loads(resp.read().decode("utf-8"))
                    if xr.get("errcode") == 0:
                        result = {"payment_url": xr.get("url", ""), "qr_url": xr.get("url_qrcode", ""), "order_id": trade_order_id, "amount": amount}
                        status = "200 OK"
                    else:
                        result = {"error": xr.get("errmsg", "Payment failed")}
                        status = "400 Bad Request"
                except Exception as e:
                    result = {"error": f"Payment gateway error: {str(e)}"}
                    status = "502 Bad Gateway"

    elif path == "/api/v1/user/topup/callback" and method == "POST":
        content_type = environ.get("CONTENT_TYPE", "")
        if "application/json" in content_type:
            xunhu_params = body
        else:
            try:
                raw = raw_body.decode("utf-8") if raw_body else ""
                xunhu_params = {}
                for pair in raw.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        from urllib.parse import unquote_plus
                        xunhu_params[unquote_plus(k)] = unquote_plus(v)
            except:
                xunhu_params = body
        # Verify hash
        if XUNHU_SECRET:
            received_hash = xunhu_params.get("hash", "")
            filtered = {k: v for k, v in xunhu_params.items() if k != "hash" and v}
            sorted_keys = sorted(filtered.keys())
            string_a = "&".join(f"{k}={filtered[k]}" for k in sorted_keys)
            expected = hashlib.md5((string_a + XUNHU_SECRET).encode("utf-8")).hexdigest()
            if expected != received_hash:
                body_bytes = b"fail"
                start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body_bytes)))])
                return [body_bytes]
        status_val = xunhu_params.get("status", "")
        if status_val == "OD":
            attach = xunhu_params.get("attach", "")
            if attach and attach.startswith("topup:"):
                parts = attach.split(":", 3)
                if len(parts) >= 3:
                    email = parts[1]
                    try:
                        amount = float(parts[2])
                    except:
                        amount = 0
                    user = _db_find_user(email)
                    if user:
                        cur_bal = user.get("balance", 0)
                        _db_upsert_user(email, {"balance": cur_bal + amount, "total_topup": user.get("total_topup", 0) + amount, "updated_at": int(time.time())})
                        _send_email(email, "Correctover 充值成功 ✅",
                            f"<h2>充值成功</h2><p>您的 Correctover 账户已成功充值 ¥{amount:.2f}。</p><p>当前余额: ¥{cur_bal + amount:.2f}</p>")
        body_bytes = b"success"
        start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body_bytes)))])
        return [body_bytes]

    elif path == "/api/v1/user/dashboard" and method == "GET":
        token = _get_header(environ, "Authorization", "").replace("Bearer ", "")
        payload = _user_verify_token(token)
        if not payload:
            result = {"error": "Unauthorized"}
            status = "401 Unauthorized"
        else:
            email = payload.get("e", "")
            user = _db_find_user(email)
            if not user:
                result = {"error": "User not found"}
                status = "404 Not Found"
            else:
                # Aggregate telemetry data for wave charts
                now_ts = int(time.time())
                bucket = _get_oss_bucket()
                # Read last 14 days of ping data
                day_data = []
                for i in range(13, -1, -1):
                    day_str = time.strftime("%Y-%m-%d", time.gmtime(now_ts - i * 86400))
                    daily_key = f"ping-db/daily/{day_str}.jsonl"
                    try:
                        raw = bucket.get_object(daily_key).read().decode("utf-8")
                        lines = raw.strip().split("\n")
                        count = len(lines)
                        total_calls = 0
                        total_tokens = 0
                        total_protects = 0
                        faults = 0
                        for line in lines:
                            if not line.strip():
                                continue
                            try:
                                entry = json.loads(line)
                                total_calls += entry.get("calls", 0)
                                if entry.get("tokens"):
                                    total_tokens += entry.get("tokens", 0)
                                total_protects += entry.get("protects", 0)
                                faults += len(entry.get("faults", [])) if isinstance(entry.get("faults"), list) else (entry.get("faults", 0) if isinstance(entry.get("faults"), (int, float)) else 0)
                            except:
                                pass
                        day_data.append({"date": day_str, "calls": total_calls, "tokens": total_tokens, "heals": total_protects, "faults": faults, "pings": count})
                    except Exception:
                        day_data.append({"date": day_str, "calls": 0, "tokens": 0, "heals": 0, "faults": 0, "pings": 0})
                # Count total devices
                total_devices = 0
                try:
                    prefix_data = bucket.list_objects_v2(prefix="ping-db/users/", delimiter="/")
                except Exception:
                    prefix_data = []
                # Count by listing
                try:
                    for obj in oss2.ObjectIteratorV2(bucket, prefix="ping-db/users/"):
                        if obj.key.endswith(".json") and obj.key != "ping-db/users/":
                            total_devices += 1
                except:
                    pass
                result = {
                    "email": email,
                    "plan": user.get("plan", "personal"),
                    "balance": user.get("balance", 0),
                    "total_topup": user.get("total_topup", 0),
                    "created_at": user.get("created_at", 0),
                    "day_data": day_data,
                    "total_devices": total_devices,
                }
                status = "200 OK"

    else:
        result = {"error": "Not found", "path": path}
        status = "404 Not Found"

    body_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body_bytes)))])
    return [body_bytes]

def _get_header(environ, name, default=""):
    """从 WSGI environ 获取 header"""
    key = "HTTP_" + name.upper().replace("-", "_")
    return environ.get(key, default)

def _admin_page():
    """管理后台 HTML 页面"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Correctover License Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#333}
.header{background:linear-gradient(135deg,#6c5ce7,#a29bfe);color:#fff;padding:20px;text-align:center}
.header h1{font-size:22px;margin-bottom:4px}
.header p{font-size:13px;opacity:.8}
.container{max-width:900px;margin:20px auto;padding:0 16px}
.card{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card h2{font-size:16px;color:#6c5ce7;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.form-row{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.form-row label{font-size:13px;color:#666;margin-bottom:4px;display:block}
.form-row input,.form-row select{padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px;flex:1;min-width:120px}
.form-row input:focus,.form-row select:focus{border-color:#6c5ce7;outline:none}
.btn{padding:10px 24px;border:none;border-radius:8px;font-size:14px;cursor:pointer;font-weight:600}
.btn-primary{background:#6c5ce7;color:#fff}
.btn-primary:hover{background:#5a4bd1}
.btn-danger{background:#e17055;color:#fff}
.btn-sm{padding:6px 14px;font-size:12px}
.result-box{background:#f8f9fa;border:1px solid #eee;border-radius:8px;padding:16px;margin-top:12px;display:none}
.result-box.show{display:block}
.result-box .key{font-family:monospace;font-size:13px;word-break:break-all;background:#fff;padding:8px;border-radius:4px;margin:8px 0;border:1px solid #eee;user-select:all}
.result-box .copy-btn{font-size:12px;color:#6c5ce7;cursor:pointer;float:right}
table{width:100%;border-collapse:collapse;font-size:13px}
table th{background:#f8f9fa;padding:10px 8px;text-align:left;font-weight:600;color:#555;border-bottom:2px solid #eee}
table td{padding:10px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
table tr:hover{background:#fafafa}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.badge-trial{background:#ffeaa7;color:#d68910}
.badge-monthly{background:#dfe6e9;color:#636e72}
.badge-annual{background:#74b9ff;color:#0652DD}
.badge-lifetime{background:#55efc4;color:#009432}
.badge-active{background:#55efc4;color:#009432}
.badge-expired{background:#fab1a0;color:#c0392b}
.token-input{margin-bottom:20px}
.token-input input{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:14px}
.token-input input:focus{border-color:#6c5ce7;outline:none}
.tab-bar{display:flex;gap:0;margin-bottom:0;background:#f8f9fa;border-radius:12px 12px 0 0;overflow:hidden}
.tab-bar button{flex:1;padding:12px;border:none;background:transparent;font-size:14px;font-weight:600;cursor:pointer;color:#999;border-bottom:3px solid transparent}
.tab-bar button.active{color:#6c5ce7;background:#fff;border-bottom-color:#6c5ce7}
.stats{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.stats .stat{background:#f8f9fa;border-radius:8px;padding:12px 16px;flex:1;min-width:100px;text-align:center}
.stats .stat .num{font-size:24px;font-weight:700;color:#6c5ce7}
.stats .stat .label{font-size:11px;color:#999}
.toast{position:fixed;top:20px;right:20px;background:#00b894;color:#fff;padding:12px 24px;border-radius:8px;font-size:14px;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
</style>
</head>
<body>
<div class="header">
<h1>🔑 Correctover License Admin</h1>
<p>签发、查看、管理 License Key</p>
</div>
<div class="container">
<div class="token-input">
<label>Admin Token</label>
<input type="password" id="token" placeholder="输入管理密钥..." value="">
</div>
<div class="tab-bar">
<button class="active" onclick="switchTab('issue')">签发 Key</button>
<button onclick="switchTab('list')">已签发列表</button>
</div>
<div class="card" style="border-radius:0 0 12px 12px">
<div id="tab-issue">
<div class="form-row">
<div style="flex:1"><label>套餐</label>
<select id="plan">
<option value="trial">试用版 (7天)</option>
<option value="monthly">月卡 (30天)</option>
<option value="annual" selected>年卡 (365天)</option>
<option value="lifetime">永久授权</option>
</select></div>
<div style="flex:1"><label>客户名称/邮箱</label>
<input type="text" id="customer" placeholder="例: friend@company.com"></div>
</div>
<div class="form-row">
<div style="flex:1"><label>备注（可选）</label>
<input type="text" id="note" placeholder="例: 赠送测试"></div>
<div style="flex:1"><label>发送邮件</label>
<select id="send_email">
<option value="0">不发送</option>
<option value="1">发送给客户</option>
</select></div>
</div>
<button class="btn btn-primary" onclick="issueKey()">🔑 签发 License Key</button>
<div id="issue-result" class="result-box"></div>
</div>
<div id="tab-list" style="display:none">
<button class="btn btn-primary btn-sm" onclick="loadList()" style="margin-bottom:12px">🔄 刷新列表</button>
<button class="btn btn-primary btn-sm" onclick="checkEmail()" style="margin-bottom:12px;margin-left:8px">📧 检查邮件</button>
<span id="email-result" style="font-size:12px;color:#666;margin-left:8px"></span>
<div id="stats-area" class="stats"></div>
<div style="overflow-x:auto">
<table>
<thead><tr><th>Key</th><th>套餐</th><th>客户</th><th>到期</th><th>状态</th><th>备注</th><th>操作</th></tr></thead>
<tbody id="license-list"></tbody>
</table>
</div>
</div>
</div>
</div>
<div id="toast" class="toast"></div>
<script>
const API="https://license-api-neuralbridge-edouhcvhbo.cn-hangzhou.fcapp.run";
function getToken(){return document.getElementById("token").value}
function switchTab(t){document.querySelectorAll(".tab-bar button").forEach(b=>b.classList.remove("active"));event.target.classList.add("active");document.getElementById("tab-issue").style.display=t==="issue"?"block":"none";document.getElementById("tab-list").style.display=t==="list"?"block":"none";if(t==="list")loadList()}
function showToast(msg){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2000)}
function copyKey(key){navigator.clipboard.writeText(key).then(()=>showToast("已复制!"))}
async function issueKey(){
  const plan=document.getElementById("plan").value;
  const customer=document.getElementById("customer").value||"manual";
  const note=document.getElementById("note").value;
  const sendEmail=document.getElementById("send_email").value==="1";
  const email=customer.includes("@")?customer:"";
  if(!getToken()){showToast("请先输入 Admin Token");return}
  try{
    const r=await fetch(API+"/api/v1/license/issue",{method:"POST",headers:{"Authorization":"Bearer "+getToken(),"Content-Type":"application/json"},body:JSON.stringify({plan,customer,note,send_email:sendEmail,email})});
    const d=await r.json();
    if(d.error){document.getElementById("issue-result").innerHTML='<p style="color:red">❌ '+d.error+'</p>';return}
    const box=document.getElementById("issue-result");
    box.classList.add("show");
    box.innerHTML='<h3 style="color:#00b894">✅ 签发成功!</h3><p><strong>套餐:</strong> '+d.plan_label+'</p><p><strong>客户:</strong> '+(d.customer||"")+'</p><p><strong>到期:</strong> '+d.expires_date+'</p><div class="key" onclick="copyKey(\\''+d.key+'\\')">'+d.key+' <span class="copy-btn">📋点击复制</span></div>'+(sendEmail?"<p>✉️ 邮件已发送</p>":"<p style='color:#e17055'>⚠️ 未发送邮件，请手动转发 Key 给客户</p>");
    showToast("签发成功!");
  }catch(e){document.getElementById("issue-result").innerHTML='<p style="color:red">❌ '+e.message+'</p>'}
}
async function loadList(){
  if(!getToken()){showToast("请先输入 Admin Token");return}
  try{
    const [stats,lic]=await Promise.all([fetch(API+"/api/v1/license/stats",{headers:{"Authorization":"Bearer "+getToken()}}).then(r=>r.json()),fetch(API+"/api/v1/license/list",{headers:{"Authorization":"Bearer "+getToken()}}).then(r=>r.json())]);
    if(stats.error||lic.error){showToast("认证失败");return}
    document.getElementById("stats-area").innerHTML='<div class="stat"><div class="num">'+stats.total+'</div><div class="label">总计</div></div><div class="stat"><div class="num" style="color:#00b894">'+stats.active+'</div><div class="label">有效</div></div><div class="stat"><div class="num" style="color:#e17055">'+stats.expired+'</div><div class="label">过期</div></div>';
    const tbody=document.getElementById("license-list");
    tbody.innerHTML=lic.licenses.reverse().map(e=>'<tr><td style="font-family:monospace;font-size:11px;word-break:break-all;max-width:300px" onclick="copyKey(\\''+e.key+'\\')">'+e.key+'<br><span style="color:#6c5ce7;font-size:10px;cursor:pointer">📋复制</span></td><td><span class="badge badge-'+e.plan+'">'+e.plan+'</span></td><td>'+e.customer+'</td><td>'+e.expires_date+'</td><td><span class="badge badge-'+e.state+'">'+e.state+'</span></td><td style="font-size:11px;color:#999">'+(e.note||"")+'</td><td><button class="btn btn-primary btn-sm" onclick="resendEmail(\\''+e.issue_id+'\\',\\''+e.customer+'\\')">✉️发邮件</button></td></tr>').join("");
  }catch(e){showToast("加载失败: "+e.message)}
}
async function resendEmail(issueId,customer){
  let email=customer;
  if(!email||!email.includes("@")){
    email=prompt("请输入客户邮箱:","");
    if(!email||!email.includes("@")){showToast("需要有效的邮箱地址");return}
  }
  if(!confirm("确认发送 License Key 邮件到 "+email+" ?"))return;
  try{
    const r=await fetch(API+"/api/v1/license/resend",{method:"POST",headers:{"Authorization":"Bearer "+getToken(),"Content-Type":"application/json"},body:JSON.stringify({issue_id:issueId,email})});
    const d=await r.json();
    if(d.error){showToast("❌ "+d.error)}else{showToast("✅ 邮件已发送到 "+email)}
  }catch(e){showToast("❌ 发送失败: "+e.message)}
}
async function checkEmail(){
  if(!getToken()){showToast("请先输入 Admin Token");return}
  document.getElementById("email-result").textContent="⏳ 正在检查收件箱...";
  try{
    const r=await fetch(API+"/api/v1/license/check-email",{method:"POST",headers:{"Authorization":"Bearer "+getToken()}});
    const d=await r.json();
    if(d.error){document.getElementById("email-result").textContent="❌ "+d.error;return}
    const info=d.replied>0?"✅ 检查 "+d.checked+" 封，自动回复 "+d.replied+" 封":"📭 检查 "+d.checked+" 封，无需要回复的邮件";
    document.getElementById("email-result").textContent=info;
    showToast(info);
    if(d.replied>0)loadList();
  }catch(e){document.getElementById("email-result").textContent="❌ "+e.message}
}
</script>
</body>
</html>'''
