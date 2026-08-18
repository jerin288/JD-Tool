"""Local Tally Prime HTTP/XML client."""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import requests

from app.models.export import TallyImportResponse
from app.models.tally import (
    TallyCompany,
    TallyCompanyData,
    TallyConnectionResult,
    TallyLedger,
    TallyLedgerCreationResult,
)

LOGGER = logging.getLogger(__name__)
NUMERIC_CHARACTER_REFERENCE = re.compile(br"&#(?:(?:x|X)([0-9a-fA-F]+)|([0-9]+));")
RAW_XML_CONTROL_BYTES = re.compile(br"[\x00-\x08\x0B\x0C\x0E-\x1F]")


class TallyConnectionError(RuntimeError):
    """Base class for user-facing Tally connection failures."""


class TallyNotRunningError(TallyConnectionError):
    pass


class TallyTimeoutError(TallyConnectionError):
    pass


class TallyInvalidResponseError(TallyConnectionError):
    pass


class TallyNoCompanyError(TallyConnectionError):
    pass


class TallyLedgerCreationError(TallyConnectionError):
    """Raised when Tally does not report a successful ledger creation."""

    def __init__(self, message: str, result: TallyLedgerCreationResult | None = None) -> None:
        super().__init__(message)
        self.result = result


class HttpResponse(Protocol):
    status_code: int
    content: bytes
    text: str

    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    def post(self, url: str, **kwargs: object) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class _CollectionDefinition:
    name: str
    object_type: str
    fetch: str


