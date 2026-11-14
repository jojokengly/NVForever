"""Fork-only actual-source pairs. Default is source preparation; execution requires --execute.

No asset downloads, GPU/game launch, source stubs, dependency edits or cache transfer.
Each job builds its two sources sequentially using only its own hosted target directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
FORK = 'https://github.com/jojokengly/NVForever.git'
CND_BASE = 'a605879db4d8a2d2998549c6788f3d190f1b5a56'
CND_HEAD = '51ede41243a38fdfd532362ec7a3c915da53a771'
NULL_BASE = 'df80a70555baa182742808646019acedbe6791f7'
NULL_HEAD = '05b8316cc978ecc0966123d3e0ab34a93bf5ba35'
STATS = 'engine/nvf-play/src/pipboy/stats/mod.rs'
INTERFACE = 'engine/nvf-play/src/interface.rs'
NULL_TEST = 'crates/fnv-game/tests/null_call_context.rs'
MAIN_TEST = 'crates/fnv-game/tests/main.rs'
sha = lambda b: hashlib.sha256(b).hexdigest()

def require(value, message):
    if not value:
        raise RuntimeError(message)

def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', '-C', str(cwd), *args])

def blob(commit, path):
    return git('show', commit + ':' + path)

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def ensure_commit(commit, execute):
    exists = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '-e', commit+'^{commit}'], capture_output=True)
    if exists.returncode:
        require(execute, 'Missing source commit locally: ' + commit)
        subprocess.run(['git', '-C', str(ROOT), 'fetch', '--no-tags', FORK, commit], check=True)
    require(git('rev-parse', commit).decode().strip() == commit, 'commit identity')

def stage(topic, side, commit, out):
    source = out / ('source-' + side)
    subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '--detach', str(source), commit], check=True)
    return source

def cnd_injection(source):
    candidate = blob(CND_HEAD, STATS)
    start = candidate.index(b'    const PAPERDOLL_FILES:')
    end = candidate.index(b'    #[test]\n    fn the_test_aid_reads_its_steps()', start)
    tests = candidate[start:end]
    require(len(re.findall(rb'#\[test\]', tests)) == 5, 'CND exact contiguous five producer tests')
    baseline = blob(CND_BASE, STATS)
    anchor = b'mod tests {\n    use super::*;\n\n'
    require(baseline.count(anchor) == 1, 'unique stats test module')
    (source/STATS).write_bytes(baseline.replace(anchor, anchor + tests, 1))
    ci = blob(CND_HEAD, INTERFACE)
    helper_start = ci.index(b'    pub(crate) fn authored_rgba_dds(')
    helper_end = ci.index(b'    #[test]', helper_start)
    helper = ci[helper_start:helper_end]
    bi = blob(CND_BASE, INTERFACE)
    anchor = b'#[cfg(test)]\nmod tests {\n    use super::*;\n\n'
    require(bi.count(anchor) == 1, 'unique interface test module')
    replacement = b'#[cfg(test)]\npub(crate) mod tests {\n    use super::*;\n\n' + helper
    (source/INTERFACE).write_bytes(bi.replace(anchor, replacement, 1))
    return {STATS: tests, INTERFACE: helper}

def null_injection(source):
    fixture = blob(NULL_HEAD, NULL_TEST)
    require(sha(fixture) == '373f9c635cc77d954fb1c7b5b0ec72ee73892d203c483a8fd1245e37892130db', 'actual05b fixture pin')
    require(len(re.findall(rb'#\[test\]', fixture)) == 3, 'NULL exact three authored fixtures')
    # No diagnostic hook API is referenced by these public tests; retain actual pre-fix production.
    require(b'no_reference_call' not in fixture, 'fixtures require new Host ABI')
    require(git('diff', NULL_BASE, NULL_HEAD, '--', 'crates/fnv-game/tests/common') == b'', 'common test ABI changed')
    (source/NULL_TEST).write_bytes(fixture)
    main = blob(NULL_BASE, MAIN_TEST)
    anchor = b'mod npc_doors;\n'
    require(main.count(anchor) == 1 and b'mod null_call_context;' not in main, 'NULL sole module registration')
    (source/MAIN_TEST).write_bytes(main.replace(anchor, anchor+b'mod null_call_context;\n', 1))
    return {NULL_TEST: fixture}

def fingerprint(source):
    # Every tracked mode/blob stays identical except reviewed exact test injection.
    rows = {}
    for entry in git('ls-tree', '-r', '-z', 'HEAD', cwd=source).split(b'\0'):
        if not entry:
            continue
        header, name = entry.split(b'\t', 1)
        path = name.decode()
        rows[path] = {'modeBlob':header.decode(), 'workingSHA256':sha((source/path).read_bytes())}
    for path in [NULL_TEST]:
        if path not in rows and (source/path).is_file():
            rows[path] = {'modeBlob':'new authored test only', 'workingSHA256':sha((source/path).read_bytes())}
    return rows

def command(out, label, args, cwd, env, timeout):
    started = time.time()
    with (out/(label+'.stdout')).open('wb') as so, (out/(label+'.stderr')).open('wb') as se:
        try:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=so, stderr=se, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    row = {'argv':args, 'cwd':str(cwd), 'exit':code, 'elapsedSeconds':time.time()-started}
    for stream in ['stdout','stderr']:
        row[stream+'SHA256'] = sha((out/(label+'.'+stream)).read_bytes())
    save(out/(label+'.json'), row)
    return row

def execute(topic, side, source, out, names, env):
    package, target = ('nvf-play', ['--lib']) if topic == 'cnd' else ('fnv-game', ['--test','integration'])
    cwd = source/'engine' if topic == 'cnd' else source
    row = command(out, 'compile', ['cargo','test','--release','--locked','-p',package,*target,'--no-run','--message-format=json'], cwd, env, 4800)
    if row['exit']:
        return {'classification':'compile/setup failure; zero behavioral tests', 'executed':0, 'compile':row}
    artifacts = []
    for line in (out/'compile.stdout').read_text().splitlines():
        try: item = json.loads(line)
        except json.JSONDecodeError: continue
        if item.get('reason') == 'compiler-artifact' and item.get('executable') and item['target']['name'] == ('nvf_play' if topic == 'cnd' else 'integration'):
            artifacts.append(item['executable'])
    require(len(set(artifacts)) == 1, 'exact selected executable')
    binary = artifacts[0]
    image = sha(Path(binary).read_bytes())
    listed = command(out, 'list', [binary,'--list'], cwd, env, 120)
    require(listed['exit'] == 0, 'list failure')
    all_names = re.findall(r'^([^\r\n]+): test$', (out/'list.stdout').read_text(), re.M)
    selected = [name for name in all_names if name.startswith('pipboy::stats::tests::paperdoll_actual_')] if topic == 'cnd' else [name for name in all_names if name.startswith('null_call_context::')]
    require(sorted(selected) == sorted(names), 'exact nonzero fixture list')
    rows = []
    for index, name in enumerate(names):
        result = command(out, 'case-'+str(index), [binary,name,'--exact','--nocapture','--test-threads=1'], cwd, env, 180)
        text = (out/('case-'+str(index)+'.stdout')).read_text()
        counts = re.findall(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', text)
        require(len(counts) == 1, 'one actual test completion')
        verdict,passed,failed,ignored,measured,filtered = counts[0]
        counts = dict(zip(['passed','failed','ignored','measured','filtered'], map(int,[passed,failed,ignored,measured,filtered])))
        require(counts['passed']+counts['failed']==1 and counts['ignored']==0, 'exact one named actual test')
        rows.append({'name':name, 'result':result, 'counts':counts})
    require(sha(Path(binary).read_bytes()) == image, 'executable changed')
    return {'classification':'actual authored fixture execution', 'executed':len(rows), 'selectedNames':selected, 'binarySHA256':image, 'cases':rows}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('topic', choices=['cnd','null'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    args=parser.parse_args()
    require(not args.execute or os.environ.get('GITHUB_REPOSITORY') == 'jojokengly/NVForever', 'execution limited to reviewed fork Actions')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    state={'topic':args.topic,'qaCommit':git('rev-parse','HEAD').decode().strip(),'sourceOnlyCPU':True,'executionRequested':args.execute,'orchestratorSHA256':sha(Path(__file__).read_bytes()),'workflowSHA256':sha((ROOT/'.github/workflows/qa-baseline-pairs.yml').read_bytes()),'sides':{}}
    save(out/'RUN.json',state)
    base,head=(CND_BASE,CND_HEAD) if args.topic=='cnd' else (NULL_BASE,NULL_HEAD)
    try:
        for commit in [base,head]: ensure_commit(commit,args.execute)
        if args.execute:
            state['toolchain']={'rustcVerbose':subprocess.check_output(['rustc','-vV']).decode(),'cargoVersion':subprocess.check_output(['cargo','-V']).decode()}
        fixtures=blob(head,STATS if args.topic=='cnd' else NULL_TEST).decode()
        short=re.findall(r'#\[test\]\s+fn ((?:paperdoll_actual_|actual_)\w+)\(',fixtures)
        prefix='pipboy::stats::tests::' if args.topic=='cnd' else 'null_call_context::'
        names=[prefix+name for name in short]
        require(len(names)==(5 if args.topic=='cnd' else 3), 'expected fixture count')
        for side,commit in [('base',base),('candidate',head)]:
            folder=out/side;folder.mkdir()
            source=stage(args.topic,side,commit,out)
            clean=fingerprint(source)
            injected=(cnd_injection(source) if args.topic=='cnd' else null_injection(source)) if side=='base' else {}
            after=fingerprint(source)
            changed=[path for path in sorted(set(clean)|set(after)) if clean.get(path)!=after.get(path)]
            allowed=([INTERFACE,STATS] if args.topic=='cnd' else [MAIN_TEST,NULL_TEST]) if side=='base' else []
            require(sorted(changed)==sorted(allowed), 'unexpected source delta')
            (folder/'test-only.patch').write_bytes(git('diff','--binary','HEAD',cwd=source))
            (folder/'canonical-candidate-vs-base.patch').write_bytes(git('diff','--binary',base,head))
            (folder/'canonical-commit.txt').write_bytes(git('show','--no-patch','--format=fuller',commit))
            if args.topic=='null': (folder/'identical-null-fixture.rs').write_bytes(blob(head,NULL_TEST))
            for path,data in injected.items(): (folder/(Path(path).name+'.injected.rs')).write_bytes(data)
            proof={'commit':commit,'tree':git('rev-parse','HEAD^{tree}',cwd=source).decode().strip(),'canonicalTreeEntriesSHA256':sha(git('ls-tree','-r','-z','HEAD',cwd=source)), 'changedTestOnlyPaths':changed,'canonicalAndWorkingFiles':after,'exactNames':names,'productionAndManifestsAndLocksUnchanged':True,'qualification':'Pristine public production plus test-only fixtures' if side=='base' else 'Exact public candidate source'}
            save(folder/'SOURCE.json',proof)
            state['sides'][side]={'source':proof}
            save(out/'RUN.json',state)
            if args.execute:
                home=folder/'home';home.mkdir();tmp=folder/'tmp';tmp.mkdir()
                env=dict(os.environ,CARGO_TARGET_DIR=str(out/'target'),CARGO_BUILD_JOBS='2',NVFOREVER_HOME=str(home),NVF_REPORTS='0',TMPDIR=str(tmp),RAYON_NUM_THREADS='1')
                state['sides'][side]['execution']=execute(args.topic,side,source,folder,names,env)
                require(fingerprint(source)==after,'tracked source/lock changed during execution')
                state['sides'][side]['allInputWorkingHashesUnchangedAfter']=True
                save(out/'RUN.json',state)
        state['complete']=True
        save(out/'RUN.json',state)
        if args.execute:
            candidate=state['sides']['candidate']['execution']
            require(candidate['executed']==len(names) and all(row['counts']['passed']==1 and row['result']['exit']==0 for row in candidate.get('cases',[])), 'candidate failed or setup incomplete')
            require(state['sides']['base']['execution']['executed']==len(names),'baseline setup incomplete; zero behavior qualification')
    except BaseException as error:
        state['error']=repr(error);save(out/'RUN.json',state);raise
    print(json.dumps({'artifact':str(out/'RUN.json'),'complete':state.get('complete'), 'executionRequested':args.execute}))

if __name__=='__main__':main()
