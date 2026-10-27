#!/usr/bin/env python3
"""Isolated real-agent evaluations. Execution success is never semantic approval."""
from __future__ import annotations
import argparse
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

SCHEMA = 1
EVALUATOR_DIRS = ('.evaluation-state', '.evaluation-log', '.evaluation-tmp', '.evaluation-output')
SKILLS = ('delivery-design', 'delivery-plan', 'delivery-implement', 'delivery-review', 'delivery-verify', 'delivery-orchestrate')
PROFESSIONAL_SKILLS = tuple(name for name in SKILLS if name != 'delivery-orchestrate') + ('delivery-fix',)
NATURAL_SKILLS = SKILLS + ('delivery-fix',)


def activation(case):
    value = case.get('activation', 'explicit')
    if value not in ('explicit', 'natural'):
        raise ValueError('activation must be explicit or natural')
    return value


def validate_natural_input(case, prompt=None):
    if activation(case) != 'natural':
        return
    skills = case.get('skills')
    if not isinstance(skills, list) or not all(isinstance(name, str) for name in skills) or len(skills) != len(NATURAL_SKILLS) or set(skills) != set(NATURAL_SKILLS):
        raise ValueError('natural activation requires exactly the seven frozen delivery skills')
    if not isinstance(case.get('prompt'), str) or not case['prompt'].strip():
        raise ValueError('natural activation requires a nonempty public prompt')
    for field in ('requirements', 'allowed_changes'):
        if not isinstance(case.get(field, []), list) or not all(isinstance(item, str) for item in case.get(field, [])):
            raise ValueError('natural public ' + field + ' must be an array of strings')
    public = json.dumps([case.get('prompt') if prompt is None else prompt,
                         case.get('requirements', []), case.get('allowed_changes', [])], ensure_ascii=False)
    if any(name in public.lower() for name in (*NATURAL_SKILLS, 'task-workflow')) or '.agents/skills' in public or 'SKILL.md' in public:
        raise ValueError('natural public input must not name skills or their source paths')


def natural_skill_sources(skill_root, skills):
    specification = importlib.util.spec_from_file_location('delivery_policy_check', Path(__file__).with_name('check_suite.py'))
    checker = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(checker)
    result = {}
    for name in skills:
        entry = Path(skill_root) / name / 'SKILL.md'
        policy = entry.parent / 'agents' / 'openai.yaml'
        if entry.is_symlink() or policy.is_symlink():
            raise ValueError('natural skill metadata must be regular frozen files')
        result[name] = {'path': str(entry.resolve()), 'skill_sha256': digest(entry),
                        'policy_path': str(policy.resolve()), 'policy_sha256': digest(policy) if policy.exists() else None,
                        'implicit_policy': checker.implicit_policy(policy)}
    return result


def build_prompt(case, prompt):
    validate_natural_input(case, prompt)
    environment = 'Evaluator environment: the pre-existing .evaluation-state/, .evaluation-log/, .evaluation-tmp/, .evaluation-output/ directories are evaluator-owned derived execution facilities. They may be explicitly excluded from product change monitoring and commits by these exact paths; do not broadly exclude business code, requirements, professional artifacts or unknown configuration.\nThis is an isolated evaluation fixture. Work only within the current workspace. '
    if activation(case) == 'natural':
        public = environment + 'Do not read skill source contents outside the current workspace, external repositories, evaluation metadata or private scoring materials. Do not push or contact other people.\n\n' + prompt
    else:
        paths = '\n'.join(f"- .agents/skills/{name}/SKILL.md" for name in case['skills'])
        public = environment + 'Read the explicitly supplied frozen skill(s):\n' + paths + '\nDo not search installed skills, external repositories, evaluation metadata or private scoring materials. Do not push or contact other people. Standalone requests must not invoke other skills or auto-start a workflow.\n\n' + prompt
    public += '\n\nPublic acceptance requirements:\n' + '\n'.join('- ' + str(item) for item in case.get('requirements', []))
    public += '\nAllowed changes:\n' + '\n'.join('- ' + str(item) for item in case.get('allowed_changes', []))
    return public


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def inventory(root, exclude_top=()):
    root = Path(root)
    result = {}
    for p in sorted(root.rglob('*')):
        if p.relative_to(root).parts[0] in exclude_top or '.git' in p.relative_to(root).parts or '__pycache__' in p.parts:
            continue
        if p.is_symlink():
            result[str(p.relative_to(root))] = {'symlink': os.readlink(p)}
        elif p.is_file():
            result[str(p.relative_to(root))] = {'sha256': digest(p), 'bytes': p.stat().st_size}
    return result


