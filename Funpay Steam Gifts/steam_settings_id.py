from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import requests

HERE = Path(__file__).resolve().parent
ITEMS_JSON = HERE / "steam_gifts.json"
DOTENV_PATHS = [HERE / ".env", Path.cwd() / ".env"]

API_BASE = "https://xn--h1aahgceagbyl.xn--p1ai/api"
STEAM_STORE_API = "https://store.steampowered.com/api/appdetails"

CANCEL_TOKENS = {"0", "q", "й", "exit", "quit", "выход", "назад", "отмена", "cancel", "back"}
REGION_CHOICES = {"RU", "UA", "KZ"}

ENV_NOTICE_SHOWN = False
_LAST_SUB_LABEL: Optional[str] = None

@dataclass
class SteamGiftItem:
    key: str
    title: str
    region: str
    app_id: Optional[int] = None
    sub_id: Optional[int] = None
    notes: str = ""
    last_price: Optional[float] = None
    currency: Optional[str] = None

def load_items() -> Dict[str, SteamGiftItem]:
    if ITEMS_JSON.exists():
        with ITEMS_JSON.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, SteamGiftItem] = {}
        for k, v in raw.items():
            out[str(k)] = SteamGiftItem(
                key=str(k),
                title=v.get("title", f"Item {k}"),
                region=v.get("region", "RU"),
                app_id=v.get("app_id"),
                sub_id=v.get("sub_id"),
                notes=v.get("notes", ""),
                last_price=v.get("last_price"),
                currency=v.get("currency"),
            )
        return out
    return {}

def save_items(items: Dict[str, SteamGiftItem]) -> None:
    payload = {
        k: {
            "title": it.title,
            "region": it.region,
            "app_id": it.app_id,
            "sub_id": it.sub_id,
            "notes": it.notes,
            "last_price": it.last_price,
            "currency": it.currency,
        }
        for k, it in items.items()
    }
    with ITEMS_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def _is_cancel_token(s: str) -> bool:
    return s.strip().lower() in CANCEL_TOKENS

def input_int(prompt: str, *, min_val: Optional[int] = None, max_val: Optional[int] = None,
              allow_blank: bool = False, allow_cancel: bool = True) -> Optional[int]:
    while True:
        s = input(prompt).strip()
        if allow_cancel and _is_cancel_token(s):
            return None
        if s == "" and allow_blank:
            return None
        if not s.lstrip("-").isdigit():
            print("Введите число.")
            continue
        val = int(s)
        if min_val is not None and val < min_val:
            print(f"Число должно быть ≥ {min_val}."); continue
        if max_val is not None and val > max_val:
            print(f"Число должно быть ≤ {max_val}."); continue
        return val

def input_str(prompt: str, *, allow_empty: bool = False, allow_cancel: bool = True) -> Optional[str]:
    while True:
        s = input(prompt).strip()
        if allow_cancel and _is_cancel_token(s):
            return None
        if not s and not allow_empty:
            print("Пустое значение недопустимо."); continue
        return s

def yes_no(prompt: str) -> bool:
    while True:
        s = input(f"{prompt} (y/n, 0 — отмена): ").strip().lower()
        if _is_cancel_token(s): return False
        if s in ("y", "yes", "д", "да"): return True
        if s in ("n", "no", "н", "нет"): return False
        print("Ответьте 'y' или 'n'.")

def press_enter():
    input("Нажмите Enter, чтобы продолжить...")


def _load_dotenv_into_environ() -> None:
    for p in DOTENV_PATHS:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    if "=" not in line: continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass

def _env_creds() -> Tuple[Optional[str], Optional[str]]:
    _load_dotenv_into_environ()
    return os.environ.get("STEAM_API_USER"), os.environ.get("STEAM_API_PASS")

def show_env_notice_once():
    global ENV_NOTICE_SHOWN
    if ENV_NOTICE_SHOWN: return
    user, pwd = _env_creds()
    missing: List[str] = []
    if not user: missing.append("STEAM_API_USER")
    if not pwd:  missing.append("STEAM_API_PASS")
    if missing:
        print("⚠️  УВЕДОМЛЕНИЕ: .env не найден или отсутствуют переменные: " + ", ".join(missing))
        print("    Работаем в УРЕЗАННОМ режиме: получение SUB_ID/инфо/расчёт цены недоступны без токена.")
        print("    Заполните .env или передайте токен аргументом:  python steam_gift_ids.py <TOKEN>\n")
    ENV_NOTICE_SHOWN = True

