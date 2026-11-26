"""Reproduce local exercises and CP7 using real HTTP, keeping raw evidence."""
import contextlib, json, os, platform, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "06-lab-complete/benchmark-observability/develop"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

@contextlib.contextmanager
def server(cwd, port, version="v2", **overrides):
    env = {**ENV, "AGENT_VERSION": version, "PORT": str(port), **overrides}
    log = (REPORTS / f"server-{port}.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                             "--port", str(port), "--no-access-log"], cwd=cwd, env=env,
                            stdout=log, stderr=log)
    try:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                raise RuntimeError(f"Server exited; see server-{port}.log")
            time.sleep(.1)
        else:
            raise TimeoutError("Agent startup")
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()

def command(cwd, args, name, allowed=(0,)):
    result = subprocess.run([sys.executable, *args], cwd=cwd, env=ENV,
                            capture_output=True, text=True, encoding="utf-8")
    (REPORTS / f"{name}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(f"{name}: exit {result.returncode}", flush=True)
    if result.returncode not in allowed:
        raise RuntimeError(f"{name} failed; inspect reports/{name}.txt")
    return result.returncode

def eval_at(port, name, baseline=None, minimum=".85"):
    args = ["eval/run_eval.py", "--url", f"http://127.0.0.1:{port}", "--min-accuracy", minimum,
            "--out", str(REPORTS / f"{name}.json")]
    if baseline:
        args += ["--baseline", str(REPORTS / f"{baseline}.json")]
    command(DEV, args, name, allowed=(0,1) if name == "eval_v1" else (0,))

def main():
    manifest = {"date_local": time.strftime("%Y-%m-%d %H:%M:%S"),
                "platform": platform.platform(), "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
                "load": {"requests": 300, "MOCK_ERROR_RATE": .01, "MOCK_SLOW_RATE": .03},
                "eval": {"MOCK_ERROR_RATE": 0, "MOCK_SLOW_RATE": 0},
                "notes": "Load SLO failure exit 1 is retained as measured evidence."}
    (REPORTS / "environment.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Original KB for pre-fix baselines. Golden dataset is never modified.
    with tempfile.TemporaryDirectory(prefix="day14-baseline-") as temp:
        baseline_dir = Path(temp) / "develop"
        shutil.copytree(DEV, baseline_dir, ignore=shutil.ignore_patterns("__pycache__", "reports"))
        original = subprocess.check_output(["git", "show",
            "83e677fef599a58e21ba796b42ccc52ed43c1968:06-lab-complete/benchmark-observability/develop/utils/mock_llm.py"],
            cwd=ROOT)
        (baseline_dir / "utils/mock_llm.py").write_bytes(original)
        with server(baseline_dir, 8001, "v1", MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0"):
            eval_at(8001, "eval_v1")
        with server(baseline_dir, 8002, MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0"):
            eval_at(8002, "eval_v2", "eval_v1")
    with server(DEV, 8002, MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0"):
        eval_at(8002, "eval_v2_fixed", "eval_v2", "1.0")
        httpx.post("http://127.0.0.1:8002/ask", json={"question":"Prometheus metrics?"}).raise_for_status()
        (REPORTS / "metrics.txt").write_text(httpx.get("http://127.0.0.1:8002/metrics").text, encoding="utf-8")
    with server(DEV, 8002):
        for c in (1,10,50,100):
            name = f"load_v2_c{c}"
            command(DEV, ["load_test.py", "--url", "http://127.0.0.1:8002", "--requests", "300",
                "--concurrency", str(c), "--out", str(REPORTS / f"{name}.json")], name, (0,1))
    for slow in ("0","0.03","0.1"):
        with server(DEV, 8002, MOCK_SLOW_RATE=slow):
            name = f"load_v2_slow_{slow}"
            command(DEV, ["load_test.py", "--url", "http://127.0.0.1:8002", "--requests", "300",
                "--concurrency", "20", "--out", str(REPORTS / f"{name}.json")], name, (0,1))
    target = DEV / "reports"
    target.mkdir(exist_ok=True)
    for path in REPORTS.glob("*.json"):
        shutil.copy2(path, target / path.name)
    print("CP7 complete", flush=True)

if __name__ == "__main__":
    main()

