import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, request

PASSWORD = os.environ.get('AMAZON_PASSWORD', 'Faure02112002@')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amazon-secret')

def get_db():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except:
        return None

def init_db():
    conn = get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS emails (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            used BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL,
            cookies TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

def get_emails_count():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as count FROM emails WHERE used = FALSE")
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result['count'] if result else 0
        except:
            pass
    return 0

def get_accounts_count():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as count FROM accounts")
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result['count'] if result else 0
        except:
            pass
    return 0

def add_emails_to_db(emails_list):
    conn = get_db()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        added = 0
        for email in emails_list:
            try:
                cur.execute("INSERT INTO emails (email) VALUES (%s) ON CONFLICT DO NOTHING", (email,))
                if cur.rowcount > 0:
                    added += 1
            except:
                pass
        conn.commit()
        cur.close()
        conn.close()
        return added
    except:
        return 0

def get_all_accounts():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT email, password, cookies, created_at FROM accounts ORDER BY created_at DESC")
            results = cur.fetchall()
            cur.close()
            conn.close()
            return results
        except:
            pass
    return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/stats')
def get_stats():
    return jsonify({
        'emails_remaining': get_emails_count(),
        'accounts_created': get_accounts_count()
    })

@app.route('/api/emails', methods=['GET', 'POST'])
def handle_emails():
    if request.method == 'POST':
        try:
            emails_text = request.form.get('emails', '') or request.data.decode('utf-8')
            if 'file' in request.files:
                emails_text = request.files['file'].read().decode('utf-8')
            new_emails = [e.strip() for e in emails_text.split('\n') if e.strip() and '@' in e]
            if not new_emails:
                return jsonify({'error': 'Aucun email valide'}), 400
            added = add_emails_to_db(new_emails)
            return jsonify({'success': True, 'added': added, 'total': get_emails_count()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'count': get_emails_count()})

@app.route('/api/accounts')
def get_accounts():
    accounts = get_all_accounts()
    formatted = []
    for acc in accounts:
        formatted.append({
            'email': acc['email'],
            'password': acc['password'],
            'cookies': acc['cookies'],
            'created_at': str(acc['created_at']) if acc['created_at'] else None
        })
    return jsonify({'accounts': formatted, 'count': len(formatted)})

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Amazon Generator",
        "short_name": "AmazonGen",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#ff6b35"
    })

try:
    init_db()
except:
    pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
