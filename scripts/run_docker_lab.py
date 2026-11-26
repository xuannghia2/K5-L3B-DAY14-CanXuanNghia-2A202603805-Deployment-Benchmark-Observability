"""Run Docker exercises on Linux and collect only observed evidence."""
import json, os, subprocess, sys, time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SHOTS = ROOT / "screenshots"
CSV = ROOT / "benchmark-results"
OBS = ROOT / "06-lab-complete/benchmark-observability/production"
for folder in (REPORTS, SHOTS, CSV, OBS / "benchmark-results"):
    folder.mkdir(exist_ok=True)
os.chmod(OBS / "benchmark-results", 0o777)

def run(args, cwd=ROOT, name=None, check=True, env=None):
    print("Running:", " ".join(args), flush=True)
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if name:
        (REPORTS / f"{name}.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if check and proc.returncode:
        print((proc.stdout + proc.stderr)[-6000:], flush=True)
        raise RuntimeError(f"{args[0]} exit {proc.returncode}")
    return proc

def compose(folder, project, *args, **kwargs):
    return run(["docker","compose","-p",project,*args],cwd=folder,**kwargs)

def wait(url, seconds=120):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:
            if httpx.get(url,timeout=3).status_code==200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError(url)

def screenshot(page,url,name):
    page.goto(url,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(12000)
    page.screenshot(path=str(SHOTS/name),full_page=True)

def query(expr):
    data=httpx.get("http://localhost:9090/api/v1/query",params={"query":expr},timeout=15).json()
    assert data["status"]=="success",data
    return data["data"]["result"]

def main():
    if not ({"--chaos-only", "--scale-only"} & set(sys.argv)):
        # CP2: images, real container HTTP and Compose through Nginx.
        for version,path in (("develop","develop"),("advanced","production")):
            run(["docker","build","-f",f"02-docker/{path}/Dockerfile","-t",f"my-agent:{version}","."],
                name=f"docker-build-{version}")
        sizes={v:int(run(["docker","image","inspect",f"my-agent:{v}","--format","{{.Size}}"]).stdout)
               for v in ("develop","advanced")}
        sizes["reduction_percent"]=(sizes["develop"]-sizes["advanced"])/sizes["develop"]*100
        (REPORTS/"docker-image-sizes.json").write_text(json.dumps(sizes,indent=2))
        run(["docker","run","-d","--name","day14-basic","-p","8000:8000","my-agent:develop"])
        try:
            wait("http://localhost:8000/openapi.json")
            resp=httpx.post("http://localhost:8000/ask",params={"question":"What is Docker?"})
            (REPORTS/"docker-basic-http.txt").write_text(f"HTTP {resp.status_code}\n{resp.text}")
            resp.raise_for_status()
        finally:
            run(["docker","rm","-f","day14-basic"],check=False)
        folder=ROOT/"02-docker/production"
        (folder/".env.local").touch()
        try:
            compose(folder,"k5-day14-docker","up","-d","--build",name="part2-compose")
            wait("http://localhost/health")
            resp=httpx.post("http://localhost/ask",json={"question":"Explain microservices"})
            (REPORTS/"part2-nginx.txt").write_text(f"HTTP {resp.status_code}\n{resp.text}")
            resp.raise_for_status()
        finally:
            compose(folder,"k5-day14-docker","logs",name="part2-stack-logs",check=False)
            compose(folder,"k5-day14-docker","down","-v",check=False)
        folder=ROOT/"05-scaling-reliability/production"
        (folder/".env.local").touch()
        try:
            compose(folder,"k5-day14-scaling","up","-d","--build","--scale","agent=3")
            wait("http://localhost:8080/health")
            run([sys.executable,"test_stateless.py"],cwd=folder,name="part5-stateless")
        finally:
            compose(folder,"k5-day14-scaling","down","-v",check=False)
    # CP8: default-load scale benchmark, then two simultaneous chaos alerts.
    project="k5-day14-observability"
    try:
        compose(OBS,project,"up","-d","--build","--scale","agent=1",name="obs-startup")
        wait("http://localhost:8080/health")
        wait("http://localhost:3000/api/health")
        wait("http://localhost:9090/-/ready")
        run(["docker","run","--rm","-v",str(OBS/"prometheus")+":/p","--entrypoint","promtool",
             "prom/prometheus:v3.16.0","test","rules","/p/alert_rules_test.yml"],name="alert-rule-tests")
        if "--chaos-only" not in sys.argv:
            for count in (1,3):
                if count==3:
                    compose(OBS,project,"up","-d","--scale","agent=3")
                    time.sleep(15) # DNS discovery of new instances.
                containers=compose(OBS,project,"ps","-q","agent").stdout.splitlines()
                assert len(containers)==count, (count, containers)
                (REPORTS/f"scale_{count}_instances.json").write_text(json.dumps({"expected":count,"actual":len(containers),"container_ids":containers},indent=2))
                compose(OBS,project,"run","--rm","--no-deps","locust","-f","/mnt/locust/locustfile.py","--host","http://nginx",
                        "--headless","-u","100","-r","10","-t","2m","--csv",f"/mnt/results/scale_{count}",
                        name=f"locust-scale-{count}",check=False)
                src=OBS/f"benchmark-results/scale_{count}_stats.csv"
                assert src.exists(), f"Missing {src}"
                (CSV/src.name).write_bytes(src.read_bytes())
        if "--scale-only" in sys.argv:
            return
        env={**os.environ,"MOCK_ERROR_RATE":"0.2","MOCK_SLOW_RATE":"0.3"}
        chaos_start=time.time()
        compose(OBS,project,"up","-d","--force-recreate","--scale","agent=3","agent",env=env)
        load=subprocess.Popen(["docker","compose","-p",project,"run","--rm","--no-deps","locust",
            "-f","/mnt/locust/locustfile.py","--host","http://nginx","--headless","-u","100","-r","10","-t","6m"],
            cwd=OBS,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            first={}
            samples=[]
            for _ in range(100):
                time.sleep(3)
                response=httpx.get("http://localhost:9090/api/v1/alerts",timeout=10).json()
                active=response["data"]["alerts"]
                elapsed=round(time.time()-chaos_start,1)
                samples.append({"elapsed_s":elapsed,"alerts":active})
                firing={a["labels"]["alertname"] for a in active if a["state"]=="firing"}
                for name in firing:
                    first.setdefault(name,elapsed)
                if {"AgentHighErrorRate","AgentHighLatencyP95"} <= firing:
                    break
            (REPORTS/"chaos-alerts.json").write_text(json.dumps({"settings":{
                "MOCK_ERROR_RATE":.2,"MOCK_SLOW_RATE":.3},"first_firing_seconds":first,"samples":samples},indent=2))
            assert {"AgentHighErrorRate","AgentHighLatencyP95"} <= first.keys(),first
            snapshot={name:query(expr) for name,expr in {
                "p95":"histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job=\"agent\",route=\"/ask\"}[1m])))",
                "avg":"sum(rate(http_request_duration_seconds_sum{job=\"agent\",route=\"/ask\"}[1m]))/sum(rate(http_request_duration_seconds_count{job=\"agent\",route=\"/ask\"}[1m]))",
                "requests_by_instance":"sum by(instance)(rate(http_requests_total{job=\"agent\",route=\"/ask\"}[1m]))"}.items()}
            snapshot["public_metrics_status"]=httpx.get("http://localhost:8080/metrics").status_code
            (REPORTS/"prometheus-snapshot.json").write_text(json.dumps(snapshot,indent=2))
            logs=compose(OBS,project,"logs","--no-color","agent").stdout
            entries=[]
            for line in logs.splitlines():
                start=line.find("{")
                if start>=0:
                    try:
                        entries.append(json.loads(line[start:]))
                    except ValueError:
                        pass
            time.sleep(7) # Allow batched OTLP spans to reach Jaeger.
            # Jaeger 2.23 removed the legacy search route; retrieve known trace IDs
            # from application logs through its documented trace-by-ID endpoint.
            calls=[e for e in entries if e.get("event")=="llm_call" and e.get("trace_id")]
            failures=[e for e in entries if e.get("event")=="llm_error" and e.get("trace_id")]
            assert calls and failures, "Missing successful/failed LLM log events"
            picked=[max(calls,key=lambda e:e.get("llm_ms",0)),failures[-1]]
            traces=[]
            for event in picked:
                response=httpx.get("http://localhost:16686/api/traces/"+event["trace_id"],timeout=30)
                response.raise_for_status()
                traces.extend(response.json()["data"])
            correlated={e.get("trace_id"):e for e in entries if e.get("trace_id")}
            candidates=[t for t in traces if t["traceID"] in correlated and
                any(s["operationName"].startswith("chat ") for s in t["spans"])]
            assert candidates,"No correlated agent traces"
            slow=max(candidates,key=lambda t:max(s["duration"] for s in t["spans"]))
            errors=[t for t in candidates if any(tag["key"]=="error" and tag["value"] is True
                     for s in t["spans"] for tag in s.get("tags",[]))]
            assert errors,"No error trace"
            err=errors[0]
            evidence={"slow":slow,"error":err,"slow_log":correlated[slow["traceID"]],
                      "error_log":correlated[err["traceID"]]}
            (REPORTS/"trace-evidence.json").write_text(json.dumps(evidence,indent=2,ensure_ascii=False))
            with sync_playwright() as p:
                browser=p.chromium.launch()
                page=browser.new_page(viewport={"width":1600,"height":1000})
                screenshot(page,"http://localhost:3000/d/day14-agent-overview?from=now-10m&to=now",
                           "grafana-dashboard.png")
                screenshot(page,"http://localhost:9090/alerts","prometheus-alert-firing.png")
                screenshot(page,f"http://localhost:16686/trace/{slow['traceID']}","jaeger-slow-trace.png")
                screenshot(page,f"http://localhost:16686/trace/{err['traceID']}","jaeger-error-trace.png")
                browser.close()
        finally:
            load.terminate()
            load.wait(15)
    finally:
        compose(OBS,project,"logs","--no-color",name="observability-stack-logs",check=False)
        compose(OBS,project,"down","-v",check=False)

if __name__=="__main__":
    main()

