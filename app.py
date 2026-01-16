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

# Import captcha solver
try:
    from captcha_solver import start_captcha_solver, click_captcha, get_captcha_state, stop_captcha_solver
    PLAYWRIGHT_AVAILABLE = True
except:
    PLAYWRIGHT_AVAILABLE = False
    print("Playwright not available, using fallback mode")

PASSWORD = os.environ.get('AMAZON_PASSWORD', 'Faure02112002@')
IMAP_SERVER = os.environ.get('IMAP_SERVER', 'imap.mail.me.com')
IMAP_PORT = int(os.environ.get('IMAP_PORT', '993'))
IMAP_USER = os.environ.get('IMAP_USER', '')
IMAP_PASSWORD = os.environ.get('IMAP_PASSWORD', '')
HEROSMS_API_KEY = os.environ.get('HEROSMS_API_KEY', '')
HEROSMS_BASE_URL = 'https://hero-sms.com/stubs/handler_api.php'
DATABASE_URL = os.environ.get('DATABASE_URL', '')
FIRST_NAMES = ['Marie', 'Jean', 'Sophie', 'Pierre', 'Claire', 'Thomas', 'Julie', 'Lucas', 'Emma', 'Hugo']
LAST_NAMES = ['Dupont', 'Martin', 'Durand', 'Bernard', 'Lefevre', 'Moreau', 'Simon', 'Laurent', 'Michel', 'Garcia']
# Proxies rotation
PROXIES = [
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-av0c62v3-duration-60',
    'isp.oxylabs.io:8001:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8002:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8003:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8004:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8005:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8006:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8007:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8008:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8009:aigrinch_NvNti:Faure02112002=',
    'isp.oxylabs.io:8010:aigrinch_NvNti:Faure02112002=',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-j4k6b5tp-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-o0lai4ly-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-kkwg8a1c-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-jdw8z84m-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-eml3gzyb-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-7lnzawnd-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-ytfm96h4-duration-60',
    'resi.thexyzstore.com:8000:aigrinchxyz:8jqb7dml-country-FR-hardsession-jyjvlxbe-duration-60',
]

def get_random_proxy():
    proxy_line = random.choice(PROXIES)
    parts = proxy_line.split(':')
    if len(parts) >= 4:
        host, port, user, pwd = parts[0], parts[1], parts[2], ':'.join(parts[3:])
        proxy_url = f'http://{user}:{pwd}@{host}:{port}'
        return {'http': proxy_url, 'https': proxy_url}
    return None



def should_continue(expected_email):
    """Vérifie si la génération doit continuer (même email, toujours active)"""
    with state_lock:
        return generation_state['active'] and generation_state.get('email') == expected_email

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'amazon-secret')

