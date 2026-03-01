from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.extensions import db, socketio
from app.models import RunnerJob, JobNegotiation, RunnerProfile
from app.services.escrow_service import lock_escrow, release_escrow, credit_wallet, InsufficientFundsError
from app.services.logger_service import log_action

jobs_bp = Blueprint('jobs', __name__)

PLATFORM_FEE_PCT = 0.10


@jobs_bp.route('/jobs')
@login_required
def index():
    status_filter = request.args.get('status', 'open')
    if status_filter not in ['open', 'claimed', 'pending_confirmation', 'completed', 'all']:
        status_filter = 'open'

    q = RunnerJob.query
    if status_filter != 'all':
        q = q.filter_by(status=status_filter)
    jobs = q.order_by(RunnerJob.created_at.desc()).all()

    # Jobs the current user posted that have an active runner and need confirmation
    needs_confirmation = RunnerJob.query.filter(
        RunnerJob.poster_id == current_user.id,
        RunnerJob.status.in_(['claimed', 'pending_confirmation']),
        RunnerJob.runner_id.isnot(None),
    ).all()

    return render_template('jobs/index.html', jobs=jobs, status_filter=status_filter,
                           needs_confirmation=needs_confirmation)


@jobs_bp.route('/jobs/new', methods=['GET', 'POST'])
@login_required
def new_job():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        reward_str = request.form.get('reward', '0')

        if not title or not description:
            flash('Title and description required.', 'danger')
            return render_template('jobs/new.html')
        try:
            reward = float(reward_str)
            if reward <= 0:
                raise ValueError
        except ValueError:
            flash('Enter a valid reward amount.', 'danger')
            return render_template('jobs/new.html')

        try:
            lock_escrow(current_user.id, reward, f'Runner job: {title}')
        except InsufficientFundsError as e:
            flash(str(e), 'danger')
            return render_template('jobs/new.html')

        job = RunnerJob(
            poster_id=current_user.id,
            title=title,
            description=description,
            reward=reward,
            escrow_locked=True,
        )
        db.session.add(job)
        db.session.commit()
        log_action('runner_job_posted', f'{current_user.username} posted job "{title}" R{reward:.2f}', current_user.id)
        socketio.emit('new_job', {'id': job.id, 'title': job.title, 'reward': job.reward, 'poster': current_user.username})
        flash(f'Job posted! R{reward:.2f} locked in escrow.', 'success')
        return redirect(url_for('jobs.index'))

    return render_template('jobs/new.html')


