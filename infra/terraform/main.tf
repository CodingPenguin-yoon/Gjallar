# Proxmox Provider 설정 (bpg/proxmox)
#
# 이 파일은 Proxmox 가상화 환경에 인프라를 배포하기 위한 Terraform 설정입니다.
# 환경변수를 통해 Proxmox API 인증 정보를 제공합니다.
#
# 필수 환경변수:
#   - TF_VAR_proxmox_api_url: Proxmox API URL (예: https://proxmox.example.com:8006/)
#   - TF_VAR_proxmox_api_token_id: Proxmox API Token ID (예: user@pam!token_name)
#   - TF_VAR_proxmox_api_token_secret: Proxmox API Token Secret

terraform {
  required_version = ">= 1.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.38"
    }
  }
}

# Proxmox Provider 설정
# bpg/proxmox provider는 기본 URL만 필요 (api2/json 제외)
locals {
  # /api2/json이 포함되어 있으면 제거
  proxmox_endpoint = replace(var.proxmox_api_url, "/api2/json", "")
}

provider "proxmox" {
  endpoint  = local.proxmox_endpoint
  api_token = "${var.proxmox_api_token_id}=${var.proxmox_api_token_secret}"
  insecure  = var.proxmox_tls_insecure
}

# 변수 정의
variable "proxmox_api_url" {
  description = "Proxmox API URL (예: https://192.168.1.100:8006/)"
  type        = string
}

variable "proxmox_api_token_id" {
  description = "Proxmox API Token ID (예: root@pam!terraform)"
  type        = string
  sensitive   = true
}

variable "proxmox_api_token_secret" {
  description = "Proxmox API Token Secret"
  type        = string
  sensitive   = true
}

variable "proxmox_tls_insecure" {
  description = "Proxmox TLS 검증 비활성화 여부"
  type        = bool
  default     = true
}

# VM 생성 변수
variable "vm_name" {
  description = "VM 이름"
  type        = string
  default     = ""
}

variable "target_node" {
  description = "Proxmox 노드 이름"
  type        = string
  default     = ""
}

variable "template_id" {
  description = "클론할 템플릿 ID (node/vmid 형식 또는 vmid만)"
  type        = string
  default     = ""
}

variable "cpu_cores" {
  description = "CPU 코어 수"
  type        = number
  default     = 2
}

variable "memory_gb" {
  description = "메모리 크기 (GB)"
  type        = number
  default     = 4
}

variable "disk_size_gb" {
  description = "디스크 크기 (GB)"
  type        = number
  default     = 50
}

variable "storage_id" {
  description = "스토리지 ID"
  type        = string
  default     = "local-lvm"
}

variable "network_ids" {
  description = "네트워크 브릿지 목록"
  type        = list(string)
  default     = ["vmbr0"]
}

variable "ssh_public_key" {
  description = "SSH 공개키 (VM에 주입)"
  type        = string
  default     = ""
}

variable "ssh_user" {
  description = "SSH 사용자 이름"
  type        = string
  default     = "root"
}

variable "vm_operation_timeout_seconds" {
  description = "VM clone/create/move/start 관련 타임아웃(초)"
  type        = number
  default     = 5400
}

variable "vm_stop_timeout_seconds" {
  description = "VM stop 타임아웃(초)"
  type        = number
  default     = 600
}

variable "vm_ip" {
  description = "VM 고정 IP 주소 (CIDR 형식: 192.168.1.100/24)"
  type        = string
  default     = ""
}

variable "vm_gateway" {
  description = "VM 게이트웨이 주소"
  type        = string
  default     = ""
}

# 템플릿 ID 파싱 (node/vmid 형식 지원)
locals {
  template_id_parts = split("/", var.template_id)
  clone_source_node = var.template_id != "" && length(local.template_id_parts) > 1 ? trimspace(local.template_id_parts[0]) : null
  clone_vm_id       = var.template_id != "" ? tonumber(length(local.template_id_parts) > 1 ? local.template_id_parts[1] : local.template_id_parts[0]) : 0
}

