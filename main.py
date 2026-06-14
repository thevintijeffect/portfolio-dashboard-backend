from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

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
# FX TABLE
# =====================================================

FX = {
    "SGD": 1,
    "USD": 1.35,
    "INR": 0.016,
    "AUD": 0.88,
    "EUR": 1.55,
    "GBP": 1.82
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
# NORMALIZE
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
            "currency": 
