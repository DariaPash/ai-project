"""Descriptor-relative, no-follow I/O for a local POSIX filesystem.

Not a sandbox against a hostile process with the same OS account. A checked path
is never reopened by absolute name; a directory rename cannot redirect an fd.
"""

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time
import uuid

from .errors import CoreError


def canonical(data):
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CoreError("INVALID_JSON", "Only finite JSON values are allowed") from exc


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("non-finite number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise CoreError("INVALID_JSON", "Malformed, duplicate-key or non-finite JSON") from exc


def parts(path):
    text = os.fspath(path)
    if not text or "\\" in text or "\x00" in text or ":" in text:
        raise CoreError("UNSAFE_PATH", "Invalid relative managed path", 4)
    value = PurePosixPath(text)
    if value.is_absolute() or any(p in ("..", ".") for p in value.parts) or not value.parts:
        raise CoreError("UNSAFE_PATH", "Path must stay inside its allowed root", 4)
    return value.parts


class SafeRoot:
    def __init__(self, path):
        if isinstance(path, SafeRoot):
            # Clone an already pinned root, never reopen its display path.
            self.path = path.path
            self.fd = os.dup(path.fd)
            return
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise CoreError("PLATFORM_UNAVAILABLE", "Descriptor-safe POSIX I/O is required", 3)
        self.path = Path(path).absolute()
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in self.path.parts[1:]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
        except OSError as exc:
            os.close(fd)
            raise CoreError("UNSAFE_ROOT", "Root is missing, inaccessible or contains a symlink", 4) from exc
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def directory(self, components, create=False):
        fd = os.dup(self.fd)
        try:
            for component in components:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        except OSError as exc:
            raise CoreError("UNSAFE_PATH", "Managed directory is inaccessible or not a real directory", 4) from exc
        finally:
            os.close(fd)

    @staticmethod
    def regular(fd):
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CoreError("UNSAFE_FILE", "Expected a regular, non-hardlinked file", 4)
        return info

    def exists(self, path):
        try:
            with self.directory(parts(path)[:-1]) as fd:
                info = os.stat(parts(path)[-1], dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise CoreError("UNSAFE_PATH", "Symlinks are not managed paths", 4)
                return True
        except FileNotFoundError:
            return False
        except CoreError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                return False
            raise

    def mkdir_exclusive(self, path):
        components = parts(path)
        with self.directory(components[:-1], create=True) as fd:
            try:
                os.mkdir(components[-1], mode=0o700, dir_fd=fd)
                os.fsync(fd)
            except FileExistsError as exc:
                raise CoreError("ALREADY_EXISTS", "Existing case is never overwritten", 7) from exc

    def subroot(self, path):
        """Pin a child root by descriptor, including across ancestor renames."""
        components = parts(path)
        with self.directory(components) as fd:
            child = object.__new__(SafeRoot)
            child.path = self.path.joinpath(*components)
            child.fd = os.dup(fd)
            return child

    def promote_directory(self, source, destination):
        """Atomic same-filesystem directory rename, with kernel no-replace semantics.

        No check-then-rename fallback: ordinary POSIX rename can overwrite an
        existing empty directory. Unsupported kernels/filesystems fail closed.
        """
        import ctypes
        import sys

        source_parts, destination_parts = parts(source), parts(destination)
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            rename = getattr(libc, "renameatx_np", None)
            flag = 0x00000004  # RENAME_EXCL
        elif sys.platform.startswith("linux"):
            rename = getattr(libc, "renameat2", None)
            flag = 1  # RENAME_NOREPLACE
        else:
            rename = None
        if rename is None:
            raise CoreError("ATOMIC_DIRECTORY_UNAVAILABLE", "Atomic no-replace directory promotion is unavailable", 3)
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        with self.directory(source_parts[:-1]) as source_fd, self.directory(destination_parts[:-1]) as target_fd:
            with self.directory(source_parts) as directory_fd:
                if os.fstat(directory_fd).st_dev != os.fstat(target_fd).st_dev:
                    raise CoreError("ATOMIC_DIRECTORY_UNAVAILABLE", "Staging and target must share a filesystem", 3)
            result = rename(
                source_fd, os.fsencode(source_parts[-1]), target_fd, os.fsencode(destination_parts[-1]), flag
            )
            if result != 0:
                error = ctypes.get_errno()
                if error in (errno.EEXIST, errno.ENOTEMPTY):
                    raise CoreError("IMPORT_EXISTS", "Never overwrite an existing case", 7)
                if error in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EXDEV):
                    raise CoreError("ATOMIC_DIRECTORY_UNAVAILABLE", "Filesystem lacks atomic no-replace promotion", 3)
                raise CoreError("DIRECTORY_PROMOTION_FAILED", "Atomic directory promotion failed; staging retained", 5)
            # A failure here may leave the complete installed case, never a
            # partially copied accepted case. Do not roll back or retry blindly.
            try:
                os.fsync(target_fd)
                os.fsync(source_fd)
            except OSError as exc:
                raise CoreError(
                    "DIRECTORY_DURABILITY_UNKNOWN", "Complete promotion occurred; inspect target before retrying", 5
                ) from exc

    def read(self, path, limit=8 * 1024 * 1024):
        components = parts(path)
        with self.directory(components[:-1]) as directory:
            try:
                fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise CoreError("UNSAFE_FILE", "File is inaccessible or is a symlink", 4) from exc
            try:
                before = self.regular(fd)
                if before.st_size > limit:
                    raise CoreError("SIZE_LIMIT", "File exceeds the approved byte limit", 4)
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    raw = stream.read(limit + 1)
                if len(raw) > limit:
                    raise CoreError("SIZE_LIMIT", "File grew beyond the byte limit", 4)
                after = self.regular(fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise CoreError("INPUT_CHANGED", "File changed while reading its bounded snapshot", 4)
                return raw
            finally:
                os.close(fd)

    def json(self, path):
        return parse_json(self.read(path))

    def write(self, path, raw, *, immutable=False):
        components = parts(path)
        with self.directory(components[:-1], create=True) as directory:
            try:
                existing = os.stat(components[-1], dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1):
                raise CoreError("UNSAFE_FILE", "Refusing to replace a special or hardlinked managed file", 4)
            if immutable and existing is not None:
                if self.read(path, max(len(raw), 8 * 1024 * 1024)) != raw:
                    raise CoreError("IMMUTABLE_CONFLICT", "Immutable content already differs", 6)
                return
            temp = ".write-" + uuid.uuid4().hex
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Writers hold the case lock; rename replaces a name, never follows it.
                os.rename(temp, components[-1], src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                os.close(fd)
                try:
                    os.unlink(temp, dir_fd=directory)
                except FileNotFoundError:
                    pass

    def append(self, path, raw):
        components = parts(path)
        with self.directory(components[:-1], create=True) as directory:
            fd = os.open(
                components[-1], os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory
            )
            try:
                self.regular(fd)
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise OSError("short append")
                    view = view[count:]
                os.fsync(fd)
                os.fsync(directory)
            finally:
                os.close(fd)

    def listdir(self, path):
        with self.directory(parts(path)) as fd:
            return sorted(os.listdir(fd))

    @contextmanager
    def lock(self, path, timeout=5):
        import fcntl

        components = parts(path)
        with self.directory(components[:-1], create=True) as directory:
            fd = os.open(components[-1], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                self.regular(fd)
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN):
                            raise
                        if time.monotonic() >= deadline:
                            raise CoreError("LOCK_TIMEOUT", "Another writer holds the local case lock", 7) from exc
                        time.sleep(0.01)
                yield
            finally:
                os.close(fd)
