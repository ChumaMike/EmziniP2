from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort)
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
from app.extensions import db, socketio
from app.models import (CommunityPost, Conversation, ConversationMessage,
                        User, RunnerJob, MarketItem)
from app.services.logger_service import log_action

messages_bp = Blueprint('messages', __name__)

CHANNELS = ('community', 'runners', 'providers')


# ── Hub ────────────────────────────────────────────────────────────────────────

@messages_bp.route('/messages')
@login_required
def index():
    tab = request.args.get('tab', 'community')
    if tab not in CHANNELS and tab != 'chats':
        tab = 'community'

    posts = []
    if tab in CHANNELS:
        posts = (CommunityPost.query
                 .filter_by(channel=tab)
                 .order_by(CommunityPost.created_at.desc())
                 .limit(60).all())

    # User's private conversations
    convs = (Conversation.query
             .filter(or_(
                 Conversation.initiator_id == current_user.id,
                 Conversation.recipient_id == current_user.id,
             ))
             .order_by(Conversation.updated_at.desc())
             .all())

    # Unread count per conversation
    unread_total = sum(
        ConversationMessage.query
        .filter_by(conversation_id=c.id, is_read=False)
        .filter(ConversationMessage.sender_id != current_user.id)
        .count()
        for c in convs
    )

    return render_template('messages/index.html',
                           tab=tab,
                           posts=posts,
                           convs=convs,
                           unread_total=unread_total,
                           channels=CHANNELS)


# ── Community Posts ─────────────────────────────────────────────────────────────

@messages_bp.route('/messages/post', methods=['POST'])
@login_required
def post():
    channel = request.form.get('channel', 'community')
    content = request.form.get('content', '').strip()
    if channel not in CHANNELS:
        abort(400)
    if not content:
        flash('Message cannot be empty.', 'danger')
        return redirect(url_for('messages.index', tab=channel))

    # Gate runners channel to approved runners only
    if channel == 'runners':
        if not (current_user.is_runner or
                (current_user.runner_profile and
                 current_user.runner_profile.status == 'approved')):
            flash('Only registered runners can post in the Runners channel.', 'danger')
            return redirect(url_for('messages.index', tab='runners'))

    cp = CommunityPost(user_id=current_user.id, channel=channel, content=content)
    db.session.add(cp)
    db.session.commit()
    socketio.emit(f'community_{channel}', {
        'username': current_user.username,
        'content': content,
        'time': cp.created_at.strftime('%H:%M'),
    })
    return redirect(url_for('messages.index', tab=channel))


# ── Private Conversations ───────────────────────────────────────────────────────

def _find_or_create_conv(other_user_id, context_type=None, context_id=None):
    """Find existing 1-to-1 conversation (with optional context) or create one."""
    other_id = other_user_id
    me = current_user.id
    conv = Conversation.query.filter(
        or_(
            and_(Conversation.initiator_id == me,  Conversation.recipient_id == other_id),
            and_(Conversation.initiator_id == other_id, Conversation.recipient_id == me),
        ),
        Conversation.context_type == context_type,
        Conversation.context_id == context_id,
    ).first()
    if not conv:
        conv = Conversation(
            initiator_id=me,
            recipient_id=other_id,
            context_type=context_type,
            context_id=context_id,
        )
        db.session.add(conv)
        db.session.commit()
    return conv


@messages_bp.route('/messages/start', methods=['POST'])
@login_required
def start_conversation():
    """Start or open a conversation, optionally with item/job context."""
    other_id     = request.form.get('other_user_id', type=int)
    context_type = request.form.get('context_type') or None
    context_id   = request.form.get('context_id', type=int) or None

    if not other_id or other_id == current_user.id:
        flash('Invalid recipient.', 'danger')
        return redirect(url_for('messages.index', tab='chats'))

    other = User.query.get_or_404(other_id)
    conv  = _find_or_create_conv(other_id, context_type, context_id)
    return redirect(url_for('messages.conversation', conv_id=conv.id))


@messages_bp.route('/messages/conversation/<int:conv_id>')
@login_required
def conversation(conv_id):
    conv = Conversation.query.get_or_404(conv_id)
    if current_user.id not in (conv.initiator_id, conv.recipient_id):
        abort(403)

    # Mark all unread messages as read
    (ConversationMessage.query
     .filter_by(conversation_id=conv_id, is_read=False)
     .filter(ConversationMessage.sender_id != current_user.id)
     .update({'is_read': True}))
    db.session.commit()

    other = conv.other_user(current_user.id)

    # Resolve context label
    context_label = None
    if conv.context_type == 'item':
        item = MarketItem.query.get(conv.context_id)
        if item:
            context_label = f'Re: {item.title}'
    elif conv.context_type == 'job':
        job = RunnerJob.query.get(conv.context_id)
        if job:
            context_label = f'Job: {job.title}'

    # All conversations for sidebar
    convs = (Conversation.query
             .filter(or_(
                 Conversation.initiator_id == current_user.id,
                 Conversation.recipient_id == current_user.id,
             ))
             .order_by(Conversation.updated_at.desc())
             .all())

    return render_template('messages/conversation.html',
                           conv=conv,
                           other=other,
                           context_label=context_label,
                           convs=convs)


@messages_bp.route('/messages/conversation/<int:conv_id>/send', methods=['POST'])
@login_required
def send_in_conversation(conv_id):
    conv = Conversation.query.get_or_404(conv_id)
    if current_user.id not in (conv.initiator_id, conv.recipient_id):
        abort(403)

    content = request.form.get('content', '').strip()
    if not content:
        return '', 204

    msg = ConversationMessage(
        conversation_id=conv_id,
        sender_id=current_user.id,
        content=content,
    )
    db.session.add(msg)
    conv.updated_at = db.func.now()
    db.session.commit()

    other_id = conv.recipient_id if conv.initiator_id == current_user.id else conv.initiator_id
    socketio.emit(f'conv_{conv_id}', {
        'sender': current_user.username,
        'sender_id': current_user.id,
        'content': content,
        'time': msg.created_at.strftime('%H:%M'),
    })

    return render_template('messages/_conv_message.html', msg=msg)
