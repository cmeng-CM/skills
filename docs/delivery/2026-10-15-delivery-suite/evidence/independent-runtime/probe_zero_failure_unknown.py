"""Isolated API probe: all actors/approval texts are synthetic fixture declarations."""
import importlib.util, pathlib, tempfile, json, sys
s=importlib.util.spec_from_file_location('delivery',pathlib.Path('delivery-orchestrate/scripts/delivery.py').resolve());m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p=pathlib.Path(tempfile.mkdtemp(prefix='delivery-zero-unknown-',dir='/private/tmp'))
(p/'output.py').write_text('print("BROKEN")\n')
(p/'plan.md').write_text('Synthetic criteria: A1 must print READY. A2 requires human operation, none performed.\n')
(p/'auth.md').write_text('Synthetic fixture approval; not a real human authorization.\n')
(p/'report.md').write_text('Synthetic API fixture setup; no real product acceptance.\n')
a=lambda x:{'id':x,'context':x}
e=m.Engine(p/'work');e.init(p,'synthetic zero exit probe','init')
e.configure(dict(schema_version=1,contract_version=1,actor=a('coordinator'),skill_revision='fixture',plan={'path':'plan.md','quote':'A1 must print READY.'},authorization={'path':'auth.md','quote':'Synthetic fixture approval','scope':'isolated API test'},mapping_reason='test-only known criteria',tasks=[{'id':'T','scope':['output.py'],'depends':[]}],reviews=[{'id':'R','tasks':['T'],'whole':True}],acceptance=[{'id':'A1','tasks':['T'],'required':True,'method':'command','command':[sys.executable,'-B','output.py'],'criteria':'stdout equals READY','environment':'isolated local','waivable':True},{'id':'A2','tasks':['T'],'required':True,'method':'manual','criteria':'real human operation record','environment':'unavailable human session','waivable':True}]),'configure')
def record(kind,target,result,who,**extra):
 return dict(schema_version=1,contract_version=1,skill_revision='fixture',kind=kind,target=target,actor=a(who),report={'path':'report.md'},result=result,summary='synthetic fixture state; not real approval',evidence=[{'path':'plan.md'}],**extra)
e.record(record('implementation','T','passed','author'),'implementation')
e.record(record('review','R',{'spec':'passed','quality':'passed'},'reviewer'),'review')
run=e.run('A1',a('verifier'),10,'run-A1')
stdout=(e.runtime/'objects'/run['payload']['stdout']['object_hash']).read_text()
after_run=e.inspect('status')
e.record(record('verification','A1','failed','verifier',run_operation='run-A1',issues=[{'id':'V-F1','summary':'Expected READY; observed BROKEN with exit 0','severity':'major','blocking':True,'tasks':['T']}]),'verify-failed')
e.record(record('verification','A2','unknown','verifier'),'verify-unknown')
state=e.inspect('status')
exception=lambda target,issues:{'acceptance':target,'scope':'test-only','risk':'test-only','authorization':{'path':'auth.md','quote':'Synthetic fixture approval','by':'fixture human label','role':'human'},'issues':issues}
try:
 e.close(dict(schema_version=1,contract_version=1,actor=a('coordinator'),mode='limited',summary='test-only attempt to exempt unknown',report={'path':'report.md'},exceptions=[exception('A1',['V-F1']),exception('A2',[])]),'close')
 reject='UNEXPECTED ACCEPTANCE'
except m.DeliveryError as exc:reject=str(exc)
print(json.dumps({'fixture_project':str(p),'warning':'synthetic actor and authorization fixtures, not real independent approval','exit_code':run['payload']['exit_code'],'stdout':stdout,'state_after_exit_zero':after_run,'state_after_semantic_records':state,'limited_unknown_rejection':reject},ensure_ascii=False,indent=2))
