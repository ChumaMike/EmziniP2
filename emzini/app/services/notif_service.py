from app.extensions import db, socketio


def notify(user_id, notif_type, title, body=None, link=None):
    """Create a persistent notification and push a real-time event to that user."""
    from app.models import Notification
    n = Notification(
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        body=body,
        link=link,
    )
    db.session.add(n)
    db.session.commit()
    socketio.emit(f'notif_{user_id}', {
        'title': title,
        'body': body or '',
        'link': link or '',
        'type': notif_type,
    })
