from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import WalletTx
from app.services.escrow_service import credit_wallet
from app.services.logger_service import log_action

wallet_bp = Blueprint('wallet', __name__)


@wallet_bp.route('/wallet')
@login_required
def index():
    txs = WalletTx.query.filter_by(user_id=current_user.id).order_by(WalletTx.created_at.desc()).limit(30).all()
    return render_template('wallet/index.html', txs=txs)


@wallet_bp.route('/wallet/topup', methods=['POST'])
@login_required
def topup():
    amount_str = request.form.get('amount', '0')
    try:
        amount = float(amount_str)
        if amount <= 0 or amount > 5000:
            flash('Enter an amount between R1 and R5000.', 'danger')
            return redirect(url_for('wallet.index'))
        credit_wallet(current_user.id, amount, 'Manual top-up')
        log_action('wallet_topup', f'{current_user.username} topped up R{amount:.2f}', current_user.id)
        flash(f'R{amount:.2f} added to your wallet. Sharp!', 'success')
    except ValueError:
        flash('Invalid amount.', 'danger')
    return redirect(url_for('wallet.index'))
