from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

# =====================================================
# GOOGLE AUTH
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

SHEET_ID = "1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"

sheet = client.open_by_key(
    SHEET_ID
)

# =====================================================
# FX RATES
# Temporary manual FX table
# We will automate later
# =====================================================

FX_TO_SGD = {

    "SGD": 1.0,

    "USD": 1.35,

    "INR": 0.016,

    "AUD": 0.88,

    "GBP": 1.82,

    "EUR": 1.55,

    "": 1.0
}

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

def safe_num(value):

    if value is None:
        return 0

    if value == "":
        return 0

    try:
        return float(value)

    except:
        return 0


def get_sheet(tab):

    ws = sheet.worksheet(tab)

    data = ws.get_all_records()

    return pd.DataFrame(data)


# =====================================================
# NORMALIZATION
# =====================================================

def normalize_cash(df):

    rows = []

    for _, r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset == "":
            continue

        value = safe_num(
            r.iloc[1]
        )

        rows.append({

            "asset": asset,

            "asset_class": "Cash",

            "sub_type": "Cash",

            "quantity": 1,

            "current_value": value,

            "cost_basis": value,

            "currency": "SGD"

        })

    return pd.DataFrame(rows)


def normalize_mf(df):

    rows = []

    for _, r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset == "":
            continue

        rows.append({

            "asset": asset,

            "asset_class": "Mutual Fund",

            "sub_type": "Mutual Fund",

            "quantity": safe_num(
                r.iloc[2]
            ),

            "current_value": safe_num(
                r.iloc[4]
            ),

            "cost_basis": safe_num(
                r.iloc[5]
            ),

            "currency": str(
                r.iloc[9]
            ).strip()

        })

    return pd.DataFrame(rows)


def normalize_gold(df):

    rows = []

    for _, r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset == "":
            continue

        rows.append({

            "asset": asset,

            "asset_class": "Gold",

            "sub_type": "Gold",

            "quantity": safe_num(
                r.iloc[2]
            ),

            "current_value": safe_num(
                r.iloc[4]
            ),

            "cost_basis": safe_num(
                r.iloc[6]
            ),

            "currency": str(
                r.iloc[9]
            ).strip()

        })

    return pd.DataFrame(rows)


def normalize_shares(df):

    rows = []

    for _, r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset == "":
            continue

        subtype = (
            "ETF"
            if "ETF" in asset.upper()
            else "Stock"
        )

        rows.append({

            "asset": asset,

            "asset_class": "Equity",

            "sub_type": subtype,

            "quantity": safe_num(
                r.iloc[2]
            ),

            "current_value": safe_num(
                r.iloc[4]
            ),

            "cost_basis": safe_num(
                r.iloc[6]
            ),

            "currency": str(
                r.iloc[11]
            ).strip()

        })

    return pd.DataFrame(rows)


# =====================================================
# PORTFOLIO API
# =====================================================

@app.get("/portfolio")

def portfolio():

    try:

        cash = normalize_cash(
            get_sheet("Cash")
        )

        mf = normalize_mf(
            get_sheet("MFs")
        )

        shares = normalize_shares(
            get_sheet("Shares")
        )

        gold = normalize_gold(
            get_sheet("Gold")
        )

        holdings = pd.concat(

            [
                cash,
                mf,
                shares,
                gold
            ],

            ignore_index=True

        )

        holdings["fx"] = holdings[
            "currency"
        ].map(
            FX_TO_SGD
        )

        holdings["fx"] = holdings[
            "fx"
        ].fillna(
            1
        )

        holdings["value_sgd"] = (

            holdings[
                "current_value"
            ]

            *

            holdings[
                "fx"
            ]

        )

        holdings["cost_sgd"] = (

            holdings[
                "cost_basis"
            ]

            *

            holdings[
                "fx"
            ]

        )

        holdings["profit_sgd"] = (

            holdings[
                "value_sgd"
            ]

            -

            holdings[
                "cost_sgd"
            ]

        )

        total_value = holdings[
            "value_sgd"
        ].sum()

        total_profit = holdings[
            "profit_sgd"
        ].sum()

        allocation = (

            holdings

            .groupby(
                "sub_type"
            )["value_sgd"]

            .sum()

            / total_value

            * 100

        )

        currency = (

            holdings

            .groupby(
                "currency"
            )["value_sgd"]

            .sum()

            / total_value

            * 100

        )

        holdings["weight_pct"] = (

            holdings[
                "value_sgd"
            ]

            /

            total_value

            * 100

        )

        top_holdings = (

            holdings

            .sort_values(

                "value_sgd",

                ascending=False

            )

            .head(10)

        )

        return {

            "summary": {

                "networth_sgd":

                round(
                    total_value,
                    2
                ),

                "profit_sgd":

                round(
                    total_profit,
                    2
                )

            },

            "allocation":

            allocation.round(
                2
            ).to_dict(),

            "currency_exposure":

            currency.round(
                2
            ).to_dict(),

            "top_holdings":

            top_holdings[
                [

                    "asset",

                    "value_sgd",

                    "weight_pct"

                ]

            ].round(
                2
            ).to_dict(

                orient="records"

            ),

            "holdings":

            holdings.fillna(
                ""
            ).round(
                2
            ).to_dict(

                orient="records"

            )

        }

    except Exception as e:

        return {

            "status": "error",

            "message": str(e)

        }
