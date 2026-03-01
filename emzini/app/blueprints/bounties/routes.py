from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Bounty
from app.services.escrow_service import lock_escrow, release_escrow, InsufficientFundsError
from app.services.logger_service import log_action

bounties_bp = Blueprint('bounties', __name__)


@bounties_bp.route('/bounties')
@login_required
def index():
    status_filter = request.args.get('status', 'open')
    q = Bounty.query
    if status_filter != 'all':
        q = q.filter_by(status=status_filter)
    bounties = q.order_by(Bounty.created_at.desc()).all()
    return render_template('bounties/index.html', bounties=bounties, status_filter=status_filter)


@bounties_bp.route('/bounties/new', methods=['GET', 'POST'])
@login_required
def new_bounty():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        reward_str = request.form.get('reward', '0')

        if not title or not description:
            flash('Title and description required.', 'danger')
            return render_template('bounties/new.html')
        try:
            reward = float(reward_str)
            if reward <= 0:
                raise ValueError
        except ValueError:
            flash('Enter a valid reward.', 'danger')
            return render_template('bounties/new.html')

        try:
            lock_escrow(current_user.id, reward, f'Bounty: {title}')
        except InsufficientFundsError as e:
            flash(str(e), 'danger')
            return render_template('bounties/new.html')

        bounty = Bounty(
            poster_id=current_user.id,
            title=title,
            description=description,
            reward=reward,
        )
        db.session.add(bounty)
        db.session.commit()
        log_action('bounty_posted', f'{current_user.username} posted bounty "{title}" R{reward:.2f}', current_user.id)
        flash(f'Bounty posted! R{reward:.2f} in escrow.', 'success')
        return redirect(url_for('bounties.index'))

    return render_template('bounties/new.html')


@bounties_bp.route('/bounties/<int:bounty_id>/claim', methods=['POST'])
@login_required
def claim_bounty(bounty_id):
    bounty = Bounty.query.get_or_404(bounty_id)
    if bounty.status != 'open':
        flash('Bounty no longer open.', 'danger')
        return redirect(url_for('bounties.index'))
    if bounty.poster_id == current_user.id:
        flash("Can't claim your own bounty.", 'danger')
        return redirect(url_for('bounties.index'))

    bounty.claimer_id = current_user.id
    bounty.status = 'claimed'
    db.session.commit()
    log_action('bounty_claimed', f'{current_user.username} claimed bounty #{bounty.id}', current_user.id)
    flash('Bounty claimed! Submit proof to the poster for verification.', 'success')
    return redirect(url_for('bounties.index'))


@bounties_bp.route('/bounties/<int:bounty_id>/verify', methods=['POST'])
@login_required
def verify_bounty(bounty_id):
    bounty = Bounty.query.get_or_404(bounty_id)
    if bounty.poster_id != current_user.id and not current_user.is_admin:
        flash('Only the poster or admin can verify.', 'danger')
        return redirect(url_for('bounties.index'))
    if bounty.status != 'claimed':
        flash('Bounty is not in claimed state.', 'danger')
        return redirect(url_for('bounties.index'))

    bounty.status = 'verified'
    db.session.commit()
    release_escrow(bounty.claimer_id, bounty.reward, f'Bounty verified: {bounty.title}')
    log_action('bounty_verified', f'Bounty #{bounty.id} verified — R{bounty.reward:.2f} paid', current_user.id)
    flash(f'Bounty verified! R{bounty.reward:.2f} paid out. +5 rep to finder!', 'success')
    return redirect(url_for('bounties.index'))
