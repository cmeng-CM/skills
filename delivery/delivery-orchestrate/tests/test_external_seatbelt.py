"""External adapter unit tests; fake local JSON-RPC server is not an agent run."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('external_seatbelt',Path(__file__).parents[1]/'scripts/external_seatbelt.py')
S=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(S)

SERVER='''#!PYTHON
import json,sys,time,os,sqlite3
from pathlib import Path
for option in sys.argv:
 if option.startswith('sqlite_home='):
  state=Path(json.loads(option.split('=',1)[1]));state.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(state/'state_5.sqlite') as db:db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)')
for line in sys.stdin:
 message=json.loads(line);method=message.get('method');identity=message.get('id')
 if method=='initialize': result={'userAgent':'fake-unit-server'}
 elif method=='mcpServerStatus/list':result={'data':[]}
 elif method=='thread/start':result={'thread':{'id':'unit-thread'},'model':'frozen-default'}
 elif method=='turn/start':
  print(json.dumps({'id':identity,'result':{'turn':{'id':'unit-turn','status':'inProgress'}}}),flush=True)
  BEHAVIOR
  continue
 elif method=='initialized':continue
 else:continue
 print(json.dumps({'id':identity,'result':result}),flush=True)
'''
COMPLETE='''print(json.dumps({'method':'item/completed','params':{'threadId':'unit-thread','turnId':'unit-turn','item':{'type':'agentMessage','text':'Reviewed real artifacts','phase':'final_answer'}}}),flush=True)
  print(json.dumps({'method':'thread/tokenUsage/updated','params':{'threadId':'unit-thread','turnId':'unit-turn','tokenUsage':{'total':{'inputTokens':1,'outputTokens':2}}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':'unit-thread','turn':{'id':'unit-turn','status':'completed'}}}),flush=True)'''


class ExternalSeatbeltTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.workspace=self.root/'fixture';self.workspace.mkdir()
  self.private=self.root/'private';self.private.mkdir()
  self.state=self.root/'state';self.state.mkdir()
  (self.state/'installation_id').write_text('12345678-1234-4234-8234-123456789abc');(self.state/'installation_id').chmod(0o644)
  (self.state/'auth.json').write_text('fake test credential only')
  (self.state/'config.toml').write_text('model="test"')
  self.run=self.root/'run';self.run.mkdir()
 def tearDown(self):self.temp.cleanup()
 def fake_server(self,behavior,before_response=False,mcp_inventory=None,skill_catalog=None):
  script=SERVER.replace('PYTHON',sys.executable).replace('BEHAVIOR',behavior)
  if mcp_inventory is not None:
   script=script.replace("result={'data':[]}", 'result='+repr(mcp_inventory))
  if skill_catalog is not None:
   script=script.replace(" elif method=='thread/start':", " elif method=='skills/list':result="+repr(skill_catalog)+"\n elif method=='thread/start':")
  if before_response:
   acknowledgement="  print(json.dumps({'id':identity,'result':{'turn':{'id':'unit-turn','status':'inProgress'}}}),flush=True)"
   script=script.replace(acknowledgement+'\n  '+behavior,'  '+behavior+'\n'+acknowledgement)
  server=self.root/'unit-server';server.write_text(script);server.chmod(0o755);return str(server)
 def test_profile_grants_no_auth_config_or_home_directory_write(self):
  text,policy=S.profile_text(self.workspace,[self.private],self.state)
  self.assertIn('(deny file-write* (require-all',text)
  self.assertNotIn('(subpath '+json.dumps(str(self.state))+')',text)
  self.assertNotIn('auth.json',text);self.assertNotIn('config.toml',text)
  self.assertEqual([str(self.state.resolve()/'installation_id')],policy['exact_cli_state_write_exceptions'])
  self.assertIn('(deny file-read* (subpath '+json.dumps(str(self.private.resolve()))+'))',text)
 def test_history_roots_and_all_sqlite_versions_denied_without_home_blanket(self):
  text,policy=S.profile_text(self.workspace,[self.private],self.state)
  rules=policy['historical_read_denials']
  for name in ('sessions','archived_sessions','memories','memories_v2','sqlite'):
   self.assertIn({'kind':'subpath','value':str(self.state.resolve()/name)},rules)
  import re
  pattern=next(r['value'] for r in rules if r['kind']=='regex')
  for name in ('state_5.sqlite','state_99.sqlite-wal','logs_2.sqlite-shm','thread_history_1.sqlite','memories_v2_1.sqlite','.codex-global-state.json','..codex-global-state.json.tmp-x','history.jsonl','session_index.jsonl'):
   self.assertTrue(re.fullmatch(pattern,str(self.state.resolve()/name)),name)
  for name in ('auth.json','config.toml','installation_id','models_cache.json'):
   self.assertIsNone(re.fullmatch(pattern,str(self.state/name)))
 def test_prior_fixture_state_denied_except_current_run_child(self):
  current=S.run_state_home(self.workspace,self.run)
  text,policy=S.profile_text(self.workspace,[self.private],self.state,runtime_state=current)
  self.assertEqual(str(self.workspace.resolve()/'.evaluation-state'),policy['prior_fixture_state_denied'])
  self.assertEqual(str(current),policy['current_run_state_exception'])
  self.assertIn('(deny file-read* (require-all ',text)
  self.assertIn('(deny file-read-data (literal '+json.dumps(str(self.workspace.resolve()/'.evaluation-state'))+'))',text)
  self.assertIn('(deny file-write* (require-all (subpath ',text)
  with self.assertRaises(ValueError):S.profile_text(self.workspace,[self.private],self.state,runtime_state=self.workspace/'other')
 def test_current_state_cannot_be_reused_or_symlinked(self):
  self.assertEqual('initialized',S.execute(self.fake_server(COMPLETE),[],self.workspace,'',{},self.run,5,startup_only=True)['status'])
  with self.assertRaises(FileExistsError):S.execute(self.fake_server(COMPLETE),[],self.workspace,'',{},self.run,5,startup_only=True)
  state=self.workspace/'.evaluation-state';current=S.run_state_home(self.workspace,self.run)
  import shutil
  shutil.rmtree(state);state.symlink_to(self.private)
  with self.assertRaises(ValueError):S.run_state_home(self.workspace,self.run)
 def test_state_audit_fails_closed_missing_schema_and_poisoned_database(self):
  import sqlite3
  with self.assertRaises(RuntimeError):S.inspect_state_database(self.workspace)
  p=self.workspace/'state_5.sqlite'
  with sqlite3.connect(p) as db:db.execute('CREATE TABLE irrelevant(id)')
  with self.assertRaises(RuntimeError):S.inspect_state_database(self.workspace)
  with sqlite3.connect(p) as db:
   db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)');db.execute("INSERT INTO threads(id) VALUES('private-history')")
  self.assertFalse(S.inspect_state_database(self.workspace)['passed'])
 def test_unknown_threads_schema_and_empty_view_are_not_empty_history_proof(self):
  import sqlite3
  schemas=[
   'CREATE TABLE threads(other TEXT)',
   'CREATE TABLE private_history(id TEXT); INSERT INTO private_history VALUES(1); CREATE VIEW threads AS SELECT * FROM private_history WHERE 0',
   'CREATE TABLE threads(id TEXT,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)',
   'CREATE TABLE threads(id BLOB PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)',
  ]
  for i,sql in enumerate(schemas):
   with self.subTest(sql=sql):
    directory=self.workspace/str(i);directory.mkdir()
    with sqlite3.connect(directory/'state_5.sqlite') as db:db.executescript(sql)
    with self.assertRaises(RuntimeError):S.inspect_state_database(directory)
 def test_unknown_startup_schema_is_recorded_and_never_starts_model(self):
  server=self.fake_server(COMPLETE);path=Path(server)
  original="db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)')"
  path.write_text(path.read_text().replace(original,"db.execute('CREATE TABLE threads(other TEXT)')"))
  value=S.execute(server,[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  audit=json.loads((self.run/'startup-state-audit.json').read_text())
  self.assertFalse(audit['passed']);self.assertIn('schema',audit['reason'])
  self.assertFalse(any(json.loads(v).get('method')=='turn/start' for v in (self.run/'requests.jsonl').read_text().splitlines()))
 def test_sql_read_error_is_saved_in_startup_audit_and_blocks_model(self):
  server=self.fake_server(COMPLETE);path=Path(server)
  create="with sqlite3.connect(state/'state_5.sqlite') as db:db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)')"
  path.write_text(path.read_text().replace(create,"(state/'state_5.sqlite').write_bytes(b'not a SQLite database')"))
  value=S.execute(server,[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  audit=json.loads((self.run/'startup-state-audit.json').read_text())
  self.assertFalse(audit['passed']);self.assertEqual('DatabaseError',audit['error_type'])
  self.assertFalse(any(json.loads(v).get('method')=='turn/start' for v in (self.run/'requests.jsonl').read_text().splitlines()))
 def test_invalid_count_return_shapes_fail_closed(self):
  import sqlite3
  with sqlite3.connect(self.workspace/'state_5.sqlite') as db:
   db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)')
  connect=sqlite3.connect
  class Proxy:
   def __init__(self,*args,**kwargs):self.db=connect(*args,**kwargs)
   def __enter__(self):return self
   def __exit__(self,*args):self.db.close()
   def execute(self,sql):
    if sql.startswith('SELECT COUNT'):
     class Cursor:
      def fetchone(inner):return bad
     return Cursor()
    return self.db.execute(sql)
  for bad in (None,(),('0',),(False,),(0.0,),(-1,),(0,1)):
   with self.subTest(result=bad),patch.object(S.sqlite3,'connect',Proxy):
    with self.assertRaises(RuntimeError):S.inspect_state_database(self.workspace)
 def test_history_symlink_targets_are_denied_and_fixture_overlap_rejected(self):
  target=self.root/'historical-source';target.mkdir();(self.state/'sessions').symlink_to(target)
  _,policy=S.profile_text(self.workspace,[self.private],self.state)
  self.assertIn({'kind':'subpath','value':str(target.resolve())},policy['historical_read_denials'])
  (self.state/'sessions').unlink();(self.state/'sessions').symlink_to(self.workspace)
  with self.assertRaises(ValueError):S.profile_text(self.workspace,[self.private],self.state)
 def test_existing_identity_required_and_protected_changes_detected(self):
  S.validate_installation_id(self.state)
  isolation={'state_home':str(self.state),'protected_files_before':S.protected_metadata(self.state)}
  self.assertTrue(S.verify_protection(isolation)['unchanged'])
  (self.state/'installation_id').write_text('modified identity')
  self.assertFalse(S.verify_protection(isolation)['unchanged'])
  with self.assertRaises(ValueError):S.validate_installation_id(self.state)
 def test_profile_rejects_fixture_inside_denied_root(self):
  with self.assertRaises(ValueError):S.profile_text(self.workspace,[self.root],self.state)
 def test_three_canaries_must_all_pass(self):
  def fake_probe(argv,**kwargs):
   if argv[3]=='/bin/cat':return subprocess.CompletedProcess(argv,1,'','cat: Operation not permitted')
   target=Path(argv[-1])
   if argv[3]=='/usr/bin/python3':
    allowed=target.name=='installation_id' or target.name.startswith('.write-canary-')
    return subprocess.CompletedProcess(argv,0 if allowed else 1,'','' if allowed else 'Operation not permitted')
   if target.parent==self.workspace:
    target.write_text('boundary-probe');return subprocess.CompletedProcess(argv,0,'','')
   return subprocess.CompletedProcess(argv,1,'','sh: Operation not permitted')
  with patch.object(S.subprocess,'run',side_effect=fake_probe):
   wrapper,proof=S.probe_boundary(self.workspace,[self.private],self.state,self.run,sandbox_cli='/sandbox-exec')
  self.assertTrue(proof['passed']);self.assertEqual('/sandbox-exec',wrapper[0])
  self.assertEqual([],list(self.private.iterdir()))
 def test_any_accessible_old_fixture_or_global_history_fails_canary_gate(self):
  old=self.workspace/'.evaluation-state';old.mkdir();(old/'state_5.sqlite').write_text('synthetic')
  (self.state/'history.jsonl').write_text('synthetic')
  for permitted in ('state_5.sqlite','history.jsonl'):
   def fake_probe(argv,**kwargs):
    target=Path(argv[-1])
    if argv[3]=='/bin/cat':return subprocess.CompletedProcess(argv,1,'','Operation not permitted')
    if argv[3]=='/usr/bin/python3':
     allowed=target.name in ('installation_id',permitted) or target.name.startswith('.write-canary-')
     return subprocess.CompletedProcess(argv,0 if allowed else 1,'','' if allowed else 'Operation not permitted')
    if target.parent==self.workspace:
     target.write_text('boundary-probe');return subprocess.CompletedProcess(argv,0,'','')
    return subprocess.CompletedProcess(argv,1,'','Operation not permitted')
   with self.subTest(permitted=permitted),patch.object(S.subprocess,'run',side_effect=fake_probe):
    with self.assertRaises(ValueError):S.probe_boundary(self.workspace,[self.private],self.state,self.run,sandbox_cli='/sandbox-exec')
    self.assertFalse(json.loads((self.run/'isolation.json').read_text())['passed'])
 def test_future_sibling_fixture_pattern_is_parent_scoped_and_current_excepted(self):
  import re
  current=self.root/'delivery-eval-work-current';current.mkdir()
  text,policy=S.profile_text(current,[self.private],self.state)
  future=self.root/'delivery-eval-work-created-later'
  self.assertFalse(future.exists())
  patterns=policy['other_fixture_patterns']
  self.assertTrue(any(re.match(p,str(future.resolve()/'README.md')) for p in patterns))
  self.assertFalse(any(re.match(p,str((self.root/'unrelated-project/README.md').resolve())) for p in patterns))
  self.assertIn('(require-not (subpath '+json.dumps(str(current.resolve()))+'))',text)
  expected=[str(self.root.resolve())]
  if expected[0].startswith(('/private/var/','/private/tmp/')):expected.append(expected[0].removeprefix('/private'))
  self.assertEqual(S.path_aliases(self.root),expected)
 def test_prior_nonstandard_state_sources_are_only_evaluator_metadata_paths(self):
  behavior=self.root/'goal/evidence/behavior'
  output=behavior/'current/runs/001';output.mkdir(parents=True)
  old=behavior/'old';old.mkdir()
  old_workspace=self.root/'legacy-nonstandard'
  (old/'evaluation.json').write_text(json.dumps({'workspace':str(old_workspace)}))
  (old/'result.json').write_text(json.dumps({'workspace':str(self.workspace)}))
  hidden=old/'runs/001/artifacts';hidden.mkdir(parents=True)
  (hidden/'result.json').write_text(json.dumps({'workspace':'/not-evaluator-metadata'}))
  records=S.prior_state_roots(self.workspace,output)
  self.assertEqual(1,len(records));self.assertEqual(str(old_workspace.resolve()/'.evaluation-state'),records[0]['denied_state'])
  _,policy=S.profile_text(self.workspace,[self.private],self.state,known_states=[records[0]['denied_state']])
  self.assertEqual([records[0]['denied_state']],policy['known_prior_state_roots'])
 def test_outside_write_success_invalidates_boundary(self):
  def wrong_probe(argv,**kwargs):
   if argv[3]=='/bin/cat':return subprocess.CompletedProcess(argv,1,'','Operation not permitted')
   Path(argv[-1]).write_text('boundary-probe');return subprocess.CompletedProcess(argv,0,'','')
  with patch.object(S.subprocess,'run',side_effect=wrong_probe):
   with self.assertRaises(ValueError):S.probe_boundary(self.workspace,[self.private],self.state,self.run,sandbox_cli='/sandbox-exec')
 def test_stdin_protocol_complete_is_execution_only(self):
  value=S.execute(self.fake_server(COMPLETE),[],self.workspace,'public request',{'model':'frozen-default','model_reasoning_effort':'xhigh'},self.run,10)
  self.assertEqual('executed',value['status'])
  requests=[json.loads(line) for line in (self.run/'requests.jsonl').read_text().splitlines()]
  turn=next(v['params'] for v in requests if v.get('method')=='turn/start')
  self.assertEqual({'type':'externalSandbox','networkAccess':'enabled'},turn['sandboxPolicy'])
  self.assertEqual('never',turn['approvalPolicy']);self.assertEqual('xhigh',turn['effort'])
  self.assertIn('turn/completed',(self.run/'appserver.jsonl').read_text())
  self.assertIn('turn.completed',(self.run/'events.jsonl').read_text())
  self.assertEqual('Reviewed real artifacts',(self.run/'last-message.txt').read_text())
  self.assertEqual(['TMPDIR','TMPPREFIX'],value['environment_keys_changed'])
  self.assertNotIn('--dangerously',json.dumps(value['argv']))
  self.assertIn('--strict-config',value['argv'])
  self.assertTrue(any(v.startswith('sqlite_home=') for v in value['argv']))
  self.assertTrue(value['startup_state_audit']['passed'])
  self.assertEqual(0,value['startup_state_audit']['thread_row_count'])
  self.assertEqual(1,len(value['runtime_state']['user_home_write_exceptions']))
  self.assertTrue(value['runtime_state']['user_home_write_exceptions'][0].endswith('/installation_id'))
 def test_startup_only_never_sends_model_turn(self):
  value=S.execute(self.fake_server(COMPLETE),[],self.workspace,'not sent',{},self.run,5,startup_only=True)
  self.assertEqual('initialized',value['status']);self.assertFalse(value['model_turn_started'])
  requests=[json.loads(v) for v in (self.run/'requests.jsonl').read_text().splitlines()]
  self.assertFalse(any(v.get('method')=='turn/start' for v in requests))
 def natural_catalog(self):
  package=self.workspace/'.agents/skills/delivery-implement';package.mkdir(parents=True)
  entry=package/'SKILL.md';entry.write_text('frozen professional body')
  policy=package/'agents/openai.yaml';policy.parent.mkdir();policy.write_text('policy:\n  allow_implicit_invocation: true\n')
  import hashlib
  expected={'delivery-implement':{'path':str(entry.resolve()),'skill_sha256':hashlib.sha256(entry.read_bytes()).hexdigest(),'policy_path':str(policy.resolve()),'policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest(),'implicit_policy':'true'}}
  return expected,{'data':[{'cwd':str(self.workspace.resolve()),'skills':[{'name':'delivery-implement','description':'Professional purpose','scope':'repo','path':str(entry.resolve()),'enabled':True}],'errors':[]}]}
 def test_natural_catalog_audited_before_model_and_never_writes_user_config(self):
  expected,catalog=self.natural_catalog()
  value=S.execute(self.fake_server(COMPLETE,skill_catalog=catalog),[],self.workspace,'ordinary public request',{},self.run,5,expected_skills=expected)
  self.assertEqual('executed',value['status']);self.assertTrue(value['skill_catalog_audit']['passed'])
  requests=[json.loads(line) for line in (self.run/'requests.jsonl').read_text().splitlines()]
  methods=[request.get('method') for request in requests]
  self.assertLess(methods.index('skills/list'),methods.index('turn/start'))
  self.assertNotIn('skills/config/write',methods)
  turn=next(request['params'] for request in requests if request.get('method')=='turn/start')
  self.assertEqual([{'type':'text','text':'ordinary public request','text_elements':[]}],turn['input'])
  override=next(arg for arg in value['argv'] if arg.startswith('skills.config='))
  self.assertIn('name="delivery-implement", enabled=false',override)
  self.assertIn('skills.include_instructions=true',value['argv'])
  self.assertEqual(catalog,json.loads((self.run/'skill-catalog.json').read_text()))
 def test_missing_frozen_catalog_blocks_turn_and_preserves_audit(self):
  expected,catalog=self.natural_catalog();catalog['data'][0]['skills']=[]
  value=S.execute(self.fake_server(COMPLETE,skill_catalog=catalog),[],self.workspace,'ordinary request',{},self.run,5,expected_skills=expected)
  self.assertEqual('execution-failed',value['status']);self.assertFalse(value['skill_catalog_audit']['passed'])
  requests=[json.loads(line) for line in (self.run/'requests.jsonl').read_text().splitlines()]
  self.assertFalse(any(item.get('method')=='turn/start' for item in requests))
  self.assertTrue((self.run/'skill-catalog-audit.json').is_file())
 def test_natural_startup_only_includes_catalog_without_model_turn(self):
  expected,catalog=self.natural_catalog()
  value=S.execute(self.fake_server(COMPLETE,skill_catalog=catalog),[],self.workspace,'never sent',{},self.run,5,startup_only=True,expected_skills=expected)
  self.assertEqual('initialized',value['status']);self.assertTrue(value['skill_catalog_audit']['passed'])
  methods=[json.loads(line).get('method') for line in (self.run/'requests.jsonl').read_text().splitlines()]
  self.assertIn('skills/list',methods);self.assertNotIn('turn/start',methods)
 def test_normal_zsh_temp_environment_reaches_child_without_replacing_user_homes(self):
  home_before=os.environ.get('HOME');codex_before=os.environ.get('CODEX_HOME')
  behavior=COMPLETE.replace("'Reviewed real artifacts'", "json.dumps({'TMPDIR':os.environ.get('TMPDIR'),'TMPPREFIX':os.environ.get('TMPPREFIX'),'HOME':os.environ.get('HOME'),'CODEX_HOME':os.environ.get('CODEX_HOME')})")
  value=S.execute(self.fake_server(behavior),[],self.workspace,'public request',{},self.run,5)
  actual=json.loads((self.run/'last-message.txt').read_text())
  self.assertEqual(str(self.workspace/'.evaluation-tmp'),actual['TMPDIR'])
  self.assertEqual(str(self.workspace/'.evaluation-tmp/zsh'),actual['TMPPREFIX'])
  self.assertEqual(home_before,actual['HOME']);self.assertEqual(codex_before,actual['CODEX_HOME'])
  self.assertEqual(home_before,os.environ.get('HOME'));self.assertEqual(codex_before,os.environ.get('CODEX_HOME'))
  self.assertEqual({'TMPDIR':actual['TMPDIR'],'TMPPREFIX':actual['TMPPREFIX']},value['temporary_environment'])
 def test_stable_external_capability_features_explicitly_disabled(self):
  value=S.execute(self.fake_server(COMPLETE),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual(['apps','plugins','remote_plugin','memories','shell_snapshot'],value['disabled_features'])
  for feature in value['disabled_features']:
   self.assertIn(['--disable',feature],[value['argv'][i:i+2] for i in range(len(value['argv'])-1)])
  self.assertNotIn('skip_host_skill_discovery',value['argv'])
 def test_runtime_injected_mcp_tools_still_block_model_turn(self):
  inventory={'data':[{'name':'codex_apps','authStatus':'unknown','tools':{'unexpectedTool':{'name':'unexpectedTool'}},'resources':[],'resourceTemplates':[]}]}
  value=S.execute(self.fake_server(COMPLETE,mcp_inventory=inventory),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  requests=[json.loads(v) for v in (self.run/'requests.jsonl').read_text().splitlines()]
  self.assertFalse(any(v.get('method')=='turn/start' for v in requests))
  self.assertEqual(inventory,value['mcp_runtime_inventory'])
  self.assertIn('external capabilities',value['reason'])
 def test_historical_rows_in_real_startup_db_block_model_turn(self):
  server=self.fake_server(COMPLETE)
  path=Path(server);text=path.read_text();text=text.replace("first_user_message TEXT)')", "first_user_message TEXT)');db.execute(\"INSERT INTO threads(id) VALUES('historical')\")")
  path.write_text(text)
  value=S.execute(server,[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  self.assertFalse(value['startup_state_audit']['passed'])
  self.assertTrue((self.run/'startup-state-audit.json').exists())
  self.assertFalse(any(json.loads(v).get('method')=='turn/start' for v in (self.run/'requests.jsonl').read_text().splitlines()))
 def test_missing_database_cannot_be_interpreted_as_no_history(self):
  server=self.fake_server(COMPLETE)
  path=Path(server);path.write_text(path.read_text().replace("db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,rollout_path TEXT,created_at INTEGER,updated_at INTEGER,source TEXT,model_provider TEXT,cwd TEXT,title TEXT,first_user_message TEXT)')", 'pass'))
  value=S.execute(server,[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  self.assertFalse(any(json.loads(v).get('method')=='turn/start' for v in (self.run/'requests.jsonl').read_text().splitlines()))
 def test_well_formed_empty_inventory_and_server_can_proceed(self):
  empty_server={'name':'disabled-server','authStatus':'unsupported','tools':{},'resources':[],'resourceTemplates':[]}
  self.assertTrue(S.validate_mcp_inventory({'data':[], 'nextCursor':None}))
  self.assertTrue(S.validate_mcp_inventory({'data':[empty_server]}))
  value=S.execute(self.fake_server(COMPLETE,mcp_inventory={'data':[empty_server]}),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('executed',value['status'])
 def test_malformed_mcp_shapes_cannot_start_model(self):
  server={'name':'disabled-server','authStatus':'unknown','tools':{},'resources':[],'resourceTemplates':[]}
  shapes=[{}, {'data':[{}]}, {'data':None}, {'data':{}}, {'data':[None]}, {'data':[], 'nextCursor':False}]
  for name,wrong in [('name',1),('authStatus',False),('tools',[]),('resources',{}),('resourceTemplates','')]:
   shape=dict(server);shape[name]=wrong;shapes.append({'data':[shape]})
  for name in server:
   shape=dict(server);del shape[name];shapes.append({'data':[shape]})
  shape=dict(server);shape['authStatus']='new-unknown-value';shapes.append({'data':[shape]})
  for index,inventory in enumerate(shapes):
   with self.subTest(inventory=inventory):
    case_dir=self.run/str(index);case_dir.mkdir()
    value=S.execute(self.fake_server(COMPLETE,mcp_inventory=inventory),[],self.workspace,'public request',{},case_dir,5)
    self.assertEqual('execution-failed',value['status'])
    requests=[json.loads(v) for v in (case_dir/'requests.jsonl').read_text().splitlines()]
    self.assertFalse(any(v.get('method')=='turn/start' for v in requests))
    self.assertIn('malformed',value['reason'])
 def test_empty_cursor_cannot_hide_incomplete_inventory(self):
  with self.assertRaises(RuntimeError):S.validate_mcp_inventory({'data':[],'nextCursor':''})
 def test_foreign_thread_final_usage_and_completion_cannot_finish_root(self):
  foreign=COMPLETE.replace("'unit-thread'","'child-thread'").replace('Reviewed real artifacts','FOREIGN ANSWER').replace("'inputTokens':1","'inputTokens':999")
  value=S.execute(self.fake_server(foreign+'\n  '+COMPLETE),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('executed',value['status']);self.assertEqual(3,value['ignored_foreign_lifecycle_events'])
  self.assertNotIn('FOREIGN ANSWER',(self.run/'last-message.txt').read_text())
  events=[json.loads(v) for v in (self.run/'events.jsonl').read_text().splitlines()]
  completed=next(v for v in events if v['type']=='turn.completed')
  self.assertEqual(1,completed['usage']['total']['inputTokens'])
  self.assertIn('FOREIGN ANSWER',(self.run/'appserver.jsonl').read_text())
 def test_wrong_turn_completion_without_root_completion_times_out(self):
  wrong_turn=COMPLETE.replace("'unit-turn'","'other-turn'")
  value=S.execute(self.fake_server(wrong_turn),[],self.workspace,'public request',{},self.run,.1)
  self.assertEqual('timeout',value['status'])
  self.assertNotIn('"type": "turn.completed"',(self.run/'events.jsonl').read_text())
 def test_commentary_only_is_not_final(self):
  commentary=COMPLETE.replace("'final_answer'","'commentary'")
  value=S.execute(self.fake_server(commentary),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  self.assertEqual('',(self.run/'last-message.txt').read_text())
 def test_root_notifications_before_start_response_are_replayed(self):
  value=S.execute(self.fake_server(COMPLETE,before_response=True),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('executed',value['status'])
  self.assertEqual('unit-turn',value['root_turn_id'])
  self.assertEqual('unit-thread',value['root_thread_id'])
 def test_timeout_preserves_raw_partial_protocol(self):
  value=S.execute(self.fake_server('time.sleep(30)'),[],self.workspace,'public request',{},self.run,0.1)
  self.assertEqual('timeout',value['status'])
  self.assertTrue((self.run/'appserver.jsonl').exists());self.assertFalse((self.run/'last-message.txt').exists())
 def test_process_crash_is_not_completion(self):
  value=S.execute(self.fake_server('sys.exit(3)'),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status']);self.assertEqual(3,value['returncode'])
 def test_malformed_message_cannot_pass(self):
  value=S.execute(self.fake_server('print("not-json",flush=True)'),[],self.workspace,'public request',{},self.run,5)
  self.assertEqual('execution-failed',value['status'])
  self.assertIn('malformed',value['reason'])


if __name__=='__main__':unittest.main()
