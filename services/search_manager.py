"""SearchManager — 搜索编排。

通过返回值与 UI 通信，不直接使用 InfoBar。
"""
from enum import Enum

from PySide6.QtCore import QObject, Signal

from services.search.whoosh_engine import WhooshSearch


class SearchErrorType(Enum):
    """搜索错误类型。"""
    EMPTY_KEYWORD = "empty_keyword"
    NO_RESULTS = "no_results"


class SearchManager(QObject):
    """搜索管理器。

    search_completed Signal 携带 (results, error_message_or_None)。
    UI 层连接此信号来展示搜索结果或错误提示。
    """
    search_completed = Signal(list, str)  # results, error_msg (empty string if ok)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        # 将 WhooshSearch 注入到 FileRepository，消除 model→services 反向依赖
        self._whoosh = WhooshSearch()
        self.db.files.set_indexer(self._whoosh)

    def search_by_filename(self, keyword, file_count=0):
        """按文件名搜索。结果通过 search_completed 信号返回。"""
        keyword = keyword.strip()
        if not keyword:
            self.search_completed.emit([], SearchErrorType.EMPTY_KEYWORD.value)
            return
        force_like = file_count < 10000
        results = self.db.files.search_files_by_name(keyword, force_like=force_like)
        self.search_completed.emit(results, "")

    def search_by_date_range(self, start_date, end_date):
        """按日期范围搜索。结果通过 search_completed 信号返回。"""
        results = self.db.files.search_files_by_date_range(start_date, end_date)
        self.search_completed.emit(results, "")
