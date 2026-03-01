import json
from datetime import datetime
from google import genai
from google.genai import types as genai_types
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Document
from app.services.logger_service import log_action

docs_bp = Blueprint('docs', __name__)

# ── Field schemas per document type ────────────────────────────────────────────

DOC_TYPES = {
    'cv': {
        'label': 'CV / Resume',
        'icon': 'fa-id-card',
        'fields': [
            {'name': 'full_name',   'label': 'Full Name',   'type': 'text',     'placeholder': 'Your full name'},
            {'name': 'email',       'label': 'Email',        'type': 'text',     'placeholder': 'you@email.com'},
            {'name': 'phone',       'label': 'Phone',        'type': 'text',     'placeholder': '+27 82 000 0000'},
            {'name': 'location',    'label': 'Location',     'type': 'text',     'placeholder': 'City, Country'},
            {'name': 'linkedin',    'label': 'LinkedIn',     'type': 'text',     'placeholder': 'linkedin.com/in/yourname'},
            {'name': 'summary',     'label': 'Professional Summary', 'type': 'textarea', 'rows': 4, 'placeholder': 'A brief overview of your career and skills...'},
            {'name': 'experience',  'label': 'Experience',   'type': 'textarea', 'rows': 6, 'placeholder': 'Job Title at Company (dates)\n• Responsibility or achievement\n• Another key achievement'},
            {'name': 'education',   'label': 'Education',    'type': 'textarea', 'rows': 4, 'placeholder': 'Degree — Institution (Year)\nRelevant coursework or honours'},
            {'name': 'skills',      'label': 'Skills',       'type': 'textarea', 'rows': 3, 'placeholder': 'Python, SQL, Project Management, etc.'},
        ],
    },
    'cover_letter': {
        'label': 'Cover Letter',
        'icon': 'fa-envelope-open-text',
        'fields': [
            {'name': 'your_name',        'label': 'Your Name',         'type': 'text',     'placeholder': 'Your full name'},
            {'name': 'your_email',       'label': 'Your Email',        'type': 'text',     'placeholder': 'you@email.com'},
            {'name': 'your_phone',       'label': 'Your Phone',        'type': 'text',     'placeholder': '+27 82 000 0000'},
            {'name': 'employer_name',    'label': 'Hiring Manager',    'type': 'text',     'placeholder': 'Ms Jane Smith'},
            {'name': 'employer_company', 'label': 'Company',           'type': 'text',     'placeholder': 'Acme Corp'},
            {'name': 'date',             'label': 'Date',              'type': 'text',     'placeholder': '1 March 2026'},
            {'name': 'subject',          'label': 'Subject / Position','type': 'text',     'placeholder': 'Application for Senior Developer Position'},
            {'name': 'opening',          'label': 'Opening Paragraph', 'type': 'textarea', 'rows': 3, 'placeholder': 'Express your enthusiasm and how you heard about the role...'},
            {'name': 'body',             'label': 'Body',              'type': 'textarea', 'rows': 6, 'placeholder': 'Highlight your relevant experience and why you are the right fit...'},
            {'name': 'closing',          'label': 'Closing Paragraph', 'type': 'textarea', 'rows': 3, 'placeholder': 'Thank them, express interest in an interview...'},
        ],
    },
    'email': {
        'label': 'Email',
        'icon': 'fa-envelope',
        'fields': [
            {'name': 'to',        'label': 'To',        'type': 'text',     'placeholder': 'recipient@example.com'},
            {'name': 'cc',        'label': 'CC',        'type': 'text',     'placeholder': 'optional@example.com'},
            {'name': 'subject',   'label': 'Subject',   'type': 'text',     'placeholder': 'Email subject line'},
            {'name': 'greeting',  'label': 'Greeting',  'type': 'text',     'placeholder': 'Dear John,'},
            {'name': 'body',      'label': 'Body',      'type': 'textarea', 'rows': 8, 'placeholder': 'The main content of your email...'},
            {'name': 'sign_off',  'label': 'Sign-off',  'type': 'text',     'placeholder': 'Kind regards,'},
            {'name': 'your_name', 'label': 'Your Name', 'type': 'text',     'placeholder': 'Your full name'},
        ],
    },
    'letter': {
        'label': 'Business Letter',
        'icon': 'fa-file-lines',
        'fields': [
            {'name': 'your_name',          'label': 'Your Name',           'type': 'text',     'placeholder': 'Your full name'},
            {'name': 'your_address',       'label': 'Your Address',        'type': 'textarea', 'rows': 3, 'placeholder': '123 Main Road\nJohannesburg, 2001'},
            {'name': 'recipient_name',     'label': 'Recipient Name',      'type': 'text',     'placeholder': 'Mr John Doe'},
            {'name': 'recipient_address',  'label': 'Recipient Address',   'type': 'textarea', 'rows': 3, 'placeholder': 'Acme Corp\n456 Business Ave\nCape Town, 8001'},
            {'name': 'date',               'label': 'Date',                'type': 'text',     'placeholder': '1 March 2026'},
            {'name': 'subject',            'label': 'Subject',             'type': 'text',     'placeholder': 'Re: Invoice #12345'},
            {'name': 'body',               'label': 'Body',                'type': 'textarea', 'rows': 8, 'placeholder': 'The full content of your letter...'},
            {'name': 'closing',            'label': 'Closing',             'type': 'text',     'placeholder': 'Yours sincerely,'},
            {'name': 'your_name_signed',   'label': 'Signed Name',         'type': 'text',     'placeholder': 'Your full name'},
        ],
    },
}


