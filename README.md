# HBD Inventory Watcher

A small Python watcher for HostingBy.Design dedicated-server inventory pages.

It checks configured store categories, extracts every listed server configuration, current `Available` count, monthly price and order link, then sends a detailed inventory report through the server's local `sendmail`/Postfix installation.

## Features

- Watches any number of HostingBy.Design store categories.
- Reports the exact configuration of every currently available dedicated server.
- Includes stock count, monthly price and direct order link when available.
- Sends a report on every run, even when stock did not change.
- Keeps category failures separate from genuine zero-stock results.
- Supports a print-only mode for safe testing.
- Uses only the local server for email delivery; no API key or external notification service is required.

## Requirements

- Python 3.10 or newer
- Beautiful Soup 4
- A working local `sendmail` command, typically supplied by Postfix

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-bs4 postfix
```

Alternatively, install the Python dependency with:

```bash
python3 -m pip install -r requirements.txt
```

## Installation

```bash
git clone https://github.com/takachlaszlo/hbd-inventory-watcher.git
cd hbd-inventory-watcher
chmod 700 hbd_inventory_report.py
mkdir -p ~/.config ~/.local/state
cp hbd-inventory.example.ini ~/.config/hbd-inventory.ini
chmod 600 ~/.config/hbd-inventory.ini
```

Edit the configuration:

```bash
nano ~/.config/hbd-inventory.ini
```

The default configuration path can be overridden with either:

```bash
python3 hbd_inventory_report.py --config /path/to/config.ini
```

or:

```bash
HBD_INVENTORY_CONFIG=/path/to/config.ini python3 hbd_inventory_report.py
```

## Testing

Print the report without sending email:

```bash
python3 hbd_inventory_report.py --print-only
```

Send a real report through the local Postfix installation:

```bash
python3 hbd_inventory_report.py
```

## Cron example: every six hours

```cron
23 */6 * * * /usr/bin/flock -n /tmp/hbd-inventory-report.lock /usr/bin/timeout 180s /usr/bin/python3 /home/USER/hbd-inventory-watcher/hbd_inventory_report.py >> /home/USER/.local/state/hbd-inventory-report.log 2>&1
```

Replace `USER` and the script path as needed. This runs at minute 23 of hours 00, 06, 12 and 18 in the server's timezone.

## Configuration format

Each watched category is an INI section whose name starts with `category_` and contains a display name plus a store URL:

```ini
[email]
from = HBD Inventory <hbdmail@your-host.example>
to = hbdmail

[category_canada_1gbit]
name = Canada - 1 Gbit
url = https://my.hostingby.design/index.php?rp=/store/leaseweb-canada
```

Multiple recipients can be separated by commas.

## Notes

The watcher parses the public store HTML. A future redesign of the HostingBy.Design store may require parser updates. An extraction failure is reported as an error and is not silently treated as an empty inventory.

This project is not affiliated with HostingBy.Design.
