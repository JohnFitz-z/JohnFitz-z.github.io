# Morning Line

One researched sports bet a day, with the reasoning and a running record. Live at https://johnfitz-z.github.io

- `index.html` is the site. It reads `picks.json`.
- `picks.json` holds every pick and result. The daily run rebuilds it each morning with `model/export_site.py`.
- `model/` is the pricing engine: margin removal, sport score models, blending, capped adjustments, Kelly staking, minimum price and closing line value. `model/METHOD.md` explains the method and inputs.
- `tools/build_artifact.py` makes the claude.ai copy of the page.

Run the tests with `python3 -m unittest model/test_pricing.py`.
