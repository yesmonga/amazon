"""
Amazon Account Generator - Railway Web App
Interface mobile-friendly pour générer des comptes Amazon
Avec support PostgreSQL pour stocker emails, comptes et cookies
"""

import os
import re
import json
import time
import random
import imaplib
import email as email_module
import requests
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from urllib.parse import quote

# ============== CONFIGURATION (Variables d'environnement) ==============
PASSWORD = os.environ.get('AMAZON_PASSWORD', 'Faure02112002@')
ARKOSE_PUBLIC_KEY = os.environ.get('ARKOSE_PUBLIC_KEY', '56938EF5-6EFA-483E-B6F6-C8A72B6A95EE')

# IMAP iCloud
IMAP_SERVER = os.environ.get('IMAP_SERVER', 'imap.mail.me.com')
IMAP_PORT = int(os.environ.get('IMAP_PORT', '993'))
IMAP_USER = os.environ.get('IMAP_USER', '')
IMAP_PASSWORD = os.environ.get('IMAP_PASSWORD', '')

# Hero SMS
HEROSMS_API_KEY = os.environ.get('HEROSMS_API_KEY', '')
HEROSMS_BASE_URL = os.environ.get('HEROSMS_BASE_URL', 'https://hero-sms.com/stubs/handler_api.php')

# PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ============== APP FLASK ==============
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amazon-generator-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============== ÉTAT GLOBAL ==============
current_job = {
    'active': False,
    'email': None,
    'status': 'idle',
    'captcha_url': None,
    'session_data': None,
    'waiting_for_captcha': False
}

# Lock pour thread-safety
job_lock = threading.Lock()

# ============== DATABASE ==============
def get_db():
    """Connexion à PostgreSQL"""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"DB Error: {e}")
        return None

def init_db():
    """Initialise les tables PostgreSQL"""
    conn = get_db()
    if not conn:
        print("No DATABASE_URL configured, using file storage")
        return False
    
    try:
        cur = conn.cursor()
        
        # Table emails (emails à utiliser)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table accounts (comptes créés)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                cookies TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully")
        return True
    except Exception as e:
        print(f"DB Init Error: {e}")
        return False

def get_emails_count():
    """Compte les emails disponibles"""
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

def get_random_email():
    """Prend un email aléatoire de la liste"""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT email FROM emails WHERE used = FALSE ORDER BY RANDOM() LIMIT 1")
            result = cur.fetchone()
            cur.close()
            conn.close()
            return result['email'] if result else None
        except:
            pass
    return None

def remove_email(email):
    """Marque un email comme utilisé"""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE emails SET used = TRUE WHERE email = %s", (email,))
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass

def save_account(email, password, cookies_dict):
    """Sauvegarde le compte créé dans PostgreSQL"""
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cookies_json = json.dumps(cookies_dict) if cookies_dict else '{}'
            cur.execute('''
                INSERT INTO accounts (email, password, cookies)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    password = EXCLUDED.password,
                    cookies = EXCLUDED.cookies
            ''', (email, password, cookies_json))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Save account error: {e}")
    return False

def add_emails_to_db(emails_list):
    """Ajoute des emails à la base de données"""
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
    """Récupère tous les comptes créés"""
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

# ============== HERO SMS ==============
def get_french_number():
    """Obtient un numéro français via Hero SMS"""
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=getNumberV2&service=am&country=78'
    try:
        response = requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            activation_id = data.get('activationId')
            phone_number = str(data.get('phoneNumber', ''))
            if activation_id and phone_number:
                phone_without_country = phone_number[2:] if phone_number.startswith('33') else phone_number
                return {
                    'activation_id': str(activation_id),
                    'phone_number': phone_number,
                    'phone_without_country': phone_without_country
                }
    except:
        pass
    return None

def set_sms_status_ready(activation_id):
    """Marque le numéro comme prêt à recevoir SMS"""
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=setStatus&status=1&id={activation_id}'
    try:
        requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'})
    except:
        pass

def get_sms_otp(activation_id, max_wait=60):
    """Attend et récupère le code SMS"""
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=getStatus&id={activation_id}'
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'})
            result = response.text.strip()
            if result.startswith('STATUS_OK:'):
                return result.split(':')[1]
        except:
            pass
        time.sleep(1)
    return None

