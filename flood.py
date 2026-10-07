#!/usr/bin/env python3
"""Bounded HTTP load test for verifying Fail2Ban protection on local Docker containers."""

from __future__ import annotations

import argparse
import os
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

DEFAULT_TARGETS = (
    ("localhost", 5173),  # Frontend container
    ("localhost", 3001),  # Backend container
    ("localhost", 8081),  # LDAP / Keycloak JWT container
)
REQUEST_TIMEOUT_SECONDS = 2
REPORT_INTERVAL_SECONDS = 3
MAX_DURATION_SECONDS = 300
MAX_CONCURRENCY = 500
MAX_REQUESTS_PER_SECOND = 500


def setting(name: str, default: int, maximum: int) -> int:
    """Read and validate a bounded positive integer from the environment."""
    raw_value = os.environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise SystemExit(f"{name} must be an integer; got {raw_value!r}") from error

    if not 1 <= value <= maximum:
        raise SystemExit(f"{name} must be between 1 and {maximum}; got {value}")
    return value


def request_status(opener: urllib.request.OpenerDirector, host: str, port: int) -> str:
    """Perform one GET to http://host:port/ and return its HTTP status, or 000 on failure."""
    url = f"http://{host}:{port}/"
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return str(response.status)
    except urllib.error.HTTPError as error:
        return str(error.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "000"


class RateLimiter:
    """Limit aggregate request starts across all workers for one target."""

    def __init__(self, requests_per_second: int) -> None:
        self.interval = 1 / requests_per_second
        self.next_request_at = 0.0
        self.lock = threading.Lock()

    def wait_for_turn(self, stop_event: threading.Event) -> bool:
        with self.lock:
            now = time.monotonic()
            scheduled_at = max(now, self.next_request_at)
            self.next_request_at = scheduled_at + self.interval
        return not stop_event.wait(max(0.0, scheduled_at - now))


def worker(
    host: str,
    port: int,
    deadline: float,
    stop_event: threading.Event,
    rate_limiter: RateLimiter,
    counts: Counter[str],
    counts_lock: threading.Lock,
) -> None:
    """Send requests until this target's fixed deadline or an interrupt."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not stop_event.is_set() and time.monotonic() < deadline:
        if not rate_limiter.wait_for_turn(stop_event):
            break
        if time.monotonic() >= deadline:
            break
        code = request_status(opener, host, port)
        with counts_lock:
            counts[code] += 1


def snapshot(counts: Counter[str], counts_lock: threading.Lock) -> Counter[str]:
    with counts_lock:
        return counts.copy()


def report(target_label: str, counts: Counter[str], final: bool = False) -> None:
    total = sum(counts.values())
    ok = counts["200"]
    failed = total - ok
    label = "RESULT" if final else f"[{datetime.now():%H:%M:%S}] requests so far"
    print(
        f"  {label} for {target_label}: total={total} ok(200)={ok} blocked/failed={failed}",
        flush=True,
    )
    if final and total:
        print(f"  -> {failed * 100 // total}% of responses were non-200", flush=True)


def run_target(
    host: str, port: int, concurrency: int, duration: int, requests_per_second: int
) -> bool:
    """Run one bounded target test; return False if interrupted by Ctrl-C."""
    target_label = f"{host}:{port}"
    print(
        f"\n--- Target: http://{target_label}/ ({concurrency} workers, "
        f"{requests_per_second} requests/s max, {duration}s) ---",
        flush=True,
    )
    counts: Counter[str] = Counter()
    counts_lock = threading.Lock()
    stop_event = threading.Event()
    rate_limiter = RateLimiter(requests_per_second)
    deadline = time.monotonic() + duration
    interrupted = False

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                worker,
                host,
                port,
                deadline,
                stop_event,
                rate_limiter,
                counts,
                counts_lock,
            )
            for _ in range(concurrency)
        ]
        try:
            while time.monotonic() < deadline:
                time.sleep(min(REPORT_INTERVAL_SECONDS, deadline - time.monotonic()))
                report(target_label, snapshot(counts, counts_lock))
        except KeyboardInterrupt:
            interrupted = True
            stop_event.set()
            print("\nStopping workers after Ctrl-C...", flush=True)
        finally:
            stop_event.set()

        for future in futures:
            future.result()

    report(target_label, snapshot(counts, counts_lock), final=True)
    return not interrupted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded HTTP load test for local Fail2Ban-protected containers."
    )
    parser.add_argument(
        "host",
        nargs="?",
        default=None,
        help="Target host or IP (e.g., localhost or 127.0.0.1)",
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=None,
        help="Target TCP port (e.g., 5173 for Frontend, 3001 for Backend, 8081 for LDAP/Keycloak)",
    )
    parser.add_argument(
        "--host",
        dest="opt_host",
        default=None,
        help="Target host (optional named flag)",
    )
    parser.add_argument(
        "--port",
        dest="opt_port",
        type=int,
        default=None,
        help="Target port (optional named flag)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help=f"Duration in seconds per target (1..{MAX_DURATION_SECONDS})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help=f"Number of concurrent workers (1..{MAX_CONCURRENCY})",
    )
    parser.add_argument(
        "--rps",
        type=int,
        default=None,
        help=f"Max requests per second (1..{MAX_REQUESTS_PER_SECOND})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.duration is not None:
        os.environ["DURATION"] = str(args.duration)
    if args.concurrency is not None:
        os.environ["CONCURRENCY"] = str(args.concurrency)
    if args.rps is not None:
        os.environ["REQUESTS_PER_SECOND"] = str(args.rps)

    duration = setting("DURATION", default=20, maximum=MAX_DURATION_SECONDS)
    concurrency = setting("CONCURRENCY", default=40, maximum=MAX_CONCURRENCY)
    requests_per_second = setting(
        "REQUESTS_PER_SECOND", default=80, maximum=MAX_REQUESTS_PER_SECOND
    )

    host = args.opt_host or args.host
    port = args.opt_port or args.port

    if host and port:
        targets = [(host, port)]
    elif host and not port:
        targets = [(host, 80)]
    else:
        targets = list(DEFAULT_TARGETS)

    print(
        "=== Bounded HTTP Fail2Ban test: "
        f"{concurrency} workers, up to {requests_per_second} requests/s, "
        f"{duration}s per target ===",
        flush=True,
    )
    for target_host, target_port in targets:
        if not run_target(
            target_host, target_port, concurrency, duration, requests_per_second
        ):
            break

    print("\n=== Test finished; only the configured lab targets were contacted. ===")
    print("A non-200 result can be a Fail2Ban ban, an HTTP error, or a connection timeout.")


if __name__ == "__main__":
    main()
