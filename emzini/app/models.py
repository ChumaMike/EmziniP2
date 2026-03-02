from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_runner = db.Column(db.Boolean, default=False)
    runner_active = db.Column(db.Boolean, default=False)
    reputation = db.Column(db.Integer, default=0)
    rep_personal = db.Column(db.Integer, default=0)   # goals, app engagement
    rep_runner   = db.Column(db.Integer, default=0)   # completed runner jobs
    rep_provider = db.Column(db.Integer, default=0)   # items/services sold
    rep_civic    = db.Column(db.Integer, default=0)   # civic reports submitted
    wallet_balance = db.Column(db.Float, default=0.0)
    real_balance   = db.Column(db.Float, default=0.0)  # admin-verified ZAR
    cash_float     = db.Column(db.Float, default=0.0)  # cash held by runner
    is_admin = db.Column(db.Boolean, default=False)
    chat_session_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class MarketItem(db.Model):
    __tablename__ = 'market_items'
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), default='general')
    status = db.Column(db.String(20), default='available')  # available, sold
    photo_filename = db.Column(db.String(260), nullable=True)
    stock_qty = db.Column(db.Integer, default=1)
    allows_delivery = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    seller = db.relationship('User', backref='market_items', foreign_keys=[seller_id])
    dms = db.relationship('DirectMessage', backref='item', cascade='all, delete-orphan')
    restock_requests = db.relationship('RestockRequest', backref='item', cascade='all, delete-orphan')


class RunnerJob(db.Model):
    __tablename__ = 'runner_jobs'
    id = db.Column(db.Integer, primary_key=True)
    poster_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    runner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    reward = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='open')  # open, claimed, completed, cancelled
    escrow_locked = db.Column(db.Boolean, default=False)
    item_id = db.Column(db.Integer, db.ForeignKey('market_items.id'), nullable=True)
    delivery_address = db.Column(db.String(300), nullable=True)
    job_type = db.Column(db.String(20), default='general')   # general | delivery
    payment_method = db.Column(db.String(20), default='wallet')  # wallet | cash | card
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    poster = db.relationship('User', backref='posted_jobs', foreign_keys=[poster_id])
    runner = db.relationship('User', backref='claimed_jobs', foreign_keys=[runner_id])
    negotiations = db.relationship('JobNegotiation', backref='job', cascade='all, delete-orphan')


class Bounty(db.Model):
    __tablename__ = 'bounties'
    id = db.Column(db.Integer, primary_key=True)
    poster_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    claimer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    reward = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='open')  # open, claimed, verified, closed
    photo_url = db.Column(db.String(500), nullable=True)
    proof_photo = db.Column(db.String(500), nullable=True)   # finder's proof image filename
    ai_verified = db.Column(db.Boolean, nullable=True)       # None=unchecked True=match False=no match
    ai_verdict_msg = db.Column(db.Text, nullable=True)       # AI explanation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    poster = db.relationship('User', backref='posted_bounties', foreign_keys=[poster_id])
    claimer = db.relationship('User', backref='claimed_bounties', foreign_keys=[claimer_id])


class CivicReport(db.Model):
    __tablename__ = 'civic_reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='other')  # pothole, pipe, electricity, other
    severity = db.Column(db.String(20), default='medium')  # low, medium, high, critical
    upvotes = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='open')  # open, in_progress, resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reporter = db.relationship('User', backref='civic_reports')
    upvote_records = db.relationship('CivicUpvote', backref='report', cascade='all, delete-orphan')


class CivicUpvote(db.Model):
    __tablename__ = 'civic_upvotes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey('civic_reports.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'report_id'),)


class WalletTx(db.Model):
    __tablename__ = 'wallet_txs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    tx_type = db.Column(db.String(30), nullable=False)  # credit, debit, escrow_lock, escrow_release
    reference = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='transactions')


class ActionLog(db.Model):
    __tablename__ = 'action_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action_type = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='action_logs')


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # user, assistant
    content = db.Column(db.Text, nullable=False)
    chat_session_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='chat_messages')


# ── Goals ──────────────────────────────────────────────────────────────────────

class Goal(db.Model):
    __tablename__ = 'goals'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, nullable=True)
    category     = db.Column(db.String(50), default='Personal')
    target_date  = db.Column(db.DateTime, nullable=True)
    progress     = db.Column(db.Integer, default=0)   # 0–100
    is_completed = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user       = db.relationship('User', backref='goals')
    milestones = db.relationship('Milestone', backref='goal',
                                 cascade='all, delete-orphan',
                                 order_by='Milestone.created_at')

    def recalculate_progress(self):
        total = len(self.milestones)
        if total == 0:
            return
        done = sum(1 for m in self.milestones if m.is_completed)
        self.progress = int((done / total) * 100)
        if self.progress == 100:
            self.is_completed = True


