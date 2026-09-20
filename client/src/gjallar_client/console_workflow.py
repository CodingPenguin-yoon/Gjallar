"""Guide the operator to an authenticated web console without exporting a session."""
from .errors import ClientError
from .workflows import identifier, segment


def guide(app, *, vmid, node):
    node = identifier(node)
    result = app.request(f'nodes/{segment(node)}/vms/{vmid}/console', operator=True)
    review = result['data']
    if not isinstance(review, dict) or review.get('target') != {'node_id': node, 'vmid': vmid}:
        raise ClientError('TARGET_CHANGED', '조회한 콘솔 대상이 선택한 VM과 다릅니다.', 8)
    _, profile = app.connections.get(app.connection_name)
    return {**result, 'data': {**review, 'web_url': f"{profile['origin']}/instances/{vmid}#console"},
            'message': '웹 주소를 열고 브라우저에서 로그인한 뒤 콘솔 접속 준비·연결을 선택하세요. CLI 로그인은 브라우저로 전달하지 않습니다.',
            'exit_code': 0}
