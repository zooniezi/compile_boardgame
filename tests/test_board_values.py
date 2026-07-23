from src.game import rules as Rules


def test_empty_line_value_is_zero(engine):
    assert engine.line_value(1, 1) == 0


def test_line_value_sums_face_up_cards(engine):
    e = engine
    c1 = e.new_card("Water", 3, 1)
    c1.face_up = True
    c2 = e.new_card("Water", 2, 1)
    c2.face_up = True
    e.players[1]["stacks"][1].extend([c1, c2])
    assert e.line_value(1, 1) == 5


def test_facedown_card_counts_as_default_value(engine):
    e = engine
    c1 = e.new_card("Water", 5, 1)
    c1.face_up = False  # 뒷면이면 값이 안 보이고 기본값(2)으로 취급
    e.players[1]["stacks"][1].append(c1)
    assert e.line_value(1, 1) == 2


def test_facedown_value_this_stack_passive_overrides_default(engine):
    e = engine
    top = e.new_card("Metal", 0, 1)
    top.face_up = True
    top.definition = {"passive": {"facedownValueThisStack": 4}}
    hidden = e.new_card("Water", 5, 1)
    hidden.face_up = False
    e.players[1]["stacks"][1].extend([top, hidden])
    # hidden은 뒷면이라 4로 취급, top은 앞면이라 값(0) 그대로.
    assert e.line_value(1, 1) == 4 + 0


def test_winning_line_requires_strictly_more(engine):
    e = engine
    assert e.winning_line(1, 1) is False  # 0 vs 0

    c = e.new_card("Water", 1, 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)
    assert e.winning_line(1, 1) is True
    assert e.winning_line(2, 1) is False


def test_compilable_lines_needs_threshold_and_winning(engine):
    e = engine
    c = e.new_card("Water", 6, 1)
    c.face_up = True
    e.players[1]["stacks"][1].append(c)
    assert e.compilable_lines(1) == []  # 값 6 < 임계값(10)

    c2 = e.new_card("Water", 5, 1)
    c2.face_up = True
    e.players[1]["stacks"][1].append(c2)
    assert e.line_value(1, 1) == 11 >= Rules.COMPILE_THRESHOLD
    assert e.compilable_lines(1) == [1]


def test_compilable_lines_empty_when_cant_compile_flag_set(engine):
    e = engine
    c = e.new_card("Water", 6, 1)
    c.face_up = True
    c2 = e.new_card("Water", 5, 1)
    c2.face_up = True
    e.players[1]["stacks"][1].extend([c, c2])
    e.cant_compile[1] = True
    assert e.compilable_lines(1) == []


def test_cards_with_def_field_top_only(engine):
    e = engine
    bottom = e.new_card("Water", 0, 1)
    bottom.face_up = True
    bottom.definition = {"someFlag": True}
    top = e.new_card("Water", 1, 1)
    top.face_up = True
    top.definition = {"someFlag": True}
    e.players[1]["stacks"][1].extend([bottom, top])

    all_matches = e.cards_with_def_field("someFlag")
    assert set(all_matches) == {bottom, top}

    top_only = e.cards_with_def_field("someFlag", {"top_only": True})
    assert top_only == [top]
