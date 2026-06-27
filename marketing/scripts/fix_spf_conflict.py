#!/usr/bin/env python3
"""Fix SPF records: delete old one, add correct one."""
import json, os
from aliyunsdkcore.client import AcsClient
from aliyunsdkalidns.request.v20150109 import (
    DescribeDomainRecordsRequest,
    DeleteDomainRecordRequest,
    AddDomainRecordRequest,
    UpdateDomainRecordRequest,
)

AK = os.environ.get("ALIYUN_AK", "")
SK = os.environ.get("ALIYUN_SK", "")
DOMAIN = "correctover.com"

client = AcsClient(AK, SK, "cn-hangzhou", timeout=10, protocol="HTTPS")

# List all records
req = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
req.set_DomainName(DOMAIN)
resp = json.loads(client.do_action_with_exception(req))
records = resp.get("DomainRecords", {}).get("Record", [])

print("All TXT records for @:")
old_spf_id = None
new_spf_id = None
for r in records:
    if r["RR"] == "@" and r["Type"] == "TXT":
        val = r["Value"]
        if "v=spf1" in val:
            if "include:spf.163.com" in val:
                old_spf_id = r["RecordId"]
                print(f"  OLD SPF: {val} (RecordId: {r['RecordId']})")
            elif "include:spf.qiye.163.com" in val:
                new_spf_id = r["RecordId"]
                print(f"  NEW SPF: {val} (RecordId: {r['RecordId']})")

# Delete old SPF
if old_spf_id:
    print(f"\nDeleting old SPF record (RecordId: {old_spf_id})...")
    req = DeleteDomainRecordRequest.DeleteDomainRecordRequest()
    req.set_RecordId(old_spf_id)
    client.do_action_with_exception(req)
    print("  Deleted ✅")
else:
    print("\nNo old SPF record found to delete")

# Update new SPF from ~all to -all (hard fail)
if new_spf_id:
    print(f"\nUpdating new SPF from ~all to -all (RecordId: {new_spf_id})...")
    req = UpdateDomainRecordRequest.UpdateDomainRecordRequest()
    req.set_RecordId(new_spf_id)
    req.set_RR("@")
    req.set_Type("TXT")
    req.set_Value('"v=spf1 include:spf.qiye.163.com -all"')
    client.do_action_with_exception(req)
    print("  Updated to hard fail ✅")

print("\nVerifying final state:")
req = DescribeDomainRecordsRequest.DescribeDomainRecordsRequest()
req.set_DomainName(DOMAIN)
resp = json.loads(client.do_action_with_exception(req))
records = resp.get("DomainRecords", {}).get("Record", [])
for r in records:
    if r["RR"] == "@" and r["Type"] == "TXT" and "v=spf1" in r["Value"]:
        print(f"  SPF: {r['Value']}")
