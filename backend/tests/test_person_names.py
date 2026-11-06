"""Photo and court labels use the same first names as the text message."""

from types import SimpleNamespace

from app.services.person_names import (
    given_name,
    label_matching_text,
    photo_name_for_slot,
    roster_names_match,
    short_partnership,
)
from app.services.player_roster_sync import player_names_match
from app.services.team_photo_search import player_names_for_team


def test_compound_given_names_stay_whole():
    assert given_name("Dee Dee Worley, Alpharetta, GA") == "Dee Dee"
    assert given_name("Mary Ann Smith") == "Mary Ann"
    assert given_name("Smith, Mary Ann") == "Mary Ann"
    assert given_name("Heather Robinson") == "Heather"
    assert given_name("McDonald Jones") == "McDonald"
    assert given_name("Dee Dee") == "Dee Dee"
    assert short_partnership("Dee Dee Smith / Mike Jones") == "Dee Dee / Mike"
    assert short_partnership("Mary Ann Smith / Bob Lee") == "Mary Ann / Bob"
    assert short_partnership("elena rossi / marija petrova") == "elena / marija"


def test_photo_label_uses_the_text_first_names():
    legal = "Dee Dee Worley, Alpharetta, GA / Dennis Lamoureux, Orange Park, FL"
    assert label_matching_text("Dee Dee / Dennis", legal) == "Dee Dee / Dennis"
    assert label_matching_text("Dee / Dennis", legal) == "Dee Dee / Dennis"
    assert short_partnership(legal) == "Dee Dee / Dennis"

    lisa = "Lisa Jones, Atlanta, GA / Heather Smith, Miami, FL"
    assert label_matching_text("Lisa Jones / Heather", lisa) == "Lisa Jones / Heather"
    other_lisa = "Lisa Smith, Miami, FL / Heather Smith, Miami, FL"
    assert label_matching_text("Lisa Smith / Heather", other_lisa) == "Lisa Smith / Heather"
    assert label_matching_text("Lisa Jones / Heather", other_lisa) == "Lisa / Heather"


def test_stale_display_name_does_not_replace_the_current_players():
    legal = "Jon Miller, Ocala, FL / Lisa Steed, Ocala, FL"
    assert label_matching_text("venitta / Ed", legal) == "Jon / Lisa"
    assert label_matching_text("Eric / Leana", "Eric Tatum, Marietta, GA / Leana Tatum, Marietta, GA") == "Eric / Leana"


def test_double_name_does_not_match_a_different_person():
    assert roster_names_match("Dee Dee", "Dee Dee Worley")
    assert not roster_names_match("Dee", "Dee Dee Worley")
    assert not roster_names_match("Dee Dee Worley", "Dee Worley")
    assert roster_names_match("Mary Ann", "Mary Ann Smith")
    assert not roster_names_match("Mary Ann Smith", "Mary Smith")
    assert not player_names_match("Lisa", "Lisa Jones")
    assert not player_names_match("Heather Herman", "Heather Huling")
    assert player_names_match("Heather Herman", "Heather Herman")


def test_photo_keeps_this_team_when_a_linked_name_is_someone_else():
    team = SimpleNamespace(
        name="Mike Arsenault / Dee Dee Worley",
        display_name="Mike / Dee Dee",
    )
    assert player_names_for_team(team, ["Mike Arsenault", "Dee Dee Worley"]) == [
        "Mike Arsenault",
        "Dee Dee Worley",
    ]
    assert player_names_for_team(team, ["Mike Arsenault", "Dee Worley"]) == [
        "Mike Arsenault",
        "Dee Dee Worley",
    ]
    assert photo_name_for_slot("Lisa Jones", "Lisa Jones, Atlanta, GA", "Lisa Smith") == "Lisa Jones, Atlanta, GA"
