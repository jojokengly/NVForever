#!/usr/bin/env python3
"""Finite fork-only public-source headless pair. No game launcher is invoked."""
import sys
if not __debug__:
    raise RuntimeError('optimized Python is not an admitted controller')
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import traceback


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def git(repo, *args):
    return subprocess.check_output(['git', '--no-optional-locks', '-C', str(repo), *args])


def tree(repo, commit):
    result = {}
    for row in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not row:
            continue
        metadata, rawpath = row.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        require(kind == 'blob', 'unexpected submodule/non-blob in source map')
        result[rawpath.decode()] = {'mode': mode, 'blob': oid}
    return result


def validate_commit_pins(plan):
    for key in ['baseline', 'baselineTree', 'candidate', 'candidateTree',
                'candidateMerge', 'candidateMergeTree', 'currentMain',
                'priorPublicHead', 'priorCorrection']:
        require(isinstance(plan.get(key), str) and re.fullmatch(r'[0-9a-f]{40}', plan[key]),
                'missing/invalid actual commit or tree pin: ' + key)
    require(plan['baselineParents'] == [plan['priorPublicHead'], plan['currentMain']], 'wrong baseline parent contract')
    require(plan['candidateMergeParents'] == [plan['priorCorrection'], plan['currentMain']], 'wrong candidate merge contract')
    require(plan['candidateParents'] == [plan['candidateMerge']], 'wrong candidate leaf contract')


def validate_dag(repo, plan):
    validate_commit_pins(plan)
    records = {}
    for label, commit, expected_parents, expected_tree in [
        ('baseline', plan['baseline'], plan['baselineParents'], plan['baselineTree']),
        ('candidateMerge', plan['candidateMerge'], plan['candidateMergeParents'], plan['candidateMergeTree']),
        ('candidate', plan['candidate'], plan['candidateParents'], plan['candidateTree']),
    ]:
        parents = git(repo, 'show', '-s', '--format=%P', commit).decode().strip().split()
        actual_tree = git(repo, 'rev-parse', commit + '^{tree}').decode().strip()
        require(parents == expected_parents and actual_tree == expected_tree, 'actual DAG/tree mismatch: ' + label)
        records[label] = {'commit': commit, 'tree': actual_tree, 'parents': parents}
    require(git(repo, 'show', '-s', '--format=%P', plan['priorCorrection']).decode().strip().split()
            == [plan['priorPublicHead']], 'prior correction lost public705 parent')
    for ancestor, descendant in [(plan['priorCorrection'], plan['candidate']),
                                 (plan['currentMain'], plan['candidate']),
                                 (plan['currentMain'], plan['baseline']),
                                 (plan['priorPublicHead'], plan['baseline']),
                                 (plan['candidate'], 'HEAD')]:
        git(repo, 'merge-base', '--is-ancestor', ancestor, descendant)
    baseline_ref = 'refs/remotes/origin/' + plan['baselineBranch']
    require(git(repo, 'rev-parse', baseline_ref).decode().strip() == plan['baseline'], 'reviewed baseline fork ref drift')
    changed = git(repo, 'diff-tree', '--no-commit-id', '--name-only', '-r',
                  plan['candidateMerge'], plan['candidate']).decode().splitlines()
    require(changed == [plan['fixturePath']], 'candidate leaf changes more than the original fixture closure')
    require(sha(git(repo, 'show', plan['candidateMerge'] + ':' + plan['fixturePath']))
            == plan['candidateMergeFixtureSHA256'], 'pre-fix merge fixture source drift')
    require(sha(git(repo, 'show', plan['candidate'] + ':' + plan['fixturePath']))
            == plan['fixtureSHA256'], 'corrected fixture source drift')
    return records


