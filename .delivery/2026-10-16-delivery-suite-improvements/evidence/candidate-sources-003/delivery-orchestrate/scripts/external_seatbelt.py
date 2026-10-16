#!/usr/bin/env python3
"""Explicit macOS external-sandbox adapter; never a fallback from another policy."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid


HISTORY_DIRECTORIES = ('sessions', 'archived_sessions', 'memories', 'memories_v2',
                       'sqlite', 'log', 'dictation-history', 'thread-writer-locks')
HISTORY_FILE_PATTERN = r'([^/]*\.sqlite(-[^/]*)?|[.]*codex-global-state[^/]*|(transcription-)?history\.jsonl|session_index\.jsonl)'
THREAD_METADATA_COLUMNS = {'id': 'TEXT', 'rollout_path': 'TEXT', 'created_at': 'INTEGER',
                           'updated_at': 'INTEGER', 'source': 'TEXT', 'model_provider': 'TEXT',
                           'cwd': 'TEXT', 'title': 'TEXT', 'first_user_message': 'TEXT'}


def historical_read_policy(state_home):
    """Block persisted history sources, not the normal auth/config or CLI binary."""
    home = Path(state_home).resolve()
    roots = [home / name for name in HISTORY_DIRECTORIES]
    expression = '^' + re.escape(str(home)) + '/' + HISTORY_FILE_PATTERN + '$'
    files = [p for p in home.iterdir() if re.fullmatch(HISTORY_FILE_PATTERN, p.name)]
    # Resolve existing aliases too: seatbelt evaluates resolved paths. Never read
    # the history itself in the evaluator; names/stat are enough to build rules.
    aliases = sorted({p.resolve() for p in roots + files if p.exists() and p.resolve() != p})
    rules = [('subpath', str(p)) for p in roots + aliases] + [('regex', expression)]
    probes = sorted({p.resolve() for p in roots + files if p.exists()})
    return rules, probes


def inspect_state_database(sqlite_home):
    """Require a real initialized empty thread DB; absence/errors fail closed."""
    paths = sorted(Path(sqlite_home).glob('state_*.sqlite'))
    if len(paths) != 1 or paths[0].is_symlink():
        raise RuntimeError('startup state audit requires exactly one regular initialized state database; model not started')
    with sqlite3.connect(paths[0].resolve().as_uri() + '?mode=ro', uri=True) as database:
        objects = database.execute("SELECT type, sql FROM sqlite_master WHERE name='threads'").fetchall()
        if not isinstance(objects, list) or len(objects) != 1 or not isinstance(objects[0], tuple) or len(objects[0]) != 2 or objects[0][0] != 'table' or not isinstance(objects[0][1], str) or objects[0][1].lstrip().upper().startswith('CREATE VIRTUAL'):
            raise RuntimeError('startup state audit requires a real threads table, not a view or virtual/unknown object; model not started')
        columns = database.execute('PRAGMA table_info(threads)').fetchall()
        if not isinstance(columns, list) or not columns or any(not isinstance(row, tuple) or len(row) != 6 or not isinstance(row[1], str) or not isinstance(row[2], str) or type(row[5]) is not int for row in columns):
            raise RuntimeError('startup state audit PRAGMA returned an invalid schema; model not started')
        observed = {row[1]: str(row[2]).strip().upper() for row in columns}
        if any(observed.get(name) != kind for name, kind in THREAD_METADATA_COLUMNS.items()):
            raise RuntimeError('startup state audit threads metadata schema missing or incompatible; model not started')
        if [(row[1], row[5]) for row in columns if row[5]] != [('id', 1)]:
            raise RuntimeError('startup state audit requires the threads id primary key; model not started')
        row = database.execute('SELECT COUNT(*) FROM threads').fetchone()
        if not isinstance(row, tuple) or len(row) != 1 or type(row[0]) is not int or row[0] < 0:
            raise RuntimeError('startup state audit COUNT returned an invalid result; model not started')
        count = row[0]
    proof = {'database': str(paths[0]), 'thread_row_count': count, 'passed': count == 0,
             'threads_object': 'table', 'validated_metadata_columns': THREAD_METADATA_COLUMNS,
             'method': 'read-only table/schema/primary-key validation and COUNT(*) before any model turn; no thread contents exported'}
    return proof


def run_state_home(workspace, run_root):
    root = Path(workspace).resolve() / '.evaluation-state'
    current = root / ('run-' + Path(run_root).name)
    if root.is_symlink() or current.is_symlink():
        raise ValueError('evaluation state directories must not be symlinks')
    return current


def prior_state_roots(workspace, run_root):
    """Read evaluator-owned path metadata only, never database/history bodies."""
    workspace = Path(workspace).resolve()
    evidence = next((p for p in Path(run_root).resolve().parents if p.name == 'evidence' and (p / 'behavior').is_dir()), None)
    records = []
    if evidence:
        paths = sorted(set((evidence / 'behavior').glob('*/evaluation.json')) | set((evidence / 'behavior').glob('*/result.json')))
        for path in paths:
            data = json.loads(path.read_text())
            value = data.get('workspace') if isinstance(data, dict) else None
            if not isinstance(value, str) or not Path(value).is_absolute():
                continue
            old = Path(value).resolve()
            if old == workspace or (old.parent == workspace.parent and old.name.startswith('delivery-eval-work-')):
                continue
            records.append({'metadata': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'workspace': str(old), 'denied_state': str(old / '.evaluation-state')})
    return records


def path_aliases(path):
    value = str(Path(path).resolve())
    aliases = [value]
    for prefix in ('/private/var/', '/private/tmp/'):
        if value.startswith(prefix):
            aliases.append(value.removeprefix('/private'))
    return aliases


def protected_metadata(state_home):
    """Only digests/metadata: never return credential or installation-id contents."""
    result = {}
    for name in ('installation_id', 'auth.json', 'config.toml'):
        path = Path(state_home) / name
        if path.exists():
            info = path.stat()
            result[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': stat.S_IMODE(info.st_mode), 'size': info.st_size, 'mtime_ns': info.st_mtime_ns}
        else:
            result[name] = {'exists': False}
    return result


def validate_installation_id(state_home):
    identity = Path(state_home) / 'installation_id'
    if not identity.is_file() or identity.is_symlink():
        raise ValueError('normal CLI installation_id must already exist as a regular file; no bootstrap or symlink')
    uuid.UUID(identity.read_text().strip())
    if stat.S_IMODE(identity.stat().st_mode) != 0o644:
        raise ValueError('normal installation_id mode must already be 0644; evaluation must not change it')
    return identity


def verify_protection(isolation):
    after = protected_metadata(isolation['state_home'])
    return {'before': isolation['protected_files_before'], 'after': after, 'unchanged': after == isolation['protected_files_before']}


def profile_text(workspace, denied, state_home, *, runtime_state=None, known_states=()):
    """Only fixture, /dev/null and the one proven installation identity may open writable."""
    workspace = Path(workspace).resolve()
    denied = [Path(p).resolve(strict=True) for p in denied]
    if not denied or any(workspace.is_relative_to(p) or p.is_relative_to(workspace) for p in denied):
        raise ValueError('external seatbelt requires denied oracle/source directories separate from fixture')
    for path in denied:
        if not path.is_dir():
            raise ValueError('denied roots must be actual directories')
    identity = Path(state_home).resolve() / 'installation_id'
    # App-server 0.154 opens this existing UUID O_RDWR even when not changing it.
    # Only this literal is excepted; auth/config and all sibling paths stay denied.
    allowed = ['(subpath ' + json.dumps(str(workspace)) + ')', '(literal "/dev/null")', '(literal ' + json.dumps(str(identity)) + ')']
    text = '(version 1)\n(allow default)\n'
    text += ''.join('(deny file-read* (subpath ' + json.dumps(str(p)) + '))\n' for p in denied)
    history_rules, _ = historical_read_policy(state_home)
    for kind, value in history_rules:
        if kind == 'subpath' and (workspace.is_relative_to(Path(value)) or Path(value).is_relative_to(workspace)):
            raise ValueError('historical state roots must be separate from fixture')
        # SBPL #"..." is a regex literal, not a Scheme/JSON string: doubling
        # regex backslashes changes their meaning and silently misses files.
        encoded = '#' + json.dumps(value).replace('\\\\', '\\') if kind == 'regex' else json.dumps(value)
        text += '(deny file-read* (' + kind + ' ' + encoded + '))\n'
    sibling_patterns = ['^' + re.escape(parent) + '/delivery-eval-work-[^/]+(/|$)' for parent in path_aliases(workspace.parent)]
    for expression in sibling_patterns:
        encoded = '#' + json.dumps(expression).replace('\\\\', '\\')
        text += '(deny file-read* (require-all (regex ' + encoded + ') (require-not (subpath ' + json.dumps(str(workspace)) + '))))\n'
    for root in sorted({str(Path(p).resolve()) for p in known_states}):
        if Path(root).is_relative_to(workspace) or workspace.is_relative_to(Path(root)):
            raise ValueError('prior evaluation state must be outside current fixture')
        text += '(deny file-read* (subpath ' + json.dumps(root) + '))\n'
    old_state = workspace / '.evaluation-state'
    state_rule = '(subpath ' + json.dumps(str(old_state)) + ')'
    if runtime_state is not None:
        runtime_state = Path(runtime_state)
        if runtime_state.parent != old_state or runtime_state.is_symlink() or old_state.is_symlink():
            raise ValueError('current runtime state must be one direct regular child of fixture state root')
        state_rule = '(require-all ' + state_rule + ' (require-not (subpath ' + json.dumps(str(runtime_state)) + ')))'
    # Resuming a contaminated fixture must not expose prior imported metadata.
    # Keep old databases and sidecars intact, but inaccessible to this process.
    # SQLite's canonicalization/mkdir checks stat the shared parent. Permit
    # metadata for that one directory, but not listing its prior children.
    read_state_rule = '(require-all ' + state_rule + ' (require-not (literal ' + json.dumps(str(old_state)) + ')))'
    text += '(deny file-read* ' + read_state_rule + ')\n'
    text += '(deny file-read-data (literal ' + json.dumps(str(old_state)) + '))\n'
    text += '(deny file-write* ' + state_rule + ')\n'
    text += '(deny file-write* (require-all\n' + ''.join('  (require-not ' + rule + ')\n' for rule in allowed) + '))\n'
    return text, {'workspace_write_root': str(workspace), 'denied_read_roots': [str(p) for p in denied], 'historical_read_denials': [{'kind': k, 'value': v} for k, v in history_rules], 'other_fixture_patterns': sibling_patterns, 'known_prior_state_roots': sorted(set(known_states)), 'prior_fixture_state_denied': str(old_state), 'current_run_state_exception': str(runtime_state) if runtime_state else None, 'exact_cli_state_write_exceptions': [str(identity)], 'device_write_exceptions': ['/dev/null'], 'network': 'unchanged; model/API connectivity retained; not a network-isolation claim'}


def probe_boundary(workspace, denied, state_home, run_root, sandbox_cli=None):
    """Run three real subprocess checks before any app-server/model process starts."""
    sandbox_cli = sandbox_cli or shutil.which('sandbox-exec')
    if not sandbox_cli:
        raise ValueError('sandbox-exec unavailable; external-seatbelt cannot run')
    run_root = Path(run_root)
    identity = validate_installation_id(state_home)
    protected_before = protected_metadata(state_home)
    current_state = run_state_home(workspace, run_root)
    prior_records = prior_state_roots(workspace, run_root)
    known_states = sorted({r['denied_state'] for r in prior_records})
    profile, policy = profile_text(workspace, denied, state_home, runtime_state=current_state, known_states=known_states)
    (run_root / 'prior-state-paths.json').write_text(json.dumps(prior_records, indent=2) + '\n')
    (run_root / 'external-seatbelt.sb').write_text(profile)
    token = uuid.uuid4().hex
    private_canary = Path(denied[0]) / ('.private-canary-' + token)
    inside = Path(workspace) / ('.write-canary-' + token)
    with tempfile.TemporaryDirectory(prefix='delivery-external-write-probe-') as outside_dir, tempfile.TemporaryDirectory(prefix='delivery-eval-work-', dir=Path(workspace).resolve().parent) as sibling_dir:
        outside = Path(outside_dir) / 'forbidden-write'
        sibling = Path(sibling_dir)
        (sibling / 'README.md').write_text(token)
        (sibling / '.evaluation-state').mkdir()
        (sibling / '.evaluation-state/state_5.sqlite').write_text('synthetic future sibling state, not user history')
        try:
            private_canary.write_text(token)
            private_canary.read_text()  # Establish baseline readability in the parent.
            commands = [
                ('private_read', [sandbox_cli, '-p', profile, '/bin/cat', str(private_canary)]),
                ('outside_write', [sandbox_cli, '-p', profile, '/bin/sh', '-c', 'printf boundary-probe > "$1"', 'probe', str(outside)]),
                ('inside_write', [sandbox_cli, '-p', profile, '/bin/sh', '-c', 'printf boundary-probe > "$1"', 'probe', str(inside)]),
                ('inside_read', [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);os.close(fd)', str(inside)]),
                ('identity_write_open', [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDWR);os.close(fd)', str(identity)]),
                ('auth_write_open', [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDWR);os.close(fd)', str(Path(state_home)/'auth.json')]),
                ('config_write_open', [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDWR);os.close(fd)', str(Path(state_home)/'config.toml')]),
            ]
            for index, alias in enumerate(path_aliases(inside)[1:]):
                commands.append(('inside_alias_read_' + str(index), [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);os.close(fd)', alias]))
            _, historical_targets = historical_read_policy(state_home)
            for index, target in enumerate(historical_targets):
                commands.append(('historical_read_' + str(index), [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);os.close(fd)', str(target)]))
            old_targets = sorted(p for p in (Path(workspace) / '.evaluation-state').rglob('*') if p.is_file() and not p.is_relative_to(current_state))
            if (Path(workspace) / '.evaluation-state').exists():
                commands.append(('prior_fixture_state_listing', [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;os.listdir(sys.argv[1])', str(Path(workspace) / '.evaluation-state')]))
            for index, target in enumerate(old_targets):
                commands.append(('prior_fixture_state_read_' + str(index), [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);os.close(fd)', str(target)]))
                commands.append(('prior_fixture_state_write_' + str(index), [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_WRONLY);os.close(fd)', str(target)]))
            cross_targets = set()
            for root in Path(workspace).resolve().parent.glob('delivery-eval-work-*'):
                if root.resolve() != Path(workspace).resolve():
                    if (root / 'README.md').is_file(): cross_targets.add(root / 'README.md')
                    cross_targets.update((root / '.evaluation-state').rglob('state_*.sqlite'))
            for root in known_states:
                cross_targets.update(Path(root).rglob('state_*.sqlite'))
            for index, target in enumerate(sorted(cross_targets)):
                for alias_index, alias in enumerate(path_aliases(target)):
                    commands.append(('other_fixture_read_' + str(index) + '_' + str(alias_index), [sandbox_cli, '-p', profile, '/usr/bin/python3', '-I', '-S', '-c', 'import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY);os.close(fd)', alias]))
            results = {}
            for name, argv in commands:
                outcome = subprocess.run(argv, text=True, capture_output=True, timeout=15)
                results[name] = {'returncode': outcome.returncode, 'stdout': outcome.stdout, 'stderr': outcome.stderr}
            denied_read = results['private_read']['returncode'] != 0 and 'Operation not permitted' in results['private_read']['stderr'] and not results['private_read']['stdout']
            denied_write = results['outside_write']['returncode'] != 0 and 'Operation not permitted' in results['outside_write']['stderr'] and not outside.exists()
            allowed_write = results['inside_write']['returncode'] == 0 and inside.exists() and inside.read_text() == 'boundary-probe'
            allowed_read = results['inside_read']['returncode'] == 0 and all(v['returncode'] == 0 for k, v in results.items() if k.startswith('inside_alias_read_'))
            identity_open = results['identity_write_open']['returncode'] == 0
            protected_open_denied = all(results[name]['returncode'] != 0 and 'Operation not permitted' in results[name]['stderr'] for name in ('auth_write_open', 'config_write_open'))
            history_denied = all(results[name]['returncode'] != 0 and 'Operation not permitted' in results[name]['stderr'] and not results[name]['stdout'] for name in results if name.startswith('historical_read_'))
            prior_state_denied = all(results[name]['returncode'] != 0 and 'Operation not permitted' in results[name]['stderr'] and not results[name]['stdout'] for name in results if name.startswith('prior_fixture_state_'))
            cross_denied = all(results[name]['returncode'] != 0 and 'Operation not permitted' in results[name]['stderr'] and not results[name]['stdout'] for name in results if name.startswith('other_fixture_read_'))
            unchanged = protected_metadata(state_home) == protected_before
            evidence = {'kind': 'macos-single-external-seatbelt', 'state_home': str(Path(state_home).resolve()), 'protected_files_before': protected_before, 'passed': denied_read and denied_write and allowed_write and allowed_read and identity_open and protected_open_denied and history_denied and prior_state_denied and cross_denied and unchanged, 'historical_read_probe_count': len(historical_targets), 'prior_fixture_state_probe_count': len(old_targets), 'other_fixture_read_target_count': len(cross_targets), 'future_sibling_created_after_profile': str(sibling), 'checks': results, 'policy': policy, 'profile_sha256': hashlib.sha256(profile.encode()).hexdigest()}
            (run_root / 'isolation.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
            if not evidence['passed']:
                raise ValueError('external seatbelt read/write boundary canaries did not all pass; model not started')
            return [sandbox_cli, '-p', profile], evidence
        finally:
            private_canary.unlink(missing_ok=True)
            inside.unlink(missing_ok=True)


def inspect_protocol(cli, run_root):
    """Derive supported protocol from the exact local CLI, not guessed flags."""
    run_root = Path(run_root)
    # The CLI exports 300+ duplicate per-method schemas. Preserve the canonical
    # complete bundle and raw generation command, avoiding redundant evidence.
    with tempfile.TemporaryDirectory(prefix='delivery-protocol-schema-') as directory:
        schema_dir = Path(directory)
        command = [cli, 'app-server', 'generate-json-schema', '--out', str(schema_dir)]
        outcome = subprocess.run(command, text=True, capture_output=True, timeout=30)
        (run_root / 'schema-command.json').write_text(json.dumps({'argv': command, 'returncode': outcome.returncode, 'stdout': outcome.stdout, 'stderr': outcome.stderr}, ensure_ascii=False, indent=2) + '\n')
        if outcome.returncode:
            raise ValueError('installed CLI could not export app-server schema')
        path = run_root / 'protocol-schema.json'
        shutil.copy2(schema_dir / 'codex_app_server_protocol.schemas.json', path)
    data = json.loads(path.read_text())
    definitions = data.get('definitions', {}).get('v2', {})
    policy = definitions.get('SandboxPolicy', {})
    branches = policy.get('oneOf', [])
    if not any(branch.get('properties', {}).get('type', {}).get('enum') == ['externalSandbox'] for branch in branches):
        raise ValueError('installed app-server schema does not support externalSandbox')
    proof = {'schema_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'policy': policy, 'source': str(path), 'command': command}
    (run_root / 'protocol.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    return proof


def validate_mcp_inventory(inventory):
    """Fail closed on the installed v2 response/server minimum schema shapes.

    Shape validity and capability absence are separate checks: malformed data
    cannot be interpreted as an empty tool catalog. Enum values match the
    captured CLI 0.154 McpAuthStatus definition, retained in protocol-schema.json.
    """
    if not isinstance(inventory, dict) or 'data' not in inventory or not isinstance(inventory['data'], list):
        raise RuntimeError('MCP inventory malformed: required data array missing or wrong type; model not started')
    cursor = inventory.get('nextCursor')
    if cursor is not None and not isinstance(cursor, str):
        raise RuntimeError('MCP inventory malformed: nextCursor must be string or null; model not started')
    auth_statuses = {'unknown', 'unsupported', 'notLoggedIn', 'bearerToken', 'oAuth'}
    required = {'name':str, 'authStatus':str, 'tools':dict, 'resources':list, 'resourceTemplates':list}
    for server in inventory['data']:
        if not isinstance(server, dict):
            raise RuntimeError('MCP inventory malformed: server entry must be an object; model not started')
        for name, kind in required.items():
            if name not in server or not isinstance(server[name], kind):
                raise RuntimeError('MCP inventory malformed: server '+name+' missing or wrong type; model not started')
        if server['authStatus'] not in auth_statuses:
            raise RuntimeError('MCP inventory malformed: unknown authStatus; model not started')
    if cursor is not None or any(server['tools'] or server['resources'] or server['resourceTemplates'] for server in inventory['data']):
        raise RuntimeError('MCP inventory exposes external capabilities or incomplete pagination despite configured disables; model not started')
    return True


def execute(cli, wrapper, workspace, prompt, model_config, run_root, timeout, *, startup_only=False):
    """One fresh ephemeral app-server thread/turn. Complete raw protocol is retained."""
    run_root = Path(run_root)
    scratch = Path(workspace) / '.evaluation-tmp'
    scratch.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment['TMPDIR'] = str(scratch)  # Normal temp routing, never HOME/CODEX_HOME.
    environment['TMPPREFIX'] = str(scratch / 'zsh')  # zsh heredocs use this, not TMPDIR.
    state_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    config_path = state_home / 'config.toml'
    actual_config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    server_names = list(actual_config.get('mcp_servers', {}))
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in server_names):
        raise ValueError('MCP server name needs explicitly reviewed quoting; no unsafe override or silent omission')
    sqlite_home = run_state_home(workspace, run_root)
    log_dir = Path(workspace) / '.evaluation-log'
    sqlite_home.mkdir(parents=True, exist_ok=False)
    log_dir.mkdir(exist_ok=True)
    argv = wrapper + [cli, 'app-server', '--strict-config', '--listen', 'stdio://', '-c', 'sqlite_home=' + json.dumps(str(sqlite_home)), '-c', 'log_dir=' + json.dumps(str(log_dir))]
    disabled_features = ['apps', 'plugins', 'remote_plugin', 'memories', 'shell_snapshot']
    for name in disabled_features:
        argv.extend(['--disable', name])
    for name in server_names:
        argv.extend(['-c', 'mcp_servers.' + name + '.enabled=false'])
    for key, value in model_config.items():
        argv.extend(['-c', key + '=' + json.dumps(value)])
    outcome = {'returncode': None, 'status': 'not-run', 'argv': argv, 'environment_keys_changed': ['TMPDIR', 'TMPPREFIX'], 'sandbox_policy': {'type':'externalSandbox', 'networkAccess':'enabled'}, 'approval_policy': 'never', 'fresh_context': True, 'config_policy': 'app-server loads actual user config; model/effort explicit; actual configured MCP server names and stable apps/plugins/remote_plugin/memories/shell_snapshot features explicitly disabled; runtime inventory checked before model turn; no unsupported ignore-user-config flag'}
    outcome['temporary_environment'] = {'TMPDIR': environment['TMPDIR'], 'TMPPREFIX': environment['TMPPREFIX']}
    outcome['runtime_state'] = {'sqlite_home': str(sqlite_home), 'log_dir': str(log_dir), 'strict_config': True, 'user_home_write_exceptions': [str(state_home / 'installation_id')]}
    outcome['disabled_features'] = disabled_features
    outcome['configured_mcp_servers_disabled'] = server_names
    outcome['actual_config_sha256'] = hashlib.sha256(config_path.read_bytes()).hexdigest() if config_path.exists() else None
    deadline = time.monotonic() + timeout
    messages = queue.Queue()
    process = subprocess.Popen(argv, cwd=workspace, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, bufsize=1)
    readers = []
    raw = (run_root / 'appserver.jsonl').open('w')
    errors = (run_root / 'stderr.txt').open('w')
    requests = (run_root / 'requests.jsonl').open('w')
    events = (run_root / 'events.jsonl').open('w')

    def read_stdout():
        try:
            for line in process.stdout:
                raw.write(line); raw.flush()
                try: messages.put(json.loads(line))
                except json.JSONDecodeError: messages.put({'_malformed':line})
        finally:
            messages.put({'_eof':True})

    def read_stderr():
        for line in process.stderr:
            errors.write(line); errors.flush()

    def send(value):
        text = json.dumps(value, ensure_ascii=False)
        requests.write(text+'\n'); requests.flush()
        process.stdin.write(text+'\n'); process.stdin.flush()

    def event(value):
        events.write(json.dumps(value, ensure_ascii=False)+'\n'); events.flush()

    def receive():
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError('app-server turn timed out')
        try: value = messages.get(timeout=min(remaining, 1))
        except queue.Empty:
            if process.poll() is not None: raise RuntimeError('app-server exited before completed turn')
            return None
        if not isinstance(value, dict): raise RuntimeError('app-server message is not an object')
        if value.get('_eof'): raise RuntimeError('app-server stream ended before completed turn')
        if value.get('_malformed'): raise RuntimeError('malformed app-server JSONL')
        return value

    def response(expected):
        while True:
            value = receive()
            if value is None: continue
            if value.get('id') == expected:
                if 'error' in value: raise RuntimeError('app-server request rejected: '+json.dumps(value['error']))
                return value.get('result', {})
            consume(value)

    thread_id = None
    root_turn_id = None
    pending_lifecycle = []
    final_messages = []
    token_usage = None
    terminal = None

    def consume(value, *, replay=False):
        nonlocal token_usage, terminal
        method = value.get('method')
        params = value.get('params', {})
        if not replay:
            # Complete wire events remain verbatim; filtering affects only the
            # root turn's derived completion/final/usage, never raw history.
            event({'type':'appserver.notification', 'message':value})
        if method and 'id' in value:
            send({'id':value['id'],'error':{'code':-32601,'message':'controlled evaluation does not grant interactive approvals or unknown client tools'}})
            event({'type':'error','reason':'unexpected client-side RPC request denied','method':method})
        if method not in ('item/completed', 'thread/tokenUsage/updated', 'turn/completed'):
            return
        if thread_id is None or root_turn_id is None:
            if not replay:
                pending_lifecycle.append(value)
            return
        event_turn_id = params.get('turn', {}).get('id') if method == 'turn/completed' else params.get('turnId')
        if params.get('threadId') != thread_id or event_turn_id != root_turn_id:
            outcome['ignored_foreign_lifecycle_events'] = outcome.get('ignored_foreign_lifecycle_events', 0) + 1
            return
        if method == 'item/completed':
            item = params.get('item', {})
            if item.get('type') == 'agentMessage':
                final_messages.append((item.get('phase'), item.get('text','')))
        elif method == 'thread/tokenUsage/updated':
            token_usage = params.get('tokenUsage')
        elif method == 'turn/completed':
            turn = params.get('turn', {})
            terminal = turn.get('status')
            outcome['turn'] = turn
            if terminal == 'completed':
                event({'type':'turn.completed','thread_id':thread_id,'turn_id':root_turn_id,'usage':token_usage})
            else:
                event({'type':'turn.failed','thread_id':thread_id,'turn_id':root_turn_id,'turn':turn})

    try:
        for target in (read_stdout, read_stderr):
            reader=threading.Thread(target=target,daemon=True);reader.start();readers.append(reader)
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'delivery-evaluation','version':'1'}}})
        outcome['initialize']=response(1)
        send({'method':'initialized','params':{}})
        start={'cwd':str(workspace),'ephemeral':True,'approvalPolicy':'never','sandbox':'read-only'}
        if model_config.get('model'):start['model']=model_config['model']
        send({'id':2,'method':'thread/start','params':start})
        created=response(2)
        thread_id=created['thread']['id']
        outcome['thread_start']=created
        event({'type':'thread.started','thread_id':thread_id})
        send({'id':5,'method':'mcpServerStatus/list','params':{'threadId':thread_id}})
        outcome['mcp_runtime_inventory'] = response(5)
        validate_mcp_inventory(outcome['mcp_runtime_inventory'])
        try:
            outcome['startup_state_audit'] = inspect_state_database(sqlite_home)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            outcome['startup_state_audit'] = {'database_root': str(sqlite_home), 'passed': False,
                                             'error_type': type(error).__name__, 'reason': str(error)}
        (run_root / 'startup-state-audit.json').write_text(json.dumps(outcome['startup_state_audit'], indent=2) + '\n')
        if not outcome['startup_state_audit']['passed']:
            raise RuntimeError('startup state audit rejected nonempty or invalid thread database; model not started')
        if startup_only:
            outcome['status'] = 'initialized'
            outcome['reason'] = 'startup and empty state verified; no model turn requested'
            outcome['model_turn_started'] = False
            return outcome
        turn={'threadId':thread_id,'cwd':str(workspace),'approvalPolicy':'never','sandboxPolicy':outcome['sandbox_policy'],'input':[{'type':'text','text':prompt,'text_elements':[]}]}
        if model_config.get('model'):turn['model']=model_config['model']
        if model_config.get('model_reasoning_effort'):turn['effort']=model_config['model_reasoning_effort']
        send({'id':3,'method':'turn/start','params':turn})
        outcome['turn_start']=response(3)
        root_turn_id = outcome['turn_start']['turn']['id']
        outcome['root_thread_id'] = thread_id
        outcome['root_turn_id'] = root_turn_id
        for buffered in pending_lifecycle:
            consume(buffered, replay=True)
        pending_lifecycle.clear()
        while terminal is None:
            value=receive()
            if value is not None:consume(value)
        final=[text for phase,text in final_messages if phase=='final_answer'] or [text for phase,text in final_messages if phase is None]
        (run_root/'last-message.txt').write_text('\n\n'.join(final))
        outcome['status']='executed' if terminal=='completed' and any(t.strip() for t in final) else 'execution-failed'
        outcome['reason']='awaiting independent artifact review' if outcome['status']=='executed' else 'turn did not complete with a nonempty final response'
    except (TimeoutError, KeyboardInterrupt) as error:
        outcome['status']='timeout' if isinstance(error,TimeoutError) else 'interrupted'
        outcome['reason']='partial/unknown execution preserved; no implicit retry'
        if thread_id:
            try: send({'id':4,'method':'turn/interrupt','params':{'threadId':thread_id,'turnId':outcome.get('turn_start',{}).get('turn',{}).get('id','')}})
            except (OSError,ValueError):pass
    except (OSError,ValueError,KeyError,RuntimeError,sqlite3.Error) as error:
        outcome['status']='execution-failed'
        outcome['reason']=str(error)
        event({'type':'error','reason':str(error)})
    finally:
        try:
            if process.stdin and not process.stdin.closed:process.stdin.close()
            process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
            outcome['shutdown']='parent terminated process group after collecting current turn state'
        outcome['returncode']=process.returncode
        for reader in readers:reader.join(timeout=3)
        for stream in (process.stdout, process.stderr):
            if stream:stream.close()
        for stream in (raw,errors,requests,events):stream.close()
        if process.returncode not in (0,None) and outcome['status'] in ('executed', 'initialized') and 'shutdown' not in outcome:
            outcome['status']='execution-failed';outcome['reason']='app-server crashed after reported turn completion'
        (run_root/'appserver-result.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+'\n')
    return outcome
