import os
import time
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import Bounty
from app.services.escrow_service import lock_escrow, release_escrow, InsufficientFundsError
from app.services.logger_service import log_action
from app.services.notif_service import notify

bounties_bp = Blueprint('bounties', __name__)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _save_bounty_photo(file):
    if not file or not file.filename:
        return None
    if not _allowed(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = secure_filename(f"bounty_{current_user.id}_{int(time.time())}.{ext}")
    file.save(os.path.join(current_app.config['BOUNTY_UPLOAD_DIR'], filename))
    return filename


def _delete_bounty_photo(filename):
    if filename:
        try:
            os.remove(os.path.join(current_app.config['BOUNTY_UPLOAD_DIR'], filename))
        except OSError:
            pass


@bounties_bp.route('/bounties/photos/<filename>')
def serve_photo(filename):
    return send_from_directory(current_app.config['BOUNTY_UPLOAD_DIR'], filename)


@bounties_bp.route('/bounties/proofs/<filename>')
def serve_proof(filename):
    return send_from_directory(current_app.config['BOUNTY_PROOF_DIR'], filename)


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

        photo_filename = _save_bounty_photo(request.files.get('photo'))

        bounty = Bounty(
            poster_id=current_user.id,
            title=title,
            description=description,
            reward=reward,
            photo_url=photo_filename,
        )
        db.session.add(bounty)
        db.session.commit()
        log_action('bounty_posted', f'{current_user.username} posted bounty "{title}" R{reward:.2f}', current_user.id)
        flash(f'Bounty posted! R{reward:.2f} in escrow.', 'success')
        return redirect(url_for('bounties.index'))

    return render_template('bounties/new.html')


@bounties_bp.route('/bounties/<int:bounty_id>/claim', methods=['GET', 'POST'])
@login_required
def claim_bounty(bounty_id):
    bounty = Bounty.query.get_or_404(bounty_id)

    if bounty.status != 'open':
        flash('Bounty no longer open.', 'danger')
        return redirect(url_for('bounties.index'))
    if bounty.poster_id == current_user.id:
        flash("Can't claim your own bounty.", 'danger')
        return redirect(url_for('bounties.index'))

    if request.method == 'GET':
        return render_template('bounties/claim.html', bounty=bounty)

    # POST — save proof photo then run AI verification
    proof_file = request.files.get('proof_photo')
    if not proof_file or not proof_file.filename:
        flash('A proof photo is required to claim a bounty.', 'danger')
        return render_template('bounties/claim.html', bounty=bounty)
    if not _allowed(proof_file.filename):
        flash('Only image files are accepted.', 'danger')
        return render_template('bounties/claim.html', bounty=bounty)

    ext = proof_file.filename.rsplit('.', 1)[1].lower()
    proof_filename = secure_filename(f"proof_{bounty_id}_{current_user.id}_{int(time.time())}.{ext}")
    proof_path = os.path.join(current_app.config['BOUNTY_PROOF_DIR'], proof_filename)
    proof_file.save(proof_path)

    # AI vision check
    from app.services.ai_service import verify_bounty_photo
    verdict = verify_bounty_photo(
        description=f"{bounty.title}. {bounty.description}",
        photo_path=proof_path,
    )

    bounty.claimer_id = current_user.id
    bounty.status = 'claimed'
    bounty.proof_photo = proof_filename
    bounty.ai_verified = verdict['match']
    bounty.ai_verdict_msg = f"[{verdict['confidence'].upper()} confidence] {verdict['reason']}"
    db.session.commit()

    log_action('bounty_claimed', f'{current_user.username} claimed bounty #{bounty.id}', current_user.id)
    notify(bounty.poster_id, 'bounty_claimed',
           f'@{current_user.username} claimed your bounty',
           body=f'{bounty.title} — proof submitted, please verify', link='/bounties')

    if verdict['match'] is True:
        flash(f'Proof submitted! AI verified: looks like a match. Waiting for poster to confirm.', 'success')
    elif verdict['match'] is False:
        flash(f"Proof submitted but AI flagged a mismatch: {verdict['reason']} The poster will still review.", 'info')
    else:
        flash('Proof submitted! Waiting for poster to review.', 'success')

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
    notify(bounty.claimer_id, 'bounty_verified',
           f'Bounty verified — R{bounty.reward:.2f} credited to your wallet',
           body=bounty.title, link='/wallet')
    flash(f'Bounty verified! R{bounty.reward:.2f} paid out. +5 rep to finder!', 'success')
    return redirect(url_for('bounties.index'))
