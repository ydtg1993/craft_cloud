"""目录树全量对比同步任务。

扫描本地目录结构，与数据库中的记录对比，处理：
- 本地新增/删除/更名的文件和目录
- 本地迁移的文件（通过哈希匹配）
- TG 消息的上传/删除/编辑
"""
from pathlib import Path

from loguru import logger

from core.db_manager import compute_file_hash
from core.telegram_uploader import TelethonUploader
from core.utils import get_cache_dir
from core.media_utils import generate_media_cache
from core.translator import tr
from model.shared_types import SYNC_PENDING, SYNC_SUCCESS
from services.sync.base_sync_task import BaseSyncTask


class DirectorySyncTask(BaseSyncTask):
    """全量目录树对比同步任务。

    逻辑：
    1. 扫描本地目录结构，获取所有文件和子目录
    2. 与数据库中的目录结构对比，找出差异
    3. 根据差异进行同步：
       - 本地新增的文件/目录：在数据库中创建，并上传到TG
       - 本地删除的文件/目录：从数据库和TG中删除
       - 本地更名的文件/目录：更新数据库和TG
       - 本地迁移的文件：更新数据库中的目录ID，TG无需操作
    4. 禁止软件中直接对同步目录下的文件进行删除、更名、迁移、新增操作
    """

    # ── 主同步入口 ────────────────────────────────────────────

    def _do_sync(self, target_dir_id, telethon_cfg, folder_config):
        """执行全量目录树对比同步。"""
        # 1. 扫描本地目录结构
        local_structure = self._scan_local_directory()
        if not local_structure:
            self.signals.completed.emit(0)
            return

        # 2. 获取数据库中的当前结构
        db_structure = self._get_db_structure(target_dir_id)

        # 3. 比较并同步结构
        sync_result = self._sync_structures(
            local_structure, db_structure, target_dir_id, telethon_cfg
        )

        if self.stop_event.is_set():
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, status=SYNC_PENDING, _bg=True
            )
            self.signals.cancelled.emit()
        else:
            self.db.sync_status.upsert_sync_folder_status(
                self.folder_path, status=SYNC_SUCCESS, _bg=True
            )
            self.signals.completed.emit(sync_result["total_changes"])

    # ── 本地目录扫描 ──────────────────────────────────────────

    def _scan_local_directory(self):
        """扫描本地目录结构，返回目录树。"""
        structure = {
            "dirs": {},
            "files": {},
        }
        folder_path = Path(self.folder_path)
        for entry in folder_path.rglob('*'):
            if self.stop_event.is_set():
                return None
            if entry.is_dir():
                rel_dir = str(entry.relative_to(folder_path))
                structure["dirs"][rel_dir] = entry.name
            elif entry.is_file():
                try:
                    rel_file = str(entry.relative_to(folder_path))
                except ValueError:
                    continue
                file_path_str = str(entry)
                try:
                    file_size = entry.stat().st_size
                    file_hash = compute_file_hash(file_path_str)
                except OSError:
                    continue
                structure["files"][rel_file] = {
                    "name": entry.name,
                    "size": file_size,
                    "hash": file_hash,
                    "local_path": file_path_str,
                }
        return structure

    # ── 数据库结构获取 ────────────────────────────────────────

    def _get_db_structure(self, root_dir_id):
        """从数据库获取目录结构。"""
        structure = {
            "dirs": {},   # 相对路径 -> 目录ID
            "files": {},  # 相对路径 -> 文件信息
        }

        all_dirs = self.db.dirs.get_directories(parent_id=root_dir_id, recursive=True)
        for dir_id, dir_name, parent_id, is_sync in all_dirs:
            path_parts = self.db.dirs.get_path_to_directory(dir_id)
            rel_path = self._calculate_relative_path(path_parts, root_dir_id)
            if rel_path is not None:
                structure["dirs"][rel_path] = dir_id

        all_files = self.db.files.get_all_files_recursive(root_dir_id)
        for f in all_files:
            dir_path_parts = self.db.dirs.get_path_to_directory(f.directory_id)
            rel_dir = self._calculate_relative_path(dir_path_parts, root_dir_id)

            if rel_dir is not None:
                rel_file = str(Path(rel_dir) / f.display_name) if rel_dir else f.display_name
                structure["files"][rel_file] = {
                    "id": f.id,
                    "message_id": f.message_id,
                    "chat_id": f.chat_id,
                    "local_path": f.local_path,
                    "display_name": f.display_name,
                    "directory_id": f.directory_id,
                }

        return structure

    def _calculate_relative_path(self, path_parts, root_dir_id):
        """计算从同步根目录开始的相对路径。"""
        root_index = -1
        for i, (dir_id, dir_name) in enumerate(path_parts):
            if dir_id == root_dir_id:
                root_index = i
                break

        if root_index == -1:
            return None

        rel_parts = []
        for dir_id, dir_name in path_parts[root_index + 1:]:
            if dir_name != tr("Root"):
                rel_parts.append(dir_name)

        return str(Path(rel_parts[0]).joinpath(*rel_parts[1:])) if rel_parts else ""

    # ── 结构同步 ──────────────────────────────────────────────

    def _sync_structures(self, local_structure, db_structure, root_dir_id, telethon_cfg):
        """同步本地结构和数据库结构。"""
        result = {
            "total_changes": 0,
            "dirs_added": 0,
            "dirs_deleted": 0,
            "dirs_renamed": 0,
            "files_added": 0,
            "files_deleted": 0,
            "files_renamed": 0,
            "files_moved": 0,
        }

        self._sync_directories(local_structure, db_structure, root_dir_id, result)
        self._sync_files(local_structure, db_structure, root_dir_id, telethon_cfg, result)

        return result

    def _sync_directories(self, local_structure, db_structure, root_dir_id, result):
        """同步目录结构。_bg=True 表示后台线程，写锁无限等待。"""
        local_dirs = set(local_structure["dirs"].keys())
        db_dirs = set(db_structure["dirs"].keys())

        # 新增的目录
        added_dirs = local_dirs - db_dirs
        # 按路径深度排序：确保父目录先于子目录创建，避免因
        # set 无序导致子目录查找父目录失败而被跳过
        added_dirs = sorted(added_dirs, key=lambda p: len(Path(p).parts))
        for rel_path in added_dirs:
            dir_name = local_structure["dirs"][rel_path]
            parent_rel = str(Path(rel_path).parent) if rel_path else ""

            parent_id = root_dir_id
            # 注：Path("sub1").parent 返回 "." 而非 ""，"." 和 "" 均表示同步根目录
            if parent_rel in (".", ""):
                parent_id = root_dir_id
            elif parent_rel in db_structure["dirs"]:
                parent_id = db_structure["dirs"][parent_rel]
            else:
                # 理论不应到达（深度排序确保父目录已创建）
                continue

            dir_id = self.db.dirs.add_directory(dir_name, parent_id, is_sync=1, _bg=True)
            db_structure["dirs"][rel_path] = dir_id
            result["dirs_added"] += 1

        # 删除的目录（深度倒序：子目录先删，避免父目录级联删除后的冗余操作）
        deleted_dirs = db_dirs - local_dirs
        deleted_dirs = sorted(deleted_dirs, key=lambda p: -len(Path(p).parts))
        for rel_path in deleted_dirs:
            dir_id = db_structure["dirs"][rel_path]
            files_in_dir = self.db.files.get_local_files_in_directory(dir_id)
            if not files_in_dir:
                self.db.dirs.delete_directory_recursive(dir_id, _bg=True)
                del db_structure["dirs"][rel_path]
                result["dirs_deleted"] += 1

        # 更名的目录
        common_dirs = local_dirs & db_dirs
        for rel_path in common_dirs:
            local_name = local_structure["dirs"][rel_path]
            dir_id = db_structure["dirs"][rel_path]

            dir_info = self.db.get_directory_info(dir_id)
            if dir_info:
                db_name = dir_info.name
                if local_name != db_name:
                    self.db.dirs.rename_directory(dir_id, local_name, _bg=True)
                    if dir_info.parent_id == 0 and dir_info.channel_id:
                        self._edit_tg_channel_title(dir_info.channel_id, local_name)
                    result["dirs_renamed"] += 1

    # ── 文件同步 ──────────────────────────────────────────────

    def _build_db_hash_index(self, db_structure):
        """构建 文件哈希 -> [(文件信息, 相对路径)] 的索引。"""
        index = {}
        for rel_path, info in db_structure["files"].items():
            file_hash = self._get_file_hash(info["id"])
            if file_hash:
                index.setdefault(file_hash, []).append((info, rel_path))
        return index

    def _get_file_hash(self, file_id):
        """获取文件的哈希值。"""
        file_info = self.db.files.get_file_by_id(file_id)
        return file_info.file_hash if file_info else None

    def _sync_files(self, local_structure, db_structure, root_dir_id, telethon_cfg, result):
        """同步文件：检测新增/删除/更名/迁移/内容变更。"""
        local_files = local_structure["files"]
        db_files = db_structure["files"]

        db_hash_index = self._build_db_hash_index(db_structure)

        # 第一步：处理本地已不存在的文件（删除或迁移/改名）
        for db_rel_path, db_info in list(db_files.items()):
            if self.stop_event.is_set():
                return
            if db_rel_path in local_files:
                continue

            file_hash = self._get_file_hash(db_info["id"])
            found = False
            if file_hash and file_hash in local_structure["files"]:
                for local_rel_path, local_info in local_structure["files"].items():
                    if local_info["hash"] == file_hash:
                        new_parent_rel = str(Path(local_rel_path).parent) if local_rel_path else ""
                        new_parent_id = root_dir_id
                        if new_parent_rel not in (".", ""):
                            if new_parent_rel in db_structure["dirs"]:
                                new_parent_id = db_structure["dirs"][new_parent_rel]

                        self.db.files.move_file(db_info["id"], new_parent_id, _bg=True)
                        self.db.files.update_file_local_info(
                            db_info["id"],
                            local_info["local_path"],
                            local_info["name"],
                            file_hash,
                            _bg=True,
                        )
                        if local_info["name"] != db_info["display_name"]:
                            self._edit_tg_message_caption(
                                db_info["chat_id"],
                                db_info["message_id"],
                                local_info["name"],
                            )
                        db_files[local_rel_path] = {
                            "id": db_info["id"],
                            "message_id": db_info["message_id"],
                            "chat_id": db_info["chat_id"],
                            "local_path": local_info["local_path"],
                            "display_name": local_info["name"],
                            "directory_id": new_parent_id,
                        }
                        del db_files[db_rel_path]
                        key = "files_moved" if new_parent_id != db_info["directory_id"] else "files_renamed"
                        result[key] += 1
                        found = True
                        break

            if not found:
                self.db.files.delete_file(db_info["id"], _bg=True)
                self._delete_tg_message(db_info["chat_id"], db_info["message_id"])
                del db_files[db_rel_path]
                result["files_deleted"] += 1

        # 第二步：处理本地新增或变更的文件
        for local_rel_path, local_info in local_files.items():
            if self.stop_event.is_set():
                return
            if local_rel_path in db_files:
                db_info = db_files[local_rel_path]
                if local_info["hash"] != self._get_file_hash(db_info["id"]):
                    # 内容变化，重新上传
                    try:
                        self._delete_tg_message(db_info["chat_id"], db_info["message_id"])
                        uploader = TelethonUploader(telethon_cfg["api_id"], telethon_cfg["api_hash"])
                        parent_id = db_info["directory_id"]
                        chat_id = self.db.dirs.get_directory_channel(parent_id)
                        file_id, msg_id, real_chat_id = self.loop.run_until_complete(
                            uploader.upload(
                                chat_id, local_info["local_path"],
                                db=self.db, dir_id=parent_id,
                                dir_name=self._get_dir_name(parent_id),
                                client=self.client,
                            )
                        )
                        cache_dir = get_cache_dir()
                        thumb_path, media_clip_path = generate_media_cache(
                            local_info["local_path"], cache_dir
                        )
                        self.db.files.update_file(
                            db_info["id"],
                            file_id_new=file_id, message_id=msg_id, chat_id=real_chat_id,
                            file_size=local_info["size"], file_hash=local_info["hash"],
                            local_path=local_info["local_path"],
                            _bg=True,
                        )
                        self.db.files.update_file_cache_paths(db_info["id"], thumb_path, media_clip_path, _bg=True)
                        db_files[local_rel_path].update({
                            "message_id": msg_id,
                            "chat_id": real_chat_id,
                            "local_path": local_info["local_path"],
                            "display_name": local_info["name"],
                        })
                        result["files_added"] += 1
                    except Exception as e:
                        logger.error(f"[{self._log_tag}] 更新文件失败 {local_info['local_path']}: {e}")
                else:
                    # 内容没变，检查改名和迁移
                    if local_info["name"] != db_info["display_name"]:
                        self.db.files.update_display_name(db_info["id"], local_info["name"], _bg=True)
                        self._edit_tg_message_caption(
                            db_info["chat_id"], db_info["message_id"], local_info["name"]
                        )
                        db_files[local_rel_path]["display_name"] = local_info["name"]
                        result["files_renamed"] += 1
                    parent_rel = str(Path(local_rel_path).parent) if local_rel_path else ""
                    new_parent_id = root_dir_id
                    if parent_rel not in (".", "") and parent_rel in db_structure["dirs"]:
                        new_parent_id = db_structure["dirs"][parent_rel]
                    if new_parent_id != db_info["directory_id"]:
                        self.db.files.move_file(db_info["id"], new_parent_id, _bg=True)
                        self.db.files.update_file_local_info(
                            db_info["id"], local_info["local_path"], local_info["name"],
                            _bg=True,
                        )
                        db_files[local_rel_path]["directory_id"] = new_parent_id
                        result["files_moved"] += 1
            else:
                # 数据库中没有这个路径，通过哈希匹配检测改名/迁移
                file_hash = local_info["hash"]
                if file_hash and file_hash in db_hash_index:
                    candidates = db_hash_index[file_hash]
                    db_info, old_rel_path = candidates[0]
                    if old_rel_path in db_files:
                        parent_rel = str(Path(local_rel_path).parent) if local_rel_path else ""
                        new_parent_id = root_dir_id
                        if parent_rel not in (".", "") and parent_rel in db_structure["dirs"]:
                            new_parent_id = db_structure["dirs"][parent_rel]

                        self.db.files.move_file(db_info["id"], new_parent_id, _bg=True)
                        self.db.files.update_file_local_info(
                            db_info["id"], local_info["local_path"],
                            local_info["name"], file_hash,
                            _bg=True,
                        )
                        if local_info["name"] != db_info["display_name"]:
                            self._edit_tg_message_caption(
                                db_info["chat_id"], db_info["message_id"], local_info["name"]
                            )

                        del db_files[old_rel_path]
                        db_files[local_rel_path] = {
                            "id": db_info["id"],
                            "message_id": db_info["message_id"],
                            "chat_id": db_info["chat_id"],
                            "local_path": local_info["local_path"],
                            "display_name": local_info["name"],
                            "directory_id": new_parent_id,
                        }
                        key = "files_moved" if new_parent_id != db_info["directory_id"] else "files_renamed"
                        result[key] += 1
                        continue

                # 真正的新文件，上传到 TG
                try:
                    parent_rel = str(Path(local_rel_path).parent) if local_rel_path else ""
                    parent_id = root_dir_id
                    if parent_rel not in (".", "") and parent_rel in db_structure["dirs"]:
                        parent_id = db_structure["dirs"][parent_rel]

                    uploader = TelethonUploader(telethon_cfg["api_id"], telethon_cfg["api_hash"])
                    chat_id = self.db.dirs.get_directory_channel(parent_id)
                    file_id, msg_id, real_chat_id = self.loop.run_until_complete(
                        uploader.upload(
                            chat_id, local_info["local_path"],
                            db=self.db, dir_id=parent_id,
                            dir_name=self._get_dir_name(parent_id),
                            client=self.client,
                        )
                    )
                    cache_dir = get_cache_dir()
                    thumb_path, media_clip_path = generate_media_cache(
                        local_info["local_path"], cache_dir
                    )
                    ext = Path(local_info["name"]).suffix.lower()
                    self.db.files.add_file(
                        file_id, msg_id, real_chat_id,
                        local_info["name"], local_info["name"],
                        parent_id, local_info["size"], ext,
                        local_path=local_info["local_path"],
                        file_hash=file_hash,
                        thumbnail_path=thumb_path,
                        cached_video_path=media_clip_path,
                        is_sync=1,
                        _bg=True,
                    )
                    result["files_added"] += 1
                except Exception as e:
                    logger.error(f"[{self._log_tag}] 上传文件失败 {local_info['local_path']}: {e}")

        result["total_changes"] = (
            result["dirs_added"] + result["dirs_deleted"] + result["dirs_renamed"] +
            result["files_added"] + result["files_deleted"] + result["files_renamed"] +
            result["files_moved"]
        )
