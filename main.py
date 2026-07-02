from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json
import requests
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

creds_dict = json.loads(os.environ["GOOGLE_CREDS"])
credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
client = gspread.authorize(credentials)
sheet = client.open_by_key("1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA")

FX_CACHE = {"rates": None, "timestamp": 0, "source": None}
DATA_CACHE = {}
CACHE_TTL = {"df": 45, "portfolio": 30, "analytics": 30, "holdings": 30}
FX_TTL = 3600

CASH_SECTION_TITLES = [
    "MM Funds",
    "SG Account balances",
    "Foreign Cash Accounts"
]

VALID_CURRENCIES = {"SGD", "USD", "INR", "AUD", "EUR", "GBP"}

def now():
    return time.time()

def cache_get(key, ttl):
    item = DATA_CACHE.get(key)
    if not item:
        return None
    if now() - item["ts"] > ttl:
        DATA_CACHE.pop(key, None)
        return None
    return item["value"]

def cache_set(key, value):
    DATA_CACHE[key] = {"ts": now(), "value": value}

def safe_float(x):
    try:
        if x is None:
            return 0
        x = str(x).strip().replace(",", "")
        if x == "":
            return 0
        return float(x)
    except:
        return 0

def clean_currency(x):
    if x is None:
        return None
    x = str(x).strip().upper()
    return x if x in VALID_CURRENCIES else None

def invalid_asset(asset):
    if asset is None:
        return True
    text = str(asset).strip().upper()
    bad = ["TOTAL", "BALANCE", "ACCOUNT", "ACCOUNTS", "GAIN", "LOSS", "REALISED", "UNREALISED", "CURRENCY"]
    return text == "" or any(k in text for k in bad)

def get_sheet_values(name):
    ws = sheet.worksheet(name)
    return ws.get_all_values()

def get_sheet_df(name):
    ws = sheet.worksheet(name)
    return pd.DataFrame(ws.get_all_records())

def get_realtime_fx_rates():
    global FX_CACHE
    t = now()
    if FX_CACHE["rates"] and (t - FX_CACHE["timestamp"]) < FX_TTL:
        return FX_CACHE["rates"], FX_CACHE["source"]

    fx_rates = None
    source_used = None
    api_endpoints = [
        {"name": "open.er-api.com", "url": "https://open.er-api.com/v6/latest/SGD", "key": "rates"},
        {"name": "exchangerate.host", "url": "https://api.exchangerate.host/latest?base=SGD", "key": "rates"},
        {"name": "frankfurter.app", "url": "https://api.frankfurter.app/latest?from=SGD", "key": "rates"},
    ]

    for api in api_endpoints:
        try:
            r = requests.get(api["url"], timeout=8)
            if r.status_code != 200:
                continue
            data = r.json()
            raw = data.get(api["key"])
            required = ["USD", "INR", "AUD", "EUR", "GBP"]
            if not raw or not all(c in raw for c in required):
                continue
            fx_rates = {
                "SGD": 1.0,
                "USD": float(raw["USD"]),
                "INR": float(raw["INR"]),
                "AUD": float(raw["AUD"]),
                "EUR": float(raw["EUR"]),
                "GBP": float(raw["GBP"]),
            }
            source_used = api["name"]
            break
        except Exception:
            continue

    if not fx_rates:
        fx_rates = {"SGD": 1.0, "USD": None, "INR": None, "AUD": None, "EUR": None, "GBP": None}
        source_used = "ERROR: All APIs failed"

    FX_CACHE["rates"] = fx_rates
    FX_CACHE["timestamp"] = t
    FX_CACHE["source"] = source_used
    return fx_rates, source_used

FX, FX_SOURCE = get_realtime_fx_rates()

