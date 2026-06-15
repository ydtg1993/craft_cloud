"""同步相关的域逻辑工具函数。

这些函数理解目录树、同步根、路径映射等业务概念，
属于 services 层而非纯 core 基础设施。
"""
from pathlib import Path


def get_sync_root_id_for_path(db, config, root_path):
    sync_settings = config.get("auto_sync_settings", {})
    folders = sync_settings.get("folders", {})
    cfg = folders.get(root_path, {})
    return cfg.get("target_dir_id")


def is_descendant(db, dir_id, ancestor_id):
    current = dir_id
    while current:
        if current == ancestor_id:
            return True
        parent = db.dirs.get_parent_id(current)
        if parent is None:
            break
        current = parent
    return False


def get_sync_root_for_dir(db, config, dir_id):
    if dir_id == 0:
        return None
    sync_settings = config.get("auto_sync_settings", {})
    folders = sync_settings.get("folders", {})
    for root_path, cfg in folders.items():
        root_dir_id = cfg.get("target_dir_id")
        if root_dir_id == dir_id:
            return root_path
        if is_descendant(db, dir_id, root_dir_id):
            return root_path
    return None


def get_local_path_for_dir(db, config, dir_id):
    if dir_id == 0:
        return None
    root_path = get_sync_root_for_dir(db, config, dir_id)
    if not root_path:
        return None
    path_parts = db.dirs.get_path_to_directory(dir_id)
    root_id = get_sync_root_id_for_path(db, config, root_path)
    rel_parts = []
    found_root = False
    for pid, name in path_parts:
        if pid == root_id:
            found_root = True
            continue
        if found_root and name != "根目录":
            rel_parts.append(name)
    if not rel_parts:
        return root_path
    return Path(root_path).joinpath(*rel_parts)
