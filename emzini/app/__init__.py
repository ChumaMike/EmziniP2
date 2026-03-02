import os
from flask import Flask
from dotenv import load_dotenv
from app.extensions import db, login_manager, socketio

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
    db_url = os.getenv('DATABASE_URL', 'sqlite:///emzini.db')
    # Railway provides postgres:// but SQLAlchemy requires postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['GEMINI_API_KEY'] = os.getenv('GEMINI_API_KEY', '')
    app.config['ADMIN_USERNAME'] = os.getenv('ADMIN_USERNAME', 'admin')
    app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8 MB upload limit
    app.config['MAIL_SERVER']   = os.getenv('MAIL_SERVER', '')
    app.config['MAIL_PORT']     = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
    app.config['MAIL_FROM']     = os.getenv('MAIL_FROM', os.getenv('MAIL_USERNAME', ''))

    # Store uploads inside instance/ so they share the persistent volume
    upload_dir = os.path.join(app.instance_path, 'uploads', 'market')
    os.makedirs(upload_dir, exist_ok=True)
    app.config['MARKET_UPLOAD_DIR'] = upload_dir

    bounty_upload_dir = os.path.join(app.instance_path, 'uploads', 'bounties')
    os.makedirs(bounty_upload_dir, exist_ok=True)
    app.config['BOUNTY_UPLOAD_DIR'] = bounty_upload_dir

    bounty_proof_dir = os.path.join(app.instance_path, 'uploads', 'bounty_proofs')
    os.makedirs(bounty_proof_dir, exist_ok=True)
    app.config['BOUNTY_PROOF_DIR'] = bounty_proof_dir

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, async_mode='eventlet', cors_allowed_origins='*')

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_unread():
        from flask_login import current_user
        if current_user.is_authenticated:
            from app.models import Conversation, ConversationMessage, Notification
            from sqlalchemy import or_
            msg_count = ConversationMessage.query.join(Conversation).filter(
                or_(Conversation.initiator_id == current_user.id,
                    Conversation.recipient_id == current_user.id),
                ConversationMessage.sender_id != current_user.id,
                ConversationMessage.is_read == False
            ).count()
            notif_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            return {'unread_msg_count': msg_count, 'unread_notif_count': notif_count}
        return {'unread_msg_count': 0, 'unread_notif_count': 0}

    # Register blueprints
    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.dashboard.routes import dashboard_bp
    from app.blueprints.marketplace.routes import marketplace_bp
    from app.blueprints.jobs.routes import jobs_bp
    from app.blueprints.bounties.routes import bounties_bp
    from app.blueprints.civic.routes import civic_bp
    from app.blueprints.wallet.routes import wallet_bp
    from app.blueprints.chat.routes import chat_bp
    from app.blueprints.admin.routes import admin_bp
    from app.blueprints.profile.routes import profile_bp
    from app.blueprints.goals.routes import goals_bp
    from app.blueprints.network.routes import network_bp
    from app.blueprints.docs.routes import docs_bp
    from app.blueprints.runner.routes import runner_bp
    from app.blueprints.messages.routes import messages_bp
    from app.blueprints.about.routes import about_bp
    from app.blueprints.notifications.routes import notifications_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(bounties_bp)
    app.register_blueprint(civic_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(runner_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(notifications_bp)

    with app.app_context():
        db.create_all()
        _migrate(db)
        _seed_admin(app)

    return app


def _migrate(db):
    """Add any missing columns to existing tables (poor-man's migration)."""
    _add_col = lambda conn, table, col, typedef: (
        conn.execute(db.text(f'ALTER TABLE {table} ADD COLUMN {col} {typedef}'))
        if col not in {r[1] for r in conn.execute(db.text(f'PRAGMA table_info({table})')).fetchall()}
        else None
    )
    with db.engine.connect() as conn:
        _add_col(conn, 'market_items',  'photo_filename',   'VARCHAR(260)')
        _add_col(conn, 'users',         'chat_session_id',  'VARCHAR(36)')
        _add_col(conn, 'chat_messages', 'chat_session_id',  'VARCHAR(36)')
        _add_col(conn, 'market_items',    'stock_qty',        'INTEGER DEFAULT 1')
        _add_col(conn, 'market_items',    'allows_delivery',  'BOOLEAN DEFAULT 1')
        _add_col(conn, 'runner_jobs',     'item_id',          'INTEGER')
        _add_col(conn, 'runner_jobs',     'delivery_address', 'VARCHAR(300)')
        _add_col(conn, 'runner_jobs',     'job_type',         'VARCHAR(20) DEFAULT "general"')
        _add_col(conn, 'runner_jobs',     'payment_method',   'VARCHAR(20) DEFAULT "wallet"')
        _add_col(conn, 'direct_messages', 'recipient_id',     'INTEGER')
        _add_col(conn, 'bounties', 'proof_photo',    'VARCHAR(500)')
        _add_col(conn, 'bounties', 'ai_verified',    'BOOLEAN')
        _add_col(conn, 'bounties', 'ai_verdict_msg', 'TEXT')
        _add_col(conn, 'users', 'rep_personal', 'INTEGER DEFAULT 0')
        _add_col(conn, 'users', 'rep_runner',   'INTEGER DEFAULT 0')
        _add_col(conn, 'users', 'rep_provider', 'INTEGER DEFAULT 0')
        _add_col(conn, 'users', 'rep_civic',    'INTEGER DEFAULT 0')
        _add_col(conn, 'users', 'real_balance', 'REAL DEFAULT 0.0')
        _add_col(conn, 'users', 'cash_float',   'REAL DEFAULT 0.0')
        # notifications table is created by db.create_all(); no extra columns needed
        conn.commit()


def _seed_admin(app):
    from app.models import User
    from app.extensions import db

    admin_username = app.config['ADMIN_USERNAME']
    if not User.query.filter_by(username=admin_username).first():
        admin = User(
            username=admin_username,
            email=f'{admin_username}@emzini.local',
            is_admin=True,
            wallet_balance=1000.0,
            is_runner=True,
        )
        admin.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(admin)
        db.session.commit()
