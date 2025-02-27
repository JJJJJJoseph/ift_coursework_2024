import sqlite3
import yaml
import os

config_path = os.getenv("CONF_PATH", "a_pipeline/config/conf.yaml")  # Default path for Docker
with open(config_path, "r") as file:
    config = yaml.safe_load(file)

if os.getenv("DOCKER_ENV"):
    DB_PATH = config["databasedocker"]["sqlite_path"]
else:
    DB_PATH = config["databaselocal"]["sqlite_path"]


def fetch_companies():
    """Fetch company data from SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    print("Using database:", DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT security, symbol, gics_sector, gics_industry, country, region 
        FROM equity_static
    """)

    companies = [
        {
            "company_name": row[0],
            "symbol": row[1],
            "gics_sector": row[2],
            "gics_industry": row[3],
            "country": row[4],
            "region": row[5]
        }
        for row in cursor.fetchall()
    ]

    conn.close()
    return companies

