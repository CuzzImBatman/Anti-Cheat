from __future__ import nested_scopes, generators, division, absolute_import, with_statement, print_function, unicode_literals
import json, base64, os, subprocess, select, requests, sys

GH_TOKEN = os.environ['STATUS_APIKEY']
COMMIT = os.environ['TRAVIS_COMMIT']
TESTDATA = 'testdemos'

def create_gist(text):
    res = requests.post('https://api.github.com/gists', data=json.dumps({
        "description": "Autogenerated by brofiler.py",
        "public": True,
        "files": {
            "report.txt": {
                "content": text
            }
        }
    }).encode('utf-8'))
    return json.loads(res.text)['files']['report.txt']['raw_url']

def set_status(sha, state, desc, ctx, url=None):
    request = {
        'state': state,
        'description': desc,
        'context': 'profiling/' + ctx
    }

    if url:
        request['target_url'] = url

    res = requests.post('https://api.github.com/repos/moritzuehling/demoinfo-public/statuses/' + sha,
                        headers={'Authorization': 'token ' + GH_TOKEN}, data=json.dumps(request).encode('utf-8'))
    return res.text

demos = [dem for dem in os.listdir(TESTDATA) if dem.endswith('.dem')]


if sys.argv[1] == 'cleanup':
    for dem in demos:
        set_status(COMMIT, 'error', '???', dem)
    sys.exit(0)
elif sys.argv[1] != 'run':
    raise ValueError('Illegal parameter')

# start by setting all of them to Preparing
for dem in demos:
    set_status(COMMIT, 'pending', 'Preparing', dem)

failure_count = 0
# now actually run profiling
for dem in demos:
    set_status(COMMIT, 'pending', 'Running', dem)
    pipe_rfd, pipe_wfd = os.pipe()
    p = subprocess.Popen(
        ['/bin/bash', 'ci/profile.sh', dem, str(pipe_wfd)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=False,
        preexec_fn = lambda: os.close(pipe_rfd),
    )

    pipe_chunks = []
    stdout_chunks = []
    stderr_chunks = []
    stdout_rfd, stderr_rfd = p.stdout.fileno(), p.stderr.fileno()
    pending = [pipe_rfd, stdout_rfd, stderr_rfd]
    while len(pending) > 1 or pipe_rfd not in pending: # wait for all except pipe
        rready, _, _ = select.select(pending, [], [])
        fd = rready[0]
        chunk = os.read(fd, 4096)
        if len(chunk) == 0:
            # end of stream
            pending.remove(fd)
        else:
            (pipe_chunks if fd is pipe_rfd else stdout_chunks if fd is stdout_rfd else stderr_chunks).append(chunk.decode('utf-8'))
    retval = p.wait()
    print('%s return value %d' % (dem, retval))

    os.unlink(TESTDATA + '/' + dem)

    gist_text = '' if retval == 0 else 'return code %d' % (retval,)
    err_text = ''.join(stderr_chunks)
    out_text = ''.join(stdout_chunks)
    pipe_text = ''.join(pipe_chunks)
    pipe_text = '\n'.join([x for x in pipe_text.split('\n') if not x.startswith('unmatched leave at stack pos')])
    if len(err_text) > 0:
        gist_text += '\n----- stderr -----\n'
        gist_text += err_text
        gist_text += '\n------------------\n'
    if len(out_text) > 0:
        gist_text += '\n----- stdout -----\n'
        gist_text += out_text
        gist_text += '\n------------------\n'
    if len(pipe_text) > 0:
        all_is_well = len(gist_text) == 0
        if not all_is_well:
            gist_text += '\n----- results-----\n'
        gist_text += pipe_text
        if not all_is_well:
            gist_text += '\n------------------\n'
    gistlink = create_gist(gist_text)
    print('Profiling results posted to: ' + gistlink)
    set_status(COMMIT, 'success' if retval is 0 else 'failure', 'Completed', dem, gistlink)
    if retval != 0:
        failure_count += 1

sys.exit(failure_count)
