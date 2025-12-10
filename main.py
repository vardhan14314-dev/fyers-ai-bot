# main.py
# Advanced hourly bot using NEW OpenAI Python API (Responses API)
# Supports Index, Stocks, Options, ETFs, Mutual Funds

import os
import time
import json
from datetime import datetime
import requests
from openai import OpenAI  # NEW API

# -----------------------------
# CONFIG
# -----------------------------
OPENAI_MODEL = "gpt-5.1"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))
SYMBOLS = os.getenv("SYMBOLS", "NIFTY50").split(",")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
LOG_FILE = os.getenv("LOG_FILE", "signals.log")

FYERS_ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN")
FYERS_QUOTE_URL = os.getenv("FYERS_QUOTE_URL", "")
FYERS_ORDER_URL = os.getenv("FYERS_ORDER_URL", "")

OMEGA_PROMPT_PATH = os.getenv("OMEGA_PROMPT_PATH", "prompts/omega-fi-prompt.txt")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -----------------------------
# LOAD PROMPT
# -----------------------------
def load_system_prompt():
    try:
        with open(OMEGA_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return (
            "You are an expert Indian financial market analyst. "
            "Analyze Index, Stocks, Options, ETFs, Mutual Funds and provide BUY/SELL/HOLD."
        )


# -----------------------------
# DETECT SYMBOL TYPE
# -----------------------------
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


# -----------------------------
# FETCH DATA
# -----------------------------
def fetch_market_data(symbol):
    asset_type, key = detect_type(symbol)

    if FYERS_QUOTE_URL and FYERS_ACCESS_TOKEN:
        try:
            headers = {"Authorization": f"Bearer {FYERS_ACCESS_TOKEN}"}
            params = {"symbol": key, "type": asset_type}
            res = requests.get(FYERS_QUOTE_URL, params=params, headers=headers, timeout=10)
            res.raise_for_status()
            data = res.json()
            return {
                "symbol": symbol,
                "type": asset_type,
                "last_price": data.get("last_price", data.get("lp")),
                "raw": data
            }
        except Exception as e:
            return {"symbol": symbol, "type": asset_type, "error": str(e)}

    # fallback mocked values:
    return {
        "symbol": symbol,
        "type": asset_type,
        "last_price": round(1000 + (hash(symbol) % 500), 2)
    }


# -----------------------------
# SNAPSHOT
# -----------------------------
def build_snapshot(symbol_data):
    lines = []
    for item in symbol_data:
        if "error" in item:
            lines.append(f"{item['symbol']} ({item['type']}): ERROR → {item['error']}")
        else:
            lines.append(f"{item['symbol']} ({item['type']}): price={item['last_price']}")
    return (
        "Market Snapshot:\n" +
        "\n".join(lines) +
        "\n\nProvide a BUY/SELL/HOLD for **each** symbol with a short reason."
    )


# -----------------------------
# OPENAI (NEW API)
# -----------------------------
def ask_gpt(system_prompt, snapshot):
    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": snapshot}
            ],
            max_output_tokens=MAX_TOKENS,
        )
        return response.output_text
    except Exception as e:
        return f"ERROR contacting OpenAI: {e}"


# -----------------------------
# PARSE SIGNAL
# -----------------------------
def parse_signal(text):
    t = text.upper()
    if "BUY" in t:
        return "BUY"
    if "SELL" in t:
        return "SELL"
    if "HOLD" in t:
        return "HOLD"
    return "UNKNOWN"


# -----------------------------
# ORDER (OPTIONAL)
# -----------------------------
def fyers_order(payload):
    if DRY_RUN:
        return {"status": "dry_run", "detail": "Order skipped", "payload": payload}

    if not (FYERS_ACCESS_TOKEN and FYERS_ORDER_URL):
        return {"status": "error", "detail": "Missing order URL or token"}

    try:
        headers = {
            "Authorization": f"Bearer {FYERS_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        resp = requests.post(FYERS_ORDER_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# -----------------------------
# LOGGING
# -----------------------------
def write_log(content):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(content + "\n")
    except:
        pass


# -----------------------------
# MAIN BOT LOGIC
# -----------------------------
def main():
    timestamp = datetime.utcnow().isoformat()

    system_prompt = load_system_prompt()

    # fetch symbols
    data_list = []
    for s in SYMBOLS:
        if s.strip():
            data_list.append(fetch_market_data(s.strip()))

    # build snapshot
    snapshot = build_snapshot(data_list)

    # call GPT
    gpt_result = ask_gpt(system_prompt, snapshot)
    signal = parse_signal(gpt_result)

    # prepare order
    order_payload = {
        "symbol": SYMBOLS[0].strip(),
        "signal": signal,
        "reason": gpt_result,
        "ts": int(time.time())
    }

    # send
    order_response = fyers_order(order_payload)

    # log
    log_line = json.dumps({
        "timestamp": timestamp,
        "symbols": SYMBOLS,
        "snapshot": snapshot,
        "gpt_output": gpt_result,
        "signal": signal,
        "order_response": order_response
    }, ensure_ascii=False)

    write_log(log_line)

    # console output for Actions
    print("✔ Bot run completed")
    print("Signal =", signal)
    print("GPT Output =", gpt_result[:250], "...")
    print("Order Response:", order_response)


if __name__ == "__main__":
    main()
