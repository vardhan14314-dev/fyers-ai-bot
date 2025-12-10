# main.py
# Advanced hourly bot: FYERS → OpenAI → Signal → (Optional) Place order → Log
# Works for Index, Stocks, Options, ETFs, Mutual Funds

import os
import time
import json
from datetime import datetime
import requests
import openai

# -----------------------------------------
# CONFIGURATION
# -----------------------------------------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))
SYMBOLS = os.getenv("SYMBOLS", "NIFTY50").split(",")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
LOG_FILE = os.getenv("LOG_FILE", "signals.log")

FYERS_ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN")
FYERS_QUOTE_URL = os.getenv("FYERS_QUOTE_URL", "")     # if you have a custom endpoint
FYERS_ORDER_URL = os.getenv("FYERS_ORDER_URL", "")     # optional
OMEGA_PROMPT_PATH = os.getenv("OMEGA_PROMPT_PATH", "prompts/omega-fi-prompt.txt")

openai.api_key = os.getenv("OPENAI_API_KEY")


# -----------------------------------------
# LOAD SYSTEM PROMPT
# -----------------------------------------
def load_system_prompt():
    try:
        with open(OMEGA_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return (
            "You are an expert Indian financial market analyst. "
            "Analyze Index, Stocks, Options, ETFs, Mutual Funds. "
            "Provide BUY/SELL/HOLD signals with reasons."
        )


# -----------------------------------------
# IDENTIFY SYMBOL TYPE
# -----------------------------------------
def detect_type(symbol):
    s = symbol.upper()
    if s.startswith("OPTION:"):
        return "OPTION", symbol[len("OPTION:"):]
    if s.startswith("ETF:"):
        return "ETF", symbol[len("ETF:"):]
    if s.startswith("MF:"):
        return "MF", symbol[len("MF:"):]
    if ":" in symbol:
        return "EQUITY", symbol
    return "INDEX", symbol


# -----------------------------------------
# FETCH MARKET DATA
# -----------------------------------------
def fetch_market_data(symbol):
    asset_type, key = detect_type(symbol)

    # Use FYERS API if URL + token provided
    if FYERS_QUOTE_URL and FYERS_ACCESS_TOKEN:
        try:
            headers = {"Authorization": f"Bearer {FYERS_ACCESS_TOKEN}"}
            params = {"symbol": key, "type": asset_type}
            r = requests.get(FYERS_QUOTE_URL, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            return {
                "symbol": symbol,
                "type": asset_type,
                "last_price": data.get("last_price", data.get("lp", None)),
                "raw": data
            }
        except Exception as e:
            return {"symbol": symbol, "type": asset_type, "error": str(e)}

    # Fallback mocked prices (so bot still runs)
    mock_price = round(1000 + (hash(symbol) % 600), 2)
    return {"symbol": symbol, "type": asset_type, "last_price": mock_price}


# -----------------------------------------
# BUILD SNAPSHOT FOR GPT
# -----------------------------------------
def build_market_snapshot(symbol_data):
    lines = []
    for s in symbol_data:
        if "error" in s:
            lines.append(f"{s['symbol']} ({s['type']}): ERROR → {s['error']}")
        else:
            lines.append(f"{s['symbol']} ({s['type']}): price={s.get('last_price')}")
    return (
        "Market Snapshot:\n" +
        "\n".join(lines) +
        "\n\nProvide a single-line BUY/SELL/HOLD signal **for each symbol** with a short reason."
    )


# -----------------------------------------
# OPENAI CALL
# -----------------------------------------
def ask_gpt(system_prompt, market_snapshot):
    try:
        response = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": market_snapshot}
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.25
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR contacting OpenAI: {e}"


# -----------------------------------------
# PARSE SIGNAL
# -----------------------------------------
def parse_signal(text):
    t = text.upper()
    if "BUY" in t:
        return "BUY"
    if "SELL" in t:
        return "SELL"
    if "HOLD" in t:
        return "HOLD"
    return "UNKNOWN"


# -----------------------------------------
# SEND ORDER (OPTIONAL)
# -----------------------------------------
def fyers_order(payload):
    if DRY_RUN:
        return {"status": "dry_run", "detail": "Order not executed", "payload": payload}

    if not (FYERS_ORDER_URL and FYERS_ACCESS_TOKEN):
        return {"status": "error", "detail": "Order URL or token missing"}

    try:
        headers = {
            "Authorization": f"Bearer {FYERS_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        r = requests.post(FYERS_ORDER_URL, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# -----------------------------------------
# LOGGING
# -----------------------------------------
def write_log(entry):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except:
        pass


# -----------------------------------------
# MAIN
# -----------------------------------------
def main():
    timestamp = datetime.utcnow().isoformat()

    system_prompt = load_system_prompt()

    # ---- Fetch all symbols ----
    data_list = []
    for sym in SYMBOLS:
        sym = sym.strip()
        if sym:
            data_list.append(fetch_market_data(sym))

    # ---- Build snapshot ----
    snapshot = build_market_snapshot(data_list)

    # ---- Ask GPT ----
    gpt_result = ask_gpt(system_prompt, snapshot)
    signal = parse_signal(gpt_result)

    # ---- Prepare order ----
    order_payload = {
        "timestamp": int(time.time()),
        "signal": signal,
        "reason": gpt_result,
        "primary_symbol": SYMBOLS[0].strip() if SYMBOLS else "N/A"
    }

    # ---- Execute order ----
    order_response = fyers_order(order_payload)

    # ---- Log everything ----
    log_entry = json.dumps({
        "time": timestamp,
        "symbols": SYMBOLS,
        "snapshot": snapshot,
        "signal_text": gpt_result,
        "parsed_signal": signal,
        "order_response": order_response
    }, ensure_ascii=False)

    write_log(log_entry)

    # Console for GitHub Action log
    print("✔ Bot run complete")
    print("Signal:", signal)
    print("Reason:", gpt_result[:200], "...")
    print("Order Result:", order_response)


if __name__ == "__main__":
    main()