generation_state = {'active': False, 'step': 'idle', 'email': None, 'customer_name': None, 'logs': [], 'captcha_url': None, 'captcha_token': None, 'session_data': None, 'error': None}
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
        cur.execute('CREATE TABLE IF NOT EXISTS emails (id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, used BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        cur.execute('CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL, cookies TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        conn.commit(); cur.close(); conn.close()
    except: pass

def get_emails_count():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("SELECT COUNT(*) as count FROM emails WHERE used = FALSE"); result = cur.fetchone(); cur.close(); conn.close()
            return result['count'] if result else 0
        except: pass
    return 0

def get_accounts_count():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("SELECT COUNT(*) as count FROM accounts"); result = cur.fetchone(); cur.close(); conn.close()
            return result['count'] if result else 0
        except: pass
    return 0

def get_random_email():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("SELECT email FROM emails WHERE used = FALSE ORDER BY RANDOM() LIMIT 1"); result = cur.fetchone(); cur.close(); conn.close()
            return result['email'] if result else None
        except: pass
    return None

def mark_email_used(email_addr):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("UPDATE emails SET used = TRUE WHERE email = %s", (email_addr,)); conn.commit(); cur.close(); conn.close()
        except: pass

def save_account_db(email_addr, password, cookies_dict):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor()
            cookies_json = json.dumps(cookies_dict) if cookies_dict else '{}'
            cur.execute('INSERT INTO accounts (email, password, cookies) VALUES (%s, %s, %s) ON CONFLICT (email) DO UPDATE SET password = EXCLUDED.password, cookies = EXCLUDED.cookies', (email_addr, password, cookies_json))
            conn.commit(); cur.close(); conn.close()
            return True
        except: pass
    return False

def add_emails_to_db(emails_list):
    conn = get_db()
    if not conn: return 0
    try:
        cur = conn.cursor(); added = 0
        for em in emails_list:
            try: cur.execute("INSERT INTO emails (email) VALUES (%s) ON CONFLICT DO NOTHING", (em,)); added += cur.rowcount
            except: pass
        conn.commit(); cur.close(); conn.close(); return added
    except: return 0

def get_all_accounts():
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("SELECT id, email, password, cookies, created_at FROM accounts ORDER BY created_at DESC"); results = cur.fetchall(); cur.close(); conn.close()
            return results
        except: pass
    return []

def get_account_by_id(account_id):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("SELECT id, email, password, cookies FROM accounts WHERE id = %s", (account_id,)); result = cur.fetchone(); cur.close(); conn.close()
            return result
        except: pass
    return None

def delete_account_by_id(account_id):
    conn = get_db()
    if conn:
        try:
            cur = conn.cursor(); cur.execute("DELETE FROM accounts WHERE id = %s", (account_id,)); conn.commit(); cur.close(); conn.close()
            return True
        except: pass
    return False

def add_log(message, log_type='info'):
    with state_lock:
        generation_state['logs'].append({'time': time.strftime('%H:%M:%S'), 'type': log_type, 'message': message})
        if len(generation_state['logs']) > 100: generation_state['logs'] = generation_state['logs'][-100:]
    import sys
    print(f"[{log_type.upper()}] {message}", flush=True)
    sys.stdout.flush()

def set_step(step):
    with state_lock: generation_state['step'] = step

def generate_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def get_french_number():
    add_log(f'Hero SMS: getting number...', 'info')
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=getNumberV2&service=am&country=78'
    try:
        response = requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'}, timeout=30)
        add_log(f'Hero SMS resp: {response.status_code} - {response.text[:100]}', 'info')
        if response.status_code == 200:
            data = response.json()
            activation_id = data.get('activationId'); phone_number = str(data.get('phoneNumber', ''))
            if activation_id and phone_number:
                phone_without_country = phone_number[2:] if phone_number.startswith('33') else phone_number
                return {'activation_id': activation_id, 'phone_number': phone_number, 'phone_without_country': phone_without_country}
    except Exception as e: add_log(f'Hero SMS error: {str(e)[:50]}', 'error')
    return None

def set_sms_status_ready(activation_id):
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=setStatus&status=1&id={activation_id}'
    try:
        response = requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'})
        add_log(f'SMS status ready: {response.text}', 'info')
        return response.text.strip() == 'ACCESS_READY'
    except: return False

def get_sms_otp(activation_id, max_wait=60, check_interval=2):
    url = f'{HEROSMS_BASE_URL}?api_key={HEROSMS_API_KEY}&action=getStatus&id={activation_id}'
    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(url, headers={'accept': '*/*', 'user-agent': 'node'})
            result = response.text.strip()
            add_log(f'SMS check: {result}', 'info')
            if result.startswith('STATUS_OK:'): return result.split(':')[1]
        except: pass
        time.sleep(check_interval)
    return None

def get_otp_from_email(target_email, max_wait=120, check_interval=5):
    add_log(f'IMAP: checking for OTP to {target_email}...', 'info')
    time.sleep(5)
    target_local = target_email.split('@')[0].lower()
    start_time = time.time()
    while time.time() - start_time < max_wait:
        # Check if generation was stopped or email changed
        with state_lock:
            current_email = generation_state.get('email')
            if not generation_state['active'] or current_email != target_email:
                add_log('IMAP: Generation stopped or email changed, aborting', 'warning')
                return None
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
            mail.login(IMAP_USER, IMAP_PASSWORD)
            mail.select('INBOX')
            _, messages = mail.search(None, '(UNSEEN)')
            email_ids = messages[0].split() if messages[0] else []
            add_log(f'IMAP: {len(email_ids)} unread', 'info')
            if email_ids:
                for email_id in reversed(email_ids[-20:]):
                    _, msg_data = mail.fetch(email_id, '(BODY.PEEK[])')
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email_module.message_from_bytes(response_part[1])
                            from_addr = msg.get('From', '').lower()
                            to_addr = msg.get('To', '').lower()
                            if 'amazon' in from_addr:
                                add_log(f'IMAP: Amazon email found, To: {to_addr[:30]}', 'info')
                                body = ''
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() in ['text/plain', 'text/html']:
                                            payload = part.get_payload(decode=True)
                                            if payload: body = payload.decode('utf-8', errors='ignore'); break
                                else:
                                    payload = msg.get_payload(decode=True)
                                    if payload: body = payload.decode('utf-8', errors='ignore')
                                is_for_target = target_email.lower() in to_addr or target_local in body.lower()
                                if is_for_target:
                                    otp_match = re.search(r'\b(\d{6})\b', body)
                                    if otp_match:
                                        mail.store(email_id, '+FLAGS', '\\Seen')
                                        mail.logout()
                                        add_log(f'IMAP: OTP found!', 'success')
                                        return otp_match.group(1)
            mail.logout()
        except Exception as e: add_log(f'IMAP error: {str(e)[:40]}', 'warning')
        time.sleep(check_interval)
    return None

def get_headers_get():
    return {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'accept-encoding': 'gzip, deflate, br',
        'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    }

def get_headers_post(referer):
    h = get_headers_get()
    h['content-type'] = 'application/x-www-form-urlencoded'
    h['origin'] = 'https://www.amazon.fr'
    h['Referer'] = referer
    h['sec-fetch-site'] = 'same-origin'
    return h

def get_headers_firefox():
    return {'Host': 'www.amazon.fr', 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3', 'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://www.amazon.fr', 'Referer': 'https://www.amazon.fr/ap/cvf/verify', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'same-origin'}

def submit_phone_number(session, phone_without_33, verify_token):
    add_log(f'Submitting phone: {phone_without_33}', 'info')
    post_data = {'openid.assoc_handle': 'frflex', 'openid.mode': 'checkid_setup', 'openid.ns': 'http://specs.openid.net/auth/2.0', 'verifyToken': verify_token, 'cvf_phone_cc': 'FR', 'cvf_phone_num': phone_without_33, 'cvf_action': 'collect'}
    response = session.post('https://www.amazon.fr/ap/cvf/verify', data=post_data, headers=get_headers_firefox(), allow_redirects=True, timeout=30)
    add_log(f'Phone submit: {response.status_code}', 'info')
    soup = BeautifulSoup(response.text, 'html.parser')
    vi = soup.find('input', {'name': 'verifyToken'})
    new_vt = vi.get('value', '') if vi else verify_token
    return response, new_vt

def submit_sms_otp(session, otp_code, verify_token):
    add_log(f'Submitting SMS OTP: {otp_code}', 'info')
    post_data = [('verificationPageContactType', 'sms'), ('openid.assoc_handle', 'frflex'), ('openid.mode', 'checkid_setup'), ('openid.ns', 'http://specs.openid.net/auth/2.0'), ('verifyToken', verify_token), ('code', otp_code), ('cvf_action', 'code')]
    headers = get_headers_firefox()
    response = session.post('https://www.amazon.fr/ap/cvf/verify', data=post_data, headers=headers, allow_redirects=False, timeout=30)
    add_log(f'SMS OTP submit: {response.status_code}', 'info')
    if response.status_code == 302:
        loc1 = response.headers.get('Location', '')
        add_log(f'SMS redirect: {loc1[:60]}', 'info')
        if loc1:
            if loc1.startswith('/'): loc1 = f'https://www.amazon.fr{loc1}'
            hg = {k: v for k, v in headers.items() if k != 'Content-Type'}
            r2 = session.get(loc1, headers=hg, allow_redirects=False, timeout=30)
            if r2.status_code == 302:
                loc2 = r2.headers.get('Location', '')
                if 'new_account=1' in loc2:
                    if loc2.startswith('/'): loc2 = f'https://www.amazon.fr{loc2}'
                    return session.get(loc2, headers=hg, allow_redirects=True, timeout=30)
    return response

def remove_phone_number(session):
    add_log('Removing phone number...', 'info')
    headers = get_headers_get()
    try:
        session.get('https://www.amazon.fr/ax/account/manage', headers=headers, allow_redirects=True, timeout=30)
        url_1 = 'https://www.amazon.fr/ap/profile/mobilephone?openid.mode=checkid_setup&ref_=ax_am_landing_change_mobile&openid.assoc_handle=frflex&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&referringAppAction=CNEP'
        r1 = session.get(url_1, headers=headers, allow_redirects=True, timeout=30)
        add_log(f'Phone page: {r1.status_code}', 'info')
        if r1.status_code != 200: return False
        soup = BeautifulSoup(r1.text, 'html.parser')
        form = soup.find('form', id='auth-remove-phone-claim')
        if not form:
            for f in soup.find_all('form'):
                if 'mobilephone' in f.get('action', ''): form = f; break
        if not form: 
            add_log('Remove phone form not found', 'warning')
            return False
        hf = {}
        for inp in form.find_all('input', type='hidden'):
            n = inp.get('name'); v = inp.get('value', '')
            if n: hf[n] = v
        aat = hf.get('appActionToken', ''); ws = hf.get('workflowState', ''); pr = hf.get('prevRID', '')
        if not aat or not ws: return False
        pd = {'appActionToken': aat, 'appAction': 'REMOVE_MOBILE_PHONE', 'prevRID': pr, 'workflowState': ws, 'deleteMobilePhone': 'irrelevant'}
        hp = get_headers_post('https://www.amazon.fr/ap/profile/mobilephone')
        r2 = session.post('https://www.amazon.fr/ap/profile/mobilephone', data=pd, headers=hp, allow_redirects=False, timeout=30)
        add_log(f'Remove POST: {r2.status_code}', 'info')
        if r2.status_code != 302: return False
        loc2 = r2.headers.get('Location', '')
        if not loc2: return False
        if loc2.startswith('/'): url_3 = f'https://www.amazon.fr{loc2}'
        else: url_3 = loc2
        r3 = session.get(url_3, headers=headers, allow_redirects=False, timeout=30)
        if r3.status_code != 302: return False
        loc3 = r3.headers.get('Location', '')
        if 'SUCCESS_REMOVE_MOBILE_CLAIM' in loc3:
            add_log('Phone removed!', 'success')
            return True
        return False
    except Exception as e:
        add_log(f'Remove phone error: {str(e)[:40]}', 'error')
        return False

def submit_otp_code(session, otp_code, response_html):
    add_log(f'Submitting email OTP: {otp_code}', 'info')
    soup = BeautifulSoup(response_html, 'html.parser')
    vt = ''
    fo = soup.find('form', class_='cvf-widget-form')
    if not fo: fo = soup.find('form', attrs={'action': lambda x: x and 'verify' in str(x)})
    if fo:
        vi = fo.find('input', {'name': 'verifyToken'})
        if vi: vt = vi.get('value', '')
    if not vt:
        m = re.search(r'name="verifyToken"\s+value="([^"]+)"', response_html)
        if m: vt = m.group(1)
    add_log(f'verifyToken for OTP: {vt[:30]}...', 'info')
    pd = {'action': 'code', 'openid.assoc_handle': 'frflex', 'openid.mode': 'checkid_setup', 'openid.ns': 'http://specs.openid.net/auth/2.0', 'verifyToken': vt, 'code': otp_code, 'metadata1': '', 'language': 'fr'}
    resp = session.post('https://www.amazon.fr/ap/cvf/verify', data=pd, headers=get_headers_post('https://www.amazon.fr/ap/cvf/verify'), allow_redirects=True, timeout=30)
    add_log(f'OTP submit: {resp.status_code}, URL: {resp.url[:50]}', 'info')
    return resp

def run_generation():
    global generation_state
    try:
        add_log('=== STARTING GENERATION ===', 'info')
        set_step('init')
        email_addr = get_random_email()
        if not email_addr:
            add_log('No email available!', 'error'); set_step('error'); return
        customer_name = generate_name()
        with state_lock:
            generation_state['email'] = email_addr
            generation_state['customer_name'] = customer_name
        add_log(f'Email: {email_addr}', 'info')
        add_log(f'Name: {customer_name}', 'info')
        session = requests.Session()
        
        # Apply random proxy
        proxy = get_random_proxy()
        if proxy:
            session.proxies = proxy
            add_log(f'Proxy: {proxy["http"].split("@")[1]}', 'info')
        
        # STEP 1: GET registration form
        set_step('get_form')
        add_log('GET registration form...', 'info')
        url_get = 'https://www.amazon.fr/ap/register?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.fr%2F&openid.assoc_handle=frflex&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.ns.pape=http%3A%2F%2Fspecs.openid.net%2Fextensions%2Fpape%2F1.0&pageId=frflex'
        rg = None
        for attempt in range(3):
            if not should_continue(email_addr): 
                add_log('Generation stopped', 'warning'); return
            try:
                # Nouveau proxy à chaque retry
                if attempt > 0:
                    proxy = get_random_proxy()
                    if proxy:
                        session.proxies = proxy
                        add_log(f'Retry with proxy: {proxy["http"].split("@")[1]}', 'info')
                rg = session.get(url_get, headers=get_headers_get(), timeout=30)
                add_log(f'GET form: {rg.status_code}', 'info')
                if rg.status_code == 200 and 'ap_register_form' in rg.text: break
            except Exception as e:
                add_log(f'GET error: {str(e)[:30]}', 'warning')
                time.sleep(2)
        else:
            add_log('GET form failed', 'error'); set_step('error'); return
        if not rg:
            add_log('No response', 'error'); set_step('error'); return
        
        soup = BeautifulSoup(rg.text, "html.parser")
        
        # Debug: log page info
        title = soup.find("title")
        add_log(f'Page title: {title.text[:40] if title else "NA"}', 'info')
        add_log(f'Final URL: {rg.url[:50]}', 'info')
        form = soup.find('form', id='ap_register_form')
        if not form:
            add_log('Form not found!', 'error'); set_step('error'); return
        add_log('Form OK!', 'success')
        
        hf = {}
        for inp in form.find_all('input', type='hidden'):
            n = inp.get('name'); v = inp.get('value', '')
            if n: hf[n] = v
        add_log(f'Hidden fields: {len(hf)}', 'info')
        
        action_url = form.get('action')
        if not action_url.startswith('http'): action_url = f'https://www.amazon.fr{action_url}'
        
        # STEP 2: POST registration
        set_step('post_register')
        add_log('POST registration...', 'info')
        pd = hf.copy()
        pd['email'] = email_addr; pd['customerName'] = customer_name; pd['password'] = PASSWORD; pd['passwordCheck'] = PASSWORD
        if 'metadata1' not in pd: pd['metadata1'] = ''
        
        rp = session.post(action_url, data=pd, headers=get_headers_post(url_get), allow_redirects=False, timeout=30)
        add_log(f'POST: {rp.status_code}, Location: {rp.headers.get("Location", "N/A")[:50]}', 'info')
        
        if rp.status_code != 302:
            add_log(f'Expected 302, got {rp.status_code}', 'error')
            add_log(f'Response: {rp.text[:200]}', 'info')
            set_step('error'); return
        
        # STEP 3: Follow CVF redirect
        set_step('cvf')
        loc = rp.headers.get('Location', '')
        add_log(f'CVF redirect: {loc[:60]}', 'info')
        if loc.startswith('/'): cvf_url = f'https://www.amazon.fr{loc}'
        else: cvf_url = loc
        
        rc = session.get(cvf_url, headers=get_headers_get(), timeout=30)
        add_log(f'CVF page: {rc.status_code}', 'info')
        
        am = re.search(r'ARKOSE_LEVEL_(\d)', rc.text)
        arkose_level = f'ARKOSE_LEVEL_{am.group(1)}' if am else 'ARKOSE_LEVEL_4'
        add_log(f'Arkose level: {arkose_level}', 'info')
        
        soup_cvf = BeautifulSoup(rc.text, 'html.parser')
        fcvf = soup_cvf.find('form', id='cvf-aamation-challenge-form')
        cvf_hf = {}
        if fcvf:
            for inp in fcvf.find_all('input', type='hidden'):
                n = inp.get('name'); v = inp.get('value', '')
                if n: cvf_hf[n] = v
        add_log(f'CVF hidden fields: {len(cvf_hf)}', 'info')
        
        # STEP 4: GET Arkose page
        set_step('arkose')
        add_log('GET Arkose page...', 'info')
        session_id = session.cookies.get('session-id', '')
        add_log(f'Session ID: {session_id[:20]}...', 'info')
        
        ao = {"clientData": json.dumps({"sessionId": session_id, "marketplaceId": "A13V1IB3VIYZZH", "clientUseCase": "/ap/register"}), "challengeType": arkose_level, "locale": "fr-FR", "externalId": ''.join(random.choices(string.ascii_uppercase + string.digits, k=20)), "enableHeaderFooter": False, "enableBypassMechanism": False, "enableModalView": False}
        ark_url = f'https://www.amazon.fr/aaut/verify/cvf?options={quote(json.dumps(ao))}'
        
        ha = get_headers_get(); ha['Referer'] = cvf_url
        ra = session.get(ark_url, headers=ha, timeout=30)
        add_log(f'Arkose page: {ra.status_code}', 'info')
        
        aar = ra.headers.get('amz-aamation-resp', '')
        ast = ''; csc = ''
        if aar:
            try:
                ad = json.loads(aar)
                ast = ad.get('sessionToken', '')
                csc = ad.get('clientSideContext', '')
                add_log(f'Arkose sessionToken: {ast[:30]}...', 'info')
            except: add_log('Failed to parse amz-aamation-resp', 'warning')
        else:
            add_log('No amz-aamation-resp header!', 'warning')
        
        soup_a = BeautifulSoup(ra.text, 'html.parser')
        iframe = soup_a.find('iframe', id='aacb-arkose-frame')
        aiu = None
        if iframe: aiu = iframe.get('src', '')
        if not aiu:
            m = re.search(r'src="(https://iframe\.arkoselabs\.com/[^"]+)"', ra.text)
            if m: aiu = m.group(1)
        if not aiu:
            add_log('Arkose iframe URL not found!', 'error')
            add_log(f'Page content: {ra.text[:300]}', 'info')
            set_step('error'); return
        add_log(f'Arkose iframe: {aiu[:60]}...', 'success')
        
        cm = soup_a.find('meta', attrs={'name': 'csrf-token'})
        csrf = cm.get('content', '') if cm else ''
        add_log(f'CSRF token: {csrf[:20]}...', 'info')
        
        with state_lock:
            generation_state['captcha_url'] = aiu
            generation_state['session_data'] = {'session': session, 'cvf_url': cvf_url, 'arkose_session_token': ast, 'client_side_context': csc, 'csrf_token': csrf, 'verify_token': cvf_hf.get('verifyToken', ''), 'arkose_options': ao, 'arkose_level': arkose_level, 'session_id': session_id}
        
        # STEP 5: Wait for captcha
        set_step('waiting_captcha')
        add_log('=== SOLVE THE CAPTCHA ===', 'warning')
        
        sw = time.time()
        while time.time() - sw < 300:
            if not should_continue(email_addr):
                add_log('Generation stopped', 'warning'); return
            # Check captcha solver state for token
            if PLAYWRIGHT_AVAILABLE:
                solver_state = get_captcha_state()
                if solver_state['token'] and solver_state['solved']:
                    with state_lock:
                        generation_state['captcha_token'] = solver_state['token']
                    add_log('Token captured from Playwright solver!', 'success')
                    break
            with state_lock:
                if generation_state['captcha_token']: break
                if not generation_state['active']: add_log('Cancelled', 'warning'); return
            time.sleep(1)
        
        with state_lock:
            ct = generation_state['captcha_token']
            sd = generation_state['session_data']
        
        if not ct:
            add_log('Captcha timeout (5min)', 'error'); set_step('error'); return
        
        add_log('Captcha received!', 'success')
        add_log(f'Token: {ct[:60]}...', 'info')
        
        session = sd['session']
        
        # Check if manual token
        if ct.startswith('MANUAL_CONFIRM'):
            add_log('Manual token - may not work with Amazon', 'warning')
        
        # STEP 6: Submit captcha
        set_step('submit_captcha')
        add_log('Submitting captcha to Amazon...', 'info')
        
        cr = json.dumps({"challengeType": sd['arkose_level'], "data": json.dumps({"sessionToken": ct})})
        vcu = f"https://www.amazon.fr/aaut/verify/cvf/{sd['arkose_session_token']}?context={quote(sd['client_side_context'], safe='')}&options={quote(json.dumps(sd['arkose_options']))}&response={quote(cr)}"
        
        add_log(f'Verify URL: {vcu[:80]}...', 'info')
        
        hv = get_headers_get()
        hv['anti-csrftoken-a2z'] = sd['csrf_token']
        hv['Referer'] = sd['cvf_url']
        hv['accept'] = '*/*'
        
        rv = session.get(vcu, headers=hv, timeout=30)
        add_log(f'Verify response: {rv.status_code}', 'info')
        add_log(f'Verify body: {rv.text[:150]}...', 'info')
        
        # STEP 7: POST finalize
        set_step('finalize')
        add_log('POST /ap/cvf/verify finalize...', 'info')
        add_log(f'verifyToken: {sd["verify_token"][:40]}...', 'info')
        
        vpd = {
            'cvf_aamation_response_token': sd['arkose_session_token'],
            'cvf_captcha_captcha_action': 'verifyAamationChallenge',
            'cvf_aamation_error_code': '',
            'clientContext': sd['session_id'],
            'openid.assoc_handle': 'frflex',
            'openid.mode': 'checkid_setup',
            'openid.ns': 'http://specs.openid.net/auth/2.0',
            'verifyToken': sd['verify_token']
        }
        
        rf = session.post('https://www.amazon.fr/ap/cvf/verify', data=vpd, headers=get_headers_post(sd['cvf_url']), allow_redirects=False, timeout=30)
        add_log(f'POST finalize: {rf.status_code}', 'info')
        add_log(f'Location: {rf.headers.get("Location", "N/A")[:60]}', 'info')
        
        # STEP 8: Follow redirects
        if rf.status_code == 302:
            fl = rf.headers.get('Location', '')
            add_log(f'Redirect 1: {fl[:60]}', 'info')
            if fl.startswith('/'): fu = f'https://www.amazon.fr{fl}'
            else: fu = fl
            
            rcl = session.get(fu, headers=get_headers_get(), allow_redirects=False, timeout=30)
            add_log(f'GET redirect 1: {rcl.status_code}', 'info')
            
            if rcl.status_code == 302:
                cr2 = rcl.headers.get('Location', '')
                add_log(f'Redirect 2: {cr2[:60]}', 'info')
                if cr2.startswith('/'): cu2 = f'https://www.amazon.fr{cr2}'
                else: cu2 = cr2
                rev = session.get(cu2, headers=get_headers_get(), timeout=30)
                add_log(f'GET redirect 2: {rev.status_code}', 'info')
            else:
                rev = rcl
        else:
            rev = rf
            add_log(f'No redirect, status: {rf.status_code}', 'warning')
        
        # Analyze final page
        add_log(f'Final URL: {rev.url[:60]}', 'info')
        soup_final = BeautifulSoup(rev.text, 'html.parser')
        title = soup_final.find('title')
        add_log(f'Page title: {title.text if title else "N/A"}', 'info')
        
        has_otp_msg = 'nous avons envoyé un code' in rev.text.lower()
        has_cvf = 'cvf' in rev.url.lower()
        has_error = 'erreur' in rev.text.lower() or 'error' in rev.text.lower()
        
        add_log(f'Has OTP msg: {has_otp_msg}, Has CVF: {has_cvf}, Has error: {has_error}', 'info')
        
        if has_otp_msg or has_cvf:
            # STEP 9: Email OTP
            set_step('email_otp')
            add_log('=== EMAIL OTP ===', 'info')
            add_log('Waiting for OTP email...', 'info')
            
            otp = get_otp_from_email(email_addr, max_wait=120, check_interval=5)
            if otp:
                add_log(f'OTP received: {otp}', 'success')
                rotp = submit_otp_code(session, otp, rev.text)
                
                add_log(f'OTP response URL: {rotp.url[:60]}', 'info')
                add_log(f'OTP response: {rotp.text[:150]}...', 'info')
                
                if 'Add mobile' in rotp.text or 'mobile number' in rotp.text.lower() or 'cvf_phone' in rotp.text:
                    add_log('Email verified! Now SMS...', 'success')
                    
                    # STEP 10: SMS verification
                    set_step('sms_otp')
                    sp = BeautifulSoup(rotp.text, 'html.parser')
                    vti = sp.find('input', {'name': 'verifyToken'})
                    vts = vti.get('value', '') if vti else ''
                    
                    if vts:
                        add_log(f'SMS verifyToken: {vts[:30]}...', 'info')
                        add_log('Adding phone number...', 'info')
                        time.sleep(5)  # 5s comme bot manuel
                        
                        sms_ok = False
                        for sa in range(5):
                            add_log(f'SMS attempt {sa+1}/5...', 'info')
                            pd = get_french_number()
                            if not pd:
                                add_log('No phone number available', 'warning')
                                time.sleep(2)
                                continue
                            
                            aid = pd['activation_id']
                            pw33 = pd['phone_without_country']
                            add_log(f'Phone: +33{pw33}', 'info')
                            
                            rph, nvt = submit_phone_number(session, pw33, vts)
                            add_log(f'Phone submit response: {rph.text[:100]}...', 'info')
                            
                            if 'id="cvf-input-code"' in rph.text:
                                add_log('Phone accepted! Waiting for SMS...', 'success')
                                set_sms_status_ready(aid)
                                sotp = get_sms_otp(aid, max_wait=60, check_interval=2)
                                
                                if sotp:
                                    add_log(f'SMS OTP: {sotp}', 'success')
                                    rsms = submit_sms_otp(session, sotp, nvt)
                                    add_log('SMS verified!', 'success')
                                    
                                    # STEP 11: Remove phone
                                    set_step('remove_phone')
                                    remove_phone_number(session)
                                    
                                    # STEP 12: Save account
                                    set_step('save_account')
                                    cd = dict(session.cookies)
                                    save_account_db(email_addr, PASSWORD, cd)
                                    mark_email_used(email_addr)
                                    
                                    add_log('=== ACCOUNT CREATED! ===', 'success')
                                    add_log(f'{email_addr}', 'success')
                                    set_step('success')
                                    sms_ok = True
                                    break  # Succès
                                else:
                                    add_log('SMS not received', 'warning')
                            elif 'cvf-number-blocked' in rph.text or 'activité inhabituelle' in rph.text:
                                add_log('Number blocked, trying another...', 'warning')
                                time.sleep(2); continue  # Essayer autre numéro
                            else:
                                add_log('Phone rejected', 'warning')
                        
                        if not sms_ok:
                            add_log('SMS failed, saving partial account', 'warning')
                            cd = dict(session.cookies)
                            save_account_db(email_addr, PASSWORD, cd)
                            mark_email_used(email_addr)
                            set_step('success_partial')
                    else:
                        add_log('verifyToken missing for SMS', 'warning')
                        cd = dict(session.cookies)
                        save_account_db(email_addr, PASSWORD, cd)
                        mark_email_used(email_addr)
                        set_step('success_partial')
                else:
                    add_log('Account created (no SMS needed)!', 'success')
                    cd = dict(session.cookies)
                    save_account_db(email_addr, PASSWORD, cd)
                    mark_email_used(email_addr)
                    set_step('success')
            else:
                add_log('Email OTP not received', 'error')
                set_step('error')
        else:
            add_log('Unexpected response after captcha', 'error')
            add_log(f'Page content: {rev.text[:300]}...', 'info')
            set_step('error')
    
    except Exception as e:
        import traceback
        add_log(f'Error: {str(e)}', 'error')
        add_log(f'Traceback: {traceback.format_exc()[:200]}', 'error')
        set_step('error')
    finally:
        with state_lock:
            generation_state['active'] = False

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
            'active': generation_state['active'],
            'step': generation_state['step'],
            'email': generation_state['email'],
            'customer_name': generation_state['customer_name'],
            'logs': generation_state['logs'][-50:],
            'captcha_url': generation_state['captcha_url'],
            'error': generation_state['error']
        })

@app.route('/api/start', methods=['POST'])
def start_generation():
    global generation_state
    # Stop any existing captcha solver
    if PLAYWRIGHT_AVAILABLE:
        stop_captcha_solver()
    with state_lock:
        # Force reset even if active (user wants fresh start)
        generation_state = {
            'active': True, 'step': 'init', 'email': None, 'customer_name': None,
            'logs': [], 'captcha_url': None, 'captcha_token': None, 'session_data': None, 'error': None
        }
    thread = threading.Thread(target=run_generation)
    thread.daemon = True
    thread.start()
    return jsonify({'success': True})

@app.route('/api/captcha', methods=['POST'])
def submit_captcha():
    data = request.get_json()
    token = data.get('token', '')
    add_log(f'Captcha token received: {token[:50]}...', 'info')
    if not token:
        return jsonify({'error': 'Token missing'}), 400
    with state_lock:
        generation_state['captcha_token'] = token
    return jsonify({'success': True})

@app.route('/api/stop', methods=['POST'])
def stop_generation():
    global generation_state
    # Stop captcha solver
    if PLAYWRIGHT_AVAILABLE:
        stop_captcha_solver()
    with state_lock:
        # Full reset
        generation_state = {
            'active': False, 'step': 'stopped', 'email': None, 'customer_name': None,
            'logs': [], 'captcha_url': None, 'captcha_token': None, 'session_data': None, 'error': None
        }
    return jsonify({'success': True})

@app.route('/api/emails', methods=['GET', 'POST'])
def handle_emails():
    if request.method == 'POST':
        try:
            et = request.form.get('emails', '') or request.data.decode('utf-8')
            if 'file' in request.files:
                et = request.files['file'].read().decode('utf-8')
            ne = [e.strip() for e in et.split('\n') if e.strip() and '@' in e]
            if not ne:
                return jsonify({'error': 'No valid emails'}), 400
            added = add_emails_to_db(ne)
            return jsonify({'success': True, 'added': added, 'total': get_emails_count()})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'count': get_emails_count()})