# ── List ────────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs')
@login_required
def index():
    docs = Document.query.filter_by(user_id=current_user.id)\
                         .order_by(Document.updated_at.desc()).all()
    return render_template('docs/index.html', docs=docs, doc_types=DOC_TYPES)


# ── New ─────────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        title    = request.form.get('title', '').strip()
        doc_type = request.form.get('doc_type', '').strip()
        if not title or doc_type not in DOC_TYPES:
            flash('Please provide a title and select a document type.', 'danger')
            return redirect(url_for('docs.new'))
        doc = Document(user_id=current_user.id, title=title, doc_type=doc_type)
        db.session.add(doc)
        db.session.commit()
        log_action('doc_created', f'{current_user.username} created document "{title}" ({doc_type})', current_user.id)
        return redirect(url_for('docs.edit', doc_id=doc.id))
    return render_template('docs/new.html', doc_types=DOC_TYPES)


# ── Edit ────────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    schema = DOC_TYPES[doc.doc_type]
    content = json.loads(doc.content_json or '{}')

    if request.method == 'POST':
        new_content = {}
        for field in schema['fields']:
            new_content[field['name']] = request.form.get(field['name'], '').strip()
        doc.content_json = json.dumps(new_content)
        doc.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Document saved.', 'success')
        return redirect(url_for('docs.preview', doc_id=doc.id))

    return render_template('docs/edit.html', doc=doc, schema=schema, content=content)


# ── Preview ─────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs/<int:doc_id>/preview')
@login_required
def preview(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    schema = DOC_TYPES[doc.doc_type]
    content = json.loads(doc.content_json or '{}')
    return render_template('docs/preview.html', doc=doc, schema=schema, content=content)


# ── Delete ──────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    db.session.delete(doc)
    db.session.commit()
    log_action('doc_deleted', f'{current_user.username} deleted document "{doc.title}"', current_user.id)
    flash('Document deleted.', 'success')
    return redirect(url_for('docs.index'))


# ── AI Draft ────────────────────────────────────────────────────────────────────

@docs_bp.route('/docs/ai-draft', methods=['POST'])
@login_required
def ai_draft():
    api_key = current_app.config.get('GEMINI_API_KEY', '')
    if not api_key:
        return jsonify({'error': 'AI not configured.'}), 503

    doc_type    = request.json.get('doc_type', '')
    user_prompt = request.json.get('user_prompt', '').strip()

    if doc_type not in DOC_TYPES or not user_prompt:
        return jsonify({'error': 'Invalid request.'}), 400

    schema = DOC_TYPES[doc_type]
    field_names = [f['name'] for f in schema['fields']]
    field_list  = ', '.join(field_names)

    system_prompt = (
        f'You are a professional document writer. '
        f'The user wants a {schema["label"]}. '
        f'Return ONLY a valid JSON object with these exact keys: {field_list}. '
        f'No markdown, no explanation — just the JSON.'
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            config=genai_types.GenerateContentConfig(system_instruction=system_prompt),
            contents=user_prompt,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        fields = json.loads(raw)
        return jsonify({'fields': fields})
    except json.JSONDecodeError:
        return jsonify({'error': 'AI returned invalid JSON. Try rephrasing your prompt.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
