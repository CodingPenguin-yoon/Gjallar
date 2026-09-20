"""Pure request policy for explicitly scoped managed capabilities."""
import re


def visible_vmids(scope):
    return set(scope["vmids"]) | set(scope.get("template_vmids", [])) | set(scope.get("create_vmids", [])) | set(scope.get("clone_vmids", [])) | set(scope.get("image_vmids", [])) | set(scope.get("restore_vmids", []))


def create_request_allowed(method, pieces, data, scope):
    if len(pieces) < 5 or pieces[2] != "qemu" or not pieces[3].isdigit():
        return False
    vmid = int(pieces[3])
    if pieces[4:] == ["clone"] and method == "POST":
        return (vmid in scope.get("template_vmids", []) and isinstance(data, dict)
                and set(data) == {"newid", "name", "target", "storage", "full"}
                and type(data["newid"]) is int and data["newid"] in scope.get("create_vmids", [])
                and data["target"] in scope["nodes"] and data["storage"] in scope["storages"]
                and type(data["full"]) is int and data["full"] == 1
                and isinstance(data["name"], str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,62}", data["name"])))
    if vmid not in scope.get("create_vmids", []):
        return False
    if method == "PUT" and pieces[4:] == ["config"]:
        required = {"cores", "memory", "agent", "onboot", "net0", "ciuser", "ipconfig0"}
        return (isinstance(data, dict) and required <= set(data) <= required | {"sshkeys"}
                and type(data["cores"]) is int and 1 <= data["cores"] <= 128
                and type(data["memory"]) is int and 128 <= data["memory"] <= 1048576
                and data["agent"] == "enabled=1" and data["onboot"] == 0
                and data["net0"] in {f"virtio,bridge={bridge}" for bridge in scope["bridges"]})
    if method == "PUT" and pieces[4:] == ["resize"]:
        return (isinstance(data, dict) and set(data) == {"disk", "size"}
                and isinstance(data["disk"], str) and bool(re.fullmatch(r"(?:scsi|virtio|sata|ide)[0-9]+", data["disk"]))
                and isinstance(data["size"], str) and bool(re.fullmatch(r"[1-9][0-9]*G", data["size"])))
    if method == "POST" and pieces[4:] in (["status", "start"], ["status", "shutdown"]):
        return data is None or data == {}
    if method == "POST" and pieces[4:] == ["agent", "exec"]:
        return data == [("command", "cloud-init"), ("command", "status"), ("command", "--wait")]
    return False


def network_request_allowed(method, pieces, data, scope):
    if (method != "PUT" or len(pieces) != 5 or pieces[2] != "qemu" or pieces[4] != "config"
            or not pieces[3].isdigit() or int(pieces[3]) not in set(scope["vmids"]) | set(scope.get("create_vmids", []))
            or not isinstance(data, dict) or set(data) != {"net0", "digest"}
            or not isinstance(data["digest"], str) or not re.fullmatch(r"[a-fA-F0-9]{40}", data["digest"])
            or not isinstance(data["net0"], str)):
        return False
    pairs = [part.split("=", 1) for part in data["net0"].split(",")]
    if not pairs or any(len(pair) != 2 or not pair[1] for pair in pairs):
        return False
    options = dict(pairs)
    return (len(options) == len(pairs) and options.get("bridge") in scope["bridges"] and "trunks" not in options
            and bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", pairs[0][1]))
            and ("tag" not in options or options["tag"].isdigit() and 1 <= int(options["tag"]) <= 4094))


def clone_request_allowed(method, pieces, data, scope):
    return (method == 'POST' and len(pieces) == 5 and pieces[2] == 'qemu' and pieces[4] == 'clone'
            and pieces[3].isdigit() and int(pieces[3]) in scope['vmids']
            and isinstance(data, dict) and set(data) == {'newid', 'name', 'storage', 'format', 'full', 'description'}
            and type(data['newid']) is int and data['newid'] in scope.get('clone_vmids', [])
            and data['newid'] != int(pieces[3]) and data['storage'] in scope['storages']
            and data['format'] in {'raw', 'qcow2'} and type(data['full']) is int and data['full'] == 1
            and isinstance(data['name'], str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', data['name']))
            and isinstance(data['description'], str) and bool(re.fullmatch(r'vm-clone-[a-f0-9]{64}', data['description'])))
