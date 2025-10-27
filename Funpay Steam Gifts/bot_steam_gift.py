from __future__ import annotations

import os
import re
import time
import json
import logging
import threading
from typing import Optional, Dict, Tuple, Any, List

import requests
from dotenv import load_dotenv

from FunPayAPI import Account
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater.events import NewOrderEvent, NewMessageEvent

load_dotenv()

FUNPAY_AUTH_TOKEN = os.getenv("FUNPAY_AUTH_TOKEN")

RAW_IDS = os.getenv("CATEGORY_IDS") or os.getenv("CATEGORY_ID") or ""
CATEGORY_IDS: List[int] = []
for t in re.split(r"[,\s;]+", RAW_IDS.strip()):
    if not t:
        continue
    try:
        CATEGORY_IDS.append(int(t))
    except Exception:
        pass

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(float(v))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default

AUTO_REFUND = _env_bool("AUTO_REFUND", True)
STRICT_SILENT_SKIP = _env_bool("STRICT_SILENT_SKIP", False)

STEAM_API_USER = os.getenv("STEAM_API_USER") or ""
STEAM_API_PASS = os.getenv("STEAM_API_PASS") or ""
TOKEN_REFRESH_SECONDS = _env_int("TOKEN_REFRESH_SECONDS", 3600)
MIN_PROVIDER_BALANCE = _env_float("MIN_PROVIDER_BALANCE", 5.0)

FRIEND_LINK_HINT_URL = os.getenv("FRIEND_LINK_HINT_URL", "https://s.team/p")
STEAM_API_BASE = "https://xn--h1aahgceagbyl.xn--p1ai/api"

CREATOR_NAME = os.getenv("CREATOR_NAME", "@tinechelovec")
CREATOR_URL = os.getenv("CREATOR_URL", "https://t.me/tinechelovec")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/by_thc")
GITHUB_URL = os.getenv("GITHUB_URL", "https://github.com/tinechelovec/Funpay-Steam-Gifts")
BANNER_NOTE = os.getenv(
    "BANNER_NOTE",
    "Бот бесплатный и с открытым исходным кодом на GitHub. "
    "Создатель бота его НЕ продаёт. Если вы где-то видите платную версию — "
    "это решение перепродавца, к автору отношения не имеет."
)

LOG_NAME = "SteamGifts"

class LevelEmojiFilter(logging.Filter):
    MAP = {"DEBUG": "🐞", "INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "💥"}
    def filter(self, record: logging.LogRecord) -> bool:
        record.level_emoji = self.MAP.get(record.levelname, "•")
        return True

class PrettyConsoleFilter(logging.Filter):
    _ORDER_RE = re.compile(r"\[ORDER ([^\]]+)\]")
    _CYN = "\033[36m"; _RST = "\033[0m"; _RED = "\033[31m"
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            msg = self._ORDER_RE.sub(lambda m: f"{self._CYN}[ORDER {m.group(1)}]{self._RST}", msg)
            msg = (msg
                   .replace("Провайдер баланс", "💰 Провайдер баланс")
                   .replace("Найдена friend-link", "🔗 Найдена friend-link")
                   .replace("Запросил у покупателя friend-link", "📨 Запросил у покупателя friend-link")
                   .replace("Create order", "🧾 Create order")
                   .replace("Pay order", "💳 Pay order")
                   .replace("Успешно оформлен и оплачен", "✅ Успешно оформлен и оплачен")
                   .replace("FAILED", f"{self._RED}FAILED{self._RST}")
            )
            record.msg, record.args = msg, ()
        except Exception:
            pass
        return True

try:
    import colorlog
    logger = colorlog.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)

    console_handler = colorlog.StreamHandler()
    console_handler.addFilter(LevelEmojiFilter())
    console_handler.addFilter(PrettyConsoleFilter())
    console_formatter = colorlog.ColoredFormatter(
        fmt="%(cyan)s%(asctime)s%(reset)s %(level_emoji)s "
            "%(log_color)s[%(levelname)-5s]%(reset)s "
            "%(bold_blue)s" + LOG_NAME + "%(reset)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        style="%",
    )
    console_handler.setFormatter(console_formatter)

    file_handler = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