@app.route('/api/accounts')
def get_accounts():
    accounts = get_all_accounts()
    formatted = [{'id': a['id'], 'email': a['email'], 'password': a['password'], 'cookies': a['cookies'], 'created_at': str(a['created_at']) if a['created_at'] else None} for a in accounts]
    return jsonify({'accounts': formatted, 'count': len(formatted)})

@app.route('/api/account/<int:account_id>', methods=['DELETE'])
def delete_account(account_id):
    if delete_account_by_id(account_id):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to delete'}), 500

@app.route('/api/account/<int:account_id>/cookies')
def get_account_cookies(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return jsonify({'error': 'Not found'}), 404
    try:
        cookies = json.loads(account['cookies']) if isinstance(account['cookies'], str) else account['cookies']
        return jsonify({'cookies': cookies})
    except:
        return jsonify({'cookies': account['cookies']})

@app.route('/session/<int:account_id>')
def open_session(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return "Compte non trouvé", 404
    return render_template('session.html', account_id=account_id, email=account['email'])

@app.route('/proxy/<int:account_id>')
def proxy_amazon(account_id):
    account = get_account_by_id(account_id)
    if not account:
        return "Compte non trouvé", 404
    
    try:
        cookies_data = json.loads(account['cookies']) if isinstance(account['cookies'], str) else account['cookies']
    except:
        cookies_data = {}
    
    session = requests.Session()
    for name, value in cookies_data.items():
        session.cookies.set(name, value, domain='.amazon.fr')
    
    url = 'https://www.amazon.fr/gp/movers-and-shakers/?ref_=nav_em_ms_0_1_1_4'
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9',
    }
    
    try:
        resp = session.get(url, headers=headers, timeout=30)
        html = resp.text
        # Remplacer les liens relatifs
        html = html.replace('href="/', 'href="https://www.amazon.fr/')
        html = html.replace('src="/', 'src="https://www.amazon.fr/')
        html = html.replace("href='/", "href='https://www.amazon.fr/")
        html = html.replace("src='/", "src='https://www.amazon.fr/")
        return html
    except Exception as e:
        return f"Erreur: {str(e)}", 500

@app.route('/api/captcha/start', methods=['POST'])
def start_captcha():
    if not PLAYWRIGHT_AVAILABLE:
        return jsonify({'error': 'Playwright not available'}), 500
    data = request.get_json()
    url = data.get('url', '')
    if not url:
        return jsonify({'error': 'URL required'}), 400
    start_captcha_solver(url)
    return jsonify({'success': True})

@app.route('/api/captcha/click', methods=['POST'])
def captcha_click():
    if not PLAYWRIGHT_AVAILABLE:
        return jsonify({'error': 'Playwright not available'}), 500
    data = request.get_json()
    x = data.get('x', 0)
    y = data.get('y', 0)
    success = click_captcha(x, y)
    state = get_captcha_state()
    return jsonify({'success': success, 'state': state})

@app.route('/api/captcha/state')
def captcha_state():
    if not PLAYWRIGHT_AVAILABLE:
        return jsonify({'error': 'Playwright not available'}), 500
    state = get_captcha_state()
    return jsonify(state)

@app.route('/api/captcha/stop', methods=['POST'])
def captcha_stop():
    if not PLAYWRIGHT_AVAILABLE:
        return jsonify({'error': 'Playwright not available'}), 500
    stop_captcha_solver()
    return jsonify({'success': True})

@app.route('/manifest.json')
def manifest():
    return jsonify({"name": "Amazon Generator", "short_name": "AmazonGen", "start_url": "/", "display": "standalone", "background_color": "#0f0f23", "theme_color": "#ff6b35"})

try:
    init_db()
except:
    pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)

