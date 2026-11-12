"""Reusable Fluent widgets: cards, chips, code views, rows and feed helpers."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIconBase,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    isDarkTheme,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
)

from .theme import accent_hex, mono_font, status_color


def icon_of(icon: FluentIconBase | QIcon | str) -> QIcon:
    if isinstance(icon, QIcon):
        return icon
    if hasattr(icon, "icon"):
        return icon.icon()
    return QIcon(icon)


def make_splitter(orientation: Qt.Orientation) -> QSplitter:
    """Splitter with a transparent, easy-to-grab handle that matches the theme."""

    splitter = QSplitter(orientation)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(10)
    splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
    return splitter


def count_label(count: int, singular: str, plural: str) -> str:
    """Return 'N noun' with the correct Spanish singular or plural form."""

    return f"{count} {singular if count == 1 else plural}"


def icon_label(icon: FluentIconBase | QIcon | str, size: int = 20) -> QLabel:
    label = QLabel()
    label.setPixmap(icon_of(icon).pixmap(size, size))
    label.setFixedSize(size, size)
    label.setScaledContents(True)
    return label


class SectionCard(CardWidget):
    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        icon: FluentIconBase | QIcon | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setBorderRadius(10)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(20, 18, 20, 18)
        self._root.setSpacing(12)

        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(10)
        if icon is not None:
            self.header_layout.addWidget(icon_label(icon, 20))
        self.title_label = StrongBodyLabel(title) if title else None
        if self.title_label is not None:
            self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)
        if title:
            self._root.addLayout(self.header_layout)
        if subtitle:
            self.subtitle_label = CaptionLabel(subtitle)
            self.subtitle_label.setWordWrap(True)
            self.subtitle_label.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
            self._root.addWidget(self.subtitle_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.body.setContentsMargins(0, 0, 0, 0)
        self._root.addLayout(self.body, 1)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.body.addLayout(layout, stretch)


class StatTile(CardWidget):
    def __init__(
        self,
        caption: str,
        value: str = "—",
        icon: FluentIconBase | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setBorderRadius(10)
        self.setMinimumHeight(78)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        if icon is not None:
            self.icon = IconWidget(icon, self)
            self.icon.setFixedSize(20, 20)
            layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.value_label = SubtitleLabel(value)
        font = self.value_label.font()
        font.setPointSize(15)
        font.setBold(True)
        self.value_label.setFont(font)
        self.caption_label = CaptionLabel(caption)
        self.caption_label.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
        text_layout.addWidget(self.value_label)
        text_layout.addWidget(self.caption_label)
        layout.addLayout(text_layout, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class Chip(QLabel):
    _TONES = {
        "neutral": ("#6B7280", 0.12),
        "accent": ("#2F6DF6", 0.14),
        "success": ("#16A34A", 0.14),
        "warning": ("#D97706", 0.14),
        "danger": ("#DC2626", 0.14),
        "violet": ("#7C3AED", 0.14),
        "teal": ("#0D9488", 0.14),
    }

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(22)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        color, alpha = self._TONES.get(tone, self._TONES["neutral"])
        qcolor = QColor(color)
        self.setStyleSheet(
            "QLabel {"
            f"color: {color};"
            f"background-color: rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, {alpha});"
            "border-radius: 11px; padding: 1px 9px; font-size: 11px; font-weight: 600;"
            "}"
        )


class TokenMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.bar = ProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar, 1)
        self.label = CaptionLabel("0 / 0")
        self.label.setMinimumWidth(110)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label)

    def update_values(self, used: int, budget: int) -> None:
        ratio = 0 if budget <= 0 else min(1.0, used / budget)
        self.bar.setValue(int(ratio * 1000))
        label = self.label
        if used > budget:
            label.setText(f"≈ {used:,} / {budget:,} tok".replace(",", "."))
            label.setTextColor(QColor("#DC2626"), QColor("#F87171"))
        elif ratio > 0.8:
            label.setText(f"≈ {used:,} / {budget:,} tok".replace(",", "."))
            label.setTextColor(QColor("#D97706"), QColor("#FBBF24"))
        else:
            label.setText(f"≈ {used:,} / {budget:,} tok".replace(",", "."))
            label.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))


class SettingsRow(QWidget):
    def __init__(
        self,
        title: str,
        description: str = "",
        control: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 10, 4, 10)
        root.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = BodyLabel(title)
        text.addWidget(self.title_label)
        if description:
            caption = CaptionLabel(description)
            caption.setWordWrap(True)
            caption.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
            text.addWidget(caption)
            self.description_label = caption
        root.addLayout(text, 1)
        if control is not None:
            control.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            root.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SwitchRow(QWidget):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        description: str = "",
        checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(BodyLabel(title))
        if description:
            caption = CaptionLabel(description)
            caption.setWordWrap(True)
            caption.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
            text.addWidget(caption)
        root.addLayout(text, 1)
        self.switch = SwitchButton(self)
        self.switch.setOnText("Sí")
        self.switch.setOffText("No")
        self.switch.setChecked(checked)
        self.switch.checkedChanged.connect(self.toggled.emit)
        root.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, value: bool) -> None:
        self.switch.setChecked(value)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.switch.setEnabled(enabled)


class EmptyState(QWidget):
    def __init__(
        self,
        icon: FluentIconBase | None,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        if icon is not None:
            picture = QLabel()
            picture.setPixmap(icon.icon().pixmap(54, 54))
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(picture)
        title_label = SubtitleLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        if description:
            caption = CaptionLabel(description)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
            caption.setMaximumWidth(520)
            caption.setTextColor(QColor(105, 105, 105), QColor(165, 165, 165))
            layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(4)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text
        self.setToolTip(text)
        super().setText(text)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setPen(QColor(230, 230, 230) if isDarkTheme() else QColor(32, 32, 32))
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, max(0, self.width() - 2))
        painter.drawText(
            self.rect().adjusted(0, 0, -2, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )


# --------------------------------------------------------------------------- code


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeView") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.editor.paint_line_numbers(event)


class CodeHighlighter(QSyntaxHighlighter):
    """A small, dependency-free highlighter for the languages we care about."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._language = ""
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._block_start: QRegularExpression | None = None
        self._block_end: QRegularExpression | None = None
        self._formats = self._make_formats()
        self.set_language("")

    def _make_formats(self) -> dict[str, QTextCharFormat]:
        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            result = QTextCharFormat()
            result.setForeground(QColor(color))
            if bold:
                result.setFontWeight(700)
            if italic:
                result.setFontItalic(True)
            return result

        return {
            "keyword": fmt("#4F8DF7", bold=True),
            "builtin": fmt("#22A06B"),
            "string": fmt("#22A06B"),
            "comment": fmt("#7C8794", italic=True),
            "number": fmt("#D97706"),
            "decorator": fmt("#9B6DFF"),
            "function": fmt("#9B6DFF"),
            "key": fmt("#0D9488"),
            "heading": fmt("#4F8DF7", bold=True),
            "add": fmt("#16A34A"),
            "remove": fmt("#DC2626"),
            "hunk": fmt("#7C5CFF", bold=True),
        }

    def set_language(self, language: str) -> None:
        language = (language or "").lower()
        key = "diff" if language in {"diff", "patch"} else language
        if key.startswith(("python", "py")):
            key = "python"
        elif key.startswith(("typescript", "tsx")):
            key = "typescript"
        elif key.startswith(("javascript", "jsx", "js")):
            key = "javascript"
        elif key.startswith("json"):
            key = "json"
        elif key.startswith("markdown"):
            key = "markdown"
        elif key.startswith("sql"):
            key = "sql"
        elif key in {"css", "scss", "sass", "less"}:
            key = "css"
        elif key in {"shell", "bash", "powershell", "bat"}:
            key = "shell"
        elif key in {"go", "rust", "java", "kotlin", "csharp", "c++", "c", "c/c++ header"}:
            key = "generic"
        else:
            key = key
        self._language = key
        self._rules = []
        self._block_start = None
        self._block_end = None
        f = self._formats
        keywords = ""
        pattern = QRegularExpression

        def add(pattern_text: str, fmt: QTextCharFormat) -> None:
            expression = pattern(pattern_text)
            expression.setPatternOptions(QRegularExpression.PatternOption.CaseInsensitiveOption)
            self._rules.append((expression, fmt))

        if key in {"python"}:
            keywords = (
                "and|as|assert|async|await|break|class|continue|def|del|elif|else|except|"
                "finally|for|from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|"
                "raise|return|True|False|try|while|with|yield|match|case"
            )
            add(r"\b(" + keywords + r")\b", f["keyword"])
            add(r"\b(self|cls)\b", f["builtin"])
            add(r"\b(print|len|range|str|int|float|list|dict|set|tuple|open|super|type|"
                r"isinstance|enumerate|zip|sorted|sum|min|max|any|all|Path)\b", f["builtin"])
            add(r"@[\w.]+", f["decorator"])
            add(r"\b\d+(?:\.\d+)?\b", f["number"])
            add(r"\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^'\\]*(?:\\.[^'\\]*)*'", f["string"])
            add(r"#[^\n]*", f["comment"])
            self._block_start = pattern(r"(\"\"\"|''')")
            self._block_end = pattern(r"(\"\"\"|''')")
        elif key in {"javascript", "typescript"}:
            keywords = (
                "await|break|case|catch|class|const|continue|debugger|default|delete|do|else|"
                "enum|export|extends|false|finally|for|from|function|get|if|implements|import|"
                "in|instanceof|interface|let|new|null|of|private|protected|public|readonly|"
                "return|set|static|super|switch|this|throw|true|try|type|typeof|undefined|"
                "var|void|while|with|yield|async|as|namespace|declare|satisfies"
            )
            add(r"\b(" + keywords + r")\b", f["keyword"])
            add(r"\b(console|window|document|process|require|Promise|Array|Object|String|"
                r"Number|Boolean|JSON|Math|Date|RegExp|Map|Set)\b", f["builtin"])
            add(r"\b\d+(?:\.\d+)?\b", f["number"])
            add(r"`[^`]*`|\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^'\\]*(?:\\.[^'\\]*)*'", f["string"])
            add(r"//[^\n]*", f["comment"])
            self._block_start = pattern(r"/\*")
            self._block_end = pattern(r"\*/")
        elif key == "json":
            add(r'"[^"\n]*"(?=\s*:)', f["key"])
            add(r'"[^"\n]*"', f["string"])
            add(r"\b(true|false|null)\b", f["keyword"])
            add(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", f["number"])
        elif key == "markdown":
            add(r"^#{1,6}\s+.*$", f["heading"])
            add(r"`[^`\n]+`", f["string"])
            add(r"\*\*[^*\n]+\*\*", f["keyword"])
            add(r"^\s*[-*+]\s", f["decorator"])
            add(r"\[[^\]\n]+\]\([^)]+\)", f["key"])
            add(r"^```.*$", f["comment"])
        elif key == "sql":
            add(
                r"\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|HAVING|"
                r"INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|ALTER|DROP|INDEX|VIEW|"
                r"AS|AND|OR|NOT|NULL|IS|IN|EXISTS|LIMIT|OFFSET|DISTINCT|CASE|WHEN|THEN|END)\b",
                f["keyword"],
            )
            add(r"'[^']*'", f["string"])
            add(r"--[^\n]*", f["comment"])
            add(r"\b\d+\b", f["number"])
        elif key == "css":
            add(r"#[0-9a-fA-F]{3,8}\b", f["number"])
            add(r"\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms)?\b", f["number"])
            add(r"\"[^\"]*\"|'[^']*'", f["string"])
            add(r"/\*.*?\*/", f["comment"])
            add(r"[.#][\w-]+(?=[^{}]*\{)", f["function"])
            self._block_start = pattern(r"/\*")
            self._block_end = pattern(r"\*/")
        elif key == "shell":
            add(r"\b(if|then|else|elif|fi|for|while|do|done|case|esac|function|in|echo|"
                r"export|local|return|exit|set|source)\b", f["keyword"])
            add(r"\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}", f["builtin"])
            add(r"\"[^\"]*\"|'[^']*'", f["string"])
            add(r"(#|--)[^\n]*", f["comment"])
        elif key == "diff":
            pass
        elif key == "generic":
            add(
                r"\b(public|private|protected|static|final|abstract|class|interface|struct|enum|"
                r"trait|impl|func|fn|def|package|import|return|if|else|for|while|switch|case|"
                r"const|let|var|new|throw|try|catch|async|await|void|int|string|bool|float|"
                r"double|char|long|short|unsigned|using|namespace|template|typename)\b",
                f["keyword"],
            )
            add(r"\b\d+(?:\.\d+)?\b", f["number"])
            add(r"\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^'\\]*(?:\\.[^'\\]*)*'", f["string"])
            add(r"//[^\n]*|#[^\n]*", f["comment"])
            self._block_start = pattern(r"/\*")
            self._block_end = pattern(r"\*/")
        else:
            add(r"#[^\n]*|//[^\n]*", f["comment"])
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        if self._language == "diff":
            if text.startswith("+++") or text.startswith("---"):
                self.setFormat(0, len(text), self._formats["hunk"])
            elif text.startswith("+"):
                self.setFormat(0, len(text), self._formats["add"])
            elif text.startswith("-"):
                self.setFormat(0, len(text), self._formats["remove"])
            elif text.startswith("@@"):
                self.setFormat(0, len(text), self._formats["hunk"])
            return

        if self._block_start is not None and self._block_end is not None:
            if self.previousBlockState() == 1:
                match = self._block_end.match(text)
                if match.hasMatch():
                    end = match.capturedEnd()
                    self.setFormat(0, end, self._formats["string"])
                    self.setCurrentBlockState(0)
                else:
                    self.setFormat(0, len(text), self._formats["string"])
                    self.setCurrentBlockState(1)
                    return
            else:
                match = self._block_start.match(text)
                if match.hasMatch():
                    end_match = self._block_end.match(text, match.capturedEnd())
                    if end_match.hasMatch():
                        self.setFormat(
                            match.capturedStart(),
                            end_match.capturedEnd() - match.capturedStart(),
                            self._formats["string"],
                        )
                    else:
                        self.setFormat(match.capturedStart(), len(text), self._formats["string"])
                        self.setCurrentBlockState(1)
                        return

        for expression, char_format in self._rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), char_format)