def obtain_token_via_env() -> Optional[str]:
    user, pwd = _env_creds()
    if not user or not pwd:
        return None
    try:
        r = requests.post(
            f"{API_BASE}/token",
            json={"username": user, "password": pwd},
            headers={"accept": "application/json", "content-type": "application/json"},
            timeout=15,
        )
        if r.status_code >= 400:
            print(f"⚠️ Не удалось получить токен: HTTP {r.status_code} {r.text}")
            return None
        data = {}
        try:
            data = r.json()
        except Exception:
            pass
        for k in ("token", "access_token", "jwt", "bearer"):
            if k in data and data[k]:
                return str(data[k])
        raw = getattr(r, "text", "") or ""
        return raw.strip() or None
    except requests.RequestException as e:
        print(f"⚠️ Сетевая ошибка при получении токена: {e}")
        return None
    
class ApiError(RuntimeError):
    pass

def _api_post(path: str, json_payload: dict, token: Optional[str] = None) -> dict:
    url = f"{API_BASE}/{path.lstrip('/')}"
    headers = {"accept": "application/json", "content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    try:
        r = requests.post(url, json=json_payload, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise ApiError(f"Сеть/соединение: {e!r}")
    if r.status_code >= 400:
        raise ApiError(f"HTTP {r.status_code}: {r.text}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}

def api_get_sub_id_by_app_id(app_id: int, token: str) -> int:
    data = _api_post("steam_gift_get_sub_id_by_app_id", {"app_id": str(app_id)}, token=token)

    for key in ("sub_id", "subId", "sub"):
        if key in data and str(data[key]).isdigit():
            return int(data[key])

    options = _extract_sub_options(data)
    if options:
        if len(options) == 1:
            pid, label = options[0]
            print(f"Найден единственный SUB_ID: {pid} ({label})")
            _set_last_sub_label(label)
            return pid
        return _ask_user_to_pick_sub(options)

    raw = data.get("raw")
    if raw and raw.strip().isdigit():
        return int(raw.strip())

    raise ApiError(f"Не удалось извлечь SUB_ID из ответа: {data}")

def api_calculate_price(sub_id: int, region: str, token: str) -> Tuple[float, Optional[str]]:
    payload = {"sub_id": str(sub_id), "region": region}
    data = _api_post("steam_gift_calculate", payload, token=token)
    price_val = None
    for k in ("price", "amount", "sum"):
        if k in data:
            try:
                price_val = float(data[k]); break
            except (TypeError, ValueError):
                pass
    currency = data.get("currency") or data.get("curr") or data.get("iso")
    if price_val is None:
        raw = data.get("raw", "")
        try: price_val = float(raw.strip())
        except Exception: pass
    if price_val is None:
        raise ApiError(f"Не удалось извлечь цену из ответа: {data}")
    return price_val, currency

def api_get_game_info(sub_id: int, token: str) -> dict:
    data = _api_post("steam_gift_get_info", {"sub_id": str(sub_id)}, token=token)
    regions = {"RU": {"price": None, "currency": None},
               "UA": {"price": None, "currency": None},
               "KZ": {"price": None, "currency": None}}

    prices_obj = data.get("prices") or data.get("region_prices") or {}
    if isinstance(prices_obj, dict):
        for code in list(regions.keys()):
            node = prices_obj.get(code) or prices_obj.get(code.lower())
            p, c = _parse_price_node(node)
            if p is not None:
                regions[code]["price"], regions[code]["currency"] = p, c

    for code in list(regions.keys()):
        if regions[code]["price"] is None:
            node = data.get(code) or data.get(code.lower())
            p, c = _parse_price_node(node)
            if p is not None:
                regions[code]["price"], regions[code]["currency"] = p, c

    for key in ("regions", "region_list"):
        arr = data.get(key)
        if isinstance(arr, list):
            for obj in arr:
                code = (str(obj.get("region") or obj.get("code") or "")).upper()
                if code in regions:
                    p, c = _parse_price_node(obj)
                    if p is not None:
                        regions[code]["price"], regions[code]["currency"] = p, c

    return {"regions": regions, "raw": data}

def _parse_price_node(node) -> Tuple[Optional[float], Optional[str]]:
    if node is None:
        return None, None
    if isinstance(node, (int, float, str)):
        try:
            return float(str(node).strip()), None
        except Exception:
            return None, None
    if isinstance(node, dict):
        price = None
        for k in ("price", "amount", "sum", "value"):
            if k in node:
                try:
                    price = float(node[k])
                    break
                except Exception:
                    pass
        curr = node.get("currency") or node.get("curr") or node.get("iso")
        return price, curr
    return None, None

def _extract_sub_options(data: dict) -> List[Tuple[int, str]]:
    options: List[Tuple[int, str]] = []

    for grp in data.get("package_groups", []) or []:
        name = str(grp.get("name", "")).lower()
        is_recurring = str(grp.get("is_recurring_subscription", "false")).lower() in {"1", "true", "yes"}
        if "subscription" in name or name == "subscriptions" or is_recurring:
            continue
        for sub in grp.get("subs", []) or []:
            pid = sub.get("packageid") or sub.get("package_id") or sub.get("id")
            if pid is None:
                continue
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            label = sub.get("option_text") or sub.get("name") or f"Package {pid}"
            options.append((pid, label))

    pkgs = data.get("packages")
    if isinstance(pkgs, list):
        for pid in pkgs:
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            if not any(p == pid_int for p, _ in options):
                options.append((pid_int, f"Package {pid_int}"))

    return options

def _ask_user_to_pick_sub(options: List[Tuple[int, str]]) -> int:
    print("\nНайдено несколько вариантов SUB_ID:")
    for i, (pid, label) in enumerate(options, start=1):
        print(f"  {i}. {label} (SUB_ID {pid})")
    while True:
        idx = input_int("Выберите вариант (номер, 0 — отмена): ", min_val=0, max_val=len(options), allow_cancel=True)
        if idx in (None, 0):
            raise ApiError("Выбор SUB_ID отменён пользователем.")
        pid, label = options[idx - 1]
        _set_last_sub_label(label)
        return pid

def _set_last_sub_label(label: Optional[str]) -> None:
    global _LAST_SUB_LABEL
    _LAST_SUB_LABEL = label

def _consume_last_sub_label() -> Optional[str]:
    global _LAST_SUB_LABEL
    val = _LAST_SUB_LABEL
    _LAST_SUB_LABEL = None
    return val

def _region_to_cc(region: str) -> str:
    return {"RU": "RU", "UA": "UA", "KZ": "KZ"}.get(region.upper(), "RU")

def fetch_game_info(app_id: int, region: str = "RU") -> Optional[dict]:
    params = {"appids": str(app_id), "l": "ru", "cc": _region_to_cc(region)}
    try:
        r = requests.get(STEAM_STORE_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"⚠️ Не удалось получить данные из Steam Store API: {e}")
        return None
    node = data.get(str(app_id)) or {}
    if not node.get("success") or "data" not in node:
        print("⚠️ Steam Store API вернул пустой ответ для этого APP_ID.")
        return None
    d = node["data"]
    name = d.get("name")
    gnames = [g.get("description") for g in d.get("genres", []) if isinstance(g, dict) and g.get("description")]
    rdate = (d.get("release_date") or {}).get("date")
    p = d.get("price_overview") or {}
    price = None
    if "final_formatted" in p:
        price = p["final_formatted"]
    elif "final" in p and "currency" in p:
        try:
            price = f"{p['final']/100:.2f} {p['currency']}"
        except Exception:
            pass
    short = d.get("short_description")
    return {
        "name": name,
        "type": d.get("type"),
        "genres": [g for g in gnames if g],
        "release_date": rdate,
        "price": price,
        "short_description": short,
    }

def make_auto_notes_from_store(info: dict) -> str:
    parts = []
    if info.get("name"): parts.append(f"Steam: {info['name']}")
    if info.get("type"): parts.append(f"Тип: {info['type']}")
    if info.get("genres"): parts.append("Жанры: " + ", ".join(info["genres"][:5]))
    if info.get("release_date"): parts.append(f"Релиз: {info['release_date']}")
    if info.get("price"): parts.append(f"Прайс (витрина): {info['price']}")
    if info.get("short_description"):
        parts.append("Описание: " + info["short_description"][:160] + ("…" if len(info["short_description"]) > 160 else ""))
    return " | ".join(parts)

def summarize_item(it: SteamGiftItem) -> str:
    parts = [f"[{it.key}] {it.title} | регион: {it.region}"]
    parts.append(f"  app_id: {it.app_id or '-'}  sub_id: {it.sub_id or '-'}")
    if it.last_price is not None:
        parts.append(f"  цена: {it.last_price} {it.currency or ''}".rstrip())
    if it.notes:
        parts.append(f"  заметки: {it.notes}")
    return "\n".join(parts)

def print_items(items: Dict[str, SteamGiftItem]) -> None:
    if not items:
        print("Пока нет ни одной позиции."); return
    for k in sorted(items.keys(), key=lambda x: int(x) if str(x).isdigit() else x):
        print(summarize_item(items[k])); print("-" * 40)

def print_region_prices_table(regions: Dict[str, Dict[str, Optional[float]]]) -> None:
    print("\nЦены по регионам (из /steam_gift_get_info):")
    print("  Регион | Цена")
    print("  -------+----------------")
    for code in ("RU", "UA", "KZ"):
        p = regions.get(code, {}).get("price")
        c = regions.get(code, {}).get("currency")
        if p is None:
            s = "нет данных"
        else:
            s = f"{p} {c or ''}".strip()
        print(f"  {code:>6} | {s}")
    print()

def resolve_order_params(funpay_key: str | int, items: Optional[Dict[str, SteamGiftItem]] = None) -> Tuple[int, str]:
    data = items or load_items()
    key = str(funpay_key)
    if key not in data:
        raise KeyError(f"Товар с кодом {key} не найден в steam_gifts.json")
    it = data[key]
    if not it.sub_id:
        raise ValueError(f"Для {key} не задан sub_id (нужно либо получить по app_id, либо указать вручную).")
    if it.region not in REGION_CHOICES:
        raise ValueError(f"Недопустимый регион {it.region} (ожидались {', '.join(sorted(REGION_CHOICES))})")
    return int(it.sub_id), it.region

def cmd_create_item():
    show_env_notice_once()
    items = load_items()
    print("\n=== Создание позиции (айдишника) Steam ===")
    print("Подсказка: отмена — 0 / «отмена» / «назад».")

    while True:
        region = input_str("Регион (RU | UA | KZ): ", allow_empty=False, allow_cancel=True)
        if region is None:
            print("Отменено."); press_enter(); return
        region = region.upper()
        if region not in REGION_CHOICES:
            print("Разрешены регионы: RU, UA, KZ."); continue
        break

    app_id = input_int("APP_ID (из URL магазина Steam): ", min_val=1, allow_cancel=True)
    if app_id is None:
        print("Отменено."); press_enter(); return

    info = fetch_game_info(app_id, region)
    auto_title = (info or {}).get("name") or f"APP {app_id}"
    auto_notes = make_auto_notes_from_store(info) if info else ""
    if not info:
        print("⚠️ Не удалось получить данные об игре из Steam Store API.")

    title = input_str(f"Название (Enter — {auto_title}): ", allow_empty=True, allow_cancel=True)
    if title is None:
        print("Отменено."); press_enter(); return
    if not title: title = auto_title

    token = _cli_token_arg_or_none() or obtain_token_via_env()

    sub_id: Optional[int] = None
    selected_pkg_label: Optional[str] = None
    if token:
        try:
            sub_id = api_get_sub_id_by_app_id(app_id, token)
            print(f"SUB_ID получен: {sub_id}")
            selected_pkg_label = _consume_last_sub_label()
        except Exception as e:
            print(f"⚠️ Не удалось получить SUB_ID по APP_ID: {e}")
    else:
        print("ℹ️ Токен отсутствует — SUB_ID не будет получен (урезанный режим).")

    default_notes = auto_notes
    if selected_pkg_label:
        default_notes = (default_notes + (" | " if default_notes else "") + f"Пакет: {selected_pkg_label}").strip()

    if token and sub_id:
        try:
            gi = api_get_game_info(sub_id, token)
            print_region_prices_table(gi["regions"])
            rp = gi["regions"].get(region, {})
            if rp and rp.get("price") is not None:
                print(f"Автозаполняем цену для региона {region}: {rp['price']} {rp.get('currency') or ''}".strip())
                auto_price, auto_curr = rp["price"], rp.get("currency")
            else:
                auto_price, auto_curr = None, None
        except Exception as e:
            print(f"⚠️ Не удалось получить информацию об игре (все регионы): {e}")
            auto_price, auto_curr = None, None
    else:
        auto_price, auto_curr = None, None

    notes = input_str("Заметки (Enter — автозаметки / пусто): ", allow_empty=True, allow_cancel=True)
    if notes is None:
        print("Отменено."); press_enter(); return
    if notes == "":
        notes = default_notes

    while True:
        funpay_id = input_int("\nУкажи ID товара для FunPay (целое ≥ 1): ", min_val=1, allow_cancel=True)
        if funpay_id is None:
            print("Отменено."); press_enter(); return
        key = str(funpay_id)
        if key in items:
            print("Этот ID уже занят — выбери другой."); continue
        break

    it = SteamGiftItem(
        key=key, title=title, region=region, app_id=app_id, sub_id=sub_id, notes=notes
    )

    if auto_price is not None:
        it.last_price, it.currency = auto_price, auto_curr

    if token and sub_id and it.last_price is None:
        if yes_no("Попробовать рассчитать цену сейчас (/steam_gift_calculate)"):
            try:
                price, cur = api_calculate_price(sub_id, region, token)
                it.last_price, it.currency = price, cur
                print(f"Цена: {price} {cur or ''}".strip())
            except Exception as e:
                print(f"⚠️ Расчёт цены не удался: {e}")

    print("\nПроверка данных позиции:")
    print(summarize_item(it))
    if yes_no("Сохранить позицию"):
        items[key] = it
        save_items(items)
        print("✅ Сохранено.")
    else:
        print("Сохранение отменено.")
    press_enter()

def _choose_existing_key(items: Dict[str, SteamGiftItem]) -> Optional[str]:
    if not items:
        print("Каталог пуст."); return None
    print("\nТекущие позиции:")
    for k in sorted(items.keys(), key=lambda x: int(x) if str(x).isdigit() else x):
        print(f"  {k}: {items[k].title} ({items[k].region})")
    sid = input_int("\nУкажи ID позиции (0 — назад): ", min_val=1, allow_cancel=True)
    if sid is None: return None
    key = str(sid)
    if key not in items:
        print("Позиция не найдена."); return None
    return key

def cmd_edit_item():
    show_env_notice_once()
    items = load_items()
    print("\n=== Редактирование позиции ===")
    key = _choose_existing_key(items)
    if not key: press_enter(); return
    it = items[key]

    print("\nЧто меняем?")
    print("  1) APP_ID → получить/обновить SUB_ID")
    print("  2) Регион")
    print("  3) Название")
    print("  4) Заметки")
    print("  5) Пересчитать цену (calculate; нужен токен и SUB_ID)")
    print("  6) Сменить ID (ключ) позиции")
    print("  7) Обновить инфо из Steam Store API по APP_ID (подтянуть название/заметки)")
    print("  8) Получить информацию об игре (все регионы) и обновить цену для текущего региона")
    print("  0) Назад")
    choice = input_int("Выбор: ", min_val=0, max_val=8, allow_cancel=True)
    if choice in (None, 0): press_enter(); return

    changed = False
    token = _cli_token_arg_or_none() or obtain_token_via_env()

    if choice == 1:
        val = input_int("Новый APP_ID (или прежний): ", min_val=1, allow_cancel=True)
        if val is None: print("Отменено."); press_enter(); return
        it.app_id = val
        if token:
            try:
                it.sub_id = api_get_sub_id_by_app_id(val, token)
                print(f"SUB_ID обновлён: {it.sub_id}")
                pkg_label = _consume_last_sub_label()
                if pkg_label and not it.notes:
                    it.notes = f"Пакет: {pkg_label}"
                    print("Заметки обновлены: добавлен выбранный пакет.")
                changed = True
            except Exception as e:
                print(f"⚠️ Не удалось получить SUB_ID: {e}")
        else:
            print("ℹ️ Токен отсутствует — SUB_ID не обновлён (урезанный режим).")
        changed = True

    elif choice == 2:
        while True:
            region = input_str("Новый регион (RU|UA|KZ): ", allow_empty=False, allow_cancel=True)
            if region is None: print("Отменено."); press_enter(); return
            region = region.upper()
            if region not in REGION_CHOICES:
                print("Разрешены: RU, UA, KZ."); continue
            it.region = region; changed = True; break

    elif choice == 3:
        title = input_str("Новое название: ", allow_empty=False, allow_cancel=True)
        if title is None: print("Отменено."); press_enter(); return
        it.title = title; changed = True

    elif choice == 4:
        notes = input_str("Новые заметки (можно пусто): ", allow_empty=True, allow_cancel=True)
        if notes is None: print("Отменено."); press_enter(); return
        it.notes = notes; changed = True

    elif choice == 5:
        if not token:
            print("Нужен токен для расчёта цены.")
        elif not it.sub_id:
            print("Нужен SUB_ID для расчёта цены.")
        else:
            try:
                price, cur = api_calculate_price(it.sub_id, it.region, token)
                it.last_price, it.currency = price, cur
                print(f"Цена обновлена: {price} {cur or ''}".strip())
                changed = True
            except Exception as e:
                print(f"⚠️ Ошибка расчёта: {e}")

    elif choice == 6:
        while True:
            new_id = input_int("Новый ID позиции (целое ≥ 1): ", min_val=1, allow_cancel=True)
            if new_id is None: print("Отменено."); press_enter(); return
            new_key = str(new_id)
            if new_key in items and new_key != it.key:
                print("Этот ID уже занят."); continue
            if new_key != it.key:
                items.pop(it.key)
                it.key = new_key
                items[new_key] = it
                changed = True
            break

    elif choice == 7:
        if not it.app_id:
            print("Сначала укажи APP_ID (п.1).")
        else:
            info = fetch_game_info(it.app_id, it.region)
            if info:
                suggested_title = info.get("name") or it.title
                print(f"Найдено название в Steam: {suggested_title}")
                if yes_no("Обновить название на найденное"):
                    it.title = suggested_title; changed = True
                auto_notes = make_auto_notes_from_store(info)
                if auto_notes:
                    print("Автозаметки собраны из Steam.")
                    if yes_no("Заменить заметки на автозаметки"):
                        it.notes = auto_notes; changed = True
            else:
                print("⚠️ Не удалось получить данные из Steam Store API.")

    elif choice == 8:
        if not token:
            print("Нужен токен.")
        elif not it.sub_id:
            print("Нужен SUB_ID (обнови через п.1).")
        else:
            try:
                gi = api_get_game_info(it.sub_id, token)
                print_region_prices_table(gi["regions"])
                rp = gi["regions"].get(it.region, {})
                if rp and rp.get("price") is not None:
                    it.last_price, it.currency = rp["price"], rp.get("currency")
                    print(f"Цена обновлена для {it.region}: {it.last_price} {it.currency or ''}".strip())
                    changed = True
                else:
                    print("Данных для текущего региона нет — поля цены не изменены.")
            except Exception as e:
                print(f"⚠️ Не удалось получить информацию об игре: {e}")

    if changed:
        print("\nОбновлённая позиция:"); print(summarize_item(it))
        if yes_no("Сохранить изменения"):
            save_items(items); print("✅ Изменения сохранены.")
        else:
            print("Сохранение отменено.")
    else:
        print("Изменений нет.")
    press_enter()

def cmd_delete_item():
    items = load_items()
    print("\n=== Удаление позиции ===")
    key = _choose_existing_key(items)
    if not key: press_enter(); return
    if yes_no(f"Удалить позицию {key} безвозвратно"):
        items.pop(key, None); save_items(items); print("✅ Удалено.")
    else:
        print("Удаление отменено.")
    press_enter()

def cmd_list_items():
    print("\n=== Список позиций ===")
    items = load_items()
    print_items(items)
    press_enter()

def main_menu():
    show_env_notice_once()
    while True:
        print("\n==============================")
        print("   Мастер айдишников Steam    ")
        print("==============================")
        print("Подсказка: в любом месте можно ввести 0 / «отмена» / «назад».")
        print("\nДоступные действия:")
        print("  1. Создать позицию (APP_ID → SUB_ID → инфо Steam)")
        print("  2. Редактировать позицию")
        print("  3. Удалить позицию")
        print("  4. Посмотреть список")
        print("  0. Выход\n")

        choice = input_int("Выберите пункт (0–4): ", min_val=0, max_val=4, allow_cancel=True)
        if choice in (None, 0):
            print("Выход."); break
        if choice == 1: cmd_create_item()
        elif choice == 2: cmd_edit_item()
        elif choice == 3: cmd_delete_item()
        elif choice == 4: cmd_list_items()

def _cli_token_arg_or_none() -> Optional[str]:
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        return sys.argv[1].strip()
    return None

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nВыход (Ctrl+C).")