# ========== MULTI-GENERATION SYSTEM ==========
generations = {}
gen_lock = threading.Lock()
gen_counter = 0

def create_gen():
    global gen_counter
    with gen_lock:
        gen_counter += 1
        gen_id = f"gen_{gen_counter}"
        generations[gen_id] = {'active': True, 'step': 'init', 'email': None, 'logs': [], 'captcha_token': None, 'captcha_screenshot': None, 'error': None}
        return gen_id

def get_gen(gen_id):
    with gen_lock:
        return generations.get(gen_id, {}).copy()

def update_gen(gen_id, **kwargs):
    with gen_lock:
        if gen_id in generations:
            generations[gen_id].update(kwargs)

def add_gen_log(gen_id, msg, log_type='info'):
    with gen_lock:
        if gen_id in generations:
            generations[gen_id]['logs'].append({'time': time.strftime('%H:%M:%S'), 'type': log_type, 'message': msg})
    print(f"[{gen_id}][{log_type.upper()}] {msg}", flush=True)

def set_gen_step(gen_id, step):
    with gen_lock:
        if gen_id in generations:
            generations[gen_id]['step'] = step

def should_gen_continue(gen_id, email):
    with gen_lock:
        g = generations.get(gen_id)
        return g and g['active'] and g.get('email') == email

