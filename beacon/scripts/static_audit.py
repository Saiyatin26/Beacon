import os
import re
import sys

forbidden_patterns = [
    (re.compile(r'("legacy"|"modern"|"ref"|"target")\s+in\s+[a-zA-Z_0-9]+(\.evidence_id|\.id|\[[\'"]id[\'"]\])', re.IGNORECASE), 'Evidence ID substring heuristic'),
    (re.compile(r'unresolved_evidence\[[01]\]'), 'Positional evidence role heuristic'),
    (re.compile(r'get\(\s*["\']dimension["\']\s*,\s*["\']OUTPUT["\']\s*\)'), 'Default dimension OUTPUT fallback'),
    (re.compile(r'FROM\s+threshold_resolutions.*ORDER\s+BY.*LIMIT', re.IGNORECASE | re.DOTALL), 'Latest threshold resolution fallback'),
    (re.compile(r'valid_evidence_ids\[:5\]'), 'Arbitrary top-5 evidence grounding'),
    (re.compile(r'elif\s+pol_ver'), 'Policy version threshold fallback'),
    (re.compile(r'ref_val\s*==\s*tgt_val'), 'Ad-hoc output equality comparison bypassing Phase 4 BehavioralEvaluationEngine'),
    (re.compile(r'cls_str\s*=\s*"MATCH"\s*if\s*ref_val\s*==\s*tgt_val'), 'Ad-hoc certification case reconstruction bypassing EvaluationResult'),
    (re.compile(r'ThresholdPolicy\(.*FIXED.*0\.0'), 'Default zero-diff threshold policy fallback creation in workflow'),
]

violations = []
backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend')

for root, dirs, files in os.walk(backend_dir):
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                for line_no, line in enumerate(f, 1):
                    for pat, desc in forbidden_patterns:
                        if pat.search(line):
                            violations.append(f'{path}:{line_no}: {desc} -> {line.strip()}')

if violations:
    print(f'FAILED: {len(violations)} violations found:')
    for v in violations:
        print('  -', v)
    sys.exit(1)
else:
    print('STATIC AUDIT PASSED: 0 forbidden patterns found in backend codebase.')
    sys.exit(0)

