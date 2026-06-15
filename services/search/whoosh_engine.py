"""Whoosh full-text search engine."""
from pathlib import Path
from whoosh.index import create_in, open_dir
from whoosh.fields import Schema, TEXT, ID, NUMERIC
from whoosh.qparser import MultifieldParser, FuzzyTermPlugin
from loguru import logger
from core.utils import get_cache_dir


class WhooshSearch:
    """Whoosh-based full-text search for files."""

    def __init__(self):
        self._index_dir = str(get_cache_dir() / "whoosh_index")
        self._schema = Schema(
            local_id=ID(stored=True, unique=True),
            name=TEXT(stored=True),
            original_name=TEXT(stored=True),
            dir_name=TEXT(stored=True),
            dir_id=NUMERIC(stored=True),
        )
        self._ix = None

    def _get_index(self):
        if self._ix is None:
            try:
                self._ix = open_dir(self._index_dir)
            except Exception:
                Path(self._index_dir).mkdir(parents=True, exist_ok=True)
                self._ix = create_in(self._index_dir, self._schema)
                logger.info(f"Created Whoosh index at {self._index_dir}")
        return self._ix

    def index_file(self, local_id: int, name: str, original_name: str,
                   dir_name: str, dir_id: int) -> None:
        """Add or update a file in the search index."""
        ix = self._get_index()
        writer = ix.writer()
        writer.update_document(
            local_id=str(local_id),
            name=name or "",
            original_name=original_name or "",
            dir_name=dir_name or "",
            dir_id=dir_id,
        )
        writer.commit()

    def remove_file(self, local_id: int) -> None:
        """Remove a file from the search index."""
        ix = self._get_index()
        writer = ix.writer()
        writer.delete_by_term("local_id", str(local_id))
        writer.commit()

    def search(self, keyword: str, limit: int = 200) -> list[int]:
        """Search for files by name, return list of local IDs ranked by relevance."""
        if not keyword.strip():
            return []
        ix = self._get_index()
        with ix.searcher() as searcher:
            parser = MultifieldParser(["name", "original_name", "dir_name"], ix.schema)
            parser.add_plugin(FuzzyTermPlugin())
            query = parser.parse(f"*{keyword}*")
            results = searcher.search(query, limit=limit)
            return [int(r["local_id"]) for r in results]

    def rebuild_index(self, files) -> None:
        """Full rebuild of the search index from file records."""
        Path(self._index_dir).mkdir(parents=True, exist_ok=True)
        self._ix = create_in(self._index_dir, self._schema)
        writer = self._ix.writer()
        count = 0
        for f in files:
            writer.add_document(
                local_id=str(f.id),
                name=f.display_name or "",
                original_name=f.original_name or "",
                dir_name=getattr(f, "dir_name", "") or "",
                dir_id=f.directory_id,
            )
            count += 1
        writer.commit()
        self._ix = open_dir(self._index_dir)
        logger.info(f"Whoosh index rebuilt with {count} files")

    def clear_index(self) -> None:
        """Delete and recreate the search index."""
        import shutil
        shutil.rmtree(self._index_dir, ignore_errors=True)
        self._ix = None
