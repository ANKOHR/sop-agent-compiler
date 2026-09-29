"""Deterministic SVG renderer for a plan's state machine."""

from __future__ import annotations

from html import escape
from pathlib import Path

from .model import Plan, Step


def render_svg(plan: Plan) -> str:
    width = 1000
    row_height = 118
    height = max(280, 150 + row_height * len(plan.steps))
    positions = {step.id: (365, 90 + index * row_height) for index, step in enumerate(plan.steps)}
    error_pos = (760, 90 + max(0, len(plan.steps) - 1) * row_height)
    rejected_pos = (760, min(height - 90, 90 + max(0, len(plan.steps) - 1) * row_height + 90))
    edges: list[tuple[str, str, str, str]] = []
    for step in plan.steps:
        if step.kind == "decision":
            _edge(edges, step.id, step.true_step, "true")
            _edge(edges, step.id, step.false_step, "false")
        elif step.kind == "parallel":
            for index, branch in enumerate(step.branches, 1):
                _edge(edges, step.id, branch, f"parallel {index}")
            _edge(edges, step.id, step.join_step, "join after all branches", "dashed")
        elif step.kind == "checkpoint":
            _edge(edges, step.id, step.next_step, "approve")
            config = step.checkpoint_config
            reject = config.on_reject if config else None
            edit = config.on_edit if config else None
            edges.append((step.id, reject or "__REJECTED__", "reject", "solid"))
            if edit:
                _edge(edges, step.id, edit, "edit with reason")
            if reject is None:
                _edge(edges, "__REJECTED__", "__REJECTED__", "", "hidden")
        else:
            _edge(edges, step.id, step.next_step, "next")
        if step.kind == "action":
            attempts = step.retry_policy.attempts
            if attempts > 1:
                edges.append((step.id, step.id, f"retry, {step.retry_policy.backoff_ms}ms backoff", "dashed"))
            edges.append((step.id, "__ERROR__", "error after retries", "solid"))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#536273"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="40" y="38" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#17212b">{escape(plan.title)}</text>',
    ]
    for source, target, label, style in edges:
        if style == "hidden":
            continue
        if source not in positions:
            continue
        sx, sy = positions[source]
        if target in positions:
            tx, ty = positions[target]
            if source == target:
                x1, y1, x2, y2 = sx + 180, sy + 20, sx + 205, sy - 8
                path = f"M{x1} {y1} C {x2} {y2}, {x2 + 18} {y2 + 18}, {x1} {sy + 40}"
                lx, ly = x2 + 6, y2 - 4
            else:
                x1, y1, x2, y2 = sx + 90, sy + 64, tx + 90, ty
                bend = (y1 + y2) / 2
                path = f"M{x1} {y1} C {x1} {bend}, {x2} {bend}, {x2} {y2}"
                lx, ly = min(x1, x2) + 12, bend - 4
        elif target == "__ERROR__":
            tx, ty = error_pos
            x1, y1, x2, y2 = sx + 180, sy + 32, tx, ty + 22
            path = f"M{x1} {y1} C {x1 + 80} {y1}, {x2 - 60} {y2}, {x2} {y2}"
            lx, ly = x1 + 45, y1 - 8
        else:
            tx, ty = rejected_pos
            x1, y1, x2, y2 = sx + 180, sy + 44, tx, ty + 22
            path = f"M{x1} {y1} C {x1 + 45} {y1}, {x2 - 45} {y2}, {x2} {y2}"
            lx, ly = x1 + 25, y1 + 12
        dash = ' stroke-dasharray="6 5"' if style == "dashed" else ""
        parts.append(f'<path d="{path}" fill="none" stroke="#536273" stroke-width="1.5"{dash} marker-end="url(#arrow)"/>')
        if label:
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-family="Arial, sans-serif" font-size="12" fill="#384657">{escape(label)}</text>')

    for step in plan.steps:
        x, y = positions[step.id]
        label = f"{step.id} [{step.kind}]"
        fill = {"action": "#edf3fa", "decision": "#fff4d6", "checkpoint": "#e8f6ee", "parallel": "#f0eafa"}[step.kind]
        if step.kind == "checkpoint":
            parts.append(f'<rect x="{x}" y="{y}" width="180" height="64" rx="18" fill="{fill}" stroke="#20864a" stroke-width="2"/>')
            parts.append(f'<text x="{x + 90}" y="{y + 27}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#17212b">{escape(label)}</text>')
            parts.append(f'<text x="{x + 90}" y="{y + 47}" text-anchor="middle" font-family="Arial, sans-serif" font-size="11" fill="#384657">human approval</text>')
        elif step.kind == "decision":
            parts.append(f'<polygon points="{x + 90},{y} {x + 180},{y + 32} {x + 90},{y + 64} {x},{y + 32}" fill="{fill}" stroke="#b07c00" stroke-width="2"/>')
            parts.append(f'<text x="{x + 90}" y="{y + 37}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#17212b">{escape(label)}</text>')
        else:
            parts.append(f'<rect x="{x}" y="{y}" width="180" height="64" rx="6" fill="{fill}" stroke="#536273" stroke-width="1.5"/>')
            parts.append(f'<text x="{x + 90}" y="{y + 37}" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#17212b">{escape(label)}</text>')
    parts.extend([
        f'<rect x="{error_pos[0]}" y="{error_pos[1]}" width="170" height="44" rx="6" fill="#fdecec" stroke="#bb3232" stroke-width="2"/>',
        f'<text x="{error_pos[0] + 85}" y="{error_pos[1] + 27}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#862323">ERROR / retries exhausted</text>',
        f'<rect x="{rejected_pos[0]}" y="{rejected_pos[1]}" width="170" height="44" rx="6" fill="#fff0e6" stroke="#bc6521" stroke-width="2"/>',
        f'<text x="{rejected_pos[0] + 85}" y="{rejected_pos[1] + 27}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#7b4218">REJECTED</text>',
        "</svg>",
    ])
    return "\n".join(parts) + "\n"


def write_svg(plan: Plan, path: str | Path) -> None:
    Path(path).write_text(render_svg(plan), encoding="utf-8", newline="\n")


def _edge(edges: list[tuple[str, str, str, str]], source: str, target: str | None, label: str, style: str = "solid") -> None:
    if target:
        edges.append((source, target, label, style))