def parse_cash_sheet():
    try:
        raw = get_sheet_values("Cash")
    except Exception:
        return []

    if not raw:
        return []

    parsed = []
    current_group = None

    def is_section_header(text):
        t = str(text).strip().lower()
        return (
            t == "mm funds"
            or t == "sg account balances"
            or t == "foreign cash accounts"
        )

    def is_total_row(text):
        t = str(text).strip().lower()
        return t.startswith("total bal in sgd") or t.startswith("total")

    for row in raw:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue

        first = cells[0]

        if is_section_header(first):
            if first.lower() == "sg account balances":
                current_group = "SG Account balances"
            elif first.lower() == "mm funds":
                current_group = "MM Funds"
            else:
                current_group = "Foreign Cash Accounts"
            continue

        if current_group is None:
            continue

        if is_total_row(first):
            continue

        if first.lower() in {"current value", "investment value", "appreciation", "appreciation %", "sgd amount"}:
            continue

        if invalid_asset(first):
            continue

        market_value = 0
        investment_value = 0

        try:
            if current_group == "MM Funds":
                market_value = safe_float(cells[1]) if len(cells) > 1 else 0
                investment_value = safe_float(cells[2]) if len(cells) > 2 else 0
            elif current_group == "SG Account balances":
                market_value = safe_float(cells[1]) if len(cells) > 1 else 0
                investment_value = market_value
            elif current_group == "Foreign Cash Accounts":
                market_value = safe_float(cells[2]) if len(cells) > 2 else 0
                investment_value = safe_float(cells[3]) if len(cells) > 3 else 0
        except Exception:
            continue

        if market_value <= 0 and investment_value <= 0:
            continue

        parsed.append({
            "asset": first,
            "sub_type": "Cash",
            "cash_group": current_group,
            "currency": "SGD",
            "qty": 1,
            "current_price": market_value,
            "investment_price": investment_value,
            "market_value": market_value,
            "investment_value": investment_value
        })

    return parsed

def normalize_mf(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r.get("MF - SK", "")).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        rows.append({
            "asset": asset,
            "sub_type": "Mutual Fund",
            "cash_group": None,
            "currency": currency,
            "qty": safe_float(r.get("Qty", 0)),
            "current_price": 0,
            "investment_price": 0,
            "market_value": safe_float(r.get("Current Value")),
            "investment_value": safe_float(r.get("Invested Amount"))
        })
    return rows

def normalize_shares(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r.get("Company", "")).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        subtype = "ETF" if "ETF" in asset.upper() else "Stock"
        rows.append({
            "asset": asset,
            "sub_type": subtype,
            "cash_group": None,
            "currency": currency,
            "qty": safe_float(r.get("Qty", 0)),
            "current_price": safe_float(r.get("Current Price", 0)),
            "investment_price": safe_float(r.get("Investment Price", 0)),
            "market_value": safe_float(r.get("Current Market Value")),
            "investment_value": safe_float(r.get("Investment Value"))
        })
    return rows

def normalize_gold(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r.get("Company", "")).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        rows.append({
            "asset": asset,
            "sub_type": "Gold",
            "cash_group": None,
            "currency": currency,
            "qty": safe_float(r.get("Qty", 0)),
            "current_price": safe_float(r.get("Current Price", 0)),
            "investment_price": safe_float(r.get("Investment Price", 0)),
            "market_value": safe_float(r.get("Current Market Value")),
            "investment_value": safe_float(r.get("Investment Value"))
        })
    return rows

def build_df():
    cached = cache_get("df", CACHE_TTL["df"])
    if cached is not None:
        return cached

    holdings = []
    try:
        holdings += parse_cash_sheet()
    except Exception:
        holdings += []

    try:
        holdings += normalize_mf(get_sheet_df("MFs"))
    except Exception:
        holdings += []

    try:
        holdings += normalize_shares(get_sheet_df("Shares"))
    except Exception:
        holdings += []

    try:
        holdings += normalize_gold(get_sheet_df("Gold"))
    except Exception:
        holdings += []

    df = pd.DataFrame(holdings)
    if df.empty:
        cache_set("df", df)
        return df

    df["fx"] = df["currency"].map(FX).replace([None], 1.0)
    df["value_sgd"] = df["market_value"] / df["fx"]
    df["investment_sgd"] = df["investment_value"] / df["fx"]
    df["profit_sgd"] = df["value_sgd"] - df["investment_sgd"]
    df["profit_pct"] = (
        (df["market_value"] - df["investment_value"])
        / df["investment_value"].replace(0, 1)
        * 100
    )

    cache_set("df", df)
    return df

