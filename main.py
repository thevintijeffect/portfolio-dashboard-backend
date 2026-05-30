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

    total=df[
        "value_sgd"
    ].sum()

    country_map={

        "USD":"US",

        "INR":"India",

        "SGD":"Singapore",

        "AUD":"Australia",

        "GBP":"UK",

        "EUR":"Europe"

    }

    df["country"]=df[
        "currency"
    ].map(
        country_map
    )

    country=(

        df.groupby(
            "country"
        )[
            "value_sgd"
        ]

        .sum()

        /

        total

        *

        100

    )

    holding_pct=(

        df[
            "value_sgd"
        ]

        /

        total

    )

    largest=round(
        holding_pct.max()*100,
        2
    )

    top5=round(
        holding_pct.nlargest(
            5
        ).sum()*100,
        2
    )

    top10=round(
        holding_pct.nlargest(
            10
        ).sum()*100,
        2
    )

    hhi=round(

        holding_pct.pow(
            2
        ).sum()

        *

        10000,

        0

    )

    score = 100

score -= min(30, (largest_holding_pct - 10) * 2)
score -= min(30, (top5_pct - 30))
score -= min(20, (hhi - 200) / 20)

score = max(min(score, 100), 0)
    risks=[]

    if largest>15:

        risks.append(
            "Large single holding concentration"
        )

    if top5>50:

        risks.append(
            "Top holdings concentration elevated"
        )

    if country.get(
        "US",
        0
    )>50:

        risks.append(
            "High USD exposure"
        )

    return {

        "country_exposure":

        country.round(
            2
        ).to_dict(),

        "concentration":{

            "largest_holding_pct":

            largest,

            "top5_pct":

            top5,

            "top10_pct":

            top10

        },

        "diversification":{

            "score":

            score,

            "hhi":

            hhi

        },

        "risk_signals":

        risks

    }

# =====================================================
# PORTFOLIO
# =====================================================

@app.get("/portfolio")

def portfolio():

    df=build_df()

    total=df[
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

    top=(

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

# =====================================================
# ANALYTICS ENDPOINT
# =====================================================

@app.get("/analytics")

def analytics():

    df=build_df()

    return analytics_engine(
        df
    )
