const GENERAL_VM_PROFILE = {
  profileId: 'general-vm',
  label: 'General VM',
  createEnabled: true,
}

export function buildCreateVmDefaults() {
  return {
    profileId: GENERAL_VM_PROFILE.profileId,
    hardware: {
      cpu: 2,
      memoryMb: 4096,
      diskGb: 40,
    },
    network: {
      ipMode: 'static',
      networkId: 'server-net',
      nodeBridges: {
        yoonmanserver2: 'vmbr0',
        yoonmanserver3: 'vmbr0',
      },
    },
    access: {
      cloudInitUser: 'yoon',
      passwordLogin: false,
    },
    profileOptions: [{ ...GENERAL_VM_PROFILE }],
  }
}
