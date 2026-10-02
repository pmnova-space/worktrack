from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = 'worktrack-secret-key-2026-change-this'

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ============ ADMIN CREDENTIALS ============
ADMIN_USERNAME = 'khoth'
ADMIN_PASSWORD = 'Khoth@123'

# ============ DATABASE INIT ============
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT UNIQUE,
            name TEXT NOT NULL,
            phone TEXT,
            daily_wage INTEGER DEFAULT 0,
            photo TEXT,
            join_date TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(worker_id, date)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            date TEXT NOT NULL,
            note TEXT,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()

init_db()

# ============ HELPERS ============
def get_today():
    return datetime.now().strftime('%Y-%m-%d')

def get_today_display():
    return datetime.now().strftime('%d %B %Y')

def get_current_month():
    return datetime.now().strftime('%Y-%m')

def is_admin():
    return session.get('admin') == True

# Login check decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

# Template context — is_admin एक function है, इसलिए template में is_admin() call करेंगे
@app.context_processor
def inject_admin():
    return dict(is_admin=is_admin)

# ============ LOGIN / LOGOUT ============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']

        if username == ADMIN_USERNAME.lower() and password == ADMIN_PASSWORD:
            session['admin'] = True
            session.permanent = True
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('home'))
        else:
            return render_template('login.html', error='गलत username या password')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('home'))

