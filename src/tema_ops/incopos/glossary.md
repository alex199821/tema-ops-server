# IncoPOS glossary (for the AI)

Store sales: receipts from the cafés' cash registers (IncoPOS). Each branch has its own IncoPOS.
Wolt orders are not rung up in IncoPOS. Store and Wolt are separate sales,
so a branch's total sales = store + Wolt.

| branch_id | branch     | POS name      | store data from |
|-----------|------------|---------------|-----------------|
| 1         | სანაპირო   | თემა სანაპირო | 2025-03-13 |
| 2         | ლისი       | ლისი          | 2024-08-25 (before that: paper and Excel) |
| 3         | დოლაბაური  | ახალი კაფე    | 2026-09-03 (opened that afternoon; first full day 2026-09-04) |
| 4         | ივერთუბანი | ივერთუბანი    | 2026-11-02 (opened then) |

დოლაბაური here is the new café at 29 ბოჭორმის ქუჩა. The original დოლაბაური (14 ბოჭორმის ქუჩა,
since 2015) has no store data yet: say so if asked.
1–3 January and Orthodox Easter Sunday and Monday have no receipts in any branch (probably closed).

## Tables

Every IncoPOS table has `branch_id` (→ `branches.id`). Each branch's IncoPOS counts its receipts and
products on its own, so the same receipt number or product id exists in other branches:
**always join on branch_id too**.

`incopos.sales`: one row per receipt

| column      | meaning |
|-------------|---------|
| branch_id   | → `branches.id` |
| id          | receipt number, counted per branch |
| paid_at     | when it was paid, Tbilisi time. Use this for "which day" and hours. |

`incopos.sale_lines`: one row per product line on a receipt

| column      | meaning |
|-------------|---------|
| branch_id, sale_id | → `incopos.sales (branch_id, id)`. Always join on both. |
| item_id     | → `incopos.items (branch_id, id)`. Always join on both. |
| quantity    | how many units |
| price       | price per unit, GEL, incl. 18% VAT |

`incopos.items (branch_id, id, name, group_id)`: each branch's products.
`(branch_id, group_id)` → `incopos.item_groups (branch_id, id)`.
`incopos.item_groups (branch_id, id, name)`: each branch's product groups (lists below).
`incopos.locations (branch_id, id, name)`: each branch's POS name (rarely needed).

## Rules
- Store sales / revenue = `SUM(quantity * price)` over `sale_lines`. Without VAT: ÷ 1.18, in every
  branch. (სანაპირო's IncoPOS shows VAT 0 by mistake; its prices include 18% like everywhere.)
- Units sold = `SUM(quantity)`.
- Receipts = number of `incopos.sales` rows: `COUNT(*)`, or `COUNT(DISTINCT (s.branch_id, s.id))`
  after a join. Never `COUNT(DISTINCT s.id)` over several branches: the numbers repeat.
  Average receipt = revenue ÷ receipts.
- "Store sales" with no branch named = all branches together; give each branch too.
- "დოზა ყავა" (coffee doses) = cups of coffee sold = units of the group ყავა (a double is one cup).
  That group also has ჩაი, ცხელი შოკოლადი, ორმაგი ცხელი შოკოლადი, ცივი მაჩა, პოდი (and at ლისი
  მაჩა ლატე): say how many of those are included.
- Sandwiches (every branch) = the food group minus the salads and fries:
  `g.name IN ('მზა პროდუქცია', 'სენდვიჩები') AND i.name NOT IN ('ცეზარი', 'ბერძნული', 'ტუნა', 'ფრი', 'კარტოფილი ფრი') AND i.name NOT LIKE '%სალათი%'`
- A day = `paid_at::date` (calendar day, 00:00–24:00).
- Filter products by `items.name`, not by id (ids differ per branch, and one name can have two ids).
- Product and group names differ between branches (see the end). To compare a product across
  branches, add up its names in each branch and say which names you used.
- Store product names are not the same as Wolt's: match each source by its own names.
- IncoPOS has no card/cash split, no cashier, no customer and no discounts, and its costs are wrong.
  Profit can't be calculated from it. Say so instead of looking.

## Product groups and products (დოლაბაური and ივერთუბანი; ლისი and სანაპირო differ, see below)
- მზა პროდუქცია (food):
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

### ლისი: the same names, except
- cold drinks are in the group გამაგრილებელი სასმელები (not ცივი სასმელები)
- sauces and add-ons are in ნედლეული: #პიკანტური 0,50, #კეტჩუპი 0,50, #მაიონეზი 0,50, გ ლ ა ს ა
- spirits by the glass: ბეილისი 0,050, ჯეიმსონი 0,05, აბსოლუტი 0,05, ფილანდია 0,05, ჯეკ დენიელსი 0,05
- also: ტუნას სალათი (a salad), მაჩა ლატე (in ყავა), სნო არომატით

### სანაპირო: its own groups and many of its own names
- სენდვიჩები (food, incl. the salads ბერძნული სალათი, თინუსის სალათი and კარტოფილი ფრი)
- გამაგრილებელი სასმელები (cold drinks, incl. რედბული 0,250 and რედბული დიდი)
- ყავა, ალკო, დანამატები (სიროფი, ნუშის რძე)
- ინგრედიენტები (sauces: აჯიკა, პიკანტური, კეჩუპი, მაიონეზი), სახარჯი მასალები (packaging)
- პ ო დ ი ს (ყავები): pods and coffee by the kilo to take home (უკოფეინო პოდი, ყავა ფლორიო 1კგ,
  რუჟი რიშარი 1კგ…), not cups
- its names for products the others name differently (probably the same product, not checked yet):
  ქათმის როლი = როლი, კარტოფილი ფრი = ფრი, სენდვიჩი ლორით = ლორის სენდვიჩი,
  წითელი ქაშაყის სენდვიჩი = ქაშაყის სენდვიჩი, ქათმის სენდვიჩი ლავაშში, ორმაგი ქათმის სენდვიჩი ლავაშში,
  კოლა 500 = კოკა კოლა 0,500, კოლა ზერო = კოკა კოლა ზერო, სნო = სნო 0,5, ფანტა, სპრაიტი, ბერნი,
  ორმაგო ესპრესო = ორმაგი ესპრესო, ჯეიმსონი 0,5, აბსოლიტი, ბეილისი, ფილანდია

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
SELECT 'store', b.name, SUM(l.quantity * l.price), COUNT(DISTINCT s.id)  -- one branch per row, so ids don't repeat
FROM incopos.sales s
JOIN incopos.sale_lines l ON l.branch_id = s.branch_id AND l.sale_id = s.id
JOIN branches b ON b.id = s.branch_id
WHERE s.paid_at::date = CURRENT_DATE - 1
GROUP BY b.name;
```

Coffee drinks sold per day and branch in the last 7 days
```sql
SELECT s.paid_at::date AS day, b.name AS branch, i.name, SUM(l.quantity) AS units
FROM incopos.sale_lines l
JOIN incopos.sales s ON s.branch_id = l.branch_id AND s.id = l.sale_id
JOIN incopos.items i ON i.branch_id = l.branch_id AND i.id = l.item_id
JOIN incopos.item_groups g ON g.branch_id = i.branch_id AND g.id = i.group_id
JOIN branches b ON b.id = s.branch_id
WHERE g.name = 'ყავა' AND s.paid_at::date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE - 1
GROUP BY 1, 2, 3
ORDER BY 1, 2, 4 DESC;
```
