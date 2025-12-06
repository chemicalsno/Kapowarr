## Indexers

### NZBHydra2

Kapowarr can use [NZBHydra2](https://github.com/theotherp/nzbhydra2) as a Usenet meta indexer. When configured, Kapowarr will query NZBHydra2 using the Newznab-compatible API and use the returned NZB results for automatic and manual searches.

#### Base URL

The **Base URL** should point to the HTTP address of your NZBHydra2 instance.

- Example: `http://localhost:5076`
- If Kapowarr runs in Docker and NZBHydra2 runs on the host, use the host's IP/hostname instead of `localhost`.

#### API Key

The **API Key** is the NZBHydra2 API key that allows Kapowarr to talk to Hydra.

- You can find it in NZBHydra2 under **Config → Main → API Key**.
- Kapowarr sends this key in the `apikey` parameter on every Hydra request.

#### Categories

The **Categories** field controls which NZB categories NZBHydra2 should search when Kapowarr sends a request.

- This is passed as the Newznab `cat` parameter.
- The value is a comma-separated list of numeric category IDs.
- If left empty, NZBHydra2 uses its own default category handling for the request.

Examples:

- Search only the comics category (for indexers that use the standard Newznab categories):
  - `7030`
- Search multiple categories at once:
  - `7030,7000`

The exact IDs depend on your indexers and NZBHydra2 configuration. You can inspect or change them in NZBHydra2's category settings and then copy the IDs into Kapowarr.

Once configured, Kapowarr will include these categories on all NZBHydra2 searches, similar to how Sonarr/Radarr restrict searches by category.
