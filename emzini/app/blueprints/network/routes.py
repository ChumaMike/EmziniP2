from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from app.extensions import db
from app.models import NetworkContact, NetworkAlert
from app.services.logger_service import log_action

network_bp = Blueprint('network', __name__)

ALERT_TYPES = ['Call', 'Email', 'Meeting', 'Follow-up', 'Other']


@network_bp.route('/network')
@login_required
def index():
    contacts = NetworkContact.query.filter_by(user_id=current_user.id)\
                                   .order_by(NetworkContact.name).all()
    upcoming = NetworkAlert.query\
                           .filter_by(user_id=current_user.id, is_completed=False)\
                           .filter(NetworkAlert.alert_date >= datetime.utcnow())\
                           .order_by(NetworkAlert.alert_date).limit(20).all()
    return render_template('network/index.html',
                           contacts=contacts, upcoming=upcoming,
                           alert_types=ALERT_TYPES)


@network_bp.route('/network/add-contact', methods=['POST'])
@login_required
def add_contact():
    name  = request.form.get('name', '').strip()
    role  = request.form.get('role', '').strip()
    phone = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    notes = request.form.get('notes', '').strip()

    if not name:
        flash('Contact name is required.', 'danger')
        return redirect(url_for('network.index'))

    c = NetworkContact(user_id=current_user.id, name=name,
                       role=role or None, phone=phone or None,
                       email=email or None, notes=notes or None)
    db.session.add(c)
    db.session.commit()
    log_action('contact_added', f'{current_user.username} added contact "{name}"', current_user.id)
    flash(f'{name} added to your network.', 'success')
    return redirect(url_for('network.index'))


@network_bp.route('/network/edit-contact/<int:cid>', methods=['POST'])
@login_required
def edit_contact(cid):
    c = NetworkContact.query.filter_by(id=cid, user_id=current_user.id).first_or_404()
    c.name  = request.form.get('name', c.name).strip() or c.name
    c.role  = request.form.get('role', '').strip() or None
    c.phone = request.form.get('phone', '').strip() or None
    c.email = request.form.get('email', '').strip() or None
    c.notes = request.form.get('notes', '').strip() or None
    db.session.commit()
    flash('Contact updated.', 'success')
    return redirect(url_for('network.index'))


@network_bp.route('/network/delete-contact/<int:cid>', methods=['POST'])
@login_required
def delete_contact(cid):
    c = NetworkContact.query.filter_by(id=cid, user_id=current_user.id).first_or_404()
    db.session.delete(c)
    db.session.commit()
    flash(f'{c.name} removed from your network.', 'success')
    return redirect(url_for('network.index'))


@network_bp.route('/network/add-alert/<int:cid>', methods=['POST'])
@login_required
def add_alert(cid):
    NetworkContact.query.filter_by(id=cid, user_id=current_user.id).first_or_404()
    title      = request.form.get('title', '').strip()
    date_str   = request.form.get('alert_date', '').strip()
    alert_type = request.form.get('alert_type', 'Follow-up')
    description = request.form.get('description', '').strip()

    if not title or not date_str:
        flash('Title and date are required for an alert.', 'danger')
        return redirect(url_for('network.index'))

    try:
        alert_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        try:
            alert_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('network.index'))

    a = NetworkAlert(user_id=current_user.id, contact_id=cid,
                     title=title, description=description or None,
                     alert_type=alert_type if alert_type in ALERT_TYPES else 'Follow-up',
                     alert_date=alert_date)
    db.session.add(a)
    db.session.commit()
    flash(f'Alert set for {alert_date.strftime("%d %b %Y")}.', 'success')
    return redirect(url_for('network.index'))


@network_bp.route('/network/toggle-alert/<int:aid>', methods=['POST'])
@login_required
def toggle_alert(aid):
    a = NetworkAlert.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    a.is_completed = not a.is_completed
    db.session.commit()
    return redirect(url_for('network.index'))


@network_bp.route('/network/delete-alert/<int:aid>', methods=['POST'])
@login_required
def delete_alert(aid):
    a = NetworkAlert.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    db.session.delete(a)
    db.session.commit()
    flash('Alert removed.', 'success')
    return redirect(url_for('network.index'))
