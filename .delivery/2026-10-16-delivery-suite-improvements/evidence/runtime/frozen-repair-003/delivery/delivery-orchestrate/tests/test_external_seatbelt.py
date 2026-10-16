"""External adapter unit tests; fake local JSON-RPC server is not an agent run."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('external_seatbelt',Path(__file__).parents[1]/'scripts/external_seatbelt.py')
S=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(S)

SERVER='''#!PYTHON
import json,sys,time
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
  self.run=self.root/'run';self.run.mkdir()
 def tearDown(self):self.temp.cleanup()
 def fake_server(self,behavior,before_response=False):
  script=SERVER.replace('PYTHON',sys.executable).replace('BEHAVIOR',behavior)
  if before_response:
   acknowledgement="  print(json.dumps({'id':identity,'result':{'turn':{'id':'unit-turn','status':'inProgress'}}}),flush=True)"
   script=script.replace(acknowledgement+'\n  '+behavior,'  '+behavior+'\n'+acknowledgement)
  server=self.root/'unit-server';server.write_text(script);server.chmod(0o755);return str(server)
 def test_profile_grants_no_auth_config_or_home_directory_write(self):
  text,policy=S.profile_text(self.workspace,[self.private],self.state)
  self.assertIn('(deny file-write* (require-all',text)
  self.assertNotIn('(subpath '+json.dumps(str(self.state))+')',text)
  self.assertNotIn('auth.json',text);self.assertNotIn('config.toml',text)
  self.assertEqual([],policy['exact_cli_state_write_exceptions'])
  self.assertIn('(deny file-read* (subpath '+json.dumps(str(self.private.resolve()))+'))',text)
 def test_profile_rejects_fixture_inside_denied_root(self):
  with self.assertRaises(ValueError):S.profile_text(self.workspace,[self.root],self.state)
 def test_three_canaries_must_all_pass(self):
  def fake_probe(argv,**kwargs):
   if argv[3]=='/bin/cat':return subprocess.CompletedProcess(argv,1,'','cat: Operation not permitted')
   target=Path(argv[-1])
   if target.parent==self.workspace:
    target.write_text('boundary-probe');return subprocess.CompletedProcess(argv,0,'','')
   return subprocess.CompletedProcess(argv,1,'','sh: Operation not permitted')
  with patch.object(S.subprocess,'run',side_effect=fake_probe):
   wrapper,proof=S.probe_boundary(self.workspace,[self.private],self.state,self.run,sandbox_cli='/sandbox-exec')
  self.assertTrue(proof['passed']);self.assertEqual('/sandbox-exec',wrapper[0])
  self.assertEqual([],list(self.private.iterdir()))
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
  self.assertEqual(['TMPDIR'],value['environment_keys_changed'])
  self.assertNotIn('--dangerously',json.dumps(value['argv']))
  self.assertIn('--strict-config',value['argv'])
  self.assertTrue(any(v.startswith('sqlite_home=') for v in value['argv']))
  self.assertEqual([],value['runtime_state']['user_home_write_exceptions'])
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
