import json, sys
from decimal import Decimal
try:
 rows=json.load(open(sys.argv[1])); assert isinstance(rows,list)
 out={}
 for r in rows:
  assert r['kind'] in ('income','expense')
  value=Decimal(r['amount']); assert value.is_finite() and value>0
  d=out.setdefault(r['currency'],dict(income=Decimal('0'),expense=Decimal('0')))
  d[r['kind']]+=value
 print(json.dumps({c:dict(income=format(d['income'],'.2f'),expense=format(d['expense'],'.2f'),net=format(d['income']-d['expense'],'.2f')) for c,d in sorted(out.items())}))
except Exception as error:
 print(str(error),file=sys.stderr);sys.exit(2)