# ============== EMAIL OTP ==============
def get_otp_from_email(target_email, max_wait=120):
    """Récupère le code OTP depuis l'email"""
    from email.utils import parsedate_to_datetime
    
    time.sleep(5)
    search_start_time = time.time()
    target_local = target_email.split('@')[0].lower()
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
            mail.login(IMAP_USER, IMAP_PASSWORD)
            mail.select('INBOX')
            
            _, messages = mail.search(None, '(UNSEEN)')
            email_ids = messages[0].split() if messages[0] else []
            
            if email_ids:
                for email_id in reversed(email_ids[-20:]):
                    _, msg_data = mail.fetch(email_id, '(BODY.PEEK[])')
                    
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email_module.message_from_bytes(response_part[1])
                            
                            from_addr = msg.get('From', '').lower()
                            subject = msg.get('Subject', '').lower()
                            to_addr = msg.get('To', '').lower()
                            
                            date_str = msg.get('Date', '')
                            try:
                                email_date = parsedate_to_datetime(date_str)
                                if email_date.timestamp() < (search_start_time - 60):
                                    continue
                            except:
                                pass
                            
                            if 'amazon' in from_addr or 'amazon' in subject:
                                body = ''
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        content_type = part.get_content_type()
                                        if content_type == 'text/plain':
                                            payload = part.get_payload(decode=True)
                                            if payload:
                                                body = payload.decode('utf-8', errors='ignore')
                                                break
                                        elif content_type == 'text/html' and not body:
                                            payload = part.get_payload(decode=True)
                                            if payload:
                                                body = payload.decode('utf-8', errors='ignore')
                                else:
                                    payload = msg.get_payload(decode=True)
                                    if payload:
                                        body = payload.decode('utf-8', errors='ignore')
                                
                                is_for_target = (
                                    target_email.lower() in to_addr or
                                    target_local in to_addr or
                                    target_email.lower() in body.lower() or
                                    target_local in body.lower()
                                )
                                
                                if is_for_target:
                                    otp_match = re.search(r'\b(\d{6})\b', body)
                                    if otp_match:
                                        mail.store(email_id, '+FLAGS', '\\Seen')
                                        mail.logout()
                                        return otp_match.group(1)
            
            mail.logout()
        except:
            pass
        time.sleep(5)
    return None

