export const permissionGroups = [
  ['VM 일상 관리', [
    ['power', '시작·정상 종료'], ['compute', 'CPU·메모리 변경'],
    ['disk', '디스크 확장'], ['network', 'NIC bridge·VLAN 변경'],
    ['clone', '일반 VM 복제'], ['delete', 'VM 삭제'], ['console', '웹 콘솔'],
  ]],
  ['VM 생성·템플릿', [
    ['create', '템플릿에서 VM 생성'], ['template', '정지 VM을 템플릿으로 전환'],
    ['image_build', '공식 이미지로 템플릿 제작'], ['image_cleanup', '제작한 템플릿·업로드 원본 정리'],
  ]],
  ['백업·복원·이동', [
    ['backup', 'VM 백업'], ['restore', '별도 VM으로 백업 복원'], ['migrate', '정지 VM 노드 이동'],
  ]],
  ['호스트 설정', [
    ['host_storage', '호스트 스토리지 설정'], ['host_network', '호스트 bridge 설정·노드 전체 반영'],
  ]],
]

export function connectionFeatures(form) {
  return ['read', ...permissionGroups.flatMap(([, items]) => items.map(([name]) => name)).filter(name => form.get(name))]
}
