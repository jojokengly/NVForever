"""Fork-only, identical unused-CSTY-copy SaveGame control on three public sources.

Default: prepare sources only. Execution is restricted to this fork QA branch on
Linux Actions; no game, GPU, asset download or imported build cache is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FORK = 'https://github.com/jojokengly/NVForever.git'
REF = 'refs/heads/qa/csty-unused-save-20261114'
SOURCES = [
    ('main', '805454db21c5a4388cb7ee3e1002747acefb56c8'),
    ('refusal', '1ff900f2ee35d5feb967f8692b8b6c00243b967d'),
    ('fixed', '35f69bd452ccfcf29e78180e7fcf632799ae9dc5'),
]
SAVE = 'engine/nvf-play/src/save.rs'
CASE = 'an_unused_csty_clone_created_by_savegame_still_enqueues_manual_and_auto_saves'
NAME = 'save::unused_copy_qa::' + CASE
sha = lambda b: hashlib.sha256(b).hexdigest()

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', '-C', str(cwd), *args])

def blob(commit, path):
    return git('show', commit + ':' + path)

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def ensure_commit(commit, execute):
    if subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', commit + '^{commit}'], capture_output=True).returncode:
        require(execute, 'missing source commit: ' + commit)
        subprocess.run(['git', '-C', str(ROOT), 'fetch', '--no-tags', FORK, commit], check=True)
    require(git('rev-parse', commit).decode().strip() == commit, 'full commit identity')

def fixture():
    source = blob(SOURCES[-1][1], SAVE)
    start = source.index(b'    fn csty_save_world(')
    end = source.index(b'    #[test]\n    fn an_assigned_csty_clone_', start)
    payload = source[start:end]
    require(payload.count(b'#[test]') == 1 and (b'fn ' + CASE.encode() + b'()') in payload, 'one exact authored unused-copy case')
    require(b'ensure_combat_style_snapshot_supported' not in payload, 'fixture must not invoke refusal/new production API')
    return b'\n#[cfg(test)]\nmod unused_copy_qa {\n    use super::*;\n\n' + payload + b'}\n'

def fingerprint(source):
    rows = {}
    for row in git('ls-tree', '-r', '-z', 'HEAD', cwd=source).split(b'\0'):
        if row:
            meta, name = row.split(b'\t', 1)
            path = name.decode('utf-8')
            rows[path] = {'modeBlob': meta.decode(), 'workingSHA256': sha((source/path).read_bytes())}
    return rows

def stage(commit, out):
    source = out/'source'
    if source.exists():
        require(git('status', '--porcelain', '--untracked-files=all', cwd=source) == b'', 'unknown source output; no candidate switch')
        subprocess.run(['git', '-C', str(source), 'switch', '--detach', commit], check=True)
    else:
        subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '--detach', str(source), commit], check=True)
    require(git('rev-parse', 'HEAD', cwd=source).decode().strip() == commit, 'source HEAD')
    require(not git('status', '--porcelain', '--untracked-files=all', cwd=source), 'source not pristine')
    return source

def command(out, label, argv, cwd, env, timeout):
    started = time.time()
    lifecycle = 'normal child completion'
    with (out/(label+'.stdout')).open('wb') as so, (out/(label+'.stderr')).open('wb') as se:
        require(os.name == 'posix', 'execution requires Linux process-group containment')
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=so, stderr=se, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=15)
            lifecycle = 'timeout: owned group SIGKILL sent; direct child reaped; abort'
            code = 124
    row = {'argv': argv, 'cwd': str(cwd), 'exit': code, 'elapsedSeconds': time.time()-started, 'lifecycle': lifecycle}
    for stream in ['stdout', 'stderr']:
        row[stream+'SHA256'] = sha((out/(label+'.'+stream)).read_bytes())
    save(out/(label+'.json'), row)
    return row

def execute(source, out, env):
    cwd = source/'engine'
    compile_row = command(out, 'compile', ['cargo','test','--release','--locked','-p','nvf-play','--lib','--no-run','--message-format=json'], cwd, env, 4800)
    if compile_row['exit']:
        return {'classification': 'compile/setup failure; zero behavioral tests', 'executed': 0, 'compile': compile_row}
    artifacts = []
    for line in (out/'compile.stdout').read_text(encoding='utf-8').splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get('reason') == 'compiler-artifact' and item.get('executable') and item['target']['name'] == 'nvf_play' and item['profile']['test']:
            artifacts.append(item['executable'])
    require(len(set(artifacts)) == 1, 'exact nvf-play unit executable')
    binary = artifacts[0]
    image = sha(Path(binary).read_bytes())
    listing = command(out, 'list', [binary, NAME, '--exact', '--list'], cwd, env, 120)
    require(listing['exit'] == 0, 'listing setup failure')
    names = re.findall(r'^([^\r\n]+): test$', (out/'list.stdout').read_text(encoding='utf-8'), re.M)
    require(names == [NAME], 'exact one nonzero selected case')
    result = command(out, 'case', [binary, NAME, '--exact', '--nocapture', '--test-threads=1'], cwd, env, 180)
    require(result['exit'] in (0, 101), 'case lifecycle/setup failure')
    text = (out/'case.stdout').read_text(encoding='utf-8')
    rows = re.findall(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', text)
    require(len(rows) == 1, 'one actual completion')
    verdict, passed, failed, ignored, measured, filtered = rows[0]
    counts = dict(zip(['passed','failed','ignored','measured','filtered'], map(int,[passed,failed,ignored,measured,filtered])))
    require(counts['passed']+counts['failed'] == 1 and counts['ignored'] == 0, 'one actual unignored case')
    require((result['exit'] == 0) == (counts['passed'] == 1), 'exit/count mismatch')
    require(sha(Path(binary).read_bytes()) == image, 'phase executable changed during execution')
    return {'classification': 'actual authored unused-copy fixture execution', 'executed': 1, 'compile': compile_row, 'list': listing, 'case': result, 'counts': counts, 'binary': binary, 'binarySHA256': image, 'imageQualification': 'phase-bound capture; later variant may overwrite this same build-output path'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    require(not args.execute or (os.environ.get('GITHUB_REPOSITORY') == 'jojokengly/NVForever' and os.environ.get('GITHUB_REF') == REF), 'execution restricted to exact fork QA branch')
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=False)
    state = {'qaCommit': git('rev-parse','HEAD').decode().strip(), 'executionRequested': args.execute, 'orchestratorSHA256': sha(Path(__file__).read_bytes()), 'workflowSHA256': sha((ROOT/'.github/workflows/qa-csty-unused-save.yml').read_bytes()), 'canonicalCase': 'save::tests::'+CASE, 'selectedCommonHarnessCase': NAME, 'variants': {}}
    save(out/'RUN.json', state)
    try:
        for _, commit in SOURCES:
            ensure_commit(commit, args.execute)
        payload = fixture(); (out/'IDENTICAL-FIXTURE-MODULE.rs').write_bytes(payload)
        state['fixtureModuleSHA256'] = sha(payload)
        if args.execute:
            state['toolchain'] = {'rustcVerbose': subprocess.check_output(['rustc','-vV']).decode(), 'cargoVersion': subprocess.check_output(['cargo','-V']).decode()}
        for side, commit in SOURCES:
            folder = out/side; folder.mkdir()
            source = stage(commit, out)
            clean = fingerprint(source)
            original = (source/SAVE).read_bytes()
            # One identical appended test module; preserve every original source byte.
            require(b'mod unused_copy_qa' not in original, 'existing QA module collision')
            (source/SAVE).write_bytes(original + payload)
            after = fingerprint(source)
            require([p for p in clean if clean[p] != after[p]] == [SAVE], 'only selected test-only file may differ')
            require((source/SAVE).read_bytes().startswith(original), 'original production/tests changed')
            (folder/'test-only.patch').write_bytes(git('diff','--binary','HEAD',cwd=source))
            (folder/'canonical-commit.txt').write_bytes(git('show','--no-patch','--format=fuller',commit))
            proof = {'commit': commit, 'tree': git('rev-parse','HEAD^{tree}',cwd=source).decode().strip(), 'canonicalTreeEntriesSHA256': sha(git('ls-tree','-r','-z','HEAD',cwd=source)), 'canonicalAndWorkingFiles': after, 'changedTestOnlyPaths': [SAVE], 'originalSaveWorkingSHA256': sha(original), 'fixtureModuleSHA256': sha(payload), 'allExistingProductionManifestsLocksAndTestBytesPreserved': True, 'qualification': 'Exact public source plus identical appended private test module; no production seam/API substitution'}
            save(folder/'SOURCE.json', proof)
            state['variants'][side] = {'source': proof}; save(out/'RUN.json', state)
            if args.execute:
                home=folder/'home';home.mkdir();tmp=folder/'tmp';tmp.mkdir()
                env=dict(os.environ,CARGO_TARGET_DIR=str(out/'target'),CARGO_BUILD_JOBS='2',NVFOREVER_HOME=str(home),NVF_REPORTS='0',TMPDIR=str(tmp),RAYON_NUM_THREADS='1')
                state['variants'][side]['execution'] = execute(source,folder,env)
                save(out/'RUN.json',state)
                require(state['variants'][side]['execution']['executed'] == 1, 'compile/setup failure aborts before next variant')
            require(fingerprint(source) == after, 'input changed during phase')
            state['variants'][side]['allInputWorkingHashesUnchangedAfter'] = True
            require((source/SAVE).read_bytes() == original+payload, 'test input changed; refuse restoration/switch')
            (source/SAVE).write_bytes(original)
            require(fingerprint(source) == clean, 'original raw source not restored')
            require(not git('status','--porcelain','--untracked-files=all',cwd=source), 'unknown output; no broad clean/reset')
            state['variants'][side]['originalRawSourceAndCleanGitRestored'] = True
            save(out/'RUN.json', state)
        if args.execute:
            require(state['variants']['main']['execution']['counts']['passed'] == 1, 'unchanged-main preservation case failed; do not certify')
            require(state['variants']['fixed']['execution']['counts']['passed'] == 1, 'fixed compatibility case failed')
        state['complete'] = True; state['singleStableSourcePath'] = str(out/'source')
        save(out/'RUN.json',state)
    except BaseException as error:
        state['error'] = repr(error); save(out/'RUN.json',state); raise
    print(json.dumps({'artifact':str(out/'RUN.json'),'complete':state.get('complete'),'executionRequested':args.execute}))

if __name__ == '__main__':
    main()
