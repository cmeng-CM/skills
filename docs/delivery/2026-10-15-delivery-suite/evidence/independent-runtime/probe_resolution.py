import importlib.util,tempfile,pathlib,json
s=importlib.util.spec_from_file_location('delivery',pathlib.Path('delivery-orchestrate/scripts/delivery.py').resolve());m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
p=pathlib.Path(tempfile.mkdtemp(prefix='delivery-resolution-',dir='/private/tmp'))
(p/'product.txt').write_text('product')
(p/'plan.md').write_text('approved plan')
(p/'auth.md').write_text('authorized')
(p/'report.md').write_text('actual review report')
e=m.Engine(p/'work');e.init(p,'probe','init')
actor=lambda a:{'id':a,'context':a}
c={'schema_version':1,'contract_version':1,'actor':actor('orchestrator'),'skill_revision':'test','plan':{'path':'plan.md','quote':'approved plan'},'authorization':{'path':'auth.md','quote':'authorized','scope':'all'},'mapping_reason':'probe','tasks':[{'id':'T1','scope':['product.txt'],'depends':[]}],'reviews':[{'id':'R1','tasks':['T1'],'whole':True}],'acceptance':[{'id':'AC1','tasks':['T1'],'required':True,'method':'inspection','criteria':'product exists','environment':'local'}]}
e.configure(c,'configure')
def rec(kind,target,result,a,**extra):
 return dict(schema_version=1,contract_version=1,skill_revision='test',kind=kind,target=target,actor=actor(a),report={'path':'report.md'},result=result,summary='probe result',evidence=[{'path':'product.txt'}],**extra)
e.record(rec('implementation','T1','passed','implementer'),'impl')
e.record(rec('review','R1',{'spec':'failed','quality':'passed'},'reviewer',issues=[{'id':'F1','summary':'defect','severity':'major','blocking':True,'tasks':['T1']}]),'review-fail')
e.record(rec('review','R1',{'spec':'passed','quality':'passed'},'reviewer',resolutions=[{'id':'F1','reason':'checked fix','evidence':[{'path':'product.txt'}]}],supersedes='review-fail',reason='fixed'),'review-fixed')
before=e.inspect('status')
e.record(rec('review','R1',{'spec':'passed','quality':'passed'},'reviewer'),'review-again')
after=e.inspect('status')
print(json.dumps({'project':str(p),'before':before,'after':after},ensure_ascii=False,indent=2))
