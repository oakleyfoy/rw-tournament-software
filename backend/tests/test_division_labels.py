"""Dashboard division labels for numbered brackets and the Women's B round robin."""

from app.routes.desk import _derive_division


def test_womens_a_keeps_four_named_divisions():
    assert _derive_division("WOM_WOM_E33_BWW_M7", "MAIN") == "Division I"
    assert _derive_division("WOM_WOM_E33_BWL_M7", "MAIN") == "Division II"
    assert _derive_division("WOM_WOM_E33_BLW_M7", "MAIN") == "Division III"
    assert _derive_division("WOM_WOM_E33_BLL_C3", "CONSOLATION") == "Division IV"


def test_womens_b_brackets_and_round_robin_are_divisions():
    assert _derive_division("WOM_WOM_E34_B1_M7", "MAIN") == "Division I"
    assert _derive_division("WOM_WOM_E34_B2_C3", "CONSOLATION") == "Division II"
    assert _derive_division("WOM_WOM_E34_B3_M1", "MAIN") == "Division III"
    assert _derive_division("WOM_WOM_E34_DIV4_RR_01", "RR") == "Division IV"
    assert _derive_division("WOM_WOM_E34_WF_R1_01", "WF") is None