# ============== GÉNÉRATION COMPTE ==============
def generate_account_thread(email):
    """Thread principal de génération de compte"""
    global current_job
    
    def update_status(status, captcha_url=None):
        with job_lock:
            current_job['status'] = status
            if captcha_url:
                current_job['captcha_url'] = captcha_url
                current_job['waiting_for_captcha'] = True
        socketio.emit('status_update', {
            'status': status,
            'email': email,
            'captcha_url': captcha_url
        })
    
    try:
        update_status('starting')
        
        # Headers
        headers_get = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'fr-FR,fr;q=0.9',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/143.0.0.0 Safari/537.36'
        }
        
        url_get = 'https://www.amazon.fr/ap/register?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.fr%2F&openid.assoc_handle=frflex&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.ns.pape=http%3A%2F%2Fspecs.openid.net%2Fextensions%2Fpape%2F1.0&pageId=frflex&failedSignInCount=0&prepopulatedLoginId='
        
        # STEP 1: GET
        update_status('get_form')
        session = curl_requests.Session(impersonate="firefox")
        
        form = None
        for attempt in range(5):
            try:
                response_get = session.get(url_get, headers=headers_get, timeout=30)
                soup = BeautifulSoup(response_get.text, 'html.parser')
                form = soup.find('form', id='ap_register_form')
                if form:
                    break
            except:
                pass
            time.sleep(2)
        
        if not form:
            update_status('error_form')
            return False
        
        # Champs cachés
        hidden_fields = {}
        for inp in form.find_all('input', type='hidden'):
            name = inp.get('name')
            if name:
                hidden_fields[name] = inp.get('value', '')
        
        action_url = form.get('action')
        
        # Nom aléatoire
        first_names = ['Marie', 'Jean', 'Sophie', 'Pierre', 'Claire', 'Thomas', 'Julie', 'Lucas']
        last_names = ['Dupont', 'Martin', 'Durand', 'Bernard', 'Lefevre', 'Moreau', 'Simon', 'Laurent']
        customer_name = f'{random.choice(first_names)} {random.choice(last_names)}'
        
        # STEP 2: POST
        update_status('post_register')
        headers_post = dict(headers_get)
        headers_post['content-type'] = 'application/x-www-form-urlencoded'
        headers_post['origin'] = 'https://www.amazon.fr'
        
        post_data = dict(hidden_fields)
        post_data['email'] = email
        post_data['customerName'] = customer_name
        post_data['password'] = PASSWORD
        post_data['passwordCheck'] = PASSWORD
        if 'metadata1' not in post_data:
            post_data['metadata1'] = ''
        
        response_post = session.post(action_url, data=post_data, headers=headers_post, allow_redirects=False)
        
        # Suivre redirections
        while response_post.status_code in [301, 302, 303, 307]:
            location = response_post.headers.get('Location', '')
            if location.startswith('/'):
                location = f'https://www.amazon.fr{location}'
            response_post = session.get(location, headers=headers_get, allow_redirects=False)
        
        # STEP 3: CVF - Extraire URL captcha
        update_status('cvf_captcha')
        
        soup_cvf = BeautifulSoup(response_post.text, 'html.parser')
        cvf_url = response_post.url if hasattr(response_post, 'url') else ''
        
        # Extraire les données pour le captcha
        cvf_hidden_fields = {}
        form_cvf = soup_cvf.find('form')
        if form_cvf:
            for inp in form_cvf.find_all('input', type='hidden'):
                name = inp.get('name')
                if name:
                    cvf_hidden_fields[name] = inp.get('value', '')
        
        verify_token = cvf_hidden_fields.get('verifyToken', '')
        
        # Détecter arkose level
        arkose_level = 'L2'
        if 'arkose_level' in response_post.text:
            match = re.search(r'"arkose_level"\s*:\s*"([^"]+)"', response_post.text)
            if match:
                arkose_level = match.group(1)
        
        # Extraire session token et context
        amz_header = response_post.headers.get('amz-aamation-resp', '')
        session_token = ''
        client_side_context = ''
        
        if amz_header:
            try:
                amz_data = json.loads(amz_header)
                session_token = amz_data.get('sessionToken', '')
                client_side_context = amz_data.get('clientSideContext', '')
            except:
                pass
        
        # Extraire blob
        arkose_blob = ''
        blob_match = re.search(r'"arkose_blob"\s*:\s*"([^"]*)"', response_post.text)
        if blob_match:
            arkose_blob = blob_match.group(1)
        
        csrf_token = ''
        csrf_input = soup_cvf.find('input', {'name': 'anti-csrftoken-a2z'})
        if csrf_input:
            csrf_token = csrf_input.get('value', '')
        
        # Construire URL iframe Arkose
        arkose_options = {
            "mode": "lightbox",
            "isAudioRequired": True,
            "onComplete": {"type": "message"},
            "onReady": {"type": "message"},
            "onError": {"type": "message"},
            "onShown": {"type": "message"},
            "onSuppress": {"type": "message"},
            "scriptSource": {"type": "inline"}
        }
        
        arkose_iframe_url = f"https://client-api.arkoselabs.com/fc/assets/ec-game-core/game-core/1.26.0/standard/index.html?data=%7B%22blob%22%3A%22{quote(arkose_blob, safe='')}%22%7D&onComplete=parent.postMessage&onError=parent.postMessage&onReady=parent.postMessage&onShown=parent.postMessage&onSuppress=parent.postMessage&publicKey={ARKOSE_PUBLIC_KEY}"
        
        # Stocker les données de session
        with job_lock:
            current_job['session_data'] = {
                'session': session,
                'arkose_level': arkose_level,
                'arkose_session_token': session_token,
                'client_side_context': client_side_context,
                'arkose_options': arkose_options,
                'cvf_url': cvf_url,
                'cvf_hidden_fields': cvf_hidden_fields,
                'csrf_token': csrf_token,
                'verify_token': verify_token
            }
        
        # Envoyer l'URL du captcha au client
        update_status('waiting_captcha', arkose_iframe_url)
        
        # Attendre la résolution du captcha (max 5 minutes)
        start_wait = time.time()
        captcha_token = None
        
        while time.time() - start_wait < 300:
            with job_lock:
                if not current_job['waiting_for_captcha']:
                    captcha_token = current_job.get('captcha_token')
                    break
            time.sleep(0.5)
        
        if not captcha_token:
            update_status('error_captcha_timeout')
            return False
        
        # STEP 4: Soumettre captcha
        update_status('submitting_captcha')
        
        session_data = current_job['session_data']
        
        captcha_response = json.dumps({
            "challengeType": session_data['arkose_level'],
            "data": json.dumps({"sessionToken": captcha_token})
        })
        
        verify_captcha_url = f'https://www.amazon.fr/aaut/verify/cvf/{session_data["arkose_session_token"]}?context={quote(session_data["client_side_context"], safe="")}&options={quote(json.dumps(session_data["arkose_options"]))}&response={quote(captcha_response)}'
        
        headers_verify = {
            'accept': '*/*',
            'user-agent': headers_get['user-agent'],
            'anti-csrftoken-a2z': session_data['csrf_token'],
            'origin': 'https://www.amazon.fr',
            'Referer': session_data['cvf_url']
        }
        
        session.get(verify_captcha_url, headers=headers_verify)
        
        # POST final
        verify_post_data = {
            'cvf_aamation_response_token': session_data['arkose_session_token'],
            'cvf_captcha_captcha_action': 'verifyAamationChallenge',
            'cvf_aamation_error_code': '',
            'clientContext': session.cookies.get('session-id', ''),
            'openid.pape.max_auth_age': '0',
            'openid.return_to': 'https://www.amazon.fr/',
            'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
            'openid.assoc_handle': 'frflex',
            'openid.mode': 'checkid_setup',
            'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
            'openid.ns': 'http://specs.openid.net/auth/2.0',
            'verifyToken': session_data['verify_token']
        }
        
        headers_post_final = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.amazon.fr',
            'user-agent': headers_get['user-agent']
        }
        
        response_final = session.post('https://www.amazon.fr/ap/cvf/verify', data=verify_post_data, headers=headers_post_final, allow_redirects=True)
        
        # STEP 5: Email OTP
        if 'transactionId' in response_final.text or 'code' in response_final.text.lower():
            update_status('waiting_email_otp')
            
            otp = get_otp_from_email(email)
            
            if otp:
                update_status('submitting_email_otp')
                
                soup = BeautifulSoup(response_final.text, 'html.parser')
                verify_token = ''
                form_otp = soup.find('form', class_='cvf-widget-form')
                if form_otp:
                    verify_input = form_otp.find('input', {'name': 'verifyToken'})
                    if verify_input:
                        verify_token = verify_input.get('value', '')
                
                if not verify_token:
                    match = re.search(r'name="verifyToken"\s+value="([^"]+)"', response_final.text)
                    if match:
                        verify_token = match.group(1)
                
                otp_data = {
                    'action': 'code',
                    'openid.assoc_handle': 'frflex',
                    'openid.mode': 'checkid_setup',
                    'openid.ns': 'http://specs.openid.net/auth/2.0',
                    'verifyToken': verify_token,
                    'code': otp,
                    'metadata1': '',
                    'language': 'fr'
                }
                
                response_otp = session.post('https://www.amazon.fr/ap/cvf/verify', data=otp_data, headers=headers_post_final, allow_redirects=True)
                response_final = response_otp
        
        # STEP 6: SMS OTP
        update_status('sms_verification')
        
        for sms_attempt in range(5):
            update_status(f'sms_attempt_{sms_attempt + 1}')
            
            phone_data = get_french_number()
            if not phone_data:
                time.sleep(2)
                continue
            
            # Extraire verifyToken
            soup = BeautifulSoup(response_final.text, 'html.parser')
            verify_token = ''
            verify_input = soup.find('input', {'name': 'verifyToken'})
            if verify_input:
                verify_token = verify_input.get('value', '')
            
            # Soumettre numéro
            phone_post_data = {
                'openid.assoc_handle': 'frflex',
                'openid.mode': 'checkid_setup',
                'openid.ns': 'http://specs.openid.net/auth/2.0',
                'verifyToken': verify_token,
                'cvf_phone_cc': 'FR',
                'cvf_phone_num': phone_data['phone_without_country'],
                'cvf_action': 'collect'
            }
            
            headers_phone = {
                'Host': 'www.amazon.fr',
                'User-Agent': headers_get['user-agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.amazon.fr',
                'Referer': 'https://www.amazon.fr/ap/cvf/verify'
            }
            
            response_phone = session.post('https://www.amazon.fr/ap/cvf/verify', data=phone_post_data, headers=headers_phone, allow_redirects=True)
            
            # Vérifier acceptation
            if 'id="cvf-input-code"' not in response_phone.text:
                continue
            
            set_sms_status_ready(phone_data['activation_id'])
            
            update_status('waiting_sms_otp')
            sms_otp = get_sms_otp(phone_data['activation_id'], max_wait=60)
            
            if not sms_otp:
                continue
            
            update_status('submitting_sms_otp')
            
            # Soumettre SMS OTP
            soup = BeautifulSoup(response_phone.text, 'html.parser')
            verify_input = soup.find('input', {'name': 'verifyToken'})
            if verify_input:
                verify_token = verify_input.get('value', '')
            
            sms_data = [
                ('verificationPageContactType', 'sms'),
                ('openid.assoc_handle', 'frflex'),
                ('openid.mode', 'checkid_setup'),
                ('openid.ns', 'http://specs.openid.net/auth/2.0'),
                ('verifyToken', verify_token),
                ('code', sms_otp),
                ('cvf_action', 'code'),
                ('resendContactType', 'sms'),
                ('resendContactType', 'sms')
            ]
            
            response_sms = session.post('https://www.amazon.fr/ap/cvf/verify', data=sms_data, headers=headers_phone, allow_redirects=True)
            
            # Succès!
            if response_sms.status_code == 200 or 'session-id' in str(session.cookies):
                update_status('saving_account')
                
                cookies_dict = dict(session.cookies)
                if save_account(email, PASSWORD, cookies_dict):
                    remove_email(email)
                    update_status('success')
                    return True
        
        update_status('failed')
        return False
        
    except Exception as e:
        update_status(f'error: {str(e)}')
        return False
    finally:
        with job_lock:
            current_job['active'] = False
            current_job['waiting_for_captcha'] = False

# ============== ROUTES ==============
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Amazon Generator",
        "short_name": "AmazonGen",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#ff6b35",
        "icons": [
            {"src": "/static/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/static/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"}
        ]
    })

