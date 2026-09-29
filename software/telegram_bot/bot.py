import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)

from bot_handlers import router as interactive_router, check_access

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Dashboard API URLs / API URL
DASHBOARD_API_URL = "http://localhost:8000/api/nodes"
ROUTER_API_URL = "http://localhost:8000/api/router"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Register the interactive menu / FSM handlers (Submit Sample, Report Anomaly,
# Update GPS, Check-in, language switch).
# 対話メニュー/FSMハンドラー（サンプル提出、異常報告、GPS更新、チェックイン、
# 言語切替）を登録する。
dp.include_router(interactive_router)

# --- Sector grid config / セクターグリッド設定 ---
# Kept identical to main.py and index.html's grid so /status and the
# dashboard always report the same sector for the same coordinates.
# main.py と index.html のグリッドと必ず一致させること。
SECTOR_START_LAT, SECTOR_END_LAT = 43.52, 43.68
SECTOR_START_LNG, SECTOR_END_LNG = 145.12, 145.40
SECTOR_LAT_STEPS, SECTOR_LNG_STEPS = 12, 12
SECTOR_COLS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']


# Fetch live API data / APIからデータを取得
async def fetch_api_data(url: str):
    try:
        async with aiohttp.ClientSession(trust_env=True, connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.get(url, timeout=2) as response:
                if response.status == 200:
                    return await response.json()
    except Exception as e:
        logging.warning(f"API Error ({url}): {e}")
    return {}


# Calculate sector from coordinates / 座標からセクターを計算
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


# Command: /status / コマンド: /status
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not check_access(message.chat.id):
        await message.answer("Access denied. / アクセス拒否。")
        return

    nodes_data = await fetch_api_data(DASHBOARD_API_URL)
    router_data = await fetch_api_data(ROUTER_API_URL) or {
        "lat": 43.6150, "lng": 145.2500, "comment": "Base Station Relay"
    }

    # Gateway info / ゲートウェイ情報
    r_lat = router_data.get("lat", 43.6150)
    r_lng = router_data.get("lng", 145.2500)
    r_sector = calculate_sector(r_lat, r_lng)
    r_comment = router_data.get("comment", "Base Station Relay")

    nodes_telemetry = ""

    for node_id, info in nodes_data.items():
        n_lat = info.get("lat", 43.6100)
        n_lng = info.get("lng", 145.2600)
        n_sector = info.get("sector") or calculate_sector(n_lat, n_lng)
        n_target = info.get("target", "Invasive flora tracking")
        n_status = info.get("status", "Online")
        n_battery = info.get("battery", 100)
        n_comment = info.get("comment") or n_target

        # Determine device type & purpose / デバイス種別と目的を判定
        dev_type = info.get("type") or ("ESP32-CAM" if "CAM" in str(n_target).upper() else "ESP32")
        status_icon = "🟢" if str(n_status).lower() == "online" else "🔴"

        nodes_telemetry += (
            f"📡 <b>Node <code>{node_id}</code></b> ({status_icon} <b>{n_status}</b> | ⚡ {n_battery}%)\n"
            f"├ <b>Device Type / 端末種別:</b> {dev_type}\n"
            f"├ <b>Purpose / 目的:</b> {n_target}\n"
            f"├ <b>Sector / セクター:</b> <code>[{n_sector}]</code>\n"
            f"├ <b>Coordinates / 座標:</b> <code>{n_lat}, {n_lng}</code>\n"
            f"└ <b>Comment / コメント:</b> {n_comment}\n\n"
        )

    if not nodes_telemetry:
        nodes_telemetry = "<i>No active nodes detected. / アクティブなノードは見つかりません。</i>\n\n"

    text = (
        "📡 <b>LoRaWAN Mesh Network Status / ネットワーク状態</b>\n\n"
        "🌐 <b>Gateway / Router (ルーター):</b>\n"
        " • <b>Status / 状態:</b> 🟢 Online / オンライン\n"
        f" • <b>Sector / セクター:</b> [ <code>{r_sector}</code> ]\n"
        f" • <b>Coordinates / 座標:</b> <code>{r_lat}, {r_lng}</code> <i>(tap to copy / タップしてコピー)</i>\n"
        f" • <b>Info / 情報:</b> {r_comment}\n\n"
        "📊 <b>Network Metrics / ネットワーク指標:</b>\n"
        f" • <b>Active Nodes / アクティブノード数:</b> {len(nodes_data)}\n"
        " • <b>Bandwidth / 使用帯域:</b> 920 MHz ARIB STD-T108\n"
        " • <b>System Health / システム状態:</b> 100%\n\n"
        f"<b>Active Nodes Telemetry (Live) / ノード遠隔測定:</b>\n\n{nodes_telemetry}"
    )

    await message.answer(text, parse_mode="HTML")


# Command: /alert_test / コマンド: /alert_test
@dp.message(Command("alert_test"))
async def cmd_alert_test(message: types.Message):
    if not check_access(message.chat.id):
        return

    nodes_data = await fetch_api_data(DASHBOARD_API_URL)
    if not nodes_data:
        await message.answer("No nodes available to test. / テスト対象のノードがありません。")
        return

    keyboard_buttons = []
    row = []

    for node_id, info in nodes_data.items():
        sector = info.get("sector", "??")
        row.append(InlineKeyboardButton(text=f"Node {node_id} ({sector})", callback_data=f"testnode_{node_id}"))
        if len(row) == 2:
            keyboard_buttons.append(row)
            row = []
    if row:
        keyboard_buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer("🎯 <b>Select target node for test alert: / テスト通知のノードを選択:</b>", reply_markup=kb, parse_mode="HTML")


# Callback: Node test selection / コールバック: ノードテスト選択
@dp.callback_query(F.data.startswith('testnode_'))
async def process_node_test(callback_query: types.CallbackQuery):
    if not check_access(callback_query.message.chat.id):
        return

    node_id = callback_query.data.split("_")[1]
    nodes_data = await fetch_api_data(DASHBOARD_API_URL)
    node_info = nodes_data.get(node_id, {"sector": "B3", "lat": 43.5833, "lng": 145.1500, "target": "Unknown"})

    await callback_query.answer(f"Triggering alert for Node {node_id}... / 警告をトリガーしています...")
    await callback_query.message.delete()

    await send_push_alert(
        node_name=f"ESP32_CAM_NODE_{node_id}",
        sector=node_info.get("sector", "N/A"),
        lat=node_info.get("lat", 0.0),
        lng=node_info.get("lng", 0.0),
        alert_type="Invasive Species",
        details=f"Threat detected near {node_info.get('target', 'target area')}. / 脅威が検出されました。"
    )


# Function: Send push alert / 関数: プッシュ通知を送信
async def send_push_alert(node_name: str, sector: str, lat: float, lng: float, alert_type: str, details: str):
    dashboard_url = f"http://127.0.0.1:8000/dashboard?node={node_name}&sector={sector}&lat={lat}&lng={lng}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺️ Open Dashboard / ダッシュボードを開く", url=dashboard_url)],
        [InlineKeyboardButton(text="✅ Acknowledge / 確認・承認", callback_data=f"ack_{node_name}")]
    ])

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"🚨 <b>ALERT: {alert_type.upper()} DETECTED! / 警告: {alert_type.upper()} を検出！</b>\n\n"
        f"📍 <b>Location / 位置:</b> Sector <code>[{sector}]</code> ({lat}, {lng})\n"
        f"📡 <b>Source Node / 送信元:</b> <code>{node_name}</code>\n"
        f"🔍 <b>Details / 詳細:</b> {details}\n"
        f"⏰ <b>Time / 時間:</b> {current_time} JST\n"
    )

    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Failed to send Telegram Push / プッシュ通知エラー: {e}")


# Callback: Acknowledge alert / コールバック: 警告の確認
@dp.callback_query(F.data.startswith('ack_'))
async def process_ack(callback_query: types.CallbackQuery):
    if not check_access(callback_query.message.chat.id):
        return

    await callback_query.answer("Received and processed / 受理されました")

    new_text = callback_query.message.html_text + "\n\n✅ <b>Verified by Operator / オペレーター確認済み</b>"
    await callback_query.message.edit_text(text=new_text, parse_mode="HTML")


# Main execution / メイン処理
async def main():
    logging.info("Starting Telegram Bot Gateway... / Telegramボットゲートウェイを起動中...")

    await bot.set_my_commands([
        BotCommand(command="start", description="Menu / メニューを開く"),
        BotCommand(command="status", description="Network status / ネットワーク状態を確認"),
        BotCommand(command="alert_test", description="Test push alert / テスト通知を送信"),
        BotCommand(command="myreports", description="My anomaly reports / 過去の異常報告"),
        BotCommand(command="cancel", description="Cancel current action / 現在の操作をキャンセル"),
    ])

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