def stop_gen(gen_id):
    with gen_lock:
        if gen_id in generations:
            generations[gen_id]['active'] = False
            generations[gen_id]['step'] = 'stopped'

@app.route('/multi')
def multi_page():
    return render_template('multi.html')

@app.route('/api/multi/start', methods=['POST'])
def multi_start():
    data = request.get_json() or {}
    count = min(int(data.get('count', 1)), 5)
    gen_ids = []
    for _ in range(count):
        gen_id = create_gen()
        gen_ids.append(gen_id)
        t = threading.Thread(target=run_gen_multi, args=(gen_id,))
        t.daemon = True
        t.start()
    return jsonify({'success': True, 'gen_ids': gen_ids})

@app.route('/api/multi/state')
def multi_state():
    with gen_lock:
        gens = {gid: {'active': g['active'], 'step': g['step'], 'email': g['email'], 'logs': g['logs'][-20:], 'captcha_screenshot': g.get('captcha_screenshot')} for gid, g in generations.items() if g['active'] or g['step'] in ['success', 'error']}
    return jsonify({'generations': gens})

@app.route('/api/multi/stop_all', methods=['POST'])
def multi_stop_all():
    with gen_lock:
        for gid in generations:
            generations[gid]['active'] = False
            generations[gid]['step'] = 'stopped'
    if PLAYWRIGHT_AVAILABLE: stop_captcha_solver()
    return jsonify({'success': True})

