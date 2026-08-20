"""
下载 Project AirSim Release 包
检查 GitHub Release 并下载预编译 SimLibs
"""
import urllib.request
import json
import os
import zipfile
import sys

# 获取最新 Release 信息
url = "https://api.github.com/repos/iamaisim/ProjectAirSim/releases/latest"
req = urllib.request.Request(url)
req.add_header("Accept", "application/json")
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())

print("Release:", data.get("tag_name", "unknown"))

assets = data.get("assets", [])
if not assets:
    # 尝试获取所有 releases
    url2 = "https://api.github.com/repos/iamaisim/ProjectAirSim/releases?per_page=5"
    req2 = urllib.request.Request(url2)
    req2.add_header("Accept", "application/json")
    resp2 = urllib.request.urlopen(req2)
    releases = json.loads(resp2.read().decode())
    for r in releases:
        print(f"\nRelease: {r.get('tag_name', 'unknown')}")
        for asset in r.get("assets", []):
            name = asset["name"]
            size_mb = asset["size"] // 1024 // 1024
            print(f"  {name} ({size_mb}MB)")
else:
    for asset in assets:
        name = asset["name"]
        size_mb = asset["size"] // 1024 // 1024
        print(f"  {name} ({size_mb}MB)")