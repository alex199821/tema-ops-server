# IncoPOS glossary (for the AI)

Store sales: receipts from the cafés' cash register (IncoPOS).
Wolt orders are not rung up in IncoPOS. Store and Wolt are separate sales,
so a branch's total sales = store + Wolt.
Data starts 2026-09-03 (the café opened that afternoon; the first full day is 2026-09-04).

## Tables

`incopos.locations (id, branch_id, name)`: one row per café. `branch_id` → `branches.id`.

| locations.id | name       | branch                              |
|--------------|------------|-------------------------------------|
| 2            | ახალი კაფე | not linked yet (`branch_id` empty)  |

So far ახალი კაფე (ბოჭორმის ქუჩა) is the only café with store data, and it is not linked
to a branch yet. For store sales of სანაპირო, ლისი or დოლაბაური, say there is no store
data for them yet.

`incopos.sales`: one row per receipt

| column      | meaning |
|-------------|---------|
| location_id | → `incopos.locations.id` |
| id          | receipt id (unique within a location) |
| paid_at     | when it was paid, Tbilisi time. Use this for "which day" and hours. |

`incopos.sale_lines`: one row per product line on a receipt

| column      | meaning |
|-------------|---------|
| location_id, sale_id | → `incopos.sales (location_id, id)`. Always join on both. |
| item_id     | → `incopos.items.id` |
| quantity    | how many units |
| price       | price per unit, GEL, incl. 18% VAT |

`incopos.items (id, name, group_id)`: products. `group_id` → `incopos.item_groups.id`.
`incopos.item_groups (id, name)`: product groups (list below).

## Rules
- Store sales / revenue = `SUM(quantity * price)` over `sale_lines`. Without VAT: ÷ 1.18.
- Units sold = `SUM(quantity)`.
- "დოზა ყავა" (coffee doses) = cups of coffee sold = units of the group ყავა (a double is one cup).
  That group also has ჩაი, ცხელი შოკოლადი, ორმაგი ცხელი შოკოლადი, ცივი მაჩა and პოდი:
  say how many of those are included.
- Receipts = number of `incopos.sales` rows. Average receipt = revenue ÷ receipts.
- A day = `paid_at::date` (calendar day, 00:00–24:00).
- Filter products by `items.name`, not by id (one name has two ids).
- Store product names are not the same as Wolt's: match each source by its own names.
- IncoPOS has no card/cash split, no cashier, no customer and no discounts,
  and its costs are wrong. Profit can't be calculated from it. Say so instead of looking.

## Product groups and products (store names)
- მზა პროდუქცია (food). Sandwiches = every product of this group except the 3 salads and ფრი:
  `g.name = 'მზა პროდუქცია' AND i.name NOT IN ('ცეზარი', 'ბერძნული', 'ტუნა', 'ფრი')`
  - sandwiches: როლი, ქათმის სენდვიჩი, პიტა ცეზარით, ორმაგი ქათმის სენდვიჩი, ბურგერი,
    ლორის სენდვიჩი, ტოსტი ლორით, ქათამი ლავაშით, ორმაგი ლორის სენდვიჩი, ვრაპი, ორმაგი ტოსტი,
    სოკოს როლი, ლავაშში ორმაგი ქათმის სენდვიჩი, ქაშაყის სენდვიჩი, პიტა დაშლილი, ვეჯი ბურგერი,
    ლორის სენდვიჩი ლავაშში, პიტა ლავაშში, სოკოს სენდვიჩი, პიტა სოკოთი,
    ორმაგი ლორის სენდვიჩი ლავაშში, ბოსტნეულის სენდვიჩი, ვეჯი ლავაშში
  - salads: ცეზარი, ბერძნული, ტუნა
  - side: ფრი
- ყავა (hot drinks, incl. tea and hot chocolate): ამერიკანო, კაპუჩინო, ჩაი, ცივი ყავა ნაყინით,
  ლატე, ორმაგი ამერიკანო, ორმაგი კაპუჩინო, ცხელი შოკოლადი, ცივი ყავა, ორმაგი ესპრესო,
  ცივი კაპუჩინო, ესპრესო, ფლეთ ვაითი, პოდი, მოჩა ლატე, კაპუჩინო ნუშის რძით, ყავა ბეილისით,
  მოკა, ცივი მოკა, ცივი მაჩა, ამერიკანი ცივი რძით, ირლანდიური ყავა, ცივი ყავა ბეილისით,
  ორმაგი ცხელი შოკოლადი
- ცივი სასმელები (cold drinks, incl. beer and fresh juice): კოკა კოლა 0,500, ბაკურიანი,
  ცივი ჩაი, სნო 0,5, კოკა კოლა ზერო, ფრეში, მთის წყალი, ბორჯომის ლიმონათი, იქსელი, ლუდი,
  ფანტა 0,500, ლიმონათი, ბორჯომი 0,5, სპრაიტი 0,500, ენერგეტიკული ბერნი, ბაკურიანი არომატით,
  ბორჯომის ენერგეტიკული, ლიკანი, ბორჯომი ქილა, ლუდი ბავარია, ესტრელა ქილა,
  ცივი ჩაი მანგო-ანანასი, სნო არომატით, ცივი ჩაი ატამი, ცივი ჩაი მანგო გვირილა,
  ლუდი კაიაკი, ტყის კენკრა
- რედბული: რედბული 0,25, რედბული 0,355
- ალკო (spirits): ჯეიმსონი 0,50, ჯეკ დენიელსი 0,50, აბსოლუტი 0,50, ჩივასი, ბეილისი 0,50,
  ფილანდია 0,50
- დანამატები (add-ons and packaging): აჯიკის დანამატი, ერთჯერადი ჭიქა, სიროფი 0,030,
  პიკანტური 0,50, ყველის დანამატი, კეტჩუპი 0,50, ჰალაპენიო, სალათის კონტეინერი,
  ნუშის რძის დანამატი, ჭიქის ჩასადები 4 იანი, მაიონეზი 0,50, ორიანი ჭიქის დასადები,
  აჯიკა კონტეინერით, რძის დანამატი
- სომხური ლავაში: ლავაში
- დოლაბაური: პიტის პური, ფრანგული პური

The other groups (mostly supplier names) have no sales.

## Examples

How were sales yesterday? (store and Wolt in one query)
```sql
SELECT 'Wolt' AS source, b.name AS place,
       SUM(o.total_gross) AS sales_gel, COUNT(*) AS orders_or_receipts
FROM wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
JOIN branches b ON b.id = v.branch_id
WHERE o.status = 'DELIVERED' AND o.received_at::date = CURRENT_DATE - 1
GROUP BY b.name
UNION ALL
SELECT 'store', loc.name, SUM(l.quantity * l.price), COUNT(DISTINCT s.id)
FROM incopos.sales s
JOIN incopos.sale_lines l ON l.location_id = s.location_id AND l.sale_id = s.id
JOIN incopos.locations loc ON loc.id = s.location_id
WHERE s.paid_at::date = CURRENT_DATE - 1
GROUP BY loc.name;
```

Coffee drinks sold per day in the last 7 days
```sql
SELECT s.paid_at::date AS day, i.name, SUM(l.quantity) AS units
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.location_id = l.location_id AND s.id = l.sale_id
JOIN incopos.items i ON i.id = l.item_id
JOIN incopos.item_groups g ON g.id = i.group_id
WHERE g.name = 'ყავა' AND s.paid_at::date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
```
