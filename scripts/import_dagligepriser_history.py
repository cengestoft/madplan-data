#!/usr/bin/env python3
"""Download Danish source snapshot; export dated history, never active offers."""
import argparse, datetime, json, pathlib, urllib.request

URL = 'https://dagligepriser.dk/data/latest-canonical.json'
STORES = {'bilkatogo':'Bilka','fotex':'føtex','meny':'MENY','minkobmand':'Min Købmand','nemlig':'Nemlig.com','netto':'Netto','rema1000':'REMA 1000','spar':'SPAR'}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-file', help='Previously downloaded JSON snapshot')
    p.add_argument('--output', default='data/history/dagligepriser')
    a = p.parse_args()
    out = pathlib.Path(a.output); out.mkdir(parents=True, exist_ok=True)
    raw = pathlib.Path(a.source_file).read_bytes() if a.source_file else urllib.request.urlopen(URL, timeout=180).read()
    products = json.loads(raw)
    if not isinstance(products, list): raise ValueError('Expected product list')
    counts = {}; files = {}; skipped = 0; dates = []
    try:
        for product in products:
            store = product.get('store')
            if store not in STORES: skipped += 1; continue
            if store not in files: files[store] = (out / (store + '.ndjson')).open('w', encoding='utf-8')
            seen = set()
            for h in product.get('priceHistory', []):
                date = h.get('date'); price = h.get('price')
                try: datetime.date.fromisoformat(date)
                except (TypeError, ValueError): skipped += 1; continue
                if not isinstance(price, (int,float)) or isinstance(price,bool) or price <= 0: skipped += 1; continue
                # Older entries may lack historical size: never substitute today's size.
                quantity = h.get('quantity'); unit = h.get('unit')
                key = (date,price,str(quantity),str(unit))
                if key in seen: continue
                seen.add(key)
                row = dict(source='dagligepriser.dk',source_url=URL,source_product_id=str(product.get('id')),store=STORES[store],store_location=None,name=product.get('name'),observation_date=date,price_dkk=price,package_amount=quantity,package_unit=unit,package_size_verified=quantity is not None and unit is not None,source_current_unavailable=product.get('unavailable'),food_relevance=None,eligible_for_current_offers=False)
                files[store].write(json.dumps(row, ensure_ascii=False,separators=(',',':'))+'\n')
                counts[store] = counts.get(store,0)+1; dates.append(date)
    finally:
        for f in files.values(): f.close()
    manifest = dict(source_url=URL,downloaded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_products=len(products),exported_history_rows=sum(counts.values()),rows_per_store=counts,earliest_date=min(dates) if dates else None,latest_date=max(dates) if dates else None,skipped=skipped,note='All source categories retained in staging. Classify food before app import. History entries may record price changes rather than daily samples. Unknown historical quantity stays null. Do not upload this directory to Git by default.')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))

if __name__ == '__main__': main()
