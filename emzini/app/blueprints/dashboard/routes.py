from datetime import datetime, timedelta
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.models import CivicReport, User, Goal, NetworkAlert, NetworkContact, ChatMessage, RunnerJob, MarketItem, Bounty

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    total_residents = User.query.count()
    open_issues     = CivicReport.query.filter_by(status='open').count()
    in_progress     = CivicReport.query.filter_by(status='in_progress').count()
    resolved        = CivicReport.query.filter_by(status='resolved').count()

    # Most urgent issues (critical/high, open)
    urgent = (CivicReport.query
              .filter(CivicReport.status == 'open',
                      CivicReport.severity.in_(['critical', 'high']))
              .order_by(CivicReport.upvotes.desc())
              .limit(4).all())

    # Recent community activity
    recent_reports = (CivicReport.query
                      .order_by(CivicReport.created_at.desc())
                      .limit(5).all())

    # Goals: current user's top 3 active goals
    active_goals = (Goal.query
                    .filter_by(user_id=current_user.id, is_completed=False)
                    .order_by(Goal.created_at.desc())
                    .limit(3).all())
    goals_total = Goal.query.filter_by(user_id=current_user.id).count()

    # Network: upcoming alerts in the next 7 days
    now = datetime.utcnow()
    week_out = now + timedelta(days=7)
    upcoming_alerts = (NetworkAlert.query
                       .filter_by(user_id=current_user.id, is_completed=False)
                       .filter(NetworkAlert.alert_date >= now,
                               NetworkAlert.alert_date <= week_out)
                       .order_by(NetworkAlert.alert_date.asc())
                       .limit(5).all())
    contacts_total = NetworkContact.query.filter_by(user_id=current_user.id).count()

    # Chat history: last 20 messages for this login session only
    chat_history = (ChatMessage.query
                    .filter_by(user_id=current_user.id,
                               chat_session_id=current_user.chat_session_id)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(20).all())

    # Personal economy stats
    open_jobs_count     = RunnerJob.query.filter_by(status='open').count()
    my_listings_count   = MarketItem.query.filter_by(seller_id=current_user.id, status='available').count()
    open_bounties_count = Bounty.query.filter_by(status='open').count()

    return render_template('dashboard/index.html',
        total_residents=total_residents,
        open_issues=open_issues,
        in_progress=in_progress,
        resolved=resolved,
        urgent=urgent,
        recent_reports=recent_reports,
        active_goals=active_goals,
        goals_total=goals_total,
        upcoming_alerts=upcoming_alerts,
        contacts_total=contacts_total,
        chat_history=chat_history,
        open_jobs_count=open_jobs_count,
        my_listings_count=my_listings_count,
        open_bounties_count=open_bounties_count,
    )
