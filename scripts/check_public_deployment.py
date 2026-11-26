"""Verify CP6 without exposing credentials in output."""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path
base=os.environ.get("BASE","").rstrip("/")
key=os.environ.get("AGENT_API_KEY","")
if not base.startswith("https://") or not key:
    raise SystemExit("Set BASE=https://... and AGENT_API_KEY in your terminal environment.")
checks=[]
for name,method,path,auth,expected in [
    ("health","GET","/health",False,200),("ready","GET","/ready",False,200),
    ("ask_no_key","POST","/ask",False,401),("ask_with_key","POST","/ask",True,200)]:
    headers={"Content-Type":"application/json"}
    if auth: headers["X-API-Key"]=key
    request=urllib.request.Request(base+path,method=method,headers=headers,
        data=json.dumps({"question":"Hello"}).encode() if method=="POST" else None)
    try:
        with urllib.request.urlopen(request,timeout=90) as response: status=response.status
    except urllib.error.HTTPError as exc: status=exc.code
    checks.append({"name":name,"status":status,"expected":expected,"passed":status==expected})
    print(name,status)
out=Path(__file__).resolve().parents[1]/"reports/public-deployment.json"
out.write_text(json.dumps({"base":base,"checks":checks},indent=2),encoding="utf-8")
sys.exit(0 if all(c["passed"] for c in checks) else 1)
