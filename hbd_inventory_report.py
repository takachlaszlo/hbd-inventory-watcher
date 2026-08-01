#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup


DEFAULT_CONFIG_FILE = Path.home() / ".config" / "hbd-inventory.ini"
SENDMAIL = "/usr/sbin/sendmail"

STOCK_PATTERN = re.compile(r"^\s*(\d+)\s+Available\s*$", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"€\s*([0-9]+(?:[.,][0-9]{1,2})?)")


@dataclass(frozen=True)
class Product:
    name: str
    available: int
    price: str
    order_url: str


@dataclass(frozen=True)
class CategoryResult:
    name: str
    url: str
    products: list[Product]
    error: str | None = None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def resolve_config_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path).expanduser()

    env_path = os.environ.get("HBD_INVENTORY_CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    return DEFAULT_CONFIG_FILE


def load_config(path: Path) -> configparser.ConfigParser:
    if not path.exists():
        raise RuntimeError(f"Hiányzik a konfigurációs fájl: {path}")

    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding="utf-8")

    if "email" not in config:
        raise RuntimeError("Hiányzik az [email] szakasz.")

    for key in ("from", "to"):
        if not config["email"].get(key, "").strip():
            raise RuntimeError(f"Hiányzó beállítás: [email] {key}")

    category_sections = [
        section for section in config.sections() if section.startswith("category_")
    ]

    if not category_sections:
        raise RuntimeError("Nincs egyetlen figyelt kategória sem.")

    for section in category_sections:
        for key in ("name", "url"):
            if not config[section].get(key, "").strip():
                raise RuntimeError(f"Hiányzó beállítás: [{section}] {key}")

    return config


def configured_timezone(config: configparser.ConfigParser) -> ZoneInfo:
    timezone_name = config.get(
        "report",
        "timezone",
        fallback="Europe/Budapest",
    ).strip()

    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise RuntimeError(f"Ismeretlen időzóna: {timezone_name}") from error


def configured_delay(config: configparser.ConfigParser) -> float:
    raw_value = config.get(
        "report",
        "request_delay_seconds",
        fallback="3",
    ).strip()

    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(
            "A [report] request_delay_seconds értéke nem szám."
        ) from error

    if value < 0 or value > 60:
        raise RuntimeError(
            "A [report] request_delay_seconds értéke 0 és 60 között legyen."
        )

    return value


def fetch_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    try:
        with urlopen(request, timeout=40) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            page = response.read().decode(charset, errors="replace")
    except HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} válasz") from error
    except URLError as error:
        raise RuntimeError(f"Kapcsolati hiba: {error.reason}") from error

    if len(page) < 1000:
        raise RuntimeError("A letöltött oldal váratlanul rövid.")

    return page


def find_order_link(container):
    for link in container.find_all("a", href=True):
        label = normalize_text(link.get_text(" ", strip=True)).lower()
        if "order now" in label:
            return link
    return None


def find_product_container(stock_node):
    for parent in stock_node.parents:
        if getattr(parent, "name", None) in ("body", "html"):
            break

        order_links = []
        for link in parent.find_all("a", href=True):
            label = normalize_text(link.get_text(" ", strip=True)).lower()
            if "order now" in label:
                order_links.append(link)

        heading = parent.find(["h2", "h3", "h4", "h5"])

        # Prefer the smallest ancestor that contains one complete product card.
        if len(order_links) == 1 and heading is not None:
            return parent

    return None