except Exception:
    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.handlers.clear()
    logger.addHandler(ch)
    logger.addHandler(fh)

try:
    import colorlog
    logger = colorlog.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)

    console_handler = colorlog.StreamHandler()
    console_formatter = colorlog.ColoredFormatter(
        fmt="%(cyan)s%(asctime)s%(reset)s %(log_color)s[%(levelname)-5s]%(reset)s %(bold_blue)s" + LOG_NAME + "%(reset)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        secondary_log_colors={
            "asctime": {"*": "cyan"},
            "name": {"*": "bold_blue"},
        },
        style="%"
    )
    console_handler.setFormatter(console_formatter)

    file_handler = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

except Exception:
    logger = logging.getLogger(LOG_NAME)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] " + LOG_NAME + ": %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.handlers.clear()
    logger.addHandler(ch)
    logger.addHandler(fh)

RED = "\033[31m"
BRIGHT_CYAN = "\033[96m"
RESET = "\033[0m"

def _log_banner_free():
    border = "═" * 85
    try:
        logger.info(f"{RED}{border}{RESET}")
        logger.info(f"{RED}Информация о проекте / Steam Gifts Bot{RESET}")
        logger.info(f"{RED}{border}{RESET}")

        line = f"{RED}Создатель: {CREATOR_NAME}"
        if CREATOR_URL:
            line += f" | Контакт: {BRIGHT_CYAN}{CREATOR_URL}{RED}"
        logger.info(line + RESET)

        if CHANNEL_URL:
            logger.info(f"{RED}Канал: {BRIGHT_CYAN}{CHANNEL_URL}{RESET}")

        if GITHUB_URL:
            logger.info(f"{RED}GitHub: {BRIGHT_CYAN}{GITHUB_URL}{RESET}")

        logger.info(f"{RED}Дисклеймер: {BANNER_NOTE}{RESET}")
        logger.info(f"{RED}{border}{RESET}")
    except Exception:
        logger.info("===============================================")
        logger.info("Информация о проекте / Steam Gifts Bot")
        logger.info(f"Создатель: {CREATOR_NAME} {(' | ' + CREATOR_URL) if CREATOR_URL else ''}")
        if CHANNEL_URL:
            logger.info(f"Канал: {CHANNEL_URL}")
        if GITHUB_URL:
            logger.info(f"GitHub: {GITHUB_URL}")
        logger.info(f"Дисклеймер: {BANNER_NOTE}")
        logger.info("===============================================")

def _log_settings():
    logger.info("⚙️  Настройки:")
    logger.info(f"    AUTO_REFUND            = {AUTO_REFUND}")
    logger.info(f"    STEAM_API_USER/PASS    = {'OK' if (STEAM_API_USER and STEAM_API_PASS) else 'MISSING'}")

HERE = os.path.abspath(os.path.dirname(__file__))
ITEMS_JSON_PATH = os.path.join(HERE, "steam_gifts.json")

REGION_CHOICES = {"RU", "UA", "KZ"}

