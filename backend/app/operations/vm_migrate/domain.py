"""First migration scope: same hardware/version, shared NFS and one unchanged NIC."""
import re
from pydantic import BaseModel, ConfigDict, Field
from app.operations.core.domain import operation_digest

ID = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'
CONFIG_KEYS = frozenset('digest name description cores sockets cpu memory balloon numa scsihw scsi0 ide2 net0 bios machine boot bootdisk ostype agent ciuser cipassword sshkeys citype ciupgrade ipconfig0 nameserver searchdomain serial0 vga onboot protection smbios1 vmgenid meta tags startup tablet template'.split())


class MigrateError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}
    def to_detail(self):
        return {'code':self.code,'message':str(self),'details':self.details}


class MigrateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    destination_node: str = Field(pattern=rf'^{ID}$')
    idempotency_key: str = Field(min_length=1,max_length=160,pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_name: str = Field(min_length=1,max_length=255)
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1,max_length=400)
    migration_acknowledged: bool


def validate_target(node_id, vmid, destination_node):
    if (not isinstance(node_id,str) or not re.fullmatch(ID,node_id) or not isinstance(destination_node,str)
            or not re.fullmatch(ID,destination_node) or node_id==destination_node
            or type(vmid) is not int or not 100<=vmid<=999999999):
        raise MigrateError('VM_MIGRATE_TARGET_INVALID','서로 다른 원본·목적 node와 VMID를 확인하세요.',422)


def device_options(raw):
    pairs = [part.split('=',1) for part in raw.split(',')] if isinstance(raw,str) else []
    if not pairs or any(len(pair)!=2 or not pair[0] or not pair[1] for pair in pairs) or len(dict(pairs))!=len(pairs):
        raise MigrateError('VM_MIGRATE_CONFIG_UNSUPPORTED','장치 옵션을 확인할 수 없습니다.')
    return dict(pairs)


def identity(config, status, pending, snapshots, *, vmid):
    if (status.get('status')!='stopped' or str(config.get('onboot',0))!='0'
            or str(config.get('template',0))!='0' or config.get('lock')):
        raise MigrateError('VM_MIGRATE_NOT_STOPPED','정지·자동 시작 해제·잠금 없는 일반 VM만 이동합니다.')
    ha=status.get('ha')
    if not isinstance(ha,dict) or type(ha.get('managed')) not in (int,bool) or ha['managed']!=0:
        raise MigrateError('VM_MIGRATE_HA_UNSUPPORTED','HA 비관리 상태를 확인한 VM만 이동합니다.')
    if any('pending' in row or row.get('delete') for row in pending) or [row.get('name') for row in snapshots]!=['current']:
        raise MigrateError('VM_MIGRATE_PENDING_OR_SNAPSHOTS','대기 설정·snapshot이 없는 VM만 지원합니다.')
    if (set(config)-CONFIG_KEYS or config.get('bios','seabios')!='seabios'
            or config.get('serial0','socket')!='socket' or 'custom-' in str(config.get('cpu',''))
            or config.get('vga','std') not in {'std','serial0','qxl','virtio','none'}):
        raise MigrateError('VM_MIGRATE_CONFIG_UNSUPPORTED','표준 SeaBIOS·단일 disk/NIC·host 장치 없는 VM만 지원합니다.')
    digest,name=config.get('digest'),config.get('name')
    if not isinstance(digest,str) or not re.fullmatch(r'[a-fA-F0-9]{40}',digest) or not isinstance(name,str) or not 1<=len(name)<=255:
        raise MigrateError('VM_MIGRATE_IDENTITY_UNAVAILABLE','VM 이름·설정 변경 감지값을 확인할 수 없습니다.',503)
    volumes=[]
    for slot,suffix in [('scsi0',r'disk-[0-9]+'),('ide2','cloudinit')]:
        parts=config.get(slot,'').split(',') if isinstance(config.get(slot),str) else []
        match=re.fullmatch(rf'({ID}):{vmid}/vm-{vmid}-{suffix}\.(raw|qcow2)',parts[0]) if parts else None
        opts=device_options(','.join(parts[1:])) if len(parts)>1 else {}
        if (not match or opts.get('shared','0')!='0' or opts.get('ro','0')!='0'
                or slot=='scsi0' and opts.get('media')=='cdrom' or slot=='ide2' and opts.get('media')!='cdrom'):
            raise MigrateError('VM_MIGRATE_DISK_UNSUPPORTED','정확한 VM 소유 scsi0·ide2 cloud-init을 확인하세요.')
        size=None
        if slot=='scsi0':
            value=re.fullmatch(r'([1-9][0-9]*)([MGT])',opts.get('size',''))
            if not value:raise MigrateError('VM_MIGRATE_DISK_UNSUPPORTED','root disk의 가상 용량을 확인하세요.')
            size=int(value[1])*1024**{'M':2,'G':3,'T':4}[value[2]]
        volumes.append({'slot':slot,'volume_id':parts[0],'storage_id':match[1],'format':match[2],'configured_size_bytes':size})
    nic=device_options(config.get('net0'))
    if (not {'virtio','bridge'}<=set(nic)<={'virtio','bridge','firewall','link_down'}
            or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',nic['virtio']) or not re.fullmatch(ID,nic['bridge'])
            or nic.get('firewall','0') not in {'0','1'} or nic.get('link_down','0') not in {'0','1'}):
        raise MigrateError('VM_MIGRATE_NETWORK_UNSUPPORTED','VLAN/trunk/추가 옵션 없는 단일 virtio net0만 지원합니다.')
    return {'vmid':vmid,'name':name,'status':'stopped','onboot':0,'ha_managed':False,'digest':digest,
        'config_fingerprint':operation_digest({key:value for key,value in config.items() if key!='digest'}),
        'volumes':volumes,'nic':nic}