def build_cash_groups(df):
    cash_df = df[df["sub_type"] == "Cash"].copy()
    if cash_df.empty:
        return {
            "groups": [],
            "grand_total": {
                "market_value": 0,
                "investment_value": 0,
                "profit_sgd": 0,
                "value_sgd": 0
            }
        }

    groups = []
    grand_market = 0
    grand_invest = 0
    grand_profit = 0
    grand_value = 0
    total_portfolio = max(df["value_sgd"].sum(), 1)

    for group_name in CASH_SECTION_TITLES:
        g = cash_df[cash_df["cash_group"] == group_name].copy()
        if g.empty:
            continue

        g["unrealised_gain"] = g["market_value"] - g["investment_value"]
        g["unrealised_gain_pct"] = g["unrealised_gain"] / g["investment_value"].replace(0, 1) * 100
        g["portfolio_pct"] = g["value_sgd"] / total_portfolio * 100

        subtotal = {
            "market_value": round(g["market_value"].sum(), 2),
            "investment_value": round(g["investment_value"].sum(), 2),
            "profit_sgd": round(g["profit_sgd"].sum(), 2),
            "value_sgd": round(g["value_sgd"].sum(), 2)
        }

        grand_market += subtotal["market_value"]
        grand_invest += subtotal["investment_value"]
        grand_profit += subtotal["profit_sgd"]
        grand_value += subtotal["value_sgd"]

        groups.append({
            "group_name": group_name,
            "rows": g.round(2).to_dict(orient="records"),
            "subtotal": subtotal
        })

    return {
        "groups": groups,
        "grand_total": {
            "market_value": round(grand_market, 2),
            "investment_value": round(grand_invest, 2),
            "profit_sgd": round(grand_profit, 2),
            "value_sgd": round(grand_value, 2)
        }
    }

@app.get("/portfolio")
def portfolio():
    cached = cache_get("portfolio", CACHE_TTL["portfolio"])
    if cached is not None:
        return cached

    df = build_df()
    total = df["value_sgd"].sum() if not df.empty else 0

    allocation = (df.groupby("sub_type")["value_sgd"].sum() / total * 100) if total > 0 else pd.Series(dtype=float)
    currency = (df.groupby("currency")["value_sgd"].sum() / total * 100) if total > 0 else pd.Series(dtype=float)

    asset_class_breakdown = []
    if total > 0:
        grouped = df.groupby("sub_type").agg({
            "investment_sgd": "sum",
            "value_sgd": "sum",
            "profit_sgd": "sum"
        })

        for asset_class, row in grouped.iterrows():
            asset_rows = df[df["sub_type"] == asset_class].copy()
            asset_rows["portfolio_pct"] = asset_rows["value_sgd"] / total * 100
            asset_rows["unrealised_gain"] = asset_rows["market_value"] - asset_rows["investment_value"]
            asset_rows["unrealised_gain_pct"] = (
                asset_rows["unrealised_gain"]
                / asset_rows["investment_value"].replace(0, 1)
                * 100
            )

            asset_class_breakdown.append({
                "asset_class": asset_class,
                "investment_sgd": round(row["investment_sgd"], 2),
                "value_sgd": round(row["value_sgd"], 2),
                "profit_sgd": round(row["profit_sgd"], 2),
                "profit_pct": round(row["profit_sgd"] / max(row["investment_sgd"], 1) * 100, 2),
                "portfolio_pct": round(row["value_sgd"] / total * 100, 2),
                "holdings": asset_rows.round(2).to_dict(orient="records")
            })

    result = {
        "summary": {
            "networth_sgd": round(total, 2),
            "profit_sgd": round(df["profit_sgd"].sum(), 2) if not df.empty else 0
        },
        "allocation": allocation.round(2).to_dict() if total > 0 else {},
        "currency_exposure": currency.round(2).to_dict() if total > 0 else {},
        "top_holdings": df.sort_values("value_sgd", ascending=False).head(10)[["asset", "value_sgd"]].round(2).to_dict(orient="records") if not df.empty else [],
        "asset_class_breakdown": asset_class_breakdown,
        "holdings": df.round(2).to_dict(orient="records") if not df.empty else [],
        "cash_groups": build_cash_groups(df),
        "fx_rates": FX,
        "fx_source": "Real-time from external API"
    }

    cache_set("portfolio", result)
    return result