def seal(repo, expected):
    result = {'head': git(repo, 'rev-parse', 'HEAD').decode().strip(),
              'tree': git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip(),
              'indexRawSHA256': sha(Path(git(repo, 'rev-parse', '--git-path', 'index').decode().strip()).read_bytes()),
              'indexEntriesSHA256': sha(git(repo, 'ls-files', '--stage', '-z')),
              'files': {}}
    tracked = {x.decode() for x in git(repo, 'ls-files', '-z').split(b'\0') if x}
    require(tracked == set(expected), 'tracked source inventory changed')
    for name, metadata in sorted(expected.items()):
        path = repo / name
        require(not path.is_symlink() and path.is_file(), 'source missing/symlink: ' + name)
        data = path.read_bytes()
        require(blob(data) == metadata['blob'], 'source bytes differ from admitted Git blob: ' + name)
        require(bool(path.stat().st_mode & 0o111) == (metadata['mode'] == '100755'), 'source mode differs: ' + name)
        result['files'][name] = {'SHA256': sha(data), 'bytes': len(data), 'mode': metadata['mode']}
    require(not git(repo, 'ls-files', '--others', '--exclude-standard').strip(), 'unexpected untracked source')
    return result


def resources():
    available = None
    for row in Path('/proc/meminfo').read_text().splitlines():
        if row.startswith('MemAvailable:'):
            available = int(row.split()[1]) * 1024
    return {'UTC': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'availableMemoryBytes': available, 'diskFreeBytes': shutil.disk_usage(os.environ['RUNNER_TEMP']).free}


def run_command(argv, cwd, stem, timeout, env, deadline):
    require(time.monotonic() < deadline, 'controller deadline before command')
    initial = resources()
    require(initial['availableMemoryBytes'] >= 4 * 1024**3, 'RAM admission floor4GiB')
    require(initial['diskFreeBytes'] >= 2 * 1024**3, 'disk admission floor2GiB')
    start = time.monotonic()
    reason = None
    with stem.with_suffix('.stdout').open('wb') as stdout, stem.with_suffix('.stderr').open('wb') as stderr:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        pid = proc.pid
        minimum = initial['availableMemoryBytes']
        try:
            while proc.poll() is None:
                sample = resources()
                minimum = min(minimum, sample['availableMemoryBytes'])
                if time.monotonic() - start > timeout or time.monotonic() > deadline:
                    reason = 'TIMEOUT'
                elif sample['availableMemoryBytes'] < 2 * 1024**3:
                    reason = 'RAM_FLOOR2GiB'
                elif sample['diskFreeBytes'] < 512 * 1024**2:
                    reason = 'DISK_FLOOR512MiB'
                if reason:
                    break
                time.sleep(1)
        finally:
            if proc.poll() is None:
                # Only this controller-created process group is signalled.
                try:
                    os.killpg(pid, signal.SIGTERM)
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        code = proc.wait()
        group_drained = True
        try:
            os.killpg(pid, 0)
            # A controller-owned child outliving its command is not an admitted
            # success. Drain that same newly-created group, never other jobs.
            group_drained = False
            os.killpg(pid, signal.SIGKILL)
            reason = reason or 'OWNED_DESCENDANT_OUTLIVED_COMMAND'
        except ProcessLookupError:
            pass
    row = {'argv': argv, 'cwd': str(cwd), 'PID': pid, 'exitCode': code,
           'seconds': time.monotonic() - start, 'termination': reason, 'ownedGroupDrainedNormally': group_drained,
           'startResources': initial, 'minimumAvailableMemoryBytes': minimum,
           'stdoutSHA256': sha(stem.with_suffix('.stdout').read_bytes()),
           'stderrSHA256': sha(stem.with_suffix('.stderr').read_bytes())}
    write(stem.with_suffix('.json'), row)
    require(reason is None, 'owned process terminated: ' + str(reason))
    return row


