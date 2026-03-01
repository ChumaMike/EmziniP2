from datetime import datetime, timedelta
from google import genai
from google.genai import types
from flask import current_app

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are EMZINI AI — the built-in assistant for the Emzini residential super-app.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IS EMZINI?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Emzini ("home" in Zulu) is a residential micro-economy platform for people living in the same complex.
It brings together community reporting, a local marketplace, errand runners, personal goal tracking,
and a professional network — all in one place.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEATURES & WHAT THEY DO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. DASHBOARD
   The home screen. Shows live stats (residents, open issues, resolved issues), urgent community
   issues, your active goals with progress bars, upcoming network reminders, quick actions, and
   the AI chat panel. Your personal hub at a glance.

2. COMMUNITY BOARD (/civic)
   Report infrastructure and safety issues in the complex — potholes, burst pipes, electricity
   faults, safety concerns, etc. Other residents can upvote reports to signal urgency. Admins
   update the status (open → in_progress → resolved). Severity levels: low, medium, high, critical.

3. RESIDENT MARKET (/market)
   A peer-to-peer marketplace for residents. List items for sale (electronics, furniture, clothing,
   food, services, general). Buyers pay directly via the Emzini wallet. No delivery needed —
   items are collected within the complex. Photo uploads supported.

4. RUNNER JOBS (/jobs)
   Post errands and delivery tasks for other residents to complete. The reward is locked in escrow
   when you post so the runner is guaranteed payment. Runners claim jobs, complete them, and earn
   the reward. Good for: buying groceries, collecting parcels, picking up takeaways, etc.

5. BOUNTIES (/bounties)
   Post a reward for a lost item found within or around the complex. The finder claims the bounty.
   Reward is locked in escrow. Good for lost keys, phones, pets, wallets, etc.

6. WALLET (/wallet)
   Every resident gets a wallet. New users start with R50 credit. Used to pay for market purchases,
   fund runner job rewards, and post bounties. All transactions go through escrow for safety.

7. GOALS (/goals)
   Personal goal tracker. Set goals with a title, category, optional target date, and description.
   Add milestones to break the goal into steps — progress auto-calculates from milestone completion.
   Completing a goal gives +10 reputation. Categories: Personal, Career, Health, Financial,
   Education, Community.

8. NETWORK (/network)
   A personal contact manager for your professional network. Save contacts with name, role, phone,
   email, and notes. Set follow-up reminders (Call, Email, Meeting, Follow-up, Other) with a date.
   Reminders appear on the dashboard so you never miss a follow-up.

9. DOCUMENTS (/docs)
   AI-assisted document creator. Generate and save CVs, cover letters, emails, and formal letters.
   Useful for job applications and official correspondence.

10. PROFILE (/profile)
    Manage your username, email, and password. Toggle Runner Mode — when active, you appear as
    available to deliver and claim runner jobs. Your runner status shows as a live pulse indicator
    in the nav.

