"""The mapper against the recorded fixture, field by field, plus the hand-authored edge
cases: a price given as an array, a family with variants, HTML, a row with no price."""

from __future__ import annotations

from shopping_agent import Product, ProductDetails
from xtal_commerce_backend import map_product, map_product_details
from xtal_commerce_backend.mapper import (
    attributes_of,
    facet_value,
    image_of,
    price_of,
    short_description_of,
)

# -- the recorded flag-and-anthem row ------------------------------------------------


def test_first_recorded_row_maps_field_by_field(recorded):
    row = recorded["results"][0]
    product = map_product(row)
    assert isinstance(product, Product)
    assert product.product_id == "7793851662415"
    assert product.title == "HERO STRETCH FLANNEL SHIRT"
    assert product.brand == "Flag & Anthem Men's"
    assert product.price == 69.5
    assert product.currency == "USD"
    assert product.rating is None and product.review_count is None
    assert product.image_url == row["image_url"]
    assert product.image_url.startswith("https://cdn.shopify.com/")
    # category is null on this collection, so product_type stands in.
    assert product.category == "Long Sleeve Shirts"
    assert product.labels == ["mid"]  # not on sale; price_tier "mid"
    assert product.in_stock is True
    assert product.short_description == row["function_description"].strip()
    assert product.options == {} and product.option_values == {} and product.variant_of is None


def test_attributes_come_from_ui_tags_then_product_attributes(recorded):
    row = recorded["results"][0]
    attributes = attributes_of(row)
    # ui_tags split on the first underscore; the prefix is the key.
    assert attributes["product_type"] == "flannel-shirt"
    assert attributes["product_category"] == "mens-clothing"
    assert attributes["gender"] == "mens"
    assert attributes["season"] == "fall"
    # product_attributes override a ui_tag with the same key (material_knit -> the store's text).
    assert attributes["material"] == "stretch knit performance fabric"
    assert attributes["sleeve_length"] == "long sleeve"
    assert attributes["pocket_style"] == "dual front chest pockets"
    assert attributes["color"] == "charcoal"
    # brand travels on Product.brand, not in attributes.
    assert "brand" not in attributes


def test_several_tags_with_one_prefix_join(recorded):
    row = recorded["results"][1]
    assert set(row["ui_tags"]) >= {"feature_soft", "feature_stretchy"}
    only_tags = {k: v for k, v in row.items() if k != "product_attributes"}
    assert attributes_of(only_tags)["feature"] == "soft, stretchy"
    # The store's own list for the same key wins and joins the same way.
    assert attributes_of(row)["feature"].startswith("soft, stretchy")


def test_every_recorded_row_maps_and_keeps_its_order(recorded):
    products = [map_product(row) for row in recorded["results"]]
    assert all(isinstance(p, Product) for p in products)
    assert [p.product_id for p in products] == [str(row["id"]) for row in recorded["results"]]
    assert all(p.image_url for p in products)
    assert all(p.attributes for p in products)


def test_details_carry_the_enhanced_description_and_specs(recorded):
    row = recorded["results"][0]
    details = map_product_details(row)
    assert isinstance(details, ProductDetails)
    assert details.long_description.startswith("The Hero Stretch Flannel Shirt by Flag & Anthem")
    assert details.specs["material"] == "stretch knit performance fabric"
    assert details.specs["fit"] == "untucked"
    assert "price" not in details.specs
    # One "Default Title" variant is a plain product: no variants listed, no options.
    assert details.variants == [] and details.options == {}
    assert details.review_highlights == []


# -- hand-authored edge cases --------------------------------------------------------


def test_price_as_array_uses_the_minimum(edge_cases):
    row = edge_cases["results"][0]
    assert row["price"] == [79.0, 59.0, 69.0]
    assert price_of(row) == 59.0


def test_family_price_is_the_lowest_in_stock_variant(edge_cases):
    product = map_product(edge_cases["results"][0])
    # The 59.0 variant is out of stock, so the family shows the lowest sellable price.
    assert product.price == 69.0
    assert product.in_stock is True
    assert product.options == {"size": ["S", "M", "L"], "color": ["Navy", "Oat"]}
    assert product.has_options


def test_variants_get_their_own_ids_option_values_and_stock(edge_cases):
    details = map_product_details(edge_cases["results"][0])
    assert [v.product_id for v in details.variants] == [
        "990001:RMC-S-NVY",
        "990001:RMC-M-NVY",
        "990001:RMC-L-OAT",
    ]
    small, medium, large = details.variants
    assert small.option_values == {"size": "S", "color": "Navy"}
    assert small.price == 79.0 and small.in_stock is True
    assert medium.in_stock is False and medium.price == 59.0
    assert large.option_values == {"size": "L", "color": "Oat"}
    assert large.image_url == "https://cdn.example.test/ridge-crew-oat.jpg"
    assert small.image_url == "https://cdn.example.test/ridge-crew.jpg"
    assert all(v.variant_of == "990001" for v in details.variants)
    assert all(v.title == "Ridge Merino Crew" for v in details.variants)


def test_html_is_stripped_and_lists_join(edge_cases):
    row = edge_cases["results"][0]
    product = map_product(row)
    assert short_description_of(row) == "Midweight merino crew. Soft hand, no itch."
    assert product.attributes["care"] == "hand wash, lay flat"
    assert product.attributes["material"] == "merino-wool"
    assert product.attributes["color"] == "navy, oat"
    assert product.labels == ["sale", "premium"]
    assert product.currency == "USD"
    assert product.category == "Knitwear"
    details = map_product_details(row)
    assert details.specs["gsm"] == "260"
    assert details.specs["weight"] == "midweight"


def test_image_falls_back_through_the_fields(edge_cases):
    assert image_of(edge_cases["results"][0]) == "https://cdn.example.test/ridge-crew.jpg"
    assert image_of(edge_cases["results"][1]) == "https://cdn.example.test/beanie.jpg"
    assert image_of({"image_url": " https://a.test/x.jpg "}) == "https://a.test/x.jpg"
    assert (
        image_of({"featured_image": "https://a.test/f.jpg", "images": []}) == "https://a.test/f.jpg"
    )
    assert image_of({}) is None


def test_name_and_variant_price_stand_in_when_title_and_price_are_missing(edge_cases):
    product = map_product(edge_cases["results"][1])
    assert product.title == "Nameless Beanie"
    assert product.price == 18.5
    assert product.in_stock is False
    assert product.options == {}  # a single Default Title variant is not a family


def test_a_row_without_a_price_is_dropped_not_invented(edge_cases):
    assert map_product(edge_cases["results"][2]) is None
    assert map_product_details(edge_cases["results"][2]) is None
    assert map_product({}) is None


def test_facet_values_take_xtal_tag_form():
    assert facet_value("Navy Blue") == "navy-blue"
    assert facet_value("  Stretch / Knit ") == "stretch-knit"
    assert facet_value("navy") == "navy"
