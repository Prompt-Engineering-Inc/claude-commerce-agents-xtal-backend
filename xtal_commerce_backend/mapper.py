"""XTAL result rows to the blueprint's ``Product`` and ``ProductDetails``, and the
blueprint's ``SearchFilters`` to an XTAL request. Every field of a row is optional: the
payload shape drifts per collection."""

from __future__ import annotations

import html
import re
from typing import Any

from shopping_agent import Product, ProductDetails, SearchFilters

from .client import SearchRequest

SHORT_DESCRIPTION_CHARS = 200
DEFAULT_CATEGORY_FACET = "category"
DEFAULT_VARIANT_TITLE = "Default Title"

_BLOCK_RE = re.compile(r"</?(?:p|br|li|div|h[1-6]|tr|ul|ol)[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_FACET_RE = re.compile(r"[^a-z0-9]+")

# Attribute keys the model already gets through a Product field.
_ATTRIBUTE_SKIPS = frozenset({"brand", "price", "currency"})


# -- text and value helpers --------------------------------------------------------


def _text(value: Any) -> str | None:
    """A string with tags removed, entities decoded, and whitespace collapsed; None when
    nothing is left."""
    if not isinstance(value, str):
        return None
    without_tags = _TAG_RE.sub("", _BLOCK_RE.sub(" ", value))
    cleaned = _SPACE_RE.sub(" ", html.unescape(without_tags)).strip()
    return cleaned or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _string(value: Any) -> str | None:
    """A scalar or a list as one display string."""
    if value is None or isinstance(value, bool):
        return None if value is None else str(value).lower()
    if isinstance(value, list):
        parts = [p for p in (_string(v) for v in value) if p]
        return ", ".join(parts) or None
    if isinstance(value, dict):
        return None
    text = _text(str(value))
    return text


def facet_value(value: str) -> str:
    """A filter value in XTAL's tag form: lower case, non-alphanumerics to hyphens."""
    return _FACET_RE.sub("-", value.strip().lower()).strip("-")


def attribute_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


# -- record fields -----------------------------------------------------------------


def product_id(record: dict[str, Any]) -> str | None:
    raw = record.get("id")
    if raw is None or raw == "":
        return None
    return str(raw)


def price_of(record: dict[str, Any]) -> float | None:
    """``price`` as a number, or the minimum of a list of prices, then the lowest variant
    price, then the numeric attribute. None when the row carries no price at all."""
    raw = record.get("price")
    if isinstance(raw, list):
        numbers = [n for n in (_number(v) for v in raw) if n is not None]
        if numbers:
            return min(numbers)
    elif (number := _number(raw)) is not None:
        return number
    variant_prices = [
        n
        for n in (
            _number(v.get("price")) for v in record.get("variants") or [] if isinstance(v, dict)
        )
        if n is not None
    ]
    if variant_prices:
        return min(variant_prices)
    numeric = record.get("numeric_product_attributes")
    if isinstance(numeric, dict):
        return _number(numeric.get("price"))
    return None


def image_of(record: dict[str, Any]) -> str | None:
    """One URL per row: ``image_url``, else ``featured_image``, else the first image."""
    for key in ("image_url", "featured_image"):
        if isinstance(record.get(key), str) and record[key].strip():
            return record[key].strip()
    images = record.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and isinstance(image.get("src"), str) and image["src"]:
                return image["src"]
            if isinstance(image, str) and image:
                return image
    return None


def attributes_of(record: dict[str, Any]) -> dict[str, str]:
    """``ui_tags`` split on the first underscore (several tags with one prefix join with
    commas), then ``product_attributes`` over them: the store's own value is the richer
    text when both name the same thing."""
    collected: dict[str, list[str]] = {}
    for tag in record.get("ui_tags") or []:
        if not isinstance(tag, str) or "_" not in tag:
            continue
        prefix, _, value = tag.partition("_")
        key, value = attribute_key(prefix), value.strip()
        if not key or not value or key in _ATTRIBUTE_SKIPS:
            continue
        values = collected.setdefault(key, [])
        if value not in values:
            values.append(value)
    attributes = {key: ", ".join(values) for key, values in collected.items()}
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict):
        for raw_key, raw_value in product_attributes.items():
            key = attribute_key(str(raw_key))
            value = _string(raw_value)
            if key and value and key not in _ATTRIBUTE_SKIPS:
                attributes[key] = value
    return attributes


