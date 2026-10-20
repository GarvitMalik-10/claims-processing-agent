"""PDF exports (README 6.5 / 9.6): the human-readable audit file and the customer letter.

Built purely from the claim file (events, report, replay) - the PDF is a rendering, not a new source.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.audit.replay import replay
from app.data.loader import SyntheticData
from app.models.events import Event, EventType
from app.report.builder import build_report
from app.store.event_store import EventStore

BRAND = colors.HexColor("#0f766e")
GREY = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=18, textColor=BRAND, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=12.5, textColor=BRAND, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=_ss["BodyText"], fontSize=9.5, leading=12.5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.8, leading=9.8, textColor=GREY)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.2, leading=10.2)
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=TA_RIGHT)


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _eur(x: float | None) -> str:
    if x is None:
        return "–"
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


def _h(s: str | None) -> str:
    return (s or "–").replace("_", " ")


def _table(rows: list[list[Any]], widths: list[float], header: bool = True, right: set[int] = frozenset()) -> Table:
    data = [[c if not isinstance(c, str) else Paragraph(_esc(c), CELL_R if i in right else CELL) for i, c in enumerate(r)]
            for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9"))]
    t.setStyle(TableStyle(style))
    return t


def _event_line(e: Event) -> str:
    p = e.payload
    match e.type:
        case EventType.EVIDENCE_RECEIVED:
            return {"text": f'customer message: "{(p.get("text") or "")[:120]}"', "image": f"photo {p.get('filename') or ''}",
                    "document": f"repair quote {(p.get('estimate') or {}).get('contractor')}"}.get(p.get("kind"), p.get("kind", ""))
        case EventType.JEV_ANSWERED:
            a = p["answer"]
            val = f"{a['noul']:.2f}" if a["type"] == "noul" else f"{a['choice']} ({a['confidence']:.2f})"
            return f"{p['question_set']} · {p['question_id']} = {val}"
        case EventType.RULE_EVALUATED:
            return f"{p['rule_id']} → {str(p['output'])[:110]}"
        case EventType.FINDING_CREATED:
            return f"{p.get('agent')}: {(p.get('summary') or '')[:120]}"
        case EventType.MESSAGE_SENT:
            return f'to customer ({p.get("kind")}): "{p.get("text", "")[:110]}"'
        case EventType.ROUTING_DECIDED:
            return f"route {p['route']} · {', '.join(p['reasons'])}"
        case EventType.COVERAGE_RESOLVED:
            return f"coverage {p['status']} · {', '.join(p['reasons'])}"
        case EventType.PAYOUT_CALCULATED:
            rec = p.get("recommendation")
            return f"payout {_eur(rec['payout'])}" if rec else "no payout calculated"
        case EventType.HUMAN_DECISION:
            return f"{p['action']} by {e.actor.id} ({e.actor.role}) · {p.get('reason') or ''}"
        case EventType.PAYMENT_INSTRUCTED:
            return f"{_eur(p['amount'])} · {p['payment_ref']}"
        case EventType.VISION_EXTRACTED:
            o = p["observation"]
            return f"{p['evidence_id']}: {o['room_type']} · {', '.join(o['damage_types'])}"
    keys = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(p.items())[:4])
    return keys


def audit_pdf(store: EventStore, data: SyntheticData, cid: str) -> bytes:
    report = build_report(store, data, cid)
    rep = replay(store, data, cid)
    chain = store.verify_chain(cid)
    events = store.events(cid)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"{cid} audit file", author="Tecto")
    s = report.claim_summary
    story: list[Any] = [
        Paragraph(f"Claim audit file · {cid}", H1),
        Paragraph(f"Tecto explainable claims engine (demo) · generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · "
                  f"{len(events)} events", SMALL),
        Spacer(1, 6),
    ]

    ok = chain.intact and rep.all_match
    verdict = (f"<b>Integrity:</b> hash chain {'intact' if chain.intact else f'BROKEN at event #{chain.first_broken_seq} ({chain.problem})'}"
               f" · <b>Replay:</b> {'all outcomes reproduced' if rep.all_match else (rep.note or 'MISMATCH')}")
    box = Table([[Paragraph(verdict, BODY)]], colWidths=[182 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ecfdf5" if ok else "#fef2f2")),
                             ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#10b981" if ok else "#ef4444")),
                             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.append(box)

    story.append(Paragraph("Decision", H2))
    pay = report.payout_recommendation
    story.append(_table([
        ["Route", _h(report.route).upper(), "Payout recommendation", _eur(pay.payout if pay else None)],
        ["Reasons", ", ".join(report.route_reasons) or "–", "Human approval", _h(report.human_approval.status)
         + (f" by {report.human_approval.reviewer_id}" if report.human_approval.reviewer_id else "")],
    ], [28, 70, 40, 44], header=False))

    story.append(Paragraph("Claim summary", H2))
    story.append(_table([
        ["Customer", s.customer_id, "Policy", s.policy_id or "–"],
        ["Peril", _h(s.peril), "Loss date", str(s.loss_date or "–")],
        ["Location", s.location or "–", "Channels", ", ".join(s.channels)],
    ], [28, 70, 40, 44], header=False))
    if s.text.get("en"):
        story.append(Spacer(1, 3))
        story.append(Paragraph(_esc(s.text["en"]), BODY))

    if pay:
        story.append(Paragraph("Payout calculation", H2))
        rows = [["Item", "Claimed", "Validated", "Depreciation", "Covered", "Reason"]]
        rows += [[l.description, _eur(l.claimed), _eur(l.validated), _eur(l.depreciation) if l.depreciation else "",
                  _eur(l.covered), l.reason or ""] for l in pay.lines]
        rows.append(["Eligible − deductible = payout", "", "", "", _eur(pay.payout),
                     f"{_eur(pay.eligible)} − {_eur(pay.deductible)}" + (f"; caps {', '.join(pay.caps_applied)}" if pay.caps_applied else "")])
        story.append(_table(rows, [52, 21, 21, 21, 21, 46], right={1, 2, 3, 4}))

    if report.coverage_decision:
        story.append(Paragraph(f"Coverage: {_h(report.coverage_decision.status)}", H2))
        rows = [["Clause", "Status", "Condition", "Facts used"]]
        for c in report.coverage_decision.clauses:
            if c.status == "not_applicable":
                continue
            title = data.policy_book.clauses[c.clause_id].title["en"] if c.clause_id in data.policy_book.clauses else ""
            rows.append([f"{c.clause_id} {title}", c.status, c.condition or "", ", ".join(f"{k}={v}" for k, v in c.facts_used.items())])
        story.append(_table(rows, [56, 22, 56, 48]))

    if report.image_claim_consistency:
        story.append(Paragraph(f"Image–claim consistency: {_h(report.image_claim_consistency.result)}", H2))
        rows = [["Check", "Result", "Source", "Detail"]]
        rows += [[_h(c.check), {True: "pass", False: "fail"}.get(c.passed, "unresolved"), c.source, c.detail]
                 for c in report.image_claim_consistency.checks]
        story.append(_table(rows, [48, 18, 14, 102]))

    if report.risk_score:
        story.append(Paragraph(f"Risk score: {report.risk_score.score:.2f}"
                               + (f" · hard flags: {', '.join(report.risk_score.hard_flags)}" if report.risk_score.hard_flags else ""), H2))
        rows = [["Signal", "Strength", "Weight", "Contribution", "Source"]]
        rows += [[_h(x.signal), f"{x.strength:.2f}", f"{x.weight}", f"{x.contribution:.3f}", x.source]
                 for x in report.risk_score.signals if x.contribution > 0]
        story.append(_table(rows, [70, 24, 24, 30, 34], right={1, 2, 3}))

    if rep.replayable:
        story.append(Paragraph("Replay (rules only, no AI calls)", H2))
        rows = [["Item", "Logged", "Replayed", "Match"]] + [[c.item, str(c.logged), str(c.replayed), "yes" if c.match else "NO"] for c in rep.checks]
        story.append(_table(rows, [40, 50, 50, 42]))

    story.append(Paragraph("Model calls (raw request/response stored by hash)", H2))
    rows = [["#", "Event", "Model", "Prompt / question set", "Request blob", "Response blob"]]
    for e in events:
        pv = e.provenance
        if pv.raw_request_blob and pv.model:
            rows.append([str(e.seq), e.type.value, pv.model, pv.prompt_or_question_set_version or "", pv.raw_request_blob[:12],
                         (pv.raw_response_blob or "")[:12]])
    story.append(_table(rows, [9, 32, 32, 39, 35, 35]))

    story.append(Paragraph("Event timeline (append-only, hash-chained)", H2))
    rows = [["#", "Time (UTC)", "Event", "Actor", "What", "Hash"]]
    for e in events:
        rows.append([str(e.seq), f"{e.timestamp:%H:%M:%S}", e.type.value, f"{e.actor.kind}:{e.actor.id}", _event_line(e), e.hash[:10]])
    story.append(_table(rows, [9, 16, 30, 30, 77, 20]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Each event's hash covers its content and the previous event's hash; any edit breaks the chain "
                           "from that event on. Config versions used: "
                           + _esc(", ".join(f"{k}@{v}" for k, v in (report.audit_trail.config_versions if report.audit_trail else {}).items())), SMALL))
    doc.build(story)
    return buf.getvalue()


_MD_INLINE = [(re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"), (re.compile(r"(?<!\*)\*(?!\*)(.+?)\*"), r"<i>\1</i>")]


def _md_inline(s: str) -> str:
    s = _esc(s)
    for pat, rep in _MD_INLINE:
        s = pat.sub(rep, s)
    return s


def letter_pdf(markdown: str, *, claim_id: str) -> bytes:
    """Render the Sonnet-written Markdown letter (headings, paragraphs, bullets, tables) to PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=f"{claim_id} decision letter", author="Tecto")
    body = ParagraphStyle("lb", parent=BODY, fontSize=10.5, leading=14.5, spaceAfter=4)
    story: list[Any] = [Paragraph("Tecto", ParagraphStyle("brand", parent=H1, fontSize=22)),
                        Paragraph(f"Ref. {claim_id}", SMALL), Spacer(1, 8)]
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    block.append(cells)
                i += 1
            ncol = max(len(r) for r in block)
            rows = [[Paragraph(_md_inline(c), CELL) for c in r + [""] * (ncol - len(r))] for r in block]
            t = Table(rows, colWidths=[170 * mm / ncol] * ncol, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9"))]))
            story += [t, Spacer(1, 6)]
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            story.append(Paragraph(_md_inline(line.lstrip("#").strip()), H1 if level == 1 else H2))
        elif line.lstrip().startswith(("- ", "* ")):
            story.append(Paragraph("• " + _md_inline(line.lstrip()[2:]), ParagraphStyle("li", parent=body, leftIndent=10)))
        elif line.strip():
            story.append(Paragraph(_md_inline(line), body))
        i += 1
    doc.build([KeepTogether(story[:3])] + story[3:])
    return buf.getvalue()
