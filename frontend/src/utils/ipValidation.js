function isValidIpv4Address(value) {
  if (typeof value !== 'string') {
    return false
  }

  const trimmed = value.trim()
  const parts = trimmed.split('.')

  if (parts.length !== 4) {
    return false
  }

  return parts.every((part) => {
    if (!/^\d+$/.test(part)) {
      return false
    }

    if (part.length > 1 && part.startsWith('0')) {
      return false
    }

    const number = Number(part)
    return number >= 0 && number <= 255
  })
}

function isValidIpv4Cidr(value) {
  if (typeof value !== 'string') {
    return false
  }

  const trimmed = value.trim()
  const [ip, prefix, ...rest] = trimmed.split('/')

  if (!ip || !prefix || rest.length > 0) {
    return false
  }

  if (!isValidIpv4Address(ip) || !/^\d+$/.test(prefix)) {
    return false
  }

  const prefixNumber = Number(prefix)
  return prefixNumber >= 0 && prefixNumber <= 32
}

function validateStaticNetworkConfig(vmIp, vmGateway) {
  if (!isValidIpv4Cidr(vmIp)) {
    return 'Static IP는 192.168.2.100/24 같은 CIDR 형식으로 입력해야 합니다.'
  }

  if (!isValidIpv4Address(vmGateway)) {
    return 'Gateway는 192.168.2.1 같은 올바른 IPv4 주소여야 합니다.'
  }

  return null
}

export { isValidIpv4Address, isValidIpv4Cidr, validateStaticNetworkConfig }
