"""Read only native Pet geometry and physical pointer position; never operate a window."""
import ctypes as ct
import json
import math
import os
import errno
import re
import subprocess
from contextlib import contextmanager
from ctypes import wintypes as wt
from pathlib import Path

APP_VERSION = '26.1023.6621.0'
PET_ID = 'custom:whale-musume'
MUTEX = 'Local\\WhaleNativePetAssetController'


class NotReady(RuntimeError):
    """Codex or its visible native pet is not ready yet; publish this waiting state."""


class DesktopUnavailable(NotReady):
    """Windows temporarily withholds cursor access on a locked or secure input desktop."""


class UnsupportedVersion(RuntimeError):
    pass

user = ct.WinDLL('user32', use_last_error=True)
kernel = ct.WinDLL('kernel32', use_last_error=True)
user.SetProcessDpiAwarenessContext.argtypes = [ct.c_void_p]
user.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
user.GetWindowLongW.argtypes = [wt.HWND, ct.c_int]
user.GetWindowLongW.restype = ct.c_long
user.GetDpiForWindow.argtypes = [wt.HWND]
user.GetDpiForWindow.restype = wt.UINT
user.IsWindowVisible.argtypes = [wt.HWND]
user.GetWindowRect.argtypes = [wt.HWND, ct.POINTER(wt.RECT)]
user.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
user.GetCursorPos.argtypes = [ct.POINTER(wt.POINT)]
user.GetCursorPos.restype = wt.BOOL
user.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user.MonitorFromWindow.restype = wt.HMONITOR
kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel.OpenProcess.restype = wt.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)]
kernel.CloseHandle.argtypes = [wt.HANDLE]
ENUMPROC = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user.EnumWindows.argtypes = [ENUMPROC, wt.LPARAM]


class MonitorInfo(ct.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('monitor', wt.RECT), ('work', wt.RECT), ('flags', wt.DWORD)]


user.GetMonitorInfoW.argtypes = [wt.HMONITOR, ct.POINTER(MonitorInfo)]