@app.get("/holdings/{asset_class}")
def holdings(asset_class: str):
    cache_key = f"holdings:{asset_class}"
    cached = cache_get(cache_key, CACHE_TTL["holdings"])
    if cached is not None:
        return cached

    df = build_df()
    if df.empty:
        return []

    if asset_class == "Cash":
        result = build_cash_groups(df)
        cache_set(cache_key, result)
        return result

    filtered = df[df["sub_type"] == asset_class].copy()
    total = df["value_sgd"].sum()

    if total > 0:
        filtered["portfolio_pct"] = filtered["value_sgd"] / total * 100
        filtered["unrealised_gain"] = filtered["market_value"] - filtered["investment_value"]
        filtered["unrealised_gain_pct"] = (
            filtered["unrealised_gain"]
            / filtered["investment_value"].replace(0, 1)
            * 100
        )

    result = filtered.round(2).to_dict(orient="records")
    cache_set(cache_key, result)
    return result

@app.get("/analytics")
def analytics():
    cached = cache_get("analytics", CACHE_TTL["analytics"])
    if cached is not None:
        return cached

    df = build_df()

    if df.empty:
        result = {
            "country_exposure": {},
            "concentration": {
                "largest_holding_pct": 0,
                "top5_pct": 0,
                "top10_pct": 0
            },
            "diversification": {
                "score": 0,
                "hhi": 0
            },
            "risk_signals": [],
            "fx_rates": FX
        }
        cache_set("analytics", result)
        return result

    total = df["value_sgd"].sum()

    if total == 0:
        result = {
            "country_exposure": {},
            "concentration": {
                "largest_holding_pct": 0,
                "top5_pct": 0,
                "top10_pct": 0
            },
            "diversification": {
                "score": 0,
                "hhi": 0
            },
            "risk_signals": [],
            "fx_rates": FX
        }
        cache_set("analytics", result)
        return result

    country_map = {
        "USD": "US",
        "INR": "India",
        "SGD": "Singapore",
        "AUD": "Australia",
        "GBP": "UK",
        "EUR": "Europe"
    }

    df["country"] = df["currency"].map(country_map)
    country = df.groupby("country")["value_sgd"].sum() / total * 100

    weights = df["value_sgd"] / total
    largest = weights.max() * 100
    top5 = weights.nlargest(5).sum() * 100
    top10 = weights.nlargest(10).sum() * 100
    hhi = weights.pow(2).sum() * 10000

    score = 100
    score -= max(0, (largest - 8) * 1.5)
    score -= max(0, (top5 - 30) * 0.8)
    score -= max(0, (top10 - 50) * 0.5)
    score -= max(0, (hhi - 200) / 20)
    score = max(min(score, 100), 0)

    risks = []
    if largest > 12:
        risks.append("High single stock concentration")
    if top5 > 40:
        risks.append("Moderate portfolio concentration")
    if country.get("US", 0) > 50:
        risks.append("High USD exposure")
    if hhi > 600:
        risks.append("Low diversification")

    result = {
        "country_exposure": country.round(2).to_dict(),
        "concentration": {
            "largest_holding_pct": round(largest, 2),
            "top5_pct": round(top5, 2),
            "top10_pct": round(top10, 2)
        },
        "diversification": {
            "score": round(score, 2),
            "hhi": round(hhi, 2)
        },
        "risk_signals": risks,
        "fx_rates": FX
    }

    cache_set("analytics", result)
    return result
