"""Independent byte readback of the prepared immutable artifact catalog."""
import os
import sys
from pathlib import Path
from .work import E,c,finish


def main(config):
    cfg=c.read(config);path=Path(cfg['manifest']);manifest=c.read(path)
    assert manifest['complete'] and Path(manifest['root'])==E
    missing=[];mismatches=[];checked=0;size=0
    for item in manifest['files']:
        target=E/item['path']
        if not target.is_file() or target.is_symlink():
            missing.append(item['path']);continue
        digest=c.sha(target)
        if digest!=item['sha256'] or target.stat().st_size!=item['bytes']:
            mismatches.append({'path':item['path'],'expected':item['sha256'],'actual':digest})
        checked+=1;size+=target.stat().st_size
    link_errors=[]
    for item in manifest['symlinks']:
        target=E/item['path']
        if not target.is_symlink() or os.readlink(target)!=item['link_target'] or target.exists()!=item['target_exists']:
            link_errors.append(item['path'])
    report={'passed':not missing and not mismatches and not link_errors,'manifest_sha256':c.sha(path),
        'regular_files_rehashed':checked,'logical_file_bytes_rehashed':size,
        'symlinks_checked':len(manifest['symlinks']),'missing':missing,'mismatches':mismatches,
        'symlink_errors':link_errors,'new_physics_steps':0,'new_render_passes':0,
        'scope':'Independent reread of every catalogued immutable file and symbolic-link target string. Mutable final control and post-manifest receipts are bound separately in FINAL_SEAL.'}
    c.write(E/cfg['output'],report)
    assert report['passed']
    finish(report)


if __name__=='__main__':main(sys.argv[1])
