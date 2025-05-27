import os
from fastapi import FastAPI, Request
from pydantic import BaseModel
from mega import Mega
import httpx
import logging

app = FastAPI()
logging.basicConfig(level=logging.INFO)

AUTH_TOKEN = "supersegreto123"
TELEGRAM_BOT_TOKEN = "6910800119:AAE7z5q1FZDtm4_qJEl_oh2et1omeT6rzDU"

class SendPhotosRequest(BaseModel):
    token: str
    megaEmail: str = None
    megaPassword: str = None
    panelID: str
    revision: str
    chatID: str
    megaSession: dict = None

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

@app.post("/sendPhotos")
async def send_photos(req: SendPhotosRequest):
    logging.info(f"📥 Richiesta ricevuta: {req.dict(exclude={'megaPassword'})}")

    if req.token != AUTH_TOKEN:
        logging.warning("❌ Token non valido")
        return {"error": "❌ Token non valido"}

    # 1. Login MEGA
    global m
    m = Mega()
    if req.megaSession:
        try:
            m.login_user(req.megaSession)
            logging.info("🔁 Sessione MEGA fornita da richiesta, uso quella.")
        except Exception as e:
            logging.error(f"❌ Sessione MEGA invalida: {e}")
            return {"error": "❌ Sessione MEGA invalida"}
    else:
        try:
            m.login(req.megaEmail, req.megaPassword)
            logging.info("🔐 Login con email/password riuscito.")
        except Exception as e:
            logging.error(f"❌ Login MEGA fallito: {e}")
            return {"error": "❌ Login MEGA fallito"}

    # 2. Trova la cartella "QUADRI EL. fatti da BPA"
    root = m.get_files()
    quadri_folder = next((f for f in root.values() if f['t'] == 1 and f['a']['n'] == "QUADRI EL. fatti da BPA"), None)
    if not quadri_folder:
        logging.warning("❌ Cartella 'QUADRI EL. fatti da BPA' non trovata")
        return {"error": "❌ Cartella 'QUADRI EL. fatti da BPA' non trovata."}

    # 3. Trova la cartella del pannello
    panel_folder = next((f for f in quadri_folder['children'] if f['t'] == 1 and f['a']['n'].startswith(req.panelID)), None)
    if not panel_folder:
        logging.warning("❌ Cartella panelID non trovata")
        return {"error": "❌ Cartella panelID non trovata."}
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
            logging.warning("❌ Cartella revisione non trovata")
            return {"error": "❌ Cartella Rev. non trovata."}
        logging.info(f"📁 Trovata cartella revisione: {rev_folder['a']['n']}")
        foto_folder = find_child_folder_by_name_contains(rev_folder, "Foto")
        if not foto_folder:
            logging.warning("❌ Cartella Foto non trovata nella revisione")
            return {"error": "❌ Cartella Foto non trovata."}
        logging.info(f"📁 Trovata cartella Foto nella revisione: {foto_folder['a']['n']}")
    else:
        logging.info(f"📁 Trovata cartella Foto direttamente in panelID: {foto_folder['a']['n']}")

    # 6. Filtra solo i file (non directory)
    files = filter_files(foto_folder)
    logging.info(f"📸 Trovate {len(files)} foto nella cartella.")

    if not files:
        return {"error": "❌ Nessuna foto trovata."}

    # 7. Invia le foto a Telegram in gruppi da max 10
    await send_photos_to_telegram(req.chatID, files)
    logging.info("✅ Tutte le foto inviate.")

    # 8. Restituisci la sessione serializzabile se generata
    if not req.megaSession:
        session = m._user  # serializzabile
        return {
            "message": "✅ Tutte le foto inviate con successo.",
            "megaSession": session
        }
    else:
        return {"message": "✅ Tutte le foto inviate con successo."}
    
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Middleware MEGA attivo"}

@app.get("/health")
async def detailed_health():
    return {
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "mega_connected": m is not None if 'm' in globals() else False
    }