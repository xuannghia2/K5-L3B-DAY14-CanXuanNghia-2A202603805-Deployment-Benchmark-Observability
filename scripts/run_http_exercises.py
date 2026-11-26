"""Exercise HTTP evidence, without writing keys or JWTs to reports."""
import contextlib, json, os, secrets, subprocess, sys, time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
REPORTS=ROOT/"reports"
records=[]
@contextlib.contextmanager
def serve(folder,port,probe="/health",**env):
    with (REPORTS/f"server-{port}.log").open("w",encoding="utf-8") as log:
        p=subprocess.Popen([sys.executable,"-m","uvicorn","app:app","--host","127.0.0.1",
                            "--port",str(port),"--no-access-log"],
                            cwd=ROOT/folder,env={**os.environ,"PYTHONIOENCODING":"utf-8",**env},
                            stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    if httpx.get(f"http://127.0.0.1:{port}{probe}").status_code==200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError(f"Startup failed: {folder}")
            yield f"http://127.0.0.1:{port}"
        finally:
            p.terminate()
            try:p.wait(10)
            except subprocess.TimeoutExpired:p.kill();p.wait()

def record(label,response):
    records.append({"exercise":label,"status":response.status_code,
                    "response_headers":dict(response.headers),"response_body":response.text})
    print(label,response.status_code,flush=True)

with serve("01-localhost-vs-production/develop",8011,"/") as base:
    record("1.2 query request",httpx.post(base+"/ask",params={"question":"Hello"}))
    record("1.2 JSON mismatch",httpx.post(base+"/ask",json={"question":"Hello"}))
with serve("01-localhost-vs-production/production",8012) as base:
    record("1.3 production ask",httpx.post(base+"/ask",json={"question":"Docker deployment"}))
with serve("04-api-gateway/develop",8013,AGENT_API_KEY=secrets.token_hex(24)) as base:
    record("4.1 missing key",httpx.post(base+"/ask",json={"question":"Hello"}))
# Separate invocation supplies an ephemeral key to test successful API key auth.
key=secrets.token_hex(24)
with serve("04-api-gateway/develop",8013,AGENT_API_KEY=key) as base:
    record("4.1 correct key",httpx.post(base+"/ask",json={"question":"Hello"},headers={"X-API-Key":key}))
with serve("04-api-gateway/production",8014,JWT_SECRET=secrets.token_hex(32)) as base:
    record("4.2 no JWT",httpx.post(base+"/ask",json={"question":"Docker"}))
    response=httpx.post(base+"/auth/token",json={"username":"student","password":"demo123"})
    response.raise_for_status()
    headers={"Authorization":"Bearer "+response.json()["access_token"]}
    for i in range(1,16):
        response=httpx.post(base+"/ask",json={"question":"Docker"},headers=headers)
        record(f"4.3 authenticated request {i}",response)
        if response.status_code==429:
            break
with serve("05-scaling-reliability/develop",8015) as base:
    record("5.1 health",httpx.get(base+"/health"))
    record("5.2 ready",httpx.get(base+"/ready"))
    record("5.3 ask",httpx.post(base+"/ask",params={"question":"Hello"}))
(REPORTS/"exercise-http-evidence.json").write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf-8")
text="\n\n".join(f"### {r['exercise']}\nHTTP {r['status']}\n"+
    "\n".join(f"{k}: {v}" for k,v in r["response_headers"].items())+"\n\n"+r["response_body"] for r in records)
(REPORTS/"exercise-http-evidence.txt").write_text(text,encoding="utf-8")
