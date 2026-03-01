from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import RunnerProfile, RunnerJob, WalletTx
from app.services.logger_service import log_action

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
        id_number  = request.form.get('id_number', '').strip()
        vehicle    = request.form.get('vehicle', 'foot')
        bio        = request.form.get('bio', '').strip()

        if not full_name or not phone or not id_number:
            flash('Full name, phone, and ID number are required.', 'danger')
            return render_template('runner/register.html', existing=existing)

        if vehicle not in ('foot', 'bicycle', 'motorbike', 'car'):
            vehicle = 'foot'

        profile = RunnerProfile(
            user_id=current_user.id,
            full_name=full_name,
            phone=phone,
            id_number=id_number,
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
