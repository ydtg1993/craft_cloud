"""Application translator — Qt QTranslator-based, follows QFluentWidgets i18n pattern.

Usage:
    # In QWidget subclasses:
    text = self.tr("Confirm")

    # In non-QObject contexts (services, utils):
    from core.translator import tr
    text = tr("Confirm")

    # With formatting:
    text = tr("Delete {count} file(s)?").format(count=5)
"""

from pathlib import Path

from PySide6.QtCore import QLocale, QTranslator, QCoreApplication

_i18n_dir = Path(__file__).parent.parent / "resources" / "i18n"


class AppTranslator(QTranslator):
    """App-level translator, same pattern as qfluentwidgets.common.FluentTranslator.

    Overrides translate() to always use the "app" context, so both
    ``self.tr()`` (QWidget subclass context) and ``core.translator.tr()``
    (explicit "app" context) resolve to the same translations.
    """

    def __init__(self, locale: QLocale = None, parent=None):
        super().__init__(parent=parent)
        self.load(locale or QLocale())

    def load(self, locale: QLocale):
        """Load .qm file for given locale."""
        qm_path = str(_i18n_dir / f"craft_cloud.{locale.name()}.qm")
        super().load(qm_path)

    def translate(self, context: str, sourceText: str, disambiguation: str = None, n: int = -1) -> str:
        """Redirect all Qt translate() calls to the "app" context.
        Falls back to sourceText when no translation is found.
        """
        result = super().translate("app", sourceText, disambiguation, n)
        return result if result else sourceText


def tr(text: str, **kwargs) -> str:
    """Translate text using the app translator context.

    Convenience wrapper around QCoreApplication.translate().
    Works from both QWidget (self.tr) and non-QWidget contexts.

    Args:
        text: English source text to translate.
        **kwargs: Format arguments applied to the translated string.
    """
    result = QCoreApplication.translate("app", text)
    if kwargs:
        result = result.format(**kwargs)
    return result