def _load_items_fallback() -> Dict[str, dict]:
    if not os.path.exists(ITEMS_JSON_PATH):
        return {}
    try:
        with open(ITEMS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        out: Dict[str, dict] = {}
        for k, v in data.items():
            out[str(k)] = {
                "title": v.get("title") or f"Item {k}",
                "region": (v.get("region") or "RU").upper(),
                "app_id": v.get("app_id"),
                "sub_id": v.get("sub_id"),
                "notes": v.get("notes") or "",
                "last_price": v.get("last_price"),
                "currency": v.get("currency"),
            }
        return out
    except Exception:
        return {}

_resolve_order_params = None
_load_items_api = None
try:
    from steam_settings_id import resolve_order_params as _resolve_order_params
    from steam_settings_id import load_items as _load_items_api
except Exception:
    try:
        from steam_settings_id import resolve_order_params as _resolve_order_params
        from steam_settings_id import load_items as _load_items_api
    except Exception:
        _resolve_order_params = None
        _load_items_api = None

def _resolve_item_from_id(funpay_key: str) -> Tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    if _resolve_order_params and _load_items_api:
        try:
            items = _load_items_api()
            sub_id, region = _resolve_order_params(funpay_key, items)
            meta = items.get(str(funpay_key))
            title = (getattr(meta, "title", None) if meta is not None else None) or (meta.get("title") if isinstance(meta, dict) else None)
            notes = (getattr(meta, "notes", None) if meta is not None else None) or (meta.get("notes") if isinstance(meta, dict) else None)
            return int(sub_id), str(region), title, notes
        except Exception:
            pass
    data = _load_items_fallback()
    node = data.get(str(funpay_key))
    if not node:
        return None, None, None, None
    sub_id = node.get("sub_id")
    region = (node.get("region") or "").upper()
    if not sub_id or region not in REGION_CHOICES:
        return None, None, None, None
    return int(sub_id), region, node.get("title"), node.get("notes")

STEAM_GIFT_REGEX = re.compile(
    r"(?i)\bsteam(?:[._\s-]*gift|[._\s-]*gift)\b\s*[:=]?\s*([0-9]{1,10})"
)

def find_gift_key(text: str) -> Optional[str]:
    if not text:
        return None
    m = STEAM_GIFT_REGEX.search(text)
    if not m:
        return None
    return m.group(1)

FRIEND_LINK_RE = re.compile(
    r"(https?://\S*?(?:s\.team/[^ \n\r\t]+|steamcommunity\.com/(?:id|profiles)/[^ \n\r\t/]+))",
    flags=re.IGNORECASE
)

def extract_friend_link(text: str) -> Optional[str]:
    if not text:
        return None
    m = FRIEND_LINK_RE.search(text)
    if m:
        return m.group(1)
    return None

STEAM_TOKEN: Optional[str] = None
_STEAM_TOKEN_LOCK = threading.Lock()

def _steam_headers() -> dict:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {STEAM_TOKEN}" if STEAM_TOKEN else ""
    }

def _obtain_token() -> Optional[str]:
    if not STEAM_API_USER or not STEAM_API_PASS:
        return None
    try:
        r = requests.post(
            f"{STEAM_API_BASE}/token",
            json={"username": STEAM_API_USER, "password": STEAM_API_PASS},
            headers={"accept": "application/json", "content-type": "application/json"},
            timeout=20
        )
        if r.status_code >= 400:
            return None
        try:
            data = r.json()
        except Exception:
            data = {}
        tok = data.get("access_token") or data.get("token") or r.text.strip()
        return tok or None
    except Exception:
        return None

def _ensure_token():
    global STEAM_TOKEN
    if STEAM_TOKEN:
        return
    with _STEAM_TOKEN_LOCK:
        if not STEAM_TOKEN:
            STEAM_TOKEN = _obtain_token()

def _refresh_token_loop(period_sec: int):
    while True:
        try:
            time.sleep(max(60, period_sec))
            tok = _obtain_token()
            if tok:
                with _STEAM_TOKEN_LOCK:
                    globals()["STEAM_TOKEN"] = tok
                logger.info("[AUTH] Токен обновлён планово.")
        except Exception:
            pass

def start_token_refresher():
    if TOKEN_REFRESH_SECONDS <= 0:
        return
    t = threading.Thread(target=_refresh_token_loop, args=(TOKEN_REFRESH_SECONDS,), daemon=True)
    t.start()

def _api_post(path: str, payload: dict, retry: bool = True) -> requests.Response:
    _ensure_token()
    url = f"{STEAM_API_BASE}{path}"
    resp = requests.post(url, json=payload, headers=_steam_headers(), timeout=25)
    if resp.status_code in (401, 403) and retry:
        with _STEAM_TOKEN_LOCK:
            globals()["STEAM_TOKEN"] = None
        _ensure_token()
        resp = requests.post(url, json=payload, headers=_steam_headers(), timeout=25)
    return resp

