import os
import logging
import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = Router()

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Backend API endpoints / バックエンドAPIエンドポイント
BACKEND_ANOMALY_URL = "http://localhost:8000/api/anomalies"

# --- Per-user UI language / ユーザーごとのUI言語 ---
# Kept in a plain module-level dict rather than FSMContext data, because
# state.clear() (called on /cancel, /start, and after every finished flow)
# would otherwise wipe the user's language choice along with the form data.
# FSMContext のデータではなくモジュールレベルの辞書で保持する。
# state.clear() は /cancel・/start・各フォーム完了後に呼ばれるため、
# そこに保存すると言語設定までフォームデータと一緒に消えてしまう。
user_lang: dict[int, str] = {}


def get_lang(user_id: int) -> str:
    return user_lang.get(user_id, "en")


def check_access(user_id: int) -> bool:
    # Log every denial with both values, so a missing/wrong ADMIN_CHAT_ID in
    # .env (e.g. left over from testing a different integration, or just
    # never set) shows up immediately in the console instead of only as a
    # silent "Access denied" in the chat.
    # 拒否のたびに両方の値をログ出力する。.envのADMIN_CHAT_IDが未設定・
    # 誤りの場合（例: 別の連携をテストした際の値が残っている等）でも、
    # チャット上の「Access denied」だけでなくコンソールにすぐ表示される。
    if ADMIN_CHAT_ID is None:
        logging.warning(
            f"ADMIN_CHAT_ID is not set in .env — every user will be denied. "
            f"Incoming chat_id was: {user_id}"
        )
        return False
    if str(user_id) != str(ADMIN_CHAT_ID).strip():
        logging.warning(
            f"Access denied: incoming chat_id={user_id} does not match ADMIN_CHAT_ID={ADMIN_CHAT_ID!r} in .env"
        )
        return False
    return True


# FSM States / 状態定義
class SurveyForm(StatesGroup):
    waiting_for_quadrat = State()
    waiting_for_count = State()

class NativeAnomalyForm(StatesGroup):
    waiting_for_species = State()
    waiting_for_severity = State()
    waiting_for_location = State()
    waiting_for_notes = State()
    waiting_for_photo = State()
    waiting_for_confirmation = State()

class LocationForm(StatesGroup):
    waiting_for_gps = State()

class EditAnomalyLocationForm(StatesGroup):
    waiting_for_new_location = State()

