from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import CivicReport, CivicUpvote
from app.services.logger_service import log_action

civic_bp = Blueprint('civic', __name__)

CATEGORIES = ['pothole', 'pipe', 'electricity', 'safety', 'other']
SEVERITIES = ['low', 'medium', 'high', 'critical']


@civic_bp.route('/civic')
@login_required
def index():
    status_filter = request.args.get('status', 'open')
    q = CivicReport.query
    if status_filter != 'all':
        q = q.filter_by(status=status_filter)
    reports = q.order_by(CivicReport.upvotes.desc(), CivicReport.created_at.desc()).all()

    user_upvotes = set(
        u.report_id for u in CivicUpvote.query.filter_by(user_id=current_user.id).all()
    )
    return render_template('civic/index.html', reports=reports, user_upvotes=user_upvotes, status_filter=status_filter)


@civic_bp.route('/civic/report', methods=['GET', 'POST'])
@login_required
def new_report():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', 'other')
        severity = request.form.get('severity', 'medium')

        if not title or not description:
            flash('Title and description required.', 'danger')
            return render_template('civic/new.html', categories=CATEGORIES, severities=SEVERITIES)

        report = CivicReport(
            reporter_id=current_user.id,
            title=title,
            description=description,
            category=category if category in CATEGORIES else 'other',
            severity=severity if severity in SEVERITIES else 'medium',
        )
        db.session.add(report)
        current_user.reputation += 2
        db.session.commit()
        log_action('civic_report', f'{current_user.username} reported "{title}"', current_user.id)
        flash(f'Report submitted! +2 rep for civic duty.', 'success')
        return redirect(url_for('civic.index'))

    return render_template('civic/new.html', categories=CATEGORIES, severities=SEVERITIES)


@civic_bp.route('/civic/<int:report_id>/upvote', methods=['POST'])
@login_required
def upvote(report_id):
    report = CivicReport.query.get_or_404(report_id)
    existing = CivicUpvote.query.filter_by(user_id=current_user.id, report_id=report_id).first()
    if existing:
        flash('Already upvoted.', 'info')
        return redirect(url_for('civic.index'))

    upvote_record = CivicUpvote(user_id=current_user.id, report_id=report_id)
    report.upvotes += 1
    db.session.add(upvote_record)
    db.session.commit()
    return redirect(url_for('civic.index'))


@civic_bp.route('/civic/<int:report_id>/status', methods=['POST'])
@login_required
def update_status(report_id):
    if not current_user.is_admin:
        flash('Admin only.', 'danger')
        return redirect(url_for('civic.index'))
    report = CivicReport.query.get_or_404(report_id)
    new_status = request.form.get('status', 'open')
    if new_status in ('open', 'in_progress', 'resolved'):
        report.status = new_status
        db.session.commit()
        flash(f'Report status updated to {new_status}.', 'success')
    return redirect(url_for('civic.index'))
