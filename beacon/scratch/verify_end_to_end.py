import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from application.repository_service import repository_service, SourceIngestionMode, AnalysisScope
from application.adapter_detector import adapter_detector
from application.input_discovery import input_discovery_engine
from api.workflow_router import _perform_repository_analysis, _run_repository_certification_pipeline, RepositoryCertificationRequest
from auth.models import User, UserRole

user = User(user_id="usr_admin", username="admin", email="admin@beacon.local", role=UserRole.SYSTEM_ADMIN, password_hash="test")

upload_id = "upl_1d779dd67884"
req = RepositoryCertificationRequest(
    source_mode=SourceIngestionMode.UPLOADED_FILES,
    analysis_scope=AnalysisScope.REPOSITORY,
    upload_id=upload_id,
    evaluation_mode="FULL_BEACON",
    explain=True,
    explanation_mode="auto",
    force_recompute=True,
)

print(f"Executing repository certification for upload {upload_id}...")
res = _run_repository_certification_pipeline(req, user)

print("\n" + "="*60)
print(f"WORKFLOW RUN ID: {res.workflow_run_id}")
print(f"CERTIFICATION STATUS: {res.status}")
print(f"CERTIFIED: {res.certified}")
print(f"EQUIVALENCE SCORE: {res.equivalence_score}")
print(f"REGRESSIONS COUNT: {res.regressions_count}")
print(f"ERROR MESSAGE: {res.error_message}")

meta = res.metadata or {}
print(f"INPUTS COUNT: {meta.get('inputs_count')}")
inp_disc = meta.get("input_discovery", {})
print(f"DISCOVERY METHOD: {inp_disc.get('discovery_method')}")
print(f"DISCOVERY SOURCE: {inp_disc.get('source')}")

rules = meta.get("discovered_rules", [])
print(f"DISCOVERED RULES COUNT: {len(rules)}")
for r in rules[:5]:
    print(f"  [{r.get('rule_id')}] ({r.get('discovery_method')}) {r.get('description')}")

th = meta.get("threshold_resolution", {})
print(f"THRESHOLD: {th.get('final_value')} (Strategy: {th.get('strategy')}, Status: {th.get('status')})")

cases = meta.get("representative_cases", [])
print(f"REPRESENTATIVE CASES COUNT: {len(cases)}")
for c in cases[:3]:
    print(f"  Case #{c.get('case_index')}: legacy={c.get('legacy_output')} vs modern={c.get('modern_output')}")

expl = res.explanation
if expl:
    verdict = expl.get("verdict") if isinstance(expl, dict) else getattr(expl, "verdict", "")
    summary = expl.get("summary") if isinstance(expl, dict) else getattr(expl, "summary", "")
    print(f"EXPLANATION VERDICT: {verdict}")
    print(f"EXPLANATION SUMMARY: {summary}")
print("="*60)
