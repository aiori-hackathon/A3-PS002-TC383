"""PEP overhead: latency of a /share decision (check + audit append, one transaction) versus
fetching the same record with NO consent check. Prints measured p50/p95 only.
Run: python -m scripts.bench_pep [N]"""
import statistics
import sys
import tempfile
import time

from app.config import load_settings
from app.gateway import StorageGateway
from app.consent_service import ConsentService
from app.mock_api import MockDataAPI
from app.pep import PolicyEnforcementPoint
from app.seed import seed_if_empty

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
with tempfile.TemporaryDirectory() as d:
    s = load_settings(d + "/bench.db")
    gw = StorageGateway(s.db_path); seed_if_empty(gw, s)
    mock, pep, cs = MockDataAPI(s.internal_token), None, ConsentService(gw)
    pep = PolicyEnforcementPoint(gw, mock, s)
    h = None
    with gw.read() as c: h = gw.current_notice(c, "analytics")["hash"]
    cs.grant("u001", "analytics", h)
    key = s.requester_keys["analytics-co"]

    def pct(xs, p): return sorted(xs)[int(len(xs) * p) - 1] * 1000
    with_check, without = [], []
    for _ in range(N):
        t = time.perf_counter(); pep.share(key, {"user_pid": "u001", "purpose": "analytics"})
        with_check.append(time.perf_counter() - t)
        t = time.perf_counter()
        with gw.read() as c: mock.get_records(c, "u001", "analytics", s.internal_token)
        without.append(time.perf_counter() - t)
    for name, xs in (("with PEP (check + audit)", with_check), ("without check", without)):
        print(f"{name:26s} p50={statistics.median(xs)*1000:.2f} ms  p95={pct(xs, .95):.2f} ms  (n={N})")
