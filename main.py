import os
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from mega import Mega
import httpx
import logging
import json

app = FastAPI()
logging.basicConfig(level=logging.INFO)

AUTH_TOKEN = "supersegreto123"
TELEGRAM_BOT_TOKEN = "6910800119:AAE7z5q1FZDtm4_qJEl_oh2et1omeT6rzDU"

class SendPhotosRequest(BaseModel):
    token: str
    megaEmail: Optional[str] = None
    megaPassword: Optional[str] = None
    panelID: str
    revision: str
    chatID: str
    megaSession: Optional[Dict[str, Any]] = None

def find_child_folder_by_name_contains(parent, keyword):
    for child in parent['children']:
        if child['t'] == 1 and keyword.lower() in child['a']['n'].lower():
            return child
    return None

def filter_files(folder):
    return [child for child in folder['children'] if child['t'] == 0]

async def send_photos_to_telegram(chat_id, files):
    MAX_MEDIA = 10
    for i in range(0, len(files), MAX_MEDIA):
        group = files[i:i+MAX_MEDIA]
        media_group = []
        files_data = {}
        for file in group:
            file_name = file['a']['n']
            file_id = file['h']
            # Scarica il file temporaneamente
            file_path = f"/tmp/{file_name}"
            m.download_url(file_id, dest_filename=file_path)
            files_data[file_name] = open(file_path, "rb")
            media_group.append({
                "type": "photo",
                "media": f"attach://{file_name}"
            })
            logging.info(f"📤 Allego file: {file_name}")

        data = {
            "chat_id": chat_id,
            "media": str(media_group).replace("'", '"')
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup",
                data=data,
                files=files_data
            )
        logging.info(f"📤 Inviato gruppo di {len(group)} foto")
        # Chiudi e rimuovi i file temporanei
        for f in files_data.values():
            f.close()
            os.remove(f.name)

# Endpoint di health check
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Middleware MEGA attivo"}

@app.get("/health")
async def detailed_health():
    return {
        "status": "ok", 
        "mega_connected": 'm' in globals() and m is not None
    }

