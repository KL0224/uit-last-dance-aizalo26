# Synthetic semantic metadata example

`foundation_metadata.json` contains synthetic rows and metadata for `example_shop`.
It is independent of competition data. `sales.order_id` references `orders.id`;
each sales row is one product line, keyed by `(order_id, line_no)`.

Run from the repository root:

```bash
PYTHONPATH=src python3 -m datamate \
  --metadata examples/foundation_metadata.json \
  --business-id example_shop \
  --document examples/README.md
```

The command writes Business Context JSON to stdout and omits internal profile
rows from the output. The declared sales-to-orders edge is structurally validated;
the one-to-many relationship still warns about fanout. The document remains
descriptive metadata; this example does not claim full revenue rule compliance.
