#!/usr/bin/env python3
"""Read FC env vars unmasked."""
import json, os, sys
aliyun_config = os.path.expanduser("~/.aliyun/config.json")
with open(aliyun_config) as f:
    profiles = json.load(f).get("profiles", [])
AK_ID = profiles[0]["access_key_id"]
AK_SECRET = profiles[0]["access_key_secret"]

from alibabacloud_fc_open20210406.client import Client
from alibabacloud_fc_open20210406 import models as fc_models
from alibabacloud_tea_openapi import models as openapi_models

config = openapi_models.Config(
    access_key_id=AK_ID, access_key_secret=AK_SECRET,
    region_id="cn-hangzhou", endpoint="fc.cn-hangzhou.aliyuncs.com",
)
client = Client(config)
gresp = client.get_function("neuralbridge", "license-api", fc_models.GetFunctionRequest())
env = gresp.body.environment_variables or {}
print("=== HMAC_SECRET ===")
print(repr(env.get("NB_HMAC_SECRET", "")))
print("\n=== All env vars ===")
for k in sorted(env.keys()):
    print(f"  {k} = {repr(env[k])}")