@app.route('/api/multi/click/<gen_id>', methods=['POST'])
def multi_click(gen_id):
    if not PLAYWRIGHT_AVAILABLE: return jsonify({'error': 'No Playwright'}), 500
    data = request.get_json()
    click_captcha(data.get('x', 0), data.get('y', 0))
    state = get_captcha_state()
    if state.get('screenshot'):
        with gen_lock:
            if gen_id in generations:
                generations[gen_id]['captcha_screenshot'] = state['screenshot']
    return jsonify({'success': True})

def run_gen_multi(gen_id):
    try:
        add_gen_log(gen_id, '=== STARTING ===', 'info')
        email_addr = get_random_email()
        if not email_addr:
            add_gen_log(gen_id, 'No email!', 'error')
            set_gen_step(gen_id, 'error')
            return
        customer_name = generate_name()
        update_gen(gen_id, email=email_addr)
        add_gen_log(gen_id, f'Email: {email_addr}', 'info')
        
        session = requests.Session()
        proxy = get_random_proxy()
        if proxy:
            session.proxies = proxy
            add_gen_log(gen_id, f'Proxy: {proxy["http"].split("@")[1]}', 'info')
        
        set_gen_step(gen_id, 'get_form')
        url_get = 'https://www.amazon.fr/ap/register?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.fr%2F&openid.assoc_handle=frflex&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.mode=checkid_setup&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.ns.pape=http%3A%2F%2Fspecs.openid.net%2Fextensions%2Fpape%2F1.0&pageId=frflex'
        
        rg = None
        for attempt in range(3):
            if not should_gen_continue(gen_id, email_addr): return
            try:
                if attempt > 0:
                    p = get_random_proxy()
                    if p: session.proxies = p
                rg = session.get(url_get, headers=get_headers_get(), timeout=30)
                if rg.status_code == 200 and 'ap_register_form' in rg.text: break
            except: time.sleep(2)
        
        if not rg or 'ap_register_form' not in rg.text:
            add_gen_log(gen_id, 'Form failed', 'error')
            set_gen_step(gen_id, 'error')
            return
        
        add_gen_log(gen_id, 'Form OK', 'success')
        soup = BeautifulSoup(rg.text, "html.parser")
        form = soup.find('form', id='ap_register_form')
        hf = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input', type='hidden') if inp.get('name')}
        action_url = form.get('action')
        if not action_url.startswith('http'): action_url = f'https://www.amazon.fr{action_url}'
        
        set_gen_step(gen_id, 'post_register')
        pd = hf.copy()
        pd.update({'email': email_addr, 'customerName': customer_name, 'password': PASSWORD, 'passwordCheck': PASSWORD})
        rp = session.post(action_url, data=pd, headers=get_headers_post(url_get), allow_redirects=False, timeout=30)
        add_gen_log(gen_id, f'POST: {rp.status_code}', 'info')
        
        loc = rp.headers.get('Location', '')
        if loc and not loc.startswith('http'): loc = f'https://www.amazon.fr{loc}'
        if '/ap/cvf' not in loc:
            add_gen_log(gen_id, 'No CVF', 'error')
            set_gen_step(gen_id, 'error')
            return
        
        set_gen_step(gen_id, 'captcha')
        rcvf = session.get(loc, headers=get_headers_get(), timeout=30)
        arkose = re.search(r'ARKOSE_LEVEL_\d+', rcvf.text)
        if not arkose:
            add_gen_log(gen_id, 'No Arkose', 'error')
            set_gen_step(gen_id, 'error')
            return
        add_gen_log(gen_id, arkose.group(), 'info')
        
        arb = loc.split('arb=')[1].split('&')[0] if 'arb=' in loc else ''
        ra = session.get(f'https://www.amazon.fr/ap/cvf/approval/arkose?arb={arb}&language=fr_FR', headers=get_headers_get(), timeout=30)
        iframe_m = re.search(r'(https://iframe\.arkoselabs\.com/[^"\']+)', ra.text)
        if not iframe_m:
            add_gen_log(gen_id, 'No iframe', 'error')
            set_gen_step(gen_id, 'error')
            return
        
        iframe_url = iframe_m.group(1).replace('&amp;', '&')
        add_gen_log(gen_id, 'Arkose found', 'success')
        
        if PLAYWRIGHT_AVAILABLE:
            add_gen_log(gen_id, '=== SOLVE CAPTCHA ===', 'warning')
            start_captcha_solver(iframe_url)
            sw = time.time()
            while time.time() - sw < 300:
                if not should_gen_continue(gen_id, email_addr): return
                state = get_captcha_state()
                if state.get('screenshot'): update_gen(gen_id, captcha_screenshot=state['screenshot'])
                if state.get('token'):
                    update_gen(gen_id, captcha_token=state['token'])
                    add_gen_log(gen_id, 'Token!', 'success')
                    break
                time.sleep(1)
            stop_captcha_solver()
        
        gen = get_gen(gen_id)
        token = gen.get('captcha_token')
        if not token:
            add_gen_log(gen_id, 'No token', 'error')
            set_gen_step(gen_id, 'error')
            return
        
        set_gen_step(gen_id, 'verifying')
        st_m = re.search(r'"sessionToken"\s*:\s*"([^"]+)"', rcvf.text)
        st = st_m.group(1) if st_m else ''
        hdrs = get_headers_post(loc)
        hdrs['Content-Type'] = 'application/json'
        rv = session.post(f'https://www.amazon.fr/aaut/verify/cvf/{st}', json={'aaCaptcha': token, 'verification': 'cvfInfo'}, headers=hdrs, timeout=30)
        add_gen_log(gen_id, f'Verify: {rv.status_code}', 'info')
        
        soup_cvf = BeautifulSoup(rcvf.text, "html.parser")
        cvf_form = soup_cvf.find('form')
        cvf_hf = {inp.get('name'): inp.get('value', '') for inp in cvf_form.find_all('input', type='hidden') if inp.get('name')} if cvf_form else {}
        vt_m = re.search(r'"verifyToken"\s*:\s*"([^"]+)"', rv.text)
        vt = vt_m.group(1) if vt_m else cvf_hf.get('verifyToken', '')
        if not vt:
            add_gen_log(gen_id, 'No verifyToken', 'error')
            set_gen_step(gen_id, 'error')
            return
        
        fd = cvf_hf.copy()
        fd.update({'verifyToken': vt, 'cvfAction': 'verify'})
        rf = session.post('https://www.amazon.fr/ap/cvf/verify', data=fd, headers=get_headers_post(loc), allow_redirects=False, timeout=30)
        redir = rf.headers.get('Location', '')
        if redir and not redir.startswith('http'): redir = f'https://www.amazon.fr{redir}'
        
        if redir:
            rev = session.get(redir, headers=get_headers_get(), allow_redirects=True, timeout=30)
            if 'ap/cvf' in rev.url:
                set_gen_step(gen_id, 'email_otp')
                add_gen_log(gen_id, '=== EMAIL OTP ===', 'info')
                otp = get_otp_from_email(email_addr)
                if not otp:
                    add_gen_log(gen_id, 'No OTP', 'error')
                    set_gen_step(gen_id, 'error')
                    return
                add_gen_log(gen_id, f'OTP: {otp}', 'success')
                soup_otp = BeautifulSoup(rev.text, "html.parser")
                otp_form = soup_otp.find('form')
                otp_hf = {inp.get('name'): inp.get('value', '') for inp in otp_form.find_all('input', type='hidden') if inp.get('name')} if otp_form else {}
                otp_hf.update({'cvfOtp': otp, 'otp': otp, 'code': otp})
                otp_action = otp_form.get('action', '/ap/cvf/verify') if otp_form else '/ap/cvf/verify'
                if not otp_action.startswith('http'): otp_action = f'https://www.amazon.fr{otp_action}'
                ro = session.post(otp_action, data=otp_hf, headers=get_headers_post(rev.url), allow_redirects=True, timeout=30)
                if 'phone' in ro.text.lower() or 'mobile' in ro.text.lower():
                    set_gen_step(gen_id, 'sms_otp')
                    add_gen_log(gen_id, 'SMS needed', 'info')
                    sms_result = handle_sms_verification(session, ro)
                    if sms_result == 'success':
                        save_account_db(email_addr, PASSWORD, dict(session.cookies))
                        mark_email_used(email_addr)
                        add_gen_log(gen_id, '=== CREATED! ===', 'success')
                        set_gen_step(gen_id, 'success')
                    else:
                        set_gen_step(gen_id, 'error')
                else:
                    save_account_db(email_addr, PASSWORD, dict(session.cookies))
                    mark_email_used(email_addr)
                    add_gen_log(gen_id, '=== CREATED! ===', 'success')
                    set_gen_step(gen_id, 'success')
            else:
                save_account_db(email_addr, PASSWORD, dict(session.cookies))
                mark_email_used(email_addr)
                add_gen_log(gen_id, '=== CREATED! ===', 'success')
                set_gen_step(gen_id, 'success')
        else:
            add_gen_log(gen_id, 'No redirect', 'error')
            set_gen_step(gen_id, 'error')
    except Exception as e:
        add_gen_log(gen_id, f'Error: {str(e)[:50]}', 'error')
        set_gen_step(gen_id, 'error')
    finally:
        with gen_lock:
            if gen_id in generations:
                generations[gen_id]['active'] = False
