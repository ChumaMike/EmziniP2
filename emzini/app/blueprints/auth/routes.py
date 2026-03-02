import uuid
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User, PasswordResetToken
from app.services.logger_service import log_action


def _send_reset_email(to_email, reset_url):
    cfg      = current_app.config
    server   = cfg.get('MAIL_SERVER', '')
    port     = cfg.get('MAIL_PORT', 587)
    username = cfg.get('MAIL_USERNAME', '')
    password = cfg.get('MAIL_PASSWORD', '')
    from_addr = cfg.get('MAIL_FROM') or username
    if not (server and username and password):
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Emzini — Reset your password'
    msg['From']    = f'Emzini <{from_addr}>'
    msg['To']      = to_email
    body = (
        f"Hi,\n\n"
        f"Someone requested a password reset for your Emzini account.\n\n"
        f"Click the link below to set a new password (expires in 1 hour):\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, ignore this email — your account is safe.\n\n"
        f"— Emzini"
    )
    msg.attach(MIMEText(body, 'plain'))
    try:
        with smtplib.SMTP(server, port) as s:
            s.starttls()
            s.login(username, password)
            s.sendmail(from_addr, to_email, msg.as_string())
        return True
    except Exception:
        return False

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html')

        user = User(username=username, email=email, wallet_balance=50.0,
                    chat_session_id=str(uuid.uuid4()))
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_action('register', f'New user registered: {username}', user.id)
        login_user(user)
        session['pwa_prompt'] = True
        flash(f'Welcome to Emzini, {username}! R50 starter credit added.', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        # Fresh chat session on every login
        user.chat_session_id = str(uuid.uuid4())
        db.session.commit()

        login_user(user, remember=True)
        session['pwa_prompt'] = True
        log_action('login', f'{username} logged in', user.id)
        return redirect(request.args.get('next') or url_for('dashboard.index'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    log_action('logout', f'{current_user.username} logged out', current_user.id)
    logout_user()
    flash('Logged out. Lekker!', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()
        # Always show same message to avoid revealing account existence
        flash('If that email is registered, a reset link has been sent.', 'info')
        if user:
            token     = secrets.token_urlsafe(32)
            expires   = datetime.utcnow() + timedelta(hours=1)
            rt        = PasswordResetToken(user_id=user.id, token=token, expires_at=expires)
            db.session.add(rt)
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            sent = _send_reset_email(user.email, reset_url)
            if not sent:
                # Email not configured — show the link directly (dev/no-mail fallback)
                flash(f'Email not configured. Reset link (share privately): {reset_url}', 'danger')
        return redirect(url_for('auth.forgot_password'))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    rt = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not rt or rt.expires_at < datetime.utcnow():
        flash('This reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('auth/reset_password.html', token=token)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)
        rt.user.set_password(password)
        rt.used = True
        db.session.commit()
        log_action('password_reset', f'{rt.user.username} reset their password', rt.user.id)
        flash('Password updated! You can now sign in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token)
