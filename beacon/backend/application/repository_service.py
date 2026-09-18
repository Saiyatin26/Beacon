"""BEACON V2 — Repository Ingestion and Analysis Service.

Provides secure, untrusted repository retrieval, revision resolution,
cryptographic content identity hashing, and automated AST/structural analysis.
Strictly avoids shell command interpolation.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from common.config import settings
from certification.adapters import compute_implementation_hash
from ingestion.static_analyzer import PythonAnalyzer

logger = logging.getLogger("beacon.application.repository_service")


def redact_url_credentials(url: str) -> str:
    """Removes sensitive credentials (passwords, tokens) from Git/HTTP URLs."""
    if "@" in url and "://" in url:
        return re.sub(r"://[^@]+@", "://***@", url)
    return url


def validate_path_containment(child_path: Path, root_path: Path) -> Path:
    """Ensures child_path does not escape root_path through directory traversal or symlinks."""
    resolved_root = root_path.resolve()
    resolved_child = child_path.resolve()
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError:
        raise RepositoryIngestionError(f"Path traversal detected: '{child_path}' escapes root '{root_path}'")
    return resolved_child


class RepositorySourceType(str, Enum):
    """Supported source types for repository ingestion."""
    GIT = "git"
    GITHUB = "github"
    LOCAL_PATH = "local_path"
    DIRECTORY = "directory"
    FILE = "file"


class RepositoryIdentity(BaseModel):
    """Immutable, content-addressed identity of a repository source."""
    model_config = ConfigDict(extra="ignore")

    canonical_url: str
    resolved_revision: str
    commit_sha: Optional[str] = None
    content_hash: str


class RepositorySourceSpec(BaseModel):
    """Specification of an external or local repository source provided by the user."""
    model_config = ConfigDict(extra="ignore")

    repository_url: str = Field(..., description="Git URL (HTTPS/SSH) or local directory/file path")
    source_type: RepositorySourceType = RepositorySourceType.GIT
    revision: Optional[str] = Field(None, description="Optional branch, tag, or commit SHA")
    subdirectory: Optional[str] = Field(None, description="Optional subfolder path inside repository")

    def sanitize(self) -> "RepositorySourceSpec":
        """Sanitizes inputs to prevent injection attacks."""
        url = self.repository_url.strip()
        # Reject shell characters
        if any(c in url for c in [";", "&", "|", "`", "$", "\n", "\r"]):
            raise ValueError(f"Repository URL contains illegal shell control characters: '{url}'")

        # Auto-detect local path vs remote git
        stype = self.source_type
        if url.startswith((".", "/", "\\")) or (":" in url and not url.startswith(("http://", "https://", "git@"))):
            stype = RepositorySourceType.LOCAL_PATH
        elif url.startswith(("http://", "https://", "git@")):
            stype = RepositorySourceType.GITHUB if "github.com" in url else RepositorySourceType.GIT

        return RepositorySourceSpec(
            repository_url=url,
            source_type=stype,
            revision=self.revision.strip() if self.revision else None,
            subdirectory=self.subdirectory.strip() if self.subdirectory else None,
        )


class RepositoryProvenance(BaseModel):
    """Cryptographically verifiable provenance metadata for an ingested repository."""
    model_config = ConfigDict(extra="ignore")

    source_url: str
    canonical_source_url: str = ""
    source_type: str
    resolved_revision: str
    commit_sha: Optional[str] = None
    content_hash: str
    retrieval_timestamp: str
    local_path: str
    status: str = "INGESTED"
    identity: Optional[RepositoryIdentity] = None


class DiscoveredEntrypoint(BaseModel):
    """A discovered candidate executable entrypoint in the repository."""
    name: str
    file_path: str
    relative_path: str
    line_number: int
    parameters: list[str] = Field(default_factory=list)
    docstring: Optional[str] = None
    has_type_hints: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class DiscoveredInputAsset(BaseModel):
    """Discovered candidate test or benchmark input asset."""
    file_path: str
    relative_path: str
    format: str  # json, csv, python
    case_count: int = 0
    sample_values: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RepositoryAnalysisReport(BaseModel):
    """Structured report produced by automated repository analysis."""
    model_config = ConfigDict(extra="ignore")

    repository_id: str
    provenance: RepositoryProvenance
    identity: Optional[RepositoryIdentity] = None
    languages: list[str] = Field(default_factory=lambda: ["python"])
    frameworks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    project_structure: list[str] = Field(default_factory=list)
    entrypoint_candidates: list[DiscoveredEntrypoint] = Field(default_factory=list)
    input_candidates: list[DiscoveredInputAsset] = Field(default_factory=list)
    boundary_invariants: list[str] = Field(default_factory=list)


class RepositoryIngestionError(RuntimeError):
    """Raised when repository retrieval, cloning, or verification fails."""
    pass


class RepositoryAnalysisError(RuntimeError):
    """Raised when repository parsing or static analysis fails."""
    pass


class RepositoryService:
    """Secure repository ingestion and automated static analysis orchestrator."""

    def __init__(self, cache_dir: Optional[Path] = None):
        base_dir = Path(getattr(settings, "database_path", "beacon.sqlite3")).resolve().parent
        self.cache_dir = cache_dir or (base_dir / "data" / "repo_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def ingest_repository(self, spec: RepositorySourceSpec) -> tuple[Path, RepositoryProvenance]:
        """Safely ingests, resolves, and hashes an external or local repository."""
        clean_spec = spec.sanitize()
        url = clean_spec.repository_url
        canonical_url = redact_url_credentials(url)

        now_iso = datetime.now(timezone.utc).isoformat()

        # Handle local path
        if clean_spec.source_type == RepositorySourceType.LOCAL_PATH:
            local_p = Path(url).resolve()
            if not local_p.exists():
                # Check relative to beacon project root
                beacon_root = Path(__file__).resolve().parent.parent.parent
                alt_p = (beacon_root / url).resolve()
                if alt_p.exists():
                    local_p = alt_p
                else:
                    raise RepositoryIngestionError(f"Local repository path does not exist: '{url}'")

            target_dir = local_p
            if clean_spec.subdirectory:
                sub_p = validate_path_containment(local_p / clean_spec.subdirectory, local_p)
                if sub_p.exists():
                    target_dir = sub_p
                else:
                    raise RepositoryIngestionError(f"Subdirectory '{clean_spec.subdirectory}' not found in '{local_p}'")

            commit_sha = None
            resolved_rev = clean_spec.revision or "local_head"
            # Try to get git commit SHA if local path is inside a git repo
            try:
                git_proc = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(local_p if local_p.is_dir() else local_p.parent),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if git_proc.returncode == 0:
                    commit_sha = git_proc.stdout.strip()
                    resolved_rev = commit_sha
            except Exception:
                pass

            try:
                content_hash = compute_implementation_hash(target_dir)
            except Exception as exc:
                raise RepositoryIngestionError(f"Failed to compute content hash for local path '{target_dir}': {exc}")

            identity = RepositoryIdentity(
                canonical_url=canonical_url,
                resolved_revision=commit_sha or resolved_rev,
                commit_sha=commit_sha,
                content_hash=content_hash,
            )

            prov = RepositoryProvenance(
                source_url=canonical_url,
                canonical_source_url=canonical_url,
                source_type="local_path",
                resolved_revision=commit_sha or resolved_rev,
                commit_sha=commit_sha,
                content_hash=content_hash,
                retrieval_timestamp=now_iso,
                local_path=str(target_dir),
                status="INGESTED",
                identity=identity,
            )
            return target_dir, prov

        # Handle remote Git repository
        url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
        dest_repo_dir = self.cache_dir / f"repo_{url_hash}"

        if not dest_repo_dir.exists():
            # Safe argument-based git clone (shell=False)
            clone_cmd = ["git", "clone", "--depth", "50", url, str(dest_repo_dir)]
            try:
                proc = subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if proc.returncode != 0:
                    raise RepositoryIngestionError(f"Git clone failed for '{canonical_url}': {proc.stderr.strip()}")
            except subprocess.TimeoutExpired:
                raise RepositoryIngestionError(f"Git clone timed out after 60 seconds for '{canonical_url}'")
            except Exception as exc:
                raise RepositoryIngestionError(f"Git clone execution error for '{canonical_url}': {exc}")
        else:
            # Update existing clone
            try:
                subprocess.run(["git", "fetch", "--all"], cwd=str(dest_repo_dir), capture_output=True, timeout=30, check=False)
            except Exception:
                pass

        # Resolve revision if requested
        commit_sha = None
        if clean_spec.revision:
            checkout_cmd = ["git", "checkout", clean_spec.revision]
            proc = subprocess.run(checkout_cmd, cwd=str(dest_repo_dir), capture_output=True, text=True, timeout=15, check=False)
            if proc.returncode != 0:
                raise RepositoryIngestionError(f"Failed to checkout revision '{clean_spec.revision}' in '{canonical_url}': {proc.stderr.strip()}")

        try:
            rev_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(dest_repo_dir), capture_output=True, text=True, timeout=5, check=False)
            if rev_proc.returncode == 0:
                commit_sha = rev_proc.stdout.strip()
        except Exception:
            pass

        target_dir = dest_repo_dir
        if clean_spec.subdirectory:
            sub_p = validate_path_containment(dest_repo_dir / clean_spec.subdirectory, dest_repo_dir)
            if not sub_p.exists():
                raise RepositoryIngestionError(f"Subdirectory '{clean_spec.subdirectory}' not found in '{canonical_url}'")
            target_dir = sub_p

        try:
            content_hash = compute_implementation_hash(target_dir)
        except Exception as exc:
            raise RepositoryIngestionError(f"Failed to compute content hash for repository '{canonical_url}': {exc}")

        effective_revision = commit_sha or clean_spec.revision or "HEAD"
        identity = RepositoryIdentity(
            canonical_url=canonical_url,
            resolved_revision=effective_revision,
            commit_sha=commit_sha,
            content_hash=content_hash,
        )

        prov = RepositoryProvenance(
            source_url=canonical_url,
            canonical_source_url=canonical_url,
            source_type="git",
            resolved_revision=effective_revision,
            commit_sha=commit_sha,
            content_hash=content_hash,
            retrieval_timestamp=now_iso,
            local_path=str(target_dir),
            status="INGESTED",
            identity=identity,
        )
        return target_dir, prov

    def analyze_repository(self, target_dir: Path, provenance: RepositoryProvenance) -> RepositoryAnalysisReport:
        """Performs comprehensive static and structural analysis on ingested repository contents."""
        if not target_dir.exists():
            raise RepositoryAnalysisError(f"Target repository path does not exist for analysis: '{target_dir}'")

        repo_id = f"REPO-{provenance.content_hash[:12]}"
        languages = set()
        frameworks = set()
        dependencies = []
        structure = []
        entrypoints: list[DiscoveredEntrypoint] = []
        inputs: list[DiscoveredInputAsset] = []
        invariants: list[str] = []

        is_single_file = target_dir.is_file()
        root_dir = target_dir.parent if is_single_file else target_dir

        # 1. Project Structure & Dependency Scanning
        if not is_single_file:
            for item in sorted(target_dir.iterdir(), key=lambda p: p.name):
                if item.name.startswith((".", "__pycache__")):
                    continue
                structure.append(f"{item.name}{'/' if item.is_dir() else ''}")

            req_txt = target_dir / "requirements.txt"
            if req_txt.exists():
                try:
                    lines = req_txt.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for line in lines:
                        clean_l = line.split("#")[0].strip()
                        if clean_l:
                            dependencies.append(clean_l)
                            if any(fw in clean_l.lower() for fw in ["fastapi", "flask", "django", "pydantic"]):
                                frameworks.add(clean_l.split("==")[0].split(">=")[0].strip())
                except Exception:
                    pass

        # 2. Python AST Analysis for Entrypoints & Invariants
        py_analyzer = PythonAnalyzer()
        py_files = [target_dir] if is_single_file and target_dir.suffix == ".py" else list(target_dir.rglob("*.py"))
        py_files = [
            f for f in py_files
            if not f.name.endswith(".pyc")
            and "__pycache__" not in f.parts
            and not f.name.startswith("test_")
        ]

        for py_f in py_files:
            languages.add("python")
            rel_p = str(py_f.relative_to(root_dir)).replace("\\", "/") if not is_single_file else py_f.name
            try:
                code_text = py_f.read_text(encoding="utf-8", errors="ignore")
                ast_res = py_analyzer.analyze(code_text, file_name=rel_p)

                # Collect candidate functions as entrypoints
                for fn in ast_res.functions:
                    # Ignore internal/dunder functions
                    if fn.name.startswith("_") and not fn.name.startswith("__init__"):
                        continue
                    entrypoints.append(
                        DiscoveredEntrypoint(
                            name=fn.name,
                            file_path=str(py_f),
                            relative_path=rel_p,
                            line_number=fn.location.line if fn.location else 1,
                            parameters=fn.arguments if hasattr(fn, "arguments") else [],
                            docstring=fn.docstring if hasattr(fn, "docstring") else None,
                            has_type_hints=bool(getattr(fn, "return_type", None)),
                            evidence={
                                "file": rel_p,
                                "line": fn.location.line if fn.location else 1,
                                "argument_count": len(fn.arguments) if hasattr(fn, "arguments") else 0,
                                "has_docstring": bool(getattr(fn, "docstring", None)),
                            },
                        )
                    )

                # Extract conditions and comparisons as behavioral boundary invariants
                for comp in ast_res.comparisons:
                    invariants.append(f"{comp.left} {comp.operator} {comp.right} (line {comp.location.line if comp.location else '?'})")

            except Exception as exc:
                logger.debug(f"Could not parse Python AST for '{rel_p}': {exc}")

        # 3. Input Assets Discovery (JSON fixtures, test datasets)
        candidate_files = [target_dir] if is_single_file and target_dir.suffix in (".json", ".csv") else list(target_dir.rglob("*.json")) + list(target_dir.rglob("*.csv"))
        candidate_files = [
            f for f in candidate_files
            if not f.name.startswith(".")
            and "package" not in f.name.lower()
            and "tsconfig" not in f.name.lower()
        ]

        for cf in candidate_files:
            rel_p = str(cf.relative_to(root_dir)).replace("\\", "/") if not is_single_file else cf.name
            try:
                if cf.suffix == ".json":
                    raw_data = json.loads(cf.read_text(encoding="utf-8", errors="ignore"))
                    cases = []
                    if isinstance(raw_data, list):
                        cases = [item for item in raw_data if isinstance(item, dict)]
                    elif isinstance(raw_data, dict):
                        if "cases" in raw_data and isinstance(raw_data["cases"], list):
                            cases = raw_data["cases"]
                        elif "inputs" in raw_data and isinstance(raw_data["inputs"], list):
                            cases = raw_data["inputs"]
                        elif "data" in raw_data and isinstance(raw_data["data"], list):
                            cases = raw_data["data"]
                        else:
                            cases = [raw_data]

                    if cases:
                        inputs.append(
                            DiscoveredInputAsset(
                                file_path=str(cf),
                                relative_path=rel_p,
                                format="json",
                                case_count=len(cases),
                                sample_values=cases[:3],
                                evidence={"file": rel_p, "total_cases": len(cases)},
                            )
                        )
            except Exception:
                pass

        return RepositoryAnalysisReport(
            repository_id=repo_id,
            provenance=provenance,
            identity=provenance.identity,
            languages=sorted(list(languages)) or ["python"],
            frameworks=sorted(list(frameworks)),
            dependencies=dependencies,
            project_structure=structure[:20],
            entrypoint_candidates=entrypoints,
            input_candidates=inputs,
            boundary_invariants=invariants[:20],
        )


repository_service = RepositoryService()
