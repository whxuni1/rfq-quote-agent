"""Sandboxed tool worker: `python -m personal_agent.tools.worker`, request JSON on stdin.

Runs with a scrubbed environment; credentials arrive only in the request payload.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any


def main() -> None:
    req: dict[str, Any] = json.loads(sys.stdin.read())
    from personal_agent.tools.base import ToolContext, ToolOutput

    module_name, fn_name = req["fn"].split(":")
    fn = getattr(importlib.import_module(module_name), fn_name)
    try:
        out = fn(req["args"], ToolContext.model_validate(req["ctx"]))
        if not isinstance(out, ToolOutput):
            out = ToolOutput(output=out)
        resp: dict[str, Any] = {"ok": True, **out.model_dump(mode="json")}
    except Exception as e:  # report every failure to the runner as data
        resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(resp, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
