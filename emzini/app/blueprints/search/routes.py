from flask import Blueprint, render_template, request
from flask_login import login_required
from app.models import MarketItem, RunnerJob, Bounty, CivicReport, CommunityPost, User
from app.extensions import db

search_bp = Blueprint('search', __name__)

LIMIT = 8   # max results per category


@search_bp.route('/search')
@login_required
def results():
    q = request.args.get('q', '').strip()
    if not q:
        return render_template('search/results.html', q='', groups=[])

    pat = f'%{q}%'

    items = (MarketItem.query
             .filter(MarketItem.status == 'available',
                     db.or_(MarketItem.title.ilike(pat),
                             MarketItem.description.ilike(pat),
                             MarketItem.category.ilike(pat)))
             .order_by(MarketItem.created_at.desc())
             .limit(LIMIT).all())

    jobs = (RunnerJob.query
            .filter(RunnerJob.status == 'open',
                    db.or_(RunnerJob.title.ilike(pat),
                            RunnerJob.description.ilike(pat)))
            .order_by(RunnerJob.created_at.desc())
            .limit(LIMIT).all())

    bounties = (Bounty.query
                .filter(Bounty.status == 'open',
                        db.or_(Bounty.title.ilike(pat),
                                Bounty.description.ilike(pat)))
                .order_by(Bounty.created_at.desc())
                .limit(LIMIT).all())

    civic = (CivicReport.query
             .filter(db.or_(CivicReport.title.ilike(pat),
                             CivicReport.description.ilike(pat)))
             .order_by(CivicReport.created_at.desc())
             .limit(LIMIT).all())

    posts = (CommunityPost.query
             .filter(CommunityPost.content.ilike(pat))
             .order_by(CommunityPost.created_at.desc())
             .limit(LIMIT).all())

    users = (User.query
             .filter(User.username.ilike(pat))
             .order_by(User.reputation.desc())
             .limit(6).all())

    groups = [
        ('Market Items',    'fa-shop',                  'text-amber-400',  items,    _item_link),
        ('Runner Jobs',     'fa-person-running',         'text-teal-400',   jobs,     _job_link),
        ('Bounties',        'fa-trophy',                 'text-indigo-400', bounties, _bounty_link),
        ('Community Board', 'fa-triangle-exclamation',   'text-blue-400',   civic,    _civic_link),
        ('Community Posts', 'fa-comments',               'text-purple-400', posts,    _post_link),
        ('Residents',       'fa-user',                   'text-zinc-400',   users,    _user_link),
    ]
    # only include groups that have results
    groups = [(label, icon, color, items, link_fn)
              for label, icon, color, items, link_fn in groups if items]

    total = sum(len(g[3]) for g in groups)
    return render_template('search/results.html', q=q, groups=groups, total=total)


# ── Result helpers ────────────────────────────────────────────────────────────

def _item_link(r):
    return f'/market/{r.id}'

def _job_link(r):
    return f'/jobs'

def _bounty_link(r):
    return f'/bounties'

def _civic_link(r):
    return f'/civic'

def _post_link(r):
    return f'/messages?tab=community'

def _user_link(r):
    return f'/profile/{r.id}'
