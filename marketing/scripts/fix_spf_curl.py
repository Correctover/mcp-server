#!/usr/bin/env python3
"""Fix SPF records for correctover.com using Aliyun DNS REST API."""
import json, sys, time, os, urllib.parse, hmac, hashlib, base64
import requests

AK = os.environ.get("ALIYUN_AK", "")
SK = os.environ.get("ALIYUN_SK", "")
DOMAIN = "correctover.com"

ENDPOINT = "https://alidns.aliyuncs.com"

def sign_request(params):
    """Sign Aliyun API request with HMAC-SHA1."""
    # Sort params by key
    sorted_keys = sorted(params.keys())
    canonical = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(params[k]), safe='')}" for k in sorted_keys)
    string_to_sign = f"GET&%2F&{urllib.parse.quote(canonical, safe='')}"

    # HMAC-SHA1
    h = hmac.new(f"{SK}&".encode(), string_to_sign.encode(), hashlib.sha1)
    signature = base64.b64encode(h.digest()).decode()

    params["Signature"] = signature
    return params

def api_call(action, extra_params=None):
    """Make an Aliyun DNS API call."""
    params = {
        "Action": action,
        "DomainName": DOMAIN,
        "Format": "JSON",
        "Version": "2015-01-09",
        "AccessKeyId": AK,
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(int(time.time() * 1000000)),
    }
    if extra_params:
        params.update(extra_params)

    signed = sign_request(params)
    r = requests.get(ENDPOINT, params=signed, timeout=15)
    return r.json()

# Step 1: List existing records
print("=== Current DNS Records ===")
resp = api_call("DescribeDomainRecords")
records = resp.get("DomainRecords", {}).get("Record", [])
for r in records:
    print(f"  {r['RR']:<25} {r['Type']:<6} {r['Value'][:60]}")

# Step 2: Find SPF records
print("\n=== SPF Analysis ===")
old_spf_id = None
new_spf_id = None
for r in records:
    if r["RR"] == "@" and r["Type"] == "TXT" and "v=spf1" in r["Value"]:
        val = r["Value"]
        if "include:spf.163.com" in val and "qiye" not in val:
            old_spf_id = r["RecordId"]
            print(f"  OLD SPF (RecordId={old_spf_id}): {val}")
        elif "include:spf.qiye.163.com" in val:
            new_spf_id = r["RecordId"]
            print(f"  NEW SPF (RecordId={new_spf_id}): {val}")

# Step 3: Delete old SPF
if old_spf_id:
    print(f"\nDeleting old SPF (include:spf.163.com)...")
    resp = api_call("DeleteDomainRecord", {"RecordId": old_spf_id})
    print(f"  Result: {resp}")
else:
    print("\nNo old SPF to delete")

# Step 4: Update new SPF from ~all to -all
if new_spf_id:
    print(f"\nUpdating new SPF ~all -> -all...")
    resp = api_call("UpdateDomainRecord", {
        "RecordId": new_spf_id,
        "RR": "@",
        "Type": "TXT",
        "Value": "v=spf1 include:spf.qiye.163.com -all"
    })
    print(f"  Result: {resp}")

# Step 5: Verify
print("\n=== Final Verification ===")
resp = api_call("DescribeDomainRecords")
records = resp.get("DomainRecords", {}).get("Record", [])
for r in records:
    if r["RR"] == "@" and r["Type"] == "TXT" and "v=spf1" in r["Value"]:
        print(f"  SPF: {r['Value']}")

print("\nDone. DNS propagation takes 10 min.")
print("After propagation, do a test email to verify SPF pass.")
