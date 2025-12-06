## Built-in Clients

A list of the download clients Kapowarr has built-in. It uses these to download from multiple sources offered by GetComics. Clicking on one of them shows a window with more information and, if the client has support for it, an option to enter credentials (see below).

### Credentials

If you have an account with Mega, Kapowarr has the ability to use this account. If you provide your login credentials for the service, Kapowarr will then take advantage of the extra features that your account has access to (higher speeds and limits, usually). You can enter the credentials by clicking on the client and filling in the form.

## Torrent Clients

By adding at least one torrent client, Kapowarr is able to download torrents.

!!! warning "Using localhost in combination with a Docker container"
    If the torrent client is hosted on the host OS, and Kapowarr is running inside a Docker container, then it is not possible to use `localhost` in the base URL of the torrent client. Instead, the IP address used by the host OS must be used.

## Usenet Clients

Kapowarr can also use external Usenet download clients (for example **SABnzbd**) when combined with an indexer such as NZBHydra2.

- At least one Usenet client must be configured for Kapowarr to be able to send NZB downloads.
- Paths and permissions follow the same principles as for torrent clients (see Docker volume mapping notes above).

### SABnzbd Category

When using SABnzbd, Kapowarr can optionally send a **category** with each NZB.

- This is the value of the **SABnzbd Category** setting.
- It must match an existing category name in SABnzbd (Config → Categories).
- SABnzbd will then apply that category's folder and post-processing rules to all NZBs sent by Kapowarr.

If you leave this field empty, Kapowarr will not send a category and SABnzbd will use its default behavior.

### SABnzbd Priority

The **SABnzbd Priority** setting controls the priority of NZBs added by Kapowarr.

- The allowed values match SABnzbd's built‑in priorities (for example: `Paused`, `Low`, `Normal`, `High`, `Force`).
- Kapowarr sends this value with each NZB it adds so that SABnzbd can queue it at the desired priority level.

If you are unsure what to choose, leave it at `Normal` to follow SABnzbd's default behavior.