def parse_case(text, code, name, expected_filter):
    summaries = re.findall(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', text)
    require(len(summaries) == 1, 'missing/duplicate test summary: ' + name)
    status, passed, failed, ignored, measured, filtered = summaries[0]
    counts = list(map(int, (passed, failed, ignored, measured, filtered)))
    require(counts[0] + counts[1] == 1 and counts[2:4] == [0, 0] and counts[4] == expected_filter,
            'wrong exact harness census: ' + name)
    require(re.search(r'^running 1 test$', text, re.M), 'wrong exact test selection')
    rows = re.findall(r'^test ' + re.escape(name) + r' \.\.\. (ok|FAILED)$', text, re.M)
    require(len(rows) == 1, 'missing/duplicate exact named result')
    require((code == 0 and counts[:2] == [1, 0] and status == 'ok' and rows == ['ok']) or
            (code == 101 and counts[:2] == [0, 1] and status == 'FAILED' and rows == ['FAILED']),
            'exit/result disagreement or non-assertion process failure')
    first = text.find('panicked at')
    return {'status': 'PASS' if code == 0 else 'FAIL', 'census': counts,
            'firstFailureExcerpt': text[max(0, first - 150):first + 1800] if first >= 0 else None,
            'laterAssertions': 'UNRUN_AFTER_FIRST_FAILURE' if code else 'COMPLETED'}


def classify_baseline(index, row, text):
    if index == 0:
        require(row['status'] == 'FAIL' and
                'assertion failed: game.0.scene.take_attachment_changes().is_empty()' in text,
                'first baseline boundary is not immediate side queue')
        return 'INTENDED_SIDE_QUEUE_ASSERTION_FAILURE'
    if index == 1:
        require(row['status'] == 'FAIL' and 'AttachFormModel leaked physical geometry' in text,
                'second baseline boundary is not leaked geometry after real positive/removal')
        return 'INTENDED_PHYSICAL_LEAK_ASSERTION_FAILURE'
    # Exact lock-checksummed Bevy0.20.1 remove uses warn, not panic. This is
    # a compatibility characterization, never a fabricated third regression.
    require(row['status'] == 'PASS', 'deferred cleanup baseline failed unexpectedly; classify raw before retry')
    return 'BASELINE_COMPATIBILITY_PASS_NO_PANIC_CLAIM'


def execute(plan, here, output):
    require(os.name == 'posix' and os.environ.get('GITHUB_ACTIONS') == 'true', 'fork hosted Linux only')
    require(os.environ.get('GITHUB_REPOSITORY') == plan['fork'] and
            os.environ.get('GITHUB_REF') == 'refs/heads/' + plan['qaBranch'], 'wrong fork/ref')
    require(not os.environ.get('RUSTFLAGS') and not os.environ.get('CARGO_ENCODED_RUSTFLAGS'), 'unreviewed Rust flags')
    temporary = Path(os.environ['RUNNER_TEMP']).resolve()
    require(output == temporary / 'attach2690-proof' and not output.exists(), 'output must be fresh exact owned path')
    for name, expected in plan['inputSHA256'].items():
        require(sha((here / name).read_bytes()) == expected, 'controller input drift: ' + name)
    output.mkdir()
    deadline = time.monotonic() + plan['totalSeconds']
    env = {k: v for k, v in os.environ.items() if not k.startswith(('NVF_', 'NVFOREVER_'))}
    env.update({'NVF_REPORTS': '0', 'RUST_BACKTRACE': '1', 'CARGO_BUILD_JOBS': '2',
                'CARGO_PROFILE_RELEASE_DEBUG': '0', 'CARGO_TERM_COLOR': 'never',
                'GIT_NO_LAZY_FETCH': '1', 'GIT_OPTIONAL_LOCKS': '0'})
    (output/'test-temp').mkdir()
    env.update({'TMPDIR':str(output/'test-temp'), 'TMP':str(output/'test-temp'), 'TEMP':str(output/'test-temp')})
    repo = Path(os.environ['GITHUB_WORKSPACE']).resolve()
    require(git(repo, 'remote', 'get-url', 'origin').decode().strip() in
            ['https://github.com/jojokengly/NVForever', 'https://github.com/jojokengly/NVForever.git'], 'wrong checkout remote')
    dag = validate_dag(repo, plan)
    write(output/'SOURCE-DAG.json', dag)
    original = tree(repo, plan['baseline'])
    candidate = tree(repo, plan['candidate'])
    changed = {p for p in set(original) | set(candidate) if original.get(p) != candidate.get(p)}
    require(changed == set(plan['candidateFive']), 'candidate delta not exact original five paths')
    for p, metadata in plan['candidateFive'].items():
        require(candidate[p] == metadata, 'candidate canonical map differs: ' + p)
    canonical_digest = lambda value: sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
    require(canonical_digest(original) == plan['baselineRawMapSHA256'], 'baseline full source map mismatch')
    require(canonical_digest(candidate) == plan['candidateMapSHA256'], 'candidate full source map mismatch')
    baseline_with_fixture = dict(original)
    baseline_with_fixture[plan['fixturePath']] = candidate[plan['fixturePath']]
    require(canonical_digest(baseline_with_fixture) == plan['baselineWithFixtureMapSHA256'], 'controlled baseline fixture closure mismatch')
    write(output / 'SOURCE-TREES.json', {'baseline': original, 'candidate': candidate})
    tools = run_command(['rustc', '-Vv'], repo, output/'rustc', 30, env, deadline)
    require(tools['exitCode'] == 0, 'rustc admission failed')
    require(run_command(['cargo', '-V'], repo, output/'cargo', 30, env, deadline)['exitCode'] == 0, 'cargo admission failed')
    write(output/'HOST.json', {'resources': resources(), 'runnerOS': os.environ.get('RUNNER_OS'),
          'imageOS': os.environ.get('ImageOS'), 'imageVersion': os.environ.get('ImageVersion'),
          'cpuCount': os.cpu_count(), 'platform': os.uname(), 'environment': {k:env.get(k) for k in
          ['CARGO_BUILD_JOBS','CARGO_PROFILE_RELEASE_DEBUG','CARGO_TERM_COLOR','RUST_BACKTRACE','RUSTUP_TOOLCHAIN']}})
    target = output / 'target'
    result = {'plan': plan, 'phases': [], 'sourceQualifiedOnly': True, 'complete': False,
              'independentBlockerClosure': False, 'scope': 'authored headless consumers; no game/GPU/native execution'}
    write(output/'RESULT.json', result)
    previous_exe = None
    opened_sources = []
    try:
        for side, commit in [('baseline', plan['baseline']), ('candidate', plan['candidate'])]:
            folder = output / side
            folder.mkdir()
            work = output / (side + '-source')
            git(repo, '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', str(work), commit)
            expected = dict(original if side == 'baseline' else candidate)
            if side == 'baseline':
                git(work, 'apply', '--check', str(here/'BASELINE-FIXTURE-ONLY.patch'))
                git(work, 'apply', str(here/'BASELINE-FIXTURE-ONLY.patch'))
                expected[plan['fixturePath']] = candidate[plan['fixturePath']]
            fixture = (work/plan['fixturePath']).read_bytes()
            require(sha(fixture) == plan['fixtureSHA256'], 'same complete fixture mismatch')
            before = seal(work, expected)
            write(folder/'SOURCE-BEFORE.json', before)
            opened_sources.append((work, expected, before, folder))
            if side == 'candidate':
                clean = run_command(['cargo','clean','--release','-p','nvforever','-p','fnv-game','--target-dir',str(target)],
                                    work/'engine', folder/'clean-own-packages', 120, env, deadline)
                require(clean['exitCode'] == 0, 'owned package invalidation failed')
            command = ['cargo','test','--release','--locked','-p','nvforever','--bin','nvforever','--no-run',
                       '--message-format=json','-j','2','--target-dir',str(target)]
            build = run_command(command, work/'engine', folder/'compile', plan['compileSeconds'], env, deadline)
            require(build['exitCode'] == 0, side+' compile/setup failure: zero case credit')
            messages = []
            for line in (folder/'compile.stdout').read_text(errors='replace').splitlines():
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            require(any(x.get('reason')=='build-finished' and x.get('success') is True for x in messages), 'no successful Cargo build-finished')
            artifacts = [x for x in messages if x.get('reason')=='compiler-artifact']
            hosts = [x for x in artifacts if x.get('target',{}).get('name')=='nvforever' and
                     x.get('target',{}).get('kind')==['bin'] and x.get('profile',{}).get('test') is True and x.get('executable')]
            require(len(hosts)==1 and hosts[0]['fresh'] is False, 'host artifact ambiguous/stale')
            host = hosts[0]
            require(Path(host['manifest_path']).resolve()==work/'engine/nvforever/Cargo.toml', 'host package/source mismatch')
            games = [x for x in artifacts if x.get('target',{}).get('name')=='fnv_game' and 'lib' in x.get('target',{}).get('kind',[])]
            require(len(games)==1 and games[0]['fresh'] is False and Path(games[0]['manifest_path']).resolve()==work/'crates/fnv-game/Cargo.toml', 'fnv-game source/freshness mismatch')
            write(folder/'ARTIFACTS.json', {'host':host,'fnv_game':games[0], 'all':artifacts})
            executable = folder/'nvforever-libtest'
            shutil.copy2(host['executable'], executable)
            digest = sha(executable.read_bytes())
            require(previous_exe is None or digest != previous_exe, 'candidate image identical to baseline')
            previous_exe = digest
            write(folder/'IMAGE.json', {'SHA256':digest,'sourceExecutable':host['executable'],'copiedExecutable':str(executable)})
            listed = run_command([str(executable),'--list','--format','terse'],work,folder/'list',60,env,deadline)
            require(listed['exitCode']==0, 'discovery/setup failed')
            all_names = re.findall(r'^(.+): test$', (folder/'list.stdout').read_text(), re.M)
            require(len(all_names)==len(set(all_names)), 'duplicate test discovery')
            owned = [n for n in all_names if n.startswith('nif_mirror::attachment_tests::')]
            require(set(owned)==set(plan['candidateNames']) and len(owned)==23, 'wrong owned23 discovery')
            selected = plan['baselineNames'] if side=='baseline' else plan['candidateNames']
            phase = {'side':side,'commit':commit,'executableSHA256':digest,'discovered':len(all_names),'cases':[]}
            result['phases'].append(phase)
            for index, name in enumerate(selected):
                stem = folder/('case-'+str(index+1).zfill(2))
                raw = run_command([str(executable),name,'--exact','--nocapture','--test-threads=1'],work,stem,plan['caseSeconds'],env,deadline)
                text = stem.with_suffix('.stdout').read_text(errors='replace')+'\n'+stem.with_suffix('.stderr').read_text(errors='replace')
                row = {'name':name, **parse_case(text,raw['exitCode'],name,len(all_names)-1)}
                phase['cases'].append(row)
                try:
                    if side=='baseline':
                        row['classification']=classify_baseline(index,row,text)
                    else:
                        row['classification']='ACTUAL_CANDIDATE_PASS' if row['status']=='PASS' else 'CANDIDATE_ASSERTION_FAILURE'
                except BaseException:
                    row['classification']='UNEXPECTED_BOUNDARY_REQUIRES_REVIEW'
                    raise
                finally:
                    write(output/'RESULT.json',result)
            after = seal(work,expected)
            write(folder/'SOURCE-AFTER.json',after)
            require(before==after,'source/index drift across '+side+' compile/cases')
            require(sha(executable.read_bytes())==digest,'retained image drift')
            if side=='candidate':
                require(all(x['status']=='PASS' for x in phase['cases']), 'candidate assertion failure(s); all selected rows retained')
        result['complete']=True
        result['classification']='BASELINE_TWO_INTENDED_ASSERT_FAILURES_AND_ONE_COMPATIBILITY_PASS_TO_CANDIDATE23PASS'
    except BaseException:
        result['failure']=traceback.format_exc()
        raise
    finally:
        result['finalSourceSeals'] = []
        for work, expected, before, folder in opened_sources:
            try:
                after = seal(work, expected)
                write(folder/'SOURCE-FINAL.json', after)
                result['finalSourceSeals'].append({'path':str(work),'beforeAfterExact':before==after})
                if before != after:
                    result['complete']=False
                    result['sourceIntegrityFailure']=str(work)
            except BaseException:
                result['complete']=False
                result['sourceIntegrityFailure']=traceback.format_exc()
        result['endResources']=resources()
        write(output/'RESULT.json',result)
        require(not result.get('sourceIntegrityFailure'),'postflight source/index integrity failure')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute-plan-sha256',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    raw=(here/'PLAN.json').read_bytes()
    require(sha(raw)==args.execute_plan_sha256,'plan pin mismatch')
    plan=json.loads(raw)
    validate_commit_pins(plan)
    execute(plan,here,Path(args.output).resolve())


if __name__=='__main__':
    main()
