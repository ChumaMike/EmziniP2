from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import WalletTx, User, TopupRequest
from app.services.escrow_service import credit_wallet
from app.services.logger_service import log_action
from app.extensions import db
import sqlalchemy as sa

wallet_bp = Blueprint('wallet', __name__)


def _rep_tier(rep):
    if rep >= 100: return ('Community Pillar', 'fa-crown',    '#f59e0b', 100, None)
    if rep >= 60:  return ('Established',      'fa-shield',   '#6366f1', 60,  100)
    if rep >= 30:  return ('Trusted',          'fa-check-circle','#14b8a6', 30, 60)
    if rep >= 10:  return ('Resident',         'fa-house',    '#94a3b8', 10,  30)
    return             ('Newcomer',            'fa-seedling', '#64748b', 0,   10)


@wallet_bp.route('/wallet')
@login_required
def index():
    txs = (WalletTx.query
           .filter_by(user_id=current_user.id)
           .order_by(WalletTx.created_at.desc())
           .limit(50).all())

    total_in  = db.session.execute(
        sa.select(sa.func.sum(WalletTx.amount)).where(
            WalletTx.user_id == current_user.id,
            WalletTx.amount > 0)
    ).scalar() or 0.0

    total_out = db.session.execute(
        sa.select(sa.func.sum(WalletTx.amount)).where(
            WalletTx.user_id == current_user.id,
            WalletTx.amount < 0,
            WalletTx.tx_type != 'escrow_lock')
    ).scalar() or 0.0

    in_escrow = db.session.execute(
        sa.select(sa.func.sum(WalletTx.amount)).where(
            WalletTx.user_id == current_user.id,
            WalletTx.tx_type == 'escrow_lock')
    ).scalar() or 0.0
    in_escrow = abs(in_escrow)

    tier_name, tier_icon, tier_color, tier_min, tier_max = _rep_tier(current_user.reputation)
    if tier_max:
        tier_pct = min(100, int((current_user.reputation - tier_min) / (tier_max - tier_min) * 100))
    else:
        tier_pct = 100

    pending_request = TopupRequest.query.filter_by(
        user_id=current_user.id, status='pending').first()
    recent_requests = (TopupRequest.query
                       .filter_by(user_id=current_user.id)
                       .order_by(TopupRequest.created_at.desc())
                       .limit(5).all())

    return render_template('wallet/index.html',
                           txs=txs,
                           total_in=total_in,
                           total_out=abs(total_out),
                           in_escrow=in_escrow,
                           tier_name=tier_name,
                           tier_icon=tier_icon,
                           tier_color=tier_color,
                           tier_pct=tier_pct,
                           tier_max=tier_max,
                           pending_request=pending_request,
                           recent_requests=recent_requests)


@wallet_bp.route('/wallet/topup', methods=['POST'])
@login_required
def topup():
    amount_str = request.form.get('amount', '0')
    try:
        amount = float(amount_str)
        if amount <= 0 or amount > 5000:
            flash('Enter an amount between R1 and R5000.', 'danger')
            return redirect(url_for('wallet.index'))
        credit_wallet(current_user.id, amount, 'Starter Credits top-up')
        log_action('wallet_topup', f'{current_user.username} topped up R{amount:.2f} App Credits', current_user.id)
        flash(f'R{amount:.2f} App Credits added. These are simulated — not real money.', 'success')
    except ValueError:
        flash('Invalid amount.', 'danger')
    return redirect(url_for('wallet.index'))


@wallet_bp.route('/wallet/request-topup', methods=['POST'])
@login_required
def request_topup():
    """Submit a deposit request for admin to verify and approve."""
    amount_str = request.form.get('amount', '0')
    reference  = request.form.get('reference', '').strip()
    try:
        amount = float(amount_str)
        if amount <= 0 or amount > 50000:
            flash('Enter an amount between R1 and R50,000.', 'danger')
            return redirect(url_for('wallet.index'))
        existing = TopupRequest.query.filter_by(user_id=current_user.id, status='pending').first()
        if existing:
            flash('You already have a pending deposit request — wait for admin approval.', 'danger')
            return redirect(url_for('wallet.index'))
        req = TopupRequest(user_id=current_user.id, amount=amount, reference=reference or None)
        db.session.add(req)
        db.session.commit()
        log_action('topup_request',
                   f'{current_user.username} requested R{amount:.2f} deposit', current_user.id)
        flash(f'Deposit request for R{amount:.2f} submitted. Admin will verify and credit your Real ZAR balance.', 'success')
    except ValueError:
        flash('Invalid amount.', 'danger')
    return redirect(url_for('wallet.index'))


@wallet_bp.route('/wallet/convert', methods=['POST'])
@login_required
def convert():
    """Convert real_balance → wallet_balance (App Credits) 1:1."""
    amount_str = request.form.get('amount', '0')
    try:
        amount = float(amount_str)
        if amount <= 0:
            flash('Enter a positive amount.', 'danger')
            return redirect(url_for('wallet.index'))
        if current_user.real_balance < amount:
            flash(f'Insufficient Real ZAR. You have R{current_user.real_balance:.2f}.', 'danger')
            return redirect(url_for('wallet.index'))
        current_user.real_balance -= amount
        current_user.wallet_balance += amount
        db.session.add(WalletTx(
            user_id=current_user.id, amount=amount,
            tx_type='credit', reference=f'Converted R{amount:.2f} from Real ZAR',
        ))
        db.session.commit()
        log_action('real_to_credits', f'{current_user.username} converted R{amount:.2f} real → App Credits', current_user.id)
        flash(f'R{amount:.2f} converted to App Credits.', 'success')
    except ValueError:
        flash('Invalid amount.', 'danger')
    return redirect(url_for('wallet.index'))
