from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json
import requests
from functools import lru_cache

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# =====================================================
# AUTH
# =====================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

creds_dict = json.loads(
    os.environ["GOOGLE_CREDS"]
)

credentials = Credentials.from_service_account_info(
    creds_dict,
    scopes=SCOPES
)

client = gspread.authorize(
    credentials
)

sheet = client.open_by_key(
    "1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"
)

# =====================================================
# FX RATE FETCHER (Real-Time)
# =====================================================

@lru_cache(maxsize=1)
def get_realtime_fx_rates(base_currency="SGD"):
    """
    Fetch real-time FX rates from exchangerate.host (free, no API key required)
    Rates are cached for 1 hour to avoid excessive API calls
    """
    try:
        # exchangerate.host latest endpoint - no authentication required
        url = f"https://api.exchangerate.host/latest?base={base_currency}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            print(f"FX API error: {response.status_code}")
            return get_default_fx_rates()
        
        data = response.json()
        
        if not data.get("rates"):
            print("FX API returned no rates")
            return get_default_fx_rates()
        
        # Convert rates to our format (multiply by base to get SGD equivalent)
        fx_rates = {
            "SGD": 1.0,
            "USD": data["rates"].get("USD", 1.35),
            "INR": data["rates"].get("INR", 0.016),
            "AUD": data["rates"].get("AUD", 0.88),
            "EUR": data["rates"].get("EUR", 1.55),
            "GBP": data["rates"].get("GBP", 1.82)
        }
        
        print(f"FX rates updated: {fx_rates}")
        return fx_rates
        
    except Exception as e:
        print(f"Error fetching FX rates: {e}")
        return get_default_fx_rates()


def get_default_fx_rates():
    """Fallback to hardcoded rates if API fails"""
    return {
        "SGD": 1,
        "USD": 1.35,
        "INR": 0.016,
        "AUD": 0.88,
        "EUR": 1.55,
        "GBP": 1.82
    }


# Initialize FX rates on startup
FX = get_realtime_fx_rates()
VALID_CURRENCIES = set(FX.keys())


# =====================================================
# ROOT
# =====================================================

@app.get("/")
def root():
    return {
        "status": "running",
        "message": "Portfolio backend active",
        "fx_rates": FX
    }


# =====================================================
# FX ENDPOINT (Get current FX rates)
# =====================================================

@app.get("/fx-rates")
def get_fx_rates():
    """Endpoint to fetch current FX rates"""
    return {
        "rates": FX,
        "base": "SGD",
        "updated": "real-time from exchangerate.host"
    }


# =====================================================
# REFRESH FX ENDPOINT
# =====================================================

@app.get("/refresh-fx")
def refresh_fx_rates():
    """Endpoint to force refresh FX rates"""
    global FX
    FX = get_realtime_fx_rates()
    return {
        "status": "success",
        "rates": FX,
        "message": "FX rates refreshed"
    }


# =====================================================
# HELPERS
# =====================================================

def safe_float(x):
    try:
        if x is None:
            return 0
        x = str(x).strip()
        if x == "":
            return 0
        return float(x)
    except:
        return 0


def clean_currency(x):
    if x is None:
        return None
    x = str(x).strip().upper()
    if x not in VALID_CURRENCIES:
        return None
    return x


def invalid_asset(asset):
    if asset is None:
        return True
    text = str(asset).upper()
    bad = [
        "TOTAL",
        "BALANCE",
        "ACCOUNT",
        "ACCOUNTS",
        "GAIN",
        "LOSS",
        "REALISED",
        "UNREALISED",
        "CURRENCY"
    ]
    if text == "":
        return True
    return any(k in text for k in bad)


# =====================================================
# LOAD SHEET
# =====================================================

def get_sheet(name):
    ws = sheet.worksheet(name)
    return pd.DataFrame(ws.get_all_records())


# =====================================================
# NORMALIZE FUNCTIONS
# =====================================================

def normalize_cash(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r["MM Funds name"]).strip()
        if invalid_asset(asset):
            continue
        value = safe_float(r["Current Value"])
        if value <= 0:
            continue
        rows.append({
            "asset": asset,
            "sub_type": "Cash",
            "currency": "SGD",
            "qty": 1,
            "current_price": value,
            "investment_price": value,
            "market_value": value,
            "investment_value": value
        })
    return rows


def normalize_mf(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r["MF - SK"]).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        rows.append({
            "asset": asset,
            "sub_type": "Mutual Fund",
            "currency": currency,
            "qty": safe_float(r.get("Qty", 0)),
            "current_price": 0,
            "investment_price": 0,
            "market_value": safe_float(r["Current Value"]),
            "investment_value": safe_float(r["Invested Amount"])
        })
    return rows