# ============ DASHBOARD ============
@app.route('/')
def home():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM workers")
    total_workers = c.fetchone()[0]

    today = get_today()
    c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'P'", (today,))
    present_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'A'", (today,))
    absent_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'H'", (today,))
    half_today = c.fetchone()[0]

    month = get_current_month()
    c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE date LIKE ?", (month + '%',))
    month_payment = c.fetchone()[0]

    c.execute("SELECT worker_id, daily_wage FROM workers")
    workers_data = c.fetchall()

    total_due = 0
    for w_id, wage in workers_data:
        c.execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'P'", (w_id,))
        p_days = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'H'", (w_id,))
        h_days = c.fetchone()[0]

        earned = (p_days * wage) + (h_days * wage // 2)

        c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE worker_id = ?", (w_id,))
        paid = c.fetchone()[0]

        total_due += max(0, earned - paid)

    conn.close()

    return render_template('index.html',
                         total_workers=total_workers,
                         present_today=present_today,
                         absent_today=absent_today,
                         half_today=half_today,
                         month_payment=month_payment,
                         total_due=total_due,
                         today=get_today_display())

# ============ WORKERS LIST ============
@app.route('/workers')
def workers():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM workers ORDER BY id DESC")
    all_workers = c.fetchall()
    conn.close()
    return render_template('workers.html', workers=all_workers)

# ============ ADD WORKER (Admin only) ============
@app.route('/add_worker', methods=['GET', 'POST'])
@admin_required
def add_worker():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        daily_wage = request.form['daily_wage']
        join_date = datetime.now().strftime('%d-%m-%Y')

        photo = request.files['photo']
        photo_name = ''
        if photo and photo.filename:
            photo_name = secure_filename(photo.filename)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_name))

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM workers")
        count = c.fetchone()[0] + 1
        worker_id = f"W{count:03d}"

        c.execute('''
            INSERT INTO workers (worker_id, name, phone, daily_wage, photo, join_date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (worker_id, name, phone, daily_wage, photo_name, join_date))

        conn.commit()
        conn.close()

        return redirect(url_for('workers'))

    return render_template('add_worker.html')

# ============ ID CARD ============
@app.route('/id_card/<int:worker_id>')
def id_card(worker_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))
    worker = c.fetchone()
    conn.close()
    return render_template('id_card.html', worker=worker)

# ============ DELETE WORKER (Admin only) ============
@app.route('/delete_worker/<int:worker_id>')
@admin_required
def delete_worker(worker_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT worker_id FROM workers WHERE id = ?", (worker_id,))
    row = c.fetchone()
    if row:
        w_id = row[0]
        c.execute("DELETE FROM attendance WHERE worker_id = ?", (w_id,))
        c.execute("DELETE FROM payments WHERE worker_id = ?", (w_id,))
        c.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('workers'))

# ============ ATTENDANCE ============
@app.route('/attendance')
def attendance():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT * FROM workers ORDER BY worker_id")
    all_workers = c.fetchall()

    today = get_today()
    c.execute("SELECT worker_id, status FROM attendance WHERE date = ?", (today,))
    today_attendance = {row[0]: row[1] for row in c.fetchall()}

    conn.close()

    return render_template('attendance.html',
                         workers=all_workers,
                         today_attendance=today_attendance,
                         today=get_today_display())

# ============ SAVE ATTENDANCE (Admin only) ============
@app.route('/save_attendance', methods=['POST'])
@admin_required
def save_attendance():
    today = get_today()
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    for key, value in request.form.items():
        if key.startswith('status_'):
            worker_id = key.replace('status_', '')
            status = value

            c.execute('''
                INSERT INTO attendance (worker_id, date, status)
                VALUES (?, ?, ?)
                ON CONFLICT(worker_id, date)
                DO UPDATE SET status = excluded.status
            ''', (worker_id, today, status))

    conn.commit()
    conn.close()

    return redirect(url_for('attendance'))

# ============ PAYMENTS ============
@app.route('/payments')
def payments():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT * FROM workers ORDER BY worker_id")
    all_workers = c.fetchall()

    c.execute('''
        SELECT p.id, p.worker_id, w.name, p.amount, p.date, p.note
        FROM payments p
        LEFT JOIN workers w ON p.worker_id = w.worker_id
        ORDER BY p.id DESC
    ''')
    all_payments = c.fetchall()

    conn.close()

    return render_template('payments.html',
                         workers=all_workers,
                         payments=all_payments,
                         today=get_today_display(),
                         today_iso=get_today())

# ============ ADD PAYMENT (Admin only) ============
@app.route('/add_payment', methods=['POST'])
@admin_required
def add_payment():
    worker_id = request.form['worker_id']
    amount = request.form['amount']
    note = request.form.get('note', '')
    date = request.form.get('date', get_today())

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO payments (worker_id, amount, date, note, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (worker_id, amount, date, note, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

    return redirect(url_for('payments'))

# ============ DELETE PAYMENT (Admin only) ============
@app.route('/delete_payment/<int:payment_id>')
@admin_required
def delete_payment(payment_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('payments'))

# ============ WORKER DETAIL ============
@app.route('/worker_detail/<worker_id>')
def worker_detail(worker_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
    worker = c.fetchone()

    if not worker:
        conn.close()
        return redirect(url_for('workers'))

    c.execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'P'", (worker_id,))
    present_days = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'H'", (worker_id,))
    half_days = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'A'", (worker_id,))
    absent_days = c.fetchone()[0]

    wage = worker[4]
    earned = (present_days * wage) + (half_days * wage // 2)

    c.execute('''
        SELECT id, amount, date, note
        FROM payments
        WHERE worker_id = ?
        ORDER BY id DESC
    ''', (worker_id,))
    all_payments = c.fetchall()

    c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE worker_id = ?", (worker_id,))
    total_paid = c.fetchone()[0]

    due = earned - total_paid

    c.execute('''
        SELECT date, status FROM attendance
        WHERE worker_id = ?
        ORDER BY date DESC
    ''', (worker_id,))
    attendance_history = c.fetchall()

    conn.close()

    return render_template('worker_detail.html',
                         worker=worker,
                         present_days=present_days,
                         half_days=half_days,
                         absent_days=absent_days,
                         earned=earned,
                         total_paid=total_paid,
                         due=due,
                         payments=all_payments,
                         attendance_history=attendance_history,
                         today=get_today_display())

if __name__ == '__main__':
    app.run(debug=True)