"""Atomic, bounded MP3 cache writers and process-shared synthesis slots."""
import fcntl
import os
from pathlib import Path
import tempfile
import time

MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_TEXT_CHARS = 50000
SYNTHESIS_TIMEOUT = 120
MAX_SYNTHESIS_SLOTS = 2


class AudioBusy(Exception):
    pass


class AudioLimit(Exception):
    pass


def _lock(path):
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise AudioBusy() from None
    return fd


class AtomicAudioWriter:
    def __init__(self, directory, key, *, reserve_slot=True):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AudioLimit('unsafe_cache_directory')
        self.path = root / (key + '.mp3')
        self.locks, self.file, self.temp = [], None, None
        self.bytes_written, self.published, self.closed = 0, False, False
        try:
            self.locks.append(_lock(root / (key + '.lock')))
            if reserve_slot:
                for index in range(MAX_SYNTHESIS_SLOTS):
                    try:
                        self.locks.append(_lock(root / ('.synthesis-slot-' + str(index) + '.lock')))
                        break
                    except AudioBusy:
                        continue
                else:
                    raise AudioBusy()
            fd, name = tempfile.mkstemp(prefix='.' + key + '.', suffix='.partial', dir=root)
            self.temp = Path(name)
            self.file = os.fdopen(fd, 'wb')
        except BaseException:
            self.close()
            raise

    def append(self, value):
        if self.closed or self.published or not isinstance(value, bytes):
            raise AudioLimit('invalid_audio_chunk')
        if self.bytes_written + len(value) > MAX_AUDIO_BYTES:
            raise AudioLimit('audio_size_limit')
        self.file.write(value)
        self.bytes_written += len(value)

    def publish(self):
        if self.closed or self.published or self.bytes_written <= 0:
            raise AudioLimit('empty_or_closed_audio')
        self.file.flush(); os.fsync(self.file.fileno()); self.file.close(); self.file = None
        os.replace(self.temp, self.path)
        self.published = True
        # The directory sync makes the completed rename durable as well.
        fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return os.fspath(self.path)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.file is not None:
            self.file.close(); self.file = None
        if self.temp is not None:
            try:
                self.temp.unlink(missing_ok=True)
            except OSError:
                pass
        for fd in reversed(self.locks):
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        self.locks.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
