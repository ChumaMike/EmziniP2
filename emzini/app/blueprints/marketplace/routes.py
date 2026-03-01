import os
import time
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db, socketio
from sqlalchemy import or_, and_
from app.models import MarketItem, User, RunnerJob, DirectMessage, RestockRequest, Conversation
from app.services.escrow_service import debit_wallet, credit_wallet, InsufficientFundsError
from app.services.logger_service import log_action

marketplace_bp = Blueprint('marketplace', __name__)

CATEGORIES = ['electronics', 'furniture', 'clothing', 'food', 'services', 'general']
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
DELIVERY_REWARD = 10.0
PLATFORM_FEE_PCT = 0.01


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _save_photo(file):
    if not file or not file.filename:
        return None
    if not _allowed(file.filename):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"market_{current_user.id}_{int(time.time())}.{ext}"
    filename = secure_filename(filename)
    file.save(os.path.join(current_app.config['MARKET_UPLOAD_DIR'], filename))
    return filename


def _delete_photo(filename):
    if filename:
        path = os.path.join(current_app.config['MARKET_UPLOAD_DIR'], filename)
        try:
            os.remove(path)
        except OSError:
            pass


@marketplace_bp.route('/market/photos/<filename>')
def serve_photo(filename):
    return send_from_directory(current_app.config['MARKET_UPLOAD_DIR'], filename)


@marketplace_bp.route('/market')
@login_required
def index():
    view     = request.args.get('view', 'items')   # items | tasks
    category = request.args.get('cat', '')

    if view == 'tasks':
        # Show open runner jobs (general + delivery)
        task_type = request.args.get('type', '')  # '' | general | delivery
        q = RunnerJob.query.filter_by(status='open')
        if task_type in ('general', 'delivery'):
            q = q.filter_by(job_type=task_type)
        tasks = q.order_by(RunnerJob.created_at.desc()).all()
        items = []
    else:
        view  = 'items'
        tasks = []
        q = MarketItem.query.filter_by(status='available')
        if category and category in CATEGORIES:
            q = q.filter_by(category=category)
        items = q.order_by(MarketItem.created_at.desc()).all()

    active_runners = User.query.filter_by(is_runner=True, runner_active=True).all()
    return render_template('marketplace/index.html',
                           items=items,
                           tasks=tasks,
                           view=view,
                           categories=CATEGORIES,
                           active_cat=category,
                           active_runners=active_runners)


@marketplace_bp.route('/market/<int:item_id>')
@login_required
def item_detail(item_id):
    item = MarketItem.query.get_or_404(item_id)
    active_runners = User.query.filter_by(is_runner=True, runner_active=True).all()
    user_restock   = RestockRequest.query.filter_by(item_id=item_id, user_id=current_user.id).first()

    # Private DMs: buyer sees thread with seller; seller sees list of buyer threads
    seller_id  = item.seller_id
    me         = current_user.id
    if me == seller_id:
        # Seller: get distinct buyers who have messaged on this item
        buyers = (db.session.query(User)
                  .join(DirectMessage, DirectMessage.sender_id == User.id)
                  .filter(DirectMessage.item_id == item_id,
                          DirectMessage.sender_id != seller_id)
                  .distinct().all())
        dms        = []
        chat_buyer = None
    else:
        buyers     = []
        chat_buyer = User.query.get(seller_id)
        dms = (DirectMessage.query
               .filter_by(item_id=item_id)
               .filter(or_(
                   and_(DirectMessage.sender_id == me,    DirectMessage.recipient_id == seller_id),
                   and_(DirectMessage.sender_id == seller_id, DirectMessage.recipient_id == me),
               ))
               .order_by(DirectMessage.created_at.asc()).all())

    return render_template('marketplace/item.html',
                           item=item,
                           active_runners=active_runners,
                           dms=dms,
                           buyers=buyers,
                           chat_buyer=chat_buyer,
                           user_restock=user_restock)


