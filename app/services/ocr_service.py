"""Local, in-memory Tesseract OCR for scanned PDF pages."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class OcrError(RuntimeError):
    """Safe, user-facing OCR failure."""


class TesseractNotFoundError(OcrError):
    """Raised when the configured Tesseract executable cannot be found."""


@dataclass(slots=True)
class OcrConfiguration:
    executable_path: str = ""
    language: str = "eng"
    dpi: int = 300
    page_segmentation_mode: int = 6


@dataclass(slots=True)
class OcrPageResult:
    page_number: int
    text: str
    words: list[dict[str, object]] = field(default_factory=list)
    mean_confidence: float = 0.0


class OcrService:
    """Render selected pages with PyMuPDF and recognize them with local Tesseract."""

    def __init__(self, configuration: OcrConfiguration | None = None) -> None:
        self.configuration = configuration or OcrConfiguration()

    def update_configuration(self, configuration: OcrConfiguration) -> None:
        self.configuration = configuration

    def resolve_executable(self) -> Path:
        configured = self.configuration.executable_path.strip().strip('"')
        candidates = [
            Path(configured) if configured else None,
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        ]
        path_command = shutil.which("tesseract")
        if path_command:
            candidates.insert(0, Path(path_command))
        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate.resolve()
        raise TesseractNotFoundError(
            "This statement needs OCR, but Tesseract was not found. Install Tesseract OCR, then set its "
            "executable path under Settings > App."
        )

    def extract_pages(
        self,
        pdf_path: Path,
        page_numbers: list[int],
        password: str = "",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[OcrPageResult], list[str]]:
        import fitz

        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:
            raise OcrError("OCR support is incomplete. Reinstall the application to add pytesseract.") from exc

        executable = self.resolve_executable()
        pytesseract.pytesseract.tesseract_cmd = str(executable)
        results: list[OcrPageResult] = []
        warnings: list[str] = []
        config = f"--psm {max(1, min(13, int(self.configuration.page_segmentation_mode)))}"
        try:
            document = fitz.open(pdf_path)
        except Exception as exc:
            raise OcrError("The PDF could not be opened for OCR.") from exc
        with document:
            if document.needs_pass and (not password or not document.authenticate(password)):
                raise OcrError("The PDF password could not be used for OCR.")
            total = len(page_numbers)
            for current, page_number in enumerate(page_numbers, start=1):
                if progress:
                    progress(current - 1, total, f"OCR page {page_number} of {document.page_count}")
                try:
                    page = document[page_number - 1]
                    zoom = max(150, min(600, int(self.configuration.dpi))) / 72
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, colorspace=fitz.csRGB)
                    image = pixmap.pil_image()
                    data = pytesseract.image_to_data(
                        image,
                        lang=self.configuration.language.strip() or "eng",
                        config=config,
                        output_type=Output.DICT,
                    )
                    words = self._words_from_data(data, zoom)
                    text = self._text_from_words(words)
                    confidences = [float(word["confidence"]) for word in words if float(word["confidence"]) >= 0]
                    results.append(
                        OcrPageResult(
                            page_number,
                            text,
                            words,
                            sum(confidences) / len(confidences) if confidences else 0.0,
                        )
                    )
                except Exception:
                    warnings.append(f"OCR failed on page {page_number}; that page was skipped.")
            if progress:
                progress(total, total, "OCR complete")
        return results, warnings

    @staticmethod
    def _words_from_data(data: dict[str, list[object]], scale: float) -> list[dict[str, object]]:
        words: list[dict[str, object]] = []
        for index, raw_text in enumerate(data.get("text", [])):
            value = str(raw_text).strip()
            if not value:
                continue
            try:
                confidence = float(data["conf"][index])
            except (KeyError, IndexError, TypeError, ValueError):
                confidence = -1.0
            words.append(
                {
                    "text": value,
                    "x0": float(data["left"][index]) / scale,
                    "top": float(data["top"][index]) / scale,
                    "line": (data.get("block_num", [0])[index], data.get("par_num", [0])[index], data.get("line_num", [0])[index]),
                    "confidence": confidence,
                }
            )
        return words

    @staticmethod
    def _text_from_words(words: list[dict[str, object]]) -> str:
        lines: dict[object, list[dict[str, object]]] = {}
        for word in words:
            lines.setdefault(word["line"], []).append(word)
        ordered = sorted(lines.values(), key=lambda line: (float(line[0]["top"]), float(line[0]["x0"])))
        return "\n".join(
            " ".join(str(word["text"]) for word in sorted(line, key=lambda item: float(item["x0"])))
            for line in ordered
        )
