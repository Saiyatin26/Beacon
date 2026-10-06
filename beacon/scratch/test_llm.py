import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from llm.manager import get_provider_manager

pm = get_provider_manager()
resp = pm.generate("Return a JSON object with key status=ok and condition=valid", json_mode=True)
print("SUCCESS:", resp.success)
print("ACTUAL PROVIDER:", resp.provider_name)
print("FALLBACK OCCURRED:", resp.fallback_occurred)
print("FALLBACK CHAIN:", resp.fallback_chain)
print("PARSED:", resp.parsed_json)