def parse_products(page_html: str, category_url: str) -> list[Product]:
    soup = BeautifulSoup(page_html, "html.parser")
    stock_nodes = soup.find_all(string=STOCK_PATTERN)

    products: list[Product] = []
    seen: set[tuple[str, str]] = set()

    for stock_node in stock_nodes:
        stock_match = STOCK_PATTERN.match(normalize_text(str(stock_node)))
        if not stock_match:
            continue

        available = int(stock_match.group(1))
        container = find_product_container(stock_node)
        if container is None:
            continue

        heading = container.find(["h2", "h3", "h4", "h5"])
        if heading is None:
            continue

        name = normalize_text(heading.get_text(" ", strip=True))
        if not name:
            continue

        order_link = find_order_link(container)
        order_url = ""
        if order_link is not None:
            order_url = urljoin(category_url, order_link.get("href", ""))

        container_text = normalize_text(container.get_text(" ", strip=True))
        price_match = PRICE_PATTERN.search(container_text)
        price = f"€{price_match.group(1)}" if price_match else "ár nem olvasható"

        identity = (name.casefold(), order_url)
        if identity in seen:
            continue

        seen.add(identity)
        products.append(
            Product(
                name=name,
                available=available,
                price=price,
                order_url=order_url,
            )
        )

    if not products:
        page_text = normalize_text(soup.get_text(" ", strip=True)).casefold()
        if "cloudflare" in page_text:
            raise RuntimeError("Cloudflare-védelmi oldal érkezett.")

        raise RuntimeError(
            "Nem sikerült termékeket és készletértékeket felismerni."
        )

    return products


def check_category(name: str, url: str) -> CategoryResult:
    try:
        page_html = fetch_page(url)
        products = parse_products(page_html, url)
        return CategoryResult(name=name, url=url, products=products)
    except Exception as error:  # Keep one broken category from suppressing the report.
        return CategoryResult(
            name=name,
            url=url,
            products=[],
            error=str(error),
        )


def build_report(
    results: list[CategoryResult],
    checked_at: datetime,
) -> tuple[str, str]:
    available_entries = [
        (result, product)
        for result in results
        if not result.error
        for product in result.products
        if product.available > 0
    ]

    available_units = sum(product.available for _, product in available_entries)
    errors = [result for result in results if result.error]

    subject = (
        f"HBD készlet: {len(available_entries)} konfiguráció, "
        f"{available_units} szerver elérhető"
    )

    if errors:
        subject += f" – {len(errors)} ellenőrzési hiba"

    lines = [
        "HOSTINGBY.DESIGN DEDIKÁLT SZERVER KÉSZLETJELENTÉS",
        "",
        f"Ellenőrzés: {checked_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        (
            f"Összesen {len(available_entries)} elérhető konfiguráció, "
            f"{available_units} megvásárolható példány."
        ),
        "",
        "=" * 72,
        "PONTOSAN EZEK A DEDIKÁLT SZERVEREK ÉRHETŐK EL",
        "=" * 72,
        "",
    ]

    if available_entries:
        for number, (result, product) in enumerate(available_entries, start=1):
            lines.extend(
                [
                    f"{number}. {result.name}",
                    f"   Pontos konfiguráció: {product.name}",
                    f"   Elérhető készlet: {product.available} db",
                    f"   Havidíj: {product.price} / hó",
                    f"   Rendelés: {product.order_url or result.url}",
                    "",
                ]
            )
    elif errors and len(errors) == len(results):
        lines.extend(
            [
                "A készlet nem volt megbízhatóan meghatározható,",
                "mert egyik kategória ellenőrzése sem sikerült.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "A sikeresen ellenőrzött kategóriákban jelenleg",
                "egyetlen megvásárolható szerver sincs.",
                "",
            ]
        )

    lines.extend(
        [
            "=" * 72,
            "KATEGÓRIÁNKÉNTI RÉSZLETEK",
            "=" * 72,
            "",
        ]
    )

    for result in results:
        lines.append(result.name)

        if result.error:
            lines.extend(
                [
                    "  Állapot: ELLENŐRZÉSI HIBA",
                    f"  Hiba: {result.error}",
                    f"  Forrás: {result.url}",
                    "",
                ]
            )
            continue

        available = [product for product in result.products if product.available > 0]
        unavailable = [product for product in result.products if product.available == 0]
        category_units = sum(product.available for product in available)

        lines.extend(
            [
                f"  Elérhető konfigurációk: {len(available)}",
                f"  Elérhető példányok: {category_units} db",
                f"  Nem elérhető konfigurációk: {len(unavailable)}",
                f"  Összes listázott konfiguráció: {len(result.products)}",
                "",
            ]
        )

        if available:
            lines.append("  Elérhető szerverek:")
            for product in available:
                lines.extend(
                    [
                        f"  - {product.name}",
                        f"    Készlet: {product.available} db",
                        f"    Havidíj: {product.price} / hó",
                        f"    Rendelés: {product.order_url or result.url}",
                    ]
                )
            lines.append("")

        if unavailable:
            lines.append("  Jelenleg nem elérhető konfigurációk:")
            for product in unavailable:
                lines.append(f"  - {product.name} — {product.price} / hó")
            lines.append("")

        lines.extend([f"  Forrás: {result.url}", ""])

    if errors:
        lines.extend(
            [
                "FIGYELMEZTETÉS:",
                "Legalább egy kategória ellenőrzése sikertelen volt.",
                "Az érintett kategóriát a jelentés nem tekinti készlethiányosnak.",
                "",
            ]
        )

    lines.append("A jelentést a saját szerveren futó készletfigyelő készítette.")

    return subject, "\n".join(lines)