@app.route('/api/stats')
def get_stats():
    return jsonify({
        'emails_remaining': get_emails_count(),
        'active': current_job['active'],
        'status': current_job['status'],
        'current_email': current_job['email']
    })

@app.route('/api/emails', methods=['POST'])
def add_emails():
    """Ajouter des emails à PostgreSQL"""
    try:
        emails_text = request.form.get('emails', '') or request.data.decode('utf-8')
        
        if 'file' in request.files:
            file = request.files['file']
            emails_text = file.read().decode('utf-8')
        
        new_emails = [e.strip() for e in emails_text.split('\n') if e.strip() and '@' in e]
        
        if not new_emails:
            return jsonify({'error': 'Aucun email valide trouvé'}), 400
        
        # Ajouter à PostgreSQL
        added = add_emails_to_db(new_emails)
        
        return jsonify({'success': True, 'added': added, 'total': get_emails_count()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/accounts')
def get_accounts():
    """Liste des comptes créés depuis PostgreSQL"""
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

@app.route('/api/start', methods=['POST'])
def start_generation():
    global current_job
    
    with job_lock:
        if current_job['active']:
            return jsonify({'error': 'Une génération est déjà en cours'}), 400
        
        email = get_random_email()
        if not email:
            return jsonify({'error': 'Plus d\'emails disponibles'}), 400
        
        current_job = {
            'active': True,
            'email': email,
            'status': 'starting',
            'captcha_url': None,
            'session_data': None,
            'waiting_for_captcha': False,
            'captcha_token': None
        }
    
    # Lancer le thread de génération
    thread = threading.Thread(target=generate_account_thread, args=(email,))
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'email': email})

# ============== SOCKET.IO ==============
@socketio.on('connect')
def handle_connect():
    emit('connected', {'status': 'ok'})
    emit('stats', {
        'emails_remaining': get_emails_count(),
        'active': current_job['active'],
        'status': current_job['status']
    })

@socketio.on('captcha_solved')
def handle_captcha_solved(data):
    global current_job
    token = data.get('token', '')
    
    with job_lock:
        if current_job['waiting_for_captcha']:
            current_job['captcha_token'] = token
            current_job['waiting_for_captcha'] = False
    
    emit('captcha_received', {'success': True})

@socketio.on('get_status')
def handle_get_status():
    emit('status_update', {
        'status': current_job['status'],
        'email': current_job['email'],
        'captcha_url': current_job['captcha_url'],
        'active': current_job['active']
    })

# ============== MAIN ==============
# Initialiser la base de données au démarrage
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
