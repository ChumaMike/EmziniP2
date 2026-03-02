from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from app.extensions import db
from app.models import Goal, Milestone
from app.services.logger_service import log_action

goals_bp = Blueprint('goals', __name__)

CATEGORIES = ['Personal', 'Career', 'Health', 'Financial', 'Education', 'Community']


@goals_bp.route('/goals')
@login_required
def index():
    active    = Goal.query.filter_by(user_id=current_user.id, is_completed=False)\
                          .order_by(Goal.created_at.desc()).all()
    completed = Goal.query.filter_by(user_id=current_user.id, is_completed=True)\
                          .order_by(Goal.created_at.desc()).limit(10).all()
    return render_template('goals/index.html',
                           active=active, completed=completed,
                           categories=CATEGORIES)


@goals_bp.route('/goals/add', methods=['POST'])
@login_required
def add():
    title       = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category    = request.form.get('category', 'Personal')
    target_str  = request.form.get('target_date', '').strip()

    if not title:
        flash('Goal title is required.', 'danger')
        return redirect(url_for('goals.index'))

    target_date = None
    if target_str:
        try:
            target_date = datetime.strptime(target_str, '%Y-%m-%d')
        except ValueError:
            pass

    goal = Goal(user_id=current_user.id, title=title,
                description=description or None,
                category=category if category in CATEGORIES else 'Personal',
                target_date=target_date)
    db.session.add(goal)
    db.session.commit()
    log_action('goal_added', f'{current_user.username} added goal "{title}"', current_user.id)
    flash(f'Goal "{title}" created!', 'success')
    return redirect(url_for('goals.index'))


@goals_bp.route('/goals/<int:goal_id>')
@login_required
def detail(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    return render_template('goals/detail.html', goal=goal)


@goals_bp.route('/goals/<int:goal_id>/add-milestone', methods=['POST'])
@login_required
def add_milestone(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    title = request.form.get('title', '').strip()
    if not title:
        flash('Milestone title required.', 'danger')
        return redirect(url_for('goals.detail', goal_id=goal_id))
    m = Milestone(goal_id=goal_id, title=title)
    db.session.add(m)
    db.session.commit()
    goal.recalculate_progress()
    db.session.commit()
    return redirect(url_for('goals.detail', goal_id=goal_id))


@goals_bp.route('/goals/<int:goal_id>/toggle-milestone/<int:ms_id>', methods=['POST'])
@login_required
def toggle_milestone(goal_id, ms_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    ms = Milestone.query.filter_by(id=ms_id, goal_id=goal_id).first_or_404()
    ms.is_completed = not ms.is_completed
    db.session.commit()
    goal.recalculate_progress()
    db.session.commit()
    return redirect(url_for('goals.detail', goal_id=goal_id))


@goals_bp.route('/goals/<int:goal_id>/complete', methods=['POST'])
@login_required
def complete(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    goal.is_completed = True
    goal.progress = 100
    for m in goal.milestones:
        m.is_completed = True
    current_user.rep_personal += 10
    current_user.reputation += 10
    db.session.commit()
    log_action('goal_completed', f'{current_user.username} completed goal "{goal.title}"', current_user.id)
    flash(f'Goal complete! +10 reputation.', 'success')
    return redirect(url_for('goals.index'))


@goals_bp.route('/goals/<int:goal_id>/delete', methods=['POST'])
@login_required
def delete(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    db.session.delete(goal)
    db.session.commit()
    flash('Goal removed.', 'success')
    return redirect(url_for('goals.index'))
