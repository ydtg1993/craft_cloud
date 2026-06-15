"""Qt 拖放数据序列化服务（纯视图层）。"""
import json
from PySide6.QtCore import QMimeData


class DragDataService:
    MIME_TYPE = "application/x-file-id"

    @staticmethod
    def encode_file_ids(file_ids: list) -> QMimeData:
        mime = QMimeData()
        mime.setData(DragDataService.MIME_TYPE, json.dumps(file_ids).encode())
        return mime

    @staticmethod
    def decode_file_ids(mime_data: QMimeData) -> list:
        raw = bytes(mime_data.data(DragDataService.MIME_TYPE))
        try:
            data = json.loads(raw.decode())
            return data if isinstance(data, list) else [data]
        except (ValueError, UnicodeDecodeError):
            return [int(raw.decode())]