# Full extended dictionary i18n / 多言語辞書
I18N = {
    "en": {
        "access_denied": "⛔ Access denied. / アクセス拒否。",
        "welcome": "🌲 **FieldEco Tracker Operator Bot**\nSelect an action or send command:",
        "lang_select": "Choose UI Language / 言語を選択してください:",
        "lang_set": "Language changed to English 🇬🇧",

        "submit_count": "📊 Submit Observation Sample",
        "report_anomaly": "⚠️ Report Eco Anomaly",
        "send_location": "📍 Update GPS Coordinates",
        "operator_ping": "🟢 Field Check-in (I'm Safe)",
        "switch_lang": "🌐 Change Language / 言語切替",
        "cancel_btn": "❌ Cancel / Back to Menu",

        "ask_quadrat": "📊 **Submit Observation Sample**\n\nEnter the Survey Quadrat / Checkpoint ID (e.g. `1-102`):",
        "ask_count": "Enter observation count / sample count (integer):",
        "sample_received": "✅ **Data Recorded!**\n\n• **Quadrat:** {quadrat}\n• **Count:** {count}\n\nSynced to Dispatch Server.",
        "invalid_number": "⚠️ Invalid input! Please enter a valid integer number:",

        "ask_gps": "📍 Click the button below to attach your current field GPS location:",
        "gps_btn": "📡 Send Current Location",
        "gps_received": "✅ **Location updated!**\nLatitude: {lat:.5f}, Longitude: {lon:.5f}",

        "ping_logged": "🟢 **Field Check-in logged.** Dispatcher notified that operator is active.",
        "op_cancelled": "❌ Operation cancelled. Returned to main menu.",

        "anomaly_synced": "✅ **Report successfully synced with Dashboard! / ダッシュボードと同期完了！**",
        "anomaly_sync_failed": "⚠️ Data collected, but backend sync failed. / データは収集されましたが、同期に失敗しました。",
        "anomaly_unreachable": "✅ Report saved, but the server was unreachable: {error}",

        "ask_photo": "📷 Attach a photo or video of the anomaly, or press Skip. / 異常の写真または動画を添付するか、スキップを押してください。",
        "skip_btn": "⏭️ Skip / スキップ",
        "photo_saved": "📷 Media attached! / メディアを添付しました！",
        "confirm_summary": (
            "📋 **Please review before submitting / 送信前にご確認ください:**\n\n"
            "🌿 **Species:** {species}\n"
            "🚨 **Severity:** {severity}\n"
            "📍 **Coords:** {lat:.5f}, {lng:.5f}\n"
            "📷 **Photo:** {photo_status}\n"
            "🔍 **Notes:** {notes}"
        ),
        "photo_yes": "attached / 添付済み",
        "photo_no": "none / なし",
        "confirm_btn": "✅ Confirm & Submit",
        "edit_notes_btn": "✏️ Edit Notes",
        "reenter_notes": "Enter new field notes / 新しい現場メモを入力してください:\n(Or type '-' to skip)",

        "my_reports_header": "📋 **Your Last Reports / 最近の報告**",
        "my_reports_empty": "No anomaly reports yet. / まだ異常報告はありません。",
        "my_reports_cmd": "📋 My Reports",
        "status_investigating_btn": "🔎 Investigating",
        "status_resolved_btn": "✅ Resolved",
        "delete_btn": "🗑️ Delete",
        "editloc_btn": "🗺️ Change Location",
        "delete_confirm": "Delete this report? This can't be undone. / この報告を削除しますか？元に戻せません。",
        "delete_yes": "🗑️ Yes, delete / はい、削除",
        "delete_no": "❌ No, keep it / いいえ",
        "deleted_ok": "🗑️ Report deleted. / 報告を削除しました。",
        "status_updated": "✅ Status updated to {status}. / ステータスを{status}に更新しました。",
        "ask_new_location": "🗺️ Send the new GPS location for this report. / この報告の新しいGPS位置情報を送信してください。",
        "location_updated": "✅ Location updated! / 位置情報を更新しました！",
        "not_found": "⚠️ Report not found (it may already be deleted). / 報告が見つかりません（既に削除された可能性があります）。",
    },
    "ja": {
        "access_denied": "⛔ アクセス拒否。/ Access denied.",
        "welcome": "🌲 **FieldEco Tracker 野外調査用ボット**\n操作を選択してください:",
        "lang_select": "Choose UI Language / 言語を選択してください:",
        "lang_set": "言語を日本語に設定しました 🇯🇵",

        "submit_count": "📊 観察サンプル数送信",
        "report_anomaly": "⚠️ 環境異常報告 (Hazard Alert)",
        "send_location": "📍 GPS位置情報を更新",
        "operator_ping": "🟢 現場チェックイン (安全確認)",
        "switch_lang": "🌐 Change Language / 言語切替",
        "cancel_btn": "❌ キャンセル / メニューに戻る",

        "ask_quadrat": "📊 **観察サンプル数送信**\n\n調査コドラート／チェックポイントIDを入力してください (例: `Q-102`):",
        "ask_count": "観察数／サンプル数を入力してください (半角数字):",
        "sample_received": "✅ **記録完了！**\n\n• **コドラート:** {quadrat}\n• **観察数:** {count}\n\n指令サーバーに同期されました。",
        "invalid_number": "⚠️ 無効な入力です。半角数字（整数）を入力してください:",

        "ask_gps": "📍 下のボタンを押して現在の現場GPS位置情報を送信してください:",
        "gps_btn": "📡 現在地を送信",
        "gps_received": "✅ **位置情報を更新しました！**\n緯度: {lat:.5f}, 経度: {lon:.5f}",

        "ping_logged": "🟢 **チェックイン完了。** オペレーターの生存・活動状態を記録しました。",
        "op_cancelled": "❌ 操作がキャンセルされました。メインメニューに戻ります。",

        "anomaly_synced": "✅ **ダッシュボードと同期完了！ / Report successfully synced with Dashboard!**",
        "anomaly_sync_failed": "⚠️ データは収集されましたが、同期に失敗しました。/ Data collected, but backend sync failed.",
        "anomaly_unreachable": "✅ データは保存されましたが、サーバーに接続できませんでした: {error}",

        "ask_photo": "📷 異常の写真または動画を添付するか、スキップを押してください。/ Attach a photo or video of the anomaly, or press Skip.",
        "skip_btn": "⏭️ スキップ / Skip",
        "photo_saved": "📷 メディアを添付しました！/ Media attached!",
        "confirm_summary": (
            "📋 **送信前にご確認ください / Please review before submitting:**\n\n"
            "🌿 **対象種:** {species}\n"
            "🚨 **脅威レベル:** {severity}\n"
            "📍 **座標:** {lat:.5f}, {lng:.5f}\n"
            "📷 **写真:** {photo_status}\n"
            "🔍 **メモ:** {notes}"
        ),
        "photo_yes": "添付済み / attached",
        "photo_no": "なし / none",
        "confirm_btn": "✅ 確認して送信",
        "edit_notes_btn": "✏️ メモを編集",
        "reenter_notes": "新しい現場メモを入力してください:\n(スキップする場合は '-')",

        "my_reports_header": "📋 **最近の報告 / Your Last Reports**",
        "my_reports_empty": "まだ異常報告はありません。/ No anomaly reports yet.",
        "my_reports_cmd": "📋 過去の報告",
        "status_investigating_btn": "🔎 調査中",
        "status_resolved_btn": "✅ 解決済み",
        "delete_btn": "🗑️ 削除",
        "editloc_btn": "🗺️ 位置変更",
        "delete_confirm": "この報告を削除しますか？元に戻せません。/ Delete this report? This can't be undone.",
        "delete_yes": "🗑️ はい、削除 / Yes, delete",
        "delete_no": "❌ いいえ / No, keep it",
        "deleted_ok": "🗑️ 報告を削除しました。/ Report deleted.",
        "status_updated": "✅ ステータスを{status}に更新しました。/ Status updated to {status}.",
        "ask_new_location": "🗺️ この報告の新しいGPS位置情報を送信してください。/ Send the new GPS location for this report.",
        "location_updated": "✅ 位置情報を更新しました！/ Location updated!",
        "not_found": "⚠️ 報告が見つかりません（既に削除された可能性があります）。/ Report not found.",
    }
}

