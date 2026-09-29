import os
import json
import logging
import aiohttp
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
TELEGRAM_PHOTO_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
TELEGRAM_VIDEO_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"

app = FastAPI(title="Notsuke FieldEco Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "nodes.json"
ROUTER_FILE = "router.json"
ANOMALY_FILE = "anomalies.json"

SECTOR_START_LAT, SECTOR_END_LAT = 43.52, 43.68
SECTOR_START_LNG, SECTOR_END_LNG = 145.12, 145.40
SECTOR_LAT_STEPS, SECTOR_LNG_STEPS = 12, 12
SECTOR_COLS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']

def calculate_sector(lat: float, lng: float) -> str:
    try:
        if not (SECTOR_START_LAT <= lat <= SECTOR_END_LAT and SECTOR_START_LNG <= lng <= SECTOR_END_LNG):
            return "OUT"

        lat_delta = (SECTOR_END_LAT - SECTOR_START_LAT) / SECTOR_LAT_STEPS
        lng_delta = (SECTOR_END_LNG - SECTOR_START_LNG) / SECTOR_LNG_STEPS

        r = int((lat - SECTOR_START_LAT) / lat_delta)
        c = int((lng - SECTOR_START_LNG) / lng_delta)

        r = max(0, min(SECTOR_LAT_STEPS - 1, r))
        c = max(0, min(SECTOR_LNG_STEPS - 1, c))

        return f"{SECTOR_COLS[c]}{SECTOR_LAT_STEPS - r}"
    except Exception:
        return "N/A"

class NodeModel(BaseModel):
    id: Optional[str] = None
    type: Optional[str] = "ESP32"
    sector: Optional[str] = None
    lat: Optional[float] = 43.6100
    lng: Optional[float] = 145.2600
    target: Optional[str] = "Scanning..."
    status: Optional[str] = "Online"
    battery: Optional[int] = 100
    comment: Optional[str] = ""
    rssi: Optional[str] = "Good"

class RouterModel(BaseModel):
    lat: Optional[float] = 43.6150
    lng: Optional[float] = 145.2500
    comment: Optional[str] = "Base Station Relay"

class AnomalyModel(BaseModel):
    species: Optional[str] = "Unknown"
    severity: Optional[str] = "Low"
    sector: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    notes: Optional[str] = ""
    status: Optional[str] = "Reported"
    photo_file_id: Optional[str] = None
    media_type: Optional[str] = "photo"

class AnomalyStatusModel(BaseModel):
    status: str

def load_json(filepath, default_data):
    if not os.path.exists(filepath):
        save_json(filepath, default_data)
        return default_data
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return default_data

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

async def notify_telegram(text: str):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        logging.warning("BOT_TOKEN / ADMIN_CHAT_ID not set - skipping Telegram push / Telegram通知をスキップしました")
        return
    payload = {"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TELEGRAM_API_URL, json=payload, timeout=5) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logging.warning(f"Telegram push failed ({resp.status}): {body}")
    except Exception as e:
        logging.warning(f"Telegram push error / Telegram通知エラー: {e}")

async def notify_telegram_photo(photo_file_id: str, caption: str):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        logging.warning("BOT_TOKEN / ADMIN_CHAT_ID not set - skipping Telegram push / Telegram通知をスキップしました")
        return
    payload = {"chat_id": ADMIN_CHAT_ID, "photo": photo_file_id, "caption": caption, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TELEGRAM_PHOTO_API_URL, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logging.warning(f"Telegram photo push failed ({resp.status}): {body}")
                    await notify_telegram(caption)
    except Exception as e:
        logging.warning(f"Telegram photo push error / Telegram写真通知エラー: {e}")
        await notify_telegram(caption)

async def notify_telegram_video(video_file_id: str, caption: str):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        logging.warning("BOT_TOKEN / ADMIN_CHAT_ID not set - skipping Telegram push / Telegram通知をスキップしました")
        return
    payload = {"chat_id": ADMIN_CHAT_ID, "video": video_file_id, "caption": caption, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TELEGRAM_VIDEO_API_URL, json=payload, timeout=15) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logging.warning(f"Telegram video push failed ({resp.status}): {body}")
                    await notify_telegram(caption)
    except Exception as e:
        logging.warning(f"Telegram video push error / Telegram動画通知エラー: {e}")
        await notify_telegram(caption)

@app.get("/api/nodes")
async def get_nodes():
    return load_json(DB_FILE, {})

@app.post("/api/nodes")
async def add_or_update_node(node: NodeModel):
    nodes_data = load_json(DB_FILE, {})
    is_new = node.id is None or node.id not in nodes_data
    node_id = str(node.id) if node.id else f"{len(nodes_data) + 1:02d}"

    sector = node.sector
    if not sector or sector in ("Unknown", "N/A", ""):
        sector = calculate_sector(node.lat, node.lng)

    nodes_data[node_id] = {
        "id": node_id,
        "type": node.type,
        "lat": node.lat,
        "lng": node.lng,
        "target": node.target,
        "status": node.status,
        "battery": node.battery,
        "sector": sector,
        "comment": node.comment,
        "rssi": node.rssi,
    }

    save_json(DB_FILE, nodes_data)

    action_en, action_ja = ("New node registered", "新規ノード登録") if is_new else ("Node updated", "ノード更新")
    await notify_telegram(
        f"📡 <b>{action_en} / {action_ja}</b>\n\n"
        f"🆔 <b>ID:</b> <code>{node_id}</code>\n"
        f"🗺️ <b>Sector / セクター:</b> [{sector}]\n"
        f"📍 <b>Coords / 座標:</b> {node.lat}, {node.lng}\n"
        f"🎯 <b>Purpose / 目的:</b> {node.target}"
    )

    return {"message": "Node saved", "node_id": node_id, "data": nodes_data[node_id]}

@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str):
    nodes_data = load_json(DB_FILE, {})

    if node_id in nodes_data:
        removed = nodes_data.pop(node_id)
        save_json(DB_FILE, nodes_data)

        await notify_telegram(
            f"🗑️ <b>Node removed / ノード削除</b>\n\n"
            f"🆔 <b>ID:</b> <code>{node_id}</code>\n"
            f"🗺️ <b>Last sector / 最終セクター:</b> [{removed.get('sector', 'N/A')}]"
        )
        return {"message": f"Node {node_id} deleted"}

    return {"error": "Node not found"}

DEFAULT_ROUTER = {"lat": 43.6150, "lng": 145.2500, "comment": "Base Station Relay"}

@app.get("/api/router")
async def get_router():
    return load_json(ROUTER_FILE, DEFAULT_ROUTER)

@app.post("/api/router")
async def save_router_api(router: RouterModel):
    data = router.dict()
    save_json(ROUTER_FILE, data)

    await notify_telegram(
        f"🌐 <b>Gateway location updated / ゲートウェイ位置更新</b>\n\n"
        f"📍 <b>Coords / 座標:</b> {data['lat']}, {data['lng']}\n"
        f"🔍 <b>Info / 情報:</b> {data.get('comment', '')}"
    )
    return {"status": "success", "router": data}

@app.delete("/api/router")
async def reset_router_api():
    save_json(ROUTER_FILE, DEFAULT_ROUTER)
    await notify_telegram(
        "🌐 <b>Gateway reset to default location / ゲートウェイを既定位置へリセット</b>"
    )
    return {"status": "reset", "router": DEFAULT_ROUTER}

@app.get("/api/anomalies")
async def get_anomalies():
    return load_json(ANOMALY_FILE, [])

@app.post("/api/anomalies")
async def add_anomaly(anomaly: AnomalyModel):
    anomalies = load_json(ANOMALY_FILE, [])
    sector = anomaly.sector or (calculate_sector(anomaly.lat, anomaly.lng) if anomaly.lat and anomaly.lng else "N/A")
    entry = {
        "id": (anomalies[-1]["id"] + 1) if anomalies else 1,
        "species": anomaly.species,
        "severity": anomaly.severity,
        "sector": sector,
        "lat": anomaly.lat,
        "lng": anomaly.lng,
        "notes": anomaly.notes,
        "photo_file_id": anomaly.photo_file_id,
        "media_type": anomaly.media_type,
        "status": anomaly.status or "Reported",
    }
    anomalies.append(entry)
    save_json(ANOMALY_FILE, anomalies)

    caption = (
        f"⚠️ <b>Eco Anomaly Reported / 生態系異常報告</b>\n\n"
        f"🆔 <b>ID:</b> <code>{entry['id']}</code>\n"
        f"🌿 <b>Species / 対象種:</b> {anomaly.species}\n"
        f"🚨 <b>Severity / 脅威レベル:</b> {anomaly.severity}\n"
        f"🗺️ <b>Sector / セクター:</b> [{sector}]\n"
        f"🔍 <b>Notes / メモ:</b> {anomaly.notes}"
    )
    if anomaly.photo_file_id and anomaly.media_type == "video":
        await notify_telegram_video(anomaly.photo_file_id, caption)
    elif anomaly.photo_file_id:
        await notify_telegram_photo(anomaly.photo_file_id, caption)
    else:
        await notify_telegram(caption)

    return {"message": "Anomaly saved", "data": entry}

@app.put("/api/anomalies/{anomaly_id}")
async def update_anomaly(anomaly_id: int, anomaly: AnomalyModel):
    anomalies = load_json(ANOMALY_FILE, [])
    for entry in anomalies:
        if entry.get("id") == anomaly_id:
            sector = anomaly.sector or calculate_sector(anomaly.lat, anomaly.lng)
            entry.update({
                "species": anomaly.species,
                "severity": anomaly.severity,
                "sector": sector,
                "lat": anomaly.lat,
                "lng": anomaly.lng,
                "notes": anomaly.notes,
            })
            save_json(ANOMALY_FILE, anomalies)

            await notify_telegram(
                f"✏️ <b>Anomaly location updated / 異常報告の位置を更新</b>\n\n"
                f"🆔 <b>ID:</b> <code>{anomaly_id}</code>\n"
                f"🌿 <b>Species / 対象種:</b> {entry['species']}\n"
                f"🗺️ <b>New sector / 新セクター:</b> [{sector}]\n"
                f"📍 <b>Coords / 座標:</b> {anomaly.lat}, {anomaly.lng}"
            )
            return {"message": "Anomaly updated", "data": entry}

    return {"error": "Anomaly not found"}

@app.delete("/api/anomalies/{anomaly_id}")
async def delete_anomaly(anomaly_id: int):
    anomalies = load_json(ANOMALY_FILE, [])
    remaining = [a for a in anomalies if a.get("id") != anomaly_id]

    if len(remaining) == len(anomalies):
        return {"error": "Anomaly not found"}

    save_json(ANOMALY_FILE, remaining)
    await notify_telegram(
        f"🗑️ <b>Anomaly report removed / 異常報告を削除</b>\n\n🆔 <b>ID:</b> <code>{anomaly_id}</code>"
    )
    return {"message": f"Anomaly {anomaly_id} deleted"}

@app.patch("/api/anomalies/{anomaly_id}/status")
async def update_anomaly_status(anomaly_id: int, payload: AnomalyStatusModel):
    anomalies = load_json(ANOMALY_FILE, [])
    for entry in anomalies:
        if entry.get("id") == anomaly_id:
            entry["status"] = payload.status
            save_json(ANOMALY_FILE, anomalies)

            status_icons = {"Reported": "🆕", "Investigating": "🔎", "Resolved": "✅"}
            icon = status_icons.get(payload.status, "ℹ️")
            await notify_telegram(
                f"{icon} <b>Anomaly status updated / 異常報告のステータс更新</b>\n\n"
                f"🆔 <b>ID:</b> <code>{anomaly_id}</code>\n"
                f"🌿 <b>Species / 対象種:</b> {entry.get('species', 'Unknown')}\n"
                f"📌 <b>Status / ステータス:</b> {payload.status}"
            )
            return {"message": "Status updated", "data": entry}

    return {"error": "Anomaly not found"}

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    initial_router = load_json(ROUTER_FILE, {"lat": 43.6150, "lng": 145.2500, "comment": "Base Station Relay"})
    r_lat = initial_router.get("lat", 43.6150)
    r_lng = initial_router.get("lng", 145.2500)
    r_comment = initial_router.get("comment", "Base Station Relay").replace('"', '&quot;').replace('\n', ' ')

    file_path = os.path.join("static", "index.html")
    if not os.path.exists(file_path):
        return HTMLResponse("<h3>Error: static/index.html not found!</h3>", status_code=404)

    with open(file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    html_content = html_content.replace("{r_lat}", str(r_lat))
    html_content = html_content.replace("{r_lng}", str(r_lng))
    html_content = html_content.replace("{r_comment}", str(r_comment))

    return html_content

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
