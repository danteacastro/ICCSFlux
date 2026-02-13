# GC Peak Library Files

JSON compound libraries for retention index (RI) based peak identification.

## Included Libraries

| File | Compounds | Use Case |
|------|-----------|----------|
| `process_gas.json` | 43 | Natural gas, refinery gas, process streams (C1-C10, sulfur, oxygenates, aromatics) |

## Building Your Own Library

Look up retention indices for your compounds at:

- **NIST WebBook** (free): https://webbook.nist.gov/chemistry/gc-ri/
  - Search by compound name, CAS number, or formula
  - Select your column type (non-polar = DB-1/HP-1/OV-101, semi-polar = DB-5/HP-5)
  - 447,000+ RI values for 112,000+ compounds

- **NIST GC RI Database** (~$300): https://chemdata.nist.gov/dokuwiki/doku.php?id=chemdata:ridatabase
  - 180,618 compounds, standalone search software

## JSON Format

```json
{
  "name": "Library Name",
  "description": "What this library covers",
  "column_phase": "non-polar (DB-1, HP-1)",
  "compounds": [
    {
      "name": "Benzene",
      "retention_index": 653,
      "formula": "C6H6",
      "molecular_weight": 78.11,
      "cas_number": "71-43-2",
      "category": "aromatic",
      "ri_tolerance": 8,
      "response_factor": 1.0,
      "unit": "mol%"
    }
  ]
}
```

## Important Notes

- RI values depend on **column phase** (non-polar vs polar). Make sure your library matches your column.
- n-Alkane RI values are defined by convention: methane=100, ethane=200, ..., n-decane=1000.
- Re-run your n-alkane reference standard whenever you change or cut the column.
- The `ri_tolerance` field controls how close a match needs to be. Tighter = fewer false positives.
