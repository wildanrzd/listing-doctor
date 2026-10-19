# Listing Doctor

Audit an Etsy listing the way a shop owner can't do by hand: pull the listing, pull what
currently outranks it for the same search, then turn that into a to-do list.

Two purposes: it's the tool, and it's the URL Etsy asks for when registering an API app.

## Setup

1. Get an Etsy API key: etsy.com/developers/register → create an app → copy the keystring.
   Then either:

   ```sh
   export ETSY_KEY=your_keystring
   ```

   or

   ```sh
   echo your_keystring > .etsy-key     # gitignored
   ```

2. Nothing else. No `pip install`. Python 3.10+, stdlib only. The AI call shells out to
   `opencode run`, so it uses an existing OpenCode subscription instead of a separate API key.

## Run

```sh
python3 audit.py doctor 4339889009
python3 audit.py doctor 4339889009 --keyword "plaid tablecloth"
python3 audit.py naive  4339889009
```

- `doctor` is the product: your listing + top competitors + their tags and prices → score,
  top 3 problems, rewritten title, 13 tags, 5 ranked fixes.
- `naive` is the honest baseline: the same listing, asked the way a normal seller would ask a
  chatbot. If `doctor` isn't clearly better than `naive`, the product isn't a product yet.

Reports land in `reports/` (gitignored) as markdown, plus a JSON dump of the exact data that
went into the prompt, so any claim in the audit can be checked against the source.

## Status

v0, October 2026. Not a product. Purpose: prove the audit is worth paying for before anything
gets wrapped into an extension or a website.
