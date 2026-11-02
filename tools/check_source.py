"""Offline heuristic scan of a fixed public-source allowlist; never private storage.

No recursive discovery, git/log/env/credential reads, archive creation or uploads.
Reports rule/line only, never the matching value. It is not a comprehensive secret audit.
"""
import os
from pathlib import Path
import re
import stat

SOURCES = (
    'game.py','server.py','oauth.py','eventsub.py','twitch_adapter.py','local_config.py',
    'static/index.html','static/style.css','static/app.js','static/twitch-ui.js',
    'twitch-config.example.json','requirements.txt','requirements.lock',
    'README.md','TWITCH_SETUP.md',
)
RULES = (
    ('private-key',re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('literal-credential',re.compile(r'''(?i)["']?(?:client_secret|access_token|refresh_token)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']''')),
    ('authorization-query',re.compile(r'''(?i)[?&](?:code|access_token|refresh_token|client_secret)=[^&\s"'<>]{6,}''')),
    ('literal-bearer',re.compile(r'(?i)\b(?:Bearer|OAuth)\s+[A-Za-z0-9]{24,}')),
)

def scan(root):
    root = Path(root)
    findings = []
    for relative in SOURCES:
        target = root/relative
        descriptor = None
        try:
            if root.is_symlink() or any(path.is_symlink() for path in (target,*target.parents) if path == root or root in path.parents):
                raise ValueError()
            descriptor = os.open(target,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024*1024:
                raise ValueError()
            data = bytearray()
            while len(data) <= 1024*1024:
                chunk = os.read(descriptor,min(65536,1024*1024+1-len(data)))
                if not chunk:break
                data.extend(chunk)
            if len(data) > 1024*1024:raise ValueError()
            source = data.decode('utf-8')
            for line_number,line in enumerate(source.splitlines(),1):
                for rule,pattern in RULES:
                    if pattern.search(line):findings.append((relative,line_number,rule))
        except (OSError,ValueError):
            findings.append((relative,0,'unreadable-or-unsafe-source'))
        finally:
            if descriptor is not None:os.close(descriptor)
    return findings

if __name__ == '__main__':
    issues = scan(Path(__file__).resolve().parent.parent)
    for name,line,rule in issues:print('{}:{}: {}'.format(name,line,rule))
    print('Scanned {} fixed public source files; {} findings. No private files opened; no archive created.'.format(len(SOURCES),len(issues)))
    raise SystemExit(1 if issues else 0)
