"""Shared Jinja2 environment for SystemVerilog generators.

Templates live next to the generated `.sv` under `src/` with `.sv.j2`
extension. The "AUTO-GENERATED" preamble is the template's responsibility.
"""

from __future__ import annotations

from pathlib import Path

import jinja2


def _build_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(Path(__file__).resolve().parent.parent)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


_ENV = _build_env()


def render_sv(template_rel: str, out_path: Path | str, **context: object) -> str:
    text = _ENV.get_template(template_rel).render(**context)
    Path(out_path).write_text(text)
    return text