# Proxmox VM 리소스 생성
resource "proxmox_virtual_environment_vm" "instance" {
  count = var.vm_name != "" && var.target_node != "" ? 1 : 0

  name      = var.vm_name
  node_name = var.target_node

  # 템플릿 클론 설정
  dynamic "clone" {
    for_each = local.clone_vm_id > 0 ? [1] : []
    content {
      vm_id     = local.clone_vm_id
      node_name = local.clone_source_node
      full      = true
    }
  }

  cpu {
    cores   = var.cpu_cores
    sockets = 1
    type    = "host"
  }

  memory {
    dedicated = var.memory_gb * 1024
  }

  disk {
    datastore_id = var.storage_id
    interface    = "scsi0"
    size         = var.disk_size_gb
  }

  # 네트워크 설정 (여러 네트워크 지원)
  dynamic "network_device" {
    for_each = var.network_ids
    content {
      bridge = network_device.value
      model  = "virtio"
    }
  }

  # Cloud-init 설정
  initialization {
    datastore_id = var.storage_id

    # SSH 키 주입 (cloud-init user_account)
    dynamic "user_account" {
      for_each = var.ssh_public_key != "" ? [1] : []
      content {
        username = var.ssh_user
        keys     = [var.ssh_public_key]
      }
    }

    ip_config {
      ipv4 {
        # 고정 IP가 설정되면 사용, 아니면 DHCP
        address = var.vm_ip != "" ? var.vm_ip : "dhcp"
        gateway = var.vm_ip != "" && var.vm_gateway != "" ? var.vm_gateway : null
      }
    }
  }

  # QEMU Guest Agent 설정
  # 고정 IP 사용 시 agent 불필요, DHCP 사용 시 IP 조회를 위해 필요
  agent {
    enabled = var.vm_ip == "" # 고정 IP면 비활성화
    timeout = "2m"
  }

  # VM 시작 설정
  started = true
  on_boot = true

  # NFS 템플릿 복제/디스크 이동이 느린 환경을 고려해 타임아웃 상향
  timeout_clone       = var.vm_operation_timeout_seconds
  timeout_create      = var.vm_operation_timeout_seconds
  timeout_migrate     = var.vm_operation_timeout_seconds
  timeout_move_disk   = var.vm_operation_timeout_seconds
  timeout_reboot      = var.vm_operation_timeout_seconds
  timeout_shutdown_vm = var.vm_operation_timeout_seconds
  timeout_start_vm    = var.vm_operation_timeout_seconds
  timeout_stop_vm     = var.vm_stop_timeout_seconds

  lifecycle {
    ignore_changes = [
      disk,
      network_device,
    ]
  }
}

# VM 정보 출력
output "vm_ip" {
  description = "생성된 VM의 IP 주소"
  value = var.vm_ip != "" ? (
    # 고정 IP 설정된 경우: CIDR에서 IP만 추출 (192.168.1.100/24 -> 192.168.1.100)
    split("/", var.vm_ip)[0]
    ) : (
    # DHCP 사용 시: agent에서 가져온 IP
    length(proxmox_virtual_environment_vm.instance) > 0 ? (
      length(proxmox_virtual_environment_vm.instance[0].ipv4_addresses) > 1 ?
      proxmox_virtual_environment_vm.instance[0].ipv4_addresses[1][0] : null
    ) : null
  )
}

output "vm_id" {
  description = "생성된 VM의 ID"
  value       = length(proxmox_virtual_environment_vm.instance) > 0 ? proxmox_virtual_environment_vm.instance[0].vm_id : null
}

output "vm_name" {
  description = "생성된 VM의 이름"
  value       = length(proxmox_virtual_environment_vm.instance) > 0 ? proxmox_virtual_environment_vm.instance[0].name : null
}
