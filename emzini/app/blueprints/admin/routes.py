from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import (ActionLog, User, RunnerJob, MarketItem, Bounty, CivicReport,
                         WalletTx, ChatMessage, Goal, Milestone,
                         NetworkContact, NetworkAlert, Document, RunnerProfile)
from app.extensions import db
from app.services.logger_service import log_action

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


# ── Overview ──────────────────────────────────────────────────────────────────

@admin_bp.route('/admin')
@login_required
@admin_required
def index():
    total_users       = User.query.count()
    admin_count       = User.query.filter_by(is_admin=True).count()
    runner_count      = User.query.filter_by(is_runner=True).count()
    active_runners    = User.query.filter_by(runner_active=True).count()
    total_liquidity   = db.session.query(db.func.sum(User.wallet_balance)).scalar() or 0

    open_jobs         = RunnerJob.query.filter_by(status='open').count()
    claimed_jobs      = RunnerJob.query.filter_by(status='claimed').count()
    completed_jobs    = RunnerJob.query.filter_by(status='completed').count()
    total_jobs        = RunnerJob.query.count()
    escrow_total      = db.session.query(db.func.sum(RunnerJob.reward)).filter(
                            RunnerJob.escrow_locked == True).scalar() or 0

    market_available  = MarketItem.query.filter_by(status='available').count()
    market_sold       = MarketItem.query.filter_by(status='sold').count()
    total_market      = MarketItem.query.count()

    open_bounties     = Bounty.query.filter_by(status='open').count()
    total_bounties    = Bounty.query.count()

    civic_open        = CivicReport.query.filter_by(status='open').count()
    civic_in_progress = CivicReport.query.filter_by(status='in_progress').count()
    civic_resolved    = CivicReport.query.filter_by(status='resolved').count()
    total_civic       = CivicReport.query.count()

    total_goals       = Goal.query.count()
    completed_goals   = Goal.query.filter_by(is_completed=True).count()
    total_milestones  = Milestone.query.count()

    total_contacts    = NetworkContact.query.count()
    pending_reminders = NetworkAlert.query.filter_by(is_completed=False).count()

    total_chat_msgs   = ChatMessage.query.count()
    total_docs        = Document.query.count()
    total_logs        = ActionLog.query.count()
    total_txs         = WalletTx.query.count()

    logs      = ActionLog.query.order_by(ActionLog.created_at.desc()).limit(20).all()
    top_users = User.query.order_by(User.reputation.desc()).limit(10).all()

    return render_template('admin/index.html',
        total_users=total_users, admin_count=admin_count,
        runner_count=runner_count, active_runners=active_runners,
        total_liquidity=total_liquidity,
        open_jobs=open_jobs, claimed_jobs=claimed_jobs,
        completed_jobs=completed_jobs, total_jobs=total_jobs, escrow_total=escrow_total,
        market_available=market_available, market_sold=market_sold, total_market=total_market,
        open_bounties=open_bounties, total_bounties=total_bounties,
        civic_open=civic_open, civic_in_progress=civic_in_progress,
        civic_resolved=civic_resolved, total_civic=total_civic,
        total_goals=total_goals, completed_goals=completed_goals, total_milestones=total_milestones,
        total_contacts=total_contacts, pending_reminders=pending_reminders,
        total_chat_msgs=total_chat_msgs, total_docs=total_docs,
        total_logs=total_logs, total_txs=total_txs,
        logs=logs, top_users=top_users,
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/users')
@login_required
@admin_required
def users():
    q      = request.args.get('q', '').strip()
    role_f = request.args.get('role', '')
    query  = User.query
    if q:
        query = query.filter(
            db.or_(User.username.ilike(f'%{q}%'), User.email.ilike(f'%{q}%'))
        )
    if role_f == 'admin':
        query = query.filter_by(is_admin=True)
    elif role_f == 'runner':
        query = query.filter_by(is_runner=True)
    elif role_f == 'active_runner':
        query = query.filter_by(runner_active=True)
    users_list = query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users_list, q=q, role_f=role_f)


