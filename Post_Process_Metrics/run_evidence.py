"""Verify copied run configuration and extract initialization activation receipts."""
import hashlib
import json
from pathlib import Path


def verified_digest(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() == expected:
        return 'exact'
    # Git autocrlf may normalize Windows text. Reconstruct its original bytes and
    # still require exact agreement with the unchanged recorded checksum.
    windows = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    if hashlib.sha256(windows).hexdigest() == expected:
        return 'exact-after-CRLF-reconstruction'
    raise ValueError(f'Configuration checksum mismatch: {path}')


def read_run_evidence(marker, fpart):
    marker = marker.resolve()
    pointer = json.loads(marker.read_text(encoding='utf-8-sig'))
    root = marker.parent
    folder = (root/Path(pointer['directory'].replace('\\', '/'))).resolve()
    if not folder.is_relative_to(root):
        raise ValueError('Configuration directory escapes its run folder')
    resolved_path = folder/'resolved.json'
    verification = {str(resolved_path): verified_digest(resolved_path, pointer['resolved_sha256'])}
    data = json.loads(resolved_path.read_text(encoding='utf-8-sig'))
    if data['schema_version'] != 1:
        raise ValueError('Unsupported resolved configuration schema')
    for relative, checksum in data['table_sha256'].items():
        path = (folder/relative.replace('\\', '/')).resolve()
        if not path.is_relative_to(folder):
            raise ValueError('Table path escapes configuration folder')
        verification[str(path)] = verified_digest(path, checksum)
    settings = data['rules']['firo_space']['settings']
    if settings.get('interpolate_gaps_up_to_days', 0) != 0:
        raise ValueError('FIRO gap interpolation is not yet supported by recreation processing')
    activation, receipts = {}, []
    for path in sorted((folder/'initialization-receipts').glob('*.json')):
        receipt = json.loads(path.read_text(encoding='utf-8-sig'))
        if receipt.get('module') != 'FIRO_SPACE' or receipt.get('output_fpart') != fpart:
            continue
        if receipt.get('member') is not None:
            continue  # This workflow handles POR only.
        if (receipt.get('configuration_id') != pointer['id']
                or receipt.get('resolved_sha256') != pointer['resolved_sha256']):
            raise ValueError(f'Receipt does not match the selected configuration: {path}')
        reservoir, enabled = receipt['reservoir'], receipt.get('active')
        if not isinstance(enabled, bool):
            raise ValueError(f'Receipt lacks a boolean activation flag: {path}')
        if reservoir in activation and activation[reservoir] != enabled:
            raise ValueError(f'Conflicting activation receipts for {reservoir}')
        activation[reservoir] = enabled
        receipts.append(str(path))
    if not receipts:
        raise ValueError('No matching POR FIRO initialization receipts')
    target = (folder/data['table_paths']['firoSpaceConfigCSV'].replace('\\', '/')).resolve()
    if str(target) not in verification:
        raise ValueError('FIRO table is not covered by the recorded table checksums')
    return target, activation, dict(marker=str(marker), configuration_id=pointer['id'],
                                     resolved_sha256=pointer['resolved_sha256'],
                                     verification=verification, receipts=receipts)
