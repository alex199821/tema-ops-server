from tema_ops.incopos.products import RENAMES, product_name


def test_a_renamed_product_gets_the_shared_name():
    assert product_name("sanapiro", "ქათმის როლი") == "როლი"
    assert product_name("lisi", "#კეტჩუპი 0,50") == "კეტჩუპი 0,50"


def test_the_same_name_is_the_same_product_in_every_branch():
    assert product_name("dolabauri", "როლი") == product_name("ivertubani", "როლი") == "როლი"


def test_spaces_are_tidied():
    assert product_name("lisi", "ცივი  ყავა ბეილისით ") == "ცივი ყავა ბეილისით"


def test_a_rename_only_counts_in_its_own_branch():
    # სანაპირო's "სნო" is the 0,5 bottle; in another branch the name stays as it is
    assert product_name("sanapiro", "სნო") == "სნო 0,5"
    assert product_name("lisi", "სნო") == "სნო"


def test_no_rename_points_to_another_rename():
    # a shared name must be final, not itself renamed again
    for renames in RENAMES.values():
        for shared in renames.values():
            assert all(shared not in other for other in RENAMES.values())