def labels_of(record: dict[str, Any]) -> list[str]:
    labels = []
    if record.get("on_sale") is True:
        labels.append("sale")
    tier = record.get("price_tier")
    if isinstance(tier, str) and tier.strip():
        labels.append(tier.strip())
    return labels


def short_description_of(record: dict[str, Any]) -> str | None:
    if text := _text(record.get("function_description")):
        return text
    if text := _text(record.get("description")):
        return text[:SHORT_DESCRIPTION_CHARS]
    return None


def long_description_of(record: dict[str, Any]) -> str | None:
    return _text(record.get("enhanced_description")) or _text(record.get("description"))


def specs_of(record: dict[str, Any]) -> dict[str, str]:
    specs: dict[str, str] = {}
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict):
        for raw_key, raw_value in product_attributes.items():
            key, value = attribute_key(str(raw_key)), _string(raw_value)
            if key and value:
                specs[key] = value
    numeric = record.get("numeric_product_attributes")
    if isinstance(numeric, dict):
        for raw_key, raw_value in numeric.items():
            key = attribute_key(str(raw_key))
            if key == "price" or key in specs:
                continue
            if (number := _number(raw_value)) is not None:
                specs[key] = f"{number:g}"
    return specs


def _in_stock(record: dict[str, Any], default: bool = True) -> bool:
    available = record.get("available")
    return available if isinstance(available, bool) else default


# -- variants ------------------------------------------------------------------------


def _option_values(variant: dict[str, Any], option_names: list[str]) -> dict[str, str]:
    """A variant's option values from whichever field the collection carries: an
    ``options`` mapping, ``selected_options`` pairs, ``option1..3`` beside the family's
    option names, or a title like "M / Navy"."""
    options = variant.get("options")
    if isinstance(options, dict) and options:
        return {attribute_key(str(k)): str(v) for k, v in options.items() if v not in (None, "")}
    selected = variant.get("selected_options")
    if isinstance(selected, list) and selected:
        pairs = {}
        for entry in selected:
            if isinstance(entry, dict) and entry.get("name") and entry.get("value") is not None:
                pairs[attribute_key(str(entry["name"]))] = str(entry["value"])
        if pairs:
            return pairs
    positional = [variant.get(f"option{i}") for i in (1, 2, 3)]
    positional = [str(v) for v in positional if v not in (None, "")]
    if positional:
        names = option_names + [f"option{i}" for i in range(len(option_names) + 1, 4)]
        return dict(zip(names, positional, strict=False))
    title = variant.get("title")
    if isinstance(title, str) and title.strip() and title.strip() != DEFAULT_VARIANT_TITLE:
        parts = [part.strip() for part in title.split(" / ") if part.strip()]
        names = option_names + [f"option{i}" for i in range(len(option_names) + 1, len(parts) + 1)]
        return dict(zip(names, parts, strict=False))
    return {}


def _family_option_names(record: dict[str, Any]) -> list[str]:
    names = []
    for option in record.get("options") or []:
        if isinstance(option, dict) and option.get("name"):
            names.append(attribute_key(str(option["name"])))
        elif isinstance(option, str) and option:
            names.append(attribute_key(option))
    return names


def variants_of(record: dict[str, Any], family: Product) -> list[Product]:
    """The family's purchasable rows, one ``Product`` each, or an empty list for a plain
    product (one variant with no option values, the usual "Default Title"). A variant's id
    is the family id, a colon, and its SKU (its own id when it has none)."""
    raw = [v for v in record.get("variants") or [] if isinstance(v, dict)]
    option_names = _family_option_names(record)
    rows = [(variant, _option_values(variant, option_names)) for variant in raw]
    if len(rows) <= 1 and not any(values for _, values in rows):
        return []
    variants: list[Product] = []
    for variant, option_values in rows:
        suffix = variant.get("sku") or variant.get("id")
        if suffix in (None, ""):
            continue
        image = variant.get("image")
        if isinstance(image, dict):
            image = image.get("src")
        variants.append(
            Product(
                product_id=f"{family.product_id}:{suffix}",
                title=family.title,
                brand=family.brand,
                price=_number(variant.get("price")) or family.price,
                currency=family.currency,
                image_url=image if isinstance(image, str) and image else family.image_url,
                category=family.category,
                labels=family.labels,
                attributes=dict(family.attributes) | option_values,
                in_stock=_in_stock(variant, family.in_stock),
                short_description=family.short_description,
                option_values=option_values,
                variant_of=family.product_id,
            )
        )
    return variants


