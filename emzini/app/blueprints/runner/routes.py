from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import RunnerProfile, RunnerJob, WalletTx
from app.services.logger_service import log_action
from app.services.escrow_service import debit_wallet, InsufficientFundsError

runner_bp = Blueprint('runner', __name__)


@runner_bp.route('/runner/register', methods=['GET', 'POST'])
@login_required
def register():
    existing = RunnerProfile.query.filter_by(user_id=current_user.id).first()
    if request.method == 'POST':
        if existing:
            flash('You already have a runner application on file.', 'info')
            return redirect(url_for('runner.register'))

        full_name  = request.form.get('full_name', '').strip()
        phone      = request.form.get('phone', '').strip()
        vehicle    = request.form.get('vehicle', 'foot')
        bio        = request.form.get('bio', '').strip()

        if not full_name or not phone:
            flash('Full name and phone number are required.', 'danger')
            return render_template('runner/register.html', existing=existing)

        if vehicle not in ('foot', 'bicycle', 'motorbike', 'car'):
            vehicle = 'foot'

        profile = RunnerProfile(
            user_id=current_user.id,
            full_name=full_name,
            phone=phone,
            id_number='',
            vehicle=vehicle,
            bio=bio,
        )
        db.session.add(profile)
        db.session.commit()
        log_action('runner_application', f'{current_user.username} applied as a runner', current_user.id)
        flash('Application submitted! An admin will review it shortly.', 'success')
        return redirect(url_for('runner.register'))

    return render_template('runner/register.html', existing=existing)


@runner_bp.route('/runner/dashboard')
@login_required
def dashboard():
    profile = RunnerProfile.query.filter_by(user_id=current_user.id).first()
    active_jobs = RunnerJob.query.filter_by(runner_id=current_user.id, status='claimed').all()
    recent_txs  = (WalletTx.query
                   .filter_by(user_id=current_user.id)
                   .order_by(WalletTx.created_at.desc())
                   .limit(10).all())
    return render_template('runner/dashboard.html',
                           profile=profile,
                           active_jobs=active_jobs,
                           recent_txs=recent_txs)


@runner_bp.route('/runner/toggle', methods=['POST'])
@login_required
def toggle():
    profile = RunnerProfile.query.filter_by(user_id=current_user.id).first()
    if not profile or profile.status != 'approved':
        flash('You must have an approved runner application to go active. Apply at /runner/register.', 'danger')
        return redirect(request.referrer or url_for('runner.register'))

    current_user.is_runner = True
    current_user.runner_active = not current_user.runner_active
    db.session.commit()

    status = 'ACTIVE' if current_user.runner_active else 'OFFLINE'
    socketio.emit('runner_status_changed', {
        'user_id': current_user.id,
        'username': current_user.username,
        'active': current_user.runner_active,
    })
    log_action('runner_toggle', f'{current_user.username} is now {status}', current_user.id)
    flash(f'Runner status: {status}', 'success')
    return redirect(request.referrer or url_for('runner.dashboard'))


# ── Document Creation Service ────────────────────────────────────────────────

DOC_PRICES = {'cv': 2.00, 'email': 1.00}


@runner_bp.route('/docs', methods=['GET', 'POST'])
@login_required
def docs():
    generated = None
    doc_type  = None
    error     = None

    if request.method == 'POST':
        doc_type = request.form.get('doc_type', '').lower()
        if doc_type not in DOC_PRICES:
            flash('Invalid document type.', 'danger')
            return render_template('runner/docs.html', generated=None, doc_type=None,
                                   prices=DOC_PRICES, error=None)

        price = DOC_PRICES[doc_type]

        # Charge wallet first
        try:
            debit_wallet(current_user.id, price, f'Document creation: {doc_type.upper()}')
        except InsufficientFundsError as e:
            return render_template('runner/docs.html', generated=None, doc_type=doc_type,
                                   prices=DOC_PRICES, error=str(e))

        # Build prompt based on doc type
        from flask import current_app
        from google import genai

        api_key = current_app.config.get('GEMINI_API_KEY') or current_app.config.get('GOOGLE_API_KEY')
        if not api_key:
            import os
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')

        try:
            client = genai.Client(api_key=api_key)

            if doc_type == 'cv':
                name       = request.form.get('name', '').strip()
                phone      = request.form.get('phone', '').strip()
                email      = request.form.get('email', '').strip()
                skills     = request.form.get('skills', '').strip()
                experience = request.form.get('experience', '').strip()
                education  = request.form.get('education', '').strip()

                prompt = f"""Write a clean, professional CV in plain text for the following person.
Use clear sections with headings. Do not use markdown symbols like ** or ##.
Use simple ALL CAPS for section headings. Keep it concise and impressive.

Name: {name}
Phone: {phone}
Email: {email}
Skills: {skills}
Work Experience: {experience}
Education: {education}

Output only the CV text, ready to copy."""

            else:  # email
                subject    = request.form.get('subject', '').strip()
                recipient  = request.form.get('recipient', '').strip()
                key_points = request.form.get('key_points', '').strip()
                tone       = request.form.get('tone', 'professional')

                prompt = f"""Write a {tone} email in plain text.
Do not use markdown. Start directly with "Subject:" then a blank line then the email body.

Subject: {subject}
To: {recipient}
Key points to cover: {key_points}

Output only the email text, ready to copy."""

            response  = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            generated = response.text.strip()

        except Exception as exc:
            # Refund if generation failed
            from app.services.escrow_service import credit_wallet
            credit_wallet(current_user.id, price, f'Document creation refund: {doc_type.upper()} (generation failed)')
            error = f'Document generation failed — R{price:.2f} refunded. ({exc})'
            generated = None

        log_action('doc_created', f'{current_user.username} created {doc_type.upper()} — R{price:.2f} charged', current_user.id)

    return render_template('runner/docs.html', generated=generated, doc_type=doc_type,
                           prices=DOC_PRICES, error=error)