@marketplace_bp.route('/market/new', methods=['GET', 'POST'])
@login_required
def new_item():
    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        description  = request.form.get('description', '').strip()
        price_str    = request.form.get('price', '0')
        category     = request.form.get('category', 'general')
        stock_str    = request.form.get('stock_qty', '1')
        allows_del   = request.form.get('allows_delivery') == 'on'

        if not title or not description:
            flash('Title and description are required.', 'danger')
            return render_template('marketplace/new.html', categories=CATEGORIES)
        try:
            price = float(price_str)
            if price <= 0:
                raise ValueError
        except ValueError:
            flash('Enter a valid price.', 'danger')
            return render_template('marketplace/new.html', categories=CATEGORIES)
        try:
            stock_qty = int(stock_str)
            if stock_qty < 1:
                raise ValueError
        except ValueError:
            stock_qty = 1

        photo_filename = _save_photo(request.files.get('photo'))

        item = MarketItem(
            seller_id=current_user.id,
            title=title,
            description=description,
            price=price,
            category=category if category in CATEGORIES else 'general',
            photo_filename=photo_filename,
            stock_qty=stock_qty,
            allows_delivery=allows_del,
        )
        db.session.add(item)
        db.session.commit()
        log_action('market_item_posted', f'{current_user.username} listed "{title}" R{price:.2f}', current_user.id)
        flash(f'"{title}" listed for R{price:.2f}!', 'success')
        return redirect(url_for('marketplace.index'))

    return render_template('marketplace/new.html', categories=CATEGORIES)


@marketplace_bp.route('/market/<int:item_id>/buy', methods=['POST'])
@login_required
def buy_item(item_id):
    item = MarketItem.query.get_or_404(item_id)
    if item.status != 'available':
        flash('Item no longer available.', 'danger')
        return redirect(url_for('marketplace.item_detail', item_id=item_id))
    if item.seller_id == current_user.id:
        flash("You can't buy your own item.", 'danger')
        return redirect(url_for('marketplace.item_detail', item_id=item_id))
    if (item.stock_qty or 0) <= 0:
        flash('Item is out of stock.', 'danger')
        return redirect(url_for('marketplace.item_detail', item_id=item_id))

    payment_method   = request.form.get('payment_method', 'wallet')
    wants_delivery   = request.form.get('wants_delivery') == '1'
    delivery_address = request.form.get('delivery_address', '').strip()

    if payment_method not in ('wallet', 'cash', 'card'):
        payment_method = 'wallet'

    # Process payment
    if payment_method == 'wallet':
        try:
            debit_wallet(current_user.id, item.price, f'Purchase: {item.title}')
            credit_wallet(item.seller_id, item.price, f'Sale: {item.title}')
        except InsufficientFundsError as e:
            flash(str(e), 'danger')
            return redirect(url_for('marketplace.item_detail', item_id=item_id))
    else:
        # Cash/card: log as pending, no wallet change yet
        log_action('cash_order', f'{current_user.username} ordered "{item.title}" via {payment_method} — pending collection', current_user.id)

    # Decrement stock
    item.stock_qty = (item.stock_qty or 1) - 1
    if item.stock_qty <= 0:
        item.status = 'sold'
        # Mark all restock requesters as notified
        for rr in item.restock_requests:
            rr.notified = True

    db.session.commit()

    # Create delivery job if requested
    if wants_delivery and item.allows_delivery:
        addr = delivery_address or 'Not specified'
        job = RunnerJob(
            poster_id=current_user.id,
            title=f'Deliver: {item.title}',
            description=f'Pick up "{item.title}" from @{item.seller.username} and deliver to: {addr}',
            reward=DELIVERY_REWARD,
            escrow_locked=False,
            item_id=item.id,
            delivery_address=addr,
            job_type='delivery',
            payment_method=payment_method,
        )
        db.session.add(job)
        db.session.commit()
        socketio.emit('new_delivery_job', {
            'id': job.id,
            'title': job.title,
            'reward': job.reward,
            'poster': current_user.username,
        })

    log_action('market_purchase',
               f'{current_user.username} bought "{item.title}" for R{item.price:.2f} via {payment_method}',
               current_user.id)

    if wants_delivery and item.allows_delivery:
        flash(f'Bought "{item.title}"! Delivery job posted — R10 for the runner. Track it below.', 'success')
        return redirect(url_for('jobs.index'))

    flash(f'Bought "{item.title}" for R{item.price:.2f}!', 'success')
    return redirect(url_for('marketplace.item_detail', item_id=item_id))