def _safe_json(resp: requests.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": (resp.text or "")}

def api_check_balance() -> float:
    try:
        r = _api_post("/check_balance", {})
        data = _safe_json(r)
        if isinstance(data, dict):
            bal = data.get("balance") or data.get("usd") or data.get("amount") or data.get("raw")
        else:
            bal = data
        return float(bal)
    except Exception:
        return 0.0

def api_calculate_price(sub_id: int, region: str) -> Tuple[bool, int, str, dict]:
    payload = {"sub_id": str(sub_id), "region": region}
    try:
        r = _api_post("/steam_gift_calculate", payload)
        data = _safe_json(r)
        status = r.status_code
        ok = (status == 200)
        msg = data.get("message") or data.get("detail") or (r.text or "")
        return ok, status, msg, data
    except Exception as e:
        return False, -1, f"Exception: {e}", {"exception": str(e)}

def api_create_order(friend_link: str, sub_id: int, region: str, gift_name: str = "-", gift_desc: str = "-") -> Tuple[bool, int, str, dict]:
    payload = {
        "friend_link": friend_link,
        "sub_id": str(sub_id),
        "region": region,
        "gift_name": gift_name or "-",
        "gift_description": gift_desc or "-"
    }
    try:
        r = _api_post("/steam_gift_create_order", payload)
        data = _safe_json(r)
        status = r.status_code
        ok = (status == 200)
        msg = data.get("message") or data.get("detail") or (r.text or "")
        return ok, status, msg, data
    except Exception as e:
        return False, -1, f"Exception: {e}", {"exception": str(e)}

def api_pay_order(custom_id: str) -> Tuple[bool, int, str, dict]:
    try:
        r = _api_post("/steam_gift_pay_order", {"custom_id": str(custom_id)})
        data = _safe_json(r)
        status = r.status_code
        ok = (status == 200)
        msg = data.get("message") or data.get("detail") or (r.text or "")
        return ok, status, msg, data
    except Exception as e:
        return False, -1, f"Exception: {e}", {"exception": str(e)}

def get_subcategory_id_safe(order, account) -> Tuple[Optional[int], Optional[object]]:
    subcat = getattr(order, "subcategory", None) or getattr(order, "sub_category", None)
    if subcat and hasattr(subcat, "id"):
        return subcat.id, subcat
    try:
        full_order = account.get_order(order.id)
        subcat = getattr(full_order, "subcategory", None) or getattr(full_order, "sub_category", None)
        if subcat and hasattr(subcat, "id"):
            return subcat.id, subcat
    except Exception:
        pass
    return None, None

STATE: Dict[int, dict] = {}

def order_url(oid: Any) -> str:
    try:
        return f"https://funpay.com/orders/{int(oid)}/"
    except Exception:
        return "https://funpay.com/orders/"

def handle_new_order(account: Account, order):
    oid = getattr(order, "id", None)
    buyer = getattr(order, "buyer_id", None)

    subcat_id, _ = get_subcategory_id_safe(order, account)
    if not subcat_id or (CATEGORY_IDS and subcat_id not in CATEGORY_IDS):
        logger.info(f"[ORDER {oid}] Подкатегория {subcat_id} не в списке — пропускаю.")
        return

    desc = (
        getattr(order, "full_description", None)
        or getattr(order, "short_description", None)
        or getattr(order, "title", None)
        or ""
    )
    key = find_gift_key(str(desc))
    if not key:
        logger.info(f"[ORDER {oid}] Маркер steamgift не найден в описании — пропускаю.")
        return

    logger.info(f"[ORDER {oid}] Найден маркер steamgift -> key={key}")

    sub_id, region, title, notes = _resolve_item_from_id(key)
    if not sub_id or not region:
        logger.info(f"[ORDER {oid}] Товар по key={key} не найден в steam_gifts.json — пропускаю.")
        return

    logger.info(f"[ORDER {oid}] Резолв OK: SUB_ID={sub_id}, REGION={region}, TITLE={title or '-'}")

    text_all = " ".join([str(getattr(order, f, "") or "") for f in ("full_description", "short_description", "title")])
    friend_link = extract_friend_link(text_all)

    chat_id = getattr(order, "chat_id", None)
    if not buyer or not chat_id:
        logger.info(f"[ORDER {oid}] Нет buyer/chat_id — пропускаю.")
        return

    STATE[buyer] = {
        "step": "got_order",
        "order_id": oid,
        "chat_id": chat_id,
        "funpay_key": key,
        "sub_id": sub_id,
        "region": region,
        "title": title or f"Steam package {sub_id}",
        "notes": notes or "-",
    }

    if friend_link:
        STATE[buyer]["friend_link"] = friend_link
        logger.info(f"[ORDER {oid}] Найдена friend-link: {friend_link}")
        proceed_create_and_pay(account, buyer)
        return

    account.send_message(
        chat_id,
        (
            f"Спасибо за заказ!\n\n"
            f"Вы купили: {STATE[buyer]['title']} (регион: {STATE[buyer]['region']}).\n"
            "Чтобы отправить подарок, нужна ссылка для добавления в друзья (friend-link).\n"
            "Её можно сгенерировать в Steam → Add a Friend → Create Invite Link.\n\n"
            f"Пришлите ссылку вида: {FRIEND_LINK_HINT_URL}/… или ссылку на ваш профиль Steam."
        )
    )
    logger.info(f"[ORDER {oid}] Запросил у покупателя friend-link.")

def _on_provider_failure(account: Account, chat_id: int, order_id: Any, http_status: int, body_preview: str, stage: str):
    logger.error(f"[ORDER {order_id}] {stage} FAILED: HTTP {http_status}; body: {body_preview}")
    if AUTO_REFUND:
        try:
            account.send_message(
                chat_id,
                f"На стороне сервиса выдачи подарков возникла временная проблема (HTTP {http_status}). Средства будут возвращены."
            )
            account.refund(order_id)
            logger.info(f"[ORDER {order_id}] Оформлён возврат покупателю.")
        except Exception as e:
            logger.error(f"[ORDER {order_id}] Ошибка при возврате: {e}")
    else:
        try:
            account.send_message(
                chat_id,
                f"На стороне сервиса выдачи подарков возникла временная проблема (HTTP {http_status}). Автовозврат выключен — свяжитесь с продавцом."
            )
        except Exception:
            pass

def proceed_create_and_pay(account: Account, buyer_id: int):
    st = STATE.get(buyer_id) or {}
    chat_id = st.get("chat_id")
    order_id = st.get("order_id")
    sub_id = st.get("sub_id")
    region = st.get("region")
    friend_link = st.get("friend_link")
    title = st.get("title") or "-"
    notes = st.get("notes") or "-"

    if not (chat_id and order_id and sub_id and region and friend_link):
        logger.info(f"[ORDER {order_id}] Недостаточно данных для оформления (chat_id/sub_id/region/link).")
        return

    try:
        bal = api_check_balance()
    except Exception:
        bal = 0.0
    logger.info(f"[ORDER {order_id}] Провайдер баланс: {bal} USD")

    calc_ok, calc_status, calc_msg, calc_data = api_calculate_price(sub_id, region)
    if calc_ok:
        try:
            need = float(calc_data.get("total") or calc_data.get("price") or 0.0)
        except Exception:
            need = 0.0
        if need > 0 and bal + 1e-9 < need:
            body = f"insufficient funds: balance={bal} < need={need}"
            logger.info(f"[ORDER {order_id}] {body}")
            _on_provider_failure(account, chat_id, order_id, 402, body, stage="PRECHECK")
            STATE.pop(buyer_id, None)
            return
    else:
        logger.info(f"[ORDER {order_id}] Calculate failed (http={calc_status}): {str(calc_msg)[:300]} -- продолжаю без предчека.")

    ok, status, msg, data = api_create_order(friend_link, sub_id, region, gift_name=title, gift_desc=notes)
    body_preview = (msg or json.dumps(data, ensure_ascii=False))[:500]
    logger.info(f"[ORDER {order_id}] Create order -> ok={ok}, http={status}, msg={body_preview}")
    if not ok:
        _on_provider_failure(account, chat_id, order_id, status, body_preview, stage="CREATE")
        STATE.pop(buyer_id, None)
        return

    try:
        created_need = float(data.get("total") or 0.0)
    except Exception:
        created_need = 0.0
    if created_need > 0 and bal + 1e-9 < created_need:
        body = f"insufficient funds after CREATE: balance={bal} < total={created_need}"
        logger.warning(f"[ORDER {order_id}] {body}")
        _on_provider_failure(account, chat_id, order_id, 402, body, stage="CREATE(funds)")
        STATE.pop(buyer_id, None)
        return

    custom_id = None
    for k in ("custom_id", "id", "order_id", "customId"):
        if k in data:
            custom_id = str(data[k])
            break
    if not custom_id:
        raw = data.get("raw") if isinstance(data, dict) else None
        if raw:
            m = re.search(r"[0-9a-fA-F-]{8,}", str(raw))
            if m:
                custom_id = m.group(0)
    if not custom_id:
        _on_provider_failure(account, chat_id, order_id, 520, "missing custom_id", stage="CREATE(no id)")
        STATE.pop(buyer_id, None)
        return

    def _pay_once():
        return api_pay_order(custom_id)

    ok2, status2, msg2, data2 = _pay_once()
    body_preview2 = (msg2 or json.dumps(data2, ensure_ascii=False))[:500]
    logger.info(f"[ORDER {order_id}] Pay order -> ok={ok2}, http={status2}, msg={body_preview2}")

    if not ok2 and status2 in (500, 502, 503, 504):
        time.sleep(2.0)
        logger.info(f"[ORDER {order_id}] Pay retry after transient error {status2}...")
        ok2, status2, msg2, data2 = _pay_once()
        body_preview2 = (msg2 or json.dumps(data2, ensure_ascii=False))[:500]
        logger.info(f"[ORDER {order_id}] Pay order (retry) -> ok={ok2}, http={status2}, msg={body_preview2}")

    if not ok2:
        _on_provider_failure(account, chat_id, order_id, status2, body_preview2, stage="PAY")
        STATE.pop(buyer_id, None)
        return

    link = order_url(order_id)
    account.send_message(
        chat_id,
        (
            "Готово! Заказ на подарок создан и оплачен.\n\n"
            "Примите запрос в друзья в Steam — после этого подарок будет отправлен.\n"
            f"Ссылка на ваш заказ: {link}\n\n"
            "Пожалуйста, оставьте отзыв — это очень помогает!"
        )
    )
    logger.info(f"[ORDER {order_id}] Успешно оформлен и оплачен. Сообщение отправлено покупателю.")
    STATE.pop(buyer_id, None)

def handle_new_message(account: Account, message):
    user_id = getattr(message, "author_id", None)
    chat_id = getattr(message, "chat_id", None)
    text = getattr(message, "text", None) or ""
    if not (user_id and chat_id and text.strip()):
        return

    st = STATE.get(user_id)
    if not st:
        return

    order_id = st.get("order_id")

    if "friend_link" not in st:
        link = extract_friend_link(text)
        if not link:
            account.send_message(
                chat_id,
                (
                    "Похоже, ссылка не распознана.\n"
                    f"Пришлите friend-link вида {FRIEND_LINK_HINT_URL}/… или ссылку на профиль Steam "
                    "(steamcommunity.com/id/... или steamcommunity.com/profiles/...)."
                )
            )
            logger.info(f"[ORDER {order_id}] Покупатель прислал невалидный friend-link.")
            return
        st["friend_link"] = link
        logger.info(f"[ORDER {order_id}] Получен friend-link от покупателя: {link}")
        proceed_create_and_pay(account, user_id)
        return

def main():
    if not FUNPAY_AUTH_TOKEN:
        raise RuntimeError("FUNPAY_AUTH_TOKEN не найден в .env")

    _log_banner_free()
    _log_settings()

    start_token_refresher()

    account = Account(FUNPAY_AUTH_TOKEN)
    account.get()
    logger.info(f"Авторизован на FunPay как @{getattr(account, 'username', '(unknown)')}")

    runner = Runner(account)
    logger.info("🚀 Steam Gifts Bot запущен. Ожидаю события FunPay...")

    for event in runner.listen(requests_delay=3.0):
        try:
            if isinstance(event, NewOrderEvent):
                order = account.get_order(event.order.id)
                handle_new_order(account, order)
            elif isinstance(event, NewMessageEvent):
                if getattr(event, "message", None) is not None:
                    handle_new_message(account, event.message)
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")

if __name__ == "__main__":
    main()
