"""Regression tests for strict license metadata classification and separated evaluation metrics."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from lyraforge.instruments import load_builtin_profile
from lyraforge.music_core import (
    ArrangeOptions,
    NormalizedScore,
    Note,
    TimeSignature,
    TrackInfo,
    arrange,
    evaluate_arrangement_against_reference,
    evaluate_transcription_against_reference,
    score_arrangement,
)
from lyraforge.music_core.arranger import Style
from lyraforge.music_core.tempo import TempoChange, TempoMap
from lyraforge.sources import (
    OpenMusicCatalogSourceAdapter,
    SourceCandidate,
    classify_license_url,
    rank_candidates,
)


def test_classify_license_url_strict_allowlist_and_negative_cases() -> None:
    cc0 = classify_license_url("http://creativecommons.org/publicdomain/zero/1.0/")
    assert cc0.license_id == "CC0-1.0"
    assert cc0.status == "open_permissive"
    assert cc0.allow_derivative is True
    assert cc0.normalized_url == "https://creativecommons.org/publicdomain/zero/1.0/"

    pdm = classify_license_url("https://www.creativecommons.org/publicdomain/mark/1.0/")
    assert pdm.license_id == "PDM-1.0"
    assert pdm.status == "open_permissive"
    assert pdm.allow_derivative is True

    by = classify_license_url("https://creativecommons.org/licenses/by/4.0/")
    assert by.license_id == "CC-BY-4.0"
    assert by.status == "open_permissive"
    assert by.allow_derivative is True

    nc = classify_license_url("https://creativecommons.org/licenses/by-nc-sa/4.0/")
    assert nc.license_id == "CC-BY-NC-SA-4.0"
    assert nc.status == "open_restricted"
    assert nc.allow_derivative is True

    # NoDerivatives forbids re-arrangement / derivative adaptation
    nd = classify_license_url("https://creativecommons.org/licenses/by-nd/4.0/")
    assert nd.license_id == "CC-BY-ND-4.0"
    assert nd.status == "open_restricted"
    assert nd.allow_derivative is False

    # Rejected weak/unrelated/spoofed inputs
    bad_inputs = [
        "",
        "MIT",
        "GPL-3.0",
        "local",
        "free to use on YouTube mit",
        "ftp://creativecommons.org/publicdomain/zero/1.0/",
        "https://user:pass@creativecommons.org/licenses/by/4.0/",
        "https://evil-creativecommons.org/licenses/by/4.0/",
        "https://creativecommons.org.attacker.example/publicdomain/zero/1.0/",
        "https://example.com/redirect?url=https://creativecommons.org/licenses/by/4.0/",
        "https://creativecommons.org/licenses/mit/1.0/",
        "https://creativecommons.org/licenses/by/notaversion/",
    ]
    for raw in bad_inputs:
        cls = classify_license_url(raw)
        assert cls.status == "unknown", f"unexpectedly trusted {raw!r}: {cls}"
        assert cls.allow_derivative is False


def test_online_catalog_rejects_ambiguous_mixed_private_and_nd_licenses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lyraforge.sources.url.socket.getaddrinfo",
        lambda *_a, **_kw: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._buf = io.BytesIO(body)

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, n: int = -1) -> bytes:
            return self._buf.read(n)

    routes = {
        "https://archive.org/advancedsearch.php": json.dumps({
            "response": {
                "docs": [
                    {
                        "identifier": "bad_substr",
                        "title": "Demo",
                        "licenseurl": "https://example.com/?ref=creativecommons.org/mit",
                    },
                    {
                        "identifier": "bad_nd",
                        "title": "Demo ND",
                        "licenseurl": "https://creativecommons.org/licenses/by-nd/4.0/",
                    },
                    {
                        "identifier": "mixed_files",
                        "title": "Mixed Piece",
                        "creator": "Archivist",
                        "licenseurl": "https://creativecommons.org/licenses/by/4.0/",
                    },
                ]
            }
        }).encode("utf-8"),
        "https://archive.org/metadata/mixed_files/files": json.dumps({
            "result": [
                {"name": "secret.mid", "private": "true"},
                {"name": "proprietary.mid", "license": "All Rights Reserved"},
                {"name": "ok.mid", "license": "CC0-1.0"},
            ]
        }).encode("utf-8"),
    }

    class _Router:
        def open(self, req: Any, timeout: float = 15.0) -> _FakeResp:
            _ = timeout
            url = req.full_url if hasattr(req, "full_url") else str(req)
            for prefix, body in routes.items():
                if url.startswith(prefix):
                    return _FakeResp(body)
            raise AssertionError(f"unexpected URL {url}")

    adapter = OpenMusicCatalogSourceAdapter(opener=_Router())
    cands = adapter.search("Demo")
    assert len(cands) == 1
    c = cands[0]
    assert c.id == "mixed_files/ok.mid"
    assert c.license_id == "CC0-1.0"
    assert c.license_status == "open_permissive"
    assert c.license_url == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert c.source_url == "https://archive.org/details/mixed_files"
    assert c.fetched_at.endswith("Z")
    assert "independent rights" in c.rights_scope_note

    # Ranking must trust user_local > open_permissive > open_restricted > unknown
    ordered = rank_candidates(
        [
            SourceCandidate("archive.org", "u", "X", "", "midi", "u", "MIT", True),
            SourceCandidate(
                "archive.org",
                "r",
                "X",
                "",
                "midi",
                "r",
                "NC",
                True,
                license_id="CC-BY-NC-4.0",
                license_status="open_restricted",
                license_url="https://creativecommons.org/licenses/by-nc/4.0/",
            ),
            SourceCandidate(
                "archive.org",
                "p",
                "X",
                "",
                "audio",
                "p",
                "CC0",
                True,
                license_id="CC0-1.0",
                license_status="open_permissive",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            ),
            SourceCandidate(
                "library",
                "l",
                "X",
                "",
                "audio",
                "l",
                "Local",
                False,
                license_id="user_local",
                license_status="user_local",
            ),
        ],
        "X",
    )
    assert [x.id for x in ordered] == ["l", "p", "r", "u"]


def test_separated_transcription_fidelity_vs_arrangement_playability() -> None:
    profile = load_builtin_profile()
    # Ground truth chord notes at 0ms and 500ms (C major + F major)
    ref_notes = [
        (0, 60),
        (0, 64),
        (0, 67),
        (500, 65),
        (500, 69),
        (500, 72),
    ]
    # Wrongly transcribed pitches that happen to lie on valid Windsong Lyre white keys!
    bad_notes = (
        Note(
            pitch=62,
            velocity=80,
            start_tick=0,
            end_tick=288,
            start_us=0,
            end_us=300_000,
            track=0,
            channel=0,
        ),
        Note(
            pitch=67,
            velocity=80,
            start_tick=480,
            end_tick=768,
            start_us=500_000,
            end_us=800_000,
            track=0,
            channel=0,
        ),
    )
    bad_score = NormalizedScore(
        source_sha256="deadbeef" * 8,
        midi_type=1,
        ticks_per_beat=480,
        tempo_map=TempoMap(480, (TempoChange(0, 500_000),)),
        time_signatures=(TimeSignature(0, 0, 4, 4),),
        tracks=(TrackInfo(0, "mono", 2, (0,)),),
        notes=bad_notes,
        duration_us=800_000,
        warnings=(),
    )

    tf = evaluate_transcription_against_reference(ref_notes, bad_notes)
    assert tf.f1 == 0.0
    assert tf.true_positives == 0
    assert tf.onset_alignment_rate > 0.0

    arr = arrange(bad_score, profile, ArrangeOptions(style=Style.BALANCED))
    qual = score_arrangement(bad_score, arr).to_json()
    # Arrangement playability vs transcribed MIDI is high even though original pitch recall is 0
    assert arr.stats["playable_ratio"] == 1.0
    assert qual["score_scope"] == "arrangement_vs_input_midi"
    assert qual["arrangement_playability_score"] == 100.0
    assert qual["subjective_listening_status"] == "unrated_manual_preview_required"

    e2e = evaluate_arrangement_against_reference(ref_notes, arr)
    assert e2e["matched_reference_notes"] == 0
    assert e2e["reference_pitch_recall"] == 0.0
