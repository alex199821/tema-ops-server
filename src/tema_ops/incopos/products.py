"""One product list for all branches.

Each branch's IncoPOS names its products its own way (სანაპირო "ქათმის როლი" = the others' "როლი").
The shared list (the `products` table) has one row per real product, and every IncoPOS product
(`incopos.items.product_id`) points to one. load_incopos.py keeps the links up to date.

How a branch's product gets its shared name:
- if it is in RENAMES below: that name (checked by a person, 2026-11-28)
- otherwise its own name, with the spaces tidied. So the same name in two branches = one product.
A product that is new and has a new name becomes a new shared product by itself; if it is really
an existing product under another name, add it to RENAMES.
Kept apart on purpose (not the same product): სნო 1,5 / სნო 0,5, ესტრელა0,330 / ესტრელა ქილა,
უკოფეინო პოდი / პოდი, მაჩა ლატე / ცივი მაჩა.
"""
import re

# branch (its key in branches.py) → {its IncoPOS name: the shared name}
RENAMES = {
    "sanapiro": {
        # food
        "ქათმის როლი": "როლი",
        "კარტოფილი ფრი": "ფრი",
        "სენდვიჩი ლორით": "ლორის სენდვიჩი",
        "ქათმის სენდვიჩი ლავაშში": "ქათამი ლავაშით",
        "ორმაგი ქათმის სენდვიჩი ლავაშში": "ლავაშში ორმაგი ქათმის სენდვიჩი",
        "წითელი ქაშაყის სენდვიჩი": "ქაშაყის სენდვიჩი",
        "სოკოს პიტა": "პიტა სოკოთი",
        "ბერძნული სალათი": "ბერძნული",
        "თინუსის სალათი": "ტუნა",
        # coffee
        "ორმაგო ესპრესო": "ორმაგი ესპრესო",
        "ამერიკანო ცივი რძით": "ამერიკანი ცივი რძით",
        # drinks
        "კოლა 500": "კოკა კოლა 0,500",
        "კოლა ზერო": "კოკა კოლა ზერო",
        "სნო": "სნო 0,5",
        "ფანტა": "ფანტა 0,500",
        "სპრაიტი": "სპრაიტი 0,500",
        "ბერნი": "ენერგეტიკული ბერნი",
        "ე ნ ე რ გ ე ტ ი კ უ ლ ი ბორჯომის": "ბორჯომის ენერგეტიკული",
        "რედბული დიდი": "რედბული 0,355",
        "რედბული 0,250": "რედბული 0,25",
        "ცივი ჩაი მანგო ანანასი": "ცივი ჩაი მანგო-ანანასი",
        "ცივი ჩაი დრაგონის ვნება": "დრაგონის ვნება",
        "ლიმონ ფრეში": "ლაიმონ ფრეში",
        # add-ons and packaging
        "სიროფი": "სიროფი 0,030",
        "ნუშის რძე": "ნუშის რძის დანამატი",
        "აჯიკა": "აჯიკის დანამატი",
        "პიკანტური": "პიკანტური 0,50",
        "კეჩუპი": "კეტჩუპი 0,50",
        "მაიონეზი": "მაიონეზი 0,50",
        "2იანი ჭიქის დასადები": "ორიანი ჭიქის დასადები",
        "4იანი ჭიქის დასადები": "ჭიქის ჩასადები 4 იანი",
        # spirits by the glass
        "ბეილისი": "ბეილისი 0,50",
        "აბსოლიტი": "აბსოლუტი 0,50",
        "ფილანდია": "ფილანდია 0,50",
        "ჯეკ დენიელსი": "ჯეკ დენიელსი 0,50",
        "ჯეიმსონი 0,5": "ჯეიმსონი 0,50",
    },
    "lisi": {
        "ტუნას სალათი": "ტუნა",
        "#კეტჩუპი 0,50": "კეტჩუპი 0,50",
        "#მაიონეზი 0,50": "მაიონეზი 0,50",
        "#პიკანტური 0,50": "პიკანტური 0,50",
        "ბეილისი 0,050": "ბეილისი 0,50",
        "აბსოლუტი 0,05": "აბსოლუტი 0,50",
        "ფილანდია 0,05": "ფილანდია 0,50",
        "ჯეკ დენიელსი 0,05": "ჯეკ დენიელსი 0,50",
        "ჯეიმსონი 0,05": "ჯეიმსონი 0,50",
        "ჩივასი 0,05": "ჩივასი",
    },
}


def tidy(name: str) -> str:
    """Spaces tidied: "ცივი  ყავა ბეილისით" (two spaces) = "ცივი ყავა ბეილისით"."""
    return re.sub(r"\s+", " ", name).strip()


def product_name(branch: str, name: str) -> str:
    """The shared product name of a branch's IncoPOS product."""
    name = tidy(name)
    return RENAMES.get(branch, {}).get(name, name)
