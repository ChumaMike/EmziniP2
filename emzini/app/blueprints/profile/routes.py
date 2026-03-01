from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import User, RunnerProfile
from app.services.logger_service import log_action

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/profile')
@login_required
def index():
    return render_template('profile/index.html')


@profile_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit():
    if request.method == 'POST':
        username    = request.form.get('username', '').strip()
        email       = request.form.get('email', '').strip()
        is_runner   = request.form.get('is_runner') == 'on'
        new_password = request.form.get('new_password', '').strip()
        confirm_pw  = request.form.get('confirm_password', '').strip()

        errors = []

        if not username or not email:
            errors.append('Username and email are required.')

        # Unique username check (allow own unchanged)
        if username != current_user.username:
            if User.query.filter_by(username=username).first():
                errors.append('That username is already taken.')

        # Unique email check
        if email != current_user.email:
            if User.query.filter_by(email=email).first():
                errors.append('That email is already registered.')

        # Password change
        if new_password:
            if len(new_password) < 6:
                errors.append('New password must be at least 6 characters.')
            elif new_password != confirm_pw:
                errors.append('Passwords do not match.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('profile/edit.html')

        # Gate runner enable behind approved RunnerProfile
        if is_runner and not current_user.is_runner:
            profile = RunnerProfile.query.filter_by(user_id=current_user.id).first()
            if not profile or profile.status != 'approved':
                flash('Submit a runner application at /runner/register first, then wait for admin approval.', 'danger')
                return render_template('profile/edit.html')

        # Commit changes
        prev_runner = current_user.is_runner
        current_user.username  = username
        current_user.email     = email
        current_user.is_runner = is_runner

        # If runner toggled off, also go inactive
        if not is_runner:
            current_user.runner_active = False

        if new_password:
            current_user.set_password(new_password)

        db.session.commit()

        # Broadcast runner status change if it changed
        if prev_runner != is_runner:
            socketio.emit('runner_status_changed', {
                'user_id': current_user.id,
                'username': current_user.username,
                'active': current_user.runner_active,
            })

        log_action('profile_update', f'{current_user.username} updated their profile', current_user.id)
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile.index'))

    return render_template('profile/edit.html')


@profile_bp.route('/profile/runner-toggle', methods=['POST'])
@login_required
def runner_toggle():
    """Quick toggle of runner_active status from the profile page."""
    if not current_user.is_runner:
        flash('Enable Runner Mode in your profile settings first.', 'danger')
        return redirect(url_for('profile.index'))

    current_user.runner_active = not current_user.runner_active
    db.session.commit()

    socketio.emit('runner_status_changed', {
        'user_id': current_user.id,
        'username': current_user.username,
        'active': current_user.runner_active,
    })
    log_action('runner_toggle',
               f'{current_user.username} is now {"ACTIVE" if current_user.runner_active else "OFFLINE"}',
               current_user.id)
    status_msg = "Active — you're live!" if current_user.runner_active else "Offline"
    flash(f'Runner status: {status_msg}', 'success')
    return redirect(url_for('profile.index'))
