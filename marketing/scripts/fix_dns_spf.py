#!/usr/bin/env python3
"""Add SPF + DKIM records to correctover.com for 163 enterprise email."""
import json, sys, os
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109 import (
    DescribeDomainRecordsRequest,
    AddDomainRecordRequest,
)

AK = os.environ.get("ALIYUN_AK", "")
SK = os.environ.get("ALIYUN_SK", "")
DOMAIN = "correctover.com"

client = AcsClient(AK, SK, "cn-hangzhou", timeout=10)

def list_records():
    req = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
    req.set_DomainName(DOMAIN)
    resp = json.loads(client.do_action_with_exception(req))
    print(f"Existing records for {DOMAIN}:")
    for r in resp.get("DomainRecords", {}).get("Record", []):
        print(f"  {r['RR']:<20} {r['Type']:<6} {r['Value']}")
    return resp

def add_record(rr, type_, value):
    req = AddDomainRecordRequest.AddDomainRecordRequest()
    req.set_DomainName(DOMAIN)
    req.set_RR(rr)
    req.set_Type(type_)
    req.set_Value(value)
    resp = json.loads(client.do_action_with_exception(req))
    print(f"  Added: {rr} {type_} {value} -> RecordId: {resp.get('RecordId')}")
    return resp

print("=== Current DNS Records ===")
list_records()

print("\n=== Adding SPF Record ===")
# SPF: allow 163 (qiye.163.com) to send as correctover.com
add_record("@", "TXT", '"v=spf1 include:spf.qiye.163.com ~all"')

print("\n=== Adding MX Records (if missing) ===")
# Note: MX records should already exist based on nslookup
# Let's add them explicitly with proper priority
# Actually, MX already exists, skip.

print("\nDone. Wait 10 min for DNS propagation.")
