import os
import re
import json
import time
import random
import string
import imaplib
import email as email_module
import threading
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, request
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote

PASSWORD = os.environ.get('AMAZON_PASSWORD', 'Faure02112002@')
IMAP_SERVER = os.environ.get('IMAP_SERVER', 'imap.mail.me.com')
IMAP_PORT = int(os.environ.get('IMAP_PORT', '993'))
IMAP_USER = os.environ.get('IMAP_USER', '')
IMAP_PASSWORD = os.environ.get('IMAP_PASSWORD', '')
HEROSMS_API_KEY = os.environ.get('HEROSMS_API_KEY', '')
HEROSMS_BASE_URL = 'https://hero-sms.com/stubs/handler_api.php'
DATABASE_URL = os.environ.get('DATABASE_URL', '')

FIRST_NAMES = ['Marie', 'Jean', 'Sophie', 'Pierre', 'Claire', 'Thomas', 'Julie', 'Lucas']
LAST_NAMES = ['Dupont', 'Martin', 'Durand', 'Bernard', 'Lefevre', 'Moreau', 'Simon', 'Laurent']

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amazon-secret')

generation_state = {
    'active': False, 'step': 'idle', 'email': None, 'customer_name': None,
    'logs': [], 'captcha_url': None, 'captcha_token': None, 'session_data': None, 'error': None
}
state_lock = threading.Lock()

def get_db():
    if not DATABASE_URL: return None
    try: return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except: return None

def init_db():
    conn = get_db()
    if not conn: return
    try:
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS emails (id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, used BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL, cookies TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        cur.close()
        conn.close()
    except: pass

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
        except: pass
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
        except: pass
    return 0

def get_random_email():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT email FROM emails WHERE used = FALSE ORDER BY RANDOM() LIMIT 1")
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result['email'] if result else None
        except: pass
    return None

def mark_email_used(email):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE emails SET used = TRUE WHERE email = %s", (email,))
            conn.commit()
            cur.close()
            conn.close()
        except: pass

def save_account_db(email, password, cookies_dict):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cookies_json = json.dumps(cookies_dict) if cookies_dict else '{}'
            cur.execute('INSERT INTO accounts (email, password, cookies) VALUES (%s, %s, %s) ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password, cookies = EXCLUDED.cookies', (email, password, cookies_json))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except: pass
    return False

def add_emails_to_db(emails_list):
    conn = get_db()
    if not conn: return 0
    try:
        cur = conn.cursor()
        added = 0
        for email in emails_list:
            try:
                cur.execute("INSERT INTO emails (email) VALUES (%s) ON CONFLICT DO NOTHING", (email,))
                if cur.rowcount > 0: added += 1
            except: pass
        conn.commit()
        cur.close()
        conn.close()
        return added
    except: return 0

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
        except: pass
    return []

def add_log(message, log_type='info'):
    with state_lock:
        generation_state['logs'].append({'time': time.strftime('%H:%M:%S'), 'type': log_type, 'message': message})
        if len(generation_state['logs']) > 50:
            generation_state['logs'] = generation_state['logs'][-50:]

def set_step(step):
    with state_lock:
        generation_state['step'] = step

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/stats')
def get_stats():
    return jsonify({'emails_remaining': get_emails_count(), 'accounts_created': get_accounts_count()})

@app.route('/api/state')
def get_state():
    with state_lock:
        return jsonify({
            'active': generation_state['active'], 'step': generation_state['step'],
            'email': generation_state['email'], 'customer_name': generation_state['customer_name'],
            'logs': generation_state['logs'][-20:], 'captcha_url': generation_state['captcha_url'],
            'error': generation_state['error']
        })

@app.route('/api/start', methods=['POST'])
def start_generation():
    global generation_state
    with state_lock:
        if generation_state['active']:
            return jsonify({'error': 'Generation deja en cours'}), 400
        generation_state = {'active': True, 'step': 'init', 'email': None, 'customer_name': None,
            'logs': [], 'captcha_url': None, 'captcha_token': None, 'session_data': None, 'error': None}
    add_log('Generation demarree - En developpement', 'info')
    set_step('demo')
    with state_lock:
        generation_state['active'] = False
    return jsonify({'success': True, 'message': 'Demo mode'})

@app.route('/api/captcha', methods=['POST'])
def submit_captcha():
    data = request.get_json()
    token = data.get('token', '')
    if not token: return jsonify({'error': 'Token manquant'}), 400
    with state_lock:
        generation_state['captcha_token'] = token
    return jsonify({'success': True})

@app.route('/api/stop', methods=['POST'])
def stop_generation():
    global generation_state
    with state_lock:
        generation_state['active'] = False
        generation_state['step'] = 'stopped'
    return jsonify({'success': True})

@app.route('/api/emails', methods=['GET', 'POST'])
def handle_emails():
    if request.method == 'POST':
        try:
            emails_text = request.form.get('emails', '') or request.data.decode('utf-8')
            if 'file' in request.files:
                emails_text = request.files['file'].read().decode('utf-8')
            new_emails = [e.strip() for e in emails_text.split('\n') if e.strip() and '@' in e]
            if not new_emails: return jsonify({'error': 'Aucun email valide'}), 400
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
        formatted.append({'email': acc['email'], 'password': acc['password'], 'cookies': acc['cookies'], 'created_at': str(acc['created_at']) if acc['created_at'] else None})
    return jsonify({'accounts': formatted, 'count': len(formatted)})

@app.route('/manifest.json')
def manifest():
    return jsonify({"name": "Amazon Generator", "short_name": "AmazonGen", "start_url": "/", "display": "standalone", "background_color": "#0f0f23", "theme_color": "#ff6b35"})

try:
    init_db()
except: pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