@admin_bp.route('/admin/users/<int:uid>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(uid):
    user = User.query.get_or_404(uid)
    if user.id == current_user.id:
        flash("You can't change your own admin status.", 'danger')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        verb = 'Granted' if user.is_admin else 'Revoked'
        log_action('admin_toggle', f'{verb} admin for {user.username}', current_user.id)
        flash(f'{verb} admin for {user.username}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:uid>/set-wallet', methods=['POST'])
@login_required
@admin_required
def set_wallet(uid):
    user = User.query.get_or_404(uid)
    try:
        amount = float(request.form.get('amount', 0))
        diff   = amount - user.wallet_balance
        user.wallet_balance = amount
        db.session.add(WalletTx(
            user_id=user.id, amount=diff,
            tx_type='credit' if diff >= 0 else 'debit',
            reference=f'Admin adjustment by {current_user.username}',
        ))
        db.session.commit()
        log_action('admin_wallet', f'Set {user.username} wallet to R{amount:.2f}', current_user.id)
        flash(f'{user.username} wallet set to R{amount:.2f}.', 'success')
    except (ValueError, TypeError):
        flash('Invalid amount.', 'danger')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:uid>/inject-real', methods=['POST'])
@login_required
@admin_required
def inject_real(uid):
    """Credit real ZAR to a user's real_balance (admin-verified deposit)."""
    user = User.query.get_or_404(uid)
    try:
        amount = float(request.form.get('amount', 0))
        if amount <= 0:
            flash('Enter a positive amount.', 'danger')
            return redirect(url_for('admin.users'))
        user.real_balance = (user.real_balance or 0.0) + amount
        db.session.commit()
        log_action('admin_inject_real', f'Injected R{amount:.2f} real ZAR for {user.username}', current_user.id)
        flash(f'R{amount:.2f} Real ZAR credited to {user.username}.', 'success')
    except (ValueError, TypeError):
        flash('Invalid amount.', 'danger')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:uid>/clear-cash-float', methods=['POST'])
@login_required
@admin_required
def clear_cash_float(uid):
    """Mark runner's cash float as collected — resets to 0."""
    user = User.query.get_or_404(uid)
    cleared = user.cash_float or 0.0
    user.cash_float = 0.0
    db.session.commit()
    log_action('admin_clear_float', f'Cleared R{cleared:.2f} cash float for {user.username}', current_user.id)
    flash(f'Cash float of R{cleared:.2f} cleared for {user.username}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/admin/users/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(uid):
    user = User.query.get_or_404(uid)
    if user.id == current_user.id:
        flash("You can't delete yourself.", 'danger')
        return redirect(url_for('admin.users'))
    username = user.username
    db.session.delete(user)
    db.session.commit()
    log_action('admin_delete_user', f'Deleted user {username}', current_user.id)
    flash(f'User {username} deleted.', 'success')
    return redirect(url_for('admin.users'))


# ── Civic ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/civic')
@login_required
@admin_required
def civic():
    status_f = request.args.get('status', '')
    sev_f    = request.args.get('severity', '')
    query    = CivicReport.query
    if status_f:
        query = query.filter_by(status=status_f)
    if sev_f:
        query = query.filter_by(severity=sev_f)
    reports = query.order_by(CivicReport.created_at.desc()).all()
    return render_template('admin/civic.html', reports=reports, status_f=status_f, sev_f=sev_f)


@admin_bp.route('/admin/civic/<int:rid>/status', methods=['POST'])
@login_required
@admin_required
def update_civic_status(rid):
    report     = CivicReport.query.get_or_404(rid)
    new_status = request.form.get('status')
    if new_status in ('open', 'in_progress', 'resolved'):
        report.status = new_status
        db.session.commit()
        log_action('civic_status_update', f'Report #{rid} → {new_status}', current_user.id)
        flash(f'Report status set to {new_status}.', 'success')
    return redirect(url_for('admin.civic'))


@admin_bp.route('/admin/civic/<int:rid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_civic(rid):
    report = CivicReport.query.get_or_404(rid)
    title  = report.title
    db.session.delete(report)
    db.session.commit()
    log_action('admin_delete_civic', f'Deleted civic report "{title}"', current_user.id)
    flash(f'Report "{title}" deleted.', 'success')
    return redirect(url_for('admin.civic'))


# ── Marketplace ───────────────────────────────────────────────────────────────

@admin_bp.route('/admin/marketplace')
@login_required
@admin_required
def marketplace():
    cat_f    = request.args.get('category', '')
    status_f = request.args.get('status', '')
    query    = MarketItem.query
    if cat_f:
        query = query.filter_by(category=cat_f)
    if status_f:
        query = query.filter_by(status=status_f)
    items = query.order_by(MarketItem.created_at.desc()).all()
    return render_template('admin/marketplace.html', items=items, cat_f=cat_f, status_f=status_f)


@admin_bp.route('/admin/marketplace/<int:iid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_listing(iid):
    item  = MarketItem.query.get_or_404(iid)
    title = item.title
    db.session.delete(item)
    db.session.commit()
    log_action('admin_delete_listing', f'Deleted listing "{title}"', current_user.id)
    flash(f'Listing "{title}" deleted.', 'success')
    return redirect(url_for('admin.marketplace'))


# ── Jobs ──────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/jobs')
@login_required
@admin_required
def jobs():
    status_f = request.args.get('status', '')
    query    = RunnerJob.query
    if status_f:
        query = query.filter_by(status=status_f)
    all_jobs = query.order_by(RunnerJob.created_at.desc()).all()
    return render_template('admin/jobs.html', jobs=all_jobs, status_f=status_f)


@admin_bp.route('/admin/jobs/<int:jid>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_job_admin(jid):
    from app.services.escrow_service import credit_wallet
    job = RunnerJob.query.get_or_404(jid)
    if job.status not in ('open', 'claimed'):
        flash(f'Cannot cancel — status is "{job.status}".', 'danger')
        return redirect(url_for('admin.jobs'))
    if job.escrow_locked:
        credit_wallet(job.poster_id, job.reward, f'Admin refund: {job.title}')
        job.escrow_locked = False
    job.status = 'cancelled'
    db.session.commit()
    log_action('admin_cancel_job', f'Cancelled job #{jid}: {job.title}', current_user.id)
    flash(f'Job "{job.title}" cancelled and escrow refunded.', 'success')
    return redirect(url_for('admin.jobs'))


# ── Bounties ──────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/bounties')
@login_required
@admin_required
def bounties():
    status_f     = request.args.get('status', '')
    query        = Bounty.query
    if status_f:
        query = query.filter_by(status=status_f)
    all_bounties = query.order_by(Bounty.created_at.desc()).all()
    return render_template('admin/bounties.html', bounties=all_bounties, status_f=status_f)


@admin_bp.route('/admin/bounties/<int:bid>/close', methods=['POST'])
@login_required
@admin_required
def close_bounty(bid):
    from app.services.escrow_service import credit_wallet
    bounty = Bounty.query.get_or_404(bid)
    if bounty.status not in ('open', 'claimed'):
        flash(f'Cannot close — status is "{bounty.status}".', 'danger')
        return redirect(url_for('admin.bounties'))
    credit_wallet(bounty.poster_id, bounty.reward, f'Admin close: {bounty.title}')
    bounty.status = 'closed'
    db.session.commit()
    log_action('admin_close_bounty', f'Closed bounty "{bounty.title}"', current_user.id)
    flash(f'Bounty "{bounty.title}" closed and reward refunded.', 'success')
    return redirect(url_for('admin.bounties'))


# ── Wallet Transactions ───────────────────────────────────────────────────────

@admin_bp.route('/admin/wallet')
@login_required
@admin_required
def wallet_txs():
    tx_type         = request.args.get('type', '')
    uid             = request.args.get('user_id', type=int)
    query           = WalletTx.query
    if tx_type:
        query = query.filter_by(tx_type=tx_type)
    if uid:
        query = query.filter_by(user_id=uid)
    txs             = query.order_by(WalletTx.created_at.desc()).limit(300).all()
    total_liquidity = db.session.query(db.func.sum(User.wallet_balance)).scalar() or 0
    total_credits   = db.session.query(db.func.sum(WalletTx.amount)).filter(
                          WalletTx.tx_type == 'credit').scalar() or 0
    total_debits    = db.session.query(db.func.sum(WalletTx.amount)).filter(
                          WalletTx.tx_type == 'debit').scalar() or 0
    total_escrow    = db.session.query(db.func.sum(WalletTx.amount)).filter(
                          WalletTx.tx_type == 'escrow_lock').scalar() or 0
    all_users       = User.query.order_by(User.username).all()
    return render_template('admin/wallet.html',
        txs=txs, tx_type=tx_type, uid=uid, all_users=all_users,
        total_liquidity=total_liquidity, total_credits=total_credits,
        total_debits=total_debits, total_escrow=total_escrow,
    )


# ── AI Chat Log ───────────────────────────────────────────────────────────────

@admin_bp.route('/admin/chat')
@login_required
@admin_required
def chat_log():
    uid        = request.args.get('user_id', type=int)
    query      = ChatMessage.query
    if uid:
        query = query.filter_by(user_id=uid)
    msgs       = query.order_by(ChatMessage.created_at.desc()).limit(300).all()
    all_users  = User.query.order_by(User.username).all()
    total_msgs = ChatMessage.query.count()
    ai_msgs    = ChatMessage.query.filter_by(role='assistant').count()
    user_msgs  = total_msgs - ai_msgs
    sessions   = db.session.query(
        db.func.count(db.func.distinct(ChatMessage.chat_session_id))).scalar() or 0
    return render_template('admin/chat.html',
        msgs=msgs, all_users=all_users, uid=uid,
        total_msgs=total_msgs, ai_msgs=ai_msgs, user_msgs=user_msgs, sessions=sessions,
    )


# ── Goals ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/goals')
@login_required
@admin_required
def goals_log():
    uid              = request.args.get('user_id', type=int)
    completed        = request.args.get('completed', '')
    query            = Goal.query
    if uid:
        query = query.filter_by(user_id=uid)
    if completed == '1':
        query = query.filter_by(is_completed=True)
    elif completed == '0':
        query = query.filter_by(is_completed=False)
    all_goals        = query.order_by(Goal.created_at.desc()).all()
    all_users        = User.query.order_by(User.username).all()
    total_goals      = Goal.query.count()
    completed_goals  = Goal.query.filter_by(is_completed=True).count()
    total_milestones = Milestone.query.count()
    done_milestones  = Milestone.query.filter_by(is_completed=True).count()
    return render_template('admin/goals.html',
        goals=all_goals, all_users=all_users, uid=uid, completed=completed,
        total_goals=total_goals, completed_goals=completed_goals,
        total_milestones=total_milestones, done_milestones=done_milestones,
    )


# ── Network ───────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/network')
@login_required
@admin_required
def network_log():
    uid             = request.args.get('user_id', type=int)
    query           = NetworkContact.query
    if uid:
        query = query.filter_by(user_id=uid)
    contacts        = query.order_by(NetworkContact.created_at.desc()).all()
    all_users       = User.query.order_by(User.username).all()
    total_contacts  = NetworkContact.query.count()
    pending_alerts  = NetworkAlert.query.filter_by(is_completed=False).count()
    total_alerts    = NetworkAlert.query.count()
    from datetime import datetime
    upcoming = (NetworkAlert.query
                .filter_by(is_completed=False)
                .filter(NetworkAlert.alert_date >= datetime.utcnow())
                .order_by(NetworkAlert.alert_date.asc())
                .limit(10).all())
    return render_template('admin/network.html',
        contacts=contacts, all_users=all_users, uid=uid,
        total_contacts=total_contacts, pending_alerts=pending_alerts,
        total_alerts=total_alerts, upcoming=upcoming,
    )


# ── Documents ─────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/docs')
@login_required
@admin_required
def docs_log():
    uid        = request.args.get('user_id', type=int)
    doc_type   = request.args.get('type', '')
    query      = Document.query
    if uid:
        query = query.filter_by(user_id=uid)
    if doc_type:
        query = query.filter_by(doc_type=doc_type)
    docs       = query.order_by(Document.created_at.desc()).all()
    all_users  = User.query.order_by(User.username).all()
    total_docs = Document.query.count()
    type_counts = {
        t: Document.query.filter_by(doc_type=t).count()
        for t in ('cv', 'cover_letter', 'email', 'letter')
    }
    return render_template('admin/docs.html',
        docs=docs, all_users=all_users, uid=uid, doc_type=doc_type,
        total_docs=total_docs, type_counts=type_counts,
    )


# ── Runners ───────────────────────────────────────────────────────────────────

@admin_bp.route('/admin/runners')
@login_required
@admin_required
def runners():
    status_f = request.args.get('status', '')
    query = RunnerProfile.query
    if status_f:
        query = query.filter_by(status=status_f)
    profiles = query.order_by(RunnerProfile.created_at.desc()).all()
    return render_template('admin/runners.html', profiles=profiles, status_f=status_f)


@admin_bp.route('/admin/runners/<int:pid>/approve', methods=['POST'])
@login_required
@admin_required
def approve_runner(pid):
    from datetime import datetime
    profile = RunnerProfile.query.get_or_404(pid)
    profile.status = 'approved'
    profile.approved_at = datetime.utcnow()
    profile.user.is_runner = True
    db.session.commit()
    log_action('runner_approved', f'Runner application approved for {profile.user.username}', current_user.id)
    flash(f'{profile.user.username} approved as a runner.', 'success')
    return redirect(url_for('admin.runners'))


@admin_bp.route('/admin/runners/<int:pid>/reject', methods=['POST'])
@login_required
@admin_required
def reject_runner(pid):
    profile = RunnerProfile.query.get_or_404(pid)
    profile.status = 'rejected'
    profile.user.is_runner = False
    profile.user.runner_active = False
    db.session.commit()
    log_action('runner_rejected', f'Runner application rejected for {profile.user.username}', current_user.id)
    flash(f'{profile.user.username} runner application rejected.', 'info')
    return redirect(url_for('admin.runners'))


# ── System Logs ───────────────────────────────────────────────────────────────

@admin_bp.route('/admin/logs')
@login_required
@admin_required
def logs():
    action_type  = request.args.get('action', '')
    uid          = request.args.get('user_id', type=int)
    query        = ActionLog.query
    if action_type:
        query = query.filter_by(action_type=action_type)
    if uid:
        query = query.filter_by(user_id=uid)
    all_logs     = query.order_by(ActionLog.created_at.desc()).limit(500).all()
    all_users    = User.query.order_by(User.username).all()
    action_types = sorted([r[0] for r in db.session.query(ActionLog.action_type).distinct().all()])
    total_logs   = ActionLog.query.count()
    return render_template('admin/logs.html',
        logs=all_logs, all_users=all_users,
        action_type=action_type, uid=uid,
        action_types=action_types, total_logs=total_logs,
    )
