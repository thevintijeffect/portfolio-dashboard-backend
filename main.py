from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

# ==========================================
# AUTH
# ==========================================

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

# ==========================================
# FX TABLE
# ==========================================

FX_TO_SGD = {

    "SGD":1,

    "USD":1.35,

    "INR":0.016,

    "AUD":0.88,

    "GBP":1.82,

    "EUR":1.55

}

# ==========================================
# ROOT
# ==========================================

@app.get("/")
def root():

    return {

        "status":"running",

        "message":"Portfolio backend active"

    }

# ==========================================
# HELPERS
# ==========================================

def safe_num(x):

    try:

        if x is None:

            return 0

        if str(x).strip()=="":

            return 0

        return float(x)

    except:

        return 0


def clean_currency(x):

    if x is None:

        return "SGD"

    value = str(
        x
    ).strip().upper()

    if value=="":

        return "SGD"

    return value


def get_sheet(tab):

    ws = sheet.worksheet(
        tab
    )

    data = ws.get_all_records()

    return pd.DataFrame(
        data
    )

# ==========================================
# NORMALIZATION
# ==========================================

def normalize_cash(df):

    rows=[]

    for _,r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset=="":

            continue

        value = safe_num(
            r.iloc[1]
        )

        rows.append({

            "asset":asset,

            "sub_type":"Cash",

            "current_value":value,

            "cost_basis":value,

            "currency":"SGD"

        })

    return rows


def normalize_mf(df):

    rows=[]

    for _,r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset=="":

            continue

        rows.append({

            "asset":asset,

            "sub_type":"Mutual Fund",

            "current_value":

            safe_num(
                r.get(
                    "Current Value",
                    0
                )
            ),

            "cost_basis":

            safe_num(
                r.get(
                    "Cost Basis",
                    0
                )
            ),

            "currency":

            clean_currency(
                r.get(
                    "Currency",
                    "SGD"
                )
            )

        })

    return rows


def normalize_gold(df):

    rows=[]

    for _,r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset=="":

            continue

        rows.append({

            "asset":asset,

            "sub_type":"Gold",

            "current_value":

            safe_num(
                r.get(
                    "Current Value",
                    0
                )
            ),

            "cost_basis":

            safe_num(
                r.get(
                    "Cost Basis",
                    0
                )
            ),

            "currency":

            clean_currency(
                r.get(
                    "Currency",
                    "SGD"
                )
            )

        })

    return rows


def normalize_shares(df):

    rows=[]

    for _,r in df.iterrows():

        asset = str(
            r.iloc[0]
        ).strip()

        if asset=="":

            continue

        subtype = (

            "ETF"

            if "ETF" in asset.upper()

            else "Stock"

        )

        rows.append({

            "asset":asset,

            "sub_type":subtype,

            "current_value":

            safe_num(
                r.get(
                    "Current Value",
                    0
                )
            ),

            "cost_basis":

            safe_num(
                r.get(
                    "Cost Basis",
                    0
                )
            ),

            "currency":

            clean_currency(
                r.get(
                    "Currency",
                    "SGD"
                )
            )

        })

    return rows

# ==========================================
# BUILD HOLDINGS
# ==========================================

def build_holdings():

    holdings=[]

    holdings.extend(

        normalize_cash(

            get_sheet(
                "Cash"
            )

        )

    )

    holdings.extend(

        normalize_mf(

            get_sheet(
                "MFs"
            )

        )

    )

    holdings.extend(

        normalize_shares(

            get_sheet(
                "Shares"
            )

        )

    )

    holdings.extend(

        normalize_gold(

            get_sheet(
                "Gold"
            )

        )

    )

    df = pd.DataFrame(
        holdings
    )

    df["fx"] = df[
        "currency"
    ].map(
        FX_TO_SGD
    ).fillna(1)

    df["value_sgd"]=(

        df[
            "current_value"
        ]

        *

        df[
            "fx"
        ]

    )

    df["cost_sgd"]=(

        df[
            "cost_basis"
        ]

        *

        df[
            "fx"
        ]

    )

    df["profit_sgd"]=(

        df[
            "value_sgd"
        ]

        -

        df[
            "cost_sgd"
        ]

    )

    return df

# ==========================================
# PORTFOLIO
# ==========================================

@app.get("/portfolio")

def portfolio():

    try:

        df = build_holdings()

        total = df[
            "value_sgd"
        ].sum()

        allocation=(

            df.groupby(
                "sub_type"
            )[
                "value_sgd"
            ]

            .sum()

            /

            total

            *

            100

        )

        currency=(

            df.groupby(
                "currency"
            )[
                "value_sgd"
            ]

            .sum()

            /

            total

            *

            100

        )

        top = (

            df.sort_values(

                "value_sgd",

                ascending=False

            )

            .head(10)

        )

        return {

            "summary":{

                "networth_sgd":

                round(
                    total,
                    2
                ),

                "profit_sgd":

                round(
                    df[
                        "profit_sgd"
                    ].sum(),
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

            top[
                [

                    "asset",

                    "value_sgd"

                ]

            ].round(
                2
            ).to_dict(
                orient="records"
            )

        }

    except Exception as e:

        return {

            "status":"error",

            "message":str(e)

        }

# ==========================================
# DEBUG
# ==========================================

@app.get("/debug")

def debug():

    try:

        mf = get_sheet("MFs")

        shares = get_sheet("Shares")

        gold = get_sheet("Gold")

        return {

            "mf_columns":

            mf.columns.tolist(),

            "shares_columns":

            shares.columns.tolist(),

            "gold_columns":

            gold.columns.tolist()

        }

    except Exception as e:

        return {

            "error":

            str(e)

        }
