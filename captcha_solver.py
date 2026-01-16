
import re
import time
import base64
import threading
import queue
from playwright.sync_api import sync_playwright

# State global pour le captcha solver
captcha_solver_state = {
    'active': False,
    'screenshot': None,
    'token': None,
    'solved': False,
    'error': None
}
solver_lock = threading.Lock()
click_queue = queue.Queue()

def start_captcha_solver(arkose_iframe_url):
    """Démarre le navigateur Playwright et ouvre l'iframe Arkose"""
    global captcha_solver_state
    
    # Si déjà actif, ne pas relancer
    with solver_lock:
        if captcha_solver_state['active']:
            return True
    
    # Vider la queue de clics
    while not click_queue.empty():
        try:
            click_queue.get_nowait()
        except:
            break
    
    def run_solver():
        global captcha_solver_state
        try:
            with solver_lock:
                captcha_solver_state['active'] = True
                captcha_solver_state['token'] = None
                captcha_solver_state['solved'] = False
                captcha_solver_state['error'] = None
                captcha_solver_state['screenshot'] = None
            
            print(f"[CAPTCHA] Starting Playwright...", flush=True)
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={'width': 400, 'height': 500},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
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
                                    print(f"[CAPTCHA] SOLVED detected!", flush=True)
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
                                        print(f"[CAPTCHA] TOKEN captured!", flush=True)
                            except:
                                pass
                    except:
                        pass
                
                page.on('response', handle_response)
                
                # Charger l'iframe
                print(f"[CAPTCHA] Loading URL...", flush=True)
                page.goto(arkose_iframe_url, wait_until='networkidle', timeout=30000)
                
                # Prendre un screenshot initial
                screenshot = page.screenshot()
                with solver_lock:
                    captcha_solver_state['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                print(f"[CAPTCHA] Initial screenshot taken", flush=True)
                
                # Boucle principale - traiter les clics et prendre des screenshots
                # On attend que SOLVED soit True ET que le token soit capturé
                start_time = time.time()
                while time.time() - start_time < 300:
                    with solver_lock:
                        if not captcha_solver_state['active']:
                            break
                        # IMPORTANT: attendre solved ET token (comme le bot manuel)
                        if captcha_solver_state['solved'] and captcha_solver_state['token']:
                            print(f"[CAPTCHA] Both SOLVED and TOKEN - success!", flush=True)
                            break
                    
                    # Traiter les clics en attente
                    try:
                        while True:
                            x, y = click_queue.get_nowait()
                            print(f"[CAPTCHA] Clicking at {x}, {y}", flush=True)
                            page.mouse.click(x, y)
                            time.sleep(0.3)
                    except queue.Empty:
                        pass
                    
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
                            print(f"[CAPTCHA] Success text detected!", flush=True)
                    except Exception as e:
                        print(f"[CAPTCHA] Screenshot error: {e}", flush=True)
                    
                    time.sleep(0.4)
                
                # Fermer
                print(f"[CAPTCHA] Closing browser...", flush=True)
                context.close()
                browser.close()
                
        except Exception as e:
            print(f"[CAPTCHA] Error: {e}", flush=True)
            with solver_lock:
                captcha_solver_state['error'] = str(e)
        finally:
            with solver_lock:
                captcha_solver_state['active'] = False
            print(f"[CAPTCHA] Solver stopped", flush=True)
    
    thread = threading.Thread(target=run_solver)
    thread.daemon = True
    thread.start()
    return True

def click_captcha(x, y):
    """Ajoute un clic à la queue (sera traité par le thread Playwright)"""
    click_queue.put((x, y))
    return True

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