@jobs_bp.route('/jobs/<int:job_id>/claim', methods=['POST'])
@login_required
def claim_job(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.status != 'open':
        flash('Job no longer available.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.poster_id == current_user.id:
        flash("Can't claim your own job.", 'danger')
        return redirect(url_for('jobs.index'))

    # Must be an approved runner to claim
    approved = RunnerProfile.query.filter_by(user_id=current_user.id, status='approved').first()
    if not approved:
        flash('You need an approved runner profile to claim jobs. Apply at /runner/register.', 'danger')
        return redirect(url_for('jobs.index'))

    job.runner_id = current_user.id
    job.status = 'claimed'
    current_user.is_runner = True
    db.session.commit()
    log_action('job_claimed', f'{current_user.username} claimed job #{job.id}', current_user.id)
    flash(f'Job claimed! Go get it done — R{job.reward:.2f} awaits.', 'success')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/mark_done', methods=['POST'])
@login_required
def mark_done(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.status != 'claimed':
        flash('Job not in claimed state.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.runner_id != current_user.id:
        flash('Only the runner can mark a job as done.', 'danger')
        return redirect(url_for('jobs.index'))

    job.status = 'pending_confirmation'
    db.session.commit()
    log_action('job_mark_done', f'Runner @{current_user.username} marked job #{job.id} done — awaiting poster confirmation', current_user.id)
    socketio.emit('job_pending_confirmation', {'id': job.id, 'runner': current_user.username})
    flash('Job marked as done. Waiting for the poster to confirm.', 'success')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/complete', methods=['POST'])
@login_required
def complete_job(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.status not in ('pending_confirmation', 'claimed'):
        flash('Job cannot be confirmed at this stage.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.poster_id != current_user.id and not current_user.is_admin:
        flash('Only the poster can confirm completion.', 'danger')
        return redirect(url_for('jobs.index'))

    job.status = 'completed'
    db.session.commit()

    if job.job_type == 'delivery':
        fee = job.reward * PLATFORM_FEE_PCT
        net = job.reward - fee
        release_escrow(job.runner_id, net, f'Delivery completed: {job.title} (net of {int(PLATFORM_FEE_PCT*100)}% platform fee)')
        # Update runner profile stats
        profile = RunnerProfile.query.filter_by(user_id=job.runner_id).first()
        if profile:
            profile.total_deliveries += 1
            profile.total_earned += net
            db.session.commit()
        log_action('platform_fee', f'R{fee:.2f} retained on delivery job #{job.id}', None)
        log_action('job_completed', f'Delivery #{job.id} done — R{net:.2f} released to runner', job.runner_id)
        flash(f'Delivery done! R{net:.2f} released to runner (R{fee:.2f} platform fee retained).', 'success')
    else:
        release_escrow(job.runner_id, job.reward, f'Job completed: {job.title}')
        log_action('job_completed', f'Job #{job.id} completed — R{job.reward:.2f} released to runner', job.runner_id)
        flash(f'Job done! R{job.reward:.2f} released to runner.', 'success')

    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def cancel_job(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.poster_id != current_user.id and not current_user.is_admin:
        flash('Not authorized.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.status not in ('open', 'claimed', 'pending_confirmation'):
        flash('Cannot cancel this job.', 'danger')
        return redirect(url_for('jobs.index'))

    job.status = 'cancelled'
    db.session.commit()
    from app.services.escrow_service import credit_wallet
    if job.escrow_locked:
        credit_wallet(job.poster_id, job.reward, f'Job cancelled refund: {job.title}')
    log_action('job_cancelled', f'Job #{job.id} cancelled — refunded R{job.reward:.2f}', current_user.id)
    flash(f'Job cancelled. R{job.reward:.2f} refunded.', 'success')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/negotiate', methods=['POST'])
@login_required
def negotiate(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.status != 'open':
        flash('Job is no longer open for offers.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.poster_id == current_user.id:
        flash("You can't make an offer on your own job.", 'danger')
        return redirect(url_for('jobs.index'))

    try:
        proposed_reward = float(request.form.get('proposed_reward', '0'))
        if proposed_reward <= 0:
            raise ValueError
    except ValueError:
        flash('Enter a valid proposed reward.', 'danger')
        return redirect(url_for('jobs.index'))

    message = request.form.get('message', '').strip()

    negotiation = JobNegotiation(
        job_id=job.id,
        runner_id=current_user.id,
        proposed_reward=proposed_reward,
        message=message,
    )
    db.session.add(negotiation)
    db.session.commit()

    socketio.emit(f'job_offer_{job.id}', {
        'negotiation_id': negotiation.id,
        'runner': current_user.username,
        'proposed_reward': proposed_reward,
        'message': message,
    })

    log_action('job_negotiation', f'{current_user.username} offered R{proposed_reward:.2f} on job #{job.id}', current_user.id)
    flash(f'Offer of R{proposed_reward:.2f} submitted to the poster.', 'success')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/negotiate/<int:nid>/accept', methods=['POST'])
@login_required
def accept_offer(job_id, nid):
    job = RunnerJob.query.get_or_404(job_id)
    neg = JobNegotiation.query.get_or_404(nid)

    if job.poster_id != current_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.status != 'open':
        flash('Job is no longer open.', 'danger')
        return redirect(url_for('jobs.index'))

    # Adjust escrow if reward changed
    if neg.proposed_reward != job.reward and job.escrow_locked:
        from app.services.escrow_service import credit_wallet, debit_wallet
        diff = neg.proposed_reward - job.reward
        if diff > 0:
            try:
                from app.services.escrow_service import lock_escrow
                lock_escrow(current_user.id, diff, f'Escrow top-up for job #{job.id}')
            except InsufficientFundsError as e:
                flash(str(e), 'danger')
                return redirect(url_for('jobs.index'))
        else:
            credit_wallet(current_user.id, -diff, f'Escrow reduction for job #{job.id}')

    job.reward = neg.proposed_reward
    job.runner_id = neg.runner_id
    job.status = 'claimed'
    neg.status = 'accepted'
    # Reject other offers
    for other in job.negotiations:
        if other.id != nid and other.status == 'pending':
            other.status = 'rejected'
    db.session.commit()

    log_action('offer_accepted',
               f'Poster accepted R{neg.proposed_reward:.2f} from @{neg.runner.username} on job #{job.id}',
               current_user.id)
    flash(f'Offer accepted! @{neg.runner.username} is now your runner at R{neg.proposed_reward:.2f}.', 'success')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/negotiate/<int:nid>/reject', methods=['POST'])
@login_required
def reject_offer(job_id, nid):
    job = RunnerJob.query.get_or_404(job_id)
    neg = JobNegotiation.query.get_or_404(nid)

    if job.poster_id != current_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('jobs.index'))

    neg.status = 'rejected'
    db.session.commit()
    log_action('offer_rejected',
               f'Poster rejected offer from @{neg.runner.username} on job #{job.id}',
               current_user.id)
    flash('Offer rejected.', 'info')
    return redirect(url_for('jobs.index'))


@jobs_bp.route('/jobs/<int:job_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_job(job_id):
    job = RunnerJob.query.get_or_404(job_id)
    if job.poster_id != current_user.id:
        flash('Not authorised.', 'danger')
        return redirect(url_for('jobs.index'))
    if job.status not in ('open', 'claimed'):
        flash('Cannot edit a completed or cancelled job.', 'danger')
        return redirect(url_for('jobs.index'))

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        try:
            new_reward = float(request.form.get('reward', job.reward))
            if new_reward <= 0:
                raise ValueError
        except ValueError:
            flash('Enter a valid reward amount.', 'danger')
            return render_template('jobs/edit.html', job=job)

        if not title or not description:
            flash('Title and description are required.', 'danger')
            return render_template('jobs/edit.html', job=job)

        # Adjust escrow if reward changed
        if job.escrow_locked and new_reward != job.reward:
            diff = new_reward - job.reward
            if diff > 0:
                try:
                    lock_escrow(current_user.id, diff, f'Job reward increase: {title}')
                except InsufficientFundsError as e:
                    flash(str(e), 'danger')
                    return render_template('jobs/edit.html', job=job)
            else:
                credit_wallet(current_user.id, abs(diff), f'Job reward decrease: {title}')

        job.title       = title
        job.description = description
        job.reward      = new_reward
        db.session.commit()
        log_action('job_edited', f'{current_user.username} edited job "{title}"', current_user.id)

        socketio.emit('job_updated', {
            'id':          job.id,
            'title':       job.title,
            'description': job.description,
            'reward':      job.reward,
        })

        flash('Job updated.', 'success')
        return redirect(url_for('jobs.index'))

    return render_template('jobs/edit.html', job=job)


# Legacy toggle route — now redirects to runner blueprint
@jobs_bp.route('/runner/toggle', methods=['POST'])
@login_required
def toggle_runner():
    return redirect(url_for('runner.toggle'), code=307)
