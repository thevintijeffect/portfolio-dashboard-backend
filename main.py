from fastapi import FastAPI
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os
import json

app = FastAPI()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

creds_dict=json.loads(
    os.environ["GOOGLE_CREDS"]
)

credentials=Credentials.from_service_account_info(
    creds_dict,
    scopes=SCOPES
)

client=gspread.authorize(
    credentials
)

sheet=client.open_by_key(
    "1A9vTee-Jfg8lgLx18-942VuBHkQnrzqI3n2uQOCwOyA"
)

FX_TO_SGD={

    "SGD":1,
    "USD":1.35,
    "INR":0.016,
    "AUD":0.88,
    "GBP":1.82,
    "EUR":1.55

}

@app.get("/")
def root():

    return {

        "status":"running",

        "message":"Portfolio backend active"

    }


def safe_num(x):

    try:

        if x=="" or x is None:

            return 0

        return float(x)

    except:

        return 0


def get_sheet(tab):

    ws=sheet.worksheet(tab)

    return pd.DataFrame(
        ws.get_all_records()
    )


def get_value(row,column):

    if column not in row:

        return ""

    return row[column]


def normalize_cash(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            get_value(
                r,
                df.columns[0]
            )
        ).strip()

        if asset=="":

            continue

        value=safe_num(

            get_value(
                r,
                df.columns[1]
            )

        )

        rows.append({

            "asset":asset,

            "asset_class":"Cash",

            "sub_type":"Cash",

            "quantity":1,

            "current_value":value,

            "cost_basis":value,

            "currency":"SGD"

        })

    return rows


def normalize_mf(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            get_value(
                r,
                df.columns[0]
            )
        ).strip()

        if asset=="":

            continue

        rows.append({

            "asset":asset,

            "asset_class":"Mutual Fund",

            "sub_type":"Mutual Fund",

            "quantity":safe_num(
                get_value(
                    r,
                    df.columns[2]
                )
            ),

            "current_value":safe_num(
                get_value(
                    r,
                    df.columns[4]
                )
            ),

            "cost_basis":safe_num(
                get_value(
                    r,
                    df.columns[5]
                )
            ),

            "currency":str(
                get_value(
                    r,
                    df.columns[9]
                )
            ).strip()

        })

    return rows


def normalize_gold(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            get_value(
                r,
                df.columns[0]
            )
        ).strip()

        if asset=="":

            continue

        rows.append({

            "asset":asset,

            "asset_class":"Gold",

            "sub_type":"Gold",

            "quantity":safe_num(
                get_value(
                    r,
                    df.columns[2]
                )
            ),

            "current_value":safe_num(
                get_value(
                    r,
                    df.columns[4]
                )
            ),

            "cost_basis":safe_num(
                get_value(
                    r,
                    df.columns[6]
                )
            ),

            "currency":str(
                get_value(
                    r,
                    df.columns[9]
                )
            ).strip()

        })

    return rows


def normalize_shares(df):

    rows=[]

    for _,r in df.iterrows():

        asset=str(
            get_value(
                r,
                df.columns[0]
            )
        ).strip()

        if asset=="":

            continue

        subtype=(
            "ETF"
            if "ETF" in asset.upper()
            else "Stock"
        )

        rows.append({

            "asset":asset,

            "asset_class":"Equity",

            "sub_type":subtype,

            "quantity":safe_num(
                get_value(
                    r,
                    df.columns[2]
                )
            ),

            "current_value":safe_num(
                get_value(
                    r,
                    df.columns[4]
                )
            ),

            "cost_basis":safe_num(
                get_value(
                    r,
                    df.columns[6]
                )
            ),

            "currency":str(
                get_value(
                    r,
                    df.columns[-1]
                )
            ).strip()

        })

    return rows


@app.get("/portfolio")
def portfolio():

    try:

        holdings=[]

        holdings.extend(
            normalize_cash(
                get_sheet("Cash")
            )
        )

        holdings.extend(
            normalize_mf(
                get_sheet("MFs")
            )
        )

        holdings.extend(
            normalize_shares(
                get_sheet("Shares")
            )
        )

        holdings.extend(
            normalize_gold(
                get_sheet("Gold")
            )
        )

        df=pd.DataFrame(
            holdings
        )

        df["fx"]=df[
            "currency"
        ].map(
            FX_TO_SGD
        ).fillna(1)

        df["value_sgd"]=(
            df["current_value"]
            *
            df["fx"]
        )

        df["cost_sgd"]=(
            df["cost_basis"]
            *
            df["fx"]
        )

        df["profit_sgd"]=(
            df["value_sgd"]
            -
            df["cost_sgd"]
        )

        total=df[
            "value_sgd"
        ].sum()

        allocation=(
            df.groupby(
                "sub_type"
            )["value_sgd"]
            .sum()/total*100
        )

        currency=(
            df.groupby(
                "currency"
            )["value_sgd"]
            .sum()/total*100
        )

        top=df.sort_values(
            "value_sgd",
            ascending=False
        ).head(10)

        return {

            "summary":{

                "networth_sgd":
                round(total,2),

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
