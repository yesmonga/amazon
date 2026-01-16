
import re
import time
import base64
import threading
from playwright.sync_api import sync_playwright

# State global pour le captcha solver
captcha_solver_state = {
    'active': False,
    'screenshot': None,
    'token': None,
    'solved': False,
    'error': None,
    'page': None,
    'browser': None,
    'context': None
}
solver_lock = threading.Lock()

def start_captcha_solver(arkose_iframe_url):
    """Démarre le navigateur Playwright et ouvre l'iframe Arkose"""
    global captcha_solver_state
    
    def run_solver():
        global captcha_solver_state
        try:
            with solver_lock:
                captcha_solver_state['active'] = True
                captcha_solver_state['token'] = None
                captcha_solver_state['solved'] = False
                captcha_solver_state['error'] = None
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={'width': 400, 'height': 500},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                page = context.new_page()
                
                with solver_lock:
                    captcha_solver_state['browser'] = browser
                    captcha_solver_state['context'] = context
                    captcha_solver_state['page'] = page
                
                # Intercepter les réponses pour capturer le token
                def handle_response(response):
                    try:
                        url = response.url
                        if '/fc/ca' in url:
                            try:
                                body = response.text()
                                if body and '"solved"' in body and 'true' in body.lower():
                                    with solver_lock:
                                        captcha_solver_state['solved'] = True
                            except:
                                pass
                        if 'arkoselabs' in url or 'funcaptcha' in url:
                            try:
                                body = response.text()
                                if body and '|r=' in body:
                                    token_match = re.search(r'"token"\s*:\s*"([^"]+\|r=[^"]+)"', body)
                                    if token_match:
                                        with solver_lock:
                                            captcha_solver_state['token'] = token_match.group(1)
                            except:
                                pass
                    except:
                        pass
                
                page.on('response', handle_response)
                
                # Charger l'iframe
                page.goto(arkose_iframe_url, wait_until='networkidle', timeout=30000)
                
                # Prendre un screenshot initial
                screenshot = page.screenshot()
                with solver_lock:
                    captcha_solver_state['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                
                # Attendre jusqu'à résolution ou timeout (5 min)
                start_time = time.time()
                while time.time() - start_time < 300:
                    with solver_lock:
                        if not captcha_solver_state['active']:
                            break
                        if captcha_solver_state['token']:
                            break
                    
                    # Prendre un nouveau screenshot
                    try:
                        screenshot = page.screenshot()
                        with solver_lock:
                            captcha_solver_state['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                            
                        # Vérifier le texte de succès
                        content = page.content()
                        if 'Vérification terminée' in content or 'prouvé que vous êtes un être humain' in content:
                            with solver_lock:
                                captcha_solver_state['solved'] = True
                    except:
                        pass
                    
                    time.sleep(0.5)
                
                # Fermer
                context.close()
                browser.close()
                
        except Exception as e:
            with solver_lock:
                captcha_solver_state['error'] = str(e)
        finally:
            with solver_lock:
                captcha_solver_state['active'] = False
                captcha_solver_state['page'] = None
                captcha_solver_state['browser'] = None
                captcha_solver_state['context'] = None
    
    thread = threading.Thread(target=run_solver)
    thread.daemon = True
    thread.start()
    return True

def click_captcha(x, y):
    """Envoie un clic aux coordonnées spécifiées"""
    global captcha_solver_state
    with solver_lock:
        page = captcha_solver_state.get('page')
        if page:
            try:
                page.mouse.click(x, y)
                time.sleep(0.3)
                screenshot = page.screenshot()
                captcha_solver_state['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                return True
            except:
                pass
    return False

def get_captcha_state():
    """Retourne l'état actuel du solver"""
    with solver_lock:
        return {
            'active': captcha_solver_state['active'],
            'screenshot': captcha_solver_state['screenshot'],
            'token': captcha_solver_state['token'],
            'solved': captcha_solver_state['solved'],
            'error': captcha_solver_state['error']
        }

def stop_captcha_solver():
    """Arrête le solver"""
    global captcha_solver_state
    with solver_lock:
        captcha_solver_state['active'] = False
