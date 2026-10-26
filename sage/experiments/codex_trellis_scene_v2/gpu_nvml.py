"""Small read-only NVML probe; no torch import or subprocess per sample.

Uses the driver ABI documented at https://docs.nvidia.com/deploy/nvml-api/.
Missing process or memory telemetry raises, retaining fail-closed admission.
"""
import ctypes as C


class Memory(C.Structure):
    _fields_ = [('total', C.c_ulonglong), ('free', C.c_ulonglong), ('used', C.c_ulonglong)]


class Process(C.Structure):
    _fields_ = [('pid', C.c_uint), ('usedGpuMemory', C.c_ulonglong),
                ('gpuInstanceId', C.c_uint), ('computeInstanceId', C.c_uint)]


def inventory():
    lib = C.CDLL('libnvidia-ml.so.1')
    def checked(name, *args):
        result = getattr(lib, name)(*args)
        if result != 0:
            raise RuntimeError(f'{name}: NVML error {result}')
    checked('nvmlInit_v2')
    try:
        count = C.c_uint(); checked('nvmlDeviceGetCount_v2', C.byref(count))
        rows = []
        for i in range(count.value):
            handle = C.c_void_p(); checked('nvmlDeviceGetHandleByIndex_v2', C.c_uint(i), C.byref(handle))
            uuid = C.create_string_buffer(96); name = C.create_string_buffer(256)
            checked('nvmlDeviceGetUUID', handle, uuid, C.c_uint(len(uuid)))
            checked('nvmlDeviceGetName', handle, name, C.c_uint(len(name)))
            memory = Memory(); checked('nvmlDeviceGetMemoryInfo', handle, C.byref(memory))
            processes = {}
            for kind, function in [('C', 'nvmlDeviceGetComputeRunningProcesses_v3'),
                                   ('G', 'nvmlDeviceGetGraphicsRunningProcesses_v3')]:
                n = C.c_uint(0); result = getattr(lib, function)(handle, C.byref(n), None)
                if result not in (0, 7): raise RuntimeError(f'{function}: NVML error {result}')
                if not n.value: continue
                for attempt in range(3):
                    capacity = max(n.value * 2, 32); buffer = (Process * capacity)(); n.value = capacity
                    result = getattr(lib, function)(handle, C.byref(n), buffer)
                    if result == 7: continue
                    if result: raise RuntimeError(f'{function}: NVML error {result}')
                    for process in buffer[:n.value]:
                        if process.usedGpuMemory == 2**64 - 1: raise RuntimeError('Unavailable process GPU memory')
                        previous = processes.get(process.pid)
                        amount = process.usedGpuMemory
                        if previous:
                            amount = max(amount, previous['_bytes'])
                            process_kind = previous['type'] + kind
                        else: process_kind = kind
                        processes[process.pid] = {'pid': str(process.pid), 'type': process_kind,
                            'used_memory': f'{amount / 1048576:.12g} MiB', '_bytes': amount}
                    break
                else: raise RuntimeError('GPU process list changed too quickly')
            for process in processes.values(): process.pop('_bytes')
            rows.append({'available': True, 'provider': 'nvml-direct-v3', 'gpu_index': i,
                'uuid': uuid.value.decode(), 'name': name.value.decode(),
                'memory_total_bytes': memory.total, 'memory_free_bytes': memory.free,
                'memory_used_bytes': memory.used, 'process_pids': sorted(processes),
                'processes': list(processes.values())})
        if not rows: raise RuntimeError('GPU inventory is empty')
        return rows
    finally:
        checked('nvmlShutdown')
