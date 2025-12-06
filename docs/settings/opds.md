## OPDS

Kapowarr includes an [OPDS](https://en.wikipedia.org/wiki/Open_Publication_Distribution_System) server so that compatible reader apps (for example Panels, Chunky, Marvin, etc.) can browse and download comics directly from your library.

### Enabling the OPDS server

The OPDS server is disabled by default.

- Go to **Settings → General** in the Kapowarr UI.
- Enable **OPDS Server**.
- Click **Save**.

Once enabled, the root catalog is available at:

- `http://{host}:{port}/opds`

If you use a Base URL (reverse proxy), the OPDS path is appended to that base. For example, with Base URL `/kapowarr`:

- `http://example.com/kapowarr/opds`

### Authentication

The following settings control access to the OPDS server:

- **Require Authentication** (OPDS Authentication)
- **OPDS Username**
- **OPDS Password**

Behavior:

- If authentication is **enabled**, clients must use **HTTP Basic Auth**.
  - Username: value of **OPDS Username**.
  - Password: value of **OPDS Password**.
- If **OPDS Password** is left empty while authentication is enabled, Kapowarr will fall back to using the main **API Key** as the OPDS password.
  - This is mainly for backwards compatibility.
  - For security, it is recommended to set a dedicated OPDS password instead of relying on the API key.

If authentication is **disabled**, the OPDS catalog is publicly accessible to anyone who can reach the URL.

### Using OPDS in reader apps

Each reader app has its own UI, but the general steps are similar:

1. In your reader app, choose **Add OPDS Server** (sometimes called "Catalog" or "Library").
2. Use the OPDS root URL, for example:
   - `http://server:5656/opds`
3. If you enabled authentication, enter the OPDS username and password when prompted.

After connecting, you should see:

- A **root catalog** with links such as **Recent Additions** and **All Volumes**.
- Acquisition feeds listing individual issues/files that can be downloaded into the app.

If you cannot connect, check:

- That Kapowarr is reachable from the device (host, port, reverse proxy).
- That the OPDS server is enabled and saved.
- That any HTTP Basic credentials match the OPDS settings in Kapowarr.
