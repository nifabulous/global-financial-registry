from __future__ import annotations

import json

import pytest

from financial_registry.domain import Institution, RegistryInput
from financial_registry.wikidata_mapping import load_reviewed_wikidata_mappings


def _institution(institution_id: str) -> Institution:
    return Institution(
        id=institution_id,
        canonical_key=f"institution:test:{institution_id}",
        legal_name="Acme Bank plc",
        normalized_name="acme bank plc",
        country_code="US",
        regulator_jurisdiction="US",
    )


def _registry(*institution_ids: str) -> RegistryInput:
    return RegistryInput(institutions=[_institution(institution_id) for institution_id in institution_ids])


def _write_mapping(path, mappings):
    path.write_text(json.dumps({"mappings": mappings}), encoding="utf-8")


def test_load_reviewed_mappings_returns_only_explicit_approved_links(tmp_path):
    path = tmp_path / "wikidata-mappings.json"
    _write_mapping(
        path,
        [
            {
                "institution_id": "inst_acme",
                "qid": "Q100",
                "review_status": "approved",
                "reviewed_by": "reviewer@example.test",
            }
        ],
    )

    assert load_reviewed_wikidata_mappings(path, _registry("inst_acme")) == {"inst_acme": "Q100"}


def test_load_reviewed_mappings_rejects_unapproved_unknown_and_duplicate_links(tmp_path):
    path = tmp_path / "wikidata-mappings.json"
    _write_mapping(
        path,
        [
            {"institution_id": "inst_acme", "qid": "Q100", "review_status": "candidate"},
        ],
    )
    with pytest.raises(ValueError, match="review_status"):
        load_reviewed_wikidata_mappings(path, _registry("inst_acme"))

    _write_mapping(
        path,
        [{"institution_id": "inst_missing", "qid": "Q100", "review_status": "approved"}],
    )
    with pytest.raises(ValueError, match="unknown institution"):
        load_reviewed_wikidata_mappings(path, _registry("inst_acme"))

    _write_mapping(
        path,
        [
            {"institution_id": "inst_acme", "qid": "Q100", "review_status": "approved"},
            {"institution_id": "inst_acme", "qid": "Q101", "review_status": "approved"},
        ],
    )
    with pytest.raises(ValueError, match="duplicate institution"):
        load_reviewed_wikidata_mappings(path, _registry("inst_acme"))


def test_load_reviewed_mappings_rejects_duplicate_qids(tmp_path):
    path = tmp_path / "wikidata-mappings.json"
    _write_mapping(
        path,
        [
            {"institution_id": "inst_acme", "qid": "Q100", "review_status": "approved"},
            {"institution_id": "inst_other", "qid": "Q100", "review_status": "approved"},
        ],
    )

    with pytest.raises(ValueError, match="duplicate Q-ID"):
        load_reviewed_wikidata_mappings(path, _registry("inst_acme", "inst_other"))


def test_load_reviewed_mappings_rejects_non_qid_values(tmp_path):
    path = tmp_path / "wikidata-mappings.json"
    _write_mapping(
        path,
        [{"institution_id": "inst_acme", "qid": "P31", "review_status": "approved"}],
    )

    with pytest.raises(ValueError, match="Q-ID"):
        load_reviewed_wikidata_mappings(path, _registry("inst_acme"))
