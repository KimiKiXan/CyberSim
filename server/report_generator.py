"""Markdown / PDF report generator with CVSS + success-rate metrics."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from config.settings import CONFIG


class ReportFormat(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    JSON = "json"


@dataclass
class ReportData:
    session_id: str
    objective: str
    targets: list[str]
    started_at: str
    finished_at: str
    metrics: dict[str, Any]
    transcript: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    final_report: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "objective": self.objective,
            "targets": self.targets,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metrics": self.metrics,
            "transcript": self.transcript,
            "tool_results": self.tool_results,
            "final_report": self.final_report,
        }


class ReportGenerator:
    """Builds operator-grade reports from a finished AttackSession."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or CONFIG.paths.reports
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ build
    def build(self, data: ReportData, fmt: ReportFormat) -> Path:
        if fmt is ReportFormat.MARKDOWN:
            return self._write_markdown(data)
        if fmt is ReportFormat.JSON:
            return self._write_json(data)
        if fmt is ReportFormat.PDF:
            return self._write_pdf(data)
        raise ValueError(f"unsupported report format: {fmt}")

    # ----------------------------------------------------------- aggregations
    @staticmethod
    def aggregate_metrics(data: ReportData) -> dict[str, Any]:
        success = sum(1 for t in data.tool_results if t.get("status") == "ok")
        blocked = sum(1 for t in data.tool_results if t.get("status") == "blocked")
        errors = sum(1 for t in data.tool_results if t.get("status") == "error")
        total = len(data.tool_results) or 1

        cvss_scores: list[float] = []
        findings: list[dict[str, Any]] = []
        for tr in data.tool_results:
            tool_data = tr.get("data") or {}
            # nuclei findings
            for f in tool_data.get("findings", []) or []:
                if isinstance(f, dict):
                    cvss = _safe_float(f.get("cvss"))
                    if cvss is not None:
                        cvss_scores.append(cvss)
                    findings.append({
                        "tool": tr.get("tool"),
                        "name": f.get("name") or f.get("template") or f.get("path"),
                        "severity": f.get("severity") or "info",
                        "cvss": cvss,
                        "where": f.get("matched_at") or f.get("path"),
                        "cve": f.get("cve"),
                    })
            # sqlmap injections
            for inj in tool_data.get("injections", []) or []:
                findings.append({
                    "tool": tr.get("tool"),
                    "name": f"SQLi via parameter {inj.get('parameter')}",
                    "severity": "high",
                    "cvss": 7.5,
                    "where": tr.get("arguments", {}).get("target"),
                })
                cvss_scores.append(7.5)
            # hydra creds
            for cred in tool_data.get("credentials", []) or []:
                findings.append({
                    "tool": tr.get("tool"),
                    "name": f"Valid credential {cred.get('user')}:{cred.get('password')}",
                    "severity": "high",
                    "cvss": 8.1,
                    "where": cred.get("host"),
                })
                cvss_scores.append(8.1)
            # msf sessions
            for sess in tool_data.get("sessions", []) or []:
                findings.append({
                    "tool": tr.get("tool"),
                    "name": f"Metasploit session opened ({sess.get('type', 'shell')})",
                    "severity": "critical",
                    "cvss": 9.8,
                    "where": sess.get("tunnel_peer") or sess.get("session_host"),
                })
                cvss_scores.append(9.8)

        return {
            "tool_calls_total": len(data.tool_results),
            "tool_success": success,
            "tool_errors": errors,
            "tool_blocked": blocked,
            "success_rate": round(success / total, 3),
            "findings_total": len(findings),
            "findings": findings,
            "max_cvss": round(max(cvss_scores), 1) if cvss_scores else 0.0,
            "avg_cvss": round(sum(cvss_scores) / len(cvss_scores), 1) if cvss_scores else 0.0,
        }

    # ----------------------------------------------------------- file writers
    def _write_json(self, data: ReportData) -> Path:
        agg = self.aggregate_metrics(data)
        path = self.output_dir / f"{data.session_id}.json"
        payload = {**data.to_dict(), "aggregated": agg}
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _write_markdown(self, data: ReportData) -> Path:
        path = self.output_dir / f"{data.session_id}.md"
        path.write_text(self.render_markdown(data), encoding="utf-8")
        return path

    def _write_pdf(self, data: ReportData) -> Path:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        )
        from reportlab.lib import colors

        path = self.output_dir / f"{data.session_id}.pdf"
        agg = self.aggregate_metrics(data)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, title=f"CyberSim Report {data.session_id}")
        styles = getSampleStyleSheet()
        mono = ParagraphStyle("mono", parent=styles["Code"], fontName="Courier", fontSize=8, leading=10)
        story: list[Any] = []
        story.append(Paragraph(f"CyberSim Attack Report — {data.session_id}", styles["Title"]))
        story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()}", styles["Normal"]))
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("<b>Objective</b>", styles["Heading2"]))
        story.append(Paragraph(_escape(data.objective), styles["Normal"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("<b>Authorized Targets</b>", styles["Heading2"]))
        for t in data.targets:
            story.append(Paragraph(f"• {_escape(t)}", styles["Normal"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("<b>Metrics</b>", styles["Heading2"]))
        metric_rows = [["Metric", "Value"]]
        for k, v in {**data.metrics, **{
            "Tool calls": agg["tool_calls_total"],
            "Success rate": f"{agg['success_rate']*100:.1f}%",
            "Findings": agg["findings_total"],
            "Max CVSS": agg["max_cvss"],
            "Avg CVSS": agg["avg_cvss"],
        }}.items():
            metric_rows.append([str(k), str(v)])
        tbl = Table(metric_rows, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.4 * cm))

        if agg["findings"]:
            story.append(Paragraph("<b>Findings</b>", styles["Heading2"]))
            find_rows: list[list[Any]] = [["Tool", "Severity", "CVSS", "Where", "Description"]]
            for f in agg["findings"]:
                find_rows.append([
                    str(f.get("tool")),
                    str(f.get("severity")),
                    str(f.get("cvss") or ""),
                    _short(str(f.get("where") or "")),
                    _short(str(f.get("name") or "")),
                ])
            t = Table(find_rows, hAlign="LEFT", colWidths=[3*cm, 2*cm, 1.5*cm, 5*cm, 6*cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7f1d1d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.5 * cm))

        if data.final_report:
            story.append(Paragraph("<b>Agent Final Report</b>", styles["Heading2"]))
            for paragraph in str(data.final_report).split("\n\n"):
                story.append(Paragraph(_escape(paragraph).replace("\n", "<br/>"), styles["Normal"]))
                story.append(Spacer(1, 0.2 * cm))

        story.append(PageBreak())
        story.append(Paragraph("<b>Tool Transcript</b>", styles["Heading2"]))
        for i, tr in enumerate(data.tool_results, 1):
            story.append(Paragraph(
                f"<b>{i}. {tr.get('tool')}</b> — status={tr.get('status')} "
                f"duration={tr.get('duration_s'):.2f}s",
                styles["Heading4"],
            ))
            story.append(Paragraph(f"args = <font face='Courier'>{_escape(json.dumps(tr.get('arguments') or {}))}</font>", styles["Normal"]))
            story.append(Paragraph(_escape(_short(tr.get("summary") or "", 800)).replace("\n", "<br/>"), mono))
            story.append(Spacer(1, 0.25 * cm))

        doc.build(story)
        path.write_bytes(buf.getvalue())
        return path

    # ---------------------------------------------------------------- render
    def render_markdown(self, data: ReportData) -> str:
        agg = self.aggregate_metrics(data)
        lines: list[str] = []
        lines.append(f"# CyberSim Attack Report — `{data.session_id}`")
        lines.append("")
        lines.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"- **Started:** {data.started_at}")
        lines.append(f"- **Finished:** {data.finished_at}")
        lines.append(f"- **Model:** {data.metrics.get('model') or 'granite3.1-dense:latest'}")
        lines.append("")
        lines.append("## Objective")
        lines.append("")
        lines.append(data.objective)
        lines.append("")
        lines.append("## Authorized Targets")
        for t in data.targets:
            lines.append(f"- `{t}`")
        lines.append("")
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        for k, v in data.metrics.items():
            lines.append(f"| {k} | {v} |")
        lines.append(f"| Tool calls | {agg['tool_calls_total']} |")
        lines.append(f"| Tool success rate | {agg['success_rate']*100:.1f}% |")
        lines.append(f"| Findings | {agg['findings_total']} |")
        lines.append(f"| Max CVSS | {agg['max_cvss']} |")
        lines.append(f"| Avg CVSS | {agg['avg_cvss']} |")
        lines.append("")
        if agg["findings"]:
            lines.append("## Findings")
            lines.append("")
            lines.append("| Tool | Severity | CVSS | Where | Description |")
            lines.append("| --- | --- | --- | --- | --- |")
            for f in agg["findings"]:
                lines.append(
                    f"| {f.get('tool')} | {f.get('severity')} | {f.get('cvss') or ''} "
                    f"| `{f.get('where') or ''}` | {f.get('name') or ''} |"
                )
            lines.append("")
        if data.final_report:
            lines.append("## Agent Final Report")
            lines.append("")
            lines.append(str(data.final_report))
            lines.append("")
        lines.append("## Tool Transcript")
        lines.append("")
        for i, tr in enumerate(data.tool_results, 1):
            lines.append(f"### {i}. `{tr.get('tool')}` — {tr.get('status')}")
            lines.append("")
            lines.append(f"- duration: `{tr.get('duration_s'):.2f}s`")
            lines.append(f"- arguments: `{json.dumps(tr.get('arguments') or {})}`")
            lines.append("")
            lines.append("```")
            lines.append(_short(tr.get("summary") or "", 4000))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_ESC_RE = re.compile(r"[<>&]")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _short(text: str, limit: int = 600) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 25] + f"\n…[truncated {len(text) - limit + 25} chars]"