def get_main_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=I18N[lang]["submit_count"], callback_data="cmd_sample_count"),
            InlineKeyboardButton(text=I18N[lang]["report_anomaly"], callback_data="cmd_eco_anomaly")
        ],
        [
            InlineKeyboardButton(text=I18N[lang]["send_location"], callback_data="cmd_send_gps"),
            InlineKeyboardButton(text=I18N[lang]["operator_ping"], callback_data="cmd_ping")
        ],
        [
            InlineKeyboardButton(text=I18N[lang]["my_reports_cmd"], callback_data="cmd_my_reports"),
            InlineKeyboardButton(text=I18N[lang]["switch_lang"], callback_data="cmd_switch_lang")
        ]
    ])

def get_cancel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=I18N[lang]["cancel_btn"], callback_data="cmd_cancel")]
    ])

# --- Start and language switching / 開始と言語切替 ---
@router.message(Command("start"))
@router.message(Command("cancel"))
async def cmd_start(message: Message, state: FSMContext):
    if not check_access(message.chat.id):
        # Show the real incoming ID right in the chat — the mismatch is
        # almost always a wrong/missing ADMIN_CHAT_ID in .env, and most
        # people don't have easy access to the server's console logs to see
        # the warning printed there. This puts the exact value they need
        # right in front of them.
        # 実際に届いたIDをそのままチャットに表示する — ほとんどの場合、
        # 原因は.envのADMIN_CHAT_IDが誤っている/未設定であるため。
        # サーバーのコンソールログを見られない人も多いので、必要な値を
        # そのままチャット上に出す。
        await message.answer(
            f"{I18N['en']['access_denied']}\n\n"
            f"Your chat ID is: <code>{message.chat.id}</code>\n"
            f"Put exactly this into .env as:\nADMIN_CHAT_ID={message.chat.id}\n"
            f"then restart bot.py.\n\n"
            f"あなたのchat IDは: <code>{message.chat.id}</code>\n"
            f".envに次のように設定してください:\nADMIN_CHAT_ID={message.chat.id}\n"
            f"その後 bot.py を再起動してください。",
            parse_mode="HTML"
        )
        return
    await state.clear()
    lang = get_lang(message.chat.id)

    # If this chat still has an old custom ReplyKeyboardMarkup pinned above
    # the text box (e.g. from an earlier bot version), an inline keyboard
    # sent afterwards does NOT replace or remove it — Telegram keeps both
    # visible until a message explicitly sends ReplyKeyboardRemove. Clear it
    # once here so old menus don't linger forever.
    # NOTE: Telegram rejects a message whose text is only a zero-width space
    # ("\u200b") with "Bad Request: text must be non-empty" — it must be a
    # real, visible character or two.
    # このチャットに古いカスタムReplyKeyboardMarkup（例: 以前のボット
    # バージョンのもの）がテキストボックス上部に残っている場合、後から
    # インラインキーボードを送っても置き換わらない/消えない —
    # ReplyKeyboardRemoveを明示的に送るまでTelegramは両方を表示し続ける。
    # 古いメニューが残り続けないよう、ここで一度だけクリアする。
    # 注意: ゼロ幅スペース（"\u200b"）のみのテキストはTelegram側で
    # 「Bad Request: text must be non-empty」として拒否される —
    # 実際に見える文字を含める必要がある。
    await message.answer("🔄", reply_markup=ReplyKeyboardRemove())

    await message.answer(
        I18N[lang]["welcome"],
        reply_markup=get_main_keyboard(lang),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "cmd_cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    await state.clear()
    lang = get_lang(callback.message.chat.id)
    await callback.message.edit_text(
        I18N[lang]["op_cancelled"],
        reply_markup=get_main_keyboard(lang)
    )

@router.callback_query(F.data == "cmd_switch_lang")
async def process_lang_menu(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="English 🇬🇧", callback_data="set_lang_en"),
            InlineKeyboardButton(text="日本語 🇯🇵", callback_data="set_lang_ja")
        ]
    ])
    await callback.message.edit_text(I18N["en"]["lang_select"], reply_markup=kb)

