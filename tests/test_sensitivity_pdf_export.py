"""Regression tests for the Reaction Sensitivity Protocol PDF snapshot."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages.mixing_sensitivity as ms
from reports.pdf import build_protocol_pdf

pypdf = pytest.importorskip("pypdf")


def _pdf_text(data: bytes) -> str:
    import io

    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def test_pdf_next_steps_table_carries_the_ui_actions():
    st = SimpleNamespace(**{k: getattr(ms, k) for k in dir(ms) if k.startswith("ms_")})
    st._ms_cache = {}
    st.ms_started = True
    st.ms_competing = "No"
    st.ms_phases = ["Liquid", "Solid"]
    st.ms_kinetics_avail = ms.ms_kinetics_options[1]  # approximate -> "Kinetics" step
    st.ms_rxn_order, st.ms_rxn_k, st.ms_rxn_c0, st.ms_rxn_trxn = "1", 0.01, 1.0, 0.0
    st.ms_rxn_dh = -50.0
    ms._recompute(st)

    ui_actions = [row["Recommended action"] for row in st._ms_cache["next_steps"]]
    assert ui_actions and all(ui_actions), "UI next steps must have non-empty actions"

    text = _pdf_text(build_protocol_pdf(dict(st._ms_cache)))
    assert "Recommended Next Steps" in text
    # Each UI action's opening words must appear in the PDF (wrapping may split lines).
    for action in ui_actions:
        assert " ".join(action.split()[:3]) in text.replace("\n", " ")
