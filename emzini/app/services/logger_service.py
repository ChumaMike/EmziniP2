import json
from app.extensions import db
from app.models import ActionLog


def log_action(action_type: str, description: str, user_id: int = None, metadata: dict = None):
    entry = ActionLog(
        user_id=user_id,
        action_type=action_type,
        description=description,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.session.add(entry)
    db.session.commit()
