import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from app.services.logger_service import log_action

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
