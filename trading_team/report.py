"""Writes the one-page PDF for the day's decision."""
from __future__ import annotations

from pathlib import Path

from .models import Recommendation

DISCLAIMER = (
    "Research output from an automated multi-agent process. Not investment advice. "
    "No orders are placed. Verify every figure before acting."
)


def write_pdf(rec: Recommendation, path: str | Path, track_record: dict,
              analyst_summaries: dict[str, str] | None = None) -> Path:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install reportlab") from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    story = [Paragraph(f"Daily Trading Desk: {rec.run_date.isoformat()}", styles["Title"])]

    if rec.is_trade:
        story.append(Paragraph(
            f"<b>Decision: BUY {rec.ticker}</b> (confidence {rec.confidence:.0%})", body))
        story.append(Paragraph(
            f"Entry (reference close): {rec.entry_price:,.2f}<br/>"
            f"Stop-loss: {rec.stop_loss:,.2f} (-{rec.stop_pct}%)<br/>"
            f"Target: {rec.target:,.2f} (+{rec.target_pct}%)", body))
    else:
        story.append(Paragraph("<b>Decision: NO TRADE (stay in cash)</b>", body))

    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Rationale.</b> {_esc(rec.rationale)}", body))

    if analyst_summaries:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Analyst views</b>", body))
        for name, summary in analyst_summaries.items():
            story.append(Paragraph(f"{name.title()}: {_esc(summary)}", body))

    if rec.risk_notes:
        story.append(Spacer(1, 6))
        story.append(Paragraph("<b>Risk review</b>", body))
        for note in rec.risk_notes:
            story.append(Paragraph(f"&bull; {_esc(note)}", body))

    unverified = ", ".join(rec.unverified) if rec.unverified else "none"
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Data Unverified:</b> {_esc(unverified)}", body))

    tr = track_record
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Track record.</b> "
        f"Closed trades: {tr.get('closed_trades', 0)}, win rate: "
        f"{tr.get('win_rate_pct') if tr.get('win_rate_pct') is not None else 'n/a'}%, "
        f"average return: {tr.get('avg_return_pct') if tr.get('avg_return_pct') is not None else 'n/a'}%, "
        f"open trades: {tr.get('open_trades', 0)}.", body))

    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<i>{DISCLAIMER}</i>", body))

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=48, rightMargin=48,
                      topMargin=48, bottomMargin=48).build(story)
    return path


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
