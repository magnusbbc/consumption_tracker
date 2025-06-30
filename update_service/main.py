import os
import pandas as pd
import requests
import psycopg2
from datetime import date, datetime, timedelta

# Config from environment
DB_CONFIG = {
    'dbname': os.environ["DB_NAME"],
    'user': os.environ["DB_USER"],
    'password': os.environ["DB_PASS"],
    'host': os.environ["DB_HOST"],
    'port': os.environ.get("DB_PORT", "5432"),
}
CURRENCIES = os.environ.get("FX_CURRENCIES", "USD,EUR").split(",")
START_DATE = os.environ.get("FX_START_DATE", "2025-01-01")

BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"

def connect():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fx_rates (
                    date DATE NOT NULL,
                    currency TEXT NOT NULL,
                    rate DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (date, currency)
                );
            """)
        conn.commit()

def get_latest_date():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM fx_rates;")
            row = cur.fetchone()
            return row[0].isoformat() if row[0] else START_DATE

def fetch_currency_data(currency, start_date, end_date):
    url = BASE_URL.format(currency=currency)
    params = {"startPeriod": start_date, "endPeriod": end_date, "format": "jsondata"}
    headers = {"Accept": "application/vnd.sdmx.data+json;version=1.0.0"}

    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    series = data["dataSets"][0]["series"]
    series_key = next(iter(series))
    obs = series[series_key]["observations"]
    dates = data["structure"]["dimensions"]["observation"][0]["values"]

    records = []
    for i, d in enumerate(dates):
        date_str = d["id"]
        rate = obs.get(str(i), [None])[0]
        if rate is not None:
            records.append((date_str, currency, rate))
    return records

def insert_records(records):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO fx_rates (date, currency, rate) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
                records
            )
        conn.commit()

def main():
    init_db()
    latest = get_latest_date()
    start_date = (datetime.strptime(latest, "%Y-%m-%d") + timedelta(days=1)).date().isoformat()
    end_date = date.today().isoformat()

    if start_date > end_date:
        print("Database already up to date.")
        return

    all_records = []
    for currency in CURRENCIES:
        print(f"Fetching {currency}...")
        recs = fetch_currency_data(currency, start_date, end_date)
        all_records.extend(recs)

    insert_records(all_records)
    print(f"Inserted {len(all_records)} records.")

if __name__ == "__main__":
    main()