def app_path(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ''
    try:
        value, size = ct.create_unicode_buffer(32768), wt.DWORD(32768)
        return value.value if kernel.QueryFullProcessImageNameW(handle, 0, value, ct.byref(size)) else ''
    finally:
        kernel.CloseHandle(handle)


def rect_tuple(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


def native_windows(allow_untested=False):
    found, errors = [], []
    @ENUMPROC
    def visit(hwnd, unused):
        # EnumWindows is the OS enumeration API; inspecting each visible topmost tool window is necessary.
        style = user.GetWindowLongW(hwnd, -20)
        if not user.IsWindowVisible(hwnd) or style & 0x88 != 0x88:
            return True
        pid = wt.DWORD()
        user.GetWindowThreadProcessId(hwnd, ct.byref(pid))
        executable = app_path(pid.value)
        if not executable.lower().endswith('\\app\\chatgpt.exe') or 'openai.codex_' not in executable.lower():
            return True
        if not allow_untested and f'OpenAI.Codex_{APP_VERSION}_'.lower() not in executable.lower():
            errors.append('Codex version changed; native Pet controller must be revalidated.')
            return False
        rect, monitor = wt.RECT(), MonitorInfo(cbSize=ct.sizeof(MonitorInfo))
        if not user.GetWindowRect(hwnd, ct.byref(rect)) or not user.GetMonitorInfoW(user.MonitorFromWindow(hwnd, 2), ct.byref(monitor)):
            return True
        found.append({'hwnd': int(hwnd), 'pid': pid.value, 'rect': rect_tuple(rect),
                      'monitor': rect_tuple(monitor.monitor), 'dpi': user.GetDpiForWindow(hwnd)})
        return True
    user.EnumWindows(visit, 0)
    if errors:
        raise UnsupportedVersion(errors[0])
    return found


def selected_pet(home):
    import tomllib
    if not (home/'config.toml').is_file():
        return None
    return tomllib.loads((home/'config.toml').read_text(encoding='utf-8')).get('desktop', {}).get('selected-avatar-id')


def pet_settings(home):
    if not (home/'.codex-global-state.json').is_file():
        raise NotReady('Show the official Mini, select the whale, and move it once.')
    state = json.loads((home/'.codex-global-state.json').read_text(encoding='utf-8'))
    bounds = state.get('electron-avatar-overlay-bounds')
    size = state.get('avatar-overlay-mascot-width-px')
    if size is None:
        size = state.get('electron-persisted-atom-state', {}).get('avatar-overlay-mascot-width-px', 112)
    if not isinstance(bounds, dict) or not all(key in bounds for key in ('x', 'y', 'displayBounds')):
        raise NotReady('Native Pet has no saved stable position. Show it and move it once.')
    width = max(80, min(224, float(size)))
    return bounds, width


def geometry(home, allow_untested=False):
    bounds, width = pet_settings(home)
    display = bounds['displayBounds']
    candidates = []
    for window in native_windows(allow_untested):  # Match the saved Electron display to the visible native Pet window.
        left, top, right, bottom = window['monitor']
        scale = window['dpi']/96
        if abs(display['width']*scale-(right-left)) > 3 or abs(display['height']*scale-(bottom-top)) > 3:
            continue
        x = left+(bounds['x']-display['x']+width/2)*scale
        y = top+(bounds['y']-display['y']+math.ceil(width*208/192)/2)*scale
        wl, wt_, wr, wb = window['rect']
        if wl <= x <= wr and wt_ <= y <= wb:
            candidates.append({**window, 'center': [x, y], 'scale': scale, 'width_dip': width})
    if not candidates:
        raise NotReady('The official Pet is hidden. Show Mini to resume.')
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one visible native Pet, found {len(candidates)} matching windows.')
    return candidates[0]


def cursor():
    point = wt.POINT()
    ct.set_last_error(0)
    if not user.GetCursorPos(ct.byref(point)):
        code=ct.get_last_error()
        if code==5:
            raise DesktopUnavailable('Windows input desktop is unavailable; cursor tracking is paused until access returns.')
        if code==0:
            raise RuntimeError('GetCursorPos failed without an extended error code.')
        raise ct.WinError(code)
    return point.x, point.y



import msvcrt
import struct
import time
import uuid

class PetRefresh:
    """Normal own-client IPC registration; only the Pet cache invalidation broadcast is sent."""
    def __init__(self):
        try:
            self.pipe = open(r'\\.\pipe\codex-ipc', 'r+b', buffering=0)
        except OSError as error:
            if isinstance(error,FileNotFoundError) or error.errno==errno.ENOENT or getattr(error,'winerror',None) in (2,109,231,233):
                raise NotReady('Codex is closed; waiting to reconnect.') from error
            raise
        self.handle = msvcrt.get_osfhandle(self.pipe.fileno())
        kernel.PeekNamedPipe.argtypes = [wt.HANDLE, ct.c_void_p, wt.DWORD, ct.c_void_p, ct.POINTER(wt.DWORD), ct.c_void_p]
        self.buffer = bytearray()
        self.client_id, self.request_id = None, str(uuid.uuid4())
        self.send({'type': 'request', 'method': 'initialize', 'requestId': self.request_id,
                   'version': 0, 'sourceClientId': 'uninitialized',
                   'params': {'clientType': 'whale-pet-asset-controller'}})
        deadline = time.monotonic()+5
        while self.client_id is None and time.monotonic() < deadline:
            self.pump()
            time.sleep(.02)
        if self.client_id is None:
            self.close()
            raise RuntimeError('Normal Pet cache client registration failed.')

    def pump(self):
        # Peek before reading: Python's Windows file descriptor locks make simultaneous blocking read/write deadlock.
        available = wt.DWORD()
        if not kernel.PeekNamedPipe(self.handle, None, 0, None, ct.byref(available), None):
            code=ct.get_last_error()
            if code in (6,109,232,233):
                raise NotReady('Codex disconnected; waiting to reconnect.')
            raise ct.WinError(code)
        if available.value:
            try:
                chunk=self.pipe.read(min(available.value,1024*1024))
                if not chunk:
                    raise NotReady('Codex disconnected while reading; waiting to reconnect.')
                self.buffer.extend(chunk)
            except OSError as error:
                if self.disconnected_error(error):
                    raise NotReady('Codex disconnected while reading; waiting to reconnect.') from error
                raise
        while len(self.buffer) >= 4:  # Frames can be split or combined by the named pipe.
            size, = struct.unpack_from('<I', self.buffer)
            if size > 16*1024*1024:
                raise RuntimeError('Unexpected local protocol frame size.')
            if len(self.buffer) < size+4:
                break
            message = json.loads(self.buffer[4:size+4])
            del self.buffer[:size+4]
            if message.get('type') != 'response' or message.get('requestId') != self.request_id:
                continue  # Do not retain or log unrelated broadcasts or their parameters.
            self.client_id = (message.get('result') or {}).get('clientId')
            if message.get('error') or message.get('version', 0) != 0 or not isinstance(self.client_id, str):
                raise RuntimeError('Own client initialization was rejected or protocol changed.')

    def send(self, message):
        assert message['method'] in ('initialize', 'query-cache-invalidate'), 'Unexpected outbound IPC operation.'
        data = json.dumps(message, separators=(',', ':')).encode('utf-8')
        payload = struct.pack('<I', len(data))+data
        try:
            written = self.pipe.write(payload)
        except OSError as error:
            if self.disconnected_error(error):
                raise NotReady('Codex disconnected while refreshing; waiting to reconnect.') from error
            raise
        if written != len(payload):
            raise RuntimeError('Local Pet refresh packet was not fully written.')

    def refresh(self):
        self.pump()
        self.send({'type': 'broadcast', 'method': 'query-cache-invalidate', 'version': 0,
                   'sourceClientId': self.client_id,
                   'params': {'queryKey': ['custom-avatars', 'by-id', PET_ID]}})

    def close(self):
        self.pipe.close()

    def disconnected_error(self,error):
        if isinstance(error,BrokenPipeError) or error.errno==errno.EPIPE or getattr(error,'winerror',None) in (109,232,233):
            return True
        if error.errno==errno.EINVAL:
            available=wt.DWORD()
            alive=kernel.PeekNamedPipe(self.handle,None,0,None,ct.byref(available),None)
            return not alive and ct.get_last_error() in (6,109,232,233)
        return False


def installed_version():
    command="Get-AppxPackage -Name 'OpenAI.Codex' | Sort-Object Version -Descending | Select-Object -First 1 -ExpandProperty Version"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
        capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Cannot read the installed Codex package version.')
    value=result.stdout.strip()
    return value if re.fullmatch(r'\d+\.\d+\.\d+\.\d+',value) else None


def check_version(allow_untested=False):
    version=installed_version()
    if version is None:
        raise NotReady('Official Codex MSIX installation was not found.')
    if version!=APP_VERSION and not allow_untested:
        raise UnsupportedVersion(f'Codex {version} is untested; supported: {APP_VERSION}. Use --allow-untested only after reading docs/compatibility.md.')
    return version


def controller_running():
    kernel.OpenMutexW.argtypes=[wt.DWORD,wt.BOOL,wt.LPCWSTR]
    kernel.OpenMutexW.restype=wt.HANDLE
    handle=kernel.OpenMutexW(0x100000,False,MUTEX)
    if handle:
        kernel.CloseHandle(handle)
        return True
    if ct.get_last_error()!=2:
        raise ct.WinError(ct.get_last_error())
    return False


@contextmanager
def single_controller():
    kernel.CreateMutexW.argtypes=[ct.c_void_p,wt.BOOL,wt.LPCWSTR]
    kernel.CreateMutexW.restype=wt.HANDLE
    handle=kernel.CreateMutexW(None,False,MUTEX)
    if not handle:
        raise ct.WinError(ct.get_last_error())
    duplicate=ct.get_last_error()==183
    try:
        yield not duplicate
    finally:
        kernel.CloseHandle(handle)
