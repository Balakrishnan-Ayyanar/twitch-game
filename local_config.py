"""Explicit storage-only credential loader. No discovery, env, logging or network.

The only supported location is WORKSPACE/.twitch-local/credentials.json. This
module never opens that location unless load_local_credentials is called. Server
imports and ordinary gameplay do not call it. Errors contain no path/data details.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import sys
from oauth import OAuthConfig

DIRECTORY = '.twitch-local'
FILENAME = 'credentials.json'
MAX_BYTES = 4096
ERROR = 'Local credential configuration unavailable or invalid.'

class LocalConfigError(Exception):
    pass

@dataclass(frozen=True)
class LocalCredentials:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def disabled_oauth_config(self):
        """Storage cannot enable authorization or any provider/chat network gate."""
        return OAuthConfig(enabled=False,client_id=self.client_id,client_secret=self.client_secret)


def _object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError()


def _owned(info):
    return info.st_uid == os.getuid()


def _no_extended_acl(descriptor):
    """Conservative owner-only policy: reject extended ACL entries, not just mode bits."""
    if sys.platform == 'darwin':
        import ctypes
        import errno
        libc = ctypes.CDLL(None,use_errno=True)
        get_acl = libc.acl_get_fd_np
        get_acl.argtypes, get_acl.restype = [ctypes.c_int,ctypes.c_int],ctypes.c_void_p
        get_entry = libc.acl_get_entry
        get_entry.argtypes, get_entry.restype = [ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)],ctypes.c_int
        free_acl = libc.acl_free
        free_acl.argtypes, free_acl.restype = [ctypes.c_void_p],ctypes.c_int
        ctypes.set_errno(0)
        acl = get_acl(descriptor,0x100)  # Darwin ACL_TYPE_EXTENDED
        if not acl:
            return ctypes.get_errno() == errno.ENOENT
        try:
            entry = ctypes.c_void_p()
            return get_entry(acl,0,ctypes.byref(entry)) == 0  # ACL_FIRST_ENTRY, no entries
        finally:
            free_acl(acl)
    if sys.platform.startswith('linux') and hasattr(os,'listxattr'):
        return not {'system.posix_acl_access','system.posix_acl_default'}.intersection(os.listxattr(descriptor))
    return False  # Unsupported platforms fail closed.


def load_local_credentials(workspace):
    """POSIX openat/no-follow checks before reading, bounded UTF-8 JSON only.

    Workspace must be owner-owned and not group/world writable; the private
    directory must be exactly 0700, file exactly 0600 or 0400, owner-owned,
    regular and single-linked. Root/directory/file symlinks are rejected without
    resolving them. Metadata is checked again after reading to detect changes.
    """
    descriptors = []
    try:
        if not all(hasattr(os, name) for name in ('O_NOFOLLOW','O_DIRECTORY','O_NONBLOCK','getuid')):
            raise ValueError()
        root = os.open(os.fspath(Path(workspace)),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        descriptors.append(root)
        root_info = os.fstat(root)
        if not _owned(root_info) or stat.S_IMODE(root_info.st_mode) & 0o022 or not _no_extended_acl(root):
            raise ValueError()
        folder = os.open(DIRECTORY,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        descriptors.append(folder)
        folder_info = os.fstat(folder)
        if not _owned(folder_info) or stat.S_IMODE(folder_info.st_mode) != 0o700 or not _no_extended_acl(folder):
            raise ValueError()
        file = os.open(FILENAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=folder)
        descriptors.append(file)
        before = os.fstat(file)
        if (not stat.S_ISREG(before.st_mode) or not _owned(before) or before.st_nlink != 1 or
                stat.S_IMODE(before.st_mode) not in (0o400,0o600) or not 1 <= before.st_size <= MAX_BYTES or
                not _no_extended_acl(file)):
            raise ValueError()
        raw = bytearray()
        while len(raw) <= MAX_BYTES:
            chunk = os.read(file,MAX_BYTES+1-len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(file)
        if (len(raw) > MAX_BYTES or len(raw) != before.st_size or
                (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns,before.st_mode,before.st_uid,before.st_nlink) !=
                (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_mode,after.st_uid,after.st_nlink)):
            raise ValueError()
        obj = json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=_invalid_constant)
        if (not isinstance(obj,dict) or set(obj) != {'schema_version','client_id','client_secret'} or
                type(obj['schema_version']) is not int or obj['schema_version'] != 1):
            raise ValueError()
        client_id,secret = obj['client_id'],obj['client_secret']
        if (not isinstance(client_id,str) or not 1 <= len(client_id) <= 256 or
                not client_id.isascii() or not client_id.isalnum() or
                not isinstance(secret,str) or not 1 <= len(secret) <= 1024 or
                not secret.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in secret)):
            raise ValueError()
        return LocalCredentials(client_id,secret)
    except (OSError,ValueError,TypeError,OverflowError,RecursionError,AttributeError):
        raise LocalConfigError(ERROR) from None
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