class Milestone(db.Model):
    __tablename__ = 'milestones'
    id           = db.Column(db.Integer, primary_key=True)
    goal_id      = db.Column(db.Integer, db.ForeignKey('goals.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)


# ── Network / Contacts ─────────────────────────────────────────────────────────

class NetworkContact(db.Model):
    __tablename__ = 'network_contacts'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name       = db.Column(db.String(200), nullable=False)
    role       = db.Column(db.String(100), nullable=True)
    phone      = db.Column(db.String(30),  nullable=True)
    email      = db.Column(db.String(120), nullable=True)
    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user   = db.relationship('User', backref='contacts')
    alerts = db.relationship('NetworkAlert', backref='contact',
                             cascade='all, delete-orphan',
                             order_by='NetworkAlert.alert_date')


class NetworkAlert(db.Model):
    __tablename__ = 'network_alerts'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contact_id   = db.Column(db.Integer, db.ForeignKey('network_contacts.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, nullable=True)
    alert_type   = db.Column(db.String(50), default='Follow-up')  # Call, Email, Meeting, Follow-up
    alert_date   = db.Column(db.DateTime, nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='network_alerts')


# ── Documents ───────────────────────────────────────────────────────────────────

class Document(db.Model):
    __tablename__ = 'documents'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title        = db.Column(db.String(120), nullable=False)
    doc_type     = db.Column(db.String(30), nullable=False)  # cv, cover_letter, email, letter
    content_json = db.Column(db.Text, default='{}')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='documents')


# ── Marketplace Enhancements ────────────────────────────────────────────────────

class DirectMessage(db.Model):
    __tablename__ = 'direct_messages'
    id           = db.Column(db.Integer, primary_key=True)
    item_id      = db.Column(db.Integer, db.ForeignKey('market_items.id'), nullable=False)
    sender_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    content      = db.Column(db.Text, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    sender    = db.relationship('User', backref='sent_dms',     foreign_keys=[sender_id])
    recipient = db.relationship('User', backref='received_dms', foreign_keys=[recipient_id])


class RestockRequest(db.Model):
    __tablename__ = 'restock_requests'
    id         = db.Column(db.Integer, primary_key=True)
    item_id    = db.Column(db.Integer, db.ForeignKey('market_items.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notified   = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='restock_requests', foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint('item_id', 'user_id'),)


# ── Runner System ───────────────────────────────────────────────────────────────

class RunnerProfile(db.Model):
    __tablename__ = 'runner_profiles'
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    full_name        = db.Column(db.String(200), nullable=False)
    phone            = db.Column(db.String(30), nullable=False)
    id_number        = db.Column(db.String(20), nullable=False)
    vehicle          = db.Column(db.String(20), default='foot')  # foot | bicycle | motorbike | car
    bio              = db.Column(db.Text, nullable=True)
    status           = db.Column(db.String(20), default='pending')  # pending | approved | rejected
    total_deliveries = db.Column(db.Integer, default=0)
    total_earned     = db.Column(db.Float, default=0.0)
    approved_at      = db.Column(db.DateTime, nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('runner_profile', uselist=False))


class JobNegotiation(db.Model):
    __tablename__ = 'job_negotiations'
    id               = db.Column(db.Integer, primary_key=True)
    job_id           = db.Column(db.Integer, db.ForeignKey('runner_jobs.id'), nullable=False)
    runner_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    proposed_reward  = db.Column(db.Float, nullable=False)
    message          = db.Column(db.Text, nullable=True)
    status           = db.Column(db.String(20), default='pending')  # pending | accepted | rejected
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    runner = db.relationship('User', backref='job_offers', foreign_keys=[runner_id])


# ── Messaging Hub ───────────────────────────────────────────────────────────────

class CommunityPost(db.Model):
    """Public posts in community channels (community / runners / providers)."""
    __tablename__ = 'community_posts'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    channel    = db.Column(db.String(20), nullable=False)  # community | runners | providers
    content    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='community_posts')


class Conversation(db.Model):
    """Private 1-to-1 conversation thread with optional context (item or job)."""
    __tablename__ = 'conversations'
    id           = db.Column(db.Integer, primary_key=True)
    initiator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    context_type = db.Column(db.String(20), nullable=True)   # item | job | None
    context_id   = db.Column(db.Integer, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    initiator = db.relationship('User', backref='initiated_conversations', foreign_keys=[initiator_id])
    recipient = db.relationship('User', backref='received_conversations',  foreign_keys=[recipient_id])
    messages  = db.relationship('ConversationMessage', backref='conversation',
                                cascade='all, delete-orphan',
                                order_by='ConversationMessage.created_at')

    def other_user(self, user_id):
        return self.recipient if self.initiator_id == user_id else self.initiator

    def last_message(self):
        return self.messages[-1] if self.messages else None


class ConversationMessage(db.Model):
    """A single message in a private Conversation."""
    __tablename__ = 'conversation_messages'
    id              = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    sender_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content         = db.Column(db.Text, nullable=False)
    is_read         = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', backref='conv_messages', foreign_keys=[sender_id])


# ── About / Suggestions ─────────────────────────────────────────────────────────

class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token      = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used       = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='reset_tokens')


class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notif_type = db.Column(db.String(40), nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    body       = db.Column(db.String(500), nullable=True)
    link       = db.Column(db.String(200), nullable=True)
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='notifications')


class Suggestion(db.Model):
    """User-submitted suggestions from the About page."""
    __tablename__ = 'suggestions'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), default='Anonymous')
    email      = db.Column(db.String(200), nullable=True)
    message    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
