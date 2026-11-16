"""The 22 TPC-H business questions, written in plain English.

Each question is a faithful restatement of the matching TPC-H reference query
(the version DuckDB's tpch extension ships, with the standard validation
parameters). Every question names the columns to return, because scoring
compares result sets: a model that answers the right question but returns
different columns would otherwise be marked wrong for its formatting rather
than its SQL.

Literal values are kept exactly as the reference query uses them, including
one oddity: Q19 filters on ship mode 'AIR REG', which does not occur in the
data (the real value is 'REG AIR'). A model that "fixes" it changes the answer,
so that question also tests whether the model follows the stated filter.
"""

from __future__ import annotations

QUESTIONS: dict[int, str] = {
    1: (
        "For all line items shipped on or before 1998-09-02, group by return flag and line status. "
        "Return return flag, line status, total quantity, total extended price, total discounted price "
        "(extended price * (1 - discount)), total charge (discounted price * (1 + tax)), average quantity, "
        "average extended price, average discount, and the number of line items."
    ),
    2: (
        "Consider parts of size 15 whose type ends in 'BRASS'. For each such part, find the suppliers in "
        "the EUROPE region who offer it at the lowest supply cost among all EUROPE-region suppliers of that "
        "part. Return supplier account balance, supplier name, supplier nation name, part key, part "
        "manufacturer, supplier address, supplier phone and supplier comment. Sort by account balance "
        "descending, then nation name, supplier name and part key, and keep the first 100 rows."
    ),
    3: (
        "For customers in the 'BUILDING' market segment, take their orders placed before 1995-03-15 and, "
        "within those, the line items shipped after 1995-03-15. Revenue per order is the sum of "
        "extended price * (1 - discount) over those line items. Return the 10 orders with the highest "
        "revenue (ties broken by earlier order date): order key, revenue, order date and ship priority."
    ),
    4: (
        "Count orders placed from 1993-07-01 up to but not including 1993-10-01 that have at least one "
        "line item received after its commit date. Return order priority and the order count per priority."
    ),
    5: (
        "For orders placed in 1994, consider line items where the customer and the line item's supplier "
        "are in the same nation, and that nation is in the 'ASIA' region. Return each nation's name and "
        "its revenue (sum of extended price * (1 - discount))."
    ),
    6: (
        "What is the sum of extended price * discount over line items shipped in 1994 with a discount "
        "between 0.05 and 0.07 inclusive and a quantity below 24? Return that single value."
    ),
    7: (
        "For line items shipped between 1995-01-01 and 1996-12-31 inclusive, where the supplier is in "
        "'FRANCE' and the customer in 'GERMANY', or the supplier is in 'GERMANY' and the customer in "
        "'FRANCE': return supplier nation, customer nation, the year of the ship date, and revenue "
        "(sum of extended price * (1 - discount))."
    ),
    8: (
        "Take orders from customers whose nation is in the 'AMERICA' region, dated between 1995-01-01 and "
        "1996-12-31 inclusive, and their line items for parts of type 'ECONOMY ANODIZED STEEL'. Per order "
        "year, what fraction of revenue (extended price * (1 - discount)) came from suppliers based in "
        "'BRAZIL'? Return order year and that fraction (between 0 and 1)."
    ),
    9: (
        "For line items of parts whose name contains 'green', profit is extended price * (1 - discount) "
        "minus the supplier's supply cost for that part (from partsupp) * quantity. Return the supplier's "
        "nation name, the order year, and total profit."
    ),
    10: (
        "For orders placed from 1993-10-01 up to but not including 1994-01-01, find revenue lost to "
        "returned line items (return flag 'R'), as the sum of extended price * (1 - discount) per customer. "
        "Return the top 20 customers by that revenue: customer key, customer name, revenue, account "
        "balance, nation name, address, phone and comment."
    ),
    11: (
        "For suppliers in 'GERMANY', a part's stock value is the sum of supply cost * available quantity "
        "across those suppliers. Return part key and stock value for every part whose value is greater "
        "than 0.0001 times the total stock value of all German suppliers."
    ),
    12: (
        "Take line items with ship mode 'MAIL' or 'SHIP' that were received in 1994, received after their "
        "commit date, and shipped before their commit date. Per ship mode, count how many belong to orders "
        "with priority '1-URGENT' or '2-HIGH', and how many to orders with any other priority. Return ship "
        "mode, the high-priority count and the low-priority count."
    ),
    13: (
        "Count each customer's orders, ignoring orders whose comment matches the pattern "
        "'%special%requests%'; customers with no remaining orders count as 0. Return the distribution: "
        "each order count, and the number of customers with that count."
    ),
    14: (
        "For line items shipped in September 1995, what percentage of revenue (extended price * "
        "(1 - discount)) came from parts whose type starts with 'PROMO'? Return that single value, "
        "between 0 and 100."
    ),
    15: (
        "Using line items shipped from 1996-01-01 up to but not including 1996-04-01, compute each "
        "supplier's total revenue (sum of extended price * (1 - discount)). Return the supplier or "
        "suppliers with the highest total: supplier key, name, address, phone and total revenue."
    ),
    16: (
        "Consider parts whose brand is not 'Brand#45', whose type does not start with 'MEDIUM POLISHED', "
        "and whose size is one of 49, 14, 23, 45, 19, 3, 36 or 9. Ignore suppliers whose comment matches "
        "'%Customer%Complaints%'. Return brand, type, size and the number of distinct suppliers offering "
        "parts with that brand, type and size."
    ),
    17: (
        "For parts of brand 'Brand#23' with container 'MED BOX', take the line items whose quantity is "
        "less than 20% of that part's average quantity across all of its line items. Return the sum of "
        "their extended price divided by 7.0, as a single value."
    ),
    18: (
        "Find orders whose line items add up to more than 300 units in total. Return customer name, "
        "customer key, order key, order date, order total price and the order's total quantity, for the "
        "first 100 such orders by total price descending, then order date."
    ),
    19: (
        "Return total revenue (sum of extended price * (1 - discount)) over line items with ship mode "
        "'AIR' or 'AIR REG' (use exactly these values) and ship instruction 'DELIVER IN PERSON' that match "
        "any one of these part rules: (a) brand 'Brand#12', container in 'SM CASE', 'SM BOX', 'SM PACK', "
        "'SM PKG', quantity 1 to 11, size 1 to 5; (b) brand 'Brand#23', container in 'MED BAG', 'MED BOX', "
        "'MED PKG', 'MED PACK', quantity 10 to 20, size 1 to 10; (c) brand 'Brand#34', container in "
        "'LG CASE', 'LG BOX', 'LG PACK', 'LG PKG', quantity 20 to 30, size 1 to 15. All ranges inclusive."
    ),
    20: (
        "Find suppliers in 'CANADA' that, for at least one part whose name starts with 'forest', have an "
        "available quantity (in partsupp) greater than half of the total quantity of that part they "
        "shipped in 1994. Return supplier name and address."
    ),
    21: (
        "For suppliers in 'SAUDI ARABIA', count line items they delivered late (received after the commit "
        "date) on orders with status 'F', where the same order also has line items from at least one "
        "other supplier, and none of those other suppliers' line items on the order were late. Return "
        "supplier name and that count for the top 100 suppliers by count descending, then supplier name."
    ),
    22: (
        "Take customers whose phone country code (the first two characters of the phone number) is one of "
        "'13', '31', '23', '29', '30', '18' or '17', whose account balance is above the average of the "
        "positive account balances among customers with those codes, and who have never placed an order. "
        "Return country code, the number of such customers, and the sum of their account balances."
    ),
}
