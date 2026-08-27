"""Bounded, replayable orchestration for source-backed registry pilots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from .domain import RegistryInput
from .merge import MergeReport, RegistryAssembler
from .snapshots import RawSnapshot
from .sources import Connector, ConnectorRunResult, run_connector


@dataclass(frozen=True)
class RegistryPilotResult:
    """Normalized source results and the merged registry for one pilot run."""

    registry: RegistryInput
    report: MergeReport
    connector_results: tuple[ConnectorRunResult, ...]

    @property
    def warnings(self) -> tuple[str, ...]:
        """Return source warnings in deterministic connector order."""

        return tuple(warning for result in self.connector_results for warning in result.warnings)


def run_registry_pilot(
    connectors: Iterable[Connector],
    *,
    now: datetime,
    previous_snapshots: Mapping[str, RawSnapshot] | None = None,
    previous_run_ids: Mapping[str, str] | None = None,
) -> RegistryPilotResult:
    """Fetch, normalize, and merge bounded connector runs.

    Connectors are sorted by source ID before execution. Each normalized
    candidate is retained on its ``ConnectorRunResult`` so the same fetch is
    not repeated merely to assemble the merged registry. A failed source still
    contributes its failed ``SourceRun`` and warning, while successful sources
    continue into the merge.
    """

    if now.tzinfo is None or now.utcoffset() is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ValueError("now must be timezone-aware UTC")
    ordered_connectors = tuple(sorted(connectors, key=lambda connector: connector.definition.id))
    previous_snapshots = previous_snapshots or {}
    previous_run_ids = previous_run_ids or {}
    results = tuple(
        run_connector(
            connector,
            previous_snapshots.get(connector.definition.id),
            now,
            previous_run_ids.get(connector.definition.id),
        )
        for connector in ordered_connectors
    )
    candidates = tuple(candidate for result in results for candidate in result.candidates)
    report = RegistryAssembler(
        (connector.definition for connector in ordered_connectors),
        (result.source_run for result in results),
    ).assemble_with_report(candidates)
    return RegistryPilotResult(report.registry, report, results)


__all__ = ["RegistryPilotResult", "run_registry_pilot"]
