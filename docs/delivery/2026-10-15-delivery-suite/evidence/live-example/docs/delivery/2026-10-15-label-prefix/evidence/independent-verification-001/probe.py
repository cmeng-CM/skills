from label import label
import inspect,json
cases=[('default',lambda: label(' x '),'x'),('space-prefix',lambda: label(' x ',prefix=' p '),' p x'),('empty-body',lambda: label('   ',prefix='p'),'p'),('unicode',lambda: label(' x ',prefix='中文'),'中文x')]
results=[]
for name,call,expected in cases:
 actual=call();results.append({'case':name,'expected':expected,'actual':actual,'passed':actual==expected})
try:
 label('x','p'); positional=False
except TypeError:
 positional=True
results.append({'case':'keyword-only','passed':positional})
# Broader literal behavior evidence for whitespace, punctuation, combining text.
for body in ['', ' a ', '\n中文\t', ' é ', '  .  ']:
 for prefix in ['', ' ', '\tX\n', '中文', ':']:
  actual=label(body,prefix=prefix)
  if actual!=prefix+body.strip():raise AssertionError((body,prefix,actual))
print(json.dumps({'signature':str(inspect.signature(label)),'criteria':results,'additional_cases':25},ensure_ascii=False,indent=2))
assert all(r['passed'] for r in results)
