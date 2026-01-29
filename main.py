import os
import requests
import json
import re
import time
import mimetypes
from fastapi import FastAPI, HTTPException, Query
from typing import Optional

app = FastAPI(title="Gemini API Wrapper")

COOKIES_FILE = "gemini.google.com_cookies-2026-01-29T151723.456.txt"

class GeminiSession:
    def __init__(self):
        self.session = None
        self.token = None
        self.last_update = 0

    def refresh(self):
        if self.session and self.token and (time.time() - self.last_update < 1800):
            return self.session, self.token
        
        cookies = {}
        if not os.path.exists(COOKIES_FILE):
            raise Exception(f"Fichier de cookies non trouvé: {COOKIES_FILE}")

        with open(COOKIES_FILE, 'r') as f:
            for line in f:
                if not line.startswith('#') and line.strip():
                    parts = line.strip().split('\t')
                    if len(parts) >= 7: 
                        cookies[parts[5]] = parts[6]
        
        self.session = requests.Session()
        for n, v in cookies.items(): 
            self.session.cookies.set(n, v, domain=".google.com")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": "https://gemini.google.com/app"
        }
        
        resp = self.session.get("https://gemini.google.com/app", headers=headers, timeout=30)
        match = re.search(r'"SNlM0e":"(.*?)"', resp.text)
        if not match: raise Exception("Auth failed: SNlM0e token not found. Check cookies.")
        
        self.token = match.group(1)
        self.last_update = time.time()
        return self.session, self.token

    def upload_image(self, image_path: str, token: str):
        # Simulation d'upload pour fallback sur URL prompt (comme dans l'original)
        return None

gemini_auth = GeminiSession()

def extract_text(raw_line):
    try:
        if "wrb.fr" in raw_line:
            data = json.loads(raw_line)
            inner = json.loads(data[0][2])
            if len(inner) > 4 and inner[4]:
                for item in inner[4]:
                    if isinstance(item, list) and len(item) > 1 and isinstance(item[1], list):
                        return item[1][0]
        return None
    except: return None

def extract_image_urls(raw_line):
    """Extrait les URLs d'images des réponses Gemini"""
    urls = []
    try:
        if "wrb.fr" in raw_line:
            data = json.loads(raw_line)
            inner = json.loads(data[0][2])
            # Recherche récursive d'URLs d'images dans la structure complexe
            content_str = str(inner)
            found_urls = re.findall(r'https://lh3\.googleusercontent\.com/[a-zA-Z0-9\-_=]+', content_str)
            for url in found_urls:
                if url not in urls:
                    urls.append(url)
    except: pass
    return urls

@app.get("/gemini")
async def gemini_endpoint(prompt: str, image: Optional[str] = None, uid: Optional[str] = None):
    start_time = time.time()
    file_id = None
    
    try:
        session, token = gemini_auth.refresh()
        
        if image:
            # Fallback sur URL dans le prompt si l'upload n'est pas implémenté
            prompt = f"[Image: {image}]\n\n{prompt}"

        req = [[prompt], None, ["", "", ""]]
        payload = {"f.req": json.dumps([None, json.dumps(req)]), "at": token}
        url = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
        
        resp = session.post(url, data=payload, params={"rt": "c"}, timeout=(10, 60), stream=True)
        
        answer = None
        for line in resp.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if "wrb.fr" in decoded_line:
                    res = extract_text(decoded_line)
                    if res:
                        answer = res
                        break
        resp.close()
        
        return {
            "status": "success",
            "uid": uid,
            "answer": answer or "Réponse reçue.",
            "execution_time": f"{round(time.time() - start_time, 2)}s"
        }
    except Exception as e:
        import traceback
        print(f"Erreur: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@app.get("/nanobanana")
async def nanobanana_endpoint(prompt: str, image: str, uid: Optional[str] = None):
    """
    Route spécifique pour le modèle Nano Banana.
    Prend une image et un prompt, et retourne l'URL de l'image générée.
    """
    start_time = time.time()
    
    try:
        session, token = gemini_auth.refresh()
        
        # Pour Nano Banana, on demande explicitement à Gemini de modifier l'image
        # et on s'assure que le prompt mentionne la modification.
        full_prompt = f"Utilise le modèle Nano Banana pour modifier cette image: {image}. Instruction: {prompt}. Retourne uniquement l'image modifiée."

        req = [[full_prompt], None, ["", "", ""]]
        payload = {"f.req": json.dumps([None, json.dumps(req)]), "at": token}
        url = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
        
        resp = session.post(url, data=payload, params={"rt": "c"}, timeout=(10, 60), stream=True)
        
        image_url = None
        lines = []
        for line in resp.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                lines.append(decoded_line)
                if "wrb.fr" in decoded_line:
                    urls = extract_image_urls(decoded_line)
                    if urls:
                        image_url = urls[0]
                        break
        resp.close()
        
        if not image_url:
            for decoded_line in lines:
                text = extract_text(decoded_line)
                if text:
                    found = re.search(r'https://lh3\.googleusercontent\.com/[a-zA-Z0-9\-_=]+', text)
                    if found:
                        image_url = found.group(0)
                        break

        return {
            "resultats": image_url or "Aucune image générée ou URL non trouvée"
        }
    except Exception as e:
        import traceback
        print(f"Erreur: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
