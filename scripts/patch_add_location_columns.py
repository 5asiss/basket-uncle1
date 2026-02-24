import os
import sqlite3


def main() -> None:
    base = os.path.abspath(os.path.join("instance", "direct_trade_mall.db"))
    if not os.path.exists(base):
        print("DB not found:", base)
        return
    print("Using DB:", base)
    conn = sqlite3.connect(base)
    cur = conn.cursor()

    def ensure_column(table: str, column: str, coltype: str) -> None:
        cur.execute(f"PRAGMA table_info('{table}')")
        cols = [r[1] for r in cur.fetchall()]
        if column in cols:
            print(f"{table}.{column} already exists")
            return
        sql = f"ALTER TABLE '{table}' ADD COLUMN {column} {coltype}"
        print("Executing:", sql)
        cur.execute(sql)
        conn.commit()

    ensure_column("order", "delivery_lat", "REAL")
    ensure_column("order", "delivery_lng", "REAL")
    ensure_column("user", "address_apt_name", "VARCHAR(100)")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()

