"""BEACON V2 — Phase 3 Application Readiness & Health Detection Engine.

Provides generic, deterministic readiness strategies (immediate, process-alive, TCP port,
HTTP endpoint, and adapter-defined) with configurable polling intervals and timeouts.
"""

from enum import Enum
import logging
import socket
import time
from typing import Any, Callable, Optional, Union
import urllib.request
import urllib.error
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("beacon.execution.readiness")


class ReadinessStrategy(str, Enum):
    """Supported readiness verification strategies."""
    IMMEDIATE = "immediate"
    PROCESS_ALIVE = "process_alive"
    TCP_PORT = "tcp_port"
    HTTP_ENDPOINT = "http_endpoint"
    ADAPTER_DEFINED = "adapter_defined"


class ReadinessConfig(BaseModel):
    """Configuration options for application readiness polling."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: ReadinessStrategy = ReadinessStrategy.IMMEDIATE
    timeout_seconds: float = 10.0
    poll_interval_seconds: float = 0.25
    target: Optional[str] = None  # e.g., "8080" for port, or "http://127.0.0.1:8080/health"
    expected_status_code: int = 200
    custom_probe: Optional[Any] = None  # Callable probe function if strategy is ADAPTER_DEFINED



class ReadinessResult(BaseModel):
    """Outcome of a readiness evaluation attempt."""
    ready: bool
    strategy: ReadinessStrategy
    duration_ms: float
    diagnostics: str = ""
    error: Optional[str] = None
    poll_attempts: int = 1


class ReadinessChecker:
    """Evaluates readiness of an application or adapter before executing inputs."""

    @classmethod
    def check_immediate(cls) -> ReadinessResult:
        return ReadinessResult(
            ready=True,
            strategy=ReadinessStrategy.IMMEDIATE,
            duration_ms=0.0,
            diagnostics="Immediate readiness assumed.",
            poll_attempts=1,
        )

    @classmethod
    def check_tcp_port(cls, host: str, port: int, timeout_sec: float) -> bool:
        """Attempts to connect to a TCP port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(max(0.5, min(timeout_sec, 2.0)))
        try:
            sock.connect((host, port))
            sock.close()
            return True
        except (socket.error, OSError):
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @classmethod
    def check_http_endpoint(cls, url: str, expected_code: int, timeout_sec: float) -> tuple[bool, str]:
        """Attempts an HTTP GET request to verify health/readiness endpoint."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BEACON-ReadinessProbe/2.0"})
            with urllib.request.urlopen(req, timeout=max(0.5, min(timeout_sec, 2.0))) as resp:
                if resp.status == expected_code or (200 <= resp.status < 300):
                    return True, f"HTTP status {resp.status} OK."
                return False, f"HTTP status {resp.status} != expected {expected_code}."
        except urllib.error.HTTPError as exc:
            if exc.code == expected_code:
                return True, f"HTTP status {exc.code} matched expected."
            return False, f"HTTP error {exc.code}: {exc.reason}"
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    @classmethod
    def wait_until_ready(
        cls,
        config: Optional[ReadinessConfig] = None,
        adapter: Optional[Any] = None,
        process: Optional[Any] = None,
    ) -> ReadinessResult:
        """Polls until the application reaches operational readiness or timeout occurs."""
        cfg = config or ReadinessConfig()
        if cfg.strategy == ReadinessStrategy.IMMEDIATE:
            return cls.check_immediate()

        start_time = time.perf_counter()
        deadline = start_time + cfg.timeout_seconds
        attempts = 0
        last_diagnostic = ""
        last_error = None

        logger.info(
            f"[READINESS] Waiting for readiness (strategy={cfg.strategy.value}, "
            f"timeout={cfg.timeout_seconds}s, poll_interval={cfg.poll_interval_seconds}s)"
        )

        while time.perf_counter() < deadline:
            attempts += 1

            if cfg.strategy == ReadinessStrategy.PROCESS_ALIVE:
                if process is not None:
                    poll_res = process.poll()
                    if poll_res is None:
                        # Process is running
                        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                        return ReadinessResult(
                            ready=True,
                            strategy=cfg.strategy,
                            duration_ms=elapsed_ms,
                            diagnostics=f"Process PID {getattr(process, 'pid', 'unknown')} is alive and running.",
                            poll_attempts=attempts,
                        )
                    else:
                        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                        return ReadinessResult(
                            ready=False,
                            strategy=cfg.strategy,
                            duration_ms=elapsed_ms,
                            diagnostics=f"Process terminated prematurely with exit code {poll_res}.",
                            error=f"Process exited with code {poll_res}",
                            poll_attempts=attempts,
                        )
                else:
                    last_diagnostic = "No process handle provided for PROCESS_ALIVE check."

            elif cfg.strategy == ReadinessStrategy.TCP_PORT:
                host = "127.0.0.1"
                port = 8080
                if cfg.target:
                    if ":" in cfg.target:
                        parts = cfg.target.split(":")
                        host = parts[0] or "127.0.0.1"
                        try:
                            port = int(parts[1])
                        except ValueError:
                            pass
                    else:
                        try:
                            port = int(cfg.target)
                        except ValueError:
                            pass

                if cls.check_tcp_port(host, port, timeout_sec=cfg.poll_interval_seconds):
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                    return ReadinessResult(
                        ready=True,
                        strategy=cfg.strategy,
                        duration_ms=elapsed_ms,
                        diagnostics=f"TCP connection established to {host}:{port}.",
                        poll_attempts=attempts,
                    )
                else:
                    last_diagnostic = f"Port {host}:{port} not yet reachable."

            elif cfg.strategy == ReadinessStrategy.HTTP_ENDPOINT:
                url = cfg.target or "http://127.0.0.1:8080/health"
                ok, diag = cls.check_http_endpoint(url, cfg.expected_status_code, cfg.poll_interval_seconds)
                if ok:
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                    return ReadinessResult(
                        ready=True,
                        strategy=cfg.strategy,
                        duration_ms=elapsed_ms,
                        diagnostics=diag,
                        poll_attempts=attempts,
                    )
                else:
                    last_diagnostic = diag

            elif cfg.strategy == ReadinessStrategy.ADAPTER_DEFINED:
                if callable(cfg.custom_probe):
                    try:
                        probe_res = cfg.custom_probe()
                        if probe_res is True or (isinstance(probe_res, dict) and probe_res.get("ready")):
                            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                            return ReadinessResult(
                                ready=True,
                                strategy=cfg.strategy,
                                duration_ms=elapsed_ms,
                                diagnostics="Custom probe confirmed readiness.",
                                poll_attempts=attempts,
                            )
                        else:
                            last_diagnostic = f"Custom probe returned not ready: {probe_res}"
                    except Exception as exc:
                        last_error = str(exc)
                        last_diagnostic = f"Custom probe exception: {exc}"
                elif adapter and hasattr(adapter, "health_check"):
                    try:
                        h = adapter.health_check()
                        if getattr(h, "is_ready", False):
                            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                            return ReadinessResult(
                                ready=True,
                                strategy=cfg.strategy,
                                duration_ms=elapsed_ms,
                                diagnostics=getattr(h, "diagnostics", "Adapter ready."),
                                poll_attempts=attempts,
                            )
                        else:
                            last_diagnostic = getattr(h, "diagnostics", "Adapter reports not ready.")
                    except Exception as exc:
                        last_error = str(exc)
                        last_diagnostic = f"Adapter health_check exception: {exc}"
                else:
                    last_diagnostic = "No custom probe or adapter with health_check provided."

            time.sleep(cfg.poll_interval_seconds)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
        return ReadinessResult(
            ready=False,
            strategy=cfg.strategy,
            duration_ms=elapsed_ms,
            diagnostics=f"Readiness check timed out after {cfg.timeout_seconds}s. Last state: {last_diagnostic}",
            error=last_error or f"Readiness timeout after {cfg.timeout_seconds}s",
            poll_attempts=attempts,
        )
