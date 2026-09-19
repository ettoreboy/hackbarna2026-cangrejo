"""Read-only contract check on extension/ before loading it into Chrome or Firefox.

The extension is Diana's tree and the backend is mine; the two agree on three things and
nothing enforces them at runtime: the signal vocabulary (CLAUDE.md rule 3), the verdict
values, and the port the drawer calls. This script reads both sides and compares. It never
writes to extension/.

    python scripts/check_extension.py            # checks against PORT from .env
    python scripts/check_extension.py --port 9000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"

sys.path.insert(0, str(ROOT))

from backend.prompts.taxonomy import HIGH_RISK_SIGNALS  # noqa: E402
from backend.schemas.analysis_schema import VERDICTS  # noqa: E402

OK, BAD = "  ok   ", "  FAIL "


def js_string_set(source: str, const_name: str) -> set[str]:
    """Pull `const NAME = new Set(["a", "b"])` out of a JS file without running it."""
    m = re.search(rf"{const_name}\s*=\s*new Set\(\[(.*?)\]\)", source, re.S)
    if not m:
        return set()
    return {a or b for a, b in re.findall(r'"([^"]*)"|\'([^\']*)\'', m.group(1))}


def js_object_keys(source: str, const_name: str) -> set[str]:
    """Keys of `const NAME = { key: {...}, ... }`, taken from the first brace block."""
    m = re.search(rf"{const_name}\s*=\s*\{{(.*?)\n\s*\}};", source, re.S)
    if not m:
        return set()
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", m.group(1), re.M))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None, help="backend port the extension must be allowed to call")
    args = ap.parse_args()

    port = args.port
    if port is None:
        from backend.config import get_settings

        port = get_settings().port

    failures: list[str] = []

    def check(passed: bool, message: str) -> None:
        print((OK if passed else BAD) + message)
        if not passed:
            failures.append(message)

    manifest_path = EXT / "manifest.json"
    if not manifest_path.exists():
        print(f"{BAD}no extension/manifest.json")
        return 1
    manifest = json.loads(manifest_path.read_text())

    print(f"{manifest['name']} v{manifest['version']}  ({EXT})\n")

    check(manifest.get("manifest_version") == 3, "manifest_version is 3")

    # Every file the manifest names must exist, or Chrome refuses the whole extension.
    listed: list[str] = []
    for block in manifest.get("content_scripts", []):
        listed += block.get("js", []) + block.get("css", [])
    background_block = manifest.get("background", {})
    listed.append(background_block.get("service_worker", ""))
    listed += background_block.get("scripts", [])
    listed += list(manifest.get("icons", {}).values())
    missing = [f for f in listed if f and not (EXT / f).exists()]
    check(not missing, f"all {len(listed)} referenced files exist" + (f" — missing {missing}" if missing else ""))

    hosts = manifest.get("host_permissions", [])
    check(any(f":{port}/" in h for h in hosts), f"host_permissions cover port {port} — {hosts}")

    background = (EXT / "background" / "background.js").read_text()
    m = re.search(r'DEFAULT_BACKEND\s*=\s*"([^"]+)"', background)
    default_backend = m.group(1) if m else ""
    check(bool(default_backend) and f":{port}" in default_backend, f"DEFAULT_BACKEND is {default_backend or '(not found)'}")
    check(any(default_backend.startswith(h.rstrip("/*")) for h in hosts), "DEFAULT_BACKEND is inside host_permissions")

    # Firefox release runs an event page, not an MV3 service worker, and refuses storage.sync
    # without a stable add-on id. Both browsers read one manifest, so both keys must stay.
    check(bool(background_block.get("service_worker")), "background.service_worker is set (Chrome)")
    check(bool(background_block.get("scripts")), "background.scripts is set (Firefox)")
    gecko_id = manifest.get("browser_specific_settings", {}).get("gecko", {}).get("id", "")
    check(bool(gecko_id), f"browser_specific_settings.gecko.id is {gecko_id or '(not set)'} — storage.sync needs it in Firefox")

    # `chrome.*` is callback-flavoured in Firefox, so an awaited call there returns undefined.
    # Every call must go through the `globalThis.browser ?? globalThis.chrome` shim.
    bare = []
    for js in sorted(EXT.rglob("*.js")):
        for n, line in enumerate(js.read_text().splitlines(), 1):
            if re.search(r"(?<![\w.])chrome\.(runtime|storage|tabs|action|scripting)\b", line) and not line.lstrip().startswith("//"):
                bare.append(f"{js.relative_to(EXT)}:{n}")
    check(not bare, "no bare chrome.* calls" + (f" — {bare}" if bare else " (browser/chrome shim used everywhere)"))

    taxonomy = (EXT / "content" / "taxonomy.js").read_text()

    ext_verdicts = js_object_keys(taxonomy, "VERDICTS")
    check(ext_verdicts == set(VERDICTS), f"verdicts match the schema — extra {sorted(ext_verdicts - set(VERDICTS))}, missing {sorted(set(VERDICTS) - ext_verdicts)}")

    ext_high_risk = js_string_set(taxonomy, "HIGH_RISK")
    check(ext_high_risk == set(HIGH_RISK_SIGNALS), f"high-risk signals match taxonomy.py — extra {sorted(ext_high_risk - set(HIGH_RISK_SIGNALS))}, missing {sorted(set(HIGH_RISK_SIGNALS) - ext_high_risk)}")

    print()
    if failures:
        print(f"{len(failures)} problem(s). The extension and the backend disagree; fix before the demo.")
        return 1
    print("extension and backend agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
