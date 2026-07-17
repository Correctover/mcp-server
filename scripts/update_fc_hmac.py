#!/usr/bin/env python3
"""Update FC license-api env vars (HMAC secret)."""
import json, os, sys, traceback

aliyun_config = os.path.expanduser("~/.aliyun/config.json")
AK_ID = ""
AK_SECRET = ""
if os.path.exists(aliyun_config):
    with open(aliyun_config) as f:
        profiles = json.load(f).get("profiles", [])
    if profiles:
        AK_ID = profiles[0].get("access_key_id", "")
        AK_SECRET = profiles[0].get("access_key_secret", "")
AK_ID = os.environ.get("ALIYUN_AK", AK_ID)
AK_SECRET = os.environ.get("ALIYUN_SK", AK_SECRET)
if not AK_ID or not AK_SECRET:
    print("No Aliyun credentials"); sys.exit(1)
print("AK:", AK_ID[:10]+"...")

from alibabacloud_fc_open20210406.client import Client
from alibabacloud_fc_open20210406 import models as fc_models
from alibabacloud_tea_openapi import models as openapi_models

NB_HMAC_SECRET = "correctover-mcp-hmac-v1-2026"

for REGION in ["cn-hangzhou", "cn-hongkong"]:
    print(f"\n--- Region: {REGION} ---")
    try:
        config = openapi_models.Config(
            access_key_id=AK_ID, access_key_secret=AK_SECRET,
            region_id=REGION, endpoint=f"fc.{REGION}.aliyuncs.com",
        )
        client = Client(config)
        resp = client.list_services(fc_models.ListServicesRequest(limit=50))
        services = getattr(resp.body, 'services', [])
        if not services:
            print("  (no services)"); continue
        for svc in services:
            name = svc.service_name
            fresp = client.list_functions(name, fc_models.ListFunctionsRequest(limit=50))
            funcs = getattr(fresp.body, 'functions', [])
            for fn in funcs:
                fname = fn.function_name
                is_license = "license" in fname.lower() or "license" in name.lower()
                print(f"  {name}/{fname} ({fn.runtime}){' <-- LICENSE' if is_license else ''}")
                if not is_license:
                    continue
                greq = fc_models.GetFunctionRequest()
                gresp = client.get_function(name, fname, greq)
                env = gresp.body.environment_variables or {}
                for k in sorted(env.keys()):
                    v = env[k]
                    masked = v[:10]+"..." if len(v)>12 else v
                    flag = " <-- HMAC" if k == "NB_HMAC_SECRET" else ""
                    print(f"    {k} = {masked}{flag}")
                curr = env.get("NB_HMAC_SECRET", None)
                if curr == NB_HMAC_SECRET:
                    print("  NB_HMAC_SECRET OK")
                else:
                    print(f"  UPDATE: NB_HMAC_SECRET {repr(curr)[:20]} -> {NB_HMAC_SECRET}")
                    env["NB_HMAC_SECRET"] = NB_HMAC_SECRET
                    upd = fc_models.UpdateFunctionRequest()
                    upd.environment_variables = env
                    upd.handler = gresp.body.handler
                    upd.runtime = gresp.body.runtime
                    upd.memory_size = gresp.body.memory_size
                    upd.timeout = gresp.body.timeout
                    client.update_function(name, fname, upd)
                    print("  UPDATED OK")
    except Exception as e:
        print(f"  Error: {e}")
        traceback.print_exc()
print("\nDone")
