import json
c=json.load(open('current_offers.json'))
h=json.load(open('monthly_price_history.json'))
a={x.get('normalized_product_key') for x in c.get('offers',[]) if x.get('normalized_product_key')}
b={x.get('normalized_product_key') for x in h.get('records',[]) if x.get('normalized_product_key')}
if len(a&b)/max(1,len(a))<0.30: raise SystemExit('history overlap below 30%')