@router.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    selected_lang = callback.data.split("_")[-1]
    user_lang[callback.message.chat.id] = selected_lang  # persist choice / 選択を保存
    await callback.message.edit_text(
        I18N[selected_lang]["lang_set"],
        reply_markup=get_main_keyboard(selected_lang)
    )

# --- 1. Submit Samples / サンプル提出 ---
@router.callback_query(F.data == "cmd_sample_count")
async def start_sample_submission(callback: CallbackQuery, state: FSMContext):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    lang = get_lang(callback.message.chat.id)
    await callback.message.answer(
        I18N[lang]["ask_quadrat"],
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="Markdown"
    )
    await state.set_state(SurveyForm.waiting_for_quadrat)

@router.message(SurveyForm.waiting_for_quadrat)
async def process_quadrat_input(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    await state.update_data(quadrat=message.text.strip())
    await message.answer(
        I18N[lang]["ask_count"],
        reply_markup=get_cancel_keyboard(lang)
    )
    await state.set_state(SurveyForm.waiting_for_count)

@router.message(SurveyForm.waiting_for_count)
async def process_count_input(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    if not message.text.isdigit():
        await message.answer(
            I18N[lang]["invalid_number"],
            reply_markup=get_cancel_keyboard(lang)
        )
        return

    data = await state.get_data()
    quadrat = data.get("quadrat")
    count = int(message.text)

    await state.clear()
    text = I18N[lang]["sample_received"].format(quadrat=quadrat, count=count)
    await message.answer(text, reply_markup=get_main_keyboard(lang), parse_mode="Markdown")

# --- 2. Eco Anomaly (Native Telegram FSM) / 生態系異常報告 ---
@router.callback_query(F.data == "cmd_eco_anomaly")
async def start_native_anomaly_report(callback: CallbackQuery, state: FSMContext):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    # Species selection keyboard / 種の選択キーボード
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌿 Heracleum maximum", callback_data="species_heracleum")],
        [InlineKeyboardButton(text="🌱 Invasive Weed / 外来雑草", callback_data="species_weed")],
        [InlineKeyboardButton(text="❓ Other / その他", callback_data="species_other")],
        [InlineKeyboardButton(text="❌ Cancel / キャンセル", callback_data="cmd_cancel")]
    ])
    await callback.message.answer(
        "⚠️ <b>Eco Anomaly Report / 生態系異常報告</b>\n\nSelect the target species / 対象種を選択してください:",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.set_state(NativeAnomalyForm.waiting_for_species)

@router.callback_query(NativeAnomalyForm.waiting_for_species, F.data.startswith("species_"))
async def process_species(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    species_map = {
        "species_heracleum": "Heracleum maximum",
        "species_weed": "Invasive Weed",
        "species_other": "Unknown / Unidentified"
    }
    selected_species = species_map.get(callback.data, "Other")
    await state.update_data(species=selected_species)

    # Severity selection / 脅威レベルの選択
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟡 Low", callback_data="sev_Low"),
            InlineKeyboardButton(text="🟧 Medium", callback_data="sev_Medium"),
            InlineKeyboardButton(text="🟥 Critical", callback_data="sev_Critical")
        ],
        [InlineKeyboardButton(text="❌ Cancel / キャンセル", callback_data="cmd_cancel")]
    ])
    await callback.message.edit_text(
        f"Selected / 選択済: <b>{selected_species}</b>\n\nNow, select Threat Level / 脅威レベルを選択してください:",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.set_state(NativeAnomalyForm.waiting_for_severity)

@router.callback_query(NativeAnomalyForm.waiting_for_severity, F.data.startswith("sev_"))
async def process_severity(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    severity = callback.data.split("_")[1]
    await state.update_data(severity=severity)

    # Request GPS / GPSの要求
    loc_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Send Current Location / 現在地を送信", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.delete()
    await callback.message.answer(
        f"Severity / 脅威レベル: <b>{severity}</b>\n\nPlease send GPS location / 位置情報を送信してください:",
        reply_markup=loc_kb, parse_mode="HTML"
    )
    await state.set_state(NativeAnomalyForm.waiting_for_location)

@router.message(NativeAnomalyForm.waiting_for_location, F.location)
async def process_anomaly_location(message: Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lng=message.location.longitude)

    await message.answer(
        "📍 <b>Location saved! / 位置情報を保存しました。</b>\n\nEnter field notes / 現場のメモを入力してください:\n(Or type '-' to skip)",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await state.set_state(NativeAnomalyForm.waiting_for_notes)

@router.message(NativeAnomalyForm.waiting_for_notes)
async def process_anomaly_notes(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    await state.update_data(notes=message.text if message.text != '-' else "No notes provided")

    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=I18N[lang]["skip_btn"], callback_data="anomaly_skip_photo")],
        [InlineKeyboardButton(text=I18N[lang]["cancel_btn"], callback_data="cmd_cancel")]
    ])
    await message.answer(I18N[lang]["ask_photo"], reply_markup=skip_kb)
    await state.set_state(NativeAnomalyForm.waiting_for_photo)