@app.post("/sendPhotos")
async def send_photos(req: SendPhotosRequest):
    logging.info(f"📥 Richiesta ricevuta per panelID: {req.panelID}, revision: {req.revision}")

    # Validazione token
    if req.token != AUTH_TOKEN:
        logging.warning("❌ Token non valido")
        return {"error": "❌ Token non valido"}

    # Validazione parametri essenziali
    if not req.megaSession and (not req.megaEmail or not req.megaPassword):
        logging.warning("❌ Credenziali MEGA mancanti")
        return {"error": "❌ Credenziali MEGA o sessione richieste"}

    # 1. Login MEGA
    global m
    m = Mega()
    
    try:
        if req.megaSession:
            try:
                # Se megaSession è già un dict, usalo direttamente
                if isinstance(req.megaSession, dict):
                    session_data = req.megaSession
                else:
                    # Se è una stringa, prova a parsarla
                    session_data = json.loads(req.megaSession) if isinstance(req.megaSession, str) else req.megaSession
                
                m.login_user(session_data)
                logging.info("🔁 Sessione MEGA riutilizzata con successo")
            except Exception as e:
                logging.warning(f"⚠️ Sessione MEGA invalida, fallback a login: {e}")
                # Fallback a login con credenziali
                if not req.megaEmail or not req.megaPassword:
                    return {"error": "❌ Sessione invalida e credenziali mancanti"}
                m.login(req.megaEmail, req.megaPassword)
                logging.info("🔐 Login MEGA con credenziali riuscito (fallback)")
        else:
            m.login(req.megaEmail, req.megaPassword)
            logging.info("🔐 Login MEGA con credenziali riuscito")
    
    except Exception as e:
        logging.error(f"❌ Login MEGA completamente fallito: {e}")
        return {"error": f"❌ Login MEGA fallito: {str(e)}"}

    try:
        # 2. Trova la cartella "QUADRI EL. fatti da BPA"
        root = m.get_files()
        quadri_folder = next((f for f in root.values() if f['t'] == 1 and f['a']['n'] == "QUADRI EL. fatti da BPA"), None)
        if not quadri_folder:
            logging.warning("❌ Cartella 'QUADRI EL. fatti da BPA' non trovata")
            return {"error": "❌ Cartella 'QUADRI EL. fatti da BPA' non trovata"}

        # 3. Trova la cartella del pannello
        panel_folder = next((f for f in quadri_folder['children'] if f['t'] == 1 and f['a']['n'].startswith(req.panelID)), None)
        if not panel_folder:
            logging.warning(f"❌ Cartella panelID '{req.panelID}' non trovata")
            return {"error": f"❌ Cartella panelID '{req.panelID}' non trovata"}
        logging.info(f"📁 Trovata cartella panelID: {panel_folder['a']['n']}")

        # 4. Cerca cartella "Foto" direttamente dentro panelFolder
        foto_folder = find_child_folder_by_name_contains(panel_folder, "Foto")

        # 5. Se non trovata, cerca revisione e dentro quella "Foto"
        if not foto_folder:
            logging.info("🔎 Cartella 'Foto' non trovata direttamente, cerco revisione...")
            rev_folder = find_child_folder_by_name_contains(panel_folder, f"Rev. {req.revision}")
            if not rev_folder:
                rev_folder = find_child_folder_by_name_contains(panel_folder, req.revision)
            if not rev_folder:
                logging.warning(f"❌ Cartella revisione '{req.revision}' non trovata")
                return {"error": f"❌ Cartella Rev. '{req.revision}' non trovata"}
            logging.info(f"📁 Trovata cartella revisione: {rev_folder['a']['n']}")
            foto_folder = find_child_folder_by_name_contains(rev_folder, "Foto")
            if not foto_folder:
                logging.warning("❌ Cartella Foto non trovata nella revisione")
                return {"error": "❌ Cartella Foto non trovata nella revisione"}
            logging.info(f"📁 Trovata cartella Foto nella revisione: {foto_folder['a']['n']}")
        else:
            logging.info(f"📁 Trovata cartella Foto direttamente in panelID: {foto_folder['a']['n']}")

        # 6. Filtra solo i file (non directory)
        files = filter_files(foto_folder)
        logging.info(f"📸 Trovate {len(files)} foto nella cartella")

        if not files:
            return {"error": "❌ Nessuna foto trovata nella cartella"}

        # 7. Filtra solo le immagini (opzionale)
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        image_files = []
        for file in files:
            file_name = file['a']['n'].lower()
            if any(file_name.endswith(ext) for ext in image_extensions):
                image_files.append(file)
        
        if not image_files:
            return {"error": "❌ Nessuna immagine trovata nella cartella"}
        
        logging.info(f"🖼️ Filtrate {len(image_files)} immagini valide")

        # 8. Invia le foto a Telegram in gruppi da max 10
        await send_photos_to_telegram(req.chatID, image_files)
        logging.info("✅ Tutte le foto inviate con successo")

        # 9. Restituisci la sessione serializzabile se generata
        response_data = {"message": f"✅ Inviate {len(image_files)} foto con successo"}
        
        if not req.megaSession:
            # Solo se non avevamo una sessione, restituiamo quella nuova
            try:
                session = m._user  # sessione serializzabile
                response_data["megaSession"] = session
                logging.info("💾 Nuova sessione MEGA inclusa nella risposta")
            except Exception as e:
                logging.warning(f"⚠️ Non riesco a serializzare la sessione: {e}")
        
        return response_data

    except Exception as e:
        logging.error(f"❌ Errore durante l'elaborazione: {e}")
        return {"error": f"❌ Errore interno: {str(e)}"}

# Endpoint per debug
@app.post("/debug/validate")
async def debug_validate(request: Request):
    """Endpoint per debuggare i dati in arrivo"""
    try:
        body = await request.body()
        json_data = await request.json()
        logging.info(f"🔍 Raw body: {body}")
        logging.info(f"🔍 Parsed JSON: {json_data}")
        return {"received": json_data, "status": "ok"}
    except Exception as e:
        logging.error(f"❌ Errore debug: {e}")
        return {"error": str(e)}