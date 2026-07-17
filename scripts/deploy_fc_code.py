#!/usr/bin/env python3
"""Deploy updated index.py to Alibaba Cloud FC (both cn-hangzhou and cn-hongkong)"""
import json, os, sys, tempfile, zipfile, io, traceback
from pathlib import Path

# Load Aliyun credentials
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

SOURCE_FILE = Path(__file__).parent.parent / "fc-functions" / "license-api" / "index.py"
if not SOURCE_FILE.exists():
    print(f"Source not found: {SOURCE_FILE}")
    sys.exit(1)

code_content = SOURCE_FILE.read_bytes()

def update_region(region, service_name):
    print(f"\n--- {region} / {service_name} ---")
    try:
        config = openapi_models.Config(
            access_key_id=AK_ID, access_key_secret=AK_SECRET,
            region_id=region, endpoint=f"fc.{region}.aliyuncs.com",
        )
        client = Client(config)

        # List functions to find license-api
        fresp = client.list_functions(service_name, fc_models.ListFunctionsRequest(limit=50))
        funcs = getattr(fresp.body, 'functions', [])
        target_func = None
        for fn in funcs:
            if "license" in fn.function_name.lower():
                target_func = fn.function_name
                print(f"  Found: {target_func} ({fn.runtime})")
                break

        if not target_func:
            print(f"  No license function found in {service_name}")
            return False

        # Get current function config
        greq = fc_models.GetFunctionRequest()
        gresp = client.get_function(service_name, target_func, greq)
        curr_env = gresp.body.environment_variables or {}

        # Build the update request
        # Note: the SDK v20210406 accepts code as a zip in the request body
        # We need to zip the index.py

        # Create zip in memory
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.py", code_content)
        zip_bytes = buf.getvalue()

        import base64
        b64_zip = base64.b64encode(zip_bytes).decode('ascii')
        upd = fc_models.UpdateFunctionRequest()
        upd.environment_variables = curr_env
        upd.handler = gresp.body.handler
        upd.runtime = gresp.body.runtime
        upd.memory_size = gresp.body.memory_size
        upd.timeout = gresp.body.timeout
        upd.code = fc_models.Code(zip_file=b64_zip)

        print(f"  Deploying... (code size: {len(code_content)} bytes, zip: {len(zip_bytes)} bytes)")
        resp = client.update_function(service_name, target_func, upd)
        print(f"  Deployed OK! Last modified: {getattr(resp.body, 'last_modified_time', 'N/A')}")
        return True

    except Exception as e:
        print(f"  Error: {e}")
        traceback.print_exc()
        return False

success = 0
# cn-hangzhou: neuralbridge/license-api
if update_region("cn-hangzhou", "neuralbridge"):
    success += 1
# cn-hongkong: neuralbridge-hk/license-api
if update_region("cn-hongkong", "neuralbridge-hk"):
    success += 1

print(f"\n{'='*40}")
print(f"Deployed: {success}/2 regions")
