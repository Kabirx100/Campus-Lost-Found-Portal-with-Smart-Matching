import os
import uuid
from datetime import date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import get_db, init_db
from matcher import find_matches

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clf-dev-secret-key')  # local demo default
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB image limit
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

CATEGORIES = ['Electronics', 'ID / Cards', 'Wallet / Money', 'Keys', 'Bag / Backpack',
              'Books / Stationery', 'Clothing', 'Accessories', 'Bottle / Lunchbox', 'Other']
LOCATIONS = ['Main Gate', 'Library', 'Canteen', 'Computer Lab', 'Classroom Block',
             'Sports Ground', 'Hostel', 'Parking Area', 'Auditorium', 'Other']

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()


# ---------- helpers ----------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def save_image(file):
    if not file or file.filename == '':
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(name)))
    return name


@app.context_processor
def inject_globals():
    return {'CATEGORIES': CATEGORIES, 'LOCATIONS': LOCATIONS, 'today': date.today().isoformat()}


# ---------- pages ----------
@app.route('/')
def index():
    db = get_db()
    stats = {
        'lost': db.execute("SELECT COUNT(*) FROM items WHERE type='lost' AND status='open'").fetchone()[0],
        'found': db.execute("SELECT COUNT(*) FROM items WHERE type='found' AND status='open'").fetchone()[0],
        'returned': db.execute("SELECT COUNT(*) FROM items WHERE status='returned'").fetchone()[0],
    }
    recent = db.execute("SELECT * FROM items WHERE status='open' ORDER BY created_at DESC LIMIT 6").fetchall()
    db.close()
    return render_template('index.html', stats=stats, recent=recent)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or len(password) < 6:
            flash('Fill all fields. Password must be at least 6 characters.', 'danger')
            return render_template('register.html')
        db = get_db()
        if db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone():
            db.close()
            flash('That email is already registered.', 'danger')
            return render_template('register.html')
        db.execute('INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
                   (name, email, generate_password_hash(password)))
        db.commit()
        db.close()
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        db.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            nxt = request.args.get('next')
            return redirect(nxt if nxt and nxt.startswith('/') else url_for('index'))
        flash('Wrong email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/report/<kind>', methods=['GET', 'POST'])
