# Wolt glossary (for the AI)

Orders that customers placed through Wolt (delivery app).
Data starts 2026-08-10 for სანაპირო and ლისი, 2026-09-07 for დოლაბაური.

## Tables

`wolt.venues (id, branch_id, name)`: each branch's Wolt store, one per branch.
`branch_id` → `branches.id`.

| venues.name       | branch    |
|-------------------|-----------|
| Tema Gamsakhurdia | სანაპირო  |
| Tema Amashukeli   | ლისი      |
| Tema Dolabauri    | დოლაბაური |

`wolt.orders`: one row per Wolt order

| column         | meaning |
|----------------|---------|
| purchase_id    | order id |
| venue_id       | → `wolt.venues.id` |
| order_number   | short number the staff see |
| status         | `DELIVERED`, or `REJECTED` (never made, not a sale) |
| received_at    | when the order came in. Use this for "which day". |
| delivered_at   | when it was delivered; empty for rejected orders |
| total_gross    | what the customer paid, GEL, incl. 18% VAT |
| total_net      | total_gross without VAT (= total_gross / 1.18) |
| is_cash        | true = paid cash to the courier |
| rating         | 1–5 stars; empty = not rated (most orders are not rated) |
| review_comment | customer's written comment; often empty |
| raw            | the full original order (JSON), see below |

`wolt.order_items`: one row per product line in an order

| column      | meaning |
|-------------|---------|
| purchase_id | → `wolt.orders.purchase_id` |
| row_number  | position of the line in the order |
| name        | product name in Georgian (list below) |
| count       | how many units |
| final_gross | line total, GEL, incl. VAT (= count × price) |
| final_net   | the same without VAT |

Useful fields inside `wolt.orders.raw`:

| field | meaning |
|-------|---------|
| `raw->>'delivery_method'` | `HOMEDELIVERY` or `TAKEAWAY` |
| `raw->>'order_type'` | `INSTANT` or `PREORDER` |
| `raw->'rejection'->>'message'` | why an order was rejected |
| `raw->'review_attributions'` | tags the customer picked with their rating: `FLAVOUR`, `PORTION_SIZE`, `TEXTURE`, `APPEARANCE`, `PACKAGING`. Often empty. |
| `raw->'items'->N->'options'` | add-ons chosen with an item (e.g. extra sauce) |

## Rules
- Wolt sales / revenue = `SUM(total_gross)` of `DELIVERED` orders only.
- Number of orders = `DELIVERED` orders, unless the question is about rejections.
- Units sold = `SUM(order_items.count)` of `DELIVERED` orders.
- Ratings: 4–5 = positive, 1–3 = negative. Average only over rated orders,
  and always say how many orders were rated (few orders have a rating).
- Sauces sold as products (კეტჩუპი, მაიონეზი, აჯიკა, სოუსი პიკანტური) are
  different from sauces added to an item (those are in `raw` options).
- For branch questions, join `wolt.orders` → `wolt.venues` → `branches`.

## Products (Wolt names)
- Rolls & pitas: ქათმის როლი, სოკოს როლი სამარხვო, პიტა ცეზარი, ლეგო პიტა ცეზარი
- Sandwiches: ქათმის სენდვიჩი, ქათმის სენდვიჩი ორმაგი შიგთავსით,
  ლორის და ყველის სენდვიჩი, ლორის და ყველის სენდვიჩი ორმაგი შიგთავსით,
  წითელი ქაშაყის სენდვიჩი, ბურგერი
- Salads: ცეზარი, ბერძნული, ტუნას სალათი
- Sides & sauces: კარტოფილი ფრი 250 გრ + კეტჩუპი, კეტჩუპი, მაიონეზი, აჯიკა,
  სოუსი პიკანტური
- Drinks: კოლა კლასიკი, კოლა ზერო, ცივი ლატე, ცივი ყავა, ცივი ყავა ნაყინით,
  ცივი ჩაი ატამი, ცივი ჩაი მანგო- ანანასი

## Examples

How much did ლისი sell on Wolt yesterday?
```sql
SELECT SUM(o.total_gross) AS sales_gel
FROM wolt.orders o
JOIN wolt.venues v ON v.id = o.venue_id
JOIN branches b ON b.id = v.branch_id
WHERE b.name = 'ლისი'
  AND o.status = 'DELIVERED'
  AND o.received_at::date = CURRENT_DATE - 1;
```

Which products get bad ratings most often?
(Compare the share of bad ratings, not raw counts: popular products appear in
more orders of every kind. Skip products with too few rated orders.)
```sql
SELECT i.name,
       COUNT(*) AS rated_orders,
       COUNT(*) FILTER (WHERE o.rating <= 3) AS low_rated,
       ROUND(100.0 * COUNT(*) FILTER (WHERE o.rating <= 3) / COUNT(*), 1) AS low_rated_pct
FROM wolt.orders o
JOIN wolt.order_items i USING (purchase_id)
WHERE o.status = 'DELIVERED' AND o.rating IS NOT NULL
GROUP BY i.name
HAVING COUNT(*) >= 20
ORDER BY low_rated_pct DESC;
```
