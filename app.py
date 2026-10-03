from flask import Flask, render_template, request, redirect, url_for, session
import os
from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename
from functools import wraps
import libsql_client
import asyncio

# ============ INDIA TIMEZONE ============
IST = timezone(timedelta(hours=5, minutes=30))

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'worktrack-secret-key-2026-change-this')

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ============ TURSO CONFIG ============
TURSO_URL = os.environ.get('TURSO_URL', '')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN', '')

# ============ ADMIN CREDENTIALS ============
ADMIN_USERNAME = 'khoth'
ADMIN_PASSWORD = 'Khoth@123'

# ============ DATABASE HELPERS ============
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

def db_execute(query, params=None):
    async def _execute():
        async with libsql_client.create_client(
            url=TURSO_URL,
            auth_token=TURSO_TOKEN
        ) as client:
            if params:
                result = await client.execute(query, params)
            else:
                result = await client.execute(query)
            return result.rows
    return run_async(_execute())

def to_int(value):
    try:
        if value is None:
            return 0
        return int(value)
    except (ValueError, TypeError):
        return 0

# ============ DATABASE INIT ============
def init_db():
    async def _init():
        async with libsql_client.create_client(
            url=TURSO_URL,
            auth_token=TURSO_TOKEN
        ) as client:
            await client.execute('''
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
            await client.execute('''
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    UNIQUE(worker_id, date)
                )
            ''')
            await client.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT
                )
            ''')
    run_async(_init())

if TURSO_URL and TURSO_TOKEN:
    try:
        init_db()
        print("✅ Turso database connected!")
    except Exception as e:
        print(f"⚠️ Database init error: {e}")
else:
    print("⚠️ TURSO_URL और TURSO_TOKEN set नहीं हैं।")

# ============ HELPERS ============
def get_today():
    return datetime.now(IST).strftime('%Y-%m-%d')

def get_today_display():
    return datetime.now(IST).strftime('%d %B %Y')

def get_current_month():
    return datetime.now(IST).strftime('%Y-%m')

def is_admin():
    return session.get('admin') == True

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

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
    total_workers = to_int(db_execute("SELECT COUNT(*) FROM workers")[0][0])

    today = get_today()
    present_today = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'P'", [today])[0][0])
    absent_today = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'A'", [today])[0][0])
    half_today = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'H'", [today])[0][0])

    month = get_current_month()
    month_payment = to_int(db_execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE date LIKE ?", [month + '%'])[0][0])

    workers_data = db_execute("SELECT worker_id, daily_wage FROM workers")

    total_due = 0
    for w_id, wage in workers_data:
        wage = to_int(wage)
        p_days = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'P'", [w_id])[0][0])
        h_days = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'H'", [w_id])[0][0])
        earned = (p_days * wage) + (h_days * wage // 2)
        paid = to_int(db_execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE worker_id = ?", [w_id])[0][0])
        total_due += max(0, earned - paid)

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
    all_workers = db_execute("SELECT * FROM workers ORDER BY id DESC")
    return render_template('workers.html', workers=all_workers)

# ============ ADD WORKER ============
@app.route('/add_worker', methods=['GET', 'POST'])
@admin_required
def add_worker():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        daily_wage = request.form['daily_wage']
        join_date = datetime.now(IST).strftime('%d-%m-%Y')

        photo = request.files['photo']
        photo_name = ''
        if photo and photo.filename:
            photo_name = secure_filename(photo.filename)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], photo_name))

        max_result = db_execute("SELECT COALESCE(MAX(id), 0) FROM workers")
        max_id = to_int(max_result[0][0]) + 1
        worker_id = f"W{max_id:03d}"

        db_execute(
            "INSERT INTO workers (worker_id, name, phone, daily_wage, photo, join_date) VALUES (?, ?, ?, ?, ?, ?)",
            [worker_id, name, phone, daily_wage, photo_name, join_date]
        )

        return redirect(url_for('workers'))

    return render_template('add_worker.html')

