"""Overture address points for Texas -> data/tx/addresses_tx.parquet

Places official records that have no coordinates (TABC licenses, El Paso's inspection list, some Austin rows) and researched addresses
the map listings lack. Adapted from co-eats/pipeline/fetch_extras.py.
"""
import os, time
import duckdb

RELEASE = "2026-09-23.1"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "tx")
t = time.time()
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
addr = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=addresses/type=address/*.parquet"
con.execute(f"""COPY (SELECT number, street, unit, postcode, postal_city, address_levels[1].value AS state, address_levels[-1].value AS muni,
  ST_Y(geometry) lat, ST_X(geometry) lon FROM read_parquet('{addr}', hive_partitioning=1)
  WHERE country = 'US' AND bbox.xmin BETWEEN -106.7 AND -93.5 AND bbox.ymin BETWEEN 25.83 AND 36.51)
  TO '{OUT}/addresses_tx.parquet' (FORMAT PARQUET)""")
print(con.execute(f"select count(*), count(*) filter (where state='TX') from '{OUT}/addresses_tx.parquet'").fetchall(), round(time.time() - t), "s")
