from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

# ---------------------------------
# GOOGLE AUTH
# ---------------------------------

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

SHEET_ID="1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"

sheet=client.open_by_key(
    SHEET_ID
)

# ---------------------------------
# FX RATES
# manually maintained initially
# ---------------------------------

FX_TO_SGD = {

    "SGD":1,

    "USD":1.35,

    "INR":0.016,

    "AUD":0.88,

    "GBP":1.82,

    "EUR":1.55
}

# ---------------------------------
# ROOT
# ---------------------------------

@app.get("/")
def root():

    return {

        "status":"running",

        "message":"portfolio backend active"
    }

# ---------------------------------
# READ SHEETS
# ---------------------------------

def get_sheet(tab):

    ws=sheet.worksheet(tab)

    data=ws.get_all_records()

    return pd.DataFrame(data)

# ---------------------------------
# NORMALIZATION
# ---------------------------------

def normalize_cash(df):

    rows=[]

    for _,r in df.iterrows():

        rows.append({

            "asset":

            r.iloc[0],

            "asset_class":

            "Cash",

            "sub_type":

            "Cash",

            "quantity":

            1,

            "current_value":

            float(r.iloc[1]),

            "cost_basis":

            float(r.iloc[1]),

            "currency":

            "SGD"
        })

    return pd.DataFrame(rows)

def normalize_mf(df):

    rows=[]

    for _,r in df.iterrows():

        rows.append({

            "asset":r.iloc[0],

            "asset_class":"Mutual Fund",

            "sub_type":"Mutual Fund",

            "quantity":r.iloc[2],

            "current_value":r.iloc[4],

            "cost_basis":r.iloc[5],

            "currency":r.iloc[9]
        })

    return pd.DataFrame(rows)

def normalize_gold(df):

    rows=[]

    for _,r in df.iterrows():

        rows.append({

            "asset":r.iloc[0],

            "asset_class":"Gold",

            "sub_type":"Gold",

            "quantity":r.iloc[2],

            "current_value":r.iloc[4],

            "cost_basis":r.iloc[6],

            "currency":r.iloc[9]
        })

    return pd.DataFrame(rows)

def normalize_shares(df):

    rows=[]

    for _,r in df.iterrows():

        asset=r.iloc[0]

        subtype="ETF" if "ETF" in str(asset).upper() else "Stock"

        rows.append({

            "asset":asset,

            "asset_class":"Equity",

            "sub_type":subtype,

            "quantity":r.iloc[2],

            "current_value":r.iloc[4],

            "cost_basis":r.iloc[6],

            "currency":r.iloc[11]
        })

    return pd.DataFrame(rows)

# ---------------------------------
# ANALYTICS ENGINE
# ---------------------------------

@app.get("/portfolio")

def portfolio():

    try:

        cash=normalize_cash(
            get_sheet("Cash")
        )

        mf=normalize_mf(
            get_sheet("MFs")
        )

        shares=normalize_shares(
            get_sheet("Shares")
        )

        gold=normalize_gold(
            get_sheet("Gold")
        )

        holdings=pd.concat(

            [cash,mf,shares,gold],

            ignore_index=True
        )

        holdings["fx"]=holdings[
            "currency"
        ].map(FX_TO_SGD)

        holdings["value_sgd"]=(
            holdings["current_value"]
            *
            holdings["fx"]
        )

        holdings["cost_sgd"]=(
            holdings["cost_basis"]
            *
            holdings["fx"]
        )

        holdings["profit_sgd"]=(
            holdings["value_sgd"]
            -
            holdings["cost_sgd"]
        )

        total=holdings[
            "value_sgd"
        ].sum()

        allocation=(
            holdings
            .groupby(
                "sub_type"
            )["value_sgd"]
            .sum()
            / total
            *100
        )

        currency=(
            holdings
            .groupby(
                "currency"
            )["value_sgd"]
            .sum()
            / total
            *100
        )

        top=(
            holdings
            .sort_values(
                "value_sgd",
                ascending=False
            )
            .head(10)
        )

        return {

            "summary":{

                "networth_sgd":

                round(total,2),

                "profit_sgd":

                round(
                    holdings[
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
            ].to_dict(
                orient="records"
            ),

            "holdings":

            holdings.fillna(
                ""
            ).to_dict(
                orient="records"
            )
        }

    except Exception as e:

        return {

            "status":"error",

            "message":str(e)
        }
