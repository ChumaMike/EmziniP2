from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.extensions import db
from app.models import Suggestion

about_bp = Blueprint('about', __name__)


@about_bp.route('/about', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        name    = request.form.get('name', '').strip()
        email   = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        if not message:
            flash('Please write a suggestion before submitting.', 'danger')
        else:
            db.session.add(Suggestion(name=name or 'Anonymous', email=email, message=message))
            db.session.commit()
            flash('Thanks for your suggestion! We read every one.', 'success')
        return redirect(url_for('about.index') + '#suggest')
    return render_template('about.html')