@login_required
def report(kind):
    if kind not in ('lost', 'found'):
        abort(404)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '')
        location = request.form.get('location', '').strip()
        event_date = request.form.get('event_date', '')
        contact = request.form.get('contact', '').strip()

        if not title or category not in CATEGORIES or not location or not event_date:
            flash('Title, category, location and date are required.', 'danger')
            return render_template('report.html', kind=kind, form=request.form)
        if event_date > date.today().isoformat():
            flash('Date cannot be in the future.', 'danger')
            return render_template('report.html', kind=kind, form=request.form)

        image = save_image(request.files.get('image'))
        db = get_db()
        cur = db.execute(
            '''INSERT INTO items (user_id, type, title, description, category, location,
                                  event_date, image, contact)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (session['user_id'], kind, title, description, category, location,
             event_date, image, contact))
        db.commit()
        item_id = cur.lastrowid
        db.close()
        flash('Report submitted. Check the suggested matches below.', 'success')
        return redirect(url_for('item_detail', item_id=item_id))
    return render_template('report.html', kind=kind, form={})


@app.route('/items')
def items():
    q = request.args.get('q', '').strip()
    kind = request.args.get('type', '')
    category = request.args.get('category', '')
    sql = "SELECT * FROM items WHERE status = 'open'"
    params = []
    if kind in ('lost', 'found'):
        sql += ' AND type = ?'
        params.append(kind)
    if category in CATEGORIES:
        sql += ' AND category = ?'
        params.append(category)
    if q:
        sql += ' AND (title LIKE ? OR description LIKE ? OR location LIKE ?)'
        params += [f'%{q}%'] * 3
    sql += ' ORDER BY created_at DESC'
    db = get_db()
    rows = db.execute(sql, params).fetchall()
    db.close()
    return render_template('items.html', items=rows, q=q, kind=kind, category=category)


@app.route('/item/<int:item_id>')
def item_detail(item_id):
    db = get_db()
    item = db.execute('''SELECT items.*, users.name AS owner_name FROM items
                         JOIN users ON users.id = items.user_id WHERE items.id = ?''',
                      (item_id,)).fetchone()
    if item is None:
        db.close()
        abort(404)

    uid = session.get('user_id')
    is_owner = uid == item['user_id']
    is_admin = session.get('role') == 'admin'

    # Smart matches: shown only to the reporter and admins
    matches = []
    if (is_owner or is_admin) and item['status'] == 'open':
        opposite = 'found' if item['type'] == 'lost' else 'lost'
        candidates = db.execute("SELECT * FROM items WHERE type = ? AND status = 'open'",
                                (opposite,)).fetchall()
        matches = find_matches(item, candidates)[:5]

    my_claim = None
    if uid:
        my_claim = db.execute('SELECT * FROM claims WHERE item_id = ? AND claimant_id = ?',
                              (item_id, uid)).fetchone()
    can_see_contact = is_owner or is_admin or (my_claim is not None and my_claim['status'] == 'approved')
    can_claim = (uid is not None and not is_owner and item['type'] == 'found'
                 and item['status'] == 'open' and my_claim is None)
    db.close()
    return render_template('item.html', item=item, matches=matches, is_owner=is_owner,
                           my_claim=my_claim, can_claim=can_claim,
                           can_see_contact=can_see_contact)


@app.route('/item/<int:item_id>/claim', methods=['POST'])
@login_required
def claim_item(item_id):
    message = request.form.get('message', '').strip()
    if len(message) < 10:
        flash('Please describe how you can prove this item is yours (10+ characters).', 'danger')
        return redirect(url_for('item_detail', item_id=item_id))
    db = get_db()
    item = db.execute('SELECT * FROM items WHERE id = ?', (item_id,)).fetchone()
    if (item is None or item['type'] != 'found' or item['status'] != 'open'
            or item['user_id'] == session['user_id']):
        db.close()
        abort(400)
    exists = db.execute('SELECT id FROM claims WHERE item_id = ? AND claimant_id = ?',
                        (item_id, session['user_id'])).fetchone()
    if not exists:
        db.execute('INSERT INTO claims (item_id, claimant_id, message) VALUES (?, ?, ?)',
                   (item_id, session['user_id'], message))
        db.commit()
        flash('Claim sent. An admin will review it.', 'success')
    db.close()
    return redirect(url_for('item_detail', item_id=item_id))


@app.route('/item/<int:item_id>/resolve', methods=['POST'])
@login_required
def resolve_item(item_id):
    db = get_db()
    item = db.execute('SELECT * FROM items WHERE id = ?', (item_id,)).fetchone()
    if item is None:
        db.close()
        abort(404)
    if item['user_id'] != session['user_id'] and session.get('role') != 'admin':
        db.close()
        abort(403)
    db.execute("UPDATE items SET status = 'returned' WHERE id = ?", (item_id,))
    db.commit()
    db.close()
    flash('Marked as resolved.', 'success')
    return redirect(url_for('my_reports'))


@app.route('/my-reports')
@login_required
def my_reports():
    db = get_db()
    mine = db.execute('SELECT * FROM items WHERE user_id = ? ORDER BY created_at DESC',
                      (session['user_id'],)).fetchall()
    rows = []
    for it in mine:
        count = 0
        if it['status'] == 'open':
            opposite = 'found' if it['type'] == 'lost' else 'lost'
            cands = db.execute("SELECT * FROM items WHERE type = ? AND status = 'open'",
                               (opposite,)).fetchall()
            count = len(find_matches(it, cands))
        rows.append({'item': it, 'match_count': count})
    claims = db.execute('''SELECT claims.*, items.title FROM claims
                           JOIN items ON items.id = claims.item_id
                           WHERE claimant_id = ? ORDER BY claims.created_at DESC''',
                        (session['user_id'],)).fetchall()
    db.close()
    return render_template('my_reports.html', rows=rows, claims=claims)


# ---------- admin ----------
@app.route('/admin')
@admin_required
def admin():
    db = get_db()
    pending = db.execute('''SELECT claims.*, items.title, users.name AS claimant_name,
                                   users.email AS claimant_email
                            FROM claims JOIN items ON items.id = claims.item_id
                            JOIN users ON users.id = claims.claimant_id
                            WHERE claims.status = 'pending' ORDER BY claims.created_at''').fetchall()
    all_items = db.execute('''SELECT items.*, users.name AS owner_name FROM items
                              JOIN users ON users.id = items.user_id
                              ORDER BY items.created_at DESC''').fetchall()
    db.close()
    return render_template('admin.html', pending=pending, all_items=all_items)


@app.route('/admin/claim/<int:claim_id>/<action>', methods=['POST'])
@admin_required
def review_claim(claim_id, action):
    if action not in ('approve', 'reject'):
        abort(404)
    db = get_db()
    claim = db.execute('SELECT * FROM claims WHERE id = ?', (claim_id,)).fetchone()
    if claim is None:
        db.close()
        abort(404)
    if action == 'approve':
        db.execute("UPDATE claims SET status = 'approved' WHERE id = ?", (claim_id,))
        db.execute("UPDATE claims SET status = 'rejected' WHERE item_id = ? AND id != ? AND status = 'pending'",
                   (claim['item_id'], claim_id))
        db.execute("UPDATE items SET status = 'returned' WHERE id = ?", (claim['item_id'],))
    else:
        db.execute("UPDATE claims SET status = 'rejected' WHERE id = ?", (claim_id,))
    db.commit()
    db.close()
    flash('Claim approved.' if action == 'approve' else 'Claim rejected.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/item/<int:item_id>/delete', methods=['POST'])
@admin_required
def delete_item(item_id):
    db = get_db()
    db.execute('DELETE FROM items WHERE id = ?', (item_id,))
    db.commit()
    db.close()
    flash('Item deleted.', 'info')
    return redirect(url_for('admin'))


if __name__ == '__main__':
    app.run(debug=True)