def options_of(variants: list[Product]) -> dict[str, list[str]]:
    options: dict[str, list[str]] = {}
    for variant in variants:
        for option, value in variant.option_values.items():
            values = options.setdefault(option, [])
            if value not in values:
                values.append(value)
    return options


# -- records -------------------------------------------------------------------------


def map_product(record: dict[str, Any]) -> Product | None:
    """One search row as a ``Product``; None when the row has no id or no price, since
    a product without a price cannot be shown honestly."""
    pid = product_id(record)
    price = price_of(record)
    title = _text(record.get("title")) or _text(record.get("name"))
    if pid is None or price is None or title is None:
        return None
    currency = record.get("currency")
    product = Product(
        product_id=pid,
        title=title,
        brand=_text(record.get("vendor")),
        price=price,
        currency=currency.upper() if isinstance(currency, str) and currency else "USD",
        image_url=image_of(record),
        category=_text(record.get("category")) or _text(record.get("product_type")),
        labels=labels_of(record),
        attributes=attributes_of(record),
        in_stock=_in_stock(record),
        short_description=short_description_of(record),
    )
    variants = variants_of(record, product)
    if variants:
        product.options = options_of(variants)
        sellable = [v for v in variants if v.in_stock]
        product.in_stock = bool(sellable)
        product.price = min(v.price for v in (sellable or variants))
    return product


def map_product_details(record: dict[str, Any]) -> ProductDetails | None:
    product = map_product(record)
    if product is None:
        return None
    details = ProductDetails(
        **product.model_dump(),
        long_description=long_description_of(record),
        specs=specs_of(record),
    )
    details.variants = variants_of(record, product)
    return details


# -- filters -------------------------------------------------------------------------


def build_search_request(
    query: str,
    filters: SearchFilters | None,
    limit: int,
    *,
    category_facet: str = DEFAULT_CATEGORY_FACET,
    search_context: dict[str, Any] | None = None,
    session_id: str | None = None,
    offset: int = 0,
) -> SearchRequest:
    """``category`` and ``attributes`` become ``facet_filters`` keyed by tag prefix;
    ``min_price``/``max_price`` become ``price_range``; ``sort`` becomes ``sort_by``."""
    facet_filters: dict[str, list[str]] = {}
    price_min = price_max = None
    sort_by = None
    if filters is not None:
        if filters.category:
            facet_filters[category_facet] = [facet_value(filters.category)]
        for key, value in filters.attributes.items():
            prefix = facet_value(key)
            if prefix and str(value).strip():
                facet_filters.setdefault(prefix, []).append(facet_value(str(value)))
        price_min, price_max = filters.min_price, filters.max_price
        if filters.sort != "relevance":
            sort_by = filters.sort
    return SearchRequest(
        query=query,
        limit=limit,
        offset=offset,
        facet_filters=facet_filters,
        price_min=price_min,
        price_max=price_max,
        sort_by=sort_by,
        search_context=search_context,
        session_id=session_id,
    )


def fallback_request(request: SearchRequest, filters: SearchFilters | None) -> SearchRequest | None:
    """The same search with the facet filters dropped and the category folded into the
    query text, for when the filtered search returned nothing: an attribute key XTAL has
    no tag prefix for empties the result set, and the blueprint's own reference backend
    treats these as soft filters. None when the request had no facet filters."""
    if not request.facet_filters:
        return None
    query = request.query
    if filters is not None and filters.category:
        query = f"{filters.category.strip()} {query}".strip()
    return SearchRequest(
        query=query,
        limit=request.limit,
        offset=request.offset,
        facet_filters={},
        price_min=request.price_min,
        price_max=request.price_max,
        sort_by=request.sort_by,
        search_context=None,
        session_id=request.session_id,
    )


def within_price_band(product: Product, filters: SearchFilters | None) -> bool:
    """The price band, checked again on the rows: some XTAL query paths apply
    ``price_range`` to facet counts but not to retrieval."""
    if filters is None:
        return True
    if filters.min_price is not None and product.price < filters.min_price:
        return False
    return filters.max_price is None or product.price <= filters.max_price


def apply_sort(products: list[Product], sort: str) -> list[Product]:
    """XTAL accepts ``sort_by`` and ranks by relevance; a price sort reorders the page
    it returned (a stable sort, so relevance breaks ties). ``rating`` has no data here."""
    if sort == "price_asc":
        return sorted(products, key=lambda p: p.price)
    if sort == "price_desc":
        return sorted(products, key=lambda p: -p.price)
    return list(products)
