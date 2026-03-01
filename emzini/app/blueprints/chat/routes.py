from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import ChatMessage
from app.services import ai_service
from app.services.logger_service import log_action

chat_bp = Blueprint('chat', __name__)


def _session_messages(limit=None):
    """Return chat messages for the current login session only."""
    sid = current_user.chat_session_id
    q = (ChatMessage.query
         .filter_by(user_id=current_user.id, chat_session_id=sid)
         .order_by(ChatMessage.created_at.asc()))
    return q.limit(limit).all() if limit else q.all()


def _save(role, content):
    msg = ChatMessage(
        user_id=current_user.id,
        role=role,
        content=content,
        chat_session_id=current_user.chat_session_id,
    )
    db.session.add(msg)
    db.session.commit()
    return msg


@chat_bp.route('/chat')
@login_required
def index():
    return render_template('chat/index.html', history=_session_messages())


@chat_bp.route('/chat/send', methods=['POST'])
@login_required
def send():
    message = request.form.get('message', '').strip()
    if not message:
        return '<div class="text-zinc-600 text-xs font-mono p-2">Empty message.</div>'

    user_msg = _save('user', message)
    log_action('ai_prompt', f'User sent prompt: {message[:80]}', current_user.id, {'length': len(message)})

    # Full session history (excluding the message we just saved) for context
    history = _session_messages()
    response, actions = ai_service.chat(current_user, message, history[:-1])

    ai_msg = _save('assistant', response)

    actions_html = ''
    if actions:
        pills = ''.join(
            f'<span class="font-mono text-[10px] bg-teal-950 border border-teal-800 '
            f'text-teal-400 px-2 py-0.5 rounded-full">&#10003; {_e(a["label"])}</span>'
            for a in actions
        )
        actions_html = f'<div class="flex gap-1.5 flex-wrap mt-2">{pills}</div>'

    return f'''
<div class="flex gap-3 flex-row-reverse items-end" id="msg-user-{user_msg.id}">
  <div class="w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center text-xs font-bold font-mono"
       style="background:rgba(13,148,136,0.12);border:1px solid rgba(13,148,136,0.2);color:var(--teal-lt);">
    {current_user.username[:2].upper()}
  </div>
  <div class="text-sm text-white leading-relaxed px-4 py-3 rounded-2xl rounded-br-sm max-w-[80%]"
       style="background:var(--teal);">
    {_e(message)}
  </div>
</div>
<div class="flex gap-3 items-end" id="msg-ai-{ai_msg.id}">
  <div class="w-8 h-8 rounded-xl flex-shrink-0 flex items-center justify-center"
       style="background:linear-gradient(135deg,var(--teal),rgba(99,102,241,0.7));">
    <i class="fas fa-robot text-white text-[11px]"></i>
  </div>
  <div class="text-sm text-zinc-300 leading-relaxed px-4 py-3 rounded-2xl rounded-bl-sm max-w-[80%] whitespace-pre-wrap"
       style="background:var(--card);border:1px solid var(--border-2);">
    {_e(response)}{actions_html}
  </div>
</div>
'''


def _e(text: str) -> str:
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#x27;'))