# ============ ID CARD ============
@app.route('/id_card/<int:worker_id>')
def id_card(worker_id):
    result = db_execute("SELECT * FROM workers WHERE id = ?", [worker_id])
    worker = result[0] if result else None
    return render_template('id_card.html', worker=worker)

# ============ DELETE WORKER ============
@app.route('/delete_worker/<int:worker_id>')
@admin_required
def delete_worker(worker_id):
    row = db_execute("SELECT worker_id FROM workers WHERE id = ?", [worker_id])
    if row:
        w_id = row[0][0]
        db_execute("DELETE FROM attendance WHERE worker_id = ?", [w_id])
        db_execute("DELETE FROM payments WHERE worker_id = ?", [w_id])
        db_execute("DELETE FROM workers WHERE id = ?", [worker_id])
    return redirect(url_for('workers'))

# ============ ATTENDANCE ============
@app.route('/attendance')
def attendance():
    all_workers = db_execute("SELECT * FROM workers ORDER BY worker_id")
    today = get_today()
    today_rows = db_execute("SELECT worker_id, status FROM attendance WHERE date = ?", [today])
    today_attendance = {row[0]: row[1] for row in today_rows}

    return render_template('attendance.html',
                         workers=all_workers,
                         today_attendance=today_attendance,
                         today=get_today_display())

@app.route('/save_attendance', methods=['POST'])
@admin_required
def save_attendance():
    today = get_today()
    for key, value in request.form.items():
        if key.startswith('status_'):
            worker_id = key.replace('status_', '')
            status = value
            db_execute(
                "INSERT INTO attendance (worker_id, date, status) VALUES (?, ?, ?) ON CONFLICT(worker_id, date) DO UPDATE SET status = excluded.status",
                [worker_id, today, status]
            )
    return redirect(url_for('attendance'))

# ============ PAYMENTS ============
@app.route('/payments')
def payments():
    all_workers = db_execute("SELECT * FROM workers ORDER BY worker_id")
    all_payments = db_execute('''
        SELECT p.id, p.worker_id, w.name, p.amount, p.date, p.note
        FROM payments p
        LEFT JOIN workers w ON p.worker_id = w.worker_id
        ORDER BY p.id DESC
    ''')
    return render_template('payments.html',
                         workers=all_workers,
                         payments=all_payments,
                         today=get_today_display(),
                         today_iso=get_today())

@app.route('/add_payment', methods=['POST'])
@admin_required
def add_payment():
    worker_id = request.form['worker_id']
    amount = request.form['amount']
    note = request.form.get('note', '')
    date = request.form.get('date', get_today())

    db_execute(
        "INSERT INTO payments (worker_id, amount, date, note, created_at) VALUES (?, ?, ?, ?, ?)",
        [worker_id, amount, date, note, datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')]
    )
    return redirect(url_for('payments'))

@app.route('/delete_payment/<int:payment_id>')
@admin_required
def delete_payment(payment_id):
    db_execute("DELETE FROM payments WHERE id = ?", [payment_id])
    return redirect(request.referrer or url_for('payments'))

# ============ WORKER DETAIL ============
@app.route('/worker_detail/<worker_id>')
def worker_detail(worker_id):
    result = db_execute("SELECT * FROM workers WHERE worker_id = ?", [worker_id])
    worker = result[0] if result else None

    if not worker:
        return redirect(url_for('workers'))

    present_days = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'P'", [worker_id])[0][0])
    half_days = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'H'", [worker_id])[0][0])
    absent_days = to_int(db_execute("SELECT COUNT(*) FROM attendance WHERE worker_id = ? AND status = 'A'", [worker_id])[0][0])

    wage = to_int(worker[4])
    earned = (present_days * wage) + (half_days * wage // 2)

    all_payments = db_execute(
        "SELECT id, amount, date, note FROM payments WHERE worker_id = ? ORDER BY id DESC",
        [worker_id]
    )

    total_paid = to_int(db_execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE worker_id = ?", [worker_id])[0][0])
    due = earned - total_paid

    attendance_history = db_execute(
        "SELECT date, status FROM attendance WHERE worker_id = ? ORDER BY date DESC",
        [worker_id]
    )

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

# ============ RUN ============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)