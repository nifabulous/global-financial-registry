from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .domain import (
    CandidateRecord,
    FinancialCategory,
    Institution,
    InstitutionStatus,
    RegistryInput,
    SourceDefinition,
    SourceRun,
    SourceRunStatus,
)
from .ids import StableIdAllocator
from .normalize import normalize_domain, normalize_identifier, normalize_name
from .sources import ConflictEvidence


@dataclass(frozen=True)
class MergeReport:
    registry: RegistryInput
    candidate_count: int
    institution_count: int
    lei_groups: int
    source_only_groups: int
    conflicts: tuple[ConflictEvidence, ...]


class RegistryAssembler:
    """Merge source candidates into deterministic, provenance-preserving institutions."""

    def __init__(self, sources: Iterable[SourceDefinition], source_runs: Iterable[SourceRun]):
        self.sources = tuple(sorted(sources, key=lambda source: source.id))
        self.source_runs = tuple(sorted(source_runs, key=lambda run: run.id))
        self._sources_by_id = {source.id: source for source in self.sources}
        if len(self._sources_by_id) != len(self.sources):
            raise ValueError("duplicate source definition ID")
        if len({run.id for run in self.source_runs}) != len(self.source_runs):
            raise ValueError("duplicate source run ID")
        for run in self.source_runs:
            if run.source_id not in self._sources_by_id:
                raise ValueError(f"source run references unknown source: {run.source_id}")

        self._successful_source_ids = {
            run.source_id for run in self.source_runs if run.status is SourceRunStatus.SUCCEEDED
        }
        self._allocator = StableIdAllocator()

    def assemble(self, candidates: Iterable[CandidateRecord]) -> RegistryInput:
        return self.assemble_with_report(candidates).registry

    def assemble_with_report(self, candidates: Iterable[CandidateRecord]) -> MergeReport:
        candidate_list = list(candidates)
        self._validate_candidate_sources(candidate_list)
        groups: dict[tuple[str, str], list[CandidateRecord]] = defaultdict(list)
        for candidate in candidate_list:
            groups[self._group_key(candidate)].append(candidate)

        institutions: list[Institution] = []
        identifiers = []
        conflicts: list[ConflictEvidence] = []
        lei_groups = 0
        source_only_groups = 0
        for group_key in sorted(groups):
            group = sorted(groups[group_key], key=self._candidate_sort_key)
            if group_key[0] == "lei":
                lei_groups += 1
            else:
                source_only_groups += 1
            institution, group_identifiers, group_conflicts = self._assemble_group(group_key, group)
            institutions.append(institution)
            identifiers.extend(group_identifiers)
            conflicts.extend(group_conflicts)

        registry = RegistryInput(
            institutions=sorted(institutions, key=lambda institution: institution.id),
            identifiers=sorted(identifiers, key=lambda identifier: (identifier.owner_id, identifier.type, identifier.value, identifier.source_id)),
            sources=list(self.sources),
            source_runs=list(self.source_runs),
        )
        conflicts.sort(key=lambda item: (item.field_kind, item.winner_source_id, item.losing_source_id, item.winner_value, item.losing_value))
        return MergeReport(
            registry=registry,
            candidate_count=len(candidate_list),
            institution_count=len(institutions),
            lei_groups=lei_groups,
            source_only_groups=source_only_groups,
            conflicts=tuple(conflicts),
        )

    def _validate_candidate_sources(self, candidates: list[CandidateRecord]) -> None:
        for candidate in candidates:
            if candidate.source_id not in self._sources_by_id:
                raise ValueError(f"candidate references unknown source: {candidate.source_id}")
            if candidate.source_id not in self._successful_source_ids:
                raise ValueError(f"candidate source lacks a successful source run: {candidate.source_id}")

    @staticmethod
    def _candidate_sort_key(candidate: CandidateRecord) -> tuple[str, str, str, str]:
        return (candidate.source_id, candidate.source_record_id, candidate.country_code, candidate.legal_name)

    @staticmethod
    def _lei(candidate: CandidateRecord) -> str | None:
        values = {
            normalize_identifier(identifier.type, identifier.value)
            for identifier in candidate.identifiers
            if identifier.type.strip().casefold() == "lei"
        }
        if len(values) > 1:
            raise ValueError(f"candidate {candidate.source_record_id} contains conflicting LEIs")
        return next(iter(values), None)

    def _group_key(self, candidate: CandidateRecord) -> tuple[str, str]:
        lei = self._lei(candidate)
        if lei:
            return "lei", lei
        return "source", f"{candidate.source_id}:{candidate.source_record_id}"

    def _source_priority(self, candidate: CandidateRecord, field_kind: str) -> tuple[int, str, str]:
        source = self._sources_by_id[candidate.source_id]
        if field_kind == "identity":
            rank = 0 if source.source_type.value == "gleif" else 1 if source.source_type.value == "regulator" else 2
        else:
            rank = 0 if source.source_type.value == "regulator" else 1 if source.source_type.value == "gleif" else 2
        return rank, candidate.source_id, candidate.source_record_id

    def _preferred(self, group: list[CandidateRecord], field_kind: str, attribute: str):
        candidates = [candidate for candidate in group if getattr(candidate, attribute)]
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: self._source_priority(candidate, field_kind))

    def _assemble_group(
        self,
        group_key: tuple[str, str],
        group: list[CandidateRecord],
    ) -> tuple[Institution, list, list[ConflictEvidence]]:
        identity_candidate = min(group, key=lambda candidate: self._source_priority(candidate, "identity"))
        country_candidate = self._preferred(group, "regulator", "country_code") or identity_candidate
        jurisdiction_candidate = self._preferred(group, "regulator", "regulator_jurisdiction") or country_candidate
        regulator_id_candidate = self._preferred(group, "regulator", "regulator_identifier")
        legal_name = identity_candidate.legal_name.strip()
        country_code = country_candidate.country_code
        regulator_jurisdiction = jurisdiction_candidate.regulator_jurisdiction or country_code
        canonical_key = (
            f"institution:lei:{group_key[1]}" if group_key[0] == "lei" else f"institution:source:{group_key[1]}"
        )
        institution_id = self._allocator.allocate("institution", canonical_key)

        categories = {
            category
            for candidate in group
            for category in candidate.categories
            if category in {item.value for item in FinancialCategory}
        }
        aliases = self._merge_names(group, legal_name)
        domains = sorted({domain for candidate in group for domain in (normalize_domain(value) for value in candidate.domains) if domain})
        operating_markets = sorted({country for candidate in group for country in (candidate.operating_markets or [candidate.country_code])})
        jurisdictions = sorted({country for candidate in group for country in ([candidate.regulator_jurisdiction] if candidate.regulator_jurisdiction else [])})
        if country_code not in jurisdictions:
            jurisdictions.append(country_code)
        jurisdictions = sorted(set(jurisdictions))
        source_ids = sorted({candidate.source_id for candidate in group})

        institution = Institution(
            id=institution_id,
            canonical_key=canonical_key,
            legal_name=legal_name,
            normalized_name=normalize_name(legal_name),
            country_code=country_code,
            regulator_jurisdiction=regulator_jurisdiction,
            regulator_identifier=regulator_id_candidate.regulator_identifier if regulator_id_candidate else None,
            operating_markets=operating_markets,
            categories=[FinancialCategory(category) for category in sorted(categories)],
            aliases=aliases,
            jurisdictions=jurisdictions,
            status=InstitutionStatus.UNKNOWN,
            source_ids=source_ids,
            domains=domains,
            confidence=1.0 if any(self._sources_by_id[candidate.source_id].source_type.value == "regulator" for candidate in group) else 0.8,
        )
        group_identifiers = self._merge_identifiers(institution_id, country_code, group)
        conflicts = self._find_conflicts(group, country_candidate, "country_code")
        conflicts.extend(self._find_conflicts(group, identity_candidate, "legal_name"))
        return institution, group_identifiers, conflicts

    @staticmethod
    def _merge_names(group: list[CandidateRecord], primary: str) -> list[str]:
        values: dict[str, str] = {}
        for candidate in group:
            for name in [candidate.legal_name, *candidate.aliases]:
                normalized = normalize_name(name)
                if normalized and normalized != normalize_name(primary):
                    values.setdefault(normalized, name.strip())
        return [values[key] for key in sorted(values)]

    @staticmethod
    def _merge_identifiers(institution_id: str, country_code: str, group: list[CandidateRecord]) -> list:
        identifiers = []
        seen = set()
        for candidate in group:
            for identifier in candidate.identifiers:
                normalized_value = normalize_identifier(identifier.type, identifier.value)
                key = (identifier.type.strip().casefold(), normalized_value, identifier.source_id)
                if key in seen:
                    continue
                seen.add(key)
                identifiers.append(
                    identifier.model_copy(
                        update={
                            "owner_id": institution_id,
                            "country_code": identifier.country_code or country_code,
                        }
                    )
                )
        return identifiers

    @staticmethod
    def _find_conflicts(
        group: list[CandidateRecord],
        winner: CandidateRecord,
        attribute: str,
    ) -> list[ConflictEvidence]:
        winner_value = str(getattr(winner, attribute))
        conflicts = []
        for candidate in group:
            losing_value = getattr(candidate, attribute)
            if attribute == "legal_name":
                differs = normalize_name(str(losing_value)) != normalize_name(winner_value)
            else:
                differs = str(losing_value) != winner_value
            if losing_value and differs:
                conflicts.append(
                    ConflictEvidence(
                        field_kind=attribute,
                        winner_source_id=winner.source_id,
                        losing_source_id=candidate.source_id,
                        winner_value=winner_value,
                        losing_value=str(losing_value),
                        reason="source precedence",
                    )
                )
        return conflicts