def confined(root, relative):
    p = (Path(root) / relative).resolve()
    if not p.is_relative_to(Path(root).resolve()):
        raise ValueError(f'path escapes fixture: {relative}')
    return p


def copy_tree(source, target, *, skill=False, exclude_top=()):
    source = Path(source).resolve()
    if not source.is_dir():
        raise ValueError(f'missing source directory: {source}')
    # Evaluation oracles and repository metadata never become agent inputs.
    for p in source.rglob('*'):
        if p.relative_to(source).parts[0] in exclude_top:
            continue
        if p.is_symlink():
            raise ValueError(f'symlink in fixture/source must be resolved explicitly: {p}')
    ignores = shutil.ignore_patterns('.git', '__pycache__', '*.pyc', 'tests') if skill else shutil.ignore_patterns('.git', '__pycache__', '*.pyc')
    def selected_ignores(directory, names):
        return set(ignores(directory, names)) | (set(exclude_top) & set(names) if Path(directory).resolve() == source else set())
    shutil.copytree(source, target, ignore=selected_ignores)


def collect_artifacts(source, target, *, exclude_top=()):
    """Copy regular products without following links; return raw link metadata.

    Agent inputs remain subject to copy_tree's stricter no-symlink policy.
    Output links may be valid, dangling, cyclic or external: none is resolved
    or recreated in the artifact tree, so opening evidence cannot escape it.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.is_relative_to(source):
        raise ValueError('artifact destination must be outside source workspace')
    target.mkdir(parents=True, exist_ok=False)
    links = {}
    for directory, names, files, directory_fd in os.fwalk(source, follow_symlinks=False):
        relative = Path(directory).relative_to(source)
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        selected = []
        for name in sorted(names + files):
            if name in ('.git', '__pycache__') or fnmatch.fnmatch(name, '*.pyc') or (relative == Path('.') and name in exclude_top):
                continue
            product = relative / name
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                links[str(product)] = os.readlink(name, dir_fd=directory_fd)
            elif stat.S_ISDIR(info.st_mode):
                selected.append(name)
            elif stat.S_ISREG(info.st_mode):
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                with os.fdopen(descriptor, 'rb') as original:
                    actual = os.fstat(original.fileno())
                    if not stat.S_ISREG(actual.st_mode):
                        raise ValueError(f'product changed type during collection: {product}')
                    with (destination / name).open('xb') as copied:
                        shutil.copyfileobj(original, copied)
                os.chmod(destination / name, stat.S_IMODE(actual.st_mode))
                os.utime(destination / name, ns=(actual.st_atime_ns, actual.st_mtime_ns))
            else:
                raise ValueError(f'unsupported artifact file type: {product}')
        names[:] = selected
    return links


def normalize_behavior_case(row):
    """Separate heterogeneous public requests from private evaluation answers."""
    prompt = row.get('prompt', row.get('request'))
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('behavior case requires a nonempty prompt or request')
    public = {'id': row['id'], 'prompt': prompt}
    private = {'id': row['id'], 'expected': row.get('expected', row.get('expectations', [])), 'forbidden': row.get('forbidden', row.get('prohibited', []))}
    # A free-form fixture field can describe injected defects. It is not public
    # input: evaluators construct an ordinary project, not expose this annotation.
    if 'fixture' in row:
        private['fixture_annotation'] = row['fixture']
    return public, private


def prepare(case_path, skills_root, output, variant):
    case_path = Path(case_path).resolve()
    case = load(case_path)
    if case.get('schema_version') != SCHEMA or not isinstance(case.get('prompt'), str):
        raise ValueError('case requires schema_version=1 and public prompt')
    if case.get('mode') not in ('standalone', 'fullflow', 'resume', 'negative'):
        raise ValueError('unsupported mode')
    skills = case.get('skills', [])
    selected_activation = activation(case)
    validate_natural_input(case)
    if selected_activation == 'explicit' and case['mode'] == 'standalone' and (len(skills) != 1 or skills[0] not in PROFESSIONAL_SKILLS):
        raise ValueError('standalone requires exactly one professional skill')
    if not skills or any(s not in (*SKILLS, *PROFESSIONAL_SKILLS, 'task-workflow') for s in skills):
        raise ValueError('unsupported skill selection')
    if selected_activation == 'natural':
        natural_skill_sources(skills_root, skills)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('output already exists; use a fresh evaluation directory')
    fixture_source = confined(case_path.parent, case['fixture'])
    output.mkdir(parents=True)
    workspace = Path(tempfile.mkdtemp(prefix='delivery-eval-work-'))
    workspace.rmdir()
    copy_tree(fixture_source, workspace)
    skill_root = workspace / '.agents' / 'skills'
    skill_root.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name in skills:
        source = Path(skills_root).resolve() / name
        copy_tree(source, skill_root / name, skill=True)
        if not (skill_root / name / 'SKILL.md').is_file():
            raise ValueError(f'missing SKILL.md: {name}')
        sources[name] = {'source': str(source), 'loaded_snapshot': inventory(skill_root / name), 'excluded': ['tests/', '.git/', '__pycache__/', '*.pyc']}
    for name in EVALUATOR_DIRS:
        (workspace / name).mkdir(exist_ok=True)
    if case.get('git', False):
        subprocess.run(['git', 'init', '-q', str(workspace)], check=True, capture_output=True)
        (workspace / '.git' / 'info' / 'exclude').write_text(''.join('/' + name + '/\n' for name in EVALUATOR_DIRS))
    if case['mode'] == 'standalone' and ((workspace / '.git').exists() or (workspace / '.workflow').exists()):
        raise ValueError('standalone fixture must have no Git or .workflow')
    if selected_activation == 'natural':
        natural_skill_sources(skill_root, skills)
    public = {k: case[k] for k in ('schema_version', 'id', 'mode', 'activation', 'skills', 'prompt', 'requirements', 'allowed_changes') if k in case}
    save(output / 'case.json', public)
    save(output / 'sources.json', sources)
    save(output / 'before.json', inventory(workspace, EVALUATOR_DIRS))
    write_result(output, {'schema_version': SCHEMA, 'id': str(uuid.uuid4()), 'case_id': case['id'], 'variant': variant, 'activation': selected_activation, 'status': 'prepared', 'workspace': str(workspace), 'case_sha256': digest(case_path), 'source_policy': 'frozen professional inputs; maintenance tests excluded', 'evaluator_derived_directories': list(EVALUATOR_DIRS), 'product_snapshot_excludes': list(EVALUATOR_DIRS), 'runs': []})
    return output


def configured_model(home):
    config_path = Path(home) / 'config.toml'
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    if config.get('model_provider') not in (None, 'openai') or config.get('profile'):
        raise ValueError('custom provider/profile needs an explicitly reviewed adapter; no silent model substitution')
    return {k: config[k] for k in ('model', 'model_reasoning_effort') if k in config}


def parse_events(path):
    events, malformed = [], []
    for i, line in enumerate(Path(path).read_text(errors='replace').splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            malformed.append(i)
    return events, malformed


def markdown(result):
    lines = ['# Agent evaluation', '', f"Case: `{result['case_id']}` · Variant: `{result['variant']}` · Activation: `{result.get('activation', 'explicit')}`", '', f"Execution: **{result['status']}**", '', 'Execution completion does not establish semantic acceptance. An independent review of actual artifacts is required.', '']
    for run in result['runs']:
        lines += [f"## {run['id']}", '', f"- State: {run['status']}", f"- Real adapter: {run['adapter']} ({run.get('cli_version', 'unavailable')})", f"- Model configuration: `{json.dumps(run.get('model_config', {}), ensure_ascii=False)}`", f"- Elapsed: {run.get('seconds', 0):.2f}s", f"- Evidence: `runs/{run['id']}/`", f"- Product snapshot exclusions: `{json.dumps(run.get('product_snapshot_excludes', []))}`", f"- Isolation: {run.get('isolation', 'not established')}", f"- Configuration policy: {run.get('config_policy', 'not established; CLI not yet started')}", f"- Temporary-file routing: `{json.dumps(run.get('temporary_environment', {}))}`", f"- CLI runtime write exceptions: `{json.dumps((run.get('external_isolation') or {}).get('policy', {}).get('exact_cli_state_write_exceptions', []))}`", f"- Reason: {run.get('reason', '')}", '']
    review = result.get('review')
    if review:
        lines += ['## Independent review', '', f"Reviewer: `{review['reviewer']}`; verdict: **{review['verdict']}**", '', review['summary'], '']
    else:
        lines += ['## Independent review', '', 'Pending. No semantic quality verdict has been recorded.', '']
    lines += ['## Limits', '', 'Configuration and isolation are reported per actual run above and in its raw request/policy records. Frozen input copies do not by themselves hide a global skill catalog; tool traces must establish which source contents were read. OS isolation is only claimed for the tested canaries and recorded profile; no network-isolation claim is made. Execution completion, model quality, independence and evidence sufficiency are separate conclusions.', '']
    return '\n'.join(lines)


def write_result(output, result):
    save(Path(output) / 'evaluation.json', result)
    (Path(output) / 'report.md').write_text(markdown(result))


def run(output, cli='codex', timeout=900, prompt_file=None, required_isolation='directory', external_isolation=None, private_dir=None, deny_read_dirs=(), expected_cli_version=None, sandbox_strategy='workspace-write'):
    output = Path(output).resolve()
    result = load(output / 'evaluation.json')
    if sandbox_strategy not in ('workspace-write', 'external-seatbelt'):
        raise ValueError('unknown sandbox strategy; no implicit fallback')
    if timeout <= 0:
        raise ValueError('timeout must be positive')
    case = load(output / 'case.json')
    run_id = f"{len(result['runs']) + 1:03d}"
    run_root = output / 'runs' / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    record = {'id': run_id, 'adapter': 'codex-app-server-external-seatbelt' if sandbox_strategy == 'external-seatbelt' else 'codex-exec', 'status': 'not-run', 'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'isolation': 'directory separation; inherited CLI environment; no OS read confinement', 'environment': {'python': sys.version.split()[0], 'platform': platform.platform()}, 'required_isolation': required_isolation, 'sandbox_strategy': sandbox_strategy, 'config_policy': 'not established; CLI not yet started'}
    started = time.monotonic()
    executable = shutil.which(cli)
    try:
        record['activation'] = activation(case)
        if record['activation'] == 'natural':
            validate_natural_input(case)
            if prompt_file:
                raise ValueError('natural activation rejects prompt-file overrides; prepare a separate public continuation case')
            if sandbox_strategy != 'external-seatbelt' or required_isolation != 'filesystem':
                raise ValueError('natural activation requires external-seatbelt and filesystem isolation with pre-turn catalog audit')
            snapshots = load(output / 'sources.json')
            for name in case['skills']:
                if snapshots.get(name, {}).get('loaded_snapshot') != inventory(Path(result['workspace']) / '.agents' / 'skills' / name):
                    raise ValueError('natural frozen skill snapshot changed since prepare: ' + name)
            record['natural_skill_sources'] = natural_skill_sources(Path(result['workspace']) / '.agents' / 'skills', case['skills'])
        if required_isolation == 'filesystem' and not (private_dir or deny_read_dirs):
            record['status'] = 'invalid-isolation'
            record['reason'] = 'required OS deny-private isolation was not configured; agent not started'
            return record
        if not executable:
            record['reason'] = 'requested real CLI not installed'
            return record
        record['cli_path'] = executable
        record['harness_sources'] = {}
        for source in (Path(__file__), Path(__file__).with_name('external_seatbelt.py'), Path(__file__).with_name('check_suite.py')):
            if source.is_file():
                target = run_root / 'harness-source' / source.name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source, target)
                record['harness_sources'][source.name] = {'sha256': digest(target), 'evidence': str(target.relative_to(output))}
        version = subprocess.run([executable, '--version'], text=True, capture_output=True, timeout=15)
        record['cli_version'] = version.stdout.strip()
        if expected_cli_version and record['cli_version'] != expected_cli_version:
            record['status'] = 'invalid-version'
            record['reason'] = 'actual CLI version differs from frozen comparison requirement; agent not started'
            return record
        if version.returncode:
            record['reason'] = 'CLI version probe failed'
            return record
        wrapper = []
        if (private_dir or deny_read_dirs) and sandbox_strategy == 'workspace-write':
            private = Path(private_dir or deny_read_dirs[0]).resolve(strict=True)
            workspace = Path(result['workspace']).resolve()
            if not private.is_dir() or private.is_relative_to(workspace) or workspace.is_relative_to(private):
                raise ValueError('private oracle directory must be separate from workspace')
            sandbox_cli = shutil.which('sandbox-exec')
            if not sandbox_cli:
                record['reason'] = 'macOS sandbox-exec unavailable; required private-directory isolation not established'
                return record
            denied = [Path(p).resolve(strict=True) for p in ([private] + list(deny_read_dirs))]
            if any(workspace.is_relative_to(p) or p.is_relative_to(workspace) for p in denied):
                raise ValueError('denied source/oracle directories must not contain the isolated workspace')
            profile = '(version 1)\n(allow default)\n' + ''.join('(deny file-read* (subpath ' + json.dumps(str(p)) + '))\n' for p in denied)
            (run_root / 'private-read-deny.sb').write_text(profile)
            canary = private / ('.isolation-canary-' + uuid.uuid4().hex)
            try:
                canary.write_text('delivery-evaluation-private-read-canary\n')
                readable = canary.read_text()
                probe = subprocess.run([sandbox_cli, '-p', profile, '/bin/cat', str(canary)], text=True, capture_output=True, timeout=15)
                isolation_ok = bool(readable) and probe.returncode != 0 and 'Operation not permitted' in probe.stderr and not probe.stdout
                isolation_evidence = {'kind': 'macos-deny-private', 'private_directory': str(private), 'denied_directories': [str(p) for p in denied], 'profile_sha256': digest(run_root / 'private-read-deny.sb'), 'canary_exit': probe.returncode, 'canary_stdout': probe.stdout, 'canary_stderr': probe.stderr, 'passed': isolation_ok}
                save(run_root / 'isolation.json', isolation_evidence)
            finally:
                canary.unlink(missing_ok=True)
            if not isolation_ok:
                record['reason'] = 'private read canary did not establish deny profile; agent not started'
                return record
            wrapper = [sandbox_cli, '-p', profile]
            external_isolation = isolation_evidence
            record['isolation'] = 'macOS inherited deny-private read profile + Codex workspace-write; canary verified before execution'
        original_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        adapter = None
        if sandbox_strategy == 'external-seatbelt':
            if not (private_dir or deny_read_dirs):
                raise ValueError('external-seatbelt requires explicit denied private/source directories')
            specification = importlib.util.spec_from_file_location('delivery_external_seatbelt', Path(__file__).with_name('external_seatbelt.py'))
            adapter = importlib.util.module_from_spec(specification)
            specification.loader.exec_module(adapter)
            denied = ([private_dir] if private_dir else []) + list(deny_read_dirs)
            wrapper, external_isolation = adapter.probe_boundary(result['workspace'], denied, original_home, run_root)
            record['isolation'] = 'single inherited macOS read/write seatbelt; base + actual historical-state canaries passed; prior fixture state denied except fresh current run; exact existing installation_id write-open exception; app-server externalSandbox'
            record['protocol'] = adapter.inspect_protocol(executable, run_root, require_skills=record['activation'] == 'natural')
        model_config = configured_model(original_home)
        record['model_config'] = model_config
        record['model_config_source'] = 'allowlisted actual CLI configuration; explicit command overrides' if model_config else 'CLI built-in default; actual model must be confirmed from trace before comparison'
        prompt = Path(prompt_file).read_text() if prompt_file else case['prompt']
        prompt = build_prompt(case, prompt)
        if adapter:
            interface_note = ('This app-server provides native multi_agent/spawn_agent for fresh independent contexts. '
                              'Use those native tools when independent execution is required. Do not launch another Codex CLI: '
                              'that would reload global configuration/MCP and attempt another sandbox layer. '
                              'This environment restriction supersedes any older optional suggestion to invoke a nested Codex CLI. '
                              'If native independent tools are unavailable, preserve pending review for external scheduling; '
                              'do not bypass approvals, reopen external tools or replace independence with a renamed identity.')
            prompt = 'Controlled independent-context interface: ' + interface_note + '\n\n' + prompt
            record['independent_context_interface'] = 'native multi_agent/spawn_agent; no nested Codex CLI; unavailable means pending external scheduling'
        (run_root / 'prompt.txt').write_text(prompt)
        for name in EVALUATOR_DIRS:
            (Path(result['workspace']) / name).mkdir(exist_ok=True)
        record['evaluator_derived_directories'] = list(EVALUATOR_DIRS)
        record['product_snapshot_excludes'] = list(EVALUATOR_DIRS)
        before = inventory(result['workspace'], EVALUATOR_DIRS)
        save(run_root / 'before.json', before)
        if adapter:
            options = {'expected_skills': record['natural_skill_sources']} if record['activation'] == 'natural' else {}
            outcome = adapter.execute(executable, wrapper, result['workspace'], prompt, model_config, run_root, timeout, **options)
            protection = adapter.verify_protection(external_isolation)
            save(run_root / 'protected-files.json', protection)
            record['protected_files'] = protection
            if not protection['unchanged']:
                outcome['status'] = 'invalid-protection'
                outcome['reason'] = 'installation identity/auth/config contents or metadata changed; execution cannot count as valid quality evidence'
            record.update({key: outcome[key] for key in ('status', 'reason', 'returncode', 'argv', 'sandbox_policy', 'environment_keys_changed', 'config_policy', 'actual_config_sha256', 'configured_mcp_servers_disabled', 'mcp_runtime_inventory', 'runtime_state', 'root_thread_id', 'root_turn_id', 'disabled_features', 'temporary_environment', 'startup_state_audit', 'skill_catalog_audit') if key in outcome})
            record['adapter'] = 'codex-app-server-external-seatbelt'
            save(run_root / 'request.json', {'argv': outcome['argv'], 'environment_keys_changed': outcome['environment_keys_changed'], 'temporary_environment': outcome['temporary_environment'], 'model_config': model_config, 'prompt_file': 'prompt.txt', 'sandbox_policy': outcome['sandbox_policy']})
            agent_last = run_root / 'last-message.txt'
        else:
            record['config_policy'] = 'exec ignores user config; actual model/reasoning explicitly supplied; existing authentication retained'
            argv = wrapper + [executable, 'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config', '--sandbox', 'workspace-write', '-c', 'approval_policy="never"', '--json', '--color', 'never', '--cd', result['workspace'], '--output-last-message', str(run_root / 'last-message.txt'), '-']
            for key, value in model_config.items():
                argv[-1:-1] = ['-c', f'{key}={json.dumps(value)}']
            agent_last = Path(result['workspace']) / '.evaluation-output' / ('last-message-' + run_id + '.txt')
            argv[argv.index('--output-last-message') + 1] = str(agent_last)
            record['argv'] = argv
            save(run_root / 'request.json', {'argv': argv, 'environment_keys_changed': [], 'model_config': model_config, 'prompt_file': 'prompt.txt'})
            with (run_root / 'events.jsonl').open('wb') as stdout, (run_root / 'stderr.txt').open('wb') as stderr:
                process = subprocess.Popen(argv, cwd=result['workspace'], stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, start_new_session=True)
                try:
                    process.communicate(prompt.encode(), timeout=timeout)
                    record['returncode'] = process.returncode
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                    record['status'] = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'interrupted'
                    record['reason'] = 'execution terminated; no semantic approval or implicit retry'
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    record['returncode'] = process.returncode
        events, malformed = parse_events(run_root / 'events.jsonl')
        record['event_count'] = len(events)
        record['malformed_jsonl_lines'] = malformed
        record['usage'] = [e.get('usage') for e in events if isinstance(e, dict) and e.get('usage')]
        record['session_ids'] = [e.get('thread_id') for e in events if isinstance(e, dict) and e.get('thread_id')]
        if agent_last.exists() and agent_last != run_root / 'last-message.txt':
            shutil.copy2(agent_last, run_root / 'last-message.txt')
        final = run_root / 'last-message.txt'
        if record['status'] not in ('timeout', 'interrupted', 'execution-failed', 'invalid-protection'):
            completed = any(isinstance(e, dict) and e.get('type') == 'turn.completed' for e in events)
            failed = any(isinstance(e, dict) and e.get('type') in ('turn.failed', 'error') for e in events)
            record['status'] = 'executed' if (record['returncode'] == 0 or (adapter and record['status'] == 'executed')) and completed and not failed and not malformed and final.exists() and final.read_text().strip() else ('not-run' if not events else 'execution-failed')
            record['reason'] = 'awaiting independent artifact review' if record['status'] == 'executed' else 'CLI did not produce a valid completed model turn; inspect raw outputs'
        record['external_isolation'] = external_isolation
        if required_isolation == 'filesystem' and not (external_isolation and external_isolation.get('kind') in ('macos-deny-private', 'macos-single-external-seatbelt') and external_isolation.get('passed')):
            record['status'] = 'invalid-isolation'
            record['reason'] = 'requested filesystem read isolation was not externally established; run cannot prove autonomous discovery'
        artifact_copy = run_root / 'artifacts'
        links = collect_artifacts(result['workspace'], artifact_copy, exclude_top=EVALUATOR_DIRS)
        save(run_root / 'artifact-symlinks.json', {'schema_version': 1, 'policy': 'regular files copied; symlinks recorded verbatim without resolving, following or recreating targets', 'links': links})
        record['artifact_symlinks'] = str((run_root / 'artifact-symlinks.json').relative_to(output))
        save(run_root / 'after.json', inventory(result['workspace'], EVALUATOR_DIRS))
        after = inventory(result['workspace'], EVALUATOR_DIRS)
        record['changes'] = {p: {'before': before.get(p), 'after': after.get(p)} for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)}
        if (Path(result['workspace']) / '.git').exists():
            git_state = {}
            for name, arguments in [('status', ['status', '--porcelain=v1']), ('head', ['rev-parse', 'HEAD']), ('commits', ['log', '-10', '--format=%H %s'])]:
                git_result = subprocess.run(['git', '-C', result['workspace']] + arguments, text=True, capture_output=True, timeout=15)
                git_state[name] = {'returncode': git_result.returncode, 'stdout': git_result.stdout, 'stderr': git_result.stderr}
            save(run_root / 'git-state.json', git_state)
        record['artifacts'] = inventory(run_root)
        return record
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if record['status'] == 'executed':
            record['status'] = 'evidence-failed'
        record['reason'] = f'{type(error).__name__}: {error}'
        return record
    finally:
        record['seconds'] = time.monotonic() - started
        result['runs'].append(record)
        result['status'] = record['status']
        result.pop('review', None)  # An additional run invalidates the previous artifact review.
        (output / 'independent-review.json').unlink(missing_ok=True)
        write_result(output, result)


def review(output, review_path):
    output = Path(output).resolve()
    result = load(output / 'evaluation.json')
    value = load(review_path)
    for field in ('reviewer', 'author_identities', 'verdict', 'summary', 'evidence', 'run_id', 'artifact_inventory_sha256', 'leakage_audit'):
        if field not in value:
            raise ValueError(f'missing review field: {field}')
    if value['reviewer'] in value['author_identities'] or not value['reviewer'] or not value['author_identities']:
        raise ValueError('reviewer must be a real independent identity; author identities required')
    latest = result['runs'][-1] if result['runs'] else None
    if not latest or latest['status'] != 'executed' or value['run_id'] != latest['id']:
        raise ValueError('review must bind the latest successfully executed real-agent run')
    if value['verdict'] not in ('pass', 'fail', 'inconclusive') or not value['evidence']:
        raise ValueError('review needs valid verdict and actual evidence')
    after = output / 'runs' / latest['id'] / 'after.json'
    if value['artifact_inventory_sha256'] != digest(after) or load(after) != inventory(result['workspace'], latest.get('product_snapshot_excludes', ())):
        raise ValueError('artifact version changed since execution or review binding is wrong')
    if value['leakage_audit'] not in ('no-leak-observed', 'leaked', 'not-established'):
        raise ValueError('invalid leakage audit')
    if value['verdict'] == 'pass' and value['leakage_audit'] != 'no-leak-observed':
        raise ValueError('leaked or unaudited execution cannot pass')
    evidence_versions = {}
    for reference in value['evidence']:
        if not isinstance(reference, str):
            raise ValueError('review evidence must name actual relative files')
        source = confined(output, reference)
        if not source.is_file():
            raise ValueError(f'missing review evidence: {reference}')
        evidence_versions[reference] = digest(source)
    value['evidence_versions'] = evidence_versions
    history = output / 'reviews'
    history.mkdir(exist_ok=True)
    numbers = [int(p.stem[8:]) for p in history.glob('history-*.json') if p.stem[8:].isdigit()]
    accepted = history / f'history-{max(numbers, default=0) + 1:03}.json'
    archive = {'schema_version': 1, 'accepted_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'evaluation_id': result['id'], 'case_id': result['case_id'], 'review': value}
    with accepted.open('x') as handle:
        handle.write(json.dumps(archive, ensure_ascii=False, indent=2) + '\n')
    result['review'] = value
    result['status'] = {'pass': 'reviewed-pass', 'fail': 'reviewed-fail', 'inconclusive': 'review-inconclusive'}[value['verdict']]
    save(output / 'independent-review.json', value)
    write_result(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    prep = subs.add_parser('prepare', help='freeze one public case and exactly its declared skills; activation defaults to explicit')
    prep.add_argument('--case', required=True)
    prep.add_argument('--skills-root', required=True)
    prep.add_argument('--output', required=True)
    prep.add_argument('--variant', choices=['legacy', 'baseline', 'candidate'], required=True)
    execute = subs.add_parser('run', help='execute a real Codex turn; file-based resume is a new run')
    execute.add_argument('--output', required=True)
    execute.add_argument('--cli', default='codex')
    execute.add_argument('--sandbox-strategy', choices=['workspace-write', 'external-seatbelt'], default='workspace-write', help='explicit strategy; external-seatbelt is never an automatic fallback')
    execute.add_argument('--timeout', type=int, default=900)
    execute.add_argument('--expected-cli-version', help='exact frozen CLI version for comparison; mismatch prevents execution')
    execute.add_argument('--prompt-file')
    execute.add_argument('--required-isolation', choices=['directory', 'filesystem'], default='directory')
    execute.add_argument('--deny-read-dir', action='append', default=[], help='additional live repository or alternate source directory denied to Codex')
    execute.add_argument('--private-dir', help='private oracle directory denied to the entire Codex process tree; macOS sandbox-exec + canary')
    judge = subs.add_parser('review', help='bind a separately produced independent review to actual artifacts')
    judge.add_argument('--output', required=True)
    judge.add_argument('--review', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepared = prepare(args.case, args.skills_root, args.output, args.variant)
            print(json.dumps({'status': 'prepared', 'output': str(prepared)}))
        elif args.command == 'run':
            value = run(args.output, args.cli, args.timeout, args.prompt_file, args.required_isolation, None, args.private_dir, args.deny_read_dir, args.expected_cli_version, args.sandbox_strategy)
            summary = {key: value.get(key) for key in ('id', 'status', 'reason', 'seconds')}
            summary['output'] = str(Path(args.output).resolve())
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if value['status'] == 'executed' else 2
        else:
            value = review(args.output, args.review)
            print(json.dumps({'status': value['status']}))
            return 0 if value['status'] == 'reviewed-pass' else 2
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({'status': 'invalid-input', 'reason': str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