11. ADMIN CONSOLE (/admin) — admin only
    System logs, telemetry, user leaderboard. Only accessible to admin users.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR TOOLS — what you can DO for the user
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Marketplace  : post item, view my listings, delete a listing
Runner jobs  : post job (escrow), view open jobs, view my jobs, claim a job, cancel a job
Bounties     : post bounty (escrow), view open bounties, delete a bounty
Civic        : report issue, view my reports, delete a report, upvote a report
Runner       : go active / go offline
Wallet       : check balance
Goals        : view goals, add goal, add milestone to goal, complete goal, delete goal
Network      : view contacts, add contact, delete contact,
               view reminders, add reminder, complete reminder, delete reminder

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOUR RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. When asked to DO something, call the tool immediately — don't describe it, just do it.
2. If required info is missing (price, name, date, etc.) ask ONE short clarifying question first.
3. After a tool call, confirm in one sentence what was done.
4. If a tool returns an error, explain it simply and suggest a fix.
5. If the request is ambiguous, ask a short clarifying question.
6. When explaining features, be concise but complete. Use the feature descriptions above.
7. Use casual South African English where natural (eish, sharp, lekker, howzit, sho).
8. Keep responses short. No markdown headers in chat. Conversational tone."""


# ── Date parser helper ─────────────────────────────────────────────────────────

def _parse_date(text: str) -> datetime:
    t = text.strip().lower()
    now = datetime.utcnow()
    if t in ('today',):
        return now
    if t in ('tomorrow',):
        return now + timedelta(days=1)
    if t in ('next week',):
        return now + timedelta(days=7)
    if t in ('next month',):
        return now + timedelta(days=30)
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d %B %Y', '%d %b %Y', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not understand date: '{text}'. Please use YYYY-MM-DD format.")


# ── Tool declarations ──────────────────────────────────────────────────────────

TOOLS = [types.Tool(function_declarations=[

    # ── Marketplace ────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='post_market_item',
        description='Post a new item for sale on the marketplace',
        parameters=types.Schema(
            type='OBJECT',
            properties={
                'title':       types.Schema(type='STRING', description='Item name'),
                'description': types.Schema(type='STRING', description='Item description'),
                'price':       types.Schema(type='NUMBER', description='Price in Rands (R)'),
                'category':    types.Schema(type='STRING',
                    enum=['electronics', 'furniture', 'clothing', 'food', 'services', 'general']),
            },
            required=['title', 'description', 'price'],
        ),
    ),
    types.FunctionDeclaration(
        name='get_my_listings',
        description="Get the user's active marketplace listings",
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='delete_market_item',
        description="Remove one of the user's own marketplace listings",
        parameters=types.Schema(type='OBJECT',
            properties={'item_id': types.Schema(type='INTEGER', description='Listing ID to remove')},
            required=['item_id']),
    ),

    # ── Runner jobs ────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='post_runner_job',
        description='Post a runner job — reward is locked in escrow immediately',
        parameters=types.Schema(type='OBJECT',
            properties={
                'title':       types.Schema(type='STRING'),
                'description': types.Schema(type='STRING'),
                'reward':      types.Schema(type='NUMBER', description='Reward in Rands'),
            },
            required=['title', 'description', 'reward']),
    ),
    types.FunctionDeclaration(
        name='get_active_jobs',
        description='List open runner jobs available to claim',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='get_my_jobs',
        description='List jobs posted by the current user',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='claim_job',
        description='Claim an open runner job to complete it and earn the reward',
        parameters=types.Schema(type='OBJECT',
            properties={'job_id': types.Schema(type='INTEGER', description='Job ID to claim')},
            required=['job_id']),
    ),
    types.FunctionDeclaration(
        name='cancel_job',
        description='Cancel your own posted job and release escrow back to your wallet',
        parameters=types.Schema(type='OBJECT',
            properties={'job_id': types.Schema(type='INTEGER', description='Job ID to cancel')},
            required=['job_id']),
    ),

    # ── Bounties ───────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='post_bounty',
        description='Post a bounty/reward for a lost item — locked in escrow',
        parameters=types.Schema(type='OBJECT',
            properties={
                'title':       types.Schema(type='STRING', description='What was lost'),
                'description': types.Schema(type='STRING'),
                'reward':      types.Schema(type='NUMBER', description='Reward in Rands'),
            },
            required=['title', 'description', 'reward']),
    ),
    types.FunctionDeclaration(
        name='get_bounties',
        description='List open bounties posted by all residents',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='delete_bounty',
        description='Remove your own bounty and release the escrow reward',
        parameters=types.Schema(type='OBJECT',
            properties={'bounty_id': types.Schema(type='INTEGER')},
            required=['bounty_id']),
    ),

    # ── Civic ──────────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='post_civic_report',
        description='Report a civic/infrastructure issue in the complex',
        parameters=types.Schema(type='OBJECT',
            properties={
                'title':       types.Schema(type='STRING'),
                'description': types.Schema(type='STRING'),
                'category':    types.Schema(type='STRING',
                    enum=['pothole', 'pipe', 'electricity', 'safety', 'other']),
                'severity':    types.Schema(type='STRING',
                    enum=['low', 'medium', 'high', 'critical']),
            },
            required=['title', 'description']),
    ),
    types.FunctionDeclaration(
        name='get_my_civic_reports',
        description="List the user's own civic reports",
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='delete_civic_report',
        description="Delete one of the user's own civic reports",
        parameters=types.Schema(type='OBJECT',
            properties={'report_id': types.Schema(type='INTEGER')},
            required=['report_id']),
    ),
    types.FunctionDeclaration(
        name='upvote_civic_report',
        description='Upvote a civic report to signal urgency',
        parameters=types.Schema(type='OBJECT',
            properties={'report_id': types.Schema(type='INTEGER')},
            required=['report_id']),
    ),

    # ── Runner / Wallet ────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='toggle_runner_status',
        description='Go active or offline as a runner',
        parameters=types.Schema(type='OBJECT',
            properties={'active': types.Schema(type='BOOLEAN', description='True = active, False = offline')},
            required=['active']),
    ),
    types.FunctionDeclaration(
        name='get_wallet_balance',
        description='Get the current wallet balance',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),

    # ── Goals ──────────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='get_my_goals',
        description="List the user's active (incomplete) goals",
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='add_goal',
        description='Create a new personal goal',
        parameters=types.Schema(type='OBJECT',
            properties={
                'title':       types.Schema(type='STRING'),
                'description': types.Schema(type='STRING'),
                'category':    types.Schema(type='STRING',
                    enum=['Personal', 'Career', 'Health', 'Financial', 'Education', 'Community']),
                'target_date': types.Schema(type='STRING',
                    description='Target date — YYYY-MM-DD, "tomorrow", "next week", etc.'),
            },
            required=['title']),
    ),
    types.FunctionDeclaration(
        name='add_milestone',
        description='Add a milestone step to an existing goal',
        parameters=types.Schema(type='OBJECT',
            properties={
                'goal_id': types.Schema(type='INTEGER'),
                'title':   types.Schema(type='STRING', description='Milestone description'),
            },
            required=['goal_id', 'title']),
    ),
    types.FunctionDeclaration(
        name='complete_goal',
        description='Mark a goal as completed (+10 reputation)',
        parameters=types.Schema(type='OBJECT',
            properties={'goal_id': types.Schema(type='INTEGER')},
            required=['goal_id']),
    ),
    types.FunctionDeclaration(
        name='delete_goal',
        description='Delete one of your goals',
        parameters=types.Schema(type='OBJECT',
            properties={'goal_id': types.Schema(type='INTEGER')},
            required=['goal_id']),
    ),

    # ── Network ────────────────────────────────────────────────────────────────
    types.FunctionDeclaration(
        name='get_my_contacts',
        description='List all contacts in your professional network',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='add_contact',
        description='Add a new contact to your network',
        parameters=types.Schema(type='OBJECT',
            properties={
                'name':  types.Schema(type='STRING', description='Contact full name'),
                'role':  types.Schema(type='STRING', description='Job title or role'),
                'phone': types.Schema(type='STRING'),
                'email': types.Schema(type='STRING'),
                'notes': types.Schema(type='STRING', description='Any notes about this contact'),
            },
            required=['name']),
    ),
    types.FunctionDeclaration(
        name='delete_contact',
        description='Remove a contact from your network (also removes their reminders)',
        parameters=types.Schema(type='OBJECT',
            properties={'contact_id': types.Schema(type='INTEGER')},
            required=['contact_id']),
    ),
    types.FunctionDeclaration(
        name='get_my_reminders',
        description='List your upcoming network reminders/alerts',
        parameters=types.Schema(type='OBJECT', properties={}),
    ),
    types.FunctionDeclaration(
        name='add_reminder',
        description='Set a follow-up reminder for a contact. Use get_my_contacts first if you need the contact ID.',
        parameters=types.Schema(type='OBJECT',
            properties={
                'contact_id':  types.Schema(type='INTEGER'),
                'title':       types.Schema(type='STRING', description='What the reminder is for'),
                'alert_type':  types.Schema(type='STRING',
                    enum=['Call', 'Email', 'Meeting', 'Follow-up', 'Other']),
                'alert_date':  types.Schema(type='STRING',
                    description='Date — YYYY-MM-DD, "tomorrow", "next week", etc.'),
                'description': types.Schema(type='STRING', description='Optional notes'),
            },
            required=['contact_id', 'title', 'alert_date']),
    ),
    types.FunctionDeclaration(
        name='complete_reminder',
        description='Mark a network reminder as done',
        parameters=types.Schema(type='OBJECT',
            properties={'alert_id': types.Schema(type='INTEGER')},
            required=['alert_id']),
    ),
    types.FunctionDeclaration(
        name='delete_reminder',
        description='Delete a network reminder',
        parameters=types.Schema(type='OBJECT',
            properties={'alert_id': types.Schema(type='INTEGER')},
            required=['alert_id']),
    ),

])]


# ── Tool executor ──────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict, user) -> str:
    from app.models import (MarketItem, RunnerJob, Bounty, CivicReport, CivicUpvote,
                             Goal, Milestone, NetworkContact, NetworkAlert)
    from app.extensions import db
    from app.services.escrow_service import lock_escrow, credit_wallet, InsufficientFundsError
    from app.services.logger_service import log_action

    try:

        # ── Wallet ─────────────────────────────────────────────────────────────
        if tool_name == 'get_wallet_balance':
            return f"Your wallet balance is R{user.wallet_balance:.2f}."

        # ── Marketplace ────────────────────────────────────────────────────────
        elif tool_name == 'get_my_listings':
            items = MarketItem.query.filter_by(seller_id=user.id, status='available').all()
            if not items:
                return "You have no active listings."
            return "\n".join(f"[ID:{i.id}] {i.title} — R{i.price:.2f} ({i.category})" for i in items)

        elif tool_name == 'post_market_item':
            item = MarketItem(
                seller_id=user.id, title=tool_input['title'],
                description=tool_input['description'], price=float(tool_input['price']),
                category=tool_input.get('category', 'general'),
            )
            db.session.add(item)
            db.session.commit()
            log_action('market_item_posted', f'{user.username} listed "{item.title}"', user.id)
            return f'Listed "{item.title}" for R{item.price:.2f}. (ID:{item.id})'

        elif tool_name == 'delete_market_item':
            item = MarketItem.query.get(int(tool_input['item_id']))
            if not item:
                return "Listing not found."
            if item.seller_id != user.id:
                return "You can only remove your own listings."
            db.session.delete(item)
            db.session.commit()
            return f'Listing "{item.title}" removed.'

        # ── Runner jobs ────────────────────────────────────────────────────────
        elif tool_name == 'get_active_jobs':
            jobs = RunnerJob.query.filter_by(status='open').order_by(RunnerJob.created_at.desc()).limit(8).all()
            if not jobs:
                return "No open jobs right now."
            return "\n".join(f"[ID:{j.id}] {j.title} — R{j.reward:.2f} by @{j.poster.username}" for j in jobs)

        elif tool_name == 'get_my_jobs':
            jobs = RunnerJob.query.filter_by(poster_id=user.id).order_by(RunnerJob.created_at.desc()).limit(8).all()
            if not jobs:
                return "You haven't posted any jobs."
            return "\n".join(f"[ID:{j.id}] {j.title} — R{j.reward:.2f} [{j.status}]" for j in jobs)

        elif tool_name == 'post_runner_job':
            reward = float(tool_input['reward'])
            lock_escrow(user.id, reward, 'Runner job escrow')
            job = RunnerJob(poster_id=user.id, title=tool_input['title'],
                            description=tool_input['description'], reward=reward, escrow_locked=True)
            db.session.add(job)
            db.session.commit()
            log_action('runner_job_posted', f'{user.username} posted "{job.title}"', user.id)
            from app.extensions import socketio
            socketio.emit('new_job', {'id': job.id, 'title': job.title, 'reward': job.reward, 'poster': user.username})
            return f'Job posted! "{job.title}" — R{reward:.2f} in escrow. (ID:{job.id})'

        elif tool_name == 'claim_job':
            job = RunnerJob.query.get(int(tool_input['job_id']))
            if not job:
                return "Job not found."
            if job.status != 'open':
                return f"Job is already {job.status}."
            if job.poster_id == user.id:
                return "You can't claim your own job."
            if not user.is_runner:
                return "Enable Runner Mode in your profile settings first."
            job.runner_id = user.id
            job.status = 'claimed'
            db.session.commit()
            return f'Sharp! You claimed "{job.title}". Contact @{job.poster.username} to get started.'

        elif tool_name == 'cancel_job':
            job = RunnerJob.query.get(int(tool_input['job_id']))
            if not job:
                return "Job not found."
            if job.poster_id != user.id:
                return "You can only cancel your own jobs."
            if job.status not in ('open', 'claimed'):
                return f"Cannot cancel — job is already '{job.status}'."
            if job.escrow_locked:
                credit_wallet(user.id, job.reward, f'Escrow release: {job.title}')
                job.escrow_locked = False
            job.status = 'cancelled'
            db.session.commit()
            return f'Job "{job.title}" cancelled. R{job.reward:.2f} returned to your wallet.'

        # ── Bounties ───────────────────────────────────────────────────────────
        elif tool_name == 'get_bounties':
            bounties = Bounty.query.filter_by(status='open').order_by(Bounty.created_at.desc()).limit(8).all()
            if not bounties:
                return "No open bounties right now."
            return "\n".join(f"[ID:{b.id}] {b.title} — R{b.reward:.2f} by @{b.poster.username}" for b in bounties)

        elif tool_name == 'post_bounty':
            reward = float(tool_input['reward'])
            lock_escrow(user.id, reward, 'Bounty escrow')
            bounty = Bounty(poster_id=user.id, title=tool_input['title'],
                            description=tool_input['description'], reward=reward)
            db.session.add(bounty)
            db.session.commit()
            return f'Bounty posted! "{bounty.title}" — R{reward:.2f} in escrow. (ID:{bounty.id})'

        elif tool_name == 'delete_bounty':
            bounty = Bounty.query.get(int(tool_input['bounty_id']))
            if not bounty:
                return "Bounty not found."
            if bounty.poster_id != user.id:
                return "You can only remove your own bounties."
            if bounty.status != 'open':
                return f"Cannot remove — status is '{bounty.status}'."
            credit_wallet(user.id, bounty.reward, f'Bounty release: {bounty.title}')
            bounty.status = 'closed'
            db.session.commit()
            return f'Bounty "{bounty.title}" removed. R{bounty.reward:.2f} returned to wallet.'

        # ── Civic ──────────────────────────────────────────────────────────────
        elif tool_name == 'post_civic_report':
            report = CivicReport(reporter_id=user.id, title=tool_input['title'],
                                  description=tool_input['description'],
                                  category=tool_input.get('category', 'other'),
                                  severity=tool_input.get('severity', 'medium'))
            db.session.add(report)
            db.session.commit()
            return f'Report submitted: "{report.title}" ({report.severity}). (ID:{report.id})'

        elif tool_name == 'get_my_civic_reports':
            reports = CivicReport.query.filter_by(reporter_id=user.id).order_by(CivicReport.created_at.desc()).limit(8).all()
            if not reports:
                return "You haven't submitted any civic reports."
            return "\n".join(f"[ID:{r.id}] {r.title} [{r.status}] {r.severity}" for r in reports)

        elif tool_name == 'delete_civic_report':
            report = CivicReport.query.get(int(tool_input['report_id']))
            if not report:
                return "Report not found."
            if report.reporter_id != user.id:
                return "You can only delete your own reports."
            db.session.delete(report)
            db.session.commit()
            return f'Report "{report.title}" deleted.'

        elif tool_name == 'upvote_civic_report':
            report = CivicReport.query.get(int(tool_input['report_id']))
            if not report:
                return "Report not found."
            if CivicUpvote.query.filter_by(user_id=user.id, report_id=report.id).first():
                return "You've already upvoted this report."
            db.session.add(CivicUpvote(user_id=user.id, report_id=report.id))
            report.upvotes += 1
            db.session.commit()
            return f'Upvoted "{report.title}". Now has {report.upvotes} upvote(s).'

        # ── Runner ─────────────────────────────────────────────────────────────
        elif tool_name == 'toggle_runner_status':
            active = bool(tool_input.get('active', False))
            user.is_runner = True
            user.runner_active = active
            db.session.commit()
            from app.extensions import socketio
            socketio.emit('runner_status_changed', {'user_id': user.id, 'username': user.username, 'active': active})
            label = "ACTIVE — you're live!" if active else "OFFLINE"
            return f'Runner status: {label}'

        # ── Goals ──────────────────────────────────────────────────────────────
        elif tool_name == 'get_my_goals':
            goals = Goal.query.filter_by(user_id=user.id, is_completed=False).all()
            if not goals:
                return "You have no active goals."
            return "\n".join(f"[ID:{g.id}] {g.title} — {g.progress}% ({g.category})" for g in goals)

        elif tool_name == 'add_goal':
            target_date = None
            if tool_input.get('target_date'):
                try:
                    target_date = _parse_date(tool_input['target_date'])
                except ValueError as e:
                    return str(e)
            goal = Goal(user_id=user.id, title=tool_input['title'],
                        description=tool_input.get('description', ''),
                        category=tool_input.get('category', 'Personal'),
                        target_date=target_date)
            db.session.add(goal)
            db.session.commit()
            due = f", due {target_date.strftime('%d %b %Y')}" if target_date else ""
            return f'Goal added: "{goal.title}" ({goal.category}{due}). (ID:{goal.id})'

        elif tool_name == 'add_milestone':
            goal = Goal.query.filter_by(id=int(tool_input['goal_id']), user_id=user.id).first()
            if not goal:
                return "Goal not found."
            m = Milestone(goal_id=goal.id, title=tool_input['title'])
            db.session.add(m)
            db.session.commit()
            goal.recalculate_progress()
            db.session.commit()
            return f'Milestone "{m.title}" added to "{goal.title}".'

        elif tool_name == 'complete_goal':
            goal = Goal.query.filter_by(id=int(tool_input['goal_id']), user_id=user.id).first()
            if not goal:
                return "Goal not found."
            goal.is_completed = True
            goal.progress = 100
            for m in goal.milestones:
                m.is_completed = True
            user.reputation += 10
            db.session.commit()
            return f'Goal "{goal.title}" completed! +10 reputation. Sharp!'

        elif tool_name == 'delete_goal':
            goal = Goal.query.filter_by(id=int(tool_input['goal_id']), user_id=user.id).first()
            if not goal:
                return "Goal not found."
            db.session.delete(goal)
            db.session.commit()
            return f'Goal "{goal.title}" deleted.'

        # ── Network ────────────────────────────────────────────────────────────
        elif tool_name == 'get_my_contacts':
            contacts = NetworkContact.query.filter_by(user_id=user.id).order_by(NetworkContact.name).all()
            if not contacts:
                return "Your network is empty. Add contacts with add_contact."
            return "\n".join(
                f"[ID:{c.id}] {c.name}" + (f" — {c.role}" if c.role else "") + (f" | {c.phone}" if c.phone else "")
                for c in contacts
            )

        elif tool_name == 'add_contact':
            c = NetworkContact(
                user_id=user.id,
                name=tool_input['name'],
                role=tool_input.get('role') or None,
                phone=tool_input.get('phone') or None,
                email=tool_input.get('email') or None,
                notes=tool_input.get('notes') or None,
            )
            db.session.add(c)
            db.session.commit()
            log_action('contact_added', f'{user.username} added contact "{c.name}"', user.id)
            return f'Contact "{c.name}" added to your network. (ID:{c.id})'

        elif tool_name == 'delete_contact':
            c = NetworkContact.query.filter_by(id=int(tool_input['contact_id']), user_id=user.id).first()
            if not c:
                return "Contact not found."
            db.session.delete(c)
            db.session.commit()
            return f'Contact "{c.name}" and their reminders removed.'

        elif tool_name == 'get_my_reminders':
            alerts = (NetworkAlert.query
                      .filter_by(user_id=user.id, is_completed=False)
                      .filter(NetworkAlert.alert_date >= datetime.utcnow())
                      .order_by(NetworkAlert.alert_date).limit(10).all())
            if not alerts:
                return "No upcoming reminders."
            return "\n".join(
                f"[ID:{a.id}] {a.alert_date.strftime('%d %b')} — {a.alert_type}: {a.title} (@{a.contact.name})"
                for a in alerts
            )

        elif tool_name == 'add_reminder':
            contact = NetworkContact.query.filter_by(
                id=int(tool_input['contact_id']), user_id=user.id).first()
            if not contact:
                return "Contact not found. Use get_my_contacts to find the correct ID."
            try:
                alert_date = _parse_date(tool_input['alert_date'])
            except ValueError as e:
                return str(e)
            alert = NetworkAlert(
                user_id=user.id,
                contact_id=contact.id,
                title=tool_input['title'],
                description=tool_input.get('description') or None,
                alert_type=tool_input.get('alert_type', 'Follow-up'),
                alert_date=alert_date,
            )
            db.session.add(alert)
            db.session.commit()
            return f'Reminder set: {alert.alert_type} "{alert.title}" with {contact.name} on {alert_date.strftime("%d %b %Y")}. (ID:{alert.id})'

        elif tool_name == 'complete_reminder':
            a = NetworkAlert.query.filter_by(id=int(tool_input['alert_id']), user_id=user.id).first()
            if not a:
                return "Reminder not found."
            a.is_completed = True
            db.session.commit()
            return f'Reminder "{a.title}" marked done.'

        elif tool_name == 'delete_reminder':
            a = NetworkAlert.query.filter_by(id=int(tool_input['alert_id']), user_id=user.id).first()
            if not a:
                return "Reminder not found."
            db.session.delete(a)
            db.session.commit()
            return f'Reminder "{a.title}" deleted.'

        else:
            return f"I don't have a tool called '{tool_name}' yet."

    except Exception as e:
        return f'Something went wrong with {tool_name}: {str(e)}'


# ── Bounty photo verification ──────────────────────────────────────────────────

def verify_bounty_photo(description: str, photo_path: str) -> dict:
    """
    Use Gemini vision to check if the proof photo matches the bounty description.
    Returns {'match': bool, 'confidence': str, 'reason': str}
    """
    api_key = current_app.config.get('GEMINI_API_KEY', '')
    if not api_key or api_key.startswith('your-'):
        return {'match': None, 'confidence': 'unknown', 'reason': 'AI not configured.'}

    try:
        import mimetypes
        mime = mimetypes.guess_type(photo_path)[0] or 'image/jpeg'
        with open(photo_path, 'rb') as f:
            image_bytes = f.read()

        client = genai.Client(api_key=api_key)
        prompt = (
            f'You are verifying a lost-item bounty claim.\n\n'
            f'Original lost item description: "{description}"\n\n'
            f'A finder has submitted the photo above as proof they found it.\n'
            f'Does the photo plausibly match the description?\n\n'
            f'Reply with ONLY a JSON object, no other text:\n'
            f'{{"match": true_or_false, "confidence": "high|medium|low", '
            f'"reason": "one sentence explanation"}}'
        )
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, image_part],
        )
        import json, re
        raw = response.text.strip()
        # strip markdown code fences if present
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        result = json.loads(raw)
        return {
            'match':      bool(result.get('match')),
            'confidence': result.get('confidence', 'medium'),
            'reason':     result.get('reason', ''),
        }
    except Exception as e:
        return {'match': None, 'confidence': 'unknown', 'reason': f'Verification error: {e}'}


# ── Friendly labels for action pills ──────────────────────────────────────────

_TOOL_LABELS = {
    'post_market_item':    'Item listed',
    'delete_market_item':  'Listing removed',
    'post_runner_job':     'Job posted',
    'claim_job':           'Job claimed',
    'cancel_job':          'Job cancelled',
    'post_bounty':         'Bounty posted',
    'delete_bounty':       'Bounty removed',
    'post_civic_report':   'Report submitted',
    'delete_civic_report': 'Report deleted',
    'upvote_civic_report': 'Report upvoted',
    'toggle_runner_status':'Runner status updated',
    'add_goal':            'Goal added',
    'complete_goal':       'Goal completed',
    'delete_goal':         'Goal deleted',
    'add_milestone':       'Milestone added',
    'add_contact':         'Contact added',
    'delete_contact':      'Contact removed',
    'add_reminder':        'Reminder set',
    'complete_reminder':   'Reminder done',
    'delete_reminder':     'Reminder deleted',
}


# ── Chat entry point ───────────────────────────────────────────────────────────

def chat(user, message: str, history: list) -> tuple:
    api_key = current_app.config.get('GEMINI_API_KEY', '')
    if not api_key or api_key.startswith('your-'):
        return ("AI not configured — paste your Gemini API key into GEMINI_API_KEY in .env", [])

    client = genai.Client(api_key=api_key)

    gemini_history = []
    for h in history[-14:]:
        role = 'user' if h.role == 'user' else 'model'
        gemini_history.append(types.Content(role=role, parts=[types.Part.from_text(text=h.content)]))

    chat_session = client.chats.create(
        model='gemini-2.5-flash',
        history=gemini_history,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOLS,
        ),
    )

    response = chat_session.send_message(message)

    if response.function_calls:
        actions_taken = []
        fn_response_parts = []
        for fn in response.function_calls:
            args = {k: v for k, v in fn.args.items()} if fn.args else {}
            result = execute_tool(fn.name, args, user)
            actions_taken.append({
                'tool':  fn.name,
                'label': _TOOL_LABELS.get(fn.name, fn.name),
            })
            fn_response_parts.append(
                types.Part.from_function_response(name=fn.name, response={'result': result})
            )
        follow = chat_session.send_message(fn_response_parts)
        return (follow.text or 'Done.', actions_taken)

    return (response.text or 'Done.', [])