def send_email(
    config: configparser.ConfigParser,
    subject: str,
    body: str,
    timezone: ZoneInfo,
) -> None:
    if not Path(SENDMAIL).exists():
        raise RuntimeError(f"Nem található a sendmail program: {SENDMAIL}")

    from_header = config["email"]["from"].strip()
    envelope_from = parseaddr(from_header)[1]
    if not envelope_from:
        raise RuntimeError("Érvénytelen feladócím.")

    recipients = [
        recipient.strip()
        for recipient in config["email"]["to"].split(",")
        if recipient.strip()
    ]
    if not recipients:
        raise RuntimeError("Nincs megadva címzett.")

    message = EmailMessage()
    message["From"] = from_header
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Date"] = format_datetime(datetime.now(timezone))
    message.set_content(body)

    result = subprocess.run(
        [SENDMAIL, "-oi", "-f", envelope_from, *recipients],
        input=message.as_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    if result.returncode != 0:
        error_text = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "A Postfix nem vette át a levelet: "
            f"{error_text or 'ismeretlen hiba'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="HostingBy.Design dedikált szerver készletjelentés."
    )
    parser.add_argument(
        "--config",
        help="Alternatív INI konfigurációs fájl.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="A jelentés kiírása e-mail küldése nélkül.",
    )
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    timezone = configured_timezone(config)
    request_delay = configured_delay(config)

    category_sections = [
        section for section in config.sections() if section.startswith("category_")
    ]

    results: list[CategoryResult] = []

    for index, section in enumerate(category_sections):
        name = config[section]["name"].strip()
        url = config[section]["url"].strip()

        print(f"Ellenőrzés: {name} — {url}", flush=True)
        result = check_category(name, url)
        results.append(result)

        if result.error:
            print(f"HIBA: {name}: {result.error}", file=sys.stderr, flush=True)
        else:
            available_units = sum(
                product.available for product in result.products
            )
            print(
                f"Talált termékek: {len(result.products)}; "
                f"elérhető példányok: {available_units}",
                flush=True,
            )

        if index < len(category_sections) - 1 and request_delay:
            time.sleep(request_delay)

    checked_at = datetime.now(timezone)
    subject, body = build_report(results, checked_at)

    if args.print_only:
        print()
        print(subject)
        print()
        print(body)
    else:
        send_email(config, subject, body, timezone)
        print("A készletjelentés átadva a helyi Postfixnek.", flush=True)

    return 1 if any(result.error for result in results) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"VÉGZETES HIBA: {error}", file=sys.stderr)
        raise SystemExit(1)