class TallyClient:
    """Fetch companies, ledgers, groups, and voucher types from local Tally Prime."""

    def __init__(
        self, server_url: str = "http://localhost:9000", timeout_seconds: float = 8.0,
        session: HttpSession | None = None,
    ) -> None:
        self.server_url = self._normalize_url(server_url)
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False  # type: ignore[attr-defined]

    def test_connection(self) -> TallyConnectionResult:
        started = time.perf_counter()
        root = self._export_collection(
            _CollectionDefinition("Codex Company Collection", "Company", "Name,GUID,StartingFrom,EndingAt")
        )
        companies = tuple(self._parse_companies(root))
        elapsed = int((time.perf_counter() - started) * 1000)
        return TallyConnectionResult(self.server_url, companies, elapsed)

    def fetch_company_data(self, company: TallyCompany | str) -> TallyCompanyData:
        company_name = company.name if isinstance(company, TallyCompany) else company
        if not company_name.strip():
            raise TallyNoCompanyError("Select an open Tally company first.")
        ledgers_root = self._export_collection(
            _CollectionDefinition("Codex Ledger Collection", "Ledger", "Name,Parent,GUID"), company_name
        )
        voucher_root = self._export_collection(
            _CollectionDefinition("Codex Voucher Type Collection", "VoucherType", "Name,Parent"), company_name
        )
        selected = company if isinstance(company, TallyCompany) else TallyCompany(company_name)
        return TallyCompanyData(
            selected,
            tuple(self._parse_ledgers(ledgers_root)),
            tuple(self._parse_voucher_types(voucher_root)),
        )

    def import_vouchers(self, payload: bytes) -> TallyImportResponse:
        """Send one or more validated voucher envelopes and parse Tally's import summary."""
        root = self._post(payload, allow_tally_errors=True)
        messages = tuple(
            text for tag, text in self._all_text(root)
            if tag in {"LINEERROR", "ERROR", "ERRORMSG"}
        )
        return TallyImportResponse(
            created=self._integer_text(root, "CREATED"),
            altered=self._integer_text(root, "ALTERED"),
            ignored=self._integer_text(root, "IGNORED"),
            errors=self._integer_text(root, "ERRORS"),
            cancelled=self._integer_text(root, "CANCELLED"),
            exceptions=self._integer_text(root, "EXCEPTIONS"),
            last_voucher_id=self._first_text(root, "LASTVCHID"),
            messages=messages,
        )

    def create_ledger(self, company_name: str, ledger_name: str, parent_group: str) -> TallyLedgerCreationResult:
        """Create a ledger under an existing Tally group using an All Masters import."""
        company_name = company_name.strip()
        ledger_name = ledger_name.strip()
        parent_group = parent_group.strip()
        if not company_name:
            raise TallyNoCompanyError("Select an open Tally company first.")
        if not ledger_name:
            raise ValueError("Enter a ledger name.")
        if not parent_group:
            raise ValueError("Enter a parent group.")

        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        body = ET.SubElement(envelope, "BODY")
        import_data = ET.SubElement(body, "IMPORTDATA")
        request_description = ET.SubElement(import_data, "REQUESTDESC")
        ET.SubElement(request_description, "REPORTNAME").text = "All Masters"
        static = ET.SubElement(request_description, "STATICVARIABLES")
        ET.SubElement(static, "SVCURRENTCOMPANY").text = company_name
        request_data = ET.SubElement(import_data, "REQUESTDATA")
        tally_message = ET.SubElement(request_data, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
        ledger = ET.SubElement(
            tally_message,
            "LEDGER",
            {"NAME": ledger_name, "ACTION": "Create"},
        )
        # The NAME attribute alone is only used by Tally as a lookup key for
        # existing masters. For a brand-new object under ACTION="Create" some
        # Tally builds also require the display name as a child element, or
        # they report "Master name is missing" and silently drop the import
        # into an interactive Import Exceptions / MISSING_MASTER_NAME state.
        ET.SubElement(ledger, "NAME").text = ledger_name
        ET.SubElement(ledger, "PARENT").text = parent_group

        request_payload = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
        root = self._post(request_payload, allow_tally_errors=True)
        messages = tuple(
            text for tag, text in self._all_text(root)
            if tag in {"LINEERROR", "ERROR", "ERRORMSG"}
        )
        result = TallyLedgerCreationResult(
            created=self._integer_text(root, "CREATED"),
            altered=self._integer_text(root, "ALTERED"),
            errors=self._integer_text(root, "ERRORS"),
            messages=messages,
        )
        if not result.succeeded:
            exceptions = self._integer_text(root, "EXCEPTIONS")
            detail = "; ".join(messages) or (
                f"Tally created {result.created} ledger(s) and reported {result.errors} error(s)."
                + (
                    f" Tally raised {exceptions} exception(s) needing manual confirmation in its own"
                    " window — check Tally for an open ledger/master screen and close or complete it."
                    if exceptions
                    else ""
                )
            )
            LOGGER.warning(
                "Tally ledger creation diagnostic - request: %s | response: %s",
                request_payload.decode("utf-8", errors="replace"),
                ET.tostring(root, encoding="unicode"),
            )
            raise TallyLedgerCreationError(f"Ledger '{ledger_name}' was not created: {detail}", result)
        return result

    def _export_collection(
        self, definition: _CollectionDefinition, company_name: str = ""
    ) -> ET.Element:
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "VERSION").text = "1"
        ET.SubElement(header, "TALLYREQUEST").text = "Export"
        ET.SubElement(header, "TYPE").text = "Collection"
        ET.SubElement(header, "ID").text = definition.name
        body = ET.SubElement(envelope, "BODY")
        description = ET.SubElement(body, "DESC")
        static = ET.SubElement(description, "STATICVARIABLES")
        ET.SubElement(static, "SVEXPORTFORMAT").text = "$$SysName:XML"
        if company_name:
            ET.SubElement(static, "SVCURRENTCOMPANY").text = company_name
        tdl = ET.SubElement(description, "TDL")
        message = ET.SubElement(tdl, "TDLMESSAGE")
        collection = ET.SubElement(message, "COLLECTION", {"NAME": definition.name, "ISMODIFY": "No"})
        ET.SubElement(collection, "TYPE").text = definition.object_type
        ET.SubElement(collection, "FETCH").text = definition.fetch
        return self._post(ET.tostring(envelope, encoding="utf-8", xml_declaration=True))

    def _post(self, payload: bytes, allow_tally_errors: bool = False) -> ET.Element:
        try:
            response = self.session.post(
                self.server_url,
                data=payload,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise TallyTimeoutError(
                f"Tally did not respond within {self.timeout_seconds:g} seconds."
            ) from exc
        except requests.ConnectionError as exc:
            raise TallyNotRunningError(
                "Could not connect to Tally Prime. Start Tally and enable its HTTP server."
            ) from exc
        except requests.RequestException as exc:
            raise TallyConnectionError(f"Tally HTTP request failed: {exc}") from exc
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as original_error:
            repaired_payload, repair_count = self._sanitize_xml_payload(response.content)
            if not repair_count:
                raise TallyInvalidResponseError(
                    f"Tally returned malformed XML ({original_error}). Check the application log for details."
                ) from original_error
            LOGGER.warning(
                "Repaired %d XML-forbidden control character reference(s) in a Tally response.",
                repair_count,
            )
            try:
                root = ET.fromstring(repaired_payload)
            except ET.ParseError as repaired_error:
                raise TallyInvalidResponseError(
                    f"Tally returned malformed XML that could not be repaired ({repaired_error})."
                ) from repaired_error
        errors = [text for tag, text in self._all_text(root) if tag in {"LINEERROR", "ERROR", "ERRORMSG"}]
        if errors and not allow_tally_errors:
            raise TallyConnectionError("Tally error: " + "; ".join(errors))
        statuses = [text for tag, text in self._all_text(root) if tag == "STATUS"]
        if "0" in statuses and not allow_tally_errors:
            raise TallyConnectionError(
                "Tally rejected the XML request. Confirm that a company is open and the HTTP server is enabled."
            )
        return root

    @classmethod
    def _integer_text(cls, root: ET.Element, tag_name: str) -> int:
        value = cls._first_text(root, tag_name)
        try:
            return int(value or "0")
        except ValueError:
            return 0

    @classmethod
    def _first_text(cls, root: ET.Element, tag_name: str) -> str:
        for element in root.iter():
            if cls._local_name(element.tag) == tag_name:
                return cls._clean_text(element.text or "")
        return ""

    @classmethod
    def _parse_companies(cls, root: ET.Element) -> list[TallyCompany]:
        companies: list[TallyCompany] = []
        for element in cls._entities(root, "COMPANY"):
            name = cls._entity_name(element)
            if name:
                companies.append(TallyCompany(
                    name=name,
                    guid=cls._child_text(element, "GUID"),
                    starting_from=cls._child_text(element, "STARTINGFROM"),
                    ending_at=cls._child_text(element, "ENDINGAT"),
                ))
        return cls._deduplicate(companies, lambda item: item.name.lower())

    @classmethod
    def _parse_ledgers(cls, root: ET.Element) -> list[TallyLedger]:
        ledgers: list[TallyLedger] = []
        for element in cls._entities(root, "LEDGER"):
            name = cls._entity_name(element)
            if name:
                ledgers.append(TallyLedger(
                    name=name,
                    parent_group=cls._child_text(element, "PARENT"),
                    guid=cls._child_text(element, "GUID"),
                ))
        return sorted(cls._deduplicate(ledgers, lambda item: item.name.lower()), key=lambda item: item.name.lower())

    @classmethod
    def _parse_voucher_types(cls, root: ET.Element) -> list[str]:
        values = [cls._entity_name(element) for element in cls._entities(root, "VOUCHERTYPE")]
        return sorted({value for value in values if value}, key=str.lower)

    @staticmethod
    def _entities(root: ET.Element, entity_name: str) -> list[ET.Element]:
        return [element for element in root.iter() if TallyClient._local_name(element.tag) == entity_name]

    @staticmethod
    def _entity_name(element: ET.Element) -> str:
        # Collection responses also contain scalar summary tags such as
        # ``<LEDGER>182</LEDGER>`` and ``<COMPANY>1</COMPANY>``.  Their text is
        # a count, not an entity name.  Real Tally masters expose NAME as an
        # attribute or direct child, so never fall back to the element text.
        return (
            TallyClient._clean_text(element.attrib.get("NAME", ""))
            or TallyClient._child_text(element, "NAME")
        )

    @staticmethod
    def _child_text(element: ET.Element, tag_name: str) -> str:
        for child in element:
            if TallyClient._local_name(child.tag) == tag_name:
                return TallyClient._clean_text(child.text or "")
        return ""

    @staticmethod
    def _all_text(root: ET.Element) -> list[tuple[str, str]]:
        return [
            (TallyClient._local_name(element.tag), (element.text or "").strip())
            for element in root.iter() if (element.text or "").strip()
        ]

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].upper()

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _sanitize_xml_payload(payload: bytes) -> tuple[bytes, int]:
        """Replace only characters forbidden by XML 1.0, preserving valid references."""
        repaired_references = 0

        def replace_reference(match: re.Match[bytes]) -> bytes:
            nonlocal repaired_references
            codepoint = int(match.group(1), 16) if match.group(1) else int(match.group(2), 10)
            allowed = (
                codepoint in {0x09, 0x0A, 0x0D}
                or 0x20 <= codepoint <= 0xD7FF
                or 0xE000 <= codepoint <= 0xFFFD
                or 0x10000 <= codepoint <= 0x10FFFF
            )
            if allowed:
                return match.group(0)
            repaired_references += 1
            return b" "

        repaired = NUMERIC_CHARACTER_REFERENCE.sub(replace_reference, payload)
        repaired, raw_control_count = RAW_XML_CONTROL_BYTES.subn(b" ", repaired)
        return repaired, repaired_references + raw_control_count

    @staticmethod
    def _deduplicate(items: list[object], key: object) -> list[object]:
        seen: set[object] = set()
        result: list[object] = []
        for item in items:
            identity = key(item)  # type: ignore[operator]
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

    @staticmethod
    def _normalize_url(value: str) -> str:
        raw = value.strip().rstrip("/") or "http://localhost:9000"
        if "://" not in raw:
            raw = f"http://{raw}"
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Enter a valid Tally HTTP URL, such as http://localhost:9000")
        if parsed.hostname.lower() not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("For privacy, the Tally server URL must use localhost or a loopback address.")
        return raw
