import sys
import os
import time
import subprocess
import requests

def run_smoke_test():
    port = 8023
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=dict(os.environ, PYTHONPATH="backend"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        started = False
        for _ in range(30):
            try:
                r = requests.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    started = True
                    print("HEALTH_OK:", r.json())
                    break
            except Exception:
                time.sleep(0.5)
        if not started:
            print("HEALTH_FAILED")
            sys.exit(1)

        # Login
        auth_resp = requests.post(
            f"http://127.0.0.1:{port}/api/v1/auth/login",
            json={"username": "admin", "password": "BeaconAdmin2026!"},
            timeout=2.0,
        )
        print("LOGIN_STATUS:", auth_resp.status_code)
        assert auth_resp.status_code == 200, f"Login failed: {auth_resp.text}"
        token = auth_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # Verify v2 adapters endpoint
        adp_resp = requests.get(f"http://127.0.0.1:{port}/api/v2/adapters", headers=headers, timeout=2.0)
        print("V2_ADAPTERS_STATUS:", adp_resp.status_code, "total:", adp_resp.json().get("total"))
        assert adp_resp.status_code == 200, f"V2 adapters failed: {adp_resp.text}"

        # Verify v1 benchmarks endpoint
        bench_resp = requests.get(f"http://127.0.0.1:{port}/api/v1/benchmarks", headers=headers, timeout=2.0)
        print("V1_BENCHMARKS_STATUS:", bench_resp.status_code)
        assert bench_resp.status_code == 200, f"V1 benchmarks failed: {bench_resp.text}"

        print("SMOKE_TEST_PASS")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    run_smoke_test()
