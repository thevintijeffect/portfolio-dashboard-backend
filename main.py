from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

# -----------------------------
# GOOGLE SHEETS CONFIG
# -----------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

# Load credentials from environment variable
creds_dict = json.loads(os.environ["GOOGLE_CREDS"])

credentials = Credentials.from_service_account_info(
    creds_dict,
    scopes=SCOPES
)

client = gspread.authorize(credentials)

SHEET_ID = "1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"

sheet = client.open_by_key(SHEET_ID)

# -----------------------------
# ROOT
# -----------------------------
@app.get("/")
def home():
    return {
        "status": "running",
        "message": "Portfolio backend active"
    }

# -----------------------------
# HELPERS
# -----------------------------
def get_sheet_data(tab_name):
    ws = sheet.worksheet(tab_name)
    data = ws.get_all_records()
    return pd.DataFrame(data)

# -----------------------------
# CLASSIFICATION
# -----------------------------
def classify_shares(df):

    def classify(asset_name):
        if isinstance(asset_name, str) and "ETF" in asset_name.upper():
            return "ETF"
        return "Stock"

    df["sub_type"] = df.iloc[:, 0].apply(classify)
    df["asset_class"] = "Equity"

    return df

def normalize_mf(df):
    df["sub_type"] = "Mutual Fund"
    df["asset_class"] = "Mutual Fund"
    return df

def normalize_gold(df):
    df["sub_type"] = "Gold"
    df["asset_class"] = "Gold"
    return df

def normalize_cash(df):
    df["sub_type"] = "Cash"
    df["asset_class"] = "Cash"
    return df

# -----------------------------
# PORTFOLIO API
# -----------------------------
@app.get("/portfolio")
def portfolio():

    cash = get_sheet_data("Cash")
    mf = get_sheet_data("MFs")
    shares = get_sheet_data("Shares")
    gold = get_sheet_data("Gold")

    cash = normalize_cash(cash)
    mf = normalize_mf(mf)
    shares = classify_shares(shares)
    gold = normalize_gold(gold)

    all_holdings = pd.concat(
        [cash, mf, shares, gold],
        ignore_index=True
    )

    return {
        "status": "success",
        "total_holdings": len(all_holdings),
        "holdings": all_holdings.fillna("").to_dict(orient="records")
    }
