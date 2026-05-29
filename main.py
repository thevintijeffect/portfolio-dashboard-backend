from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

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

client = gspread.authorize(credentials)

sheet = client.open_by_key(
    "1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"
)

# =====================================================
# FX RATES
# =====================================================

FX = {
    "SGD": 1.0,
    "USD": 1.35,
    "INR": 0.016,
    "EUR": 1.55,
    "GBP": 1.82,
    "AUD": 0.88
}

VALID_CURRENCIES = set(FX.keys())

# =====================================================
# ROOT
# =====================================================

@app.get("/")
def root():
    return {
        "status": "running",
        "message": "Portfolio backend active"
    }

# =====================================================
# HELPERS
# =====================================================

def safe_float(x):
    try:
        if x is None:
            return 0.0
        x = str(x).strip()
        if x == "" or x.lower() == "nan":
            return 0.0
        return float(x)
    except:
        return 0.0


def clean_currency(x):
    if x is None:
        return None

    x = str(x).strip().upper()

    # remove junk values
    if x not in VALID_CURRENCIES:
        return None

    return x


def is_invalid_asset(name):
    if name is None:
        return True

    name = str(name).strip().upper()

    invalid_keywords = [
        "TOTAL",
        "BALANCE",
        "ACCOUNT",
        "ACCOUNTS",
        "DEBT",
        "GAIN",
        "LOSS",
        "REALISED",
        "UNREALISED",
        "CURRENCY"
    ]

    if name == "":
        return True

    return any(k in name for k in invalid_keywords)

# =====================================================
# SHEET LOADER
# =====================================================

def get_sheet(name):
    ws = sheet.worksheet(name)
    return pd.DataFrame(ws.get_all_records())

# =====================================================
# NORMALIZERS
# =====================================================

def normalize_cash(df):
    rows = []

    for _, r in df.iterrows():

        asset = str(r["MM Funds name"]).strip()

        if is_invalid_asset(asset):
            continue

        value = safe_float(r["Current Value"])

        if value <= 0:
            continue

        rows.append({
            "asset": asset,
            "sub_type": "Cash",
            "current_value": value,
            "cost_basis": value,
            "currency": "SGD"
        })

    return rows


def normalize_mf(df):
    rows = []

    for _, r in df.iterrows():

        asset = str(r["MF - SK"]).strip()

        if is_invalid_asset(asset):
            continue

        currency = clean_currency(r.get(" Currency "))

        if currency is None:
            continue

        rows.append({
            "asset": asset,
            "sub_type": "Mutual Fund",
            "current_value": safe_float(r["Current Value"]),
            "cost_basis": safe_float(r["Invested Amount"]),
            "currency": currency
        })

    return rows


def normalize_shares(df):
    rows = []

    for _, r in df.iterrows():

        asset = str(r["Company"]).strip()

        if is_invalid_asset(asset):
            continue

        currency = clean_currency(r.get(" Currency "))

        if currency is None:
            continue

        subtype = "ETF" if "ETF" in asset.upper() else "Stock"

        rows.append({
            "asset": asset,
            "sub_type": subtype,
            "current_value": safe_float(r["Current Market Value"]),
            "cost_basis": safe_float(r["Investment Value"]),
            "currency": currency
        })

    return rows


def normalize_gold(df):
    rows = []

    for _, r in df.iterrows():

        asset = str(r["Company"]).strip()

        if is_invalid_asset(asset):
            continue

        currency = clean_currency(r.get(" Currency "))

        if currency is None:
            continue

        rows.append({
            "asset": asset,
            "sub_type": "Gold",
            "current_value": safe_float(r["Current Market Value"]),
            "cost_basis": safe_float(r["Investment Value"]),
            "currency": currency
        })

    return rows

# =====================================================
# BUILD PORTFOLIO
# =====================================================

def build_df():

    holdings = []

    holdings += normalize_cash(get_sheet("Cash"))
    holdings += normalize_mf(get_sheet("MFs"))
    holdings += normalize_shares(get_sheet("Shares"))
    holdings += normalize_gold(get_sheet("Gold"))

    df = pd.DataFrame(holdings)

    df["fx"] = df["currency"].map(FX).fillna(1.0)

    df["value_sgd"] = df["current_value"] * df["fx"]
    df["cost_sgd"] = df["cost_basis"] * df["fx"]
    df["profit_sgd"] = df["value_sgd"] - df["cost_sgd"]

    return df

# =====================================================
# PORTFOLIO API
# =====================================================

@app.get("/portfolio")
def portfolio():

    try:

        df = build_df()

        total = df["value_sgd"].sum()

        allocation = (
            df.groupby("sub_type")["value_sgd"].sum()
            / total * 100
        )

        # STRICT currency filtering (prevents junk)
        df_currency = df[df["currency"].isin(VALID_CURRENCIES)]

        currency = (
            df_currency.groupby("currency")["value_sgd"].sum()
            / total * 100
        )

        top = df.sort_values("value_sgd", ascending=False).head(10)

        return {
            "summary": {
                "networth_sgd": round(total, 2),
                "profit_sgd": round(df["profit_sgd"].sum(), 2)
            },
            "allocation": allocation.round(2).to_dict(),
            "currency_exposure": currency.round(2).to_dict(),
            "top_holdings": top[["asset", "value_sgd"]]
                .round(2)
                .to_dict(orient="records")
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# =====================================================
# DEBUG (CLEAN)
# =====================================================

@app.get("/debug")
def debug():

    try:

        df = build_df()

        return {
            "currencies_raw": df["currency"].unique().tolist(),
            "asset_types": df["sub_type"].value_counts().to_dict(),
            "sample_rows": df.head(15).to_dict(orient="records")
        }

    except Exception as e:
        return {
            "error": str(e)
        }