def check_preconditions(value, destination):
    if (not isinstance(value,dict) or type(value.get('running')) not in (int,bool) or value['running']!=0
            or not isinstance(value.get('allowed_nodes'),list) or destination not in value['allowed_nodes']
            or value.get('local_disks')!=[] or value.get('local_resources')!=[]
            or value.get('mapped-resources',[])!=[] or value.get('mapped-resource-info',{})!={}
            or value.get('dependent-ha-resources',[])!=[]
            or not isinstance(value.get('not_allowed_nodes'),dict) or value['not_allowed_nodes'].get(destination)):
        raise MigrateError('VM_MIGRATE_PRECONDITION_BLOCKED','PVE의 이동 가능 노드·정지·공유 자원 조건을 확인하세요.')
    return {'destination_allowed':True,'local_disks':False,'local_resources':False,'ha_dependencies':False}


def check_expected(before, request):
    if request.migration_acknowledged is not True or request.confirmation!=f"{before['vmid']}/{before['name']}/{before['node_id']}->{request.destination_node}":
        raise MigrateError('VM_MIGRATE_CONFIRMATION_REQUIRED','VMID/이름/원본->목적 node와 이동 영향을 확인하세요.',422)
    if before['name']!=request.expected_name or before['review_digest']!=request.expected_review_digest:
        raise MigrateError('VM_MIGRATE_STATE_CHANGED','검토한 VM·공유 자원·노드 조건이 변경됐습니다. 다시 검토하세요.')


def request_body(destination_node):
    return {'target':destination_node,'online':0,'with-local-disks':0,'force':0}


def request_allowed(method,pieces,data,scope):
    return (method=='POST' and len(pieces)==5 and pieces[2]=='qemu' and pieces[4]=='migrate'
        and pieces[3].isdigit() and int(pieces[3]) in scope['vmids'] and isinstance(data,dict)
        and data.get('target') in scope['nodes'] and data['target']!=pieces[1]
        and data==request_body(data['target']) and all(type(data[key]) is int for key in ('online','with-local-disks','force')))


def task_reference(value, *, node_id, vmid):
    if not isinstance(value,str) or len(value)>512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:qmigrate:{vmid}:[A-Za-z0-9_.@!+-]+:',value):
        raise MigrateError('VM_MIGRATE_TASK_UNKNOWN','정확한 원본 node/VM의 이동 task를 확인하지 못했습니다. 자동 재이동하지 마세요.',503)
    return value
