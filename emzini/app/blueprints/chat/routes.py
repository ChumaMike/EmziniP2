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
    response = ai_service.chat(current_user, message, history[:-1])

    ai_msg = _save('assistant', response)

    return f'''
<div class="flex gap-3 flex-row-reverse" id="msg-user-{user_msg.id}">
  <div class="w-8 h-8 bg-zinc-700 rounded-lg flex-shrink-0 flex items-center justify-center text-xs text-white font-bold font-mono">
    {current_user.username[:2].upper()}
  </div>
  <div class="bg-zinc-800 border border-zinc-700 p-3 rounded-lg rounded-tr-none max-w-[85%] text-white text-sm">
    {_e(message)}
  </div>
</div>
<div class="flex gap-3" id="msg-ai-{ai_msg.id}">
  <div class="w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center text-xs text-white font-bold font-mono"
       style="background:var(--teal);">EM</div>
  <div class="bg-zinc-900 border border-zinc-800 p-3 rounded-lg rounded-tl-none max-w-[85%] text-zinc-300 text-sm whitespace-pre-wrap">
    {_e(response)}
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
