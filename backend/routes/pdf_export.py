"""
PDF export of screening history - patient self-export and therapist export.

Privacy:
- The patient route exports ONLY the signed-in user's own screenings (g.user_id).
- The therapist route reuses the ONE shared active-link helper from
  routes.therapist (_active_link_or_403): without an ACTIVE link the answer is
  the same 403, whether the patient exists or not.
- Chat content can never appear here: no chat transcripts are stored anywhere
  in the schema, and this module reads Screening rows only.
- Personalised responses are sent with Cache-Control: no-store.

Note on scripts: reportlab's built-in Helvetica cannot render Urdu/Arabic
glyphs, so Urdu-script names appear as placeholders. Everything else in the
PDF (labels, scores, dates) is ASCII by design.
"""

import io
from datetime import datetime, timezone

from flask import Blueprint, jsonify, g, Response

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from ..models import db, User, Screening
from ..middleware import require_auth, require_therapist
from .user import _is_crisis, _analyse
from .therapist import _active_link_or_403


# Two prefixes, one module: the patient route lives under /api/screening and
# the therapist route under /api/therapist, without touching either blueprint.
screening_pdf_bp = Blueprint('screening_pdf', __name__, url_prefix='/api/screening')
therapist_pdf_bp = Blueprint('therapist_pdf', __name__, url_prefix='/api/therapist')


DISCLAIMER = "This is a screening result, not a diagnosis."
ANSWER_LEGEND = ("Answer key: 0 = not at all, 1 = several days, "
                 "2 = more than half the days, 3 = nearly every day.")

_TYPE_LABELS = {'phq9': 'PHQ-9 (Depression)', 'gad7': 'GAD-7 (Anxiety)'}


def _fmt_dt(dt):
    if not dt:
        return '-'
    return dt.strftime('%Y-%m-%d %H:%M')


def _trend_lines(rows):
    """Human trend summary - reuses the dashboard's own analysis helpers."""
    per_type, situation = _analyse(rows)
    lines = []
    overall = {
        'improving': 'Scores have been trending down over time.',
        'worsening': 'Scores have been trending up over time.',
        'stable': 'Scores have been relatively stable.',
        'new': 'Not enough check-ins yet to establish a trend.',
    }.get(situation, '')
    if overall:
        lines.append(f"Overall: {overall}")
    for atype, info in per_type.items():
        label = _TYPE_LABELS.get(atype, atype)
        lines.append(
            f"{label}: {info['count']} check-in(s) - latest {info['latest_score']} "
            f"({info['latest_severity']}), average {info['average_score']}, "
            f"best {info['best_score']}, worst {info['worst_score']}, "
            f"trend {info['direction']}"
        )
    return lines


def _build_pdf(rows, patient_label, prepared_for=None):
    """Render the screening history PDF and return its bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title='Zehni Sukoon - Screening History',
        author='Zehni Sukoon',
    )
    styles = getSampleStyleSheet()
    body = styles['Normal']
    small = ParagraphStyle('small', parent=body, fontSize=8.5,
                           textColor=colors.HexColor('#555555'))

    story = [
        Paragraph('Zehni Sukoon - Screening History', styles['Title']),
        Paragraph(f'<b>{patient_label}</b>', body),
        Paragraph(f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}', small),
    ]
    if prepared_for:
        story.append(Paragraph(f'Prepared for: {prepared_for}', small))
    story += [
        Spacer(1, 6),
        Paragraph(f'<b>{DISCLAIMER}</b>', body),
        Spacer(1, 12),
    ]

    # Trend summary ---------------------------------------------------------
    story.append(Paragraph('Trend summary', styles['Heading3']))
    trend = _trend_lines(list(reversed(rows)))
    if trend:
        for line in trend:
            story.append(Paragraph(line, body))
    else:
        story.append(Paragraph('No screening records yet.', body))
    story.append(Spacer(1, 14))

    # Per-screening details -------------------------------------------------
    story.append(Paragraph('Screening records', styles['Heading3']))
    if not rows:
        story.append(Paragraph('No screening records yet.', body))
    for r in rows:
        title = (_TYPE_LABELS.get(r.assessment_type, r.assessment_type or '-')
                 + ' - ' + _fmt_dt(r.created_at))
        story.append(Paragraph(title, styles['Heading4']))
        crisis = _is_crisis(r)
        crisis_html = ('<font color="#b91c1c"><b>YES - self-harm signal recorded</b></font>'
                       if crisis else 'No')
        answers = r.answers or {}
        answers_text = ', '.join(f'{k}={v}' for k, v in answers.items()) or '-'
        table = Table([
            ['Total score', str(r.total_score) if r.total_score is not None else '-'],
            ['Severity', r.severity or '-'],
            ['Crisis flag', Paragraph(crisis_html, body)],
            ['Item-level answers', Paragraph(answers_text, body)],
        ], colWidths=[4.2 * cm, 12 * cm])
        table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#4e635e')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 0), (-1, -2), 0.4, colors.HexColor('#d8dedb')),
        ]))
        story.append(table)
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 8))
    story.append(Paragraph(ANSWER_LEGEND, small))
    story.append(Paragraph(f'<b>{DISCLAIMER}</b>', small))

    doc.build(story)
    return buffer.getvalue()


def _pdf_response(pdf_bytes, filename):
    return Response(pdf_bytes, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Cache-Control': 'no-store',
    })


def _own_rows(user_id):
    return (Screening.query.filter_by(user_id=user_id)
            .order_by(Screening.created_at.desc()).all())


# ── Patient: download own history ──────────────────────────────────────
@screening_pdf_bp.route('/export-pdf', methods=['GET'])
@require_auth
def export_own_pdf():
    """
    GET /api/screening/export-pdf
    The signed-in user's own screening history as PDF. Guests (no JWT) get 401 -
    an anonymous session has no account to own the file.
    """
    user = db.session.get(User, g.user_id)
    label = (user.display_name if user and user.display_name
             else f'Patient #{g.user_id}')
    pdf = _build_pdf(_own_rows(g.user_id), f'Patient: {label}')
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return _pdf_response(pdf, f'zehni-sukoon-screenings-{day}.pdf')


# ── Therapist: download for an ACTIVE-linked patient ───────────────────
@therapist_pdf_bp.route('/patients/<int:patient_id>/export-pdf', methods=['GET'])
@require_therapist
def export_patient_pdf(patient_id: int):
    """
    GET /api/therapist/patients/<patient_id>/export-pdf
    Gated on the shared active-link check - identical 403 whether the patient
    does not exist, belongs to another therapist, or the link was revoked.
    """
    if not _active_link_or_403(g.user_id, patient_id):
        return jsonify({'error': 'You do not have access to this patient'}), 403

    patient = db.session.get(User, patient_id)
    if not patient:
        return jsonify({'error': 'You do not have access to this patient'}), 403

    therapist = db.session.get(User, g.user_id)
    prepared_for = (therapist.display_name if therapist and therapist.display_name
                    else therapist.email if therapist else None)
    label = patient.display_name or f'Patient #{patient_id}'
    pdf = _build_pdf(_own_rows(patient_id), f'Patient: {label}',
                     prepared_for=prepared_for)
    day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return _pdf_response(pdf, f'patient-{patient_id}-screenings-{day}.pdf')
