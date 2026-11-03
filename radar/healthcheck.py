"""Daily watchdog: warns via ntfy when an OFFICIAL source is down or data is stale.

    python -m radar.healthcheck            # real check (GitHub Actions, daily)
    python -m radar.healthcheck --dry-run  # prints the problems only
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from .notify import Message, Notifier, pages_url
from .store import load_json
from .util import parse_iso, utcnow

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_DOWN = timedelta(hours=6)
STALE = timedelta(hours=1)


def problems(health: dict | None, now) -> list[str]:
    if not health:
        return ["health.json não existe — o radar ainda não correu."]
    out = []
    generated = parse_iso(health.get("generated_at"))
    if generated is None or now - generated > STALE:
        mins = int((now - generated).total_seconds() // 60) if generated else None
        out.append(f"dados parados há {mins} min" if mins is not None else "sem generated_at")
    for sid, e in (health.get("sources") or {}).items():
        if not e.get("enabled", True) or e.get("tier") != "official" or not e.get("error"):
            continue
        last_ok = parse_iso(e.get("last_success"))
        if last_ok is None or now - last_ok > OFFICIAL_DOWN:
            since = f"desde {e.get('last_success')}" if last_ok else "nunca funcionou"
            out.append(f"fonte {e.get('name', sid)} em baixo ({since}): {e.get('error', '')[:80]}")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    health = load_json(Path(args.root) / "docs" / "data" / "health.json", None)
    found = problems(health, utcnow())
    if not found:
        print("Radar saudável.")
        return 0
    for p in found:
        print("PROBLEMA:", p)
    if args.dry_run:
        return 0
    notifier = Notifier.from_env()
    if not notifier.enabled:
        print("NTFY_TOPIC não definido: alerta não enviado.")
        return 0
    first = found[0]
    title = f"⚠️ Radar: {first}" if len(found) == 1 else f"⚠️ Radar: {len(found)} problemas"
    notifier.send(Message(title=title[:250], body="\n".join(found)[:1000], priority=4,
                          tags=["warning"], click=pages_url() + "#sobre"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