@router.message(NativeAnomalyForm.waiting_for_photo, F.photo)
async def process_anomaly_photo(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    # message.photo is a list of the same image at increasing resolutions —
    # the last one is the largest / message.photoは同じ画像の解像度違いの
    # リストで、最後の要素が最大サイズ
    await state.update_data(photo_file_id=message.photo[-1].file_id, media_type="photo")
    await message.answer(I18N[lang]["photo_saved"])
    await show_anomaly_confirmation(message, state, lang)


@router.message(NativeAnomalyForm.waiting_for_photo, F.video)
async def process_anomaly_video(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    await state.update_data(photo_file_id=message.video.file_id, media_type="video")
    await message.answer(I18N[lang]["photo_saved"])
    await show_anomaly_confirmation(message, state, lang)


@router.callback_query(NativeAnomalyForm.waiting_for_photo, F.data == "anomaly_skip_photo")
async def process_anomaly_skip_photo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = get_lang(callback.message.chat.id)
    await show_anomaly_confirmation(callback.message, state, lang)


async def show_anomaly_confirmation(message: Message, state: FSMContext, lang: str):
    data = await state.get_data()
    summary = I18N[lang]["confirm_summary"].format(
        species=data.get("species", "Unknown"),
        severity=data.get("severity", "Low"),
        lat=data.get("lat", 0.0),
        lng=data.get("lng", 0.0),
        photo_status=I18N[lang]["photo_yes"] if data.get("photo_file_id") else I18N[lang]["photo_no"],
        notes=data.get("notes", ""),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=I18N[lang]["confirm_btn"], callback_data="anomaly_confirm")],
        [InlineKeyboardButton(text=I18N[lang]["edit_notes_btn"], callback_data="anomaly_edit_notes")],
        [InlineKeyboardButton(text=I18N[lang]["cancel_btn"], callback_data="cmd_cancel")]
    ])
    await message.answer(summary, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(NativeAnomalyForm.waiting_for_confirmation)


@router.callback_query(NativeAnomalyForm.waiting_for_confirmation, F.data == "anomaly_edit_notes")
async def process_anomaly_edit_notes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = get_lang(callback.message.chat.id)
    await callback.message.answer(I18N[lang]["reenter_notes"])
    await state.set_state(NativeAnomalyForm.waiting_for_notes)


@router.callback_query(NativeAnomalyForm.waiting_for_confirmation, F.data == "anomaly_confirm")
async def process_anomaly_confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = get_lang(callback.message.chat.id)
    data = await state.get_data()
    await state.clear()
    await submit_anomaly_report(callback.message, lang, data)


async def submit_anomaly_report(message: Message, lang: str, data: dict):
    """POST a completed anomaly report to the FastAPI backend (which then
    pushes it to Telegram itself, photo included). Shared by the normal FSM
    flow and anything else that finishes an anomaly report.
    完成した異常報告をFastAPIバックエンドへPOSTする（写真も含め、
    バックエンド側からTelegramへも通知される）。通常のFSMフローなど、
    異常報告を完了させる処理から共通で呼び出される。"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(BACKEND_ANOMALY_URL, json=data, timeout=10) as response:
                if response.status in (200, 201):
                    await message.answer(I18N[lang]["anomaly_synced"], reply_markup=get_main_keyboard(lang), parse_mode="HTML")
                else:
                    await message.answer(I18N[lang]["anomaly_sync_failed"], reply_markup=get_main_keyboard(lang))
    except Exception as e:
        await message.answer(I18N[lang]["anomaly_unreachable"].format(error=e), reply_markup=get_main_keyboard(lang))

# --- 3. Update GPS coordinates / GPS座標の更新 ---
@router.callback_query(F.data == "cmd_send_gps")
async def request_gps_location(callback: CallbackQuery, state: FSMContext):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    lang = get_lang(callback.message.chat.id)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=I18N[lang]["gps_btn"], request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await callback.message.answer(I18N[lang]["ask_gps"], reply_markup=kb)
    await state.set_state(LocationForm.waiting_for_gps)

@router.message(LocationForm.waiting_for_gps, F.location)
async def process_location_received(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    lat = message.location.latitude
    lon = message.location.longitude

    await state.clear()
    await message.answer(
        I18N[lang]["gps_received"].format(lat=lat, lon=lon),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    await message.answer(I18N[lang]["welcome"], reply_markup=get_main_keyboard(lang))

# --- 4. Field Check-in / 現場チェックイン ---
@router.callback_query(F.data == "cmd_ping")
async def process_operator_ping(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    lang = get_lang(callback.message.chat.id)
    await callback.message.answer(I18N[lang]["ping_logged"], parse_mode="Markdown")

# --- 5. My Reports: list + change location / status / delete ---
# --- 5. 過去の報告: 一覧 + 位置変更・ステータス変更・削除 ---
STATUS_ICONS = {"Reported": "🆕", "Investigating": "🔎", "Resolved": "✅"}


def report_card_text(lang: str, report: dict) -> str:
    status = report.get("status", "Reported")
    icon = STATUS_ICONS.get(status, "🆕")
    return (
        f"{icon} <b>#{report.get('id')}</b> — {report.get('species', 'Unknown')}\n"
        f"🚨 {report.get('severity', 'Low')} | 🗺️ [{report.get('sector', 'N/A')}] | 📌 {status}\n"
        f"📍 {report.get('lat')}, {report.get('lng')}\n"
        f"🔍 {report.get('notes', '')}"
    )


def report_card_keyboard(lang: str, report_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=I18N[lang]["status_investigating_btn"], callback_data=f"statusinv_{report_id}"),
            InlineKeyboardButton(text=I18N[lang]["status_resolved_btn"], callback_data=f"statusres_{report_id}"),
        ],
        [
            InlineKeyboardButton(text=I18N[lang]["editloc_btn"], callback_data=f"editloc_{report_id}"),
            InlineKeyboardButton(text=I18N[lang]["delete_btn"], callback_data=f"delanomaly_{report_id}"),
        ],
    ])


async def fetch_anomalies() -> list:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BACKEND_ANOMALY_URL, timeout=5) as response:
                if response.status == 200:
                    return await response.json()
    except Exception as e:
        logging.warning(f"Failed to fetch anomalies / 異常報告の取得に失敗: {e}")
    return []


async def show_my_reports(message: Message, lang: str):
    reports = await fetch_anomalies()
    if not reports:
        await message.answer(I18N[lang]["my_reports_empty"], reply_markup=get_main_keyboard(lang))
        return

    await message.answer(I18N[lang]["my_reports_header"], parse_mode="Markdown")
    for report in reports[-5:][::-1]:  # last 5, most recent first / 直近5件を新しい順に
        await message.answer(
            report_card_text(lang, report),
            reply_markup=report_card_keyboard(lang, report.get("id")),
            parse_mode="HTML"
        )


@router.message(Command("myreports"))
async def cmd_my_reports_text(message: Message):
    if not check_access(message.chat.id):
        await message.answer(I18N["en"]["access_denied"])
        return
    await show_my_reports(message, get_lang(message.chat.id))


@router.callback_query(F.data == "cmd_my_reports")
async def cmd_my_reports_callback(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    await callback.answer()
    await show_my_reports(callback.message, get_lang(callback.message.chat.id))


@router.callback_query(F.data.startswith("statusinv_") | F.data.startswith("statusres_"))
async def process_status_change(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    lang = get_lang(callback.message.chat.id)
    report_id = callback.data.split("_", 1)[1]
    new_status = "Investigating" if callback.data.startswith("statusinv_") else "Resolved"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(f"{BACKEND_ANOMALY_URL}/{report_id}/status", json={"status": new_status}, timeout=5) as response:
                if response.status == 200:
                    await callback.answer(I18N[lang]["status_updated"].format(status=new_status))
                    data = (await response.json()).get("data", {})
                    await callback.message.edit_text(
                        report_card_text(lang, data or {"id": report_id, "status": new_status}),
                        reply_markup=report_card_keyboard(lang, report_id),
                        parse_mode="HTML"
                    )
                else:
                    await callback.answer(I18N[lang]["not_found"], show_alert=True)
    except Exception as e:
        await callback.answer(f"⚠️ {e}", show_alert=True)


@router.callback_query(F.data.startswith("delanomaly_") & ~F.data.startswith("delanomaly_yes_") & ~F.data.startswith("delanomaly_no_"))
async def process_delete_prompt(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    lang = get_lang(callback.message.chat.id)
    report_id = callback.data.split("_", 1)[1]
    await callback.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=I18N[lang]["delete_yes"], callback_data=f"delanomaly_yes_{report_id}"),
        InlineKeyboardButton(text=I18N[lang]["delete_no"], callback_data=f"delanomaly_no_{report_id}"),
    ]])
    await callback.message.edit_text(I18N[lang]["delete_confirm"], reply_markup=kb)


@router.callback_query(F.data.startswith("delanomaly_no_"))
async def process_delete_cancel(callback: CallbackQuery):
    lang = get_lang(callback.message.chat.id)
    report_id = callback.data.split("_", 2)[2]
    await callback.answer()
    reports = await fetch_anomalies()
    report = next((r for r in reports if str(r.get("id")) == report_id), None)
    if report:
        await callback.message.edit_text(
            report_card_text(lang, report), reply_markup=report_card_keyboard(lang, report_id), parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(I18N[lang]["not_found"])


@router.callback_query(F.data.startswith("delanomaly_yes_"))
async def process_delete_confirmed(callback: CallbackQuery):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    lang = get_lang(callback.message.chat.id)
    report_id = callback.data.split("_", 2)[2]
    await callback.answer()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"{BACKEND_ANOMALY_URL}/{report_id}", timeout=5) as response:
                if response.status == 200:
                    await callback.message.edit_text(I18N[lang]["deleted_ok"])
                else:
                    await callback.message.edit_text(I18N[lang]["not_found"])
    except Exception as e:
        await callback.message.edit_text(f"⚠️ {e}")


@router.callback_query(F.data.startswith("editloc_"))
async def process_editloc_prompt(callback: CallbackQuery, state: FSMContext):
    if not check_access(callback.message.chat.id):
        await callback.answer(I18N["en"]["access_denied"], show_alert=True)
        return
    lang = get_lang(callback.message.chat.id)
    report_id = callback.data.split("_", 1)[1]
    await callback.answer()

    await state.update_data(editing_anomaly_id=report_id)
    await state.set_state(EditAnomalyLocationForm.waiting_for_new_location)

    loc_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=I18N[lang]["gps_btn"], request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.answer(I18N[lang]["ask_new_location"], reply_markup=loc_kb)


@router.message(EditAnomalyLocationForm.waiting_for_new_location, F.location)
async def process_editloc_received(message: Message, state: FSMContext):
    lang = get_lang(message.chat.id)
    data = await state.get_data()
    report_id = data.get("editing_anomaly_id")
    await state.clear()

    lat, lng = message.location.latitude, message.location.longitude

    reports = await fetch_anomalies()
    report = next((r for r in reports if str(r.get("id")) == str(report_id)), None)
    if not report:
        await message.answer(I18N[lang]["not_found"], reply_markup=ReplyKeyboardRemove())
        return

    payload = {
        "species": report.get("species"),
        "severity": report.get("severity"),
        "sector": None,  # let the backend recompute it for the new coordinates / バックエンド側で再計算させる
        "lat": lat,
        "lng": lng,
        "notes": report.get("notes"),
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(f"{BACKEND_ANOMALY_URL}/{report_id}", json=payload, timeout=5) as response:
                if response.status == 200:
                    updated = (await response.json()).get("data", report)
                    await message.answer(I18N[lang]["location_updated"], reply_markup=ReplyKeyboardRemove())
                    await message.answer(
                        report_card_text(lang, updated), reply_markup=report_card_keyboard(lang, report_id), parse_mode="HTML"
                    )
                else:
                    await message.answer(I18N[lang]["not_found"], reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        await message.answer(f"⚠️ {e}", reply_markup=ReplyKeyboardRemove())