@marketplace_bp.route('/market/<int:item_id>/messages')
@login_required
def item_messages(item_id):
    item = MarketItem.query.get_or_404(item_id)
    dms = DirectMessage.query.filter_by(item_id=item_id).order_by(DirectMessage.created_at.asc()).all()
    return render_template('marketplace/_dms.html', item=item, dms=dms)


@marketplace_bp.route('/market/<int:item_id>/messages/send', methods=['POST'])
@login_required
def send_message(item_id):
    item = MarketItem.query.get_or_404(item_id)
    content = request.form.get('content', '').strip()
    if not content:
        return '', 204

    # Private: buyer → seller or seller → specific buyer
    me        = current_user.id
    seller_id = item.seller_id
    if me == seller_id:
        # Seller replying to a specific buyer
        recipient_id = request.form.get('buyer_id', type=int) or None
    else:
        recipient_id = seller_id

    dm = DirectMessage(item_id=item_id, sender_id=me,
                       recipient_id=recipient_id, content=content)
    db.session.add(dm)
    db.session.commit()

    # Emit only to participants (room keyed by sorted user pair + item)
    pair_key = f'dm_{item_id}_{min(me, recipient_id or me)}_{max(me, recipient_id or me)}'
    socketio.emit(pair_key, {
        'sender':    current_user.username,
        'content':   content,
        'sender_id': me,
    })

    return render_template('marketplace/_dm_message.html', dm=dm, item=item)


@marketplace_bp.route('/market/<int:item_id>/restock', methods=['POST'])
@login_required
def restock_notify(item_id):
    item = MarketItem.query.get_or_404(item_id)
    existing = RestockRequest.query.filter_by(item_id=item_id, user_id=current_user.id).first()
    if existing:
        flash("You're already on the notify list.", 'info')
    else:
        rr = RestockRequest(item_id=item_id, user_id=current_user.id)
        db.session.add(rr)
        db.session.commit()
        flash("We'll notify you when this item is back in stock.", 'success')
    return redirect(url_for('marketplace.item_detail', item_id=item_id))


@marketplace_bp.route('/market/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    item = MarketItem.query.get_or_404(item_id)
    if item.seller_id != current_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('marketplace.item_detail', item_id=item_id))

    if request.method == 'POST':
        title       = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price_str   = request.form.get('price', '0')
        category    = request.form.get('category', item.category)
        stock_str   = request.form.get('stock_qty', '1')
        allows_del  = request.form.get('allows_delivery') == 'on'

        if not title or not description:
            flash('Title and description are required.', 'danger')
            return render_template('marketplace/edit.html', item=item, categories=CATEGORIES)
        try:
            price = float(price_str)
            if price <= 0:
                raise ValueError
        except ValueError:
            flash('Enter a valid price.', 'danger')
            return render_template('marketplace/edit.html', item=item, categories=CATEGORIES)
        try:
            stock_qty = int(stock_str)
            if stock_qty < 0:
                raise ValueError
        except ValueError:
            stock_qty = item.stock_qty or 1

        # Replace photo only if a new one was uploaded
        new_photo = request.files.get('photo')
        if new_photo and new_photo.filename:
            _delete_photo(item.photo_filename)
            item.photo_filename = _save_photo(new_photo)

        item.title          = title
        item.description    = description
        item.price          = price
        item.category       = category if category in CATEGORIES else item.category
        item.stock_qty      = stock_qty
        item.allows_delivery = allows_del
        if stock_qty > 0 and item.status == 'sold':
            item.status = 'available'

        db.session.commit()
        log_action('market_item_edited', f'{current_user.username} edited "{title}"', current_user.id)
        flash('Listing updated.', 'success')
        return redirect(url_for('marketplace.item_detail', item_id=item_id))

    return render_template('marketplace/edit.html', item=item, categories=CATEGORIES)


@marketplace_bp.route('/market/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_item(item_id):
    item = MarketItem.query.get_or_404(item_id)
    if item.seller_id != current_user.id and not current_user.is_admin:
        flash('Not authorized.', 'danger')
        return redirect(url_for('marketplace.index'))
    _delete_photo(item.photo_filename)
    db.session.delete(item)
    db.session.commit()
    flash('Listing removed.', 'success')
    return redirect(url_for('marketplace.index'))
