"""Exercise real Windows FileIO errors using only private random test pipes."""
import errno
import os
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
if os.name=='nt':
    import ctypes as ct
    import msvcrt
    from ctypes import wintypes as wt
    from codex_whale_pet import windows as win


@unittest.skipUnless(os.name=='nt','Windows named pipes are required.')
class NamedPipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel=ct.WinDLL('kernel32',use_last_error=True)
        cls.kernel.CreateNamedPipeW.argtypes=[wt.LPCWSTR,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,wt.DWORD,ct.c_void_p]
        cls.kernel.CreateNamedPipeW.restype=wt.HANDLE
        cls.kernel.ConnectNamedPipe.argtypes=[wt.HANDLE,ct.c_void_p]
        cls.kernel.DisconnectNamedPipe.argtypes=[wt.HANDLE]
        cls.kernel.CloseHandle.argtypes=[wt.HANDLE]
        win.kernel.PeekNamedPipe.argtypes=[wt.HANDLE,ct.c_void_p,wt.DWORD,ct.c_void_p,ct.POINTER(wt.DWORD),ct.c_void_p]

    @contextmanager
    def connected_pipe(self):
        name=rf'\\.\pipe\whale-test-{uuid.uuid4().hex}'
        server=self.kernel.CreateNamedPipeW(name,0x80003,0,1,4096,4096,0,None)
        if server in (None,wt.HANDLE(-1).value):
            raise ct.WinError(ct.get_last_error())
        client=None

        def close_server(disconnect=False):
            nonlocal server
            if server is None:
                return
            handle,server=server,None
            try:
                if disconnect and not self.kernel.DisconnectNamedPipe(handle):
                    raise ct.WinError(ct.get_last_error())
            finally:
                if not self.kernel.CloseHandle(handle):
                    raise ct.WinError(ct.get_last_error())

        try:
            client=open(name,'r+b',buffering=0)
            # The client is already connected: ConnectNamedPipe returns ERROR_PIPE_CONNECTED,
            # so there is no blocking server wait or worker thread to leave behind.
            if not self.kernel.ConnectNamedPipe(server,None) and ct.get_last_error()!=535:
                raise ct.WinError(ct.get_last_error())
            ipc=win.PetRefresh.__new__(win.PetRefresh)
            ipc.pipe,ipc.handle=client,msvcrt.get_osfhandle(client.fileno())
            ipc.buffer=bytearray()
            yield ipc,close_server
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                close_server()

    def test_missing_pipe_is_waiting(self):
        name=rf'\\.\pipe\whale-test-{uuid.uuid4().hex}'
        with self.assertRaises(FileNotFoundError) as caught:
            with open(name,'r+b',buffering=0):
                self.fail('An uncreated random test pipe unexpectedly exists.')
        self.assertEqual(caught.exception.errno,errno.ENOENT)
        self.assertIsNone(getattr(caught.exception,'winerror',None))
        # Replay the real CRT exception; the application pipe is never opened.
        with mock.patch('builtins.open',side_effect=caught.exception) as opened:
            with self.assertRaises(win.NotReady):
                win.PetRefresh()
        opened.assert_called_once()

    def test_peer_close_and_disconnect_are_waiting(self):
        for disconnect in (False,True):  # Cover both distinct Win32 teardown paths.
            with self.subTest(disconnect=disconnect),self.connected_pipe() as (ipc,close_server):
                close_server(disconnect)
                with self.assertRaises(OSError) as caught:
                    ipc.pipe.write(b'x')
                self.assertEqual(caught.exception.errno,errno.EINVAL)
                self.assertIsNone(getattr(caught.exception,'winerror',None))
                self.assertTrue(ipc.disconnected_error(caught.exception))
                with self.assertRaises(win.NotReady):
                    ipc.send({'method':'query-cache-invalidate'})
                with self.assertRaises(win.NotReady):
                    ipc.pump()
                if disconnect:
                    with self.assertRaises(OSError) as read_error:
                        ipc.pipe.read(1)
                    self.assertEqual(read_error.exception.errno,errno.EINVAL)
                else:
                    self.assertEqual(ipc.pipe.read(1),b'')

    def test_read_after_successful_peek_handles_close_race(self):
        for disconnect in (False,True):  # FileIO returns EOF or EINVAL after the peer closes.
            with self.subTest(disconnect=disconnect),self.connected_pipe() as (ipc,close_server):
                close_server(disconnect)
                real_peek=win.kernel.PeekNamedPipe
                first=True

                def stale_peek(*args):
                    nonlocal first
                    if first:
                        first=False
                        args[4]._obj.value=1
                        return True
                    return real_peek(*args)

                # Deterministically enter the race between a successful peek and a real read.
                with mock.patch.object(win.kernel,'PeekNamedPipe',side_effect=stale_peek):
                    with self.assertRaises(win.NotReady):
                        ipc.pump()

    def test_live_pipe_preserves_unrelated_einval(self):
        with self.connected_pipe() as (ipc,unused_close):
            error=OSError(errno.EINVAL,'synthetic argument error')
            self.assertFalse(ipc.disconnected_error(error))
            self.assertFalse(ipc.disconnected_error(PermissionError(errno.EACCES,'synthetic access error')))
            proxy=mock.Mock(wraps=ipc.pipe)
            proxy.write.side_effect=error
            with mock.patch.object(ipc,'pipe',proxy):
                with self.assertRaises(OSError) as caught:
                    ipc.send({'method':'query-cache-invalidate'})
            self.assertIs(caught.exception,error)


if __name__=='__main__':
    unittest.main()