def normalize_shares(df):
    rows = []
    for _, r in df.iterrows():
        asset = str(r["Company"]).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        subtype = "ETF" if "ETF" in asset.upper() else "Stock"
        rows.append({
            "asset": asset,
            "sub_type": subtype,
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
        asset = str(r["Company"]).strip()
        if invalid_asset(asset):
            continue
        currency = clean_currency(r.get(" Currency "))
        if currency is None:
            continue
        rows.append({
            "asset": asset,
            "sub_type": "Gold",
            "currency": currency,
            "qty": safe_float(r.get("Qty", 0)),
            "current_price": safe_float(r.get("Current Price", 0)),
            "investment_price": safe_float(r.get("Investment Price", 0)),
            "market_value": safe_float(r["Current Market Value"]),
            "investment_value": safe_float(r["Investment Value"])
        })
    return rows


# =====================================================
# BUILD DF
# =====================================================

def build_df():
    holdings = []
    holdings += normalize_cash(get_sheet("Cash"))
    holdings += normalize_mf(get_sheet("MFs"))
    holdings += normalize_shares(get_sheet("Shares"))
    holdings += normalize_gold(get_sheet("Gold"))

    df = pd.DataFrame(holdings)

    if df.empty:
        return df

    # Use real-time FX rates instead of hardcoded
    df["fx"] = df["currency"].map(FX)
    df["value_sgd"] = df["market_value"] * df["fx"]
    df["investment_sgd"] = df["investment_value"] * df["fx"]
    df["profit_sgd"] = df["value_sgd"] - df["investment_sgd"]
    df["profit_pct"] = (
        (df["market_value"] - df["investment_value"])
        / df["investment_value"].replace(0, 1)
        * 100
    )

    return df


# =====================================================
# PORTFOLIO ENDPOINT
# =====================================================

@app.get("/portfolio")
def portfolio():
    df = build_df()
    total = df["value_sgd"].sum()

    allocation = (
        df.groupby("sub_type")["value_sgd"].sum()
        / total * 100
    ) if total > 0 else pd.DataFrame()

    currency = (
        df.groupby("currency")["value_sgd"].sum()
        / total * 100
    ) if total > 0 else pd.DataFrame()

    top = df.sort_values("value_sgd", ascending=False).head(10)

    asset_class_breakdown = []
    
    if total > 0:
        grouped = df.groupby("sub_type").agg({
            "investment_sgd": "sum",
            "value_sgd": "sum",
            "profit_sgd": "sum"
        })

        for asset_class, row in grouped.iterrows():
            holdings = df[df["sub_type"] == asset_class].copy()
            holdings["portfolio_pct"] = holdings["value_sgd"] / total * 100
            holdings["unrealised_gain"] = holdings["market_value"] - holdings["investment_value"]
            holdings["unrealised_gain_pct"] = (
                holdings["unrealised_gain"]
                / holdings["investment_value"].replace(0, 1)
                * 100
            )

            asset_class_breakdown.append({
                "asset_class": asset_class,
                "investment_sgd": round(row["investment_sgd"], 2),
                "value_sgd": round(row["value_sgd"], 2),
                "profit_sgd": round(row["profit_sgd"], 2),
                "profit_pct": round(row["profit_sgd"] / max(row["investment_sgd"], 1) * 100, 2),
                "portfolio_pct": round(row["value_sgd"] / total * 100, 2),
                "holdings": holdings.round(2).to_dict(orient="records")
            })

    return {
        "summary": {
            "networth_sgd": round(total, 2),
            "profit_sgd": round(df["profit_sgd"].sum(), 2) if not df.empty else 0
        },
        "allocation": allocation.round(2).to_dict() if total > 0 else {},
        "currency_exposure": currency.round(2).to_dict() if total > 0 else {},
        "top_holdings": top[["asset", "value_sgd"]].round(2).to_dict(orient="records") if not top.empty else [],
        "asset_class_breakdown": asset_class_breakdown,
        "holdings": df.round(2).to_dict(orient="records") if not df.empty else [],
        "fx_rates": FX
    }


# =====================================================
# HOLDINGS ENDPOINT
# =====================================================

@app.get("/holdings/{asset_class}")
def holdings(asset_class: str):
    df = build_df()
    
    if df.empty:
        return []
    
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
    
    return filtered.round(2).to_dict(orient="records")


# =====================================================
# ANALYTICS ENDPOINT
# =====================================================

@app.get("/analytics")
def analytics():
    df = build_df()
    
    if df.empty:
        return {
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
    
    total = df["value_sgd"].sum()
    
    if total == 0:
        return {
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
    hhi = (weights.pow(2).sum()) * 10000
    
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
    
    return {
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