class CodeView(PlainTextEdit):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        line_numbers: bool = True,
        read_only: bool = True,
    ) -> None:
        super().__init__(parent)
        self._line_numbers = line_numbers
        self._accent = "#2F6DF6"
        self.setReadOnly(read_only)
        self.setFont(mono_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("PlainTextEdit { background: transparent; border: none; }")
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._area: LineNumberArea | None = None
        if line_numbers:
            self._area = LineNumberArea(self)
            self.blockCountChanged.connect(self._update_number_area_width)
            self.updateRequest.connect(self._update_number_area)
            self.cursorPositionChanged.connect(self._highlight_current_line)
        self.highlighter = CodeHighlighter(self.document())
        self._update_number_area_width()
        self._highlight_current_line()

    def set_accent(self, color: str) -> None:
        self._accent = color
        self._highlight_current_line()

    def set_language(self, language: str) -> None:
        self.highlighter.set_language(language)

    def set_content(self, text: str, language: str = "") -> None:
        self.setPlainText(text)
        self.highlighter.set_language(language)
        self._update_number_area_width()

    def set_editable(self, editable: bool) -> None:
        self.setReadOnly(not editable)

    def set_word_wrap(self, enabled: bool) -> None:
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def set_font_size(self, size: int) -> None:
        font = self.font()
        font.setPointSize(size)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._update_number_area_width()

    # Line-number plumbing ------------------------------------------------
    def line_number_area_width(self) -> int:
        if not self._line_numbers:
            return 0
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_number_area_width(self) -> None:
        if not self._line_numbers:
            return
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_number_area(self, rect, dy: int) -> None:
        if self._area is None:
            return
        if dy:
            self._area.scroll(0, dy)
        else:
            self._area.update(0, rect.y(), self._area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_number_area_width()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._area is not None:
            rect = self.contentsRect()
            self._area.setGeometry(
                rect.left(), rect.top(), self.line_number_area_width(), rect.height()
            )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._area)
        painter.fillRect(event.rect(), QColor(128, 128, 128, 16))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        painter.setFont(self.font())
        palette_color = self.palette().color(QPalette.ColorRole.WindowText)
        palette_color.setAlpha(120)
        painter.setPen(palette_color)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self.line_number_area_width() - 8,
                    self.fontMetrics().height(),
                    int(Qt.AlignmentFlag.AlignRight),
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1

    def _highlight_current_line(self) -> None:
        if self.isReadOnly() and self._line_numbers:
            selection = QTextEdit.ExtraSelection()
            color = QColor(self._accent)
            color.setAlpha(18)
            selection.format.setBackground(color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            self.setExtraSelections([selection])


# ------------------------------------------------------------------------- dialogs


def notify(
    parent: QWidget | None,
    kind: str,
    title: str,
    content: str = "",
    duration: int = 2800,
) -> None:
    if parent is None:
        return
    window = parent.window() if isinstance(parent, QWidget) else parent
    method = getattr(InfoBar, kind, None) or getattr(InfoBar, "info")
    try:
        method(
            title,
            content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=duration,
            parent=window,
        )
    except Exception:
        pass


def confirm(parent: QWidget, title: str, content: str) -> bool:
    box = MessageBox(title, content, parent.window() if parent else None)
    box.yesButton.setText("Continuar")
    box.cancelButton.setText("Cancelar")
    return bool(box.exec())


class TextDialog(QDialog):
    """Plain, resizable dialog with a monospace code view and copy action."""

    def __init__(
        self,
        title: str,
        text: str,
        parent: QWidget | None = None,
        language: str = "",
        width: int = 920,
        height: int = 620,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(title), 1)
        copy_button = PushButton("Copiar")
        close_button = PrimaryPushButton("Cerrar")
        copy_button.clicked.connect(lambda: self._copy(text))
        close_button.clicked.connect(self.accept)
        header.addWidget(copy_button)
        header.addWidget(close_button)
        layout.addLayout(header)
        self.view = CodeView(self, line_numbers=False)
        self.view.set_content(text, language)
        layout.addWidget(self.view, 1)

    def _copy(self, text: str) -> None:
        try:
            from ..clipboard import copy_text

            copy_text(text)
            notify(self, "success", "Copiado", "Contenido en el portapapeles.", 1500)
        except Exception as error:
            notify(self, "error", "No se pudo copiar", str(error))


__all__ = [
    "Chip",
    "CodeView",
    "ElidedLabel",
    "EmptyState",
    "SectionCard",
    "SettingsRow",
    "StatTile",
    "SwitchRow",
    "TextDialog",
    "TokenMeter",
    "confirm",
    "count_label",
    "icon_label",
    "icon_of",
    "make_splitter",
    "notify",
]
