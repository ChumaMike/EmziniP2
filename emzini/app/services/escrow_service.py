from app.extensions import db
from app.models import User, WalletTx


class InsufficientFundsError(Exception):
    pass


def lock_escrow(user_id: int, amount: float, reference: str):
    user = User.query.get(user_id)
    if user.wallet_balance < amount:
        raise InsufficientFundsError(f'Need R{amount:.2f}, have R{user.wallet_balance:.2f}')
    user.wallet_balance -= amount
    tx = WalletTx(user_id=user_id, amount=-amount, tx_type='escrow_lock', reference=reference)
    db.session.add(tx)
    db.session.commit()


def release_escrow(to_user_id: int, amount: float, reference: str):
    user = User.query.get(to_user_id)
    user.wallet_balance += amount
    user.reputation += 5
    tx = WalletTx(user_id=to_user_id, amount=amount, tx_type='escrow_release', reference=reference)
    db.session.add(tx)
    db.session.commit()


def credit_wallet(user_id: int, amount: float, reference: str):
    user = User.query.get(user_id)
    user.wallet_balance += amount
    tx = WalletTx(user_id=user_id, amount=amount, tx_type='credit', reference=reference)
    db.session.add(tx)
    db.session.commit()


def debit_wallet(user_id: int, amount: float, reference: str):
    user = User.query.get(user_id)
    if user.wallet_balance < amount:
        raise InsufficientFundsError(f'Need R{amount:.2f}, have R{user.wallet_balance:.2f}')
    user.wallet_balance -= amount
    tx = WalletTx(user_id=user_id, amount=-amount, tx_type='debit', reference=reference)
    db.session.add(tx)
    db.session.commit()
