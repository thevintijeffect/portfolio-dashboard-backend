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

    "SGD":1,

    "USD":1.35,

    "INR":0.016,

    "AUD":0.88,

    "EUR":1.55,

    "GBP":1.82

}

VALID_CURRENCIES=set(
    FX.keys()
)

# =====================================================
# ROOT
# =====================================================

@app.get("/")

def root():

    return {

        "status":"running",

        "message":"Portfolio backend active"

    }

# =====================================================
# HELPERS
# =====================================================

def safe_float(x):

    try:

        if x is None:

            return 0

        x=str(
            x
        ).strip()

        if x=="":

            return 0

        return float(x)

    except:

        return 0


def clean_currency(x):

    if x is None:

        return None

    x=str(
        x
    ).strip().upper()

    if x not in VALID_CURRENCIES:

        return None

    return x


def invalid_asset(asset):

    if asset is None:

        return True

    text=str(
        asset
    ).upper()

    bad=[

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

    if text=="":

        return True

    return any(
        k in text
        for k in bad
    )


# =====================================================
# LOAD SHEET
# =====================================================

def get_sheet(name):

    ws=sheet.worksheet(
        name
    )

    return pd.DataFrame(
        ws.get_all_records()
    )

# =====================================================
# NORMALIZE
# =====================================================

def normalize_cash(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            r["MM Funds name"]
        ).strip()

        if invalid_asset(
            asset
        ):

            continue

        value=safe_float(
            r["Current Value"]
        )

        if value<=0:

            continue

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

        asset=str(
            r["MF - SK"]
        ).strip()

        if invalid_asset(
            asset
        ):

            continue

        currency=clean_currency(
            r.get(
                " Currency "
            )
        )

        if currency is None:

            continue

        rows.append({

            "asset":asset,

            "sub_type":"Mutual Fund",

            "current_value":

            safe_float(
                r[
                    "Current Value"
                ]
            ),

            "cost_basis":

            safe_float(
                r[
                    "Invested Amount"
                ]
            ),

            "currency":

            currency

        })

    return rows


def normalize_shares(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            r["Company"]
        ).strip()

        if invalid_asset(
            asset
        ):

            continue

        currency=clean_currency(
            r.get(
                " Currency "
            )
        )

        if currency is None:

            continue

        subtype=(

            "ETF"

            if "ETF"

            in asset.upper()

            else "Stock"

        )

        rows.append({

            "asset":asset,

            "sub_type":subtype,

            "current_value":

            safe_float(
                r[
                    "Current Market Value"
                ]
            ),

            "cost_basis":

            safe_float(
                r[
                    "Investment Value"
                ]
            ),

            "currency":

            currency

        })

    return rows


def normalize_gold(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            r["Company"]
        ).strip()

        if invalid_asset(
            asset
        ):

            continue

        currency=clean_currency(
            r.get(
                " Currency "
            )
        )

        if currency is None:

            continue

        rows.append({

            "asset":asset,

            "sub_type":"Gold",

            "current_value":

            safe_float(
                r[
                    "Current Market Value"
                ]
            ),

            "cost_basis":

            safe_float(
                r[
                    "Investment Value"
                ]
            ),

            "currency":

            currency

        })

    return rows


# =====================================================
# BUILD DF
# =====================================================

def build_df():

    holdings=[]

    holdings += normalize_cash(
        get_sheet(
            "Cash"
        )
    )

    holdings += normalize_mf(
        get_sheet(
            "MFs"
        )
    )

    holdings += normalize_shares(
        get_sheet(
            "Shares"
        )
    )

    holdings += normalize_gold(
        get_sheet(
            "Gold"
        )
    )

    df=pd.DataFrame(
        holdings
    )

    df["fx"]=df[
        "currency"
    ].map(
        FX
    )

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

# =====================================================
# ANALYTICS ENGINE
# =====================================================

def analytics_engine(df):

    total = df["value_sgd"].sum()

    # =========================
    # COUNTRY EXPOSURE
    # =========================

    country_map = {
        "USD": "US",
        "INR": "India",
        "SGD": "Singapore",
        "AUD": "Australia",
        "GBP": "UK",
        "EUR": "Europe"
    }

    df["country"] = df["currency"].map(country_map)

    country = (
        df.groupby("country")["value_sgd"].sum()
        / total * 100
    )

    # =========================
    # CONCENTRATION
    # =========================

    weights = df["value_sgd"] / total

    largest = weights.max() * 100
    top5 = weights.nlargest(5).sum() * 100
    top10 = weights.nlargest(10).sum() * 100

    # =========================
    # HERFINDAHL INDEX
    # =========================

    hhi = (weights.pow(2).sum()) * 10000

    # =========================
    # DIVERSIFICATION SCORE (FIXED)
    # =========================

    score = 100

    # Penalty 1: largest holding
    score -= max(0, (largest - 8) * 1.5)

    # Penalty 2: top 5 concentration
    score -= max(0, (top5 - 30) * 0.8)

    # Penalty 3: top 10 concentration
    score -= max(0, (top10 - 50) * 0.5)

    # Penalty 4: HHI (scaled)
    score -= max(0, (hhi - 200) / 20)

    # Clamp
    score = max(min(score, 100), 0)

    # =========================
    # RISK SIGNALS
    # =========================

    risks = []

    if largest > 12:
        risks.append("High single stock concentration")

    if top5 > 40:
        risks.append("Moderate portfolio concentration")

    if country.get("US", 0) > 50:
        risks.append("High USD exposure")

    if hhi > 600:
        risks.append("Low diversification")

    # =========================
    # OUTPUT
    # =========================

    return {

        "country_exposure":
        country.round(2).to_dict(),

        "concentration": {
            "largest_holding_pct": round(largest, 2),
            "top5_pct": round(top5, 2),
            "top10_pct": round(top10, 2)
        },

        "diversification": {
            "score": round(score, 2),
            "hhi": round(hhi, 2)
        },

        "risk_signals": risks
    }
# =====================================================
# PORTFOLIO
# =====================================================

@app.get("/portfolio")
def portfolio():

    df = build_df()
    total = df["value_sgd"].sum()

    # =====================================
    # Asset Class Totals
    # =====================================

    asset_class_totals = (
        df.groupby("sub_type")["value_sgd"]
        .sum()
        .sort_values(ascending=False)
    )

    asset_class_breakdown = []

    for asset_class, total_value in asset_class_totals.items():

        holdings = (
            df[df["sub_type"] == asset_class]
            .sort_values("value_sgd", ascending=False)
        )

        asset_class_breakdown.append({
            "asset_class": asset_class,
            "total_value_sgd": round(total_value, 2),
            "percentage": round(total_value / total * 100, 2),
            "holdings": holdings[
                ["asset", "currency", "value_sgd", "profit_sgd"]
            ].round(2).to_dict(orient="records")
        })

    allocation = (
        df.groupby("sub_type")["value_sgd"].sum()
        / total * 100
    )

    currency = (
        df.groupby("currency")["value_sgd"].sum()
        / total * 100
    )

    top = (
        df.sort_values("value_sgd", ascending=False)
        .head(10)
    )

    return {
        "summary": {
            "networth_sgd": round(total, 2),
            "profit_sgd": round(df["profit_sgd"].sum(), 2)
        },
        "allocation": allocation.round(2).to_dict(),
        "currency_exposure": currency.round(2).to_dict(),
        "top_holdings": top[
            ["asset", "value_sgd"]
        ].round(2).to_dict(orient="records"),
        "asset_class_breakdown": asset_class_breakdown,
        "holdings": df[
            ["asset", "sub_type", "currency", "value_sgd", "profit_sgd"]
        ].round(2).to_dict(orient="records")
    }

# =====================================================
# ANALYTICS ENDPOINT
# =====================================================

@app.get("/analytics")

def analytics():

    df=build_df()

    return analytics_engine(
        df
    )
