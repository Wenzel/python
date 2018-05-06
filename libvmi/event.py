import ctypes
from builtins import object, super
from enum import Enum

from _libvmi import ffi, lib


EVENTS_VERSION = lib.VMI_EVENTS_VERSION


class EventType(Enum):
    INVALID = lib.VMI_EVENT_INVALID
    MEMORY = lib.VMI_EVENT_MEMORY
    REGISTER = lib.VMI_EVENT_REGISTER
    SINGLESTEP = lib.VMI_EVENT_SINGLESTEP
    INTERRUPT = lib.VMI_EVENT_INTERRUPT
    GUEST_REQUEST = lib.VMI_EVENT_GUEST_REQUEST
    CPUID = lib.VMI_EVENT_CPUID
    DEBUG_EXCEPTION = lib.VMI_EVENT_DEBUG_EXCEPTION
    PRIVILEGED_CALL = lib.VMI_EVENT_PRIVILEGED_CALL
    DESCRIPTOR_ACCESS = lib.VMI_EVENT_DESCRIPTOR_ACCESS


class EventResponse(Enum):
    NONE = lib.VMI_EVENT_RESPONSE_NONE
    EMULATE = lib.VMI_EVENT_RESPONSE_EMULATE
    EMULATE_NOWRITE = lib.VMI_EVENT_RESPONSE_EMULATE_NOWRITE
    SET_EMUL_READ_DATA = lib.VMI_EVENT_RESPONSE_SET_EMUL_READ_DATA
    DENY = lib.VMI_EVENT_RESPONSE_DENY
    TOGGLE_SINGLESTEP = lib.VMI_EVENT_RESPONSE_TOGGLE_SINGLESTEP
    SLAT_ID = lib.VMI_EVENT_RESPONSE_SLAT_ID
    VMM_PAGETABLE_ID = lib.VMI_EVENT_RESPONSE_VMM_PAGETABLE_ID
    SET_REGISTERS = lib.VMI_EVENT_RESPONSE_SET_REGISTERS
    SET_EMUL_INSN = lib.VMI_EVENT_RESPONSE_SET_EMUL_INSN
    GET_NEXT_INTERRUPT = lib.VMI_EVENT_RESPONSE_GET_NEXT_INTERRUPT


class MemAccess(Enum):
    INVALID = lib.VMI_MEMACCESS_INVALID
    N = lib.VMI_MEMACCESS_N
    R = lib.VMI_MEMACCESS_R
    W = lib.VMI_MEMACCESS_W
    X = lib.VMI_MEMACCESS_X
    RW = lib.VMI_MEMACCESS_RW
    RX = lib.VMI_MEMACCESS_RX
    WX = lib.VMI_MEMACCESS_WX
    RWX = lib.VMI_MEMACCESS_RWX
    W2X = lib.VMI_MEMACCESS_W2X
    RWX2N = lib.VMI_MEMACCESS_RWX2N


class RegAccess(Enum):
    INVALID = lib.VMI_REGACCESS_INVALID
    N = lib.VMI_REGACCESS_N
    R = lib.VMI_REGACCESS_R
    W = lib.VMI_REGACCESS_W
    RW = lib.VMI_REGACCESS_RW


@ffi.def_extern()
def generic_event_callback(cffi_vmi, cffi_event):
    # get generic event data dict
    generic_data = ffi.from_handle(cffi_event.data)
    # get true callback
    event = generic_data['event']
    vmi = generic_data['vmi']
    callback = event.get_callback()
    # call callback with the right Python objects as args
    event_response = callback(vmi, event)
    if event_response is None:
        event_response = EventResponse.NONE
    return event_response.value


class Event(object):

    version = EVENTS_VERSION
    type = None

    def __init__(self, callback, slat_id=0, data=None):
        self.slat_id = slat_id
        self.data = data
        self.py_callback = callback
        self.generic_data = {
            'vmi': None,
            'event': self,
        }
        self.generic_handle = None
        self.cffi_event = ffi.new("vmi_event_t *")

    def set_vmi_instance(self, vmi_instance):
        self.generic_data['vmi'] = vmi_instance

    def get_callback(self):
        return self.py_callback

    def to_cffi(self):
        self.cffi_event.version = self.version
        self.cffi_event.type = self.type.value
        self.cffi_event.slat_id = self.slat_id
        # convert our generic_data dict to a CFFI void* handle
        # and keep a reference to the handle in self.generic_handle
        self.generic_handle = ffi.new_handle(self.generic_data)
        # assign the handle to the event data
        self.cffi_event.data = self.generic_handle
        self.cffi_event.callback = lib.generic_event_callback

    def to_dict(self):
        return {
            'version': self.version,
            'type': self.type.name,
            'slat_id': self.slat_id,
            'data': self.data,
            'vcpu_id': self.cffi_event.vcpu_id,
            'x86_regs': {
                'rax': hex(self.cffi_event.x86_regs.rax),
                'rsp': hex(self.cffi_event.x86_regs.rsp),
                'rip': hex(self.cffi_event.x86_regs.rip),
            }
        }


class MemEvent(Event):

    type = EventType.MEMORY

    def __init__(self, in_access, callback, gfn=0, generic=False, slat_id=0,
                 data=None):
        super().__init__(callback, slat_id, data)
        self.in_access = in_access
        self.generic = generic
        self.gfn = gfn

    def to_cffi(self):
        super().to_cffi()
        self.cffi_event.mem_event.in_access = self.in_access.value
        self.cffi_event.mem_event.generic = int(self.generic)
        if self.generic:
            self.cffi_event.mem_event.gfn = ctypes.c_ulonglong(~0).value
        else:
            self.cffi_event.mem_event.gfn = self.gfn
        return self.cffi_event

    def to_dict(self):
        d = super().to_dict()
        d['in_access'] = self.in_access.name
        d['out_access'] = MemAccess(self.cffi_event.mem_event.out_access).name
        d['gptw'] = bool(self.cffi_event.mem_event.gptw)
        d['gla_valid'] = bool(self.cffi_event.mem_event.gla_valid)
        d['gla'] = hex(self.cffi_event.mem_event.gla)
        d['offset'] = hex(self.cffi_event.mem_event.offset)
        return d


class SingleStepEvent(Event):

    type = EventType.SINGLESTEP

    def __init__(self, vcpus, callback, enable=True, slat_id=0, data=None):
        super().__init__(callback, slat_id, data)
        self.vcpus = 0
        for vcpu in vcpus:
            mask = 1 << vcpu
            self.vcpus |= mask
        self.enable = enable

    def to_cffi(self):
        super().to_cffi()
        self.cffi_event.ss_event.vcpus = self.vcpus
        self.cffi_event.ss_event.enable = int(self.enable)
        return self.cffi_event


class RegEvent(Event):

    type = EventType.REGISTER

    def __init__(self, register, in_access, callback, equal=None, slat_id=0,
                 data=None):
        super().__init__(callback, slat_id, data)
        self.register = register
        self.in_access = in_access
        self.equal = equal
        if self.equal is None:
            self.equal = 0

    def to_cffi(self):
        super().to_cffi()
        self.cffi_event.reg_event.reg = self.register.value
        self.cffi_event.reg_event.in_access = self.in_access.value
        self.cffi_event.reg_event.equal = self.equal
        return self.cffi_event

    def to_dict(self):
        d = super().to_dict()
        d['in_access'] = self.in_access.name
        d['out_access'] = RegAccess(self.cffi_event.reg_event.out_access).name
        d['value'] = hex(self.cffi_event.reg_event.value)
        d['previous'] = hex(self.cffi_event.reg_event.previous)
        return d
