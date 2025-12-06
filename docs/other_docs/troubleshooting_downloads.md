# Troubleshooting Download Issues

This guide covers common issues with downloads, especially when using external download clients like SABnzbd, NZBGet, or qBittorrent in Docker.

## Common Error Messages

### "SABnzbd storage path does not exist"

**Error in logs:**
```
[ERROR] SABnzbd storage path does not exist: /data/usenet/complete/comics/Batman.cbz
```

**Cause:** Kapowarr cannot find the downloaded files because the path reported by SABnzbd doesn't exist in Kapowarr's container. This happens when SABnzbd and Kapowarr run in separate Docker containers and see the same files through different paths.

**Solution:** Configure [Remote Path Mapping](../installation/docker.md#remote-path-mapping-for-external-download-clients).

### "Download has no files to move"

**Error in logs:**
```
[WARNING] Download 123 has no files to move
```

**Cause:** Usually follows the "storage path does not exist" error. Kapowarr completed the download in SABnzbd but couldn't find the files to import them.

**Solution:** Same as above - configure Remote Path Mapping.

---

## Step-by-Step: Fixing Path Issues

### 1. Verify Download Client is Working

First, confirm SABnzbd/NZBGet is successfully downloading files:

1. Open your download client's web UI
2. Check that downloads are completing successfully
3. Note the **path** where completed files are stored (e.g., `/data/usenet/complete/comics/`)

### 2. Check Kapowarr Can See the Files

SSH into your server and check if Kapowarr can access the downloaded files:

```bash
# List files in Kapowarr's download folder
docker exec kapowarr ls -la /app/temp_downloads

# Check if a specific file exists
docker exec kapowarr ls -la /app/temp_downloads/Batman.cbz
```

**If you see "No such file or directory"**, the paths aren't mapped correctly.

### 3. Configure Remote Path Mapping

!!! info "What is Remote Path Mapping?"
    Remote Path Mapping tells Kapowarr: "When SABnzbd says the file is at `/data/usenet/complete/comics/file.cbz`, actually look for it at `/app/temp_downloads/file.cbz`"

**Configuration Steps:**

1. **In Kapowarr UI**: Go to `Settings` → `Download Clients`
2. **Find your download client** in the list
3. **Scroll down** to "Remote Path Mappings" section
4. **Click "Add Remote Mapping"**
5. **Fill in**:
   - **Client**: Select your download client
   - **Remote Path**: The path from your download client's settings (e.g., `/data/usenet/complete/comics/`)
   - **Local Path**: Kapowarr's download folder path (e.g., `/app/temp_downloads/`)
6. **Click Save**

### 4. Verify the Fix

Trigger a test download and check the logs:

```bash
# Monitor Kapowarr logs for success
docker logs kapowarr --follow | grep -i "download completed"
```

**Success looks like:**
```
[INFO] Usenet download completed: /app/temp_downloads/Batman.cbz
[INFO] Postprocessing of successful download: 1
```

---

## Finding the Correct Paths

### Remote Path (Download Client's Perspective)

Check your download client's configuration:

=== "SABnzbd"
    1. Open SABnzbd web UI
    2. Go to `Settings` → `Folders`
    3. Find **"Completed Download Folder"**
    4. Copy that path (e.g., `/data/usenet/complete/comics/`)

=== "NZBGet"
    1. Open NZBGet web UI
    2. Go to `Settings` → `Paths`
    3. Find **"DestDir"**
    4. Copy that path

=== "qBittorrent"
    1. Open qBittorrent web UI
    2. Go to `Options` → `Downloads`
    3. Find **"Default Save Path"**
    4. Copy that path

### Local Path (Kapowarr's Perspective)

Look at your Kapowarr Docker configuration:

=== "Docker CLI"
    Find the line in your `docker run` command that maps the download folder:
    ```bash
    -v "/host/path:/app/temp_downloads"
    ```
    The **local path** is `/app/temp_downloads/`

=== "Docker Compose"
    Find the line in your `docker-compose.yml`:
    ```yaml
    volumes:
      - "/host/path:/app/temp_downloads"
    ```
    The **local path** is `/app/temp_downloads/`

=== "Docker Desktop"
    1. Open Docker Desktop
    2. Go to `Containers` → Find `kapowarr`
    3. Look at the **Volumes** section
    4. Find the mapping where the **Container Path** corresponds to your downloads
    5. That container path is your **local path**

---

## Advanced Troubleshooting

### Check Docker Volume Mappings

Verify that both containers are mounting the same physical location:

```bash
# Check SABnzbd's mounts
docker inspect sabnzbd | grep -A 10 Mounts

# Check Kapowarr's mounts
docker inspect kapowarr | grep -A 10 Mounts
```

Look for the **physical host path** that both containers share.

### Example Problem & Solution

**Problem:**
- Host: `/mnt/user/data/usenet/complete/comics/`
- SABnzbd container: `/mnt/user/data` → `/data`
  - SABnzbd sees: `/data/usenet/complete/comics/`
- Kapowarr container: `/mnt/user/data/usenet/complete/comics` → `/app/temp_downloads`
  - Kapowarr sees: `/app/temp_downloads/`

**When SABnzbd reports:** `/data/usenet/complete/comics/Batman.cbz`
**Kapowarr needs to find it at:** `/app/temp_downloads/Batman.cbz`

**Solution - Remote Path Mapping:**
- Remote Path: `/data/usenet/complete/comics/`
- Local Path: `/app/temp_downloads/`

### Verify Path Translation in Logs

After configuring the mapping, check logs for the translation:

```bash
docker logs kapowarr --tail 100 | grep storage_path
```

**Success looks like:**
```
[DEBUG] Download SABnzbd_nzo_abc123 storage_path: /data/usenet/complete/comics/Batman.cbz
[DEBUG] Usenet download completed: /app/temp_downloads/Batman.cbz
```

Notice how the path changed from `/data/usenet/complete/comics/` to `/app/temp_downloads/`.

---

## SABnzbd-Specific Issues

### Smart Duplicate Detection

**Symptom:** Downloads are marked as "Duplicate NZB" even after clearing queue/history.

**Cause:** SABnzbd's "Smart Duplicate Detection" uses a hash-based cache that persists for 4 days and survives queue/history clears.

**Solution:**

1. **Via Config File:**
   ```bash
   docker exec sabnzbd sed -i "s/^no_smart_dupes = [0-9]*/no_smart_dupes = 0/" /config/sabnzbd.ini
   docker restart sabnzbd
   ```

2. **Via Web UI:**
   - Settings → Switches → "Smart Duplicate Detection" → Set to `0` (Off)
   - Save and restart SABnzbd

**Why disable it?** Kapowarr has its own deduplication logic that's more appropriate for automated download management.

### Downloads Stuck as "Queued"

**Symptom:** Downloads stay in "Queued" state and never start.

**Possible Causes:**
1. SABnzbd is paused
2. No active Usenet servers configured
3. Insufficient disk space
4. SABnzbd is waiting for a schedule

**Solution:**
- Check SABnzbd web UI for any warnings/errors
- Verify Usenet server configuration
- Check disk space: `df -h`
- Check SABnzbd scheduler settings

---

## Permission Issues

### Files Download but Can't Be Moved

**Symptom:**
```
[ERROR] Permission denied: /content/Batman/Batman.cbz
```

**Cause:** Kapowarr doesn't have write permissions to the destination folder.

**Solution:**

1. **Check folder permissions:**
   ```bash
   ls -la /path/to/comics
   ```

2. **Fix permissions (Linux/Mac):**
   ```bash
   # Give read/write to everyone (not recommended for production)
   chmod -R 777 /path/to/comics

   # Better: Match the container's user (usually UID 1000)
   chown -R 1000:1000 /path/to/comics
   chmod -R 755 /path/to/comics
   ```

3. **For Docker:** Ensure the volume mapping has correct permissions
   ```bash
   docker run -v "/path/to/comics:/content:rw" ...
   ```
   The `:rw` ensures read-write access.

---

## Network Issues

### Can't Connect to SABnzbd

**Error in logs:**
```
[ERROR] Failed to connect to SABnzbd: Connection refused
```

**Solutions:**

1. **Check SABnzbd is running:**
   ```bash
   docker ps | grep sabnzbd
   ```

2. **Verify the URL in Kapowarr settings:**
   - If on same host: `http://sabnzbd:8080` (using container name)
   - If on different host: `http://192.168.1.100:8080` (using IP)
   - **Don't use** `localhost` or `127.0.0.1` from inside Docker

3. **Check Docker network:**
   ```bash
   # Both containers should be on the same network
   docker network inspect bridge
   ```

4. **Test connectivity:**
   ```bash
   docker exec kapowarr wget -qO- http://sabnzbd:8080/api?mode=version
   ```

---

## Still Having Issues?

If you're still experiencing problems:

1. **Check the logs** for specific error messages:
   ```bash
   docker logs kapowarr --tail 200
   ```

2. **Join the community:**
   - [Discord server](https://discord.gg/nMNdgG7vsE)
   - [Subreddit](https://www.reddit.com/r/kapowarr/)

3. **Report a bug:**
   - [GitHub Issues](https://github.com/Casvt/Kapowarr/issues)
   - Include logs, Docker configuration, and steps to reproduce
